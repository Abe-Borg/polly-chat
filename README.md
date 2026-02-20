# PoliCita — Chat UI

A web-based chat interface for the PoliCita political science teaching assistant, powered by a DigitalOcean Gradient AI agent backend.

## Features

- **Butter-smooth streaming** — tokens are buffered and rendered via `requestAnimationFrame` with adaptive pacing (80–600 CPS), producing a silky typewriter effect that masks network jitter
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
├── main.py              # FastAPI backend — proxies SSE stream to/from DO agent
├── static/
│   └── index.html       # Single-file frontend (HTML + CSS + JS)
├── requirements.txt     # Python dependencies
├── .gitignore
└── .env                 # DO_AGENT_URL and DO_API_KEY (not committed)
```

## Setup

### Prerequisites
- Python 3.10+
- A DigitalOcean Gradient AI agent endpoint and API key

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

## Architecture

The frontend is a single `index.html` file with no build step. It streams Server-Sent Events from the FastAPI backend, which proxies requests to the DigitalOcean agent's `/api/v1/chat/completions` endpoint using `httpx`.

**Key libraries:**
- **Backend:** FastAPI, httpx, python-dotenv
- **Frontend:** marked.js (CDN), DM Sans + Fraunces + JetBrains Mono (Google Fonts)

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
- Periodic `: keep-alive` SSE comment lines (every 15s) to survive intermediary idle timeouts

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

| Variable       | Description                                      |
|----------------|--------------------------------------------------|
| `DO_AGENT_URL` | Base URL of your DigitalOcean Gradient AI agent  |
| `DO_API_KEY`   | API key for authenticating with the agent         |