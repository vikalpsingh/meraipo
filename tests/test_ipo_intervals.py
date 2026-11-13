from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from apps.api.job_routes import ScheduleInput
from packages.shared.job_schedules import is_due, next_slot

IST = ZoneInfo("Asia/Kolkata")


@pytest.mark.parametrize("hours", [1, 2, 4, 6, 12, 24])
def test_interval_slots(hours):
    state = dict(times=["07:15"], frequency="hourly", interval_hours=hours)
    actual = [h for h in range(24) if is_due(state, datetime(2026, 11, 13, h, 15, tzinfo=IST))]
    assert actual == [h for h in range(24) if (h - 7) % hours == 0]
    assert not is_due(state, datetime(2026, 11, 13, 7, 16, tzinfo=IST))


@pytest.mark.parametrize(
    "saturday,sunday,day", [(False, False, 16), (True, False, 14), (False, True, 15)]
)
def test_next_run_skips_disabled_weekends(saturday, sunday, day):
    at = datetime(2026, 11, 13, 19, 0, tzinfo=IST)
    result = next_slot(["07:00"], at, "hourly", 0, 12, saturday, sunday)
    assert result == f"2026-11-{day}T07:00:00+05:30"


def test_rejects_unsupported_interval():
    with pytest.raises(ValidationError):
        ScheduleInput(times=["07:00"], paused=False, frequency="hourly", interval_hours=3)
