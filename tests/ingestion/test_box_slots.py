"""Home and away team abbreviations from CHN box score URLs (neutral-site games use them)."""

import pytest

from src.ingestion.chn_team_schedule_scraper import _box_slots


@pytest.mark.parametrize(
    "url, slots",
    [
        ("https://www.collegehockeynews.com/box/final/20251025/bu_/con/", ("bu_", "con")),
        ("/box/final/20251025/bu_/con", ("bu_", "con")),
        # women's links end in a league marker, which once got read as the home team
        ("/box/final/20261107/mne/bu_/w", ("mne", "bu_")),
        ("https://www.collegehockeynews.com/box/final/20260322/osu/wis/w/", ("osu", "wis")),
        (None, None),
        ("/reports/team/Maine/25", None),
    ],
)
def test_box_slots(url, slots):
    assert _box_slots(url) == slots
