"""
The two leagues CHIRP covers: D-I men's and women's college hockey.

Everything that differs between them lives here. The pipeline runs one league at a time,
chosen by the CHIRP_LEAGUE environment variable (`men` by default), so every step of a
refresh, including the subprocesses it starts, works on the same league:

  uv run python -m src.pipeline.refresh                       # men's
  CHIRP_LEAGUE=women uv run python -m src.pipeline.refresh    # women's

Men's data keeps its original home (data/); women's mirrors it under data/women/. Each
league has its own database on the same Postgres server, with identical tables.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

ENV_VAR = "CHIRP_LEAGUE"


@dataclass(frozen=True)
class League:
    key: str  # "men" | "women"
    label: str  # shown on the site
    url_prefix: str  # CHN's path prefix for this league's schedule and team pages
    team_link: re.Pattern  # a CHN team link; group 1 is the team id
    data: Path  # this league's data/ folder
    database: str  # its database on the Postgres server
    model: str  # its frozen win model card in models/
    has_xg: bool  # CHN publishes expected goals
    has_skater_toi: bool  # CHN publishes skaters' time on ice

    def raw(self, *parts: str) -> Path:
        return self.data.joinpath("raw", "chn", *parts)

    def processed(self, *parts: str) -> Path:
        return self.data.joinpath("processed", *parts)


MEN = League(
    key="men",
    label="Men",
    url_prefix="",
    team_link=re.compile(r"/reports/team/[^/]+/(\d+)"),
    data=Path("data"),
    database="hockey",
    model="win_model_v1",
    has_xg=True,
    has_skater_toi=True,
)

WOMEN = League(
    key="women",
    label="Women",
    url_prefix="/women",
    team_link=re.compile(r"/women/team/[^/]+/(\d+)"),
    data=Path("data/women"),
    database="hockey_women",
    model="win_model_women_v1",
    has_xg=False,
    has_skater_toi=False,
)

LEAGUES = {league.key: league for league in (MEN, WOMEN)}


def get(key: str) -> League:
    try:
        return LEAGUES[key]
    except KeyError:
        raise ValueError(f"Unknown league {key!r}: use one of {', '.join(LEAGUES)}") from None


def current() -> League:
    """The league this process works on (CHIRP_LEAGUE, default men)."""
    return get(os.environ.get(ENV_VAR, "men"))


def database_url(base_url: str, league: League) -> str:
    """The same server and credentials as base_url, with the league's database name.

    postgresql://u:p@host:5432/hockey -> postgresql://u:p@host:5432/hockey_women
    """
    head, sep, tail = base_url.rpartition("/")
    if not sep or "@" not in head and "//" not in head:
        raise ValueError(f"Can't read the database name from {base_url!r}")
    query = tail[tail.index("?"):] if "?" in tail else ""
    return f"{head}/{league.database}{query}"
