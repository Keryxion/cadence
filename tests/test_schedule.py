from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from cadence.model import Wake
from cadence.schedule import (parse_duration, parse_at, next_every, next_cron,
                                 local_day, time_due)


def ts(value):
    return datetime.fromisoformat(value).timestamp()


@pytest.mark.parametrize("text,seconds", [("20m", 1200), ("in 2h", 7200),
    ("+1d 2h 3m 4s", 93784), ("1.5h", 5400), (60, 60)])
def test_duration(text, seconds):
    assert parse_duration(text) == seconds


@pytest.mark.parametrize("text", ["", "0s", "-1h", "junk 2h", "1h junk", True, float("inf")])
def test_bad_duration(text):
    with pytest.raises(ValueError):
        parse_duration(text)


def test_at_relative_iso_and_tomorrow():
    now = ts("2025-10-12T12:00:00+00:00")
    assert parse_at("+20m", now=now, timezone="UTC") == now + 1200
    assert parse_at("in 2h", now=now, timezone="UTC") == now + 7200
    assert parse_at("tomorrow 09:00", now=now, timezone="Asia/Tokyo") == ts("2025-10-13T09:00:00+09:00")
    assert parse_at("2025-10-13T09:00:00", now=now, timezone="Asia/Tokyo") == ts("2025-10-13T09:00:00+09:00")
    assert parse_at("2025-10-13T09:00:00Z", now=now, timezone="Asia/Tokyo") == ts("2025-10-13T09:00:00+00:00")


def test_I1_I3_jump_coalesce_and_catchup():
    wake = Wake("s", "note", "every", next_due_at=100, eff_interval_s=900)
    decision = time_due(wake, now=18100, catch_up_s=21600)
    assert (decision.state, decision.dedupe_key, decision.next_due_at) == ("pending", "t:100", 19000)
    assert time_due(Wake("s", "note", "at", next_due_at=100), now=21701,
                    catch_up_s=21600).state == "missed"
    assert time_due(wake, now=99, catch_up_s=21600) is None


def test_every_jitter_is_explicit_and_anchor_is_local():
    now = ts("2025-10-12T12:00:00+00:00")
    assert next_every(now, 1000) == now + 1000
    assert next_every(now, 1000, jitter_unit=-1) == now + 900
    assert next_every(now, 1000, jitter_unit=1) == now + 1100
    assert next_every(now, 86400, anchor="09:00", timezone="UTC") == ts("2025-10-13T09:00:00+00:00")
    with pytest.raises(ValueError):
        next_every(now, 0)


def test_cron_pure_and_strictly_future():
    now = ts("2025-10-12T12:00:00+00:00")
    assert next_cron("0 9 * * *", now=now, timezone="Asia/Tokyo") == ts("2025-10-13T09:00:00+09:00")
    with pytest.raises(ValueError):
        next_cron("garbage", now=now, timezone="UTC")






def test_cron_interval_floor_and_fractional_dedupe():
    now = ts("2025-10-12T12:00:00+00:00")
    wake = Wake("s", "note", "cron", trigger_json={"cron": "* * * * *"},
                next_due_at=now, eff_interval_s=3600)
    decision = time_due(wake, now=now, catch_up_s=21600)
    assert decision.next_due_at == now + 3600
    a = time_due(Wake("s", "note", "at", next_due_at=now + 0.25), now=now + 1,
                 catch_up_s=21600)
    b = time_due(Wake("s", "note", "at", next_due_at=now + 0.5), now=now + 1,
                 catch_up_s=21600)
    assert a.dedupe_key != b.dedupe_key
