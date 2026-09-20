import hashlib
import secrets
from datetime import timedelta

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.cache import client
from packages.database.models import AdminSession, AdminUser, now
from packages.database.session import get_session
from packages.shared.calculations import utc
from packages.shared.config import settings

hasher = PasswordHasher()
dummy_hash = hasher.hash(secrets.token_urlsafe(32))


def digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def verify(password, encoded):
    try:
        return hasher.verify(encoded, password)
    except (VerificationError, InvalidHashError):
        return False


async def login_limit(request: Request, email: str):
    # Never trust forwarded IP headers supplied directly by a visitor.
    keys = [
        "login:ip:" + digest(request.client.host if request.client else "unknown"),
        "login:user:" + digest(email.lower()),
    ]
    try:
        for key in keys:
            count = await client.eval(
                "local n=redis.call('INCR',KEYS[1]); if n==1 then redis.call('EXPIRE',KEYS[1],900) end; return n",
                1,
                key,
            )
            if count > 10:
                raise HTTPException(429, "Too many attempts. Try again in 15 minutes.")
    except HTTPException:
        raise
    except Exception:
        if settings().environment != "test":
            raise HTTPException(503, "Sign-in is temporarily unavailable") from None


async def admin(request: Request, db: AsyncSession = Depends(get_session)):
    token = request.cookies.get("mera_session", "")
    session = await db.scalar(select(AdminSession).where(AdminSession.token_hash == digest(token)))
    if not session or utc(session.expires_at) <= now():
        raise HTTPException(401, "Administrator sign-in required")
    user = await db.get(AdminUser, session.admin_id)
    if not user or not user.enabled:
        raise HTTPException(401, "Administrator sign-in required")
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        csrf = request.headers.get("x-csrf-token", "")
        if request.headers.get("origin") != settings().public_origin or not secrets.compare_digest(
            session.csrf_hash, digest(csrf)
        ):
            raise HTTPException(403, "Invalid request origin or CSRF token")
    return user, session


async def new_session(db, user):
    token, csrf = secrets.token_urlsafe(48), secrets.token_urlsafe(32)
    db.add(
        AdminSession(
            admin_id=user.id,
            token_hash=digest(token),
            csrf_hash=digest(csrf),
            expires_at=now() + timedelta(hours=settings().session_hours),
        )
    )
    return token, csrf
