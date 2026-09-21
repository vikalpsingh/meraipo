"""Moderated feedback with anonymous browser voting, never a claim of one vote per person."""

import re
import secrets
from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import Field
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from apps.api.cache import client
from apps.api.schemas import Input
from apps.api.security import admin, digest
from packages.database import models as m
from packages.database.session import get_session
from packages.shared.config import settings

router = APIRouter()
PUBLIC = ("OPEN", "PLANNED", "IN_PROGRESS", "DONE")
COOKIE = "mera_feedback"


def browser(request, response=None):
    token = request.cookies.get(COOKIE, "")
    if not re.fullmatch(r"[a-f0-9]{64}", token):
        if response is None:
            raise HTTPException(403, "Please reload the feedback page and enable cookies.")
        token = secrets.token_hex(32)
        response.set_cookie(
            COOKIE,
            token,
            httponly=True,
            samesite="lax",
            secure=settings().public_origin.startswith("https://"),
            max_age=31536000,
            path="/api/v1/feedback",
        )
    return digest(token)


async def write_guard(request, operation):
    if request.headers.get("origin") != settings().public_origin:
        raise HTTPException(403, "Invalid request origin")
    visitor = browser(request)
    limit, seconds = (5, 3600) if operation == "submit" else (60, 60)
    try:
        count = await client.eval(
            "local n=redis.call('INCR',KEYS[1]); if n==1 then redis.call('EXPIRE',KEYS[1],ARGV[1]) end; return n",
            1,
            f"feedback:{operation}:{visitor}",
            seconds,
        )
        if count > limit:
            raise HTTPException(429, "Too many requests. Please try again later.")
    except HTTPException:
        raise
    except Exception:
        if settings().environment != "test":
            raise HTTPException(
                503, "Feedback is temporarily unavailable. Your input has not been submitted."
            ) from None
    return visitor


def insert_for(db, model):
    return (pg_insert if db.bind.dialect.name == "postgresql" else sqlite_insert)(model)


def public_record(row, votes):
    return {
        "id": row.id,
        "kind": row.kind,
        "title": row.title,
        "body": row.body,
        "status": row.status,
        "votes": votes,
        "created_at": row.created_at.isoformat(),
    }


@router.get("/feedback")
async def feedback(request: Request, response: Response, db=Depends(get_session)):
    visitor = browser(request, response)
    totals = (
        select(m.FeedbackVote.feedback_id, func.count().label("votes"))
        .group_by(m.FeedbackVote.feedback_id)
        .subquery()
    )
    count = func.coalesce(totals.c.votes, 0)
    public = (m.CustomerFeedback.kind == "FEATURE", m.CustomerFeedback.status.in_(PUBLIC))
    rows = (
        await db.execute(
            select(m.CustomerFeedback, count)
            .outerjoin(totals, totals.c.feedback_id == m.CustomerFeedback.id)
            .where(*public)
            .order_by(count.desc(), m.CustomerFeedback.created_at, m.CustomerFeedback.id)
            .limit(5)
        )
    ).all()
    voted = set(
        (
            await db.scalars(
                select(m.FeedbackVote.feedback_id).where(
                    m.FeedbackVote.voter_hash == visitor,
                    m.FeedbackVote.feedback_id.in_([r.id for r, _ in rows]),
                )
            )
        ).all()
    )
    total = await db.scalar(select(func.count()).select_from(m.CustomerFeedback).where(*public))
    delivered = await db.scalar(
        select(func.count())
        .select_from(m.CustomerFeedback)
        .where(*public, m.CustomerFeedback.status == "DONE")
    )
    return {
        "items": [{**public_record(row, votes), "voted": row.id in voted} for row, votes in rows],
        "summary": {"published": total, "delivered": delivered},
    }


class Submission(Input):
    kind: Literal["FEATURE", "FEEDBACK"]
    title: str = Field(min_length=4, max_length=120)
    body: str = Field(min_length=10, max_length=2000)
    request_key: UUID


@router.post("/feedback", status_code=202)
async def submit(data: Submission, request: Request, db=Depends(get_session)):
    visitor = await write_guard(request, "submit")
    values = data.model_dump(exclude={"request_key"})
    await db.execute(
        insert_for(db, m.CustomerFeedback)
        .values(
            **values,
            id=str(uuid4()),
            request_key=str(data.request_key),
            author_hash=visitor,
            status="PENDING",
            created_at=m.now(),
            updated_at=m.now(),
        )
        .on_conflict_do_nothing(index_elements=["author_hash", "request_key"])
    )
    row = await db.scalar(
        select(m.CustomerFeedback).where(
            m.CustomerFeedback.author_hash == visitor,
            m.CustomerFeedback.request_key == str(data.request_key),
        )
    )
    if any(getattr(row, key) != value for key, value in values.items()):
        raise HTTPException(
            409, "This submission was already used for different feedback. Reload and try again."
        )
    await db.commit()
    return {
        "message": "Thank you. Your feedback is saved for review. Approved feature requests appear on the public board."
    }


class Vote(Input):
    voted: bool = Field(strict=True)


@router.put("/feedback/{feedback_id}/vote")
async def vote(feedback_id: UUID, data: Vote, request: Request, db=Depends(get_session)):
    visitor = await write_guard(request, "vote")
    row = await db.get(m.CustomerFeedback, str(feedback_id))
    if not row or row.kind != "FEATURE" or row.status not in PUBLIC:
        raise HTTPException(404, "Feature request not found")
    if row.status == "DONE":
        raise HTTPException(409, "This feature has already been delivered.")
    if data.voted:
        await db.execute(
            insert_for(db, m.FeedbackVote)
            .values(
                id=str(uuid4()),
                feedback_id=row.id,
                voter_hash=visitor,
                created_at=m.now(),
                updated_at=m.now(),
            )
            .on_conflict_do_nothing(index_elements=["feedback_id", "voter_hash"])
        )
    else:
        await db.execute(
            delete(m.FeedbackVote).where(
                m.FeedbackVote.feedback_id == row.id, m.FeedbackVote.voter_hash == visitor
            )
        )
    await db.commit()
    return {"voted": data.voted}


@router.get("/admin/feedback")
async def inbox(auth=Depends(admin), page: int = Query(1, ge=1), db=Depends(get_session)):
    counts = (
        select(m.FeedbackVote.feedback_id, func.count().label("votes"))
        .group_by(m.FeedbackVote.feedback_id)
        .subquery()
    )
    rows = (
        await db.execute(
            select(m.CustomerFeedback, func.coalesce(counts.c.votes, 0))
            .outerjoin(counts, counts.c.feedback_id == m.CustomerFeedback.id)
            .order_by(m.CustomerFeedback.created_at.desc(), m.CustomerFeedback.id)
            .offset((page - 1) * 25)
            .limit(26)
        )
    ).all()
    return {
        "items": [public_record(row, votes) for row, votes in rows[:25]],
        "has_more": len(rows) > 25,
    }


class Review(Input):
    status: Literal["PENDING", "OPEN", "PLANNED", "IN_PROGRESS", "DONE", "HIDDEN", "REVIEWED"]


@router.patch("/admin/feedback/{feedback_id}")
async def review(feedback_id: UUID, data: Review, auth=Depends(admin), db=Depends(get_session)):
    row = await db.get(m.CustomerFeedback, str(feedback_id))
    if not row:
        raise HTTPException(404, "Feedback not found")
    if row.kind == "FEEDBACK" and data.status not in {"PENDING", "REVIEWED", "HIDDEN"}:
        raise HTTPException(422, "General feedback remains private; mark it reviewed or hidden.")
    row.status = data.status
    db.add(
        m.Audit(
            admin_id=auth[0].id,
            action="feedback.review",
            entity_id=row.id,
            changes={"status": data.status},
        )
    )
    await db.commit()
    return {"status": row.status}
