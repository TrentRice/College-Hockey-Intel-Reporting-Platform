"""League settings (config/leagues.py): what differs between men's and women's."""

from pathlib import Path

import pytest

from config import leagues
from src.pipeline import refresh


def test_default_league_is_men(monkeypatch):
    monkeypatch.delenv(leagues.ENV_VAR, raising=False)
    assert leagues.current() is leagues.MEN
    monkeypatch.setenv(leagues.ENV_VAR, "women")
    assert leagues.current() is leagues.WOMEN
    monkeypatch.setenv(leagues.ENV_VAR, "coed")
    with pytest.raises(ValueError, match="Unknown league"):
        leagues.current()


def test_men_keep_their_original_paths_and_women_mirror_them():
    assert leagues.MEN.raw("boxscores", "2026_27") == Path("data/raw/chn/boxscores/2026_27")
    assert leagues.MEN.processed("ids") == Path("data/processed/ids")
    assert leagues.WOMEN.raw("schedules") == Path("data/women/raw/chn/schedules")
    assert leagues.WOMEN.processed("chn") == Path("data/women/processed/chn")


@pytest.mark.parametrize(
    "url, expected",
    [
        ("postgresql://u:p@localhost:5432/hockey", "postgresql://u:p@localhost:5432/hockey_women"),
        ("postgresql://u@127.0.0.1:5999/hockey?sslmode=disable",
         "postgresql://u@127.0.0.1:5999/hockey_women?sslmode=disable"),
    ],
)
def test_women_use_their_own_database_on_the_same_server(url, expected):
    assert leagues.database_url(url, leagues.WOMEN) == expected


@pytest.mark.parametrize(
    "league, href, team_id",
    [
        (leagues.MEN, "/reports/team/Boston-University/10", 10),
        (leagues.WOMEN, "/women/team/Boston-University/10", 10),
        (leagues.MEN, "/women/team/Boston-University/10", None),  # never the other league's
        (leagues.WOMEN, "/reports/team/Maine/25", None),
    ],
)
def test_team_links(league, href, team_id):
    m = league.team_link.search(href)
    assert (int(m.group(1)) if m else None) == team_id


def test_refresh_skips_predictions_until_the_league_has_a_model(monkeypatch, tmp_path):
    monkeypatch.setattr(refresh, "MODELS_DIR", tmp_path)
    monkeypatch.setattr(refresh, "LEAGUE", leagues.WOMEN)
    names = [s.name for s in refresh.default_steps(tmp_path / "r.md")]
    assert names[-1] == "load" and "predict" not in names
    (tmp_path / "win_model_women_v1.json").write_text("{}")
    assert [s.name for s in refresh.default_steps(tmp_path / "r.md")][-2:] == ["predict", "backup"]
