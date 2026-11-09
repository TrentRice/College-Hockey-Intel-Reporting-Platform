import pytest

# ----------------------------------------------------------------------------
# Access
# ----------------------------------------------------------------------------


def test_health_needs_no_key(client):
    r = client.get("/health", headers={"X-API-Key": ""})
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "database": "ok"}


@pytest.mark.parametrize("headers", [{"X-API-Key": ""}, {"X-API-Key": "wrong"}])
def test_v1_needs_the_right_key(client, headers):
    r = client.get("/v1/seasons", headers=headers)
    assert r.status_code == 401


def test_api_is_read_only(database_url):
    import psycopg

    from src.api.db import CONNECTION_OPTIONS

    with (
        psycopg.connect(database_url, options=CONNECTION_OPTIONS, autocommit=True) as conn,
        pytest.raises(psycopg.errors.ReadOnlySqlTransaction),
    ):
        conn.execute("DELETE FROM teams")


# ----------------------------------------------------------------------------
# Seasons and teams
# ----------------------------------------------------------------------------


def test_seasons(client):
    assert client.get("/v1/seasons").json() == [
        {"season": "2025-26", "start_year": 2025, "games": 1, "played": 1},
        {"season": "2026-27", "start_year": 2026, "games": 4, "played": 2},
    ]


def test_teams_default_to_the_latest_season(client):
    names = [t["name"] for t in client.get("/v1/teams").json()]
    assert names == ["Home U", "Rival College", "Small State"]
    assert [t["name"] for t in client.get("/v1/teams", params={"season": "2025-26"}).json()] == [
        "Home U"
    ]


@pytest.mark.parametrize(
    "params, expected",
    [
        ({"conference": "hockey east"}, ["Home U", "Rival College"]),
        ({"d1_only": True}, ["Home U", "Rival College"]),
        ({"search": "university"}, ["Home U"]),  # matches an alias, not the current name
    ],
)
def test_team_filters(client, params, expected):
    assert [t["name"] for t in client.get("/v1/teams", params=params).json()] == expected


def test_team_detail(client):
    t = client.get("/v1/teams/1").json()
    assert t["aliases"] == ["Home U", "Home University"]
    assert t["seasons"] == [
        {"season": "2025-26", "conference": "Hockey East"},
        {"season": "2026-27", "conference": "Hockey East"},
    ]


@pytest.mark.parametrize(
    "url, status",
    [
        ("/v1/teams/999", 404),
        ("/v1/teams/999/games", 404),
        ("/v1/teams?season=2026", 422),  # bad format
        ("/v1/teams?season=1999-00", 404),  # not loaded
        ("/v1/teams/3/season-stats", 404),  # no games played yet
    ],
)
def test_errors(client, url, status):
    assert client.get(url).status_code == status


# ----------------------------------------------------------------------------
# Games, stats, roster
# ----------------------------------------------------------------------------


def test_team_games(client):
    games = {g["game_id"]: g for g in client.get("/v1/teams/1/games").json()}
    assert list(games) == ["g1", "g2", "g3", "g4"]

    win = games["g1"]
    assert (win["is_home"], win["goals_for"], win["goals_against"], win["result"]) == (
        True,
        4,
        2,
        "W",
    )
    assert (win["shots_for"], win["shots_against"]) == (35, 25)
    assert win["opponent"] == {"team_id": 2, "name": "Rival College"}

    shootout = games["g2"]
    assert (shootout["is_home"], shootout["result"], shootout["shootout_won"]) == (
        False,
        "T",
        False,
    )

    upcoming = games["g3"]
    assert (upcoming["result"], upcoming["goals_for"], upcoming["shots_for"]) == (None, None, None)

    tbd = games["g4"]
    assert tbd["opponent"] is None
    assert tbd["is_home"] is False  # home side is TBD, so this team is the away side


def test_team_games_played_filter(client):
    played = client.get("/v1/teams/1/games", params={"played": True}).json()
    upcoming = client.get("/v1/teams/1/games", params={"played": False}).json()
    assert [g["game_id"] for g in played] == ["g1", "g2"]
    assert [g["game_id"] for g in upcoming] == ["g3", "g4"]


def test_team_season_stats(client):
    s = client.get("/v1/teams/1/season-stats").json()
    assert s["record"] == "1-0-1"
    assert (s["goals_for"], s["goals_against"], s["goal_diff"]) == (7, 5, 2)
    assert s["pp_pct"] == pytest.approx(2 / 6, abs=1e-3)
    assert s["pk_pct"] == pytest.approx(1 - 1 / 5, abs=1e-3)
    assert (
        client.get("/v1/teams/1/season-stats", params={"season": "2025-26"}).json()["record"]
        == "0-1-0"
    )


def test_team_roster(client):
    r = client.get("/v1/teams/1/roster").json()
    assert [(s["name"], s["position"], s["points"]) for s in r["skaters"]] == [
        ("Ava Forward", "F", 4),
        ("Ben Defense", "D", 4),
    ]  # tied on points; more goals first
    starter, backup = r["goalies"]
    assert (starter["name"], starter["starts"], starter["save_pct"]) == ("Cal Goalie", 2, 0.915)
    assert starter["gaa"] == pytest.approx(4 * 3600 / 6000, abs=0.01)
    assert backup["name"] == "Dee Backup"
