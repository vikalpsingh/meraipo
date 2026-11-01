"""Fail-closed production gate shared by administrator and dispatcher."""

from datetime import timedelta

from packages.database import models as m
from packages.providers.ses_readiness import config_hash, readiness
from packages.shared.calculations import utc
from packages.shared.config import settings
from packages.shared.email_alerts import control, feature_enabled


async def production_checks(db, refresh=False):
    c = settings()
    state = await control(db)
    aws = await readiness(refresh)
    test = await db.get(m.EmailDelivery, state.test_delivery_id) if state.test_delivery_id else None
    checks = {
        "server_permission": c.ipo_email_sending_enabled,
        "signup_feature": await feature_enabled(db),
        "aws_readiness": aws["ready"],
        "scheduler_healthy": bool(
            state.scheduler_seen_at
            and utc(state.scheduler_seen_at) > m.now() - timedelta(minutes=3)
        ),
        "unsubscribe_verified": bool(test and test.unsubscribed_at),
        "test_received": bool(
            test
            and test.kind == "TEST"
            and test.delivered_at
            and test.status not in ("BOUNCED", "COMPLAINT", "FAILED", "REJECTED", "SUPPRESSED")
            and state.test_received_at
            and state.test_config_hash == config_hash()
        ),
    }
    return state, {"ready": all(checks.values()), "checks": checks, "aws": aws}
