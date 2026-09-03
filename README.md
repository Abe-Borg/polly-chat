# PoliCita — Chat UI

A web-based chat interface for the PoliCita political science teaching assistant, powered by a DigitalOcean Gradient AI agent backend.

## Features

- **Butter-smooth streaming** — tokens are buffered and rendered via `requestAnimationFrame` with adaptive pacing (80–600 CPS), producing a silky typewriter effect that masks network jitter
- **Automatic date/time awareness** — the backend injects the current date, time, and day of the week (Pacific Time) into every request so the agent can answer questions about schedules and due dates accurately
- **Blinking cursor** — inline `▋` cursor follows the text during streaming, disappears on completion
- **Stop generation** — abort button cancels the response mid-stream via `AbortController`; partial response is preserved
- **Deferred markdown rendering** — plain text during streaming (O(1) per frame), single full `marked.parse()` on completion (avoids O(n²) re-parsing)
- **Smart auto-scrolling** — `MutationObserver` reacts to DOM changes; `wheel`/`touch` events detect user scroll-up to pause; instant scroll during streaming, smooth on completion
- **CSS containment** — `contain: layout style paint` on message rows isolates reflow; `content-visibility: auto` on completed messages skips off-screen rendering
- **Code block copy buttons** — one-click copy with language labels on fenced code blocks
- **Dark / Light mode** — toggle in the header; persists via `localStorage`; respects system preference on first visit
- **Font size control** — cycle through small / medium / large
- **Auto-resizing textarea** — grows with content (up to 160px), Enter to send, Shift+Enter for newline
- **New conversation button** — clears history and resets the UI
- **Welcome screen** — shown on load with suggestion chips, disappears on first message
- **Mobile responsive** — layout adapts for small screens with touch scroll detection
- **Scroll anchoring** — CSS `overflow-anchor` prevents older messages from jumping when new content arrives

## Project Structure

```
polly-app/
├── main.py                      # FastAPI backend — proxies SSE stream to/from DO agent
├── static/
│   └── index.html               # Single-file frontend (HTML + CSS + JS)
├── scripts/
│   ├── deploy.sh                # Pull, install, restart, health-check, roll back on failure
│   └── export_agent_config.py   # Copies the DO agent's config into deploy/agent-config.json
├── deploy/
│   ├── polly-chat.service       # The droplet's systemd unit, version controlled
│   └── agent-config.json        # The DO agent's config (secrets redacted) — created by
│                                #   the first run of export_agent_config.py, then committed
├── .github/workflows/deploy.yml # Deploys to the droplet on every push to master
├── requirements.txt             # Python dependencies
├── .gitignore
└── .env                         # DO_AGENT_URL and DO_API_KEY (not committed)
```

## Setup

### Prerequisites
- Python 3.10+
- A DigitalOcean Gradient AI agent endpoint and API key
- Course documents uploaded to the agent's Knowledge Base (see below)

### Installation

```bash
# Clone the repo
git clone https://github.com/Abe-Borg/Polly-App.git
cd Polly-App

# Create and activate a virtual environment
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # macOS/Linux

# Install dependencies
pip install -r requirements.txt

# Create .env file
echo DO_AGENT_URL=https://your-agent-url-here > .env
echo DO_API_KEY=your-api-key-here >> .env
```

### Running

```bash
uvicorn main:app --reload
```

Open [http://localhost:8000](http://localhost:8000) in your browser.

### Setting Up Course Documents (Knowledge Base)

1. Log in to the DigitalOcean console
2. Navigate to your Gradient AI agent's settings
3. Under **Knowledge Base**, click **Add Knowledge Base**
4. Upload your course documents (syllabus PDF, assignment sheets, reading lists, etc.)
5. The platform handles chunking, embedding, and indexing automatically
6. Update the agent's system instructions to reference the knowledge base for course-specific questions

## Who owns what

This repository is one half of a two-part system. The other half is the agent's
configuration on DigitalOcean — its persona, its course documents, its model
settings. That half is not code here, but it decides how the app behaves just as
much as this code does, and most confusion about this project comes from trying
to reason about one half without seeing the other.

The rule that settles where anything belongs:

> **Does it depend on who is asking, or when? → this app.**
> **Is it identical for every student on every request? → the agent.**

| Concern | Owner | Where it lives |
|---------|-------|----------------|
| Persona, tone, refusal policy | **DO agent** | `instruction` |
| Course knowledge (syllabus, readings) | **DO agent** | Knowledge bases |
| Retrieval tuning (`k`, `retrieval_method`) | **DO agent** | Agent settings |
| Model and sampling (`model`, `temperature`, `top_p`, `max_tokens`) | **DO agent** | Agent settings |
| Content safety | **DO agent** | Guardrails |
| Regression-testing the agent's answers | **DO agent** | Evaluations |
| Current date and time | **this app** | `get_time_context()` in `main.py` |
| Conversation history | **this app** | `conversationHistory` in `static/index.html` |
| SSE transport, keep-alives, timeouts | **this app** | `_agent_sse_frames()` in `main.py` |
| Surfacing upstream errors to the student | **this app** | `_error_event()` in `main.py` |
| Markdown rendering, code blocks | **this app** | `static/index.html` |
| Theme, font size, UI preferences | **this app** | browser `localStorage` |
| Authentication, rate limiting, request logging | **nobody yet** | see [Known gaps](#known-gaps) |

The agent is stateless. Its endpoint is OpenAI-shaped chat completions: the full
`messages` array goes up on every call and tokens come back, and nothing is
retained between calls. `conversationHistory` in the browser is therefore the
only memory anywhere in the system — a page refresh is the system forgetting.

### The app never sends a system role

Because the persona belongs to the agent, `build_messages()` sends only `user`
and `assistant` turns. A client-supplied `system` message would either be
rejected by the agent or silently compete with the configured `instruction`, and
which of the two happened would not be visible from here.

Request-scoped context the platform cannot know — currently just the time — is
folded into the user turn instead. If you ever need the assistant to *behave*
differently, that change belongs in the agent's `instruction`, not here.

### Known gaps

Written down so they stay decisions rather than surprises:

- **No persistence.** History dies with the tab.
- **No authentication or rate limiting.** Anyone who can reach the app can spend
  agent budget.
- **No request logging.** Real student questions are never recorded, so the
  agent's Evaluations can only be built from prompts written by hand rather than
  from questions students actually ask.
- **Citations are discarded.** The agent emits `[[C1]]`-style markers when
  `provide_citations` is on; `parseMarkdown()` in `static/index.html` strips them
  with a regex. Setting `include_retrieval_info` on the request would also return
  the source files behind each answer.

## Architecture

The frontend is a single `index.html` file with no build step. It streams Server-Sent Events from the FastAPI backend, which proxies requests to the DigitalOcean agent's `/api/v1/chat/completions` endpoint using `httpx`.

```
Student Browser → Nginx → FastAPI (main.py)
                              │
                              ├── Injects current date/time (Pacific Time)
                              ├── Forwards to Gradient Agent endpoint
                              │
                              ▼
                    DigitalOcean Gradient Agent
                         ├── System prompt (PoliCita persona)
                         ├── Knowledge Base (syllabus, course docs)
                         └── LLM model (response generation)
```

**Key libraries:**
- **Backend:** FastAPI, httpx, python-dotenv
- **Frontend:** marked.js (CDN), DM Sans + Fraunces + JetBrains Mono (Google Fonts)

### How Date/Time Injection Works

Every request from the frontend passes through `main.py` before reaching the
Gradient agent, which prepends the current date, time, and day of the week in
Pacific Time to the user's message. This means the agent always knows "today"
without needing function calling or external APIs. It travels in the user turn
rather than as a system message, because the persona belongs to the agent — see
[Who owns what](#who-owns-what). Example injected text:

```
Current date and time: Friday, February 21, 2026, 03:45 PM PST.
Use this to answer any questions about schedules, due dates,
or time-sensitive course information.
```

### Streaming Pipeline

The streaming architecture follows a three-stage pipeline that decouples network ingestion from rendering:

```
Network (fetch reader)  →  Token Buffer (string queue)  →  rAF Renderer (DOM writes)
      fast as possible         no DOM touch                    1 write per frame
```

1. **Ingest**: The `fetch` reader consumes SSE chunks as fast as the network delivers them, parsing `data:` lines and extracting `delta.content` tokens
2. **Buffer**: Tokens are pushed into a string queue inside the pacer — no DOM writes, no re-renders
3. **Render**: A `requestAnimationFrame` loop drains the queue at an adaptive rate (80 CPS steady, ramping to 600 CPS when backlog grows), appending to a single `Text` node — one DOM write per frame

On stream completion, the pacer flushes any remaining buffer, the cursor is removed, and a single `marked.parse()` call converts the accumulated text to formatted HTML.

### How Auto-Scrolling Works

Instead of `scrollTop = scrollHeight` on every token (which forces synchronous reflow), the app uses:
- A `MutationObserver` watching `childList + subtree + characterData` to detect actual DOM changes
- `wheel` and `touchmove` events to detect user intent (scrolling up pauses auto-scroll)
- Instant scrolling during streaming (no `behavior: 'smooth'` animation queue buildup)
- A single smooth scroll on stream completion

### How Stop Generation Works

1. Each `sendMessage()` call creates a new `AbortController`
2. The fetch request receives the controller's `signal`
3. Clicking the stop button calls `controller.abort()`, which terminates the fetch stream
4. The pacer flushes remaining buffered text, and the partial response is finalized with markdown parsing
5. The backend's `httpx` streaming connection closes automatically when the client disconnects

### Backend SSE Hardening

The FastAPI backend includes headers to ensure streaming works end-to-end in production:
- `X-Accel-Buffering: no` — prevents Nginx from buffering the SSE stream into large blobs
- `Cache-Control: no-cache, no-transform` — prevents intermediary caching
- `Connection: keep-alive` — maintains the SSE connection
- Periodic `: keep-alive` SSE comment lines (every 15s of upstream silence) to survive intermediary idle timeouts. Agent output is pulled by a background task so that idle time is genuinely idle for the request handler — iterating the upstream response directly would block the handler and starve the keep-alive exactly when it is needed, letting Nginx's default 60s `proxy_read_timeout` drop a slow answer

### Nginx Configuration

If running behind Nginx, ensure your proxy config includes:

```nginx
location /api/ {
    proxy_pass http://127.0.0.1:8000;
    proxy_buffering off;
    proxy_set_header Connection '';
    proxy_http_version 1.1;
    chunked_transfer_encoding off;
}
```

## Environment Variables

| Variable              | Required | Description                                                        |
|-----------------------|----------|--------------------------------------------------------------------|
| `DO_AGENT_URL`        | yes      | Base URL of your DigitalOcean Gradient AI agent                     |
| `DO_API_KEY`          | yes      | The agent's own key. Talks to the agent; cannot read configuration. |
| `DO_MANAGEMENT_TOKEN` | no       | A DigitalOcean personal access token, read scope. Used only by `scripts/export_agent_config.py`. The app never reads it. |

`DO_API_KEY` and `DO_MANAGEMENT_TOKEN` are different credentials and are not
interchangeable — the first authenticates to the agent's inference endpoint, the
second to DigitalOcean's management API. Using one where the other is expected
produces a 401.

Both values are trimmed of surrounding whitespace on load, and a trailing slash
on `DO_AGENT_URL` is ignored. A key pasted into a control panel or an
`EnvironmentFile` frequently picks up a trailing newline, which otherwise
produces a malformed `Authorization` header and a 401 from the agent.

## Keeping the agent's configuration in git

The agent's settings live in DigitalOcean's control panel, where they cannot be
reviewed, diffed, or rolled back. `scripts/export_agent_config.py` copies them
into `deploy/agent-config.json` so a change to the agent shows up in `git diff`
alongside changes to the code.

**One-time setup.** Create a personal access token at
[cloud.digitalocean.com/account/api/tokens](https://cloud.digitalocean.com/account/api/tokens)
with read scope, and add it to `.env`:

```
DO_MANAGEMENT_TOKEN=dop_v1_...
```

**Then, from the repository root:**

```bash
venv\Scripts\python scripts\export_agent_config.py     # Windows
# venv/bin/python scripts/export_agent_config.py        # macOS/Linux/droplet
```

It finds the right agent by matching `DO_AGENT_URL` against each agent's
deployment URL. If nothing matches and the account has more than one agent, it
prints them and asks you to re-run with `--agent-uuid <uuid>`.

The script prints a summary of every setting that governs behaviour — model,
temperature, `k`, `retrieval_method`, `provide_citations`, attached knowledge
bases and guardrails, and the full `instruction` — then writes the JSON. Values
that look like credentials are replaced with their length, and fields that
change on their own (`updated_at`, indexing status, usage counters) are dropped,
so repeated exports of an unchanged agent are byte-identical and a diff only
ever shows a real change.

The first run creates `deploy/agent-config.json`; it is not in the repository
until someone with a management token runs the export, because only an account
holding the agent can produce it. Commit it once it exists.

**Run it again whenever you change the agent**, and commit the result with a
message saying what you changed and why. That file is the record of the half of this
system that is not code. Reviewing a change to the persona then works the same
way as reviewing a change to `main.py`.

> The export is read-only: it never writes to DigitalOcean. Editing
> `deploy/agent-config.json` does not change the agent — the control panel is
> still where changes are made. The file is the record, not the source.

## Deployment

Pushing to `master` deploys to the droplet. The workflow in
`.github/workflows/deploy.yml` opens an SSH session and pipes `scripts/deploy.sh`
to it, so the droplet always runs the deploy logic from the commit being
deployed. That script fetches, installs dependencies, restarts the service, and
then **verifies the result against `/api/health`** — if the app does not answer,
it rolls back to the previous commit, restarts, and fails the build with the
last 40 lines of the service log.

A deploy that leaves the app running but unable to reach the agent is reported
loudly and *not* rolled back: that is a configuration problem, and the previous
commit would fail the same way while hiding the report that identifies it.

### One-time setup

**1. Find out how the app currently runs.** On the droplet:

```bash
PORT=8000
PID=$(sudo ss -lptnH "sport = :$PORT" | grep -oP 'pid=\K[0-9]+' | head -1)
if [ -z "$PID" ]; then
  echo "nothing listening on :$PORT"
else
  echo "pid:     $PID"
  echo "command: $(tr '\0' ' ' < /proc/$PID/cmdline)"
  echo "cwd:     $(sudo readlink /proc/$PID/cwd)"
  UNIT=$(ps -o unit= -p "$PID" 2>/dev/null | tr -d ' ')
  case "$UNIT" in
    ""|-|*.scope) echo "unit:    none — started by hand, will not survive a reboot" ;;
    *)            echo "unit:    $UNIT"; sudo systemctl cat "$UNIT" ;;
  esac
fi
```

`cwd` is the working directory the process actually has, and the unit file shows
whether `WorkingDirectory` and `EnvironmentFile` are set. If `unit` comes back
empty the app was started by hand and will not survive a reboot — install
`deploy/polly-chat.service` (adjusting the user and paths first) before going
further.

**2. Give the droplet read access to this repo.** The deploy fetches from
GitHub, and the droplet's remote is HTTPS, which GitHub no longer accepts a
password for — so a fetch there prompts for credentials and fails. This is
easy to miss because it fails silently in one specific way: `git fetch` errors,
but the `git reset --hard origin/master` that follows still succeeds against the
*stale* local `origin/master` ref, so the deploy reports success while changing
nothing.

Generate a key on the droplet:

```bash
ssh-keygen -t ed25519 -C "polly-chat droplet" -f /root/.ssh/github_deploy -N ""
cat /root/.ssh/github_deploy.pub
```

Add that public key at **Settings → Deploy keys → Add deploy key** on this
repository. Leave *Allow write access* unchecked; deploys only read.

Then point SSH and the remote at it:

```bash
printf 'Host github.com\n  IdentityFile /root/.ssh/github_deploy\n  IdentitiesOnly yes\n' >> /root/.ssh/config
chmod 600 /root/.ssh/config
git -C /opt/polly-chat remote set-url origin git@github.com:Abe-Borg/polly-chat.git
ssh -T git@github.com
```

The last command should answer `Hi Abe-Borg/polly-chat! You've successfully
authenticated, but GitHub does not provide shell access.` Confirm the fetch
itself works before relying on any of this:

```bash
git -C /opt/polly-chat fetch origin master && echo "fetch OK"
```

**3. Create a deploy key for GitHub Actions to reach the droplet.** This is a
second, separate key, in the opposite direction: step 2 lets the droplet read
from GitHub, this one lets GitHub Actions log in to the droplet. On your
machine:

```bash
ssh-keygen -t ed25519 -C "github-actions-deploy" -f ~/.ssh/polly_deploy -N ""
ssh-copy-id -i ~/.ssh/polly_deploy.pub root@your.droplet.ip
```

**4. If you deploy as a non-root user, let it restart the service without a
password.** Skip this entirely when the SSH user is `root`. Otherwise, on the
droplet with `sudo visudo -f /etc/sudoers.d/polly-chat-deploy` (confirm the
paths with `command -v systemctl journalctl`):

```
youruser ALL=(root) NOPASSWD: /usr/bin/systemctl restart polly-chat, /usr/bin/journalctl -u polly-chat *
```

**5. Add the repository secrets and variables** under Settings → Secrets and
variables → Actions:

| Kind     | Name               | Value                                            |
|----------|--------------------|--------------------------------------------------|
| Secret   | `DROPLET_SSH_KEY`  | Contents of `~/.ssh/polly_deploy` (private key)   |
| Secret   | `DROPLET_HOST`     | Droplet IP or hostname                           |
| Secret   | `DROPLET_USER`     | SSH user — `root` on the current droplet         |
| Variable | `APP_DIR`          | `/opt/polly-chat`                                |
| Variable | `SERVICE_NAME`     | `polly-chat`                                     |

`APP_DIR` and `SERVICE_NAME` match the defaults baked into `scripts/deploy.sh`,
so they are only strictly needed if the droplet ever changes.

**6. Confirm the droplet's checkout tracks this repo** — the script deploys with
`git fetch` and `git reset --hard`, so the app directory has to be a clone with
an `origin` remote:

```bash
git -C /opt/polly-chat remote -v
```

If that reports no remote, the code was copied up rather than cloned. Turn it
into a clone before the first deploy — `.env` is untracked and survives:

```bash
cd /opt/polly-chat
git init -b master
git remote add origin https://github.com/Abe-Borg/polly-chat.git
git fetch origin master
git reset --hard origin/master
```

Then run the workflow once from the Actions tab (**Deploy to droplet** → Run
workflow) to prove the path end to end before relying on it.

### Deploying by hand

The same script runs standalone on the droplet, which is useful when you want a
deploy without a push:

```bash
cd /opt/polly-chat && bash scripts/deploy.sh
```

### Why `reset --hard` and not `pull`

The droplet is a deployment target, not a workspace. A stray edit made while
debugging would turn the next `git pull` into a merge conflict at the worst
possible moment; resetting to `origin/master` makes the deploy deterministic.
`.env` is gitignored, so it is never touched.

## Troubleshooting

### `/api/health`

Deployments fail differently than local runs, usually because the process never
received the environment. `GET /api/health` reports what the running process
actually loaded, and reveals no secret material, so it is safe to curl against
a live deployment:

```bash
curl -s https://your-host/api/health | python -m json.tool
```

```json
{
  "agent_url_configured": true,
  "agent_url": "https://your-agent.ondigitalocean.app",
  "api_key_configured": true,
  "api_key": { "length": 64, "sha256_prefix": "9b5192e64b0d" },
  "api_key_had_surrounding_whitespace": false,
  "agent_reachable": true,
  "agent_status_code": 200
}
```

Read it as follows:

- **`api_key_configured: false`** — the process never loaded `.env`. Under
  systemd this is almost always a missing `WorkingDirectory` or
  `EnvironmentFile`; `load_dotenv()` only finds `.env` relative to the working
  directory.
- **`api_key_had_surrounding_whitespace: true`** — the key is being sent with a
  stray newline or space. It is now trimmed automatically, but the source value
  is worth cleaning up.
- **`api_key.sha256_prefix`** — confirm the deployment holds the key you think
  it does, without exposing it, by comparing against your own copy:
  `printf %s "$DO_API_KEY" | sha256sum | cut -c1-12`
- **`agent_reachable: false`** — the process cannot reach the agent.
  `agent_detail` carries the status code and response body; a 401 means the key
  is wrong or expired, and a connection error usually means egress is blocked.

### The chat returns nothing

Upstream failures are delivered to the browser as an SSE error frame and
rendered in the transcript, and the full upstream body is logged server-side
(`journalctl -u your-service -f`) and written to the browser console. A
response that is empty with no error at all points at the connection being cut
between the browser and the app rather than at the agent — check the Nginx
config below.

### When systemd supplies the environment

The unit sets both `WorkingDirectory` and `EnvironmentFile`, so `.env` is read
twice: once by systemd, once by `load_dotenv()`. **systemd wins.** `load_dotenv()`
defaults to `override=False` and will not replace a variable that is already
set, so the value the app sees is systemd's parse of the file, not dotenv's.

The two parsers do not agree on everything, and the difference bites when `.env`
was written on Windows. A CRLF file gives systemd a trailing carriage return in
the value, producing an `Authorization: Bearer <key>\r` header and a 401 from a
key that is otherwise perfectly valid. Check without printing the key:

```bash
sudo grep -c $'\r' /opt/polly-chat/.env    # any non-zero result is this bug
```

Fix it in place, then restart:

```bash
sudo sed -i 's/\r$//' /opt/polly-chat/.env
sudo systemctl restart polly-chat
```

The backend strips surrounding whitespace from both values on load, so this is
handled either way, and `/api/health` reports
`api_key_had_surrounding_whitespace: true` when it had to.

To confirm what the running process actually received, without exposing it:

```bash
sudo tr '\0' '\n' < /proc/$(systemctl show -p MainPID --value polly-chat)/environ \
  | grep -E '^DO_' | sed 's/=.*/=<set>/'
```

### The agent rejects something the app sent

The app sends only `user` and `assistant` turns, so a 4xx naming a role or
message is not a system-role rejection — earlier versions of this app sent a
leading `system` message and retried once without it, and that retry is gone.
Look instead at the conversation history the browser sent: it is not validated
or capped, so a malformed entry or a history long enough to exceed the model's
context window reaches the agent as-is. `agent_detail` in the error frame
carries the agent's own explanation.