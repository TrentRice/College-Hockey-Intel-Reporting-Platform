import datetime as dt

import pytest

from src.dashboard.logic import (
    LOWER_IS_BETTER,
    TEAM_STATS,
    comparison_rows,
    default_last,
    delta_value,
    difference_tones,
    direction,
    fmt,
    fmt_delta,
    game_label,
    is_zero,
    meetings,
    next_game,
    record_pct,
    side_by_side,
    streak_score,
)


@pytest.mark.parametrize(
    "value, kind, expected",
    [
        (0.2345, "pct", "23.4%"),
        (3.6, "num", "3.60"),
        ("7-3-0", "text", "7-3-0"),
        (None, "pct", "–"),
    ],
)
def test_fmt(value, kind, expected):
    assert fmt(value, kind) == expected


def test_deltas():
    assert fmt_delta(0.231, 0.300, "pct") == "-6.9 pts"
    assert fmt_delta(3.6, 4.5, "num") == "-0.90"
    assert fmt_delta("3-2-0", "7-3-0", "text") is None
    assert fmt_delta(None, 0.5, "pct") is None
    assert is_zero("+0.00") and is_zero("-0.0 pts") and not is_zero("+0.40")


@pytest.mark.parametrize("played, expected", [(1, 1), (4, 4), (5, 5), (12, 5)])
def test_default_last_never_exceeds_games_played(played, expected):
    assert default_last(played) == expected


def g(game_id, date, played, opp=2, **extra):
    return {
        "game_id": game_id, "date": date, "is_played": played, "is_home": True, "is_neutral": False,
        "opponent": {"team_id": opp, "name": f"Team {opp}"} if opp else None, **extra,
    }  # fmt: skip


def test_next_game_is_the_first_unplayed_one_from_today():
    sched = [g("a", "2026-11-07", True), g("b", "2026-11-13", False), g("c", "2026-11-20", False)]
    assert next_game(sched, dt.date(2026, 11, 14))["game_id"] == "c"  # b was postponed: in the past
    assert next_game(sched, dt.date(2026, 12, 1)) is None


def test_meetings():
    sched = [
        g("a", "2026-11-07", True, opp=2),
        g("b", "2026-11-08", True, opp=3),
        g("c", "2026-12-01", False),
    ]
    assert [m["game_id"] for m in meetings(sched, 2)] == ["a"]


def test_comparison_rows_show_season_only_when_partial():
    win = {"record": "3-2-0", "pp_pct": 0.231}
    season = {"record": "7-3-0", "pp_pct": 0.3}
    rows = {r["Stat"]: r for r in comparison_rows(win, season)}
    assert rows["Power play %"] == {
        "Stat": "Power play %",
        "Last N": "23.1%",
        "Season": "30.0%",
        "Difference": -6.9,  # a number, so the column sorts by value
    }
    assert rows["Record"]["Difference"] is None
    assert "Season" not in comparison_rows(win, None)[0]


Q = {
    "record": "3-2-0",
    "streak": "L1",
    "win_pct": 0.6,
    "goals_for_per_game": 3.6,
    "goals_against_per_game": 2.8,
    "shots_against_per_game": 24.4,
    "pim_per_game": 15.0,
    "times_shorthanded_per_game": 4.4,
    "pp_pct": 0.2,
    "save_pct": 0.8851,
    "home_record": "1-2-0",
    "away_record": "2-0-0",
    "xg_share": None,
}
BU = {
    "record": "6-4-0", "streak": "L2", "win_pct": 0.6, "goals_for_per_game": 4.2,
    "goals_against_per_game": 3.4, "shots_against_per_game": 32.2, "pim_per_game": 9.0,
    "times_shorthanded_per_game": 2.2, "pp_pct": 0.2, "save_pct": 0.8849,
    "home_record": "2-1-0", "away_record": "0-0-0", "xg_share": 0.5,
}  # fmt: skip


def test_every_stat_gets_a_better_value():
    rows = {r["Stat"]: r["Better"] for r in side_by_side(Q, BU, "Quinnipiac", "BU")}
    assert len(rows) == len(TEAM_STATS) and all(rows.values())
    assert rows["Goals for / game"] == "BU"
    # lower is better for these four
    assert rows["Goals against / game"] == "Quinnipiac"
    assert rows["Shots against / game"] == "Quinnipiac"
    assert rows["Times shorthanded / game"] == "BU"
    assert rows["PIM / game"] == "BU"
    # text stats
    assert rows["Record"] == "Tie"  # 3-2-0 and 6-4-0 are both .600
    assert rows["Streak"] == "Quinnipiac"  # L1 beats L2
    assert rows["Home"] == "BU"
    assert rows["Away"] == "n/a"  # BU has no away games to compare
    assert rows["xG share"] == "n/a"
    # ties are judged as displayed: 88.5% vs 88.5%
    assert rows["Power play %"] == "Tie" and rows["Save %"] == "Tie"


@pytest.mark.parametrize(
    "streak, score", [("W3", 3), ("W1", 1), ("T2", 0), ("L1", -1), ("L4", -4), (None, None)]
)
def test_streak_order(streak, score):
    assert streak_score(streak) == score


@pytest.mark.parametrize("record, pct", [("3-2-0", 0.6), ("2-1-1", 0.625), ("0-0-0", None)])
def test_record_pct(record, pct):
    assert record_pct(record) == pct


def test_difference_tones_follow_better_not_up():
    window = {
        "goals_for_per_game": 3.6,
        "goals_against_per_game": 2.8,
        "pim_per_game": 16.0,
        "pp_pct": 0.3,
    }
    season = {
        "goals_for_per_game": 4.5,
        "goals_against_per_game": 3.1,
        "pim_per_game": 15.0,
        "pp_pct": 0.3,
    }
    tones = dict(zip([s.label for s in TEAM_STATS], difference_tones(window, season), strict=True))
    assert tones["Goals for / game"] == "worse"  # down, higher is better
    assert tones["Goals against / game"] == "better"  # down, lower is better
    assert tones["PIM / game"] == "worse"  # up, lower is better
    assert tones["Power play %"] == ""  # no change
    assert tones["Record"] == ""  # text rows have no difference to color


def test_lower_is_better_list():
    assert LOWER_IS_BETTER == [
        "Goals against / game", "Shots against / game", "Times shorthanded / game", "PIM / game",
    ]  # fmt: skip


@pytest.mark.parametrize(
    "game, label",
    [
        (
            {
                "result": "W",
                "goals_for": 4,
                "goals_against": 1,
                "ot_periods": 0,
                "shootout_won": None,
            },
            "W 4-1",
        ),
        (
            {
                "result": "L",
                "goals_for": 3,
                "goals_against": 4,
                "ot_periods": 1,
                "shootout_won": None,
            },
            "L 3-4 OT",
        ),
        (
            {
                "result": "T",
                "goals_for": 3,
                "goals_against": 3,
                "ot_periods": 1,
                "shootout_won": False,
            },
            "T 3-3 SO (lost)",
        ),
    ],
)
def test_game_label(game, label):
    assert game_label(game) == label


@pytest.mark.parametrize(
    "delta, expected",
    [("+1.8 pts", 1), ("-6.9 pts", -1), ("+0.40", 1), ("-0.90", -1), ("+0.00", 0), ("", 0)],
)
def test_direction_drives_the_difference_colors(delta, expected):
    assert direction(delta) == expected


@pytest.mark.parametrize(
    "window, season, kind, expected",
    [
        (0.231, 0.300, "pct", -6.9),
        (1.2, 1.1, "num", 0.1),
        (0.6, 0.6, "num", 0.0),
        (0.30000001, 0.3, "pct", 0.0),
        (None, 0.5, "pct", None),
        ("3-2-0", "7-3-0", "text", None),
    ],
)
def test_delta_values_are_numbers_rounded_as_shown(window, season, kind, expected):
    value = delta_value(window, season, kind)
    assert value == expected
    if value == 0:
        assert str(value) == "0.0"  # never "-0.0"


def test_differences_sort_by_value_not_text():
    values = [delta_value(w, s, "num") for w, s in [(1.2, 1.1), (0.6, 1.4), (0.8, 0.4), (0.5, 0.6)]]
    assert sorted(values) == [-0.8, -0.1, 0.1, 0.4]  # as text, "-0.10" would sort before "-0.80"
