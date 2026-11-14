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
    assert all(m.delta for m in app.metric)  # each headline number shows its change vs season
    assert "Last 1 vs season" in [h.value for h in app.subheader]


def test_head_to_head_and_difference_columns_render(app):
    app.sidebar.radio[0].set_value("Any team").run()
    app.slider[0].set_value(1).run()
    no_errors(app)
    frames = [df.value for df in app.dataframe]
    assert any("Difference" in getattr(f, "columns", []) for f in frames)
