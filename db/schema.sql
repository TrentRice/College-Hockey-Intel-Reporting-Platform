-- College hockey database: PostgreSQL schema.
--
-- Star schema: dimension tables (who/what/when) and fact tables (what happened), joined on
-- surrogate ids. team_id and player_id come from src/transform/id_mapping.py and are stable
-- across reloads; the CHN ids are kept as attributes for tracing back to the source.
--
-- Load order: seasons, conferences, teams, team_aliases, team_seasons, players,
-- player_seasons, player_id_merges, games, then the fact tables.
-- See docs/schema.md for the diagram and how ids are assigned.

CREATE SCHEMA IF NOT EXISTS hockey;
SET search_path TO hockey;

-- ----------------------------------------------------------------------------
-- Dimensions
-- ----------------------------------------------------------------------------

CREATE TABLE seasons (
    season      TEXT PRIMARY KEY CHECK (season ~ '^\d{4}-\d{2}$'),   -- '2025-26'
    start_year  SMALLINT NOT NULL UNIQUE
);

CREATE TABLE conferences (
    conference_id  SMALLSERIAL PRIMARY KEY,
    name           TEXT NOT NULL UNIQUE                           -- 'Hockey East'
);

CREATE TABLE teams (
    team_id      INTEGER PRIMARY KEY,
    chn_team_id  INTEGER UNIQUE,              -- NULL for non-D1 opponents
    name         TEXT NOT NULL,               -- most recent name ('RPI')
    is_d1        BOOLEAN NOT NULL
);

-- Every name a team has appeared under; the loader maps box score names through this.
CREATE TABLE team_aliases (
    alias    TEXT PRIMARY KEY,
    team_id  INTEGER NOT NULL REFERENCES teams
);

-- Conference membership changes (e.g. teams moving to the NCHC), so it is per season.
CREATE TABLE team_seasons (
    team_id        INTEGER NOT NULL REFERENCES teams,
    season         TEXT NOT NULL REFERENCES seasons,
    conference_id  SMALLINT REFERENCES conferences,   -- NULL for non-D1
    PRIMARY KEY (team_id, season)
);

CREATE TABLE players (
    player_id      INTEGER PRIMARY KEY,
    chn_player_id  INTEGER UNIQUE,             -- known only for players who scored a goal
    name           TEXT NOT NULL,              -- most recent spelling
    position       CHAR(1) CHECK (position IN ('F', 'D', 'G'))
);

-- A player's season with one team: the roster. `name` is the spelling used that season.
CREATE TABLE player_seasons (
    player_id  INTEGER NOT NULL REFERENCES players,
    season     TEXT NOT NULL REFERENCES seasons,
    team_id    INTEGER NOT NULL REFERENCES teams,
    name       TEXT NOT NULL,
    position   CHAR(1) CHECK (position IN ('F', 'D', 'G')),
    games      SMALLINT NOT NULL DEFAULT 0,
    link       TEXT NOT NULL
               CHECK (link IN ('chn_id', 'team_and_name', 'name_transfer',
                               'single_season', 'ambiguous')),
    PRIMARY KEY (player_id, season, team_id)
);

-- Ids retired when new data showed two ids were one player. Lets the API redirect old ids.
CREATE TABLE player_id_merges (
    old_player_id  INTEGER PRIMARY KEY,
    new_player_id  INTEGER NOT NULL REFERENCES players,
    merged_on      DATE NOT NULL
);

-- ----------------------------------------------------------------------------
-- Games
-- ----------------------------------------------------------------------------

CREATE TABLE games (
    game_id          TEXT PRIMARY KEY,          -- CHN-derived: '<date>_<away chn id>_<home chn id>'
    season           TEXT NOT NULL REFERENCES seasons,
    game_date        DATE NOT NULL,
    home_team_id     INTEGER REFERENCES teams,  -- NULL when the opponent is 'TBD'
    away_team_id     INTEGER REFERENCES teams,
    home_goals       SMALLINT,                  -- NULL until played
    away_goals       SMALLINT,
    is_played        BOOLEAN NOT NULL,
    is_neutral       BOOLEAN NOT NULL,
    is_conference    BOOLEAN NOT NULL,
    ot_periods       SMALLINT NOT NULL DEFAULT 0,
    shootout_winner_team_id INTEGER REFERENCES teams,
    shootout_score   TEXT,                      -- '3-2'
    game_type        TEXT,                      -- 'Hockey East Game', 'Non-Conference Game', ...
    event            TEXT,                      -- tournament / named event
    game_note        TEXT,
    venue            TEXT,
    attendance       INTEGER,
    referees         TEXT[],
    asst_referees    TEXT[],
    box_score_url    TEXT,
    source           TEXT NOT NULL DEFAULT 'college_hockey_news',
    CHECK (home_team_id IS DISTINCT FROM away_team_id)
);
CREATE INDEX games_season_idx ON games (season);
CREATE INDEX games_home_idx   ON games (home_team_id, game_date);
CREATE INDEX games_away_idx   ON games (away_team_id, game_date);

-- ----------------------------------------------------------------------------
-- Facts (one row per team/player per game, or per event)
-- ----------------------------------------------------------------------------

CREATE TABLE team_game_stats (
    game_id            TEXT NOT NULL REFERENCES games,
    team_id            INTEGER NOT NULL REFERENCES teams,
    opponent_team_id   INTEGER NOT NULL REFERENCES teams,
    is_home            BOOLEAN NOT NULL,
    goals              SMALLINT NOT NULL,
    goals_p1           SMALLINT,
    goals_p2           SMALLINT,
    goals_p3           SMALLINT,
    goals_ot           SMALLINT,
    goals_against      SMALLINT NOT NULL,
    shots              SMALLINT NOT NULL,
    shots_p1           SMALLINT,
    shots_p2           SMALLINT,
    shots_p3           SMALLINT,
    shots_ot           SMALLINT,
    shots_against      SMALLINT NOT NULL,
    pp_goals           SMALLINT NOT NULL,
    pp_opportunities   SMALLINT NOT NULL,
    sh_goals           SMALLINT NOT NULL,
    en_goals           SMALLINT NOT NULL,
    pp_goals_against   SMALLINT NOT NULL,
    times_shorthanded  SMALLINT NOT NULL,
    penalties          SMALLINT NOT NULL,
    pim                SMALLINT NOT NULL,
    faceoffs_won       SMALLINT NOT NULL,
    faceoffs_lost      SMALLINT NOT NULL,
    xg                 NUMERIC(4, 1),            -- CHN metrics; not every game has them
    xg_against         NUMERIC(4, 1),
    empty_net_seconds  INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (game_id, team_id)
);
CREATE INDEX team_game_stats_team_idx ON team_game_stats (team_id);

CREATE TABLE skater_game_stats (
    game_id        TEXT NOT NULL REFERENCES games,
    player_id      INTEGER NOT NULL REFERENCES players,
    team_id        INTEGER NOT NULL REFERENCES teams,
    position       CHAR(1) NOT NULL CHECK (position IN ('F', 'D')),
    goals          SMALLINT NOT NULL,
    assists        SMALLINT NOT NULL,
    points         SMALLINT NOT NULL,
    plus_minus     SMALLINT NOT NULL,
    shots          SMALLINT,
    toi_seconds    INTEGER,                  -- not published for every game
    pim            SMALLINT NOT NULL,
    faceoffs_won   SMALLINT,
    faceoffs_lost  SMALLINT,
    PRIMARY KEY (game_id, player_id)
);
CREATE INDEX skater_game_stats_player_idx ON skater_game_stats (player_id);
CREATE INDEX skater_game_stats_team_idx   ON skater_game_stats (team_id);

CREATE TABLE goalie_game_stats (
    game_id        TEXT NOT NULL REFERENCES games,
    player_id      INTEGER NOT NULL REFERENCES players,
    team_id        INTEGER NOT NULL REFERENCES teams,
    is_starter     BOOLEAN NOT NULL,
    saves          SMALLINT NOT NULL,
    goals_against  SMALLINT NOT NULL,
    shots_against  SMALLINT NOT NULL,
    toi_seconds    INTEGER NOT NULL,
    PRIMARY KEY (game_id, player_id)
);
CREATE INDEX goalie_game_stats_player_idx ON goalie_game_stats (player_id);

CREATE TABLE goals (
    game_id             TEXT NOT NULL REFERENCES games,
    goal_number         SMALLINT NOT NULL,         -- 1.. in game order
    team_id             INTEGER NOT NULL REFERENCES teams,
    period              SMALLINT NOT NULL CHECK (period BETWEEN 1 AND 4),   -- 4 = overtime
    period_seconds      SMALLINT NOT NULL CHECK (period_seconds BETWEEN 0 AND 1200),
    strength            TEXT NOT NULL,             -- as printed: 'EV', 'PP', 'SH,EN', '5x3'
    is_pp               BOOLEAN NOT NULL,
    is_sh               BOOLEAN NOT NULL,
    is_en               BOOLEAN NOT NULL,
    is_extra_attacker   BOOLEAN NOT NULL,
    is_penalty_shot     BOOLEAN NOT NULL,
    scorer_id           INTEGER REFERENCES players,  -- NULL: no scorer credited
    assist1_id          INTEGER REFERENCES players,
    assist2_id          INTEGER REFERENCES players,
    scorer_season_goal  SMALLINT,
    PRIMARY KEY (game_id, goal_number)
);
CREATE INDEX goals_scorer_idx  ON goals (scorer_id);
CREATE INDEX goals_assist1_idx ON goals (assist1_id);
CREATE INDEX goals_assist2_idx ON goals (assist2_id);

CREATE TABLE penalties (
    game_id         TEXT NOT NULL REFERENCES games,
    penalty_number  SMALLINT NOT NULL,             -- 1.. in game order
    team_id         INTEGER NOT NULL REFERENCES teams,
    player_id       INTEGER REFERENCES players,    -- NULL for a bench penalty
    is_bench        BOOLEAN NOT NULL,
    period          SMALLINT NOT NULL CHECK (period BETWEEN 1 AND 4),
    period_seconds  SMALLINT NOT NULL CHECK (period_seconds BETWEEN 0 AND 1200),
    minutes         SMALLINT NOT NULL,
    infraction      TEXT,
    PRIMARY KEY (game_id, penalty_number),
    CHECK (is_bench = (player_id IS NULL))
);
CREATE INDEX penalties_player_idx ON penalties (player_id);

-- ----------------------------------------------------------------------------
-- Views: the season totals most queries (and the API) want
-- ----------------------------------------------------------------------------

CREATE VIEW skater_season_totals AS
SELECT g.season, s.player_id, s.team_id,
       COUNT(*)            AS games,
       SUM(s.goals)        AS goals,
       SUM(s.assists)      AS assists,
       SUM(s.points)       AS points,
       SUM(s.plus_minus)   AS plus_minus,
       SUM(s.shots)        AS shots,
       SUM(s.pim)          AS pim,
       SUM(s.faceoffs_won) AS faceoffs_won,
       SUM(s.faceoffs_lost) AS faceoffs_lost
FROM skater_game_stats s JOIN games g USING (game_id)
GROUP BY g.season, s.player_id, s.team_id;

CREATE VIEW goalie_season_totals AS
SELECT g.season, s.player_id, s.team_id,
       COUNT(*)                AS games,
       SUM(s.is_starter::int)  AS starts,
       SUM(s.saves)            AS saves,
       SUM(s.shots_against)    AS shots_against,
       SUM(s.goals_against)    AS goals_against,
       SUM(s.toi_seconds)      AS toi_seconds,
       ROUND(SUM(s.saves)::numeric / NULLIF(SUM(s.shots_against), 0), 3) AS save_pct,
       ROUND(SUM(s.goals_against) * 3600.0 / NULLIF(SUM(s.toi_seconds), 0), 2) AS gaa
FROM goalie_game_stats s JOIN games g USING (game_id)
GROUP BY g.season, s.player_id, s.team_id;

CREATE VIEW team_season_totals AS
SELECT g.season, t.team_id,
       COUNT(*)                                            AS games,
       SUM((t.goals > t.goals_against)::int)               AS wins,
       SUM((t.goals < t.goals_against)::int)               AS losses,
       SUM((t.goals = t.goals_against)::int)               AS ties,   -- incl. shootout games
       SUM(t.goals)                                        AS goals_for,
       SUM(t.goals_against)                                AS goals_against,
       SUM(t.shots)                                        AS shots_for,
       SUM(t.shots_against)                                AS shots_against,
       ROUND(SUM(t.pp_goals)::numeric / NULLIF(SUM(t.pp_opportunities), 0), 3) AS pp_pct,
       ROUND(1 - SUM(t.pp_goals_against)::numeric / NULLIF(SUM(t.times_shorthanded), 0), 3)
                                                           AS pk_pct,
       ROUND(SUM(t.faceoffs_won)::numeric
             / NULLIF(SUM(t.faceoffs_won + t.faceoffs_lost), 0), 3) AS faceoff_pct
FROM team_game_stats t JOIN games g USING (game_id)
GROUP BY g.season, t.team_id;
