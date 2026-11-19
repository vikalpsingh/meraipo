"""Official X endpoints. No retries or logging of credential-bearing requests."""

import json
from datetime import timedelta

import httpx

from packages.database import models as m
from packages.shared.calculations import utc
from packages.shared.config import settings
from packages.shared.market_config import decrypt_secret, encrypt_secret

SCOPES = "tweet.read tweet.write users.read offline.access media.write"


class XError(Exception):
    def __init__(self, code, status=None, request_id=None):
        super().__init__(code)
        self.code, self.status, self.request_id = code, status, request_id


async def request(method, path, **kwargs):
    try:
        async with httpx.AsyncClient(timeout=20, follow_redirects=False) as client:
            response = await client.request(method, "https://api.x.com" + path, **kwargs)
    except httpx.HTTPError as exc:
        raise XError("NETWORK_OUTCOME_UNKNOWN") from exc
    if not response.is_success:
        raise XError(
            f"X_HTTP_{response.status_code}",
            response.status_code,
            response.headers.get("x-request-id", "")[:100],
        )
    try:
        return response.json() if response.content else {}
    except ValueError as exc:
        raise XError("INVALID_RESPONSE") from exc


async def exchange(data):
    c = settings()
    return await request(
        "POST",
        "/2/oauth2/token",
        data={"client_id": c.x_client_id, **data},
        auth=(c.x_client_id, c.x_client_secret.get_secret_value()),
    )


def save_tokens(account, data):
    if not data.get("access_token") or not data.get("refresh_token"):
        raise XError("MISSING_REFRESH_TOKEN")
    if not set(SCOPES.split()).issubset(set(data.get("scope", "").split())):
        raise XError("MISSING_SCOPES")
    account.tokens = encrypt_secret(json.dumps(data))
    account.expires_at = m.now() + timedelta(seconds=int(data["expires_in"]))
    account.error_code = None


async def access_token(db, account):
    if not account.tokens:
        raise XError("CONNECT_REQUIRED")
    data = json.loads(decrypt_secret(account.tokens))
    if not account.expires_at or utc(account.expires_at) <= m.now() + timedelta(minutes=5):
        try:
            updated = await exchange(
                {"grant_type": "refresh_token", "refresh_token": data["refresh_token"]}
            )
            save_tokens(account, updated)
            await db.commit()  # Persist rotated credentials before any subsequent request.
            data = updated
        except XError:
            account.error_code = "RECONNECT_REQUIRED"
            account.auto_publish = False
            await db.commit()
            raise
    return data["access_token"]


async def identity(token):
    user = (await request("GET", "/2/users/me", headers={"Authorization": "Bearer " + token}))[
        "data"
    ]
    if user.get("username", "").casefold() != "meraipo":
        raise XError("WRONG_X_ACCOUNT")
    if settings().x_expected_user_id and user["id"] != settings().x_expected_user_id:
        raise XError("WRONG_X_ACCOUNT_ID")
    return user
