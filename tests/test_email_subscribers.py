import json

from fastapi import Response

from apps.api.email_admin import subscribers
from packages.database import models as m
from packages.shared.market_config import encrypt_secret


async def test_subscribers_paginate_and_exclude_test_only(db):
    for i in range(3):
        db.add(
            m.EmailSubscriber(
                email_hash=f"directory-{i}",
                email_encrypted=encrypt_secret(f"user{i}@example.com"),
                consent_at=m.now(),
                verified_at=m.now(),
                contact_encrypted=encrypt_secret(
                    json.dumps({"first_name": f"User{i}", "last_name": "Test"})
                ),
            )
        )
    db.add(
        m.EmailSubscriber(
            email_hash="test-only",
            email_encrypted=encrypt_secret("test@example.com"),
            consent_at=m.now(),
        )
    )
    await db.commit()
    response = Response()
    first = await subscribers(response, page=1, page_size=2, auth=None, db=db)
    second = await subscribers(response, page=2, page_size=2, auth=None, db=db)
    assert first["counts"]["total"] == 3
    assert first["counts"]["active"] == 3
    assert len(first["items"]) == 2 and len(second["items"]) == 1
    assert {r["id"] for r in first["items"]}.isdisjoint(r["id"] for r in second["items"])
    assert all(r["first_name"].startswith("User") for r in first["items"])
    assert response.headers["cache-control"] == "no-store"
