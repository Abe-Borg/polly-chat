from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import httpx
import os
import json
import asyncio
import hashlib
import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("policita")

app = FastAPI()

# Values set through a hosting control panel or an EnvironmentFile often carry a
# trailing newline or space, and a trailing slash on the URL would produce a
# double slash in the agent path. Normalise both here rather than at every use.
_RAW_AGENT_URL = os.getenv("DO_AGENT_URL") or ""
_RAW_API_KEY = os.getenv("DO_API_KEY") or ""
DO_AGENT_URL = _RAW_AGENT_URL.strip().rstrip("/")
DO_API_KEY = _RAW_API_KEY.strip()

AGENT_PATH = "/api/v1/chat/completions"
KEEPALIVE_INTERVAL = 15.0


def get_time_context() -> str:
    """Generate a current date/time context string in Pacific Time."""
    try:
        now = datetime.now(ZoneInfo("America/Los_Angeles"))
    except ZoneInfoNotFoundError:
        # Slim container images ship without the IANA database. Degrade to UTC
        # instead of failing the whole request.
        logger.warning("Timezone data unavailable; falling back to UTC")
        now = datetime.now(timezone.utc)
    day_name = now.strftime("%A")
    date_str = now.strftime("%B %d, %Y")
    time_str = now.strftime("%I:%M %p %Z")
    return (
        f"Current date and time: {day_name}, {date_str}, {time_str}. "
        "Use this to answer any questions about schedules, due dates, "
        "or time-sensitive course information."
    )


class ChatRequest(BaseModel):
    message: str
    conversation_history: list = []


def build_messages(request: "ChatRequest", inline_time: bool) -> list:
    """Assemble the outgoing message list.

    Normally the time context rides as a leading system message. When the agent
    rejects a client-supplied system role, `inline_time` folds the same context
    into the user turn instead.
    """
    time_context = get_time_context()
    if inline_time:
        return request.conversation_history + [
            {"role": "user", "content": f"{time_context}\n\n{request.message}"}
        ]
    return (
        [{"role": "system", "content": time_context}]
        + request.conversation_history
        + [{"role": "user", "content": request.message}]
    )


def _is_role_rejection(status_code: int, body: str) -> bool:
    """Does this look like the agent refusing the system role we sent?"""
    if status_code not in (400, 422):
        return False
    lowered = body.lower()
    return "role" in lowered or "system" in lowered


def _error_event(message: str, detail: str = "") -> str:
    """SSE frame the frontend renders as a visible error."""
    return f"data: {json.dumps({'error': message, 'detail': detail})}\n\n"


async def _agent_sse_frames(response):
    """Yield SSE frames from the agent, emitting a keep-alive comment whenever
    the agent goes quiet for KEEPALIVE_INTERVAL seconds.

    Lines are pulled by a background task so idle time is genuinely idle for us.
    Iterating the response directly would block here and starve the keep-alive,
    letting an intermediary proxy time the connection out mid-answer.
    """
    queue: asyncio.Queue = asyncio.Queue()
    done = object()

    async def pump():
        try:
            async for line in response.aiter_lines():
                await queue.put(line)
        except Exception as exc:  # surfaced to the caller below
            await queue.put(exc)
        else:
            await queue.put(done)

    pump_task = asyncio.create_task(pump())
    try:
        while True:
            try:
                item = await asyncio.wait_for(queue.get(), timeout=KEEPALIVE_INTERVAL)
            except asyncio.TimeoutError:
                yield ": keep-alive\n\n"
                continue

            if item is done:
                return
            if isinstance(item, Exception):
                raise item
            if item.startswith("data: "):
                yield f"{item}\n\n"
    finally:
        pump_task.cancel()


@app.post("/api/chat")
async def chat(request: ChatRequest):
    if not DO_AGENT_URL or not DO_API_KEY:
        raise HTTPException(status_code=500, detail="Agent not configured")

    async def stream_response():
        headers = {
            "Authorization": f"Bearer {DO_API_KEY}",
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=15.0)) as client:
            # Second pass retries without a system role if the agent rejects one.
            for inline_time in (False, True):
                messages = build_messages(request, inline_time)
                try:
                    async with client.stream(
                        "POST",
                        f"{DO_AGENT_URL}{AGENT_PATH}",
                        headers=headers,
                        json={"messages": messages, "stream": True},
                    ) as response:
                        if response.status_code != 200:
                            body = (await response.aread()).decode(errors="replace")
                            if not inline_time and _is_role_rejection(response.status_code, body):
                                logger.warning(
                                    "Agent rejected the system role (HTTP %s); "
                                    "retrying with the time context inline",
                                    response.status_code,
                                )
                                continue
                            logger.error(
                                "Agent returned HTTP %s: %s", response.status_code, body[:500]
                            )
                            yield _error_event(
                                f"The agent returned HTTP {response.status_code}.", body[:500]
                            )
                            return

                        async for frame in _agent_sse_frames(response):
                            yield frame
                        return

                except httpx.HTTPError as exc:
                    logger.exception("Request to the agent failed")
                    yield _error_event(
                        "Could not reach the agent.", f"{type(exc).__name__}: {exc}"
                    )
                    return

    return StreamingResponse(
        stream_response(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


def _key_fingerprint(secret: str):
    """Identify a key without revealing it.

    Compare against `printf %s "$DO_API_KEY" | sha256sum` locally to confirm the
    deployment is using the key you think it is.
    """
    if not secret:
        return None
    return {
        "length": len(secret),
        "sha256_prefix": hashlib.sha256(secret.encode()).hexdigest()[:12],
    }


@app.get("/api/health")
async def health():
    """Report configuration and agent reachability.

    Exposes no secret material, so it is safe to curl on a live deployment.
    """
    report = {
        "agent_url_configured": bool(DO_AGENT_URL),
        "agent_url": DO_AGENT_URL or None,
        "api_key_configured": bool(DO_API_KEY),
        "api_key": _key_fingerprint(DO_API_KEY),
        "api_key_had_surrounding_whitespace": _RAW_API_KEY != _RAW_API_KEY.strip(),
        "agent_url_had_surrounding_whitespace": _RAW_AGENT_URL != _RAW_AGENT_URL.strip(),
        "time_context": get_time_context(),
    }

    if not (DO_AGENT_URL and DO_API_KEY):
        report["agent_reachable"] = False
        report["agent_detail"] = "Skipped: DO_AGENT_URL and/or DO_API_KEY is missing."
        return report

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=15.0)) as client:
            response = await client.post(
                f"{DO_AGENT_URL}{AGENT_PATH}",
                headers={
                    "Authorization": f"Bearer {DO_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={"messages": [{"role": "user", "content": "ping"}], "stream": False},
            )
        report["agent_reachable"] = response.status_code == 200
        report["agent_status_code"] = response.status_code
        if response.status_code != 200:
            report["agent_detail"] = response.text[:500]
    except httpx.HTTPError as exc:
        report["agent_reachable"] = False
        report["agent_detail"] = f"{type(exc).__name__}: {exc}"

    return report


app.mount("/", StaticFiles(directory="static", html=True), name="static")
