"""
Prediction log: every D-I game's win probability, saved before the game (win model v1).

  uv run python -m src.pipeline.predict      # or `make predict`; the nightly refresh runs it
                                             # after the load

Rules
  * Upcoming: each D-I vs D-I game in the next DAYS_AHEAD days (Eastern dates) is logged.
    Until game day, every run refreshes it, because new results keep arriving. The run on
    game day writes the final pre-game prediction, and the row is then **locked**: it never
    changes again. (If the game is moved to a later date, it unlocks until the new date.)
  * Backfill: played games not yet in the log get their pre-game prediction (inputs from games
    before the date) and `backfilled = true`. Only seasons after the model's training season:
    on its own training games the model would be grading its own homework. Backfilled rows
    are exactly what the frozen model would have said, but they weren't logged in advance,
    so they're always reported separately.
  * Results aren't stored. Readers join hockey.games, so a corrected score is picked up.
  * The log lives in its own schema (db/predictions.sql), which the nightly load never
    touches.
"""

from __future__ import annotations

import argparse
import datetime as dt
from pathlib import Path
from zoneinfo import ZoneInfo

import psycopg
from psycopg.rows import dict_row

from config.settings import settings
from src.db.load import refresh_guard
from src.models.win_model import load_card, predict_game

PREDICTIONS_SQL = Path(__file__).resolve().parents[2] / "db" / "predictions.sql"
DAYS_AHEAD = 7
EASTERN = ZoneInfo("America/New_York")

CANDIDATES_SQL = """
SELECT g.game_id, g.season, g.game_date, g.home_team_id, g.away_team_id, g.is_neutral,
       g.is_played
FROM hockey.games g
JOIN hockey.teams h ON h.team_id = g.home_team_id
JOIN hockey.teams a ON a.team_id = g.away_team_id
WHERE h.is_d1 AND a.is_d1 AND (
    -- upcoming in the window
    (NOT g.is_played AND g.game_date BETWEEN %(today)s AND %(until)s)
    -- played, after the training season, and never logged: backfill
    OR (%(backfill)s AND g.is_played AND g.season > %(trained)s AND g.game_date <= %(today)s
        AND NOT EXISTS (SELECT 1 FROM predictions.game_predictions p
                        WHERE p.game_id = g.game_id AND p.model = %(model)s))
)
ORDER BY g.game_date, g.game_id
"""

UPSERT_SQL = """
INSERT INTO predictions.game_predictions AS p (
    game_id, model, season, game_date, home_team_id, away_team_id, neutral,
    home_win_probability, home_games_played, away_games_played,
    home_close_shot_share, away_close_shot_share,
    home_goal_diff_per_game, away_goal_diff_per_game,
    reliable, backfilled, logged_on)
VALUES (
    %(game_id)s, %(model)s, %(season)s, %(game_date)s, %(home_team_id)s, %(away_team_id)s,
    %(neutral)s, %(p)s, %(hgp)s, %(agp)s, %(hcs)s, %(acs)s, %(hgd)s, %(agd)s,
    %(reliable)s, %(backfilled)s, %(today)s)
ON CONFLICT (game_id, model) DO UPDATE SET
    season = EXCLUDED.season, game_date = EXCLUDED.game_date,
    home_team_id = EXCLUDED.home_team_id, away_team_id = EXCLUDED.away_team_id,
    neutral = EXCLUDED.neutral, home_win_probability = EXCLUDED.home_win_probability,
    home_games_played = EXCLUDED.home_games_played, away_games_played = EXCLUDED.away_games_played,
    home_close_shot_share = EXCLUDED.home_close_shot_share,
    away_close_shot_share = EXCLUDED.away_close_shot_share,
    home_goal_diff_per_game = EXCLUDED.home_goal_diff_per_game,
    away_goal_diff_per_game = EXCLUDED.away_goal_diff_per_game,
    reliable = EXCLUDED.reliable, logged_on = EXCLUDED.logged_on, updated_at = now()
WHERE p.logged_on < EXCLUDED.game_date      -- locked once written on or after game day
RETURNING (xmax = 0) AS inserted
"""


def eastern_today() -> dt.date:
    return dt.datetime.now(EASTERN).date()


def log_predictions(
    database_url: str,
    today: dt.date | None = None,
    days_ahead: int = DAYS_AHEAD,
    backfill: bool = True,
) -> dict[str, int]:
    """Write the log; returns counts of what happened."""
    today = today or eastern_today()
    card = load_card()
    counts = {"logged": 0, "updated": 0, "locked": 0, "backfilled": 0}
    with psycopg.connect(database_url) as conn:
        conn.execute(PREDICTIONS_SQL.read_text())
        with conn.cursor(row_factory=dict_row) as cur:
            games = cur.execute(CANDIDATES_SQL, {
                "today": today, "until": today + dt.timedelta(days=days_ahead),
                "backfill": backfill, "trained": card["trained_on"]["season"],
                "model": card["name"],
            }).fetchall()  # fmt: skip
        for g in games:
            pred = predict_game(conn, card, g)
            h, a = pred["home_inputs"], pred["away_inputs"]
            is_backfill = g["is_played"]
            row = conn.execute(UPSERT_SQL, {
                "game_id": g["game_id"], "model": card["name"], "season": g["season"],
                "game_date": g["game_date"], "home_team_id": g["home_team_id"],
                "away_team_id": g["away_team_id"], "neutral": g["is_neutral"],
                "p": pred["home_win_probability"],
                "hgp": h["games_played"], "agp": a["games_played"],
                "hcs": h["close_shot_share"], "acs": a["close_shot_share"],
                "hgd": h["goal_diff_per_game"], "agd": a["goal_diff_per_game"],
                "reliable": pred["reliable"], "backfilled": is_backfill, "today": today,
            }).fetchone()  # fmt: skip
            if row is None:
                counts["locked"] += 1
            elif is_backfill:
                counts["backfilled"] += 1
            elif row[0]:
                counts["logged"] += 1
            else:
                counts["updated"] += 1
        conn.commit()
    return counts


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--today", type=dt.date.fromisoformat, help="Eastern date to act as (testing)")
    ap.add_argument("--days-ahead", type=int, default=DAYS_AHEAD)
    ap.add_argument("--no-backfill", action="store_true")
    args = ap.parse_args()
    with refresh_guard(settings.database_url):
        counts = log_predictions(
            settings.database_url, args.today, args.days_ahead, backfill=not args.no_backfill
        )
    print(
        f"Prediction log: {counts['logged']} new, {counts['updated']} updated, "
        f"{counts['backfilled']} backfilled, {counts['locked']} already locked"
    )


if __name__ == "__main__":
    main()
