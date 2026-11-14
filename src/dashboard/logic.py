"""Plain helpers behind the dashboard: no Streamlit here, so they're easy to test."""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

DEFAULT_LAST = 5


def record_pct(record: str | None) -> float | None:
    """'3-2-0' -> win % counting ties as half; None when there are no games."""
    if not record:
        return None
    w, lo, t = (int(x) for x in record.split("-"))
    games = w + lo + t
    return (w + 0.5 * t) / games if games else None


def streak_score(streak: str | None) -> int | None:
    """'W3' -> 3, 'L2' -> -2, 'T1' -> 0: any win streak beats a tie beats any losing streak."""
    if not streak:
        return None
    n = int(streak[1:])
    return {"W": n, "L": -n, "T": 0}[streak[0]]


@dataclass(frozen=True)
class Stat:
    key: str
    label: str
    kind: str  # pct | num | text
    higher_is_better: bool = True
    score: Callable[[Any], float | None] | None = None  # how a text stat is compared


TEAM_STATS = [
    Stat("record", "Record", "text", score=record_pct),
    Stat("win_pct", "Win %", "pct"),
    Stat("streak", "Streak", "text", score=streak_score),
    Stat("goals_for_per_game", "Goals for / game", "num"),
    Stat("goals_against_per_game", "Goals against / game", "num", higher_is_better=False),
    Stat("goal_diff_per_game", "Goal diff / game", "num"),
    Stat("shots_for_per_game", "Shots for / game", "num"),
    Stat("shots_against_per_game", "Shots against / game", "num", higher_is_better=False),
    Stat("shot_share", "Shot share", "pct"),
    Stat("xg_share", "xG share", "pct"),
    Stat("shooting_pct", "Shooting %", "pct"),
    Stat("save_pct", "Save %", "pct"),
    Stat("pp_pct", "Power play %", "pct"),
    Stat("pk_pct", "Penalty kill %", "pct"),
    Stat("pp_opportunities_per_game", "PP chances / game", "num"),
    Stat("times_shorthanded_per_game", "Times shorthanded / game", "num", higher_is_better=False),
    Stat("pim_per_game", "PIM / game", "num", higher_is_better=False),
    Stat("faceoff_pct", "Faceoff %", "pct"),
    Stat("home_record", "Home", "text", score=record_pct),
    Stat("away_record", "Away", "text", score=record_pct),
]
LOWER_IS_BETTER = [s.label for s in TEAM_STATS if not s.higher_is_better]


def comparable(stat: Stat, value: Any) -> float | None:
    """The value as it's compared: rounded to what's displayed, so 60.0% vs 60.0% is a tie."""
    if value is None:
        return None
    if stat.score is not None:
        v = stat.score(value)
        return None if v is None else round(v, 3)
    if stat.kind == "pct":
        return round(value * 100, 1)
    if stat.kind == "num":
        return round(value, 2)
    return None


HEADLINE = [
    "goals_for_per_game",
    "goals_against_per_game",
    "shot_share",
    "pp_pct",
    "pk_pct",
    "save_pct",
]


def fmt(value: Any, kind: str) -> str:
    if value is None:
        return "–"
    if kind == "pct":
        return f"{value * 100:.1f}%"
    if kind == "num":
        return f"{value:.2f}"
    return str(value)


def fmt_delta(window: Any, season: Any, kind: str) -> str | None:
    """'+3.2 pts' style difference, last N minus season; None when not comparable."""
    if window is None or season is None or kind not in ("pct", "num"):
        return None
    d = window - season
    if kind == "pct":
        return f"{d * 100:+.1f} pts"
    return f"{d:+.2f}"


def delta_value(window: Any, season: Any, kind: str) -> float | None:
    """Last N minus season as a number, rounded as displayed (percentage points for pct).
    Numbers, not text, so a table sorts them by value: most negative first one way, most
    positive first the other."""
    if window is None or season is None or kind not in ("pct", "num"):
        return None
    d = round((window - season) * 100, 1) if kind == "pct" else round(window - season, 2)
    return d + 0.0  # no "-0.0"


DELTA_FORMAT = {"pct": "{:+.1f} pts", "num": "{:+.2f}"}


def direction(delta: str) -> int:
    """+1 if the last N is higher than the season, -1 if lower, 0 for no change or blank."""
    if not delta or is_zero(delta):
        return 0
    return 1 if delta.startswith("+") else -1


def is_zero(delta: str) -> bool:
    """'+0.00' or '-0.0 pts' is no change."""
    return float(delta.split()[0]) == 0


def default_last(games_played: int) -> int:
    return min(DEFAULT_LAST, games_played)


def next_game(schedule: list[dict], today: dt.date) -> dict | None:
    """The first unplayed game today or later."""
    upcoming = [
        g for g in schedule
        if not g["is_played"] and dt.date.fromisoformat(str(g["date"])) >= today
    ]  # fmt: skip
    return min(upcoming, key=lambda g: (str(g["date"]), g["game_id"])) if upcoming else None


def meetings(schedule: list[dict], opponent_id: int) -> list[dict]:
    """Played games against one opponent, oldest first."""
    return [
        g for g in schedule
        if g["is_played"] and g["opponent"] and g["opponent"]["team_id"] == opponent_id
    ]  # fmt: skip


def comparison_rows(
    window: dict, season: dict | None, stats: list[Stat] = TEAM_STATS
) -> list[dict]:
    """One row per stat: last N, season (when the window is shorter), and the difference."""
    rows = []
    for s in stats:
        row = {"Stat": s.label, "Last N": fmt(window.get(s.key), s.kind)}
        if season is not None:
            row["Season"] = fmt(season.get(s.key), s.kind)
            row["Difference"] = delta_value(window.get(s.key), season.get(s.key), s.kind)
        rows.append(row)
    return rows


def tone(stat: Stat, now: Any, then: Any) -> str:
    """'better', 'worse' or '' (no change, or nothing to compare)."""
    a, b = comparable(stat, now), comparable(stat, then)
    if a is None or b is None or a == b:
        return ""
    return "better" if (a > b) == stat.higher_is_better else "worse"


def difference_tones(window: dict, season: dict, stats: list[Stat] = TEAM_STATS) -> list[str]:
    """Per comparison row: is the last N better or worse than the season? Text stats ('', no
    difference shown) are left uncolored."""
    return [
        tone(s, window.get(s.key), season.get(s.key)) if s.kind != "text" else "" for s in stats
    ]


TIE = "Tie"
NOT_COMPARABLE = "n/a"


def side_by_side(
    left: dict, right: dict, left_name: str, right_name: str, stats: list[Stat] = TEAM_STATS
) -> list[dict]:
    """Two teams' windows, stat by stat. `Better` names the team ahead on every stat
    (lower is better for goals against, shots against, times shorthanded and PIM), says
    'Tie' when they're level as displayed, and 'n/a' when either side has no value."""
    rows = []
    for s in stats:
        a, b = left.get(s.key), right.get(s.key)
        ca, cb = comparable(s, a), comparable(s, b)
        if ca is None or cb is None:
            better = NOT_COMPARABLE
        elif ca == cb:
            better = TIE
        else:
            better = left_name if (ca > cb) == s.higher_is_better else right_name
        rows.append(
            {
                "Stat": s.label,
                left_name: fmt(a, s.kind),
                right_name: fmt(b, s.kind),
                "Better": better,
            }
        )
    return rows


def describe_game(g: dict) -> str:
    where = "vs" if g["is_home"] else "at"
    if g.get("is_neutral"):
        where = "vs (neutral)"
    opp = g["opponent"]["name"] if g.get("opponent") else "TBD"
    day = dt.date.fromisoformat(str(g["date"]))
    return f"{where} {opp}, {day:%a %b %-d}"


def game_label(g: dict) -> str:
    """'W 4-2 OT' for a played game."""
    extra = ""
    if g.get("shootout_won") is not None:
        extra = " SO" + (" (won)" if g["shootout_won"] else " (lost)")
    elif g.get("ot_periods"):
        extra = " OT"
    return f"{g['result']} {g['goals_for']}-{g['goals_against']}{extra}"
