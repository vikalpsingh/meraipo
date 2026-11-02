"""Shared, escaped pre-listing HTML/text for preview, tests and production mail."""

import base64
import struct
import zlib
from datetime import timedelta
from html import escape
from zoneinfo import ZoneInfo

from sqlalchemy import select

from packages.database import models as m
from packages.shared.calculations import utc
from packages.shared.config import settings
from packages.shared.email_preferences import (
    CATEGORY_LABELS,
    band_for_percent,
    matching_preferences,
)

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


def price_chart_png(price, implied):
    """Draw two proportional bars on a shared zero-based scale as an indexed PNG."""
    width = 540
    maximum = max(price, implied)

    def bar_row(amount, colour):
        pixels = round(width * amount / maximum)
        return bytes([0]) + bytes([colour]) * pixels + bytes([1]) * (width - pixels)

    gap = bytes(width + 1)
    pixels = bar_row(price, 2) * 12 + gap * 6 + bar_row(implied, 3) * 12
    palette = bytes.fromhex("103c3d 285350 89b5ad") + bytes.fromhex(
        "77e1bb" if implied >= price else "ffb6a5"
    )

    def chunk(kind, data):
        return (
            struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
        )

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, 30, 8, 3, 0, 0, 0))
        + chunk(b"PLTE", palette)
        + chunk(b"IDAT", zlib.compress(pixels))
        + chunk(b"IEND", b"")
    )


async def content(
    db,
    ipo_id,
    public_url,
    unsubscribe_url,
    test=False,
    opening=False,
    inline_attachment=False,
    test_category=None,
):
    ipo = await db.get(m.IPO, ipo_id)
    if not ipo:
        raise ValueError("IPO_NOT_FOUND")
    company = await db.get(m.Company, ipo.company_id)
    dates = await db.scalar(select(m.IPODate).where(m.IPODate.ipo_id == ipo_id))
    rendered_at = m.now()
    gmp = await db.scalar(
        select(m.GMP)
        .where(m.GMP.ipo_id == ipo_id, m.GMP.observed_at <= rendered_at)
        .order_by(m.GMP.observed_at.desc(), m.GMP.created_at.desc(), m.GMP.id.desc())
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
    stale = bool(
        gmp and rendered_at - utc(gmp.observed_at) > timedelta(hours=settings().gmp_ttl_hours)
    )

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
    if test_category:
        label = CATEGORY_LABELS[test_category]
        subject = f"TEST — {label} | {company.name} | MeraIPO"
        matches = test_category in matching_preferences(
            band_for_percent(None if stale else percent)
        )
        rows.insert(0, ("Test category", label))
        rows.insert(1, ("Latest GMP matches this preference", "Yes" if matches else "No"))
    origin = settings().public_origin.rstrip("/")
    campaign = "ipo_opening" if opening else "ipo_prelisting"
    homepage = f"{origin}/?utm_source=meraipo_email&utm_medium=email&utm_campaign={campaign}&utm_content=homepage"
    png = None
    same_day = (
        gmp and utc(gmp.observed_at).astimezone(IST).date() == rendered_at.astimezone(IST).date()
    )
    if same_day and percent is not None and not stale and price + premium >= 0:
        implied = price + premium
        rows.insert(4, ("GMP-implied price per share", money(implied)))
        png = price_chart_png(price, implied)
        src = (
            "cid:ipo-price-chart"
            if inline_attachment
            else "data:image/png;base64," + base64.b64encode(png).decode("ascii")
        )
        stamp = utc(gmp.observed_at).astimezone(IST).strftime("%d %b %Y, %I:%M %p IST")
        chart = (
            f"<p><strong>Price per share · {percent:+.2f}% implied change</strong></p>"
            f"<p>Upper bar · {price_label}: {money(price)}<br>Lower bar · GMP-implied price: {money(implied)}</p>"
            f'<img src="{src}" width="540" height="30" alt="Price comparison" style="display:block;width:100%;max-width:540px;height:auto">'
            f'<p style="font-size:13px">GMP observed {stamp}</p>'
        )
    else:
        chart = '<p style="margin:0">A current price comparison for today is unavailable.</p>'
    text = (
        subject
        + "\n\n"
        + "\n".join(f"{k}: {v}" for k, v in rows)
        + "\n\n"
        + disclaimer
        + "\nIPO guide: "
        + public_url
        + "\nVisit MeraIPO.com: "
        + homepage
        + "\nUnsubscribe: "
        + unsubscribe_url
    )
    cells = "".join(
        f'<tr><th scope="row" align="left" style="padding:10px 6px;border-bottom:1px solid #dce5e2;font-weight:normal">{escape(k)}</th>'
        f'<td style="padding:10px 6px;border-bottom:1px solid #dce5e2">{escape(v)}</td></tr>'
        for k, v in rows
    )
    home_link = escape(homepage, quote=True)
    edition = ("TEST · " if test else "") + ("Opening day" if opening else "Listing tomorrow")
    if test_category:
        edition = f"Category test · {CATEGORY_LABELS[test_category]}"
    markup = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;background:#edf3f1;font-family:Arial,Helvetica,sans-serif;color:#193b36">
<table width="100%" role="presentation" cellspacing="0" cellpadding="0"><tr><td align="center">
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="max-width:600px;background:#fff;text-align:left">
<tr><td style="padding:12px 24px"><a href="{home_link}"><img src="{escape(origin)}/meraipo-logo-market-header.png" width="180" height="60" alt="Visit MeraIPO.com" style="display:block;border:0"></a></td></tr>
<tr><td bgcolor="#103c3d" style="color:#fff;padding:24px">
<p style="margin:0;color:#b7f2dc;font-size:13px">MERAIPO MARKET WATCH &nbsp; · &nbsp; {edition}</p>
<h1 style="margin:10px 0 18px;font-size:26px;line-height:1.2">{escape(company.name)}</h1>
{chart}</td></tr>
<tr><td style="padding:20px 24px"><h2 style="margin:0;font-size:18px">IPO snapshot</h2>
<table width="100%" cellspacing="0" cellpadding="0" style="font-size:14px">{cells}</table>
<p style="margin:22px 0"><a href="{escape(public_url)}" style="display:inline-block;padding:13px 18px;background:#12624b;color:#fff;text-decoration:none;border-radius:6px;font-weight:bold">Read the IPO guide &#8599;</a></p>
<p><a href="{home_link}" style="color:#12624b">Explore more IPOs on MeraIPO.com &#8599;</a></p>
<p style="font-size:13px;line-height:1.5;color:#47605b">{escape(disclaimer)}</p></td></tr>
<tr><td bgcolor="#f2f6f4" style="padding:16px 24px;font-size:13px"><a style="color:#355a50" href="{escape(unsubscribe_url)}">Unsubscribe from IPO alerts</a></td></tr>
</table></td></tr></table></body></html>"""
    result = {"subject": subject, "text": text, "html": markup}
    if inline_attachment and png:
        result["chart_png"] = png
    return result
