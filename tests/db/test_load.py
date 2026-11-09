import pandas as pd
import pytest

from src.db.load import UnmappedError, map_strict, number_events, split_officials, to_python


def test_map_strict_maps_and_allows_known_gaps():
    out = map_strict(pd.Series(["BU", "TBD", None]), {"BU": 1}, "teams", allow={"TBD"})
    assert out.tolist()[0] == 1
    assert out.isna().tolist() == [False, True, True]


def test_map_strict_refuses_unknown_names():
    with pytest.raises(UnmappedError, match="1 teams"):
        map_strict(pd.Series(["BU", "Nowhere State"]), {"BU": 1}, "teams")


def test_events_are_numbered_in_game_order():
    df = pd.DataFrame(
        {
            "game_id": ["g1", "g1", "g1", "g2"],
            "period": [2, 1, 1, 1],
            "time_seconds": [100, 900, 30, 5],
        }
    )
    assert number_events(df).tolist() == [3, 2, 1, 1]


def test_officials_become_lists():
    out = split_officials(pd.Series(["Tim Benedetto, Jack Millea", None]))
    assert out.tolist() == [["Tim Benedetto", "Jack Millea"], None]


@pytest.mark.parametrize(
    "value, data_type, expected",
    [
        (3.0, "smallint", 3),
        (float("nan"), "integer", None),
        (pd.NA, "integer", None),
        (1, "boolean", True),
        (4.5, "numeric", 4.5),
        (["a", "b"], "ARRAY", ["a", "b"]),
        ("2026-11-08", "date", "2026-11-08"),
    ],
)
def test_values_are_converted_for_copy(value, data_type, expected):
    assert to_python(value, data_type) == expected
