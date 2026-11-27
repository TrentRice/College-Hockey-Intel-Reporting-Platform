"""
The whole CHIRP backend inside the Streamlit Community Cloud app (docs/cloud.md).

Streamlit's free hosting runs one Python process and nothing else, so at startup this:

  1. downloads the latest data from the private data repo (processed CSVs, the newest
     prediction-log backup, the run history; never the raw pages),
  2. starts a private Postgres for this app only (bundled by the pixeltable-pgserver
     wheel), listening on 127.0.0.1 inside the app's container,
  3. loads the data with the same loader the Mac uses (src.db.load), and
  4. runs the same API (src.api) on 127.0.0.1 in a background thread, with a random key.

The dashboard then talks to the API exactly as it does on the Mac. Nothing here is
reachable from outside the container: only Streamlit's page is public.

Every few minutes `check_for_new_data` asks GitHub for the data repo's latest commit, and when
the nightly job has pushed one it reloads in the background (a full refresh in one
transaction, so pages keep working while it runs).

For testing without GitHub, set CHIRP_DATA_DIR to a local data/ folder.
"""

from __future__ import annotations

import logging
import os
import secrets
import shutil
import socket
import subprocess
import tarfile
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import psycopg
import requests
import uvicorn

from config import leagues
from config.settings import settings
from src.cloud.runs import import_runs
from src.db.load import build_tables, load_database
from src.pipeline.backup import backups, restore_predictions

log = logging.getLogger("chirp.cloud")

WORK_DIR = Path(tempfile.gettempdir()) / "chirp"
PG_USER = "hockey"
PG_DB = "hockey"
GITHUB_API = "https://api.github.com"
CHECK_EVERY = 10 * 60  # seconds between "is there new data?" checks
# What the app needs from the data repo (paths inside it). The raw pages stay behind.
LEAGUE_FILES = ("processed/chn/", "processed/ids/", "backups/", "pipeline_runs.csv")
# Men's at the data repo's root, women's under women/ (config/leagues.py)
WANTED = LEAGUE_FILES + tuple(f"women/{p}" for p in LEAGUE_FILES)


# ----------------------------------------------------------------------------
# Getting the data
# ----------------------------------------------------------------------------


def wanted(member_path: str) -> str | None:
    """'<repo>-<sha>/processed/chn/x.csv' -> 'processed/chn/x.csv' if the app needs it."""
    _, _, inner = member_path.partition("/")
    return inner if inner.startswith(WANTED) else None


def extract(tar_path: Path, dest: Path) -> None:
    """Extract only the wanted files, refusing anything that would land outside dest."""
    dest = dest.resolve()
    with tarfile.open(tar_path, "r:gz") as tar:
        for m in tar:
            inner = wanted(m.name)
            if inner is None or not m.isfile():
                continue
            target = (dest / inner).resolve()
            if not target.is_relative_to(dest):
                raise ValueError(f"unsafe path in data archive: {m.name}")
            target.parent.mkdir(parents=True, exist_ok=True)
            with tar.extractfile(m) as src, target.open("wb") as out:
                shutil.copyfileobj(src, out)


class GitHubData:
    """The private data repo, read with a read-only token."""

    def __init__(self, repo: str, token: str, branch: str = "main"):
        self.repo, self.branch = repo, branch
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
        })

    def latest(self) -> str:
        r = self.session.get(
            f"{GITHUB_API}/repos/{self.repo}/commits/{self.branch}",
            headers={"Accept": "application/vnd.github.sha"}, timeout=30,
        )
        if r.status_code in (401, 403, 404):
            raise RuntimeError(
                f"GitHub refused access to {self.repo} ({r.status_code}). Check DATA_REPO and "
                "DATA_REPO_TOKEN in the app's secrets (docs/cloud.md)."
            )
        r.raise_for_status()
        return r.text.strip()

    def fetch(self, version: str, dest: Path) -> None:
        tar_path = dest.with_suffix(".tar.gz")
        with self.session.get(
            f"{GITHUB_API}/repos/{self.repo}/tarball/{version}", stream=True, timeout=120
        ) as r:
            r.raise_for_status()
            with tar_path.open("wb") as f:
                for chunk in r.iter_content(1 << 20):
                    f.write(chunk)
        try:
            extract(tar_path, dest)
        finally:
            tar_path.unlink(missing_ok=True)


class LocalData:
    """A local data/ folder (CHIRP_DATA_DIR), for testing the cloud app without GitHub."""

    def __init__(self, path: Path):
        self.path = path

    def latest(self) -> str:
        files = [self.path / "pipeline_runs.csv", *(self.path / "processed").rglob("*.csv"),
                 self.path / "women/pipeline_runs.csv", *(self.path / "women/processed").rglob("*.csv")]
        return str(max((f.stat().st_mtime_ns for f in files if f.exists()), default=0))

    def fetch(self, version: str, dest: Path) -> None:
        for inner in WANTED:
            src = self.path / inner
            if src.is_dir():
                shutil.copytree(src, dest / inner)
            elif src.exists():
                dest.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dest / inner)


# ----------------------------------------------------------------------------
# Postgres and the API
# ----------------------------------------------------------------------------


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def pg_bin_dir() -> Path:
    """Postgres 18 from the pixeltable-pgserver wheel (the `cloud` dependency group), which
    bundles real Postgres binaries, so nothing depends on the host's apt packages."""
    try:
        import pixeltable_pgserver
    except ImportError:
        pass
    else:
        bundled = Path(pixeltable_pgserver.__file__).parent / "pginstall18" / "bin"
        if (bundled / "pg_ctl").exists():
            return bundled
    if pg_ctl := shutil.which("pg_ctl"):
        return Path(pg_ctl).parent
    raise RuntimeError("Postgres isn't installed: install the `cloud` dependency group.")


def start_postgres(work: Path) -> str:
    """A throwaway Postgres for this app: 127.0.0.1 only, no Unix socket. Returns its URL."""
    bin_dir, pgdata, port = pg_bin_dir(), work / "pgdata", free_port()
    if pgdata.exists():  # left by an earlier process in this container
        subprocess.run([bin_dir / "pg_ctl", "-D", pgdata, "stop", "-m", "immediate"],
                       capture_output=True, check=False)
        shutil.rmtree(pgdata)
    work.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [bin_dir / "initdb", "-D", pgdata, "-U", PG_USER, "--auth=trust", "-E", "UTF8",
         "--no-locale"],
        check=True, capture_output=True,
    )
    options = (f"-c listen_addresses=127.0.0.1 -p {port} -c unix_socket_directories='' "
               "-c shared_buffers=32MB -c max_connections=20 -c fsync=off "
               "-c synchronous_commit=off -c full_page_writes=off")
    subprocess.run(
        [bin_dir / "pg_ctl", "-D", pgdata, "-l", work / "postgres.log", "-o", options, "-w",
         "start"],
        check=True, capture_output=True,
    )
    with psycopg.connect(f"postgresql://{PG_USER}@127.0.0.1:{port}/postgres",
                         autocommit=True) as conn:
        for league in leagues.LEAGUES.values():  # one database per league
            conn.execute(f"CREATE DATABASE {league.database}")
    return f"postgresql://{PG_USER}@127.0.0.1:{port}/{PG_DB}"


def start_api(database_urls: dict[str, str], api_key: str) -> tuple[int, uvicorn.Server]:
    """The CHIRP API on 127.0.0.1 in a background thread. Returns its port and server."""
    from src.api.main import create_app

    port = free_port()
    server = uvicorn.Server(uvicorn.Config(
        create_app(database_urls=database_urls, api_key=api_key),
        host="127.0.0.1", port=port, log_level="warning",
    ))
    threading.Thread(target=server.run, name="chirp-api", daemon=True).start()
    deadline = time.monotonic() + 60
    while not server.started:
        if time.monotonic() > deadline:
            raise RuntimeError("The API didn't start within 60 seconds.")
        time.sleep(0.1)
    return port, server


def stop_postgres(work: Path) -> None:
    pgdata = work / "pgdata"
    if pgdata.exists():
        subprocess.run([pg_bin_dir() / "pg_ctl", "-D", pgdata, "stop", "-m", "fast"],
                       capture_output=True, check=False)


# ----------------------------------------------------------------------------
# The backend
# ----------------------------------------------------------------------------


def league_urls(database_url: str) -> dict[str, str]:
    """Each league's database on the app's Postgres (the men's URL is `database_url`)."""
    return {key: leagues.database_url(database_url, lg) for key, lg in leagues.LEAGUES.items()}


def load_all(database_url: str, snapshot: Path) -> None:
    """Load the men's data (the snapshot's root) and the women's (its women/ folder). A
    women's problem is logged and skipped, so the men's site never goes down with it."""
    urls = league_urls(database_url)
    load_snapshot(urls["men"], snapshot)
    women = snapshot / "women"
    if (women / "processed/chn").is_dir():
        try:
            load_snapshot(urls["women"], women)
        except Exception:
            log.exception("Women's data failed to load; the men's site is unaffected")


def load_snapshot(database_url: str, data_dir: Path) -> None:
    """Load one league's snapshot: the hockey tables, then the prediction log and the run
    history (each replaced as a whole, in its own transaction)."""
    load_database(database_url, build_tables(data_dir / "processed/chn", data_dir / "processed/ids"))
    if found := backups(data_dir / "backups"):
        restore_predictions(database_url, found[-1], replace=True)
    with psycopg.connect(database_url) as conn:
        import_runs(conn, data_dir / "pipeline_runs.csv")
        conn.commit()


@dataclass
class Backend:
    source: GitHubData | LocalData
    database_url: str
    api_url: str
    version: str | None = None
    checked_at: float = 0.0
    error: str | None = None  # the last failed reload, shown nowhere public; see the logs
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _api: uvicorn.Server | None = None

    @classmethod
    def start(cls, repo: str | None = None, token: str | None = None) -> Backend:
        local = os.environ.get("CHIRP_DATA_DIR")
        if local:
            source: GitHubData | LocalData = LocalData(Path(local))
        elif repo and token:
            source = GitHubData(repo, token)
        else:
            raise RuntimeError("Set DATA_REPO and DATA_REPO_TOKEN in the app's secrets "
                               "(docs/cloud.md), or CHIRP_DATA_DIR for a local test.")
        started = time.monotonic()
        database_url = start_postgres(WORK_DIR)
        backend = cls(source, database_url, api_url="")
        backend.reload(backend.source.latest())
        # The dashboard reads the key from settings and the address from CHIRP_API_URL
        key = secrets.token_urlsafe(32)
        settings.api_key = key
        port, backend._api = start_api(league_urls(database_url), key)
        backend.api_url = f"http://127.0.0.1:{port}"
        os.environ["CHIRP_API_URL"] = backend.api_url
        log.warning("CHIRP backend ready in %.0fs (data %s)", time.monotonic() - started,
                    backend.version)
        return backend

    def stop(self) -> None:
        """Shut down the API and Postgres (before starting a backend on newer code)."""
        if self._api is not None:
            self._api.should_exit = True
        stop_postgres(WORK_DIR)

    def reload(self, version: str) -> None:
        dest = WORK_DIR / f"data-{int(time.time() * 1000)}"
        try:
            self.source.fetch(version, dest)
            load_all(self.database_url, dest)
            self.version, self.error = version, None
        finally:
            shutil.rmtree(dest, ignore_errors=True)

    def check_for_new_data(self) -> None:
        """Cheap; call on every page view. At most every CHECK_EVERY seconds it asks for the
        latest data version, and if it changed, reloads in a background thread."""
        if time.monotonic() - self.checked_at < CHECK_EVERY or not self._lock.acquire(False):
            return
        self.checked_at = time.monotonic()

        def work() -> None:
            try:
                latest = self.source.latest()
                if latest != self.version:
                    self.reload(latest)
                    log.warning("Reloaded CHIRP data (%s)", latest)
            except Exception as e:  # keep serving the data already loaded
                self.error = f"{type(e).__name__}: {e}"
                log.exception("Data reload failed; still serving %s", self.version)
            finally:
                self._lock.release()

        threading.Thread(target=work, name="chirp-reload", daemon=True).start()
