import os
from datetime import datetime, timedelta, timezone

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from fastapi import FastAPI, Header, HTTPException, Request

app = FastAPI(title="FlipAI Admin Auth", version="1.1.0")

ADMIN_EMAIL = os.environ.get("FLIPAI_ADMIN_EMAIL", "").strip().lower()
ADMIN_PASSWORD_HASH = os.environ.get("FLIPAI_ADMIN_PASSWORD_HASH", "").strip()
JWT_SECRET = os.environ.get("FLIPAI_JWT_SECRET", "").strip()
ADMIN_TOKEN_MINUTES = int(os.environ.get("FLIPAI_ADMIN_TOKEN_MINUTES", "30"))

password_hasher = PasswordHasher()


def normalize_email(value: str) -> str:
    email = value.strip().lower()
    if len(email) > 254 or "@" not in email or email.startswith("@") or email.endswith("@"):
        raise HTTPException(status_code=401, detail="Invalid admin credentials")
    return email


def require_config():
    if not ADMIN_EMAIL or not ADMIN_PASSWORD_HASH or len(JWT_SECRET) < 32:
        raise HTTPException(status_code=503, detail="Admin authentication is not configured")


def create_admin_token() -> tuple[str, int]:
    require_config()
    now = datetime.now(timezone.utc)
    expires = now + timedelta(minutes=ADMIN_TOKEN_MINUTES)
    token = jwt.encode(
        {
            "sub": ADMIN_EMAIL,
            "type": "admin_access",
            "role": "admin",
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
        if payload.get("type") != "admin_access" or payload.get("sub") != ADMIN_EMAIL:
            raise jwt.InvalidTokenError()
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
        raise HTTPException(status_code=401, detail="Invalid or expired admin access token")
    return payload


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "service": "flipai-admin-auth",
        "configured": bool(ADMIN_EMAIL and ADMIN_PASSWORD_HASH and len(JWT_SECRET) >= 32),
        "version": "1.1.0",
    }


@app.post("/v1/admin/auth/login")
async def admin_login(request: Request):
    require_config()
    payload = await request.json()
    email = normalize_email(str(payload.get("email", "")))
    password = str(payload.get("password", ""))

    if email != ADMIN_EMAIL or not password:
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
        "admin": {"email": ADMIN_EMAIL, "role": "admin"},
    }


@app.get("/v1/admin/auth/me")
async def admin_me(authorization: str | None = Header(default=None)):
    authenticate_admin(authorization)
    return {"email": ADMIN_EMAIL, "role": "admin"}
