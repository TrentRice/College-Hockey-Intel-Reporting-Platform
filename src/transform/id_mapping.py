"""
Assigns stable IDs to every team and player in data/processed/chn/, across all seasons.

The box score tables name teams and players with plain text, which breaks joins whenever a
name changes ("Rensselaer" -> "RPI", "Joseph Grainda" -> "JJ Grainda") or two players share
one. This step turns those names into surrogate keys that the database and API use.

Teams
  D1 teams carry a CHN team id on the schedule page, so each CHN id is one team. Non-D1
  opponents (Maryville, St. Anselm, ...) have none and are keyed by name. "TBD" is not a team.

Players
  Only goal scorers link to a CHN player page (scorer_chn_id). Everyone else -- skaters who
  never scored, goalies, assists, penalties -- appears by name only. A player-season is
  identified by (season, team_id, name_key), and player-seasons are linked into one player:
    1. same CHN player id                      -> same player (also links transfers)
    2. same team + same name_key, other season -> same player, unless that team/name has
                                                  two different CHN ids (two real people);
                                                  then the id-less seasons stay separate
                                                  and are marked 'ambiguous'
    3. history ends on team A in season N, same name_key starts on team B in season N+1,
       one-to-one, not two different CHN ids    -> same player (a transfer who hasn't scored
                                                  for the new team yet); ~99% right when
                                                  checked against CHN ids
  Each player_season's `link` says which rule placed it (single_season = no link needed).
  CHN's "Uknown" scorer rows are ignored: the CHN ids on them point at players who are not
  in that game's box score, so the links are wrong.

Stable IDs
  The outputs double as the registry: on each run, existing ids are read back and reused,
  so adding a season never renumbers anyone. New teams/players get max(id) + 1. If new data
  joins two existing players into one, the lower id survives and player_id_merges.csv
  records old -> new so callers holding the old id can be redirected.

Usage (from project root):
  uv run python -m src.transform.id_mapping

Outputs (data/processed/ids/):
  teams.csv             team_id, chn_team_id, name, is_d1
  team_aliases.csv      team_id, alias
  team_seasons.csv      team_id, season, conference
  players.csv           player_id, chn_player_id, name, position, first_season, last_season,
                        n_seasons
  player_seasons.csv    player_id, season, team_id, name, position, games, link  (the roster)
  player_names.csv      player_id, season, team_id, name, name_key  (every spelling; the
                        lookup the loader uses and the registry the next run reads)
  player_id_merges.csv  old_player_id, new_player_id, merged_on
"""

from __future__ import annotations

import argparse
import datetime as dt
import logging
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

log = logging.getLogger(__name__)

DATA_DIR = Path("data/processed/chn")
OUT_DIR = Path("data/processed/ids")
UNKNOWN_SCORER = "Uknown"  # CHN's own spelling for a goal with no credited scorer
NOT_PLAYERS = {UNKNOWN_SCORER, "BENCH"}  # BENCH = bench minor, charged to the team
NOT_TEAMS = {"TBD"}
NAME_SUFFIXES = {"jr", "sr", "ii", "iii", "iv"}
KEY = ["season", "team_id", "name_key"]  # one player-season


def name_key(name: str) -> str:
    """Matching form of a name: no accents, case, punctuation or suffix.
    'Jérémie Minville' == 'Jeremie Minville', 'Jimmy Dowd, Jr.' == 'Jimmy Dowd'."""
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[^a-z\s-]", "", s).replace("-", " ")
    return " ".join(p for p in s.split() if p not in NAME_SUFFIXES)


def load(table: str, data_dir: Path = DATA_DIR) -> pd.DataFrame:
    files = sorted(data_dir.glob(f"{table}_*.csv"))
    if not files:
        raise FileNotFoundError(f"no {table}_*.csv in {data_dir}")
    return pd.concat([pd.read_csv(f) for f in files], ignore_index=True)


def read_previous(name: str, out_dir: Path) -> pd.DataFrame | None:
    path = out_dir / name
    return pd.read_csv(path) if path.exists() else None


def next_ids(start: int, n: int) -> list[int]:
    return list(range(start + 1, start + 1 + n))


# ----------------------------------------------------------------------------
# Teams
# ----------------------------------------------------------------------------


@dataclass
class Teams:
    teams: pd.DataFrame
    aliases: pd.DataFrame
    seasons: pd.DataFrame

    def id_by_name(self) -> dict[str, int]:
        return dict(zip(self.aliases.alias, self.aliases.team_id))


def build_teams(games: pd.DataFrame, previous: Teams | None = None) -> Teams:
    """games: all_games rows. One team per CHN team id; non-D1 teams by name."""
    sides = [
        games[["season", f"{s}_team", f"{s}_team_id", f"{s}_conference"]].set_axis(
            ["season", "name", "chn_team_id", "conference"], axis=1
        )
        for s in ("home", "away")
    ]
    seen = pd.concat(sides).drop_duplicates()
    seen = seen[~seen.name.isin(NOT_TEAMS)].copy()
    seen["chn_team_id"] = seen.chn_team_id.astype("Int64")

    clash = seen.groupby("name").chn_team_id.nunique()
    if (clash > 1).any():
        raise ValueError(f"team names used by two CHN ids: {list(clash[clash > 1].index)}")
    seen["natural_key"] = [
        f"chn:{c}" if pd.notna(c) else f"name:{name_key(n)}"
        for c, n in zip(seen.chn_team_id, seen.name)
    ]

    # reuse ids from the last run
    known: dict[str, int] = {}
    if previous is not None:
        t = previous.teams
        known.update({f"chn:{c}": i for c, i in zip(t.chn_team_id, t.team_id) if pd.notna(c)})
        non_d1 = set(t.team_id[t.chn_team_id.isna()])
        a = previous.aliases[previous.aliases.team_id.isin(non_d1)]
        known.update({f"name:{name_key(n)}": i for n, i in zip(a.alias, a.team_id)})

    keys = (
        seen.sort_values(["chn_team_id", "name"], na_position="last")
        .drop_duplicates("natural_key")
        .natural_key
    )
    new = [k for k in keys if k not in known]
    known.update(zip(new, next_ids(max(known.values(), default=0), len(new))))
    seen["team_id"] = seen.natural_key.map(known)

    latest = seen.sort_values("season").groupby("team_id").last()
    teams = pd.DataFrame(
        {
            "team_id": latest.index,
            "chn_team_id": latest.chn_team_id.values,
            "name": latest.name.values,
            "is_d1": latest.chn_team_id.notna().values,
        }
    ).sort_values("team_id")
    aliases = seen[["team_id", "name"]].drop_duplicates().rename(columns={"name": "alias"})
    team_seasons = (
        seen[["team_id", "season", "conference"]]
        .drop_duplicates(["team_id", "season"])
        .sort_values(["season", "team_id"])
    )
    return Teams(
        teams.reset_index(drop=True),
        aliases.sort_values(["team_id", "alias"]).reset_index(drop=True),
        team_seasons.reset_index(drop=True),
    )


# ----------------------------------------------------------------------------
# Players
# ----------------------------------------------------------------------------


def player_appearances(tables: dict[str, pd.DataFrame], team_ids: dict[str, int]) -> pd.DataFrame:
    """Every place a player's name shows up -> season, team_id, game_id, name, position, chn_id."""
    sk, gl, go, pe = (
        tables[t] for t in ("box_skaters", "box_goalies", "box_goals", "box_penalties")
    )
    cols = ["season", "team", "game_id", "name", "position", "chn_id", "plays"]
    parts = [
        sk.assign(name=sk.player, chn_id=pd.NA, plays=True),
        gl.assign(name=gl.goalie, position="G", chn_id=pd.NA, plays=True),
        go.assign(name=go.scorer, position=pd.NA, chn_id=go.scorer_chn_id, plays=False),
        go.assign(name=go.assist1, position=pd.NA, chn_id=pd.NA, plays=False),
        go.assign(name=go.assist2, position=pd.NA, chn_id=pd.NA, plays=False),
        pe.assign(name=pe.player, position=pd.NA, chn_id=pd.NA, plays=False),
    ]
    a = pd.concat([p[cols] for p in parts], ignore_index=True)
    a = a[a.name.notna() & ~a.name.isin(NOT_PLAYERS)].copy()

    missing = set(a.team) - set(team_ids)
    if missing:
        raise ValueError(f"box score teams not on any schedule: {sorted(missing)}")
    a["team_id"] = a.team.map(team_ids)
    a["name_key"] = a.name.map(name_key)
    blank = a.name_key == ""
    if blank.any():
        log.warning(
            "skipping %d names with nothing to match on: %s",
            blank.sum(),
            sorted(set(a.name[blank])),
        )
        a = a[~blank]
    a["chn_id"] = a.chn_id.astype("Int64")
    return a.drop(columns="team")


def player_seasons_from(appearances: pd.DataFrame) -> pd.DataFrame:
    """One row per (season, team_id, name_key): display name, position, CHN id, games."""
    a = appearances
    # display name: the spelling the box score's player tables use most
    named = a.sort_values("plays", ascending=False)
    name = named.groupby(KEY).name.agg(lambda s: s.mode().iloc[0])
    pos = a.dropna(subset=["position"]).groupby(KEY).position.agg(lambda s: s.mode().iloc[0])
    games = a[a.plays].groupby(KEY).game_id.nunique()
    chn = a.dropna(subset=["chn_id"]).groupby(KEY).chn_id.unique()

    ps = pd.DataFrame({"name": name}).join(pos).join(games.rename("games")).reset_index()
    ps["games"] = ps.games.fillna(0).astype(int)
    ps["chn_ids"] = [list(chn.get(k, [])) for k in zip(ps.season, ps.team_id, ps.name_key)]
    two = ps[ps.chn_ids.str.len() > 1]
    for r in two.itertuples():
        log.warning(
            "%s %s %s has CHN ids %s; not linking by id", r.season, r.team_id, r.name, r.chn_ids
        )
    ps["chn_player_id"] = [c[0] if len(c) == 1 else pd.NA for c in ps.chn_ids]
    ps["chn_player_id"] = ps.chn_player_id.astype("Int64")
    return ps.drop(columns="chn_ids")


class _UnionFind:
    def __init__(self, n: int):
        self.parent = list(range(n))

    def find(self, i: int) -> int:
        while self.parent[i] != i:
            self.parent[i] = self.parent[self.parent[i]]
            i = self.parent[i]
        return i

    def union(self, i: int, j: int) -> None:
        self.parent[self.find(i)] = self.find(j)


def link_player_seasons(ps: pd.DataFrame) -> pd.DataFrame:
    """Adds `group` (one per real player) and `link` (how the season was linked)."""
    ps = ps.reset_index(drop=True)
    uf = _UnionFind(len(ps))
    for idx in ps.dropna(subset=["chn_player_id"]).groupby("chn_player_id").groups.values():
        for j in idx[1:]:
            uf.union(idx[0], j)

    ambiguous: set[int] = set()
    for idx in ps.groupby(["team_id", "name_key"]).groups.values():
        n_ids = ps.loc[idx, "chn_player_id"].dropna().nunique()
        if n_ids <= 1:
            for j in idx[1:]:
                uf.union(idx[0], j)
        else:
            ambiguous.update(i for i in idx if pd.isna(ps.at[i, "chn_player_id"]))

    ps["group"] = [uf.find(i) for i in range(len(ps))]
    size = ps.group.map(ps.group.value_counts())
    ps["link"] = "single_season"
    ps.loc[size > 1, "link"] = "team_and_name"
    ps.loc[ps.chn_player_id.notna(), "link"] = "chn_id"
    ps.loc[list(ambiguous), "link"] = "ambiguous"

    transfers = transfer_links(ps)
    moved = ps.group.isin(transfers.keys())  # rows of the later part of each transfer
    first = ps.groupby("group").season.transform("min") == ps.season
    ps.loc[moved & first & (ps.link != "chn_id"), "link"] = "name_transfer"
    for later, earlier in transfers.items():
        uf.union(later, earlier)
    ps["group"] = [uf.find(i) for i in range(len(ps))]
    # the season before a transfer was 'single_season' until the transfer joined it on
    joined = ps.group.map(ps.group.value_counts()) > 1
    ps.loc[joined & (ps.link == "single_season"), "link"] = "name_transfer"
    return ps


def transfer_links(ps: pd.DataFrame) -> dict[int, int]:
    """Rule 3: a player whose history ends on one team the season before another player with
    the same name_key starts on a different team -> the same player moving. Only when that
    pairing is one-to-one and the two don't carry different CHN ids. Checked against players
    whose CHN ids prove the answer, this rule is ~99% right; it mostly catches transfers who
    have not scored yet for their new team. -> {later group: earlier group}"""
    year = ps.season.str[:4].astype(int)
    g = ps.assign(year=year).sort_values("year").groupby("group")
    span = pd.DataFrame(
        {
            "first": g.year.min(),
            "last": g.year.max(),
            "first_key": g.name_key.first(),
            "last_key": g.name_key.last(),
            "first_team": g.team_id.first(),
            "last_team": g.team_id.last(),
            "chn": g.chn_player_id.max(),
        }
    )
    ends = span.reset_index().rename(columns={"group": "earlier"})
    begins = span.reset_index().rename(columns={"group": "later"})
    pairs = begins.merge(ends, left_on="first_key", right_on="last_key", suffixes=("", "_e"))
    pairs = pairs[
        (pairs["first"] == pairs["last_e"] + 1)
        & (pairs.first_team != pairs.last_team_e)
        & ~(pairs.chn.notna() & pairs.chn_e.notna())  # both known: CHN already decided
    ]
    one_to_one = (pairs.groupby("later").earlier.transform("size") == 1) & (
        pairs.groupby("earlier").later.transform("size") == 1
    )
    return dict(zip(pairs.later[one_to_one], pairs.earlier[one_to_one]))


def assign_player_ids(
    ps: pd.DataFrame,
    prev_seasons: pd.DataFrame | None = None,
    prev_players: pd.DataFrame | None = None,
    today: str | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """ps: linked player-seasons. Reuses ids from the previous run. -> (ps with player_id, merges)."""
    old: dict[tuple, int] = {}
    if prev_seasons is not None:
        old = dict(zip(zip(*(prev_seasons[k] for k in KEY)), prev_seasons.player_id))
    old_by_chn: dict[int, int] = {}
    if prev_players is not None:
        p = prev_players.dropna(subset=["chn_player_id"])
        old_by_chn = dict(zip(p.chn_player_id.astype(int), p.player_id))

    ps = ps.copy()
    ps["old_id"] = [old.get(k) for k in zip(*(ps[k] for k in KEY))]
    ps["old_chn_id"] = [old_by_chn.get(int(c)) if pd.notna(c) else None for c in ps.chn_player_id]

    group_id: dict[int, int] = {}
    merges = []
    new_groups = []
    for g, rows in ps.groupby("group"):
        ids = set(rows.old_id.dropna().astype(int)) | set(rows.old_chn_id.dropna().astype(int))
        if not ids:
            new_groups.append((rows.season.min(), rows.team_id.iloc[0], rows.name_key.iloc[0], g))
            continue
        keep = min(ids)
        group_id[g] = keep
        merges += [(i, keep) for i in sorted(ids - {keep})]

    start = max([*old.values(), *old_by_chn.values()], default=0)
    for (*_, g), pid in zip(sorted(new_groups), next_ids(start, len(new_groups))):
        group_id[g] = pid
    ps["player_id"] = ps.group.map(group_id)

    if prev_seasons is not None:
        gone = set(prev_seasons.player_id) - set(ps.player_id) - {m[0] for m in merges}
        if gone:
            log.warning("%d player ids from the last run no longer appear in the data", len(gone))
    merged_on = today or dt.date.today().isoformat()
    merges_df = pd.DataFrame(merges, columns=["old_player_id", "new_player_id"]).assign(
        merged_on=merged_on
    )
    return ps.drop(columns=["old_id", "old_chn_id", "group"]), merges_df


def players_from(ps: pd.DataFrame) -> pd.DataFrame:
    s = ps.sort_values(["season", "games"])
    g = s.groupby("player_id")
    out = pd.DataFrame(
        {
            "chn_player_id": g.chn_player_id.max(),
            "name": g.name.last(),
            "position": s.dropna(subset=["position"]).groupby("player_id").position.last(),
            "first_season": g.season.min(),
            "last_season": g.season.max(),
            "n_seasons": g.season.nunique(),
        }
    )
    return out.reset_index().sort_values("player_id").reset_index(drop=True)


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------


def build(data_dir: Path = DATA_DIR, out_dir: Path = OUT_DIR) -> dict[str, pd.DataFrame]:
    tables = {
        t: load(t, data_dir)
        for t in ("all_games", "box_skaters", "box_goalies", "box_goals", "box_penalties")
    }

    prev_teams = None
    if (out_dir / "teams.csv").exists():
        prev_teams = Teams(
            read_previous("teams.csv", out_dir).astype({"chn_team_id": "Int64"}),
            read_previous("team_aliases.csv", out_dir),
            read_previous("team_seasons.csv", out_dir),
        )
    teams = build_teams(tables["all_games"], prev_teams)

    appearances = player_appearances(tables, teams.id_by_name())
    ps = link_player_seasons(player_seasons_from(appearances))
    # player_names.csv is the registry: every (season, team, spelling) -> player_id
    prev_names = read_previous("player_names.csv", out_dir)
    if prev_names is None:
        prev_names = read_previous("player_seasons.csv", out_dir)  # older layout
    ps, merges = assign_player_ids(ps, prev_names, read_previous("players.csv", out_dir))
    prev_merges = read_previous("player_id_merges.csv", out_dir)
    if prev_merges is not None:
        merges = pd.concat([prev_merges, merges], ignore_index=True)

    ps = ps.sort_values(["season", "team_id", "player_id", "games"], ascending=[1, 1, 1, 0])
    names = ps[["player_id", "season", "team_id", "name", "name_key"]]
    return {
        "teams.csv": teams.teams,
        "team_aliases.csv": teams.aliases,
        "team_seasons.csv": teams.seasons,
        "players.csv": players_from(ps),
        "player_seasons.csv": roster_from(ps),
        "player_names.csv": names,
        "player_id_merges.csv": merges,
    }


LINK_RANK = {
    "chn_id": 0,
    "team_and_name": 1,
    "name_transfer": 2,
    "single_season": 3,
    "ambiguous": 4,
}


def roster_from(ps: pd.DataFrame) -> pd.DataFrame:
    """One row per player, season and team. A player CHN spells two ways in one season
    ('Jake' / 'Jacob Leblanc', linked by CHN id) is one roster row under the spelling with
    the most games; every spelling stays in player_names.csv."""
    ps = ps.sort_values(["player_id", "season", "team_id", "games"], ascending=[1, 1, 1, 0])
    g = ps.groupby(["player_id", "season", "team_id"], sort=False)
    out = g.first()[["name", "position"]]
    out["games"] = g.games.sum()
    out["link"] = g.link.agg(lambda s: min(s, key=LINK_RANK.__getitem__))
    return out.reset_index().sort_values(["season", "team_id", "player_id"]).reset_index(drop=True)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--data-dir", type=Path, default=DATA_DIR)
    ap.add_argument("--out-dir", type=Path, default=OUT_DIR)
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")

    out = build(args.data_dir, args.out_dir)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    for name, df in out.items():
        df.to_csv(args.out_dir / name, index=False)

    t, p, ps = out["teams.csv"], out["players.csv"], out["player_seasons.csv"]
    log.info("teams: %d (%d D1, %d non-D1)", len(t), t.is_d1.sum(), (~t.is_d1).sum())
    log.info("players: %d, %d with a CHN id", len(p), p.chn_player_id.notna().sum())
    log.info("player-seasons by link: %s", ps.link.value_counts().to_dict())
    log.info("multi-team players: %d", ps.groupby("player_id").team_id.nunique().gt(1).sum())
    log.info("wrote %s", args.out_dir)


if __name__ == "__main__":
    main()
