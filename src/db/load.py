"""
Loads the processed CHN data into PostgreSQL (schema in db/schema.sql).

Full refresh: in one transaction the `hockey` schema is dropped, recreated from
db/schema.sql and refilled from the CSVs. Anyone querying sees the old data until the
commit and the new data after it, never a half-loaded database. The data is small (about
100k rows a season), so a full reload takes seconds and can't drift the way incremental
updates can. Ids stay stable because they come from data/processed/ids/, not the database.

Every name in the box scores must map to an id. A name that doesn't is an error, not a
NULL. The only NULLs are the ones the data really has: no credited scorer ("Uknown"),
bench penalties and TBD opponents.

Usage (from project root, database running via `make db-up`):
  uv run python -m src.db.load
  uv run python -m src.db.load --database-url postgresql://user:pw@host:5432/db

Inputs: data/processed/chn/*.csv, data/processed/ids/*.csv (run `make ids` first)
"""

from __future__ import annotations

import argparse
import logging
import os
import time
from contextlib import contextmanager
from pathlib import Path

import pandas as pd
import psycopg

from config.settings import settings
from src.transform.id_mapping import DATA_DIR, NOT_PLAYERS, OUT_DIR, UNKNOWN_SCORER, load, name_key

log = logging.getLogger(__name__)

SCHEMA_SQL = Path("db/schema.sql")
FEATURES_SQL = Path("db/features.sql")  # views over the tables, rebuilt with them
SCHEMA = "hockey"
BENCH = "BENCH"


class UnmappedError(ValueError):
    pass


# ----------------------------------------------------------------------------
# Building the tables
# ----------------------------------------------------------------------------


def ids_table(name: str, ids_dir: Path) -> pd.DataFrame:
    path = ids_dir / name
    if not path.exists():
        raise SystemExit(f"{path} not found. Run `make ids` first.")
    return pd.read_csv(path)


def map_strict(values: pd.Series, mapping: dict, what: str, allow: set = frozenset()) -> pd.Series:
    """values -> ids; NaN and `allow` -> None; anything else unmapped is an error."""
    out = values.map(mapping)
    bad = values.notna() & ~values.isin(allow) & out.isna()
    if bad.any():
        sample = sorted(set(map(str, values[bad])))[:10]
        raise UnmappedError(f"{bad.sum()} {what} not in the id tables, e.g. {sample}")
    return out.astype("Int64")


def split_officials(s: pd.Series) -> pd.Series:
    return s.map(
        lambda v: [p.strip() for p in v.split(",") if p.strip()] if isinstance(v, str) else None
    )


def number_events(df: pd.DataFrame) -> pd.Series:
    """1.. per game, in game order (period, then time)."""
    order = df.sort_values(["game_id", "period", "time_seconds"], kind="stable")
    return order.groupby("game_id").cumcount().add(1).reindex(df.index)


def build_tables(data_dir: Path = DATA_DIR, ids_dir: Path = OUT_DIR) -> dict[str, pd.DataFrame]:
    """Every table in db/schema.sql, in load order, with the schema's column names."""
    teams = ids_table("teams.csv", ids_dir)
    aliases = ids_table("team_aliases.csv", ids_dir)
    team_seasons = ids_table("team_seasons.csv", ids_dir)
    players = ids_table("players.csv", ids_dir)
    player_seasons = ids_table("player_seasons.csv", ids_dir)
    player_names = ids_table("player_names.csv", ids_dir)
    merges = ids_table("player_id_merges.csv", ids_dir)

    games = load("all_games", data_dir)
    box = load("box_games", data_dir)
    team_stats = load("box_team_stats", data_dir)
    skaters = load("box_skaters", data_dir)
    goalies = load("box_goalies", data_dir)
    goals = load("box_goals", data_dir)
    penalties = load("box_penalties", data_dir)

    team_id = dict(zip(aliases.alias, aliases.team_id))
    pid = dict(zip(zip(player_names.season, player_names.team_id, player_names.name_key),
                   player_names.player_id))  # fmt: skip

    def player_ids(df: pd.DataFrame, col: str, what: str) -> pd.Series:
        """(season, team, name) -> player_id. Names that aren't players map to None."""
        tid = df.team.map(team_id)
        keys = [
            (s, t, name_key(n)) if isinstance(n, str) and n not in NOT_PLAYERS else None
            for s, t, n in zip(df.season, tid, df[col])
        ]
        out = pd.Series([pid.get(k) if k else None for k in keys], index=df.index, dtype="Int64")
        bad = pd.Series([k is not None for k in keys], index=df.index) & out.isna()
        if bad.any():
            sample = sorted(set(zip(df.team[bad], df[col][bad])))[:10]
            raise UnmappedError(f"{bad.sum()} {what} not in player_names, e.g. {sample}")
        return out

    seasons = pd.DataFrame({"season": sorted(games.season.unique())})
    seasons["start_year"] = seasons.season.str[:4].astype(int)

    # games: schedule + box score details
    g = games.merge(
        box.drop(columns=["season", "date", "home_team", "away_team"]), on="game_id", how="left"
    )
    games_t = pd.DataFrame(
        {
            "game_id": g.game_id,
            "season": g.season,
            "game_date": g.date,
            "home_team_id": map_strict(g.home_team, team_id, "home teams", allow={"TBD"}),
            "away_team_id": map_strict(g.away_team, team_id, "away teams", allow={"TBD"}),
            "home_goals": g.home_goals,
            "away_goals": g.away_goals,
            "is_played": g.is_played,
            "is_neutral": g.is_neutral,
            "is_conference": g.is_conference,
            "ot_periods": g.ot_periods.fillna(0),
            "shootout_winner_team_id": map_strict(g.shootout_winner, team_id, "shootout winners"),
            "shootout_score": g.shootout_score,
            "game_type": g.game_type,
            "event": g.event,
            "game_note": g.game_note,
            "venue": g.venue,
            "attendance": g.attendance,
            "referees": split_officials(g.referees),
            "asst_referees": split_officials(g.asst_referees),
            "box_score_url": g.box_score_url,
            "source": g.source,
        }
    )

    ts = team_stats.assign(
        team_id=map_strict(team_stats.team, team_id, "teams"),
        opponent_team_id=map_strict(team_stats.opponent, team_id, "opponents"),
    ).drop(columns=["season", "date", "team", "opponent"])

    sk = skaters.assign(
        player_id=player_ids(skaters, "player", "skaters"),
        team_id=map_strict(skaters.team, team_id, "teams"),
    ).drop(columns=["season", "date", "team", "opponent", "is_home", "player"])

    gl = goalies.assign(
        player_id=player_ids(goalies, "goalie", "goalies"),
        team_id=map_strict(goalies.team, team_id, "teams"),
    ).drop(columns=["season", "date", "team", "opponent", "is_home", "goalie"])

    goals_t = pd.DataFrame(
        {
            "game_id": goals.game_id,
            "goal_number": number_events(goals),
            "team_id": map_strict(goals.team, team_id, "teams"),
            "period": goals.period,
            "period_seconds": goals.time_seconds,
            "strength": goals.strength,
            "is_pp": goals.is_pp,
            "is_sh": goals.is_sh,
            "is_en": goals.is_en,
            "is_extra_attacker": goals.is_extra_attacker,
            "is_penalty_shot": goals.is_penalty_shot,
            "scorer_id": player_ids(goals, "scorer", "scorers"),
            "assist1_id": player_ids(goals, "assist1", "assists"),
            "assist2_id": player_ids(goals, "assist2", "assists"),
            "scorer_season_goal": goals.scorer_season_goal.where(goals.scorer != UNKNOWN_SCORER),
        }
    )

    pen_t = pd.DataFrame(
        {
            "game_id": penalties.game_id,
            "penalty_number": number_events(penalties),
            "team_id": map_strict(penalties.team, team_id, "teams"),
            "player_id": player_ids(penalties, "player", "penalized players"),
            "is_bench": penalties.player.eq(BENCH),
            "period": penalties.period,
            "period_seconds": penalties.time_seconds,
            "minutes": penalties.minutes,
            "infraction": penalties.infraction,
        }
    )

    return {
        "seasons": seasons,
        "conferences": pd.DataFrame(
            {"conference": sorted(team_seasons.conference.dropna().unique())}
        ),
        "teams": teams,
        "team_aliases": aliases,
        "team_seasons": team_seasons,
        "players": players,
        "player_seasons": player_seasons,
        "player_names": player_names.drop(columns="name_key"),
        "player_id_merges": merges,
        "games": games_t,
        "team_game_stats": ts,
        "skater_game_stats": sk,
        "goalie_game_stats": gl,
        "goals": goals_t,
        "penalties": pen_t,
    }


# ----------------------------------------------------------------------------
# Writing to Postgres
# ----------------------------------------------------------------------------


def column_types(conn: psycopg.Connection, table: str) -> list[tuple[str, str]]:
    rows = conn.execute(
        "SELECT column_name, data_type FROM information_schema.columns "
        "WHERE table_schema = %s AND table_name = %s ORDER BY ordinal_position",
        (SCHEMA, table),
    ).fetchall()
    if not rows:
        raise ValueError(f"table {SCHEMA}.{table} not in the database")
    return rows


def to_python(value, data_type: str):
    """One value -> what COPY expects for the column's type."""
    if value is None or (not isinstance(value, list) and pd.isna(value)):
        return None
    if data_type in ("smallint", "integer", "bigint"):
        return int(value)
    if data_type == "boolean":
        return bool(value)
    if data_type == "numeric":
        return float(value)
    if data_type == "ARRAY":
        return list(value)
    return str(value)


def copy_table(conn: psycopg.Connection, table: str, df: pd.DataFrame) -> int:
    cols = column_types(conn, table)
    names = [c for c, _ in cols]
    extra = set(df.columns) - set(names)
    df = df.drop(columns=list(extra & {"name_key", "first_season", "last_season", "n_seasons"}))
    if unknown := set(df.columns) - set(names):
        raise ValueError(f"{table}: columns not in the schema: {sorted(unknown)}")
    use = [(c, t) for c, t in cols if c in df.columns]
    with conn.cursor().copy(
        f"COPY {SCHEMA}.{table} ({', '.join(c for c, _ in use)}) FROM STDIN"
    ) as cp:
        for row in df[[c for c, _ in use]].itertuples(index=False):
            cp.write_row([to_python(v, t) for v, (_, t) in zip(row, use)])
    return len(df)


def load_database(database_url: str, tables: dict[str, pd.DataFrame]) -> dict[str, int]:
    counts = {}
    with psycopg.connect(database_url) as conn:  # one transaction; commits on success
        conn.execute(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE")
        conn.execute(SCHEMA_SQL.read_text())
        conn.execute(f"SET search_path TO {SCHEMA}")
        for table, df in tables.items():
            counts[table] = copy_table(conn, table, df)
        conn.execute(FEATURES_SQL.read_text())
        check_load(conn, tables)
    return counts


def check_load(conn: psycopg.Connection, tables: dict[str, pd.DataFrame]) -> None:
    """Row counts and a few totals must match the CSVs, or the transaction rolls back."""
    problems = []
    for table, df in tables.items():
        (n,) = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
        if n != len(df):
            problems.append(f"{table}: {n} rows loaded, {len(df)} expected")
    (view_goals,) = conn.execute(
        "SELECT COALESCE(SUM(goals), 0) FROM skater_season_totals"
    ).fetchone()
    expected = int(tables["skater_game_stats"].goals.sum())
    if view_goals != expected:
        problems.append(f"skater_season_totals goals {view_goals} != box score total {expected}")
    (team_goals,) = conn.execute(
        "SELECT COALESCE(SUM(goals_for), 0) FROM team_season_totals"
    ).fetchone()
    if team_goals != int(tables["team_game_stats"].goals.sum()):
        problems.append("team_season_totals goals don't match team_game_stats")
    if problems:
        raise RuntimeError("load check failed:\n  " + "\n  ".join(problems))


@contextmanager
def refresh_guard(database_url: str):
    """A load run by hand takes the refresh pipeline's lock, so it can't overlap a refresh.
    Inside the pipeline the lock is already held by the refresh itself."""
    from src.pipeline.refresh import IN_PIPELINE_ENV, LOCK_ID

    if os.environ.get(IN_PIPELINE_ENV):
        yield
        return
    with psycopg.connect(database_url, autocommit=True) as conn:
        if not conn.execute("SELECT pg_try_advisory_lock(%s)", (LOCK_ID,)).fetchone()[0]:
            raise SystemExit(
                "A data refresh is running (see `make runs`); try again when it's done."
            )
        try:
            yield
        finally:
            conn.execute("SELECT pg_advisory_unlock(%s)", (LOCK_ID,))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--database-url", default=settings.database_url)
    ap.add_argument("--data-dir", type=Path, default=DATA_DIR)
    ap.add_argument("--ids-dir", type=Path, default=OUT_DIR)
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")

    start = time.perf_counter()
    tables = build_tables(args.data_dir, args.ids_dir)
    try:
        with refresh_guard(args.database_url):
            counts = load_database(args.database_url, tables)
    except psycopg.OperationalError as e:
        raise SystemExit(f"Can't connect to the database ({e}). Is it running? Try `make db-up`.")
    for table, n in counts.items():
        log.info("%-20s %8s rows", table, f"{n:,}")
    log.info("loaded %s rows in %.1fs", f"{sum(counts.values()):,}", time.perf_counter() - start)


if __name__ == "__main__":
    main()
