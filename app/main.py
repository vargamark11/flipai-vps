import os
import httpx
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse

app = FastAPI(title="FlipAI API", version="1.0.0")

PUBLIC_API_KEY = os.environ["FLIPAI_PUBLIC_API_KEY"]
INTERNAL_API_KEY = os.environ["FLIPAI_INTERNAL_API_KEY"]
LLAMA_URL = os.environ.get("LLAMA_URL", "http://127.0.0.1:8080/v1/chat/completions")
MODEL_ALIAS = os.environ.get("FLIPAI_MODEL_ALIAS", "flipai-v1")

SYSTEM_PROMPT = """You are FlipAI, a fast, practical and helpful AI assistant.
Answer in the same language as the user unless they request otherwise.
Be clear, direct and concise by default.
Do not claim capabilities you do not have.
"""

def require_auth(authorization: str | None):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing API key")
    token = authorization.removeprefix("Bearer ").strip()
    if token != PUBLIC_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")

@app.get("/health")
async def health():
    return {"status": "ok", "service": "flipai-api", "model": MODEL_ALIAS}

@app.get("/v1/models")
async def models(authorization: str | None = Header(default=None)):
    require_auth(authorization)
    return {
        "object": "list",
        "data": [{
            "id": MODEL_ALIAS,
            "object": "model",
            "owned_by": "flipai"
        }]
    }

@app.post("/v1/chat/completions")
async def chat(request: Request, authorization: str | None = Header(default=None)):
    require_auth(authorization)
    payload = await request.json()

    messages = payload.get("messages")
    if not isinstance(messages, list) or not messages:
        raise HTTPException(status_code=400, detail="messages is required")

    clean_messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for m in messages:
        if isinstance(m, dict) and m.get("role") in {"user", "assistant", "system"}:
            clean_messages.append({
                "role": m["role"],
                "content": str(m.get("content", ""))
            })

    upstream = {
        "model": MODEL_ALIAS,
        "messages": clean_messages,
        "temperature": payload.get("temperature", 0.7),
        "max_tokens": payload.get("max_tokens", 512),
        "stream": False
    }

    headers = {
        "Authorization": f"Bearer {INTERNAL_API_KEY}",
        "Content-Type": "application/json"
    }

    try:
        async with httpx.AsyncClient(timeout=180.0) as client:
            response = await client.post(LLAMA_URL, json=upstream, headers=headers)
    except httpx.RequestError as exc:
        raise HTTPException(status_code=502, detail=f"Model backend unavailable: {exc}") from exc

    try:
        data = response.json()
    except ValueError:
        raise HTTPException(status_code=502, detail="Invalid response from model backend")

    return JSONResponse(content=data, status_code=response.status_code)
