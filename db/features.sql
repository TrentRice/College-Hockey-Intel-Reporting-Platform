-- Feature base tables: one row per team, skater or goalie per played game, in the order
-- they happened. These are views over the `hockey` tables, so they're always current. The
-- loader recreates them after every load (dropping `hockey` drops these too).
--
-- "Last N games" and season-to-date numbers are computed from these rows on request, by
-- src/features/form.py, using only games before a given date (no peeking ahead).

DROP SCHEMA IF EXISTS features CASCADE;
CREATE SCHEMA features;

-- One row per team per played game, both sides of the score next to each other
CREATE VIEW features.team_games AS
SELECT g.season, g.game_id, g.game_date, t.team_id, t.opponent_team_id,
       t.is_home, g.is_neutral, g.is_conference,
       t.goals AS goals_for, t.goals_against,
       CASE WHEN t.goals > t.goals_against THEN 'W'
            WHEN t.goals < t.goals_against THEN 'L' ELSE 'T' END AS result,
       g.ot_periods,
       CASE WHEN g.shootout_winner_team_id IS NULL THEN NULL
            ELSE g.shootout_winner_team_id = t.team_id END      AS shootout_won,
       t.shots AS shots_for, t.shots_against,
       t.pp_goals, t.pp_opportunities, t.pp_goals_against, t.times_shorthanded,
       t.sh_goals, t.en_goals, t.penalties, t.pim,
       t.faceoffs_won, t.faceoffs_lost,
       t.xg AS xg_for, t.xg_against,
       ROW_NUMBER() OVER w                                       AS game_number,
       g.game_date - LAG(g.game_date) OVER w                     AS rest_days  -- NULL for game 1
FROM hockey.team_game_stats t
JOIN hockey.games g USING (game_id)
WHERE g.is_played
WINDOW w AS (PARTITION BY t.team_id, g.season ORDER BY g.game_date, g.game_id);

-- Power-play goals and assists per player per game, from the scoring summary
CREATE VIEW features.player_pp_points AS
SELECT game_id, player_id, SUM(g)::int AS pp_goals, SUM(a)::int AS pp_assists
FROM (
    SELECT game_id, scorer_id AS player_id, 1 AS g, 0 AS a FROM hockey.goals WHERE is_pp AND scorer_id IS NOT NULL
    UNION ALL
    SELECT game_id, assist1_id, 0, 1 FROM hockey.goals WHERE is_pp AND assist1_id IS NOT NULL
    UNION ALL
    SELECT game_id, assist2_id, 0, 1 FROM hockey.goals WHERE is_pp AND assist2_id IS NOT NULL
) x
GROUP BY game_id, player_id;

CREATE VIEW features.skater_games AS
SELECT g.season, s.game_id, g.game_date, s.team_id, s.player_id, s.position,
       s.goals, s.assists, s.points,
       COALESCE(pp.pp_goals, 0) AS pp_goals, COALESCE(pp.pp_assists, 0) AS pp_assists,
       s.shots, s.plus_minus, s.pim, s.toi_seconds, s.faceoffs_won, s.faceoffs_lost
FROM hockey.skater_game_stats s
JOIN hockey.games g USING (game_id)
LEFT JOIN features.player_pp_points pp USING (game_id, player_id);

CREATE VIEW features.goalie_games AS
SELECT g.season, s.game_id, g.game_date, s.team_id, s.player_id,
       s.is_starter, s.saves, s.shots_against, s.goals_against, s.toi_seconds
FROM hockey.goalie_game_stats s
JOIN hockey.games g USING (game_id);
