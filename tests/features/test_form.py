import datetime as dt

import psycopg
import pytest

from src.features.form import (
    likely_starter,
    summarize_goalie,
    summarize_team,
    team_form,
)

# ----------------------------------------------------------------------------
# Summaries on made-up rows (newest first)
# ----------------------------------------------------------------------------


def game(
    result,
    gf,
    ga,
    *,
    sf=30,
    sa=30,
    ppg=0,
    ppo=0,
    ppga=0,
    tsh=0,
    home=True,
    neutral=False,
    xg=(2.0, 2.0),
):
    return {
        "result": result,
        "goals_for": gf,
        "goals_against": ga,
        "shots_for": sf,
        "shots_against": sa,
        "pp_goals": ppg,
        "pp_opportunities": ppo,
        "pp_goals_against": ppga,
        "times_shorthanded": tsh,
        "sh_goals": 0,
        "pim": 6,
        "faceoffs_won": 30,
        "faceoffs_lost": 30,
        "is_home": home,
        "is_neutral": neutral,
        "xg_for": xg[0],
        "xg_against": xg[1],
    }


ROWS = [
    game("W", 4, 1, sf=40, sa=20, ppg=2, ppo=4, ppga=0, tsh=3, xg=(3.0, 1.0)),
    game("W", 3, 2, ppg=1, ppo=3, ppga=1, tsh=2, home=False, xg=(None, None)),
    game("T", 2, 2, neutral=True),
    game("L", 0, 3, sf=20, sa=40, ppo=1, ppga=1, tsh=5, home=False, xg=(1.0, 3.0)),
]


def test_team_summary():
    s = summarize_team(ROWS)
    assert (s["games"], s["record"], s["streak"]) == (4, "2-1-1", "W2")
    assert s["win_pct"] == 0.625  # (2 + 0.5) / 4
    assert (s["home_record"], s["away_record"], s["neutral_record"]) == ("1-0-0", "1-1-0", "0-0-1")
    assert (s["goals_for_per_game"], s["goals_against_per_game"]) == (2.25, 2.0)
    assert s["shot_share"] == 0.5  # 120 for, 120 against
    assert s["pp_pct"] == 0.375  # 3 of 8
    assert s["pk_pct"] == 0.8  # 2 PP goals against on 10 times shorthanded
    assert s["xg_share"] == 0.5  # the game with no xG is left out: 6.0 for, 6.0 against
    assert s["save_pct"] == round(1 - 8 / 120, 3)


def test_empty_rates_are_none_not_errors():
    s = summarize_team([game("W", 1, 0, ppo=0, tsh=0)])
    assert s["pp_pct"] is None and s["pk_pct"] is None


def test_goalie_summary():
    s = summarize_goalie([
        {"is_starter": True, "saves": 28, "shots_against": 30, "goals_against": 2, "toi_seconds": 3600},
        {"is_starter": False, "saves": 9, "shots_against": 10, "goals_against": 1, "toi_seconds": 1800},
    ])  # fmt: skip
    assert (s["games"], s["starts"], s["save_pct"], s["gaa"]) == (2, 1, 0.925, 2.0)


def starts(*pairs):
    return [{"player_id": p, "name": f"G{p}", "game_id": g, "is_starter": True} for p, g in pairs]


def test_likely_starter_most_starts_wins():
    recent = ["g5", "g4", "g3", "g2", "g1"]  # newest first
    s = likely_starter(starts((1, "g5"), (2, "g4"), (2, "g3"), (2, "g2"), (1, "g1")), recent)
    assert (s["player_id"], s["starts"], s["of_last"], s["started_last_game"]) == (2, 3, 5, False)


def test_likely_starter_tie_goes_to_the_most_recent():
    recent = ["g4", "g3", "g2", "g1"]
    s = likely_starter(starts((1, "g4"), (2, "g3"), (1, "g2"), (2, "g1")), recent)
    assert (s["player_id"], s["started_last_game"]) == (1, True)


# ----------------------------------------------------------------------------
# Against the test database (tests/api/fixture.sql)
# Home U, 2026-27: g1 Oct 10 W 4-2 at home, g2 Oct 11 T 3-3 away (lost the shootout)
# ----------------------------------------------------------------------------


def form(client, path="form", **params):
    return client.get(f"/v1/teams/1/{path}", params=params)


def test_full_season_has_no_separate_season_totals(client):
    f = form(client).json()
    assert (f["games_played"], f["last"], f["games_used"]) == (2, None, 2)
    assert f["window"]["record"] == "1-0-1"
    assert f["season_totals"] is None
    assert [g["game_id"] for g in f["games"]] == ["g2", "g1"]  # newest first


def test_last_n_comes_with_season_totals(client):
    f = form(client, last=1).json()
    assert (f["games_used"], f["window"]["record"], f["window"]["streak"]) == (1, "0-0-1", "T1")
    assert f["season_totals"]["record"] == "1-0-1"
    assert f["window"]["pp_pct"] == 0.5 and f["season_totals"]["pp_pct"] == pytest.approx(
        2 / 6, abs=1e-3
    )
    assert [g["game_id"] for g in f["games"]] == ["g2"]


def test_last_n_is_capped_at_games_played(client):
    f = form(client, last=50).json()
    assert (f["last"], f["games_used"], f["season_totals"]) == (50, 2, None)


@pytest.mark.parametrize("last", [0, -3])
def test_last_must_be_positive(client, last):
    assert form(client, last=last).status_code == 422


def test_as_of_uses_only_earlier_games(client):
    f = form(client, as_of="2026-10-11").json()  # g2 is on Oct 11: not before
    assert (f["games_played"], f["window"]["record"]) == (1, "1-0-0")
    assert form(client, as_of="2026-10-10").status_code == 404  # nothing before Oct 10


def test_rest_days(client):
    g2, g1 = form(client).json()["games"]
    assert (g1["rest_days"], g2["rest_days"]) == (None, 1)
    assert g2["shootout_won"] is False


def test_player_form_window_and_season(client):
    f = form(client, "player-form", last=1).json()  # g2 only
    ava = next(s for s in f["skaters"] if s["name"] == "Ava Forward")
    assert (ava["window"]["games"], ava["window"]["points"], ava["window"]["pp_goals"]) == (1, 1, 0)
    assert (ava["season_totals"]["points"], ava["season_totals"]["pp_goals"]) == (4, 1)
    ben = next(s for s in f["skaters"] if s["name"] == "Ben Defense")
    assert ben["season_totals"]["pp_points"] == 1  # assisted Ava's PP goal in g1
    assert f["goalies"][0]["name"] == "Cal Goalie"


def test_player_form_full_season(client):
    f = form(client, "player-form").json()
    assert all(s["season_totals"] is None for s in f["skaters"])
    assert [s["name"] for s in f["skaters"]] == [
        "Ava Forward",
        "Ben Defense",
    ]  # 4 pts each; Ava more goals


def test_likely_starter_from_the_database(client):
    s = form(client, "player-form").json()["likely_starter"]
    assert (s["name"], s["starts"], s["of_last"], s["started_last_game"]) == (
        "Cal Goalie",
        2,
        2,
        True,
    )


def test_no_leakage_from_later_games(database_url):
    """Features as of a date must not change when every game from that date on is removed."""
    as_of = dt.date(2026, 10, 11)
    with psycopg.connect(database_url) as conn:  # rolled back at the end
        before = team_form(conn, 1, "2026-27", as_of=as_of)
        for table in (
            "goals",
            "penalties",
            "skater_game_stats",
            "goalie_game_stats",
            "team_game_stats",
        ):
            conn.execute(
                f"DELETE FROM hockey.{table} WHERE game_id IN "
                "(SELECT game_id FROM hockey.games WHERE game_date >= %s)",
                (as_of,),
            )
        after = team_form(conn, 1, "2026-27", as_of=as_of)
        conn.rollback()
    assert before == after


def test_games_carry_xg(client):
    games = form(client).json()["games"]
    assert all("xg_for" in g and "xg_against" in g for g in games)  # None where CHN has no xG
