from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import httpx
import os
import json
from dotenv import load_dotenv

load_dotenv()

app = FastAPI()

DO_AGENT_URL = os.getenv("DO_AGENT_URL")
DO_API_KEY = os.getenv("DO_API_KEY")

class ChatRequest(BaseModel):
    message: str
    conversation_history: list = []

@app.post("/api/chat")
async def chat(request: ChatRequest):
    if not DO_AGENT_URL or not DO_API_KEY:
        raise HTTPException(status_code=500, detail="Agent not configured")

    messages = request.conversation_history + [
        {"role": "user", "content": request.message}
    ]

    async def stream_response():
        async with httpx.AsyncClient(timeout=60.0) as client:
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

                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        yield f"{line}\n\n"

    return StreamingResponse(stream_response(), media_type="text/event-stream")

app.mount("/", StaticFiles(directory="static", html=True), name="static")