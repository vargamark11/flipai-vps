import os
from datetime import datetime, timedelta, timezone

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from fastapi import FastAPI, Header, HTTPException, Request

app = FastAPI(title="FlipAI Admin Auth", version="1.0.0")

ADMIN_USERNAME = os.environ.get("FLIPAI_ADMIN_USERNAME", "admin").strip()
ADMIN_PASSWORD_HASH = os.environ.get("FLIPAI_ADMIN_PASSWORD_HASH", "").strip()
JWT_SECRET = os.environ.get("FLIPAI_JWT_SECRET", "").strip()
ADMIN_TOKEN_MINUTES = int(os.environ.get("FLIPAI_ADMIN_TOKEN_MINUTES", "30"))

password_hasher = PasswordHasher()


def require_config():
    if not ADMIN_USERNAME or not ADMIN_PASSWORD_HASH or len(JWT_SECRET) < 32:
        raise HTTPException(status_code=503, detail="Admin authentication is not configured")


def create_admin_token() -> tuple[str, int]:
    require_config()
    now = datetime.now(timezone.utc)
    expires = now + timedelta(minutes=ADMIN_TOKEN_MINUTES)
    token = jwt.encode(
        {
            "sub": ADMIN_USERNAME,
            "type": "admin_access",
            "iat": int(now.timestamp()),
            "exp": int(expires.timestamp()),
        },
        JWT_SECRET,
        algorithm="HS256",
    )
    return token, int((expires - now).total_seconds())


def authenticate_admin(authorization: str | None):
    require_config()
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing admin access token")
    token = authorization.removeprefix("Bearer ").strip()
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
        if payload.get("type") != "admin_access" or payload.get("sub") != ADMIN_USERNAME:
            raise jwt.InvalidTokenError()
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
        raise HTTPException(status_code=401, detail="Invalid or expired admin access token")
    return payload


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "service": "flipai-admin-auth",
        "configured": bool(ADMIN_USERNAME and ADMIN_PASSWORD_HASH and len(JWT_SECRET) >= 32),
        "version": "1.0.0",
    }


@app.post("/v1/admin/auth/login")
async def admin_login(request: Request):
    require_config()
    payload = await request.json()
    username = str(payload.get("username", "")).strip()
    password = str(payload.get("password", ""))

    if username != ADMIN_USERNAME or not password:
        raise HTTPException(status_code=401, detail="Invalid admin credentials")

    try:
        password_hasher.verify(ADMIN_PASSWORD_HASH, password)
    except (VerifyMismatchError, Exception):
        raise HTTPException(status_code=401, detail="Invalid admin credentials")

    token, expires_in = create_admin_token()
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in": expires_in,
        "admin": {"username": ADMIN_USERNAME},
    }


@app.get("/v1/admin/auth/me")
async def admin_me(authorization: str | None = Header(default=None)):
    authenticate_admin(authorization)
    return {"username": ADMIN_USERNAME, "role": "admin"}
