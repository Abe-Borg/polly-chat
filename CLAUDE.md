# CLAUDE.md

Guidance for working in this repository.

## What this is

A FastAPI app that serves a single-page chat UI and proxies its requests to a
DigitalOcean Gradient AI agent. It is a teaching assistant for a political
science course, used by students.

- `main.py` — the whole backend, ~230 lines. Proxies SSE, injects time, reports health.
- `static/index.html` — the whole frontend. No build step, no framework.
- `scripts/deploy.sh` — deploys to the droplet; run over SSH by the GitHub Actions workflow.
- `scripts/export_agent_config.py` — copies the DO agent's config into
  `deploy/agent-config.json`, which that script creates on its first run.

## The two halves — read this before changing behaviour

This repo is one half of the system. The other half is the agent's
configuration on DigitalOcean: its `instruction` (persona), knowledge bases,
model, sampling settings, retrieval tuning, and guardrails. `README.md` →
"Who owns what" has the full ownership table. The rule:

> Depends on who is asking or when → this app.
> Identical for every student on every request → the agent.

**Before changing how the assistant talks, sounds, or refuses, stop.** That is
the agent's `instruction`, not this code. Read `deploy/agent-config.json` to see
what it currently says — and if that file is not present, it means nobody has
run `scripts/export_agent_config.py` yet, so the agent's half of the system is
still unrecorded. Changing the persona means changing it in the DigitalOcean
control panel and re-running the export.

## Invariants — do not break these without a deliberate decision

1. **Never send a `system` role.** `build_messages()` sends only `user` and
   `assistant` turns. The agent owns the persona; a client-supplied system
   message would be rejected or would silently compete with the configured
   `instruction`. Request-scoped context goes in the user turn.

2. **The keep-alive interval is measured from the last write to the client, not
   from the last line the agent sent.** An agent that emits its own SSE comments
   would otherwise reset the timer on lines that are dropped, and nothing would
   reach the browser. See `_agent_sse_frames()`.

3. **Agent lines are pulled by a background task.** Iterating the upstream
   response directly in the handler would block it and starve the keep-alive
   exactly when it is needed, letting Nginx's 60s `proxy_read_timeout` drop a
   slow answer mid-sentence.

4. **`/api/health` must never expose secret material.** It is public and safe to
   curl on a live deployment. Keys are reported as a length and a SHA-256 prefix.

5. **`deploy/agent-config.json` is a record, not a source.** Editing it changes
   nothing. Change the agent in the control panel, then re-run the export.

## Commands

```bash
# Run locally (Windows)
venv\Scripts\activate
uvicorn main:app --reload

# Export the agent's configuration after changing it in DO's control panel
venv\Scripts\python scripts\export_agent_config.py

# Deploy: push to master. The workflow SSHes to the droplet and pipes
# scripts/deploy.sh to it. To deploy by hand, on the droplet:
cd /opt/polly-chat && bash scripts/deploy.sh

# Check a live deployment
curl -s https://your-host/api/health | python -m json.tool
```

## Environment

`DO_AGENT_URL` and `DO_API_KEY` are required by the app. `DO_MANAGEMENT_TOKEN`
is a *different* credential — a DigitalOcean personal access token — used only
by the export script. They are not interchangeable.

Both app values are stripped of surrounding whitespace on load, because a key
pasted into an `EnvironmentFile` frequently carries a trailing newline that
produces a malformed `Authorization` header and a 401.

## Known gaps

Real, and deliberately not yet fixed. Do not treat any of these as a bug you
have just discovered:

- Agent output is rendered with `marked` into `innerHTML` with no sanitizer.
- `marked` is loaded unpinned from a CDN.
- `conversation_history` is accepted from the client unvalidated and uncapped.
- `/api/health` makes a billable agent call on every request and is unauthenticated.
- Only `httpx.HTTPError` is caught around the stream; other exceptions escape
  without an error frame.
- History lives only in a browser variable, so a refresh loses the conversation.
- No authentication, rate limiting, or request logging.
- Citations from the agent are stripped by a regex in `parseMarkdown()`.

## Conventions

- Comments explain *why*, especially where the code looks odd on purpose. The
  keep-alive timing and the absent system role both look wrong without their
  reasons; keep those reasons attached to the code.
- No build step for the frontend, and no framework. Keep it that way unless
  there is a reason that survives being written down here.
- Update `README.md` when behaviour changes, and `requirements.txt` when
  dependencies change.
