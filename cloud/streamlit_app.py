"""
Streamlit Community Cloud entry point (docs/cloud.md). Locally, use `make dashboard` or
`make up` instead.

Starts the private backend once per app process (data from the private data repo, a
Postgres and the API, all inside the app), then runs the normal dashboard,
src/dashboard/app.py, unchanged.
"""

import runpy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:  # `streamlit run cloud/streamlit_app.py` only adds cloud/
    sys.path.insert(0, str(ROOT))

import streamlit as st

from src.cloud.backend import Backend


def secret(name: str) -> str | None:
    try:
        return st.secrets.get(name)
    except FileNotFoundError:  # no secrets at all (a local test with CHIRP_DATA_DIR)
        return None


@st.cache_resource(show_spinner="Starting CHIRP: loading the latest data (about a minute)…")
def backend() -> Backend:
    return Backend.start(secret("DATA_REPO"), secret("DATA_REPO_TOKEN"))


backend().check_for_new_data()
runpy.run_path(str(ROOT / "src" / "dashboard" / "app.py"), run_name="__main__")
