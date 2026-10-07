from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from app.core.timeutil import pass_expires_at


@pytest.mark.parametrize("local_hm,expected_day_offset", [
    ((10, 0), 0),          # morning → today 16:30
    ((16, 29), 0),         # just before closing → today 16:30
    ((16, 30), 1),         # at closing → tomorrow 16:30
    ((18, 0), 1),          # evening → tomorrow 16:30
])
def test_pass_expires_at_next_gate_closing(local_hm, expected_day_offset):
    tz = ZoneInfo("Asia/Karachi")
    hour, minute = local_hm
    local = datetime(2026, 10, 7, hour, minute, tzinfo=tz)
    expires = pass_expires_at("Asia/Karachi", hour=16, minute=30, now=local.astimezone(UTC))
    expected_local = datetime(2026, 10, 7 + expected_day_offset, 16, 30, tzinfo=tz)
    assert expires == expected_local.astimezone(UTC)
