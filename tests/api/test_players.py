import pytest


def names(r):
    return [p["name"] for p in r.json()["items"]]


@pytest.mark.parametrize(
    "params, expected",
    [
        ({"search": "eli"}, ["Éli Rival"]),  # accents optional
        ({"search": "avery"}, ["Ava Forward"]),  # matches another spelling
        ({"position": "G"}, ["Cal Goalie", "Dee Backup", "Fay Keeper"]),
        ({"team_id": 2}, ["Éli Rival", "Fay Keeper"]),
        ({"season": "2025-26"}, ["Ava Forward"]),
        ({"season": "2025-26", "team_id": 2}, []),
    ],
)
def test_player_search(client, params, expected):
    assert names(client.get("/v1/players", params=params)) == expected


def test_player_summary(client):
    (ava,) = client.get("/v1/players", params={"search": "ava"}).json()["items"]
    assert ava["team"] == {"team_id": 1, "name": "Home U"}
    assert (ava["first_season"], ava["last_season"], ava["chn_player_id"]) == (
        "2025-26",
        "2026-27",
        9001,
    )


def test_player_profile(client):
    p = client.get("/v1/players/10").json()
    assert p["names"] == ["Ava Forward", "Avery Forward"]
    last, this = p["seasons"]
    assert (last["season"], last["skater"]["games"], last["skater"]["points"]) == ("2025-26", 1, 1)
    assert (this["season"], this["skater"]["points"], this["goalie"]) == ("2026-27", 4, None)


def test_goalie_profile(client):
    (season,) = client.get("/v1/players/12").json()["seasons"]
    assert season["skater"] is None
    assert (season["goalie"]["starts"], season["goalie"]["save_pct"]) == (2, 0.915)


def test_merged_id_redirects(client):
    r = client.get("/v1/players/99", follow_redirects=False)
    assert r.status_code == 308
    assert r.headers["location"].endswith("/v1/players/10")
    assert client.get("/v1/players/99").json()["player_id"] == 10  # followed


def test_merged_id_redirect_keeps_the_query(client):
    r = client.get("/v1/players/99/games", params={"season": "2025-26"}, follow_redirects=False)
    assert r.headers["location"].endswith("/v1/players/10/games?season=2025-26")


def test_game_log(client):
    log = client.get("/v1/players/10/games").json()
    assert [(g["game_id"], g["result"]) for g in log] == [("g5", "L"), ("g1", "W"), ("g2", "T")]
    assert log[1]["skater"]["points"] == 3 and log[1]["goalie"] is None
    assert log[2]["opponent"] == {"team_id": 2, "name": "Rival College"}
    assert [
        g["game_id"]
        for g in client.get("/v1/players/10/games", params={"season": "2026-27"}).json()
    ] == ["g1", "g2"]


def test_goalie_game_log(client):
    log = client.get("/v1/players/13/games").json()
    assert [(g["game_id"], g["goalie"]["is_starter"]) for g in log] == [("g2", False)]


def test_unknown_player(client):
    assert client.get("/v1/players/555").status_code == 404
    assert client.get("/v1/players/555/games").status_code == 404
