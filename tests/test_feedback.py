from uuid import uuid4

import pytest
from sqlalchemy import func, select

from apps.api import feedback_routes as routes
from packages.database import models as m

ORIGIN = {"origin": "http://localhost:3000"}


@pytest.fixture(autouse=True)
def isolated_limiter(monkeypatch):
    async def count(*args):
        return 1

    monkeypatch.setattr(routes.client, "eval", count)


def submission(**changes):
    return {
        "kind": "FEATURE",
        "title": "Compare IPOs side by side",
        "body": "Compare issue prices, subscriptions and company fundamentals.",
        "request_key": str(uuid4()),
        **changes,
    }


async def create_feature(db, **changes):
    row = m.CustomerFeedback(
        kind="FEATURE",
        title="Compare IPOs",
        body="A useful comparison view.",
        status="OPEN",
        author_hash="a" * 64,
        request_key=str(uuid4()),
    )
    for key, value in changes.items():
        setattr(row, key, value)
    db.add(row)
    await db.commit()
    return row


async def test_submission_is_private_idempotent_and_cookie_is_not_cached(client, db):
    response = await client.get("/api/v1/feedback")
    assert response.headers["cache-control"] == "no-store"
    assert "HttpOnly" in response.headers["set-cookie"]
    payload = submission()
    for _ in range(2):
        assert (
            await client.post("/api/v1/feedback", json=payload, headers=ORIGIN)
        ).status_code == 202
    assert await db.scalar(select(func.count()).select_from(m.CustomerFeedback)) == 1
    assert (await client.get("/api/v1/feedback")).json()["items"] == []
    conflict = await client.post(
        "/api/v1/feedback", json={**payload, "title": "Different idea"}, headers=ORIGIN
    )
    assert conflict.status_code == 409


async def test_votes_are_unique_reversible_and_browser_specific(client, db):
    row = await create_feature(db)
    await client.get("/api/v1/feedback")
    for _ in range(3):
        assert (
            await client.put(
                f"/api/v1/feedback/{row.id}/vote", json={"voted": True}, headers=ORIGIN
            )
        ).status_code == 200
    board = (await client.get("/api/v1/feedback")).json()["items"][0]
    assert board["votes"] == 1 and board["voted"] is True
    client.cookies.clear()
    second = (await client.get("/api/v1/feedback")).json()["items"][0]
    assert second["votes"] == 1 and second["voted"] is False
    await client.put(f"/api/v1/feedback/{row.id}/vote", json={"voted": True}, headers=ORIGIN)
    assert (await client.get("/api/v1/feedback")).json()["items"][0]["votes"] == 2
    await client.put(f"/api/v1/feedback/{row.id}/vote", json={"voted": False}, headers=ORIGIN)
    assert (await client.get("/api/v1/feedback")).json()["items"][0]["votes"] == 1


async def test_top_five_rank_and_summary_exclude_private_feedback(client, db):
    for count in range(7):
        row = await create_feature(
            db, title=f"Feature {count}", status="DONE" if count == 6 else "OPEN"
        )
        for voter in range(count):
            db.add(m.FeedbackVote(feedback_id=row.id, voter_hash=f"{voter:064d}"))
    await create_feature(db, kind="FEEDBACK", title="Private message", status="REVIEWED")
    await create_feature(db, title="Pending message", status="PENDING")
    await db.commit()
    body = (await client.get("/api/v1/feedback")).json()
    assert [row["votes"] for row in body["items"]] == [6, 5, 4, 3, 2]
    assert body["summary"] == {"published": 7, "delivered": 1}
    assert all("author_hash" not in row and "request_key" not in row for row in body["items"])


async def test_write_origin_cookie_validation_and_hidden_vote_guard(client, db):
    assert (
        await client.post("/api/v1/feedback", json=submission(), headers=ORIGIN)
    ).status_code == 403
    await client.get("/api/v1/feedback")
    assert (
        await client.post(
            "/api/v1/feedback", json=submission(), headers={"origin": "https://evil.example"}
        )
    ).status_code == 403
    assert (
        await client.post("/api/v1/feedback", json=submission(body="short"), headers=ORIGIN)
    ).status_code == 422
    assert (await client.get("/api/v1/admin/feedback")).status_code == 401
    for status, expected in [("PENDING", 404), ("HIDDEN", 404), ("DONE", 409)]:
        row = await create_feature(db, status=status)
        assert (
            await client.put(
                f"/api/v1/feedback/{row.id}/vote", json={"voted": True}, headers=ORIGIN
            )
        ).status_code == expected


async def test_admin_review_publishes_and_hides_without_losing_votes(admin_client, db):
    row = await create_feature(db, status="PENDING")
    assert (await admin_client.get("/api/v1/admin/feedback")).json()["items"][0]["id"] == row.id
    response = await admin_client.patch(f"/api/v1/admin/feedback/{row.id}", json={"status": "OPEN"})
    assert response.status_code == 200
    assert (await admin_client.get("/api/v1/feedback")).json()["items"][0]["id"] == row.id
    await admin_client.put(f"/api/v1/feedback/{row.id}/vote", json={"voted": True})
    await admin_client.patch(f"/api/v1/admin/feedback/{row.id}", json={"status": "HIDDEN"})
    assert (await admin_client.get("/api/v1/feedback")).json()["items"] == []
    assert await db.scalar(select(func.count()).select_from(m.FeedbackVote)) == 1
    private = await create_feature(db, kind="FEEDBACK", status="PENDING")
    assert (
        await admin_client.patch(f"/api/v1/admin/feedback/{private.id}", json={"status": "OPEN"})
    ).status_code == 422


async def test_rate_limit_reports_retry_without_storing(client, db, monkeypatch):
    await client.get("/api/v1/feedback")

    async def exhausted(*args):
        return 6

    monkeypatch.setattr(routes.client, "eval", exhausted)
    assert (
        await client.post("/api/v1/feedback", json=submission(), headers=ORIGIN)
    ).status_code == 429
    assert await db.scalar(select(func.count()).select_from(m.CustomerFeedback)) == 0
