"""The whole dashboard, run headless by Streamlit's test harness, with its API calls sent to
the real API over the made-up test database (tests/api/fixture.sql)."""

from pathlib import Path

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from src.dashboard import client as dashboard_client

APP = str(Path(__file__).resolve().parents[2] / "src/dashboard/app.py")


@pytest.fixture
def app(client, monkeypatch):
    def get(path, **params):
        params = {
            k: (v.isoformat() if hasattr(v, "isoformat") else v)
            for k, v in params.items()
            if v is not None
        }
        r = client.get(path, params=params)
        return None if r.status_code == 404 else r.json()

    monkeypatch.setattr(dashboard_client, "get", get)
    st.cache_data.clear()
    at = AppTest.from_file(APP, default_timeout=30)
    at.run()
    return at


def no_errors(at):
    assert not at.exception, [e.value for e in at.exception]


def test_next_opponent_that_has_no_games_yet(app):
    # Home U's next game is against Small State (non-D1, no games): a clear message, no crash
    no_errors(app)
    assert "Small State" in app.error[0].value


def test_scouting_any_team(app):
    app.sidebar.radio[0].set_value("Any team").run()
    no_errors(app)
    assert app.title[0].value == "Rival College"
    slider = app.slider[0]
    assert (slider.min, slider.max, slider.value) == (1, 2, 2)  # Rival College has played 2


def test_moving_the_slider_shows_season_alongside(app):
    app.sidebar.radio[0].set_value("Any team").run()
    app.slider[0].set_value(1).run()
    no_errors(app)
    labels = [m.label for m in app.metric]
    assert "Goals for / game" in labels
    scouting = [m for m in app.metric if not m.label.endswith(" win")]  # not the win tab's
    assert all(m.delta for m in scouting)  # each headline number shows its change vs season
    assert "Last 1 vs season" in [h.value for h in app.subheader]


def test_head_to_head_and_difference_columns_render(app):
    app.sidebar.radio[0].set_value("Any team").run()
    app.slider[0].set_value(1).run()
    no_errors(app)
    frames = [df.value for df in app.dataframe]
    assert any("Difference" in getattr(f, "columns", []) for f in frames)


def test_win_probability_tab_explains_no_prediction(app):
    # Home U's next game is against Small State (not D-I): a clear message, no crash
    no_errors(app)
    msgs = [i.value for i in app.info]
    assert any("D-I teams only" in m for m in msgs)


def test_win_probability_tab_follows_the_sidebar_team(client, monkeypatch, app):
    # Point "next game" at g2 (Home U at Rival College); predictions work as of any game date.
    # No team picker in the tab: it uses the sidebar's "Your team" (Home U here).
    from src.dashboard import logic

    g2 = {"game_id": "g2", "date": "2026-10-11", "is_home": False, "is_neutral": False,
          "is_played": False, "opponent": {"team_id": 2, "name": "Rival College"}}
    monkeypatch.setattr(logic, "next_game", lambda schedule, today: g2)
    st.cache_data.clear()
    app.run()
    no_errors(app)
    assert app.sidebar.selectbox[1].value == "Home U"
    assert not [s for s in app.main.selectbox if s.label == "Team"]  # no separate picker
    values = {m.label: m.value for m in app.metric}
    assert "Home U win" in values and "Rival College win" in values
    total = int(values["Home U win"].rstrip("%")) + int(values["Rival College win"].rstrip("%"))
    assert total in (99, 100, 101)  # two rounded halves of one probability
    frames = [df.value for df in app.dataframe]
    assert any("Effect on chance" in getattr(f, "columns", []) for f in frames)


def test_win_probability_any_team_is_a_matchup(app):
    # Any team: Home U against the picked team, venue chosen in the tab
    app.sidebar.radio[0].set_value("Any team").run()
    no_errors(app)
    values = {m.label: m.value for m in app.metric}
    assert "Home U win" in values and "Rival College win" in values
    venue = next(r for r in app.main.radio if r.label.startswith("Where"))
    assert venue.value == "Home"  # no upcoming meeting with Rival College in the fixture
    home_pct = int(values["Home U win"].rstrip("%"))
    venue.set_value("Away").run()
    no_errors(app)
    away_pct = int({m.label: m.value for m in app.metric}["Home U win"].rstrip("%"))
    assert away_pct < home_pct  # losing home ice lowers the chance
