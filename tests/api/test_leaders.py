import pytest


def ranked(r, stat):
    return [(x["rank"], x["name"], x[stat]) for x in r.json()["items"]]


def test_points_leaders_share_tied_ranks(client):
    r = client.get("/v1/leaders/skaters")
    assert ranked(r, "points") == [
        (1, "Ava Forward", 4),
        (1, "Ben Defense", 4),
        (3, "Éli Rival", 3),
    ]
    assert r.json()["items"][0]["points_per_game"] == 2.0
    assert r.json()["items"][0]["team"] == {"team_id": 1, "name": "Home U"}


@pytest.mark.parametrize(
    "params, stat, expected",
    [
        (
            {"stat": "goals"},
            "goals",
            [(1, "Ava Forward", 3), (1, "Éli Rival", 3), (3, "Ben Defense", 1)],
        ),
        ({"position": "D"}, "points", [(1, "Ben Defense", 4)]),
        ({"min_games": 3}, "points", []),
        ({"season": "2025-26"}, "points", [(1, "Ava Forward", 1)]),
    ],
)
def test_skater_leader_options(client, params, stat, expected):
    assert ranked(client.get("/v1/leaders/skaters", params=params), stat) == expected


def test_goalie_leaders_need_a_third_of_team_minutes(client):
    # Home U played 2 games (7,200 s); Dee Backup's 1,500 s is under a third
    r = client.get("/v1/leaders/goalies")
    assert ranked(r, "save_pct") == [(1, "Cal Goalie", 0.915), (2, "Fay Keeper", 0.892)]
    everyone = client.get("/v1/leaders/goalies", params={"qualified": False})
    assert [x["name"] for x in everyone.json()["items"]] == [
        "Cal Goalie",
        "Fay Keeper",
        "Dee Backup",
    ]


def test_gaa_ranks_lowest_first(client):
    r = client.get("/v1/leaders/goalies", params={"stat": "gaa"})
    assert [x["name"] for x in r.json()["items"]] == ["Cal Goalie", "Fay Keeper"]


def test_unknown_stat_is_rejected(client):
    assert client.get("/v1/leaders/skaters", params={"stat": "salary"}).status_code == 422
