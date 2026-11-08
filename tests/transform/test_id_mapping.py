import pandas as pd
import pytest

from src.transform.id_mapping import (
    assign_player_ids,
    build_teams,
    link_player_seasons,
    name_key,
    player_appearances,
    player_seasons_from,
)


@pytest.mark.parametrize(
    "a, b",
    [
        ("Jérémie Minville", "Jeremie Minville"),
        ("Jimmy Dowd, Jr.", "Jimmy Dowd"),
        ("Jean-Luc Foudy", "Jean Luc Foudy"),
        ("Ryan O'Connor", "Ryan OConnor"),
        ("  Nick   RHÉAUME ", "nick rheaume"),
    ],
)
def test_name_key_matches_spelling_variants(a, b):
    assert name_key(a) == name_key(b)


def test_name_key_keeps_different_names_apart():
    assert name_key("Joseph Grainda") != name_key("JJ Grainda")


# ----------------------------------------------------------------------------
# Teams
# ----------------------------------------------------------------------------


def games(*rows):
    cols = ["season", "home_team", "home_team_id", "home_conference",
            "away_team", "away_team_id", "away_conference"]  # fmt: skip
    return pd.DataFrame(rows, columns=cols)


GAMES = games(
    ("2025-26", "Rensselaer", 48, "ECAC", "Boston University", 10, "Hockey East"),
    ("2026-27", "RPI", 48, "ECAC", "Maryville", None, None),
    ("2026-27", "Boston University", 10, "Hockey East", "TBD", None, None),
)


def test_teams_one_id_per_chn_team_with_aliases():
    t = build_teams(GAMES)
    assert len(t.teams) == 3  # RPI, BU, Maryville; TBD is not a team
    rpi = t.teams[t.teams.chn_team_id == 48].iloc[0]
    assert rpi["name"] == "RPI"  # latest name
    assert t.id_by_name()["Rensselaer"] == t.id_by_name()["RPI"] == rpi.team_id
    assert not t.teams[t.teams.name == "Maryville"].is_d1.iloc[0]


def test_team_ids_survive_a_new_team():
    first = build_teams(GAMES)
    more = pd.concat(
        [GAMES, games(("2027-28", "Long Island", 62, "Independent", "Assumption", None, None))]
    )
    second = build_teams(more, previous=first)
    before = first.id_by_name()
    after = second.id_by_name()
    assert all(after[n] == i for n, i in before.items())
    assert after["Long Island"] > max(before.values())


# ----------------------------------------------------------------------------
# Players
# ----------------------------------------------------------------------------

TEAM_IDS = {"BU": 1, "BC": 2, "UNH": 3}


def tables(skaters=(), goals=(), goalies=(), penalties=()):
    sk = pd.DataFrame(list(skaters), columns=["season", "team", "game_id", "player", "position"])
    go = pd.DataFrame(
        list(goals),
        columns=["season", "team", "game_id", "scorer", "scorer_chn_id", "assist1", "assist2"],
    )
    gl = pd.DataFrame(list(goalies), columns=["season", "team", "game_id", "goalie"])
    pe = pd.DataFrame(list(penalties), columns=["season", "team", "game_id", "player"])
    return {"box_skaters": sk, "box_goals": go, "box_goalies": gl, "box_penalties": pe}


def resolve(t, prev_seasons=None, prev_players=None):
    ps = link_player_seasons(player_seasons_from(player_appearances(t, TEAM_IDS)))
    ps, merges = assign_player_ids(ps, prev_seasons, prev_players, today="2026-11-08")
    return ps, merges


def ids(ps, season, team, name):
    row = ps[
        (ps.season == season) & (ps.team_id == TEAM_IDS[team]) & (ps.name_key == name_key(name))
    ]
    assert len(row) == 1, (season, team, name)
    return row.player_id.iloc[0]


def test_chn_id_links_a_transfer_and_a_new_spelling():
    t = tables(
        skaters=[("2028-29", "BU", "g1", "Joseph Grainda", "F"), ("2029-30", "BC", "g2", "JJ Grainda", "F")],
        goals=[("2028-29", "BU", "g1", "Joseph Grainda", 60269, None, None),
               ("2029-30", "BC", "g2", "JJ Grainda", 60269, None, None)],
    )  # fmt: skip
    ps, _ = resolve(t)
    assert ids(ps, "2028-29", "BU", "Joseph Grainda") == ids(ps, "2029-30", "BC", "JJ Grainda")
    assert set(ps.link) == {"chn_id"}


def test_same_team_and_name_links_seasons_without_a_chn_id():
    t = tables(
        skaters=[
            ("2028-29", "BU", "g1", "Sam Stevens", "D"),
            ("2029-30", "BU", "g2", "Sam Stevens", "D"),
        ]
    )
    ps, _ = resolve(t)
    assert ps.player_id.nunique() == 1
    assert set(ps.link) == {"team_and_name"}


def test_two_chn_ids_on_one_team_name_leave_the_unknown_season_unlinked():
    t = tables(
        skaters=[(s, "BU", f"g{s}", "Luke Johnson", "F") for s in ("2026-27", "2027-28", "2028-29")],
        goals=[("2026-27", "BU", "g2026-27", "Luke Johnson", 111, None, None),
               ("2028-29", "BU", "g2028-29", "Luke Johnson", 222, None, None)],
    )  # fmt: skip
    ps, _ = resolve(t)
    assert ps.player_id.nunique() == 3
    assert ps.set_index("season").link["2027-28"] == "ambiguous"


def test_transfer_without_a_goal_is_linked_by_name():
    t = tables(
        skaters=[
            ("2029-30", "BU", "g1", "Anthony Dowd", "D"),
            ("2030-31", "UNH", "g2", "Anthony Dowd", "D"),
        ]
    )
    ps, _ = resolve(t)
    assert ps.player_id.nunique() == 1
    assert ps.set_index("season").link["2030-31"] == "name_transfer"


def test_transfer_rule_skips_one_to_many():
    t = tables(skaters=[("2029-30", "BU", "g1", "Cole Miller", "F"),
                        ("2030-31", "BC", "g2", "Cole Miller", "F"),
                        ("2030-31", "UNH", "g3", "Cole Miller", "F")])  # fmt: skip
    ps, _ = resolve(t)
    assert ps.player_id.nunique() == 3


def test_unknown_scorer_and_bench_are_not_players():
    t = tables(
        skaters=[("2025-26", "BU", "g1", "A Player", "F")],
        goals=[("2025-26", "BU", "g1", "Uknown", 57473, "A Player", None)],
        penalties=[("2025-26", "BU", "g1", "BENCH")],
    )
    ps, _ = resolve(t)
    assert list(ps.name) == ["A Player"]
    assert ps.chn_player_id.isna().all()  # the id on the Uknown row is not trusted


def test_ids_are_stable_when_a_season_is_added():
    one = tables(
        skaters=[
            ("2029-30", "BU", "g1", "Zed Alpha", "F"),
            ("2029-30", "BU", "g1", "Amy Beta", "D"),
        ]
    )
    ps1, _ = resolve(one)
    two = tables(skaters=[("2029-30", "BU", "g1", "Zed Alpha", "F"), ("2029-30", "BU", "g1", "Amy Beta", "D"),
                          ("2029-30", "BU", "g1", "Aaron Aardvark", "F")])  # fmt: skip
    ps2, merges = resolve(two, prev_seasons=ps1)
    for name in ("Zed Alpha", "Amy Beta"):
        assert ids(ps1, "2029-30", "BU", name) == ids(ps2, "2029-30", "BU", name)
    assert ids(ps2, "2029-30", "BU", "Aaron Aardvark") == ps1.player_id.max() + 1
    assert merges.empty


def test_new_link_merges_two_old_ids_and_records_it():
    # run 1: a player on BU (scored) and an id-less player on BC look like two people
    t1 = tables(
        skaters=[("2028-29", "BU", "g1", "Jake Leblanc", "F"), ("2028-29", "BC", "g2", "Jacob Leblanc", "F"),
                 ("2028-29", "BC", "g2", "Other Guy", "F")],
        goals=[("2028-29", "BU", "g1", "Jake Leblanc", 61788, None, None)],
    )  # fmt: skip
    ps1, _ = resolve(t1)
    # run 2: the BC player scores, and CHN's link shows it's the same person
    t2 = tables(
        skaters=t1["box_skaters"].values.tolist(),
        goals=[("2028-29", "BU", "g1", "Jake Leblanc", 61788, None, None),
               ("2028-29", "BC", "g2", "Jacob Leblanc", 61788, None, None)],
    )  # fmt: skip
    players1 = ps1.groupby("player_id").chn_player_id.max().reset_index()
    ps2, merges = resolve(t2, prev_seasons=ps1, prev_players=players1)
    bu, bc = ids(ps1, "2028-29", "BU", "Jake Leblanc"), ids(ps1, "2028-29", "BC", "Jacob Leblanc")
    assert ids(ps2, "2028-29", "BC", "Jacob Leblanc") == min(bu, bc)
    assert merges.to_dict("records") == [
        {"old_player_id": max(bu, bc), "new_player_id": min(bu, bc), "merged_on": "2026-11-08"}
    ]
    assert ids(ps2, "2028-29", "BC", "Other Guy") == ids(ps1, "2028-29", "BC", "Other Guy")
