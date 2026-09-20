from datetime import timedelta

from packages.shared.calculations import utc

SLOTS = {
    "sync-ipos": [(23, 0)],
    "sync-prices": [(23, 10)],
    "sync-results": [(21, 0)],
    "collect-ipos": [(7, 0)],
    "publish-ipos": [(7, 15)],
    "collect-prices": [(18, 45)],
    "publish-prices": [(19, 0)],
    "collect-results": [(21, 0)],
    "publish-results": [(21, 30)],
    "ipo-master": [(7, 0)],
    "ipo-live": [(10, 30), (12, 30), (14, 30), (16, 0), (17, 30)],
    "eod-prices": [(18, 15)],
    "results": [(19, 0)],
    "reconcile": [(22, 30)],
}


def next_scheduled(job, at, holidays=()):
    for offset in range(15):
        day = at + timedelta(days=offset)
        if job in ("collect-results", "publish-results", "sync-results") and day.weekday() != 4:
            continue
        if job in ("eod-prices", "collect-prices", "publish-prices", "sync-prices") and (
            day.weekday() >= 5 or day.date().isoformat() in holidays
        ):
            continue
        for hour, minute in SLOTS.get(job, []):
            candidate = day.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if candidate > at:
                return candidate.isoformat()
    return None


def freshness(kind, observed_at, at, *, active=True, failed=False, holidays=()):
    """Results are event-driven; freshness describes scan health, not filing age."""
    if not active:
        return "NOT_EXPECTED"
    if failed:
        return "ERROR"
    if observed_at is None:
        return "STALE"
    if kind == "prices":
        expected = at.date()
        # Before EOD, yesterday is the latest expected trading date.
        if (at.hour, at.minute) < (18, 15):
            expected -= timedelta(days=1)
        while expected.weekday() >= 5 or expected.isoformat() in holidays:
            expected -= timedelta(days=1)
        return "FRESH" if observed_at.date() >= expected else "STALE"
    age = (utc(at) - utc(observed_at)).total_seconds() / 3600
    limit = 4 if kind in ("subscriptions", "gmp") else 8 * 24 if kind == "results" else 26
    return "FRESH" if age <= limit else "AGING" if age <= limit * 2 else "STALE"
