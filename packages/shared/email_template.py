"""Shared, escaped pre-listing HTML/text for preview, tests and production mail."""

from datetime import timedelta
from html import escape
from zoneinfo import ZoneInfo

from sqlalchemy import select

from packages.database import models as m
from packages.shared.calculations import utc
from packages.shared.config import settings

IST = ZoneInfo("Asia/Kolkata")


def eligible_listing(ipo, dates, guide, today):
    return bool(
        dates
        and dates.listing_date == today + timedelta(days=1)
        and ipo.status.upper() in ("CLOSED", "UPCOMING", "OPEN")
        and (ipo.raw_status or "").upper() not in ("CANCELLED", "POSTPONED", "WITHDRAWN")
        and guide
        and guide.schedule_status == "CONFIRMED"
        and guide.verification_status == "VERIFIED"
    )


def eligible_opening(ipo, dates, guide, today):
    return bool(
        dates
        and dates.open_date == today
        and ipo.status.upper() in ("OPEN", "UPCOMING")
        and (ipo.raw_status or "").upper() not in ("CANCELLED", "POSTPONED", "WITHDRAWN")
        and guide
        and guide.schedule_status == "CONFIRMED"
        and guide.verification_status == "VERIFIED"
    )


async def content(db, ipo_id, public_url, unsubscribe_url, test=False, opening=False):
    ipo = await db.get(m.IPO, ipo_id)
    if not ipo:
        raise ValueError("IPO_NOT_FOUND")
    company = await db.get(m.Company, ipo.company_id)
    dates = await db.scalar(select(m.IPODate).where(m.IPODate.ipo_id == ipo_id))
    gmp = await db.scalar(
        select(m.GMP)
        .where(m.GMP.ipo_id == ipo_id, m.GMP.observed_at <= m.now())
        .order_by(m.GMP.observed_at.desc(), m.GMP.created_at.desc())
        .limit(1)
    )
    subscription = await db.scalar(
        select(m.Subscription)
        .where(m.Subscription.ipo_id == ipo_id, m.Subscription.observed_at <= m.now())
        .order_by(m.Subscription.observed_at.desc())
        .limit(1)
    )
    price = (
        ipo.price_high
        if opening
        else (ipo.issue_price if ipo.issue_price is not None else ipo.price_high)
    )
    price_label = (
        "Issue price"
        if ipo.issue_price is not None and not opening
        else "Upper price band (assumption)"
    )
    premium = gmp.value if gmp else None
    percent = premium / price * 100 if premium is not None and price and price > 0 else None
    stale = bool(gmp and m.now() - utc(gmp.observed_at) > timedelta(hours=settings().gmp_ttl_hours))

    def money(n):
        return f"₹{n:,.2f}" if n is not None else "N/A"

    rows = [
        (
            "Opening date" if opening else "Listing date",
            str(dates.open_date if opening else dates.listing_date) if dates else "N/A",
        ),
        (price_label, money(price)),
        ("Unofficial GMP", money(premium) + (" · stale snapshot" if stale else "")),
        ("GMP-implied gain (assumption)", f"{percent:+.2f}%" if percent is not None else "N/A"),
    ]
    if subscription and subscription.multiple is not None:
        rows.append(
            (
                "Subscription",
                f"{subscription.multiple:.2f}× (as of {utc(subscription.observed_at).astimezone(IST).strftime('%d %b %Y %H:%M IST')})",
            )
        )
    if gmp:
        rows.append(
            (
                "GMP observed",
                utc(gmp.observed_at).astimezone(IST).strftime("%d %b %Y %H:%M IST")
                + " · "
                + (gmp.source_provider or "source unspecified"),
            )
        )
    rows.append(
        (
            "IPO data updated",
            utc(ipo.source_timestamp or ipo.updated_at)
            .astimezone(IST)
            .strftime("%d %b %Y %H:%M IST"),
        )
    )
    disclaimer = "GMP is unofficial. The estimated gain assumes the stated GMP over the issue price or upper band; it is not a guaranteed listing price or return. IPO investing involves loss risk. Verify dates and data before deciding."
    subject = (
        ("TEST — " if test else "")
        + f"MeraIPO | {company.name} {'Opens Today' if opening else 'Lists Tomorrow'} — Key IPO Details"
    )
    text = (
        subject
        + "\n\n"
        + "\n".join(f"{k}: {v}" for k, v in rows)
        + "\n\n"
        + disclaimer
        + "\nIPO guide: "
        + public_url
        + "\nUnsubscribe: "
        + unsubscribe_url
    )
    cells = "".join(
        f'<tr><td style="padding:10px;border-bottom:1px solid #ddd">{escape(k)}</td><td style="padding:10px;border-bottom:1px solid #ddd">{escape(v)}</td></tr>'
        for k, v in rows
    )
    origin = settings().public_origin.rstrip("/")
    markup = f'''<!doctype html><html><head><meta name="viewport" content="width=device-width, initial-scale=1"></head><body style="margin:0;background:#f4f6f8;font-family:Arial,sans-serif;color:#17323d"><table role="presentation" width="100%"><tr><td align="center"><table role="presentation" width="100%" style="max-width:600px;background:white;padding:24px"><tr><td><img src="{escape(origin, quote=True)}/meraipo-logo-market-header.png" width="240" height="80" alt="MeraIPO"><h1 style="font-size:24px">{escape(subject)}</h1><table width="100%">{cells}</table><p><a style="display:inline-block;padding:14px;background:#146b59;color:white" href="{escape(public_url, quote=True)}">Read the IPO guide</a></p><p style="font-size:13px">{escape(disclaimer)}</p><p><a href="{escape(unsubscribe_url, quote=True)}">Unsubscribe from IPO alerts</a></p></td></tr></table></td></tr></table></body></html>'''
    return {"subject": subject, "text": text, "html": markup}
