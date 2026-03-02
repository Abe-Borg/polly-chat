from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import httpx
import os
import json
import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo
from dotenv import load_dotenv

load_dotenv()

app = FastAPI()

DO_AGENT_URL = os.getenv("DO_AGENT_URL")
DO_API_KEY = os.getenv("DO_API_KEY")


def get_time_context() -> str:
    """Generate a current date/time context string in Pacific Time."""
    now = datetime.now(ZoneInfo("America/Los_Angeles"))
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


@app.post("/api/chat")
async def chat(request: ChatRequest):
    if not DO_AGENT_URL or not DO_API_KEY:
        raise HTTPException(status_code=500, detail="Agent not configured")

    # Inject current date/time as a system message at the front
    time_context = {"role": "system", "content": get_time_context()}

    messages = [time_context] + request.conversation_history + [
        {"role": "user", "content": request.message}
    ]

    async def stream_response():
        async with httpx.AsyncClient(timeout=120.0) as client:
            async with client.stream(
                "POST",
                f"{DO_AGENT_URL}/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {DO_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "messages": messages,
                    "stream": True,
                },
            ) as response:
                if response.status_code != 200:
                    error = await response.aread()
                    yield f"data: {json.dumps({'error': error.decode()})}\n\n"
                    return

                # Track time since last data for keep-alive
                last_yield = asyncio.get_event_loop().time()

                async for line in response.aiter_lines():
                    now = asyncio.get_event_loop().time()

                    # Send SSE keep-alive comment if 15s have passed without data
                    if now - last_yield > 15.0:
                        yield ": keep-alive\n\n"

                    if line.startswith("data: "):
                        yield f"{line}\n\n"
                        last_yield = now

    return StreamingResponse(
        stream_response(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


app.mount("/", StaticFiles(directory="static", html=True), name="static")