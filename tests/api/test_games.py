import pytest


def ids(r):
    return [g["game_id"] for g in r.json()["items"]]


@pytest.mark.parametrize(
    "params, expected",
    [
        ({}, ["g1", "g2", "g3", "g4"]),  # latest season
        ({"season": "2025-26"}, ["g5"]),
        ({"date": "2026-10-11"}, ["g2"]),
        ({"date_from": "2026-10-11", "date_to": "2026-12-31"}, ["g2", "g3"]),
        ({"team_id": 3}, ["g3"]),
        ({"played": False}, ["g3", "g4"]),
        ({"conference_only": True}, ["g1", "g2"]),
    ],
)
def test_game_filters(client, params, expected):
    assert ids(client.get("/v1/games", params=params)) == expected


def test_games_are_paged(client):
    r = client.get("/v1/games", params={"limit": 2, "offset": 1}).json()
    assert [g["game_id"] for g in r["items"]] == ["g2", "g3"]
    assert (r["total"], r["limit"], r["offset"]) == (4, 2, 1)
    assert client.get("/v1/games", params={"limit": 201}).status_code == 422


def test_game_summary_teams(client):
    g2 = client.get("/v1/games", params={"date": "2026-10-11"}).json()["items"][0]
    assert g2["home"] == {"team_id": 2, "name": "Rival College"}
    assert g2["shootout_winner"] == {"team_id": 2, "name": "Rival College"}


def test_box_score(client):
    b = client.get("/v1/games/g1").json()
    assert b["game"]["home"]["name"] == "Home U"
    away, home = b["teams"]
    assert (away["team"]["name"], away["is_home"], home["is_home"]) == (
        "Rival College",
        False,
        True,
    )
    assert home["stats"]["goals"] == 4
    assert home["stats"]["shots"] == 35
    assert [s["name"] for s in home["skaters"]] == ["Ava Forward", "Ben Defense"]
    assert [g["name"] for g in home["goalies"]] == ["Cal Goalie"]


def test_box_score_goals(client):
    goals = client.get("/v1/games/g1").json()["goals"]
    assert [g["goal_number"] for g in goals] == [1, 2, 3, 4, 5, 6]
    first, _, pp, unknown, _, en = goals
    assert (first["period"], first["time"], first["team"]["name"]) == (1, "5:00", "Home U")
    assert first["scorer"] == {"player_id": 10, "name": "Ava Forward"}
    assert [a["name"] for a in first["assists"]] == ["Ben Defense"]
    assert pp["is_pp"] and [a["player_id"] for a in pp["assists"]] == [11, 12]
    assert unknown["scorer"] is None and unknown["assists"] == []
    assert en["is_en"] and en["time"] == "19:10"


def test_box_score_penalties(client):
    hooking, bench = client.get("/v1/games/g1").json()["penalties"]
    assert hooking["player"] == {"player_id": 20, "name": "Éli Rival"}
    assert (bench["is_bench"], bench["player"], bench["time"]) == (True, None, "5:00")


def test_box_score_before_the_game(client):
    b = client.get("/v1/games/g3").json()
    assert [t["stats"] for t in b["teams"]] == [None, None]
    assert all(t["skaters"] == [] and t["goalies"] == [] for t in b["teams"])
    assert b["goals"] == [] and b["penalties"] == []


def test_box_score_with_a_tbd_opponent(client):
    b = client.get("/v1/games/g4").json()
    assert b["game"]["home"] is None
    assert [t["team"]["name"] for t in b["teams"]] == ["Home U"]


def test_unknown_game(client):
    assert client.get("/v1/games/nope").status_code == 404
