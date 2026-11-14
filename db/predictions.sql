-- Prediction log: each game's win probability, saved before the game.
-- Written by src/pipeline/predict.py (nightly, after the load). Read by /v1/predictions.
--
-- Its own schema on purpose: the nightly load rebuilds `hockey` from scratch, and this log
-- must survive that. So there are no foreign keys into `hockey`; game and team ids are
-- stable across loads. Results aren't stored here: readers join hockey.games, so a
-- corrected score is picked up automatically.

CREATE SCHEMA IF NOT EXISTS predictions;

CREATE TABLE IF NOT EXISTS predictions.game_predictions (
    game_id                 TEXT NOT NULL,
    model                   TEXT NOT NULL,            -- e.g. win_model_v1
    season                  TEXT NOT NULL,
    game_date               DATE NOT NULL,
    home_team_id            INTEGER NOT NULL,
    away_team_id            INTEGER NOT NULL,
    neutral                 BOOLEAN NOT NULL,
    home_win_probability    DOUBLE PRECISION NOT NULL
                            CHECK (home_win_probability > 0 AND home_win_probability < 1),
    home_games_played       INTEGER NOT NULL,
    away_games_played       INTEGER NOT NULL,
    home_close_shot_share   DOUBLE PRECISION,
    away_close_shot_share   DOUBLE PRECISION,
    home_goal_diff_per_game DOUBLE PRECISION,
    away_goal_diff_per_game DOUBLE PRECISION,
    reliable                BOOLEAN NOT NULL,         -- both teams past the 3-game warm-up
    -- true = written after the game, from games before its date (the frozen model's
    -- numbers, but not logged in advance)
    backfilled              BOOLEAN NOT NULL,
    logged_on               DATE NOT NULL,            -- Eastern date of the last write
    first_logged_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (game_id, model),
    CHECK (home_team_id <> away_team_id)
);

-- A row is locked once it's been written on or after its game date (the final pre-game
-- prediction, or a backfill). src/pipeline/predict.py never updates a locked row.
CREATE INDEX IF NOT EXISTS game_predictions_season_idx
    ON predictions.game_predictions (season, model, game_date);
