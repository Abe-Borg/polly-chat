# PoliCita — Chat UI

A web-based chat interface for the PoliCita political science teaching assistant, powered by a DigitalOcean Gradient AI agent backend.

## Features

- **Streaming responses** — tokens render in real-time as the agent generates them
- **Stop generation** — abort button to cancel a response mid-stream (uses `AbortController`)
- **Markdown rendering** — powered by `markdown-it` for robust handling of partial/streaming markdown (headings, lists, bold, italic, tables, blockquotes, code blocks)
- **Code block copy buttons** — one-click copy with language labels on fenced code blocks
- **Dark / Light mode** — toggle in the header; persists via `localStorage`; respects system preference on first visit
- **Auto-resizing textarea** — multi-line input that grows with content (up to 160px), send with Enter, newline with Shift+Enter
- **New conversation button** — clears history and resets the UI
- **Welcome screen** — shown on load, disappears on first message
- **Mobile responsive** — layout adapts for small screens
- **Smooth scrolling** — chat auto-scrolls as tokens arrive

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
- **Frontend:** markdown-it (CDN), DM Sans + Instrument Serif + JetBrains Mono (Google Fonts)

### How Stop Generation Works

1. Each `sendMessage()` call creates a new `AbortController`
2. The fetch request receives the controller's `signal`
3. Clicking the stop button calls `controller.abort()`, which terminates the fetch stream
4. The partial response already rendered in the DOM is preserved
5. The backend's `httpx` streaming connection closes automatically when the client disconnects

### How Markdown Streaming Works

Previous version used `marked.js` which would produce broken HTML when parsing incomplete markdown mid-stream. The new version uses `markdown-it` which handles partial input more gracefully. The full accumulated text is re-parsed on each token, and code blocks are post-processed to inject copy buttons and language labels.

## Environment Variables

| Variable       | Description                                      |
|----------------|--------------------------------------------------|
| `DO_AGENT_URL` | Base URL of your DigitalOcean Gradient AI agent  |
| `DO_API_KEY`   | API key for authenticating with the agent         |