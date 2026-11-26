"""Deterministic verified IPO brief, conservative length and durable publish guard."""

import base64
import hashlib
import re
import secrets
from contextlib import asynccontextmanager
from datetime import date, timedelta
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from redis.exceptions import RedisError
from sqlalchemy import func, select

from apps.api.cache import client
from packages.database import models as m
from packages.providers import x_api
from packages.shared.calculations import utc
from packages.shared.config import settings
from packages.shared.market_config import load_market_settings

IST = ZoneInfo("Asia/Kolkata")

DEFAULT_SCHEDULES = {
    "MARKET_DAILY": {"enabled": False, "time": "08:45", "auto_publish": False},
    "IPO_OPENING": {"enabled": False, "time": "09:00"},
    "IPO_CLOSING": {"enabled": False, "time": "09:15"},
}


def schedules(a):
    return {k: {**v, **(a.schedules or {}).get(k, {})} for k, v in DEFAULT_SCHEDULES.items()}


def due(config, now):
    hour, minute = map(int, config["time"].split(":"))
    elapsed = now.hour * 60 + now.minute - hour * 60 - minute
    return config["enabled"] and 0 <= elapsed < 60


async def opening_image(db, ipo_id, closing=False, current=False):
    from packages.shared.email_template import content

    item = await content(
        db,
        ipo_id,
        settings().public_origin,
        "",
        opening=True,
        closing=closing,
        current=current,
        inline_attachment=True,
    )
    return item["chart_png"]


async def validate_post(db, row):
    now = m.now()
    if row.trading_date != now.astimezone(IST).date():
        raise x_api.XError("DRAFT_EXPIRED")
    if row.kind not in ("MANUAL", "MARKET_DAILY", "MARKET_TEST") and not trading_day(
        await load_market_settings(db), row.trading_date
    ):
        raise x_api.XError("NON_TRADING_DAY")
    if row.kind in ("MARKET_DAILY", "MARKET_TEST"):
        trading_day(await load_market_settings(db), row.trading_date)  # Validate calendar coverage.
        if row.trading_date.weekday() >= 5:
            raise x_api.XError("NON_TRADING_DAY")
    a = await account(db)
    if row.kind in DEFAULT_SCHEDULES and not schedules(a)[row.kind]["enabled"]:
        raise x_api.XError("POST_TYPE_DISABLED")
    if row.kind in ("MARKET_DAILY", "MARKET_TEST"):
        from datetime import datetime

        stamp = datetime.fromisoformat(row.evidence["generated_at"])
        if not now - timedelta(hours=1) <= stamp <= now:
            raise x_api.XError("MARKET_DRAFT_EXPIRED")
        # Evidence is model-selected; automation requires a separate tested opt-in.
        if not row.evidence.get("facts"):
            raise x_api.XError("AI_INSUFFICIENT_EVIDENCE")
    elif row.kind == "IPO_TEST":
        text, _ = await public_ipo_snapshot(db, row.evidence.get("ipo_id"), current=True)
        if text != row.content or await quote_key(db, row.evidence["ipo_id"]) != row.evidence.get(
            "quote_key"
        ):
            raise x_api.XError("SOURCE_CHANGED_REGENERATE")
    elif row.kind != "MANUAL":
        text, _ = await snapshot(
            db, row.evidence.get("ipo_id"), row.kind == "IPO_OPENING", row.kind == "IPO_CLOSING"
        )
        if text != row.content:
            raise x_api.XError("SOURCE_CHANGED_REGENERATE")
        if row.kind in ("IPO_OPENING", "IPO_CLOSING"):
            # Quote identity, not PNG render clock, is compared before publishing.
            if await quote_key(db, row.evidence["ipo_id"]) != row.evidence.get("quote_key"):
                raise x_api.XError("GMP_CHANGED_REGENERATE")
    if not row.content.strip():
        raise x_api.XError("EMPTY_DRAFT")
    if weighted_length(row.content) > 280:
        raise x_api.XError("DRAFT_TOO_LONG")


async def quote_key(db, ipo_id):
    ipo = await db.get(m.IPO, ipo_id)
    gmp = await db.scalar(
        select(m.GMP)
        .where(m.GMP.ipo_id == ipo_id, m.GMP.observed_at <= m.now())
        .order_by(m.GMP.observed_at.desc(), m.GMP.created_at.desc(), m.GMP.id.desc())
        .limit(1)
    )
    fresh = bool(
        gmp
        and utc(gmp.observed_at).astimezone(IST).date() == m.now().astimezone(IST).date()
        and utc(gmp.observed_at) >= m.now() - timedelta(hours=settings().gmp_ttl_hours)
    )
    return f"{ipo.price_high}:{gmp.id if fresh else 'unavailable'}:{gmp.value if fresh else ''}"


async def generate_scheduled(db, kind, manual=False):
    from packages.providers import market_research

    now = m.now()
    local = now.astimezone(IST)
    a = await account(db)
    config = schedules(a)[kind]
    if not config["enabled"] or (not manual and not due(config, local)):
        return []
    is_trading = trading_day(await load_market_settings(db), local.date())
    if local.weekday() >= 5 or (kind != "MARKET_DAILY" and not is_trading):
        return []
    ids = (
        [None]
        if kind == "MARKET_DAILY"
        else list(
            await db.scalars(
                select(m.IPODate.ipo_id).where(
                    (m.IPODate.close_date if kind == "IPO_CLOSING" else m.IPODate.open_date)
                    == local.date()
                )
            )
        )
    )
    if manual and kind in ("IPO_OPENING", "IPO_CLOSING"):
        existing = set(
            await db.scalars(
                select(m.XPost.dedupe_key).where(
                    m.XPost.trading_date == local.date(), m.XPost.kind == kind
                )
            )
        )
        ids.sort(key=lambda ipo_id: f"{kind}:{local.date()}:{ipo_id}" in existing)
    result = []
    # One candidate per minute bounds lock lifetime and provider costs; backlog catches up.
    for ipo_id in ids:
        key = f"{kind}:{local.date()}:{ipo_id or 'market'}"
        row = await db.scalar(select(m.XPost).where(m.XPost.dedupe_key == key))
        refreshed = False
        if (
            row
            and kind in ("IPO_OPENING", "IPO_CLOSING")
            and row.status == "BLOCKED"
            and row.attempts == 0
        ):
            ipo = await db.get(m.IPO, ipo_id)
            refreshed = bool(
                ipo
                and ipo.source_timestamp
                and str(ipo.source_timestamp) != row.evidence.get("source_timestamp")
            )
        if row and not (
            (manual or refreshed)
            and kind in ("IPO_OPENING", "IPO_CLOSING")
            and row.status in ("BLOCKED", "DRAFT", "FAILED")
            and row.attempts == 0
        ):
            continue
        if row is None:
            row = m.XPost(
                trading_date=local.date(),
                dedupe_key=key,
                kind=kind,
                status="GENERATING",
                content="",
                evidence={},
            )
            db.add(row)
        else:
            row.status = "GENERATING"
            row.approved_at = row.approved_by = row.error_code = None
        await db.commit()  # Reserve before any paid request; interrupted work is not retried.
        try:
            if kind == "MARKET_DAILY":
                from packages.shared.market_config import market_settings_context

                async with market_settings_context(db):
                    text, evidence = await market_research.generate(now)
            else:
                text, evidence = await snapshot(
                    db, ipo_id, opening=kind == "IPO_OPENING", closing=kind == "IPO_CLOSING"
                )
                before = await quote_key(db, ipo_id)
                row.image_png = await opening_image(db, ipo_id, closing=kind == "IPO_CLOSING")
                evidence["quote_key"] = await quote_key(db, ipo_id)
                if before != evidence["quote_key"]:
                    raise x_api.XError("GMP_CHANGED_REGENERATE")
            await assign_content(db, row, text, evidence)
            can_auto = (
                not manual
                and a.auto_publish
                and (kind in ("IPO_OPENING", "IPO_CLOSING") or config.get("auto_publish", False))
            )
            row.status = "SKIPPED" if text == "SKIP_POST" else "QUEUED" if can_auto else "DRAFT"
        except x_api.XError as exc:
            row.status, row.error_code = "BLOCKED", exc.code
            row.api_status, row.request_id = exc.status, exc.request_id
            row.evidence = getattr(exc, "review", {})
        await db.commit()
        result.append(row)
        break
    return result


async def assign_content(db, row, text, evidence):
    row.content, row.evidence = text, evidence
    if text == "SKIP_POST":
        row.content_hash = None
        return
    digest = hashlib.sha256(text.encode()).hexdigest()
    duplicate = await db.scalar(
        select(m.XPost.id).where(m.XPost.content_hash == digest, m.XPost.id != row.id).limit(1)
    )
    if duplicate:
        error = x_api.XError("DUPLICATE_CONTENT_REVIEW_EXISTING_POST")
        error.review = {
            "duplicate_post_id": duplicate,
            "reason": "Identical content already exists. Review that post instead of sending a duplicate.",
        }
        raise error
    row.content_hash = digest


async def generate_test(db, kind, ipo_id=None):
    """One paid market test per day; IPO tests are isolated from event schedules."""
    from packages.providers import market_research
    from packages.shared.market_config import market_settings_context

    now = m.now()
    day = now.astimezone(IST).date()
    test_kind = "MARKET_TEST" if kind == "MARKET_DAILY" else "IPO_TEST"
    key = f"{test_kind}:{day}:{ipo_id if test_kind == 'IPO_TEST' else 'market'}"
    row = await db.scalar(select(m.XPost).where(m.XPost.dedupe_key == key))
    if row:
        return row
    row = m.XPost(
        kind=test_kind,
        trading_date=day,
        dedupe_key=key,
        status="GENERATING",
        content="",
        evidence={},
    )
    db.add(row)
    await db.commit()
    try:
        if test_kind == "MARKET_TEST":
            async with market_settings_context(db):
                text, evidence = await market_research.generate(now)
        else:
            text, evidence = await public_ipo_snapshot(db, ipo_id, current=True)
            before = await quote_key(db, ipo_id)
            row.image_png = await opening_image(db, ipo_id, current=True)
            evidence["quote_key"] = await quote_key(db, ipo_id)
            if before != evidence["quote_key"]:
                raise x_api.XError("GMP_CHANGED_REGENERATE")
        await assign_content(db, row, text, {**evidence, "test": True})
        row.status = "SKIPPED" if text == "SKIP_POST" else "DRAFT"
    except x_api.XError as exc:
        row.status, row.error_code = "BLOCKED", exc.code
        row.evidence = getattr(exc, "review", {})
        row.api_status, row.request_id = exc.status, exc.request_id
    await db.commit()
    return row


@asynccontextmanager
async def operation_lock():
    owner = secrets.token_hex(24)
    try:
        acquired = await client.set("x:operation", owner, nx=True, ex=120)
    except RedisError as exc:
        raise x_api.XError("X_COORDINATION_UNAVAILABLE") from exc
    if not acquired:
        raise x_api.XError("X_OPERATION_BUSY")
    try:
        yield
    finally:
        await client.eval(
            "if redis.call('get',KEYS[1]) == ARGV[1] then return redis.call('del',KEYS[1]) else return 0 end",
            1,
            "x:operation",
            owner,
        )


def weighted_length(text):
    # t.co URLs cost 23; conservative Unicode weighting never understates emoji sequences.
    parts = re.split(r"(https://[^\s]+)", text)
    return sum(
        23 if p.startswith("https://") else sum(1 if ord(ch) < 128 else 2 for ch in p)
        for p in parts
    )


def trading_day(config, day):
    if config.trading_calendar_year != day.year:
        raise x_api.XError("TRADING_CALENDAR_NOT_VERIFIED")
    try:
        holidays = {
            date.fromisoformat(x.strip()) for x in config.trading_holidays.split(",") if x.strip()
        }
    except ValueError as exc:
        raise x_api.XError("INVALID_TRADING_CALENDAR") from exc
    return day.weekday() < 5 and day not in holidays


async def account(db):
    from apps.api.feedback_routes import insert_for

    await db.execute(
        insert_for(db, m.XAccount).values(id="meraipo", auto_publish=False).on_conflict_do_nothing()
    )
    return await db.get(m.XAccount, "meraipo", populate_existing=True)


async def public_ipo_review(db, ipo, dates, closing=False, current=False):
    """Use published feed provenance, never an administrator's guide approval."""
    now = m.now()
    day = now.astimezone(IST).date()
    detail = await db.scalar(
        select(m.IPOProviderDetail).where(m.IPOProviderDetail.ipo_id == ipo.id)
    )
    guide = await db.scalar(select(m.ApplicantGuide).where(m.ApplicantGuide.ipo_id == ipo.id))
    source = detail.source_url if detail else (guide.source_url if guide else "")
    provider = (ipo.source_provider or "").lower()
    # IPOAlerts imports may not contain a per-company source URL.
    if not source and provider == "ipoalerts":
        source = "https://ipoalerts.in/"
    host = (urlsplit(source or "").hostname or "").lower()
    checks = {
        "Public feed source": bool(
            source
            and source.startswith("https://")
            and any(
                host == d or host.endswith("." + d)
                for d in ("nseindia.com", "bseindia.com", "ipoalerts.in", "ipowatch.in")
            )
        ),
        "Fresh feed": bool(
            ipo.source_timestamp
            and now - timedelta(hours=settings().x_max_age_hours)
            <= utc(ipo.source_timestamp)
            <= now
        ),
        "Open or upcoming": ipo.status in ("OPEN", "UPCOMING"),
        "No flagged data conflict": (ipo.quality or "").upper()
        not in ("CONFLICT", "CONFLICTED", "INVALID", "REJECTED"),
        "Application dates valid": bool(
            dates.open_date and dates.close_date and dates.open_date <= day <= dates.close_date
        ),
        "Event is today": current or (dates.close_date if closing else dates.open_date) == day,
        "Not cancelled or postponed": (ipo.raw_status or "").upper()
        not in ("CANCELLED", "POSTPONED", "WITHDRAWN"),
    }
    return checks, source


async def public_ipo_snapshot(db, ipo_id, closing=False, current=False):
    now = m.now()
    day = now.astimezone(IST).date()
    if not trading_day(await load_market_settings(db), day):
        raise x_api.XError("NON_TRADING_DAY")
    rows = (
        await db.execute(
            select(m.IPO, m.IPODate, m.Company)
            .join(m.IPODate, m.IPODate.ipo_id == m.IPO.id)
            .join(m.Company, m.Company.id == m.IPO.company_id)
            .where(m.Company.is_demo.is_(False), m.IPO.id == ipo_id)
        )
    ).all()
    for ipo, dates, company in rows:
        checks, source = await public_ipo_review(db, ipo, dates, closing, current)
        if not all(checks.values()):
            error = x_api.XError("IPO_PUBLIC_SOURCE_NOT_READY")
            error.review = {
                "checks": checks,
                "source_url": source,
                "source_timestamp": str(ipo.source_timestamp),
            }
            raise error
        name = " ".join(company.name.split()).replace("@", "").replace("#", "")[:80]
        text = (
            f"{'IPO open for subscription' if current else 'IPO closes today' if closing else 'IPO opens today'} | {day:%d %b %Y}\n{name}\n"
            f"Applications: {dates.open_date:%d %b}–{dates.close_date:%d %b}.\n"
            f"https://www.meraipo.com/ipo/{company.slug}\nPublic-feed reminder. GMP unofficial; returns not guaranteed."
        )
        if weighted_length(text) > 280:
            raise x_api.XError("DRAFT_TOO_LONG")
        return text, {
            "ipo_id": ipo.id,
            "source_url": source,
            "source_timestamp": ipo.source_timestamp.isoformat(),
            "generated_at": now.isoformat(),
            "policy": "public_feed",
            "event": "current" if current else "closing" if closing else "opening",
        }
    raise x_api.XError("NO_OPENING_OR_CLOSING_IPO")


async def snapshot(db, ipo_id=None, opening=False, closing=False):
    if opening or closing:
        return await public_ipo_snapshot(db, ipo_id, closing)
    now = m.now()
    day = now.astimezone(IST).date()
    config = await load_market_settings(db)
    if not trading_day(config, day):
        raise x_api.XError("NON_TRADING_DAY")
    rows = (
        await db.execute(
            select(m.IPO, m.IPODate, m.ApplicantGuide, m.Company)
            .join(m.IPODate, m.IPODate.ipo_id == m.IPO.id)
            .join(m.ApplicantGuide, m.ApplicantGuide.ipo_id == m.IPO.id)
            .join(m.Company, m.Company.id == m.IPO.company_id)
            .where(
                m.Company.is_demo.is_(False),
                m.IPO.status.in_(["OPEN", "UPCOMING"]),
                m.IPODate.open_date <= day,
                m.IPODate.close_date >= day,
                m.ApplicantGuide.verification_status == "VERIFIED",
                m.ApplicantGuide.schedule_status == "CONFIRMED",
            )
            .order_by(m.IPODate.close_date, m.Company.name, m.IPO.id)
        )
    ).all()
    for ipo, dates, guide, company in rows:
        if ipo_id and ipo.id != ipo_id:
            continue
        if opening and dates.open_date != day:
            continue
        host = (urlsplit(guide.source_url).hostname or "").lower()
        if not any(
            host == domain or host.endswith("." + domain)
            for domain in ("nseindia.com", "bseindia.com", "ipoalerts.in")
        ):
            continue
        if (
            not ipo.source_timestamp
            or not now - timedelta(hours=settings().x_max_age_hours)
            <= utc(ipo.source_timestamp)
            <= now
        ):
            continue
        if not guide.reviewed_on or not day - timedelta(days=30) <= guide.reviewed_on <= day:
            continue
        if (ipo.raw_status or "").upper() in ("CANCELLED", "POSTPONED", "WITHDRAWN"):
            continue
        name = " ".join(company.name.split())[:80]
        # No mentions/hashtags supplied by external source names.
        name = name.replace("@", "").replace("#", "")
        text = f"MeraIPO | {day:%d %b %Y}\nIPO watch: {name}\nOpen for subscription; closes {dates.close_date:%d %b}.\nSource: {host}\nResearch details: https://www.meraipo.com/ipo/{company.slug}\nFor information, not investment advice."
        if opening:
            text = f"IPO opens today | {day:%d %b %Y}\n{name}\nCloses {dates.close_date:%d %b}.\nhttps://www.meraipo.com/ipo/{company.slug}\nGMP is unofficial; returns are not guaranteed."
        if weighted_length(text) > 280:
            continue
        return text, {
            "ipo_id": ipo.id,
            "source_url": guide.source_url,
            "source_timestamp": ipo.source_timestamp.isoformat(),
            "reviewed_on": guide.reviewed_on.isoformat(),
            "open_date": dates.open_date.isoformat(),
            "close_date": dates.close_date.isoformat(),
            "generated_at": now.isoformat(),
        }
    raise x_api.XError("NO_FRESH_VERIFIED_IPO")


async def generate(db):
    day = m.now().astimezone(IST).date()
    row = await db.scalar(
        select(m.XPost).where(m.XPost.trading_date == day, m.XPost.kind == "IPO_BRIEF")
    )
    if row and row.status not in ("BLOCKED", "DRAFT", "FAILED"):
        return row
    if row is None:
        row = m.XPost(trading_date=day, dedupe_key=f"IPO_BRIEF:{day}", content="", evidence={})
        db.add(row)
    try:
        text, evidence = await snapshot(db)
        row.content, row.evidence = text, evidence
        row.content_hash = hashlib.sha256(text.encode()).hexdigest()
        row.status, row.error_code = "DRAFT", None
    except x_api.XError as exc:
        row.status, row.error_code = "BLOCKED", exc.code
    row.approved_at = row.approved_by = None
    await db.commit()
    return row


async def publish(db, key):
    c = settings()
    row = await db.get(m.XPost, key)
    a = await account(db)
    if not c.x_enabled or not a.tokens:
        raise x_api.XError("X_DISABLED_OR_DISCONNECTED")
    if not row or row.status not in ("APPROVED", "QUEUED"):
        raise x_api.XError("APPROVAL_REQUIRED")
    if not row.approved_at and (
        row.kind in ("MANUAL", "MARKET_TEST", "IPO_TEST")
        or not a.auto_publish
        or (
            row.kind == "MARKET_DAILY"
            and not schedules(a)["MARKET_DAILY"].get("auto_publish", False)
        )
    ):
        raise x_api.XError("APPROVAL_REQUIRED")
    if row.trading_date != m.now().astimezone(IST).date():
        raise x_api.XError("DRAFT_EXPIRED")
    await validate_post(db, row)
    if row.attempts >= c.x_daily_attempt_limit:
        raise x_api.XError("DAILY_ATTEMPT_LIMIT")
    month = row.trading_date.replace(day=1)
    attempts = await db.scalar(
        select(func.coalesce(func.sum(m.XPost.attempts), 0)).where(m.XPost.trading_date >= month)
    )
    if attempts >= c.x_monthly_post_limit:
        raise x_api.XError("MONTHLY_ATTEMPT_LIMIT")
    token = await x_api.access_token(db, a)
    user = await x_api.identity(token)
    if user["id"] != a.user_id:
        raise x_api.XError("ACCOUNT_ID_CHANGED")
    media_id = None
    if row.image_png:
        # Persist a reservation before media upload too: failures cannot burn unlimited calls.
        row.status, row.attempted_at = "SENDING", m.now()
        row.attempts += 1
        await db.commit()
        try:
            upload = await x_api.request(
                "POST",
                "/2/media/upload",
                headers={"Authorization": "Bearer " + token},
                json={
                    "media": base64.b64encode(row.image_png).decode("ascii"),
                    "media_type": "image/png",
                    "media_category": "tweet_image",
                },
            )
            media_id = upload.get("data", {}).get("id")
            if (
                not media_id
                or not str(media_id).isdigit()
                or upload.get("data", {}).get("processing_info", {}).get("state")
                not in (None, "succeeded")
            ):
                raise x_api.XError("MEDIA_NOT_READY")
        except x_api.XError as exc:
            row.status, row.error_code = "FAILED", exc.code
            row.api_status, row.request_id = exc.status, exc.request_id
            await db.commit()
            return row
    row.status, row.attempted_at = "SENDING", m.now()
    if not row.image_png:
        row.attempts += 1
    await db.commit()  # Crash after this point is uncertain; never automatically resend.
    try:
        result = await x_api.request(
            "POST",
            "/2/tweets",
            headers={"Authorization": "Bearer " + token},
            json={
                "text": row.content,
                **({"media": {"media_ids": [str(media_id)]}} if media_id else {}),
            },
        )
        post_id = result.get("data", {}).get("id", "")
        if not isinstance(post_id, str) or not post_id.isdigit():
            raise x_api.XError("INVALID_RESPONSE")
        row.post_id, row.published_at, row.status = post_id, m.now(), "PUBLISHED"
        row.error_code = None
    except x_api.XError as exc:
        row.status = "FAILED" if exc.status and 400 <= exc.status < 500 else "UNCERTAIN"
        row.error_code, row.api_status, row.request_id = exc.code, exc.status, exc.request_id
    await db.commit()
    return row
