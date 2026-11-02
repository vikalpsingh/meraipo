"""Cumulative GMP preferences and private, confirmation-gated subscriber profiles."""

import re
from datetime import timedelta

from sqlalchemy import select

from packages.database import models as m
from packages.shared.calculations import utc
from packages.shared.config import settings

CATEGORY_LABELS = {
    "white": "All IPOs",
    "light_green": "Above 20%",
    "strong_green": "Above 40%",
    "gold": "Above 100%",
}
BANDS = ("white", "light_green", "strong_green", "gold")


def validate_profile(body):
    profile = {}
    for name in ("first_name", "last_name"):
        value = body.get(name)
        if (
            not isinstance(value, str)
            or not 1 <= len(value.strip()) <= 80
            or any(ord(c) < 32 for c in value)
        ):
            raise ValueError("Invalid name")
        profile[name] = value.strip()
    band = body.get("gmp_band")
    if band not in BANDS:
        raise ValueError("Select one GMP band")
    phone = body.get("phone") or ""
    if not isinstance(phone, str):
        raise ValueError("Invalid phone")
    phone = phone.strip()
    if phone and (
        len(phone) > 24
        or not re.fullmatch(r"\+?[0-9 ()-]+", phone)
        or not 7 <= len(re.sub(r"\D", "", phone)) <= 15
    ):
        raise ValueError("Invalid phone")
    profile.update(phone=phone or None, gmp_band=band)
    return profile


def band_for_percent(percent):
    if percent is None or percent <= 20:
        return "white"
    if percent <= 40:
        return "light_green"
    if percent <= 100:
        return "strong_green"
    return "gold"


async def current_band(db, ipo):
    latest = await db.scalar(
        select(m.GMP)
        .where(m.GMP.ipo_id == ipo.id, m.GMP.observed_at <= m.now())
        .order_by(m.GMP.observed_at.desc(), m.GMP.created_at.desc(), m.GMP.id.desc())
        .limit(1)
    )
    if (
        not latest
        or latest.value is None
        or not ipo.price_high
        or ipo.price_high <= 0
        or utc(latest.observed_at) < m.now() - timedelta(hours=settings().gmp_ttl_hours)
    ):
        return "white"
    return band_for_percent(latest.value / ipo.price_high * 100)


def matching_preferences(band):
    """White means all IPOs; higher thresholds include every higher band."""
    return BANDS[: BANDS.index(band) + 1]
