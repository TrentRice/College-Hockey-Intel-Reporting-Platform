"""
Streamlit Community Cloud entry point (docs/cloud.md). Locally, use `make dashboard` or
`make up` instead.

Starts the private backend once per app process (data from the private data repo, a
Postgres and the API, all inside the app), then runs the normal dashboard,
src/dashboard/app.py, unchanged.

Code updates: on a push, Streamlit Cloud pulls the new files into the running app without
restarting it, and Python keeps the old modules it already imported. So every run checks
CHIRP's code on disk; when it has changed, the old backend is stopped, CHIRP's modules are
forgotten, and everything starts again on the new code (what "Reboot app" would do).
"""

import runpy
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:  # `streamlit run cloud/streamlit_app.py` only adds cloud/
    sys.path.insert(0, str(ROOT))

import streamlit as st

CODE = [ROOT / "src", ROOT / "config", ROOT / "db", ROOT / "models"]
PACKAGES = ("src", "config")  # CHIRP's own modules, re-imported after a code update


def code_version() -> int:
    """Changes whenever a file of CHIRP's code, SQL or model card changes on disk."""
    return max(
        (f.stat().st_mtime_ns for d in CODE for f in d.rglob("*")
         if f.suffix in (".py", ".sql", ".json") and f.is_file()),
        default=0,
    )


def secret(name: str) -> str | None:
    try:
        return st.secrets.get(name)
    except FileNotFoundError:  # no secrets at all (a local test with CHIRP_DATA_DIR)
        return None


@st.cache_resource
def running() -> dict:
    """Lives as long as the app process: the backend and the code version it runs."""
    return {"backend": None, "version": None, "lock": threading.Lock()}


state = running()
with state["lock"]:  # one session starts the backend; the others wait for it
    version = code_version()
    if state["backend"] is not None and state["version"] != version:
        # A backend from older code may predate stop(): then just let it go
        if stop := getattr(state["backend"], "stop", None):
            stop()
        state["backend"] = None
        st.cache_data.clear()  # answers cached by the old code
    if state["backend"] is None:
        # Always start from the code on disk: forget CHIRP modules imported earlier in this
        # process, which may be older than the files (including this file's first run after
        # an update)
        for name in [m for m in sys.modules if m.split(".")[0] in PACKAGES]:
            del sys.modules[name]
        from src.cloud.backend import Backend

        with st.spinner("Starting CHIRP: loading the latest data (about a minute)…"):
            state["backend"] = Backend.start(secret("DATA_REPO"), secret("DATA_REPO_TOKEN"))
        state["version"] = version

state["backend"].check_for_new_data()
runpy.run_path(str(ROOT / "src" / "dashboard" / "app.py"), run_name="__main__")
