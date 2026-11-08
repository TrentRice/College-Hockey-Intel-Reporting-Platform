import pytest

from src.ingestion.chn_boxscore_parser import split_assists


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Ben Schoen, Simon Mack", ["Ben Schoen", "Simon Mack"]),
        ("Jimmy Dowd, Jr., Simon Mack", ["Jimmy Dowd, Jr.", "Simon Mack"]),
        ("Xander Lamppa, Jimmy Dowd, Jr.", ["Xander Lamppa", "Jimmy Dowd, Jr."]),
        ("John Smith, III", ["John Smith, III"]),
        ("Solo Assist", ["Solo Assist"]),
        ("", []),
    ],
)
def test_split_assists_keeps_name_suffixes(text, expected):
    assert split_assists(text) == expected
