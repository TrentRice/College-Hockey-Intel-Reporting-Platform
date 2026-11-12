import datetime as dt

import pytest

from src.pipeline.scheduler import EASTERN, should_run


def at(day: str, hhmm: str) -> dt.datetime:
    return dt.datetime.fromisoformat(f"{day}T{hhmm}").replace(tzinfo=EASTERN)


IN_SEASON = "2026-11-11"  # a Wednesday


@pytest.mark.parametrize(
    "now, runs, expected",
    [
        (at(IN_SEASON, "04:59"), [], False),  # too early
        (at(IN_SEASON, "05:00"), [], True),
        (at(IN_SEASON, "14:30"), [], True),  # Mac was asleep at 5: catch up
        (at(IN_SEASON, "06:00"), [(at(IN_SEASON, "05:01"), "success")], False),
        (at(IN_SEASON, "05:30"), [(at(IN_SEASON, "05:01"), "running")], False),
        (
            at(IN_SEASON, "05:30"),
            [(at(IN_SEASON, "05:01"), "failed")],
            False,
        ),  # retry waits an hour
        (at(IN_SEASON, "06:05"), [(at(IN_SEASON, "05:01"), "failed")], True),
        (
            at(IN_SEASON, "06:05"),
            [(at(IN_SEASON, "05:01"), "blocked")],
            True,
        ),  # e.g. a late box score
        (
            at(IN_SEASON, "12:00"),
            [(at(IN_SEASON, f"0{h}:00"), "failed") for h in (5, 6, 7)],
            False,  # three strikes: try again tomorrow
        ),
        (at("2026-06-10", "06:00"), [], False),  # off-season Wednesday
        (at("2026-06-08", "06:00"), [], True),  # off-season Monday
    ],
)
def test_should_run(now, runs, expected):
    run, reason = should_run(now, runs)
    assert run is expected, reason


def test_eastern_time_is_used_whatever_the_server_clock_says():
    utc_9am = dt.datetime(2026, 11, 11, 9, 0, tzinfo=dt.UTC)  # 4 a.m. Eastern
    assert should_run(utc_9am, [])[0] is False
