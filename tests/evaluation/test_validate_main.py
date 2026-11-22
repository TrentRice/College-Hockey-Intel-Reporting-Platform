"""The validator's command line (src/evaluation/validate_chn_data.py)."""

import pandas as pd
import pytest

from src.evaluation import validate_chn_data as v


def test_strict_passes_when_no_check_has_any_mismatch(tmp_path, monkeypatch):
    """All-clean data once crashed (pd.concat of nothing), which blocked the nightly refresh."""
    clean = v.Exact(group="g", name="clean check", shows="", checked=10,
                    failures=pd.DataFrame(columns=["game_id", "team", "detail", "cause"]))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(v, "load", lambda root: ({}, ["2026_27"]))
    monkeypatch.setattr(v, "exact_checks", lambda data: [clean])
    monkeypatch.setattr(v, "approximate_checks", lambda data: [])
    monkeypatch.setattr(v, "write_report", lambda *a, **k: None)
    monkeypatch.setattr("sys.argv", ["validate", "--strict", "--report", str(tmp_path / "r.md")])
    try:
        v.main()
    except SystemExit as e:
        pytest.fail(f"exited with {e.code}")
    written = pd.read_csv(tmp_path / v.FAILURES_PATH)
    assert list(written.columns) == ["check", "game_id", "team", "detail", "cause"]
    assert written.empty
