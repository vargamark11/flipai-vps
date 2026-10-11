import hashlib
import json
import os
import secrets
import uuid

import asyncpg
import httpx
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

app = FastAPI(title="FlipAI API", version="1.4.0")

PUBLIC_API_KEY = os.environ["FLIPAI_PUBLIC_API_KEY"]
INTERNAL_API_KEY = os.environ["FLIPAI_INTERNAL_API_KEY"]
LLAMA_URL = os.environ.get("LLAMA_URL", "http://127.0.0.1:8080/v1/chat/completions")
MODEL_ALIAS = os.environ.get("FLIPAI_MODEL_ALIAS", "flipai-v1")
DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://flipai:flipai@127.0.0.1:5432/flipai")
MEMORY_LIMIT = int(os.environ.get("FLIPAI_MEMORY_LIMIT", "20"))
STARTING_CREDITS = int(os.environ.get("FLIPAI_STARTING_CREDITS", "5000"))
REQUESTS_PER_MINUTE = int(os.environ.get("FLIPAI_REQUESTS_PER_MINUTE", "20"))

SYSTEM_PROMPT = """You are FlipAI, a fast, practical and helpful AI assistant.
Answer in the same language as the user unless they request otherwise.
Be clear, direct and concise by default.
Do not claim capabilities you do not have.
"""

pool: asyncpg.Pool | None = None


def hash_key(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


async def authenticate(authorization: str | None) -> dict:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing API key")

    token = authorization.removeprefix("Bearer ").strip()
    if token == PUBLIC_API_KEY:
        return {"type": "admin", "user_id": None, "name": "admin"}

    if pool is None:
        raise HTTPException(status_code=503, detail="Database unavailable")

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, name, credits FROM users WHERE api_key_hash=$1",
            hash_key(token),
        )

    if not row:
        raise HTTPException(status_code=401, detail="Invalid API key")

    return {
        "type": "user",
        "user_id": row["id"],
        "name": row["name"],
        "credits": row["credits"],
    }


def require_admin(auth: dict):
    if auth["type"] != "admin":
        raise HTTPException(status_code=403, detail="Admin API key required")


@app.on_event("startup")
async def startup():
    global pool
    pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=5)
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id UUID PRIMARY KEY,
                name TEXT NOT NULL,
                api_key_hash TEXT NOT NULL UNIQUE,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
        await conn.execute(
            f"ALTER TABLE users ADD COLUMN IF NOT EXISTS credits BIGINT NOT NULL DEFAULT {STARTING_CREDITS}"
        )
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS conversations (
                id UUID PRIMARY KEY,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
        await conn.execute("ALTER TABLE conversations ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES users(id) ON DELETE CASCADE")
        await conn.execute("ALTER TABLE conversations ADD COLUMN IF NOT EXISTS title TEXT NOT NULL DEFAULT 'New chat'")
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id BIGSERIAL PRIMARY KEY,
                conversation_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                role TEXT NOT NULL CHECK (role IN ('user','assistant','system')),
                content TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS usage_events (
                id BIGSERIAL PRIMARY KEY,
                user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                conversation_id UUID REFERENCES conversations(id) ON DELETE SET NULL,
                prompt_tokens INTEGER NOT NULL DEFAULT 0,
                completion_tokens INTEGER NOT NULL DEFAULT 0,
                total_tokens INTEGER NOT NULL DEFAULT 0,
                credits_used BIGINT NOT NULL DEFAULT 0,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS request_events (
                id BIGSERIAL PRIMARY KEY,
                user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_conversation_id_id ON messages(conversation_id, id)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_conversations_user_updated ON conversations(user_id, updated_at DESC)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_usage_user_created ON usage_events(user_id, created_at DESC)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_requests_user_created ON request_events(user_id, created_at DESC)")


@app.on_event("shutdown")
async def shutdown():
    global pool
    if pool is not None:
        await pool.close()


@app.get("/health")
async def health():
    db_ok = False
    if pool is not None:
        try:
            async with pool.acquire() as conn:
                db_ok = await conn.fetchval("SELECT 1") == 1
        except Exception:
            db_ok = False
    return {
        "status": "ok" if db_ok else "degraded",
        "service": "flipai-api",
        "model": MODEL_ALIAS,
        "database": db_ok,
        "version": "1.4.0",
    }


@app.get("/v1/models")
async def models(authorization: str | None = Header(default=None)):
    await authenticate(authorization)
    return {"object": "list", "data": [{"id": MODEL_ALIAS, "object": "model", "owned_by": "flipai"}]}


@app.post("/v1/admin/users")
async def create_user(request: Request, authorization: str | None = Header(default=None)):
    auth = await authenticate(authorization)
    require_admin(auth)
    payload = await request.json()
    name = str(payload.get("name", "")).strip()
    if not name:
        raise HTTPException(status_code=400, detail="name is required")

    requested_credits = payload.get("credits", STARTING_CREDITS)
    try:
        credits = max(0, int(requested_credits))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="credits must be an integer")

    user_id = uuid.uuid4()
    raw_key = "flipai_user_" + secrets.token_hex(32)
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO users(id, name, api_key_hash, credits) VALUES($1,$2,$3,$4)",
            user_id,
            name,
            hash_key(raw_key),
            credits,
        )

    return {"id": str(user_id), "name": name, "credits": credits, "api_key": raw_key}


@app.get("/v1/admin/users")
async def list_users(authorization: str | None = Header(default=None)):
    auth = await authenticate(authorization)
    require_admin(auth)
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT id, name, credits, created_at FROM users ORDER BY created_at DESC")
    return {
        "data": [
            {
                "id": str(r["id"]),
                "name": r["name"],
                "credits": r["credits"],
                "created_at": r["created_at"].isoformat(),
            }
            for r in rows
        ]
    }


@app.post("/v1/admin/users/{user_id}/credits")
async def add_credits(user_id: str, request: Request, authorization: str | None = Header(default=None)):
    auth = await authenticate(authorization)
    require_admin(auth)
    try:
        uid = uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid user_id")

    payload = await request.json()
    try:
        amount = int(payload.get("amount", 0))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="amount must be an integer")
    if amount == 0:
        raise HTTPException(status_code=400, detail="amount must not be zero")

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "UPDATE users SET credits=GREATEST(0, credits+$2) WHERE id=$1 RETURNING credits",
            uid,
            amount,
        )
    if not row:
        raise HTTPException(status_code=404, detail="User not found")
    return {"user_id": str(uid), "credits": row["credits"]}


@app.get("/v1/account/credits")
async def account_credits(authorization: str | None = Header(default=None)):
    auth = await authenticate(authorization)
    if auth["type"] == "admin":
        return {"type": "admin", "credits": None, "unit": "1 credit = 1 token"}
    async with pool.acquire() as conn:
        credits = await conn.fetchval("SELECT credits FROM users WHERE id=$1", auth["user_id"])
    return {"user_id": str(auth["user_id"]), "credits": credits, "unit": "1 credit = 1 token"}


@app.get("/v1/account/usage")
async def account_usage(authorization: str | None = Header(default=None)):
    auth = await authenticate(authorization)
    if auth["type"] == "admin":
        raise HTTPException(status_code=400, detail="Usage endpoint requires a user API key")
    async with pool.acquire() as conn:
        totals = await conn.fetchrow(
            """
            SELECT
                COALESCE(SUM(prompt_tokens),0)::BIGINT AS prompt_tokens,
                COALESCE(SUM(completion_tokens),0)::BIGINT AS completion_tokens,
                COALESCE(SUM(total_tokens),0)::BIGINT AS total_tokens,
                COALESCE(SUM(credits_used),0)::BIGINT AS credits_used,
                COUNT(*)::BIGINT AS requests
            FROM usage_events
            WHERE user_id=$1
            """,
            auth["user_id"],
        )
        recent = await conn.fetch(
            """
            SELECT conversation_id, prompt_tokens, completion_tokens, total_tokens, credits_used, created_at
            FROM usage_events
            WHERE user_id=$1
            ORDER BY created_at DESC
            LIMIT 20
            """,
            auth["user_id"],
        )
    return {
        "totals": dict(totals),
        "recent": [
            {
                "conversation_id": str(r["conversation_id"]) if r["conversation_id"] else None,
                "prompt_tokens": r["prompt_tokens"],
                "completion_tokens": r["completion_tokens"],
                "total_tokens": r["total_tokens"],
                "credits_used": r["credits_used"],
                "created_at": r["created_at"].isoformat(),
            }
            for r in recent
        ],
    }


async def enforce_rate_limit(auth: dict):
    if auth["type"] == "admin":
        return
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                "DELETE FROM request_events WHERE user_id=$1 AND created_at < NOW() - INTERVAL '1 day'",
                auth["user_id"],
            )
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM request_events WHERE user_id=$1 AND created_at >= NOW() - INTERVAL '1 minute'",
                auth["user_id"],
            )
            if count >= REQUESTS_PER_MINUTE:
                raise HTTPException(
                    status_code=429,
                    detail=f"Rate limit exceeded: {REQUESTS_PER_MINUTE} requests per minute",
                )
            await conn.execute("INSERT INTO request_events(user_id) VALUES($1)", auth["user_id"])


async def require_credits(auth: dict):
    if auth["type"] == "admin":
        return
    async with pool.acquire() as conn:
        credits = await conn.fetchval("SELECT credits FROM users WHERE id=$1", auth["user_id"])
    if credits is None or credits <= 0:
        raise HTTPException(status_code=402, detail="Insufficient credits")


async def record_usage(auth: dict, conversation_id: uuid.UUID, usage: dict | None):
    if auth["type"] != "user" or not usage:
        return
    prompt_tokens = max(0, int(usage.get("prompt_tokens", 0) or 0))
    completion_tokens = max(0, int(usage.get("completion_tokens", 0) or 0))
    total_tokens = max(0, int(usage.get("total_tokens", prompt_tokens + completion_tokens) or 0))
    if total_tokens == 0:
        total_tokens = prompt_tokens + completion_tokens
    credits_used = total_tokens

    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                """
                INSERT INTO usage_events(
                    user_id, conversation_id, prompt_tokens, completion_tokens, total_tokens, credits_used
                ) VALUES($1,$2,$3,$4,$5,$6)
                """,
                auth["user_id"],
                conversation_id,
                prompt_tokens,
                completion_tokens,
                total_tokens,
                credits_used,
            )
            await conn.execute(
                "UPDATE users SET credits=GREATEST(0, credits-$2) WHERE id=$1",
                auth["user_id"],
                credits_used,
            )


async def check_conversation_access(conversation_id: uuid.UUID, auth: dict):
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT id, user_id, title FROM conversations WHERE id=$1", conversation_id)
    if not row:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if auth["type"] == "user" and row["user_id"] != auth["user_id"]:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return row


async def ensure_conversation(conversation_id: str | None, auth: dict, title: str | None = None) -> uuid.UUID:
    if pool is None:
        raise HTTPException(status_code=503, detail="Database unavailable")

    if conversation_id:
        try:
            cid = uuid.UUID(conversation_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid conversation_id")
        await check_conversation_access(cid, auth)
        return cid

    cid = uuid.uuid4()
    owner = auth["user_id"] if auth["type"] == "user" else None
    conversation_title = (title or "New chat").strip()[:120] or "New chat"
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO conversations(id, user_id, title) VALUES($1,$2,$3)",
            cid,
            owner,
            conversation_title,
        )
    return cid


@app.post("/v1/conversations")
async def create_conversation(request: Request, authorization: str | None = Header(default=None)):
    auth = await authenticate(authorization)
    payload = await request.json()
    cid = await ensure_conversation(None, auth, payload.get("title"))
    return {"id": str(cid), "title": (payload.get("title") or "New chat")[:120]}


@app.get("/v1/conversations")
async def list_conversations(authorization: str | None = Header(default=None)):
    auth = await authenticate(authorization)
    async with pool.acquire() as conn:
        if auth["type"] == "admin":
            rows = await conn.fetch(
                "SELECT id, user_id, title, created_at, updated_at FROM conversations ORDER BY updated_at DESC LIMIT 100"
            )
        else:
            rows = await conn.fetch(
                "SELECT id, user_id, title, created_at, updated_at FROM conversations WHERE user_id=$1 ORDER BY updated_at DESC LIMIT 100",
                auth["user_id"],
            )
    return {
        "data": [
            {
                "id": str(r["id"]),
                "user_id": str(r["user_id"]) if r["user_id"] else None,
                "title": r["title"],
                "created_at": r["created_at"].isoformat(),
                "updated_at": r["updated_at"].isoformat(),
            }
            for r in rows
        ]
    }


@app.get("/v1/conversations/{conversation_id}")
async def get_conversation(conversation_id: str, authorization: str | None = Header(default=None)):
    auth = await authenticate(authorization)
    try:
        cid = uuid.UUID(conversation_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid conversation_id")
    row = await check_conversation_access(cid, auth)
    async with pool.acquire() as conn:
        messages = await conn.fetch(
            "SELECT id, role, content, created_at FROM messages WHERE conversation_id=$1 ORDER BY id ASC",
            cid,
        )
    return {
        "id": str(cid),
        "title": row["title"],
        "messages": [
            {
                "id": m["id"],
                "role": m["role"],
                "content": m["content"],
                "created_at": m["created_at"].isoformat(),
            }
            for m in messages
        ],
    }


@app.delete("/v1/conversations/{conversation_id}")
async def delete_conversation(conversation_id: str, authorization: str | None = Header(default=None)):
    auth = await authenticate(authorization)
    try:
        cid = uuid.UUID(conversation_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid conversation_id")
    await check_conversation_access(cid, auth)
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM conversations WHERE id=$1", cid)
    return {"deleted": True, "id": str(cid)}


async def load_history(conversation_id: uuid.UUID) -> list[dict]:
    if pool is None:
        return []
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT role, content
            FROM (
                SELECT id, role, content
                FROM messages
                WHERE conversation_id=$1
                ORDER BY id DESC
                LIMIT $2
            ) q
            ORDER BY id ASC
            """,
            conversation_id,
            MEMORY_LIMIT,
        )
    return [{"role": r["role"], "content": r["content"]} for r in rows]


async def save_message(conversation_id: uuid.UUID, role: str, content: str):
    if pool is None:
        return
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO messages(conversation_id, role, content) VALUES($1,$2,$3)",
            conversation_id,
            role,
            content,
        )
        await conn.execute("UPDATE conversations SET updated_at=NOW() WHERE id=$1", conversation_id)


async def maybe_set_title(conversation_id: uuid.UUID, user_text: str):
    title = " ".join(user_text.strip().split())[:60]
    if not title:
        return
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE conversations SET title=$2 WHERE id=$1 AND title='New chat'",
            conversation_id,
            title,
        )


def extract_user_message(messages: list[dict]) -> str:
    for message in reversed(messages):
        if isinstance(message, dict) and message.get("role") == "user":
            return str(message.get("content", ""))
    raise HTTPException(status_code=400, detail="At least one user message is required")


def upstream_headers() -> dict:
    return {
        "Authorization": f"Bearer {INTERNAL_API_KEY}",
        "Content-Type": "application/json",
    }


async def stream_from_llama(upstream: dict, conversation_id: uuid.UUID, auth: dict):
    assistant_text = ""
    usage = None
    timeout = httpx.Timeout(connect=10.0, read=None, write=30.0, pool=30.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        async with client.stream("POST", LLAMA_URL, json=upstream, headers=upstream_headers()) as response:
            if response.status_code >= 400:
                yield await response.aread()
                return

            async for line in response.aiter_lines():
                if not line:
                    continue
                if line.startswith("data: "):
                    data = line[6:]
                    if data == "[DONE]":
                        yield b"data: [DONE]\n\n"
                        break
                    try:
                        obj = json.loads(data)
                        delta = obj.get("choices", [{}])[0].get("delta", {}).get("content")
                        if delta:
                            assistant_text += delta
                        if obj.get("usage"):
                            usage = obj["usage"]
                    except Exception:
                        pass
                    yield (line + "\n\n").encode()
                else:
                    yield (line + "\n").encode()

    if assistant_text.strip():
        await save_message(conversation_id, "assistant", assistant_text.strip())
    await record_usage(auth, conversation_id, usage)


@app.post("/v1/chat/completions")
async def chat(request: Request, authorization: str | None = Header(default=None)):
    auth = await authenticate(authorization)
    await enforce_rate_limit(auth)
    await require_credits(auth)
    payload = await request.json()

    incoming_messages = payload.get("messages")
    if not isinstance(incoming_messages, list) or not incoming_messages:
        raise HTTPException(status_code=400, detail="messages is required")

    conversation_id = await ensure_conversation(payload.get("conversation_id"), auth)
    user_text = extract_user_message(incoming_messages)
    history = await load_history(conversation_id)
    await save_message(conversation_id, "user", user_text)
    await maybe_set_title(conversation_id, user_text)

    is_stream = bool(payload.get("stream", False))
    upstream = {
        "model": MODEL_ALIAS,
        "messages": [{"role": "system", "content": SYSTEM_PROMPT}] + history + [{"role": "user", "content": user_text}],
        "temperature": payload.get("temperature", 0.7),
        "max_tokens": payload.get("max_tokens", 512),
        "stream": is_stream,
    }
    if is_stream:
        upstream["stream_options"] = {"include_usage": True}

    if is_stream:
        return StreamingResponse(
            stream_from_llama(upstream, conversation_id, auth),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                "X-Conversation-ID": str(conversation_id),
            },
        )

    try:
        async with httpx.AsyncClient(timeout=180.0) as client:
            response = await client.post(LLAMA_URL, json=upstream, headers=upstream_headers())
    except httpx.RequestError as exc:
        raise HTTPException(status_code=502, detail=f"Model backend unavailable: {exc}") from exc

    try:
        data = response.json()
    except ValueError:
        raise HTTPException(status_code=502, detail="Invalid response from model backend")

    if response.status_code < 400:
        try:
            assistant_text = data["choices"][0]["message"]["content"]
            if assistant_text:
                await save_message(conversation_id, "assistant", assistant_text)
        except Exception:
            pass
        await record_usage(auth, conversation_id, data.get("usage"))

    data["conversation_id"] = str(conversation_id)
    return JSONResponse(content=data, status_code=response.status_code)
