-- Made-up data for API tests (no CHN data). Loaded into a separate hockey_test database.
SET search_path TO hockey;

INSERT INTO seasons VALUES ('2025-26', 2025), ('2026-27', 2026);
INSERT INTO conferences VALUES ('Hockey East');

INSERT INTO teams VALUES
    (1, 101, 'Home U',  TRUE),
    (2, 102, 'Rival College', TRUE),
    (3, NULL, 'Small State', FALSE);
INSERT INTO team_aliases VALUES ('Home U', 1), ('Home University', 1), ('Rival College', 2), ('Small State', 3);
INSERT INTO team_seasons VALUES
    (1, '2025-26', 'Hockey East'), (1, '2026-27', 'Hockey East'),
    (2, '2026-27', 'Hockey East'), (3, '2026-27', NULL);

INSERT INTO players VALUES
    (10, 9001, 'Ava Forward', 'F'), (11, NULL, 'Ben Defense', 'D'), (12, NULL, 'Cal Goalie', 'G'),
    (13, NULL, 'Dee Backup', 'G'), (20, 9002, 'Éli Rival', 'F'), (21, NULL, 'Fay Keeper', 'G');
INSERT INTO player_seasons VALUES
    (10, '2025-26', 1, 'Ava Forward', 'F', 1, 'chn_id'),
    (10, '2026-27', 1, 'Ava Forward', 'F', 2, 'chn_id'),
    (11, '2026-27', 1, 'Ben Defense', 'D', 2, 'single_season'),
    (12, '2026-27', 1, 'Cal Goalie', 'G', 2, 'single_season'),
    (13, '2026-27', 1, 'Dee Backup', 'G', 1, 'single_season'),
    (20, '2026-27', 2, 'Éli Rival', 'F', 2, 'chn_id'),
    (21, '2026-27', 2, 'Fay Keeper', 'G', 2, 'single_season');

-- g1: Home U 4-2 Rival (home win). g2: Home U at Rival, 3-3, Rival wins the shootout.
-- g3: Home U vs Small State, not played yet. g4: Home U vs TBD. g5: last season.
INSERT INTO games (game_id, season, game_date, home_team_id, away_team_id, home_goals, away_goals,
                   is_played, is_neutral, is_conference, ot_periods, shootout_winner_team_id,
                   shootout_score, game_type, venue) VALUES
    ('g1', '2026-27', '2026-10-10', 1, 2, 4, 2, TRUE, FALSE, TRUE, 0, NULL, NULL, 'Hockey East Game', 'Home Rink'),
    ('g2', '2026-27', '2026-10-11', 2, 1, 3, 3, TRUE, FALSE, TRUE, 1, 2, '2-1', 'Hockey East Game', 'Rival Rink'),
    ('g3', '2026-27', '2026-12-01', 1, 3, NULL, NULL, FALSE, FALSE, FALSE, 0, NULL, NULL, 'Non-Conference Game', 'Home Rink'),
    ('g4', '2026-27', '2027-01-03', NULL, 1, NULL, NULL, FALSE, TRUE, FALSE, 0, NULL, NULL, 'Non-Conference Game', NULL),
    ('g5', '2025-26', '2026-02-01', 1, 2, 1, 5, TRUE, FALSE, TRUE, 0, NULL, NULL, 'Hockey East Game', 'Home Rink');

INSERT INTO team_game_stats (game_id, team_id, opponent_team_id, is_home, goals, goals_against,
                             shots, shots_against, pp_goals, pp_opportunities, sh_goals, en_goals,
                             pp_goals_against, times_shorthanded, penalties, pim,
                             faceoffs_won, faceoffs_lost, shots_p1, shots_p2, shots_p3, shots_ot) VALUES
    ('g1', 1, 2, TRUE,  4, 2, 35, 25, 1, 4, 0, 1, 1, 3, 3, 6, 30, 20, 12, 11, 12, NULL),
    ('g1', 2, 1, FALSE, 2, 4, 25, 35, 1, 3, 0, 0, 1, 4, 4, 8, 20, 30, 8, 9, 8, NULL),
    ('g2', 2, 1, TRUE,  3, 3, 28, 30, 0, 2, 0, 0, 1, 2, 2, 4, 25, 25, 9, 9, 9, 1),
    ('g2', 1, 2, FALSE, 3, 3, 30, 28, 1, 2, 0, 0, 0, 2, 2, 4, 25, 25, 10, 10, 9, 1),
    ('g5', 1, 2, TRUE,  1, 5, 20, 40, 0, 1, 0, 0, 2, 5, 5, 10, 15, 35, 7, 7, 6, NULL),
    ('g5', 2, 1, FALSE, 5, 1, 40, 20, 2, 5, 0, 0, 0, 1, 1, 2, 35, 15, 13, 14, 13, NULL);

INSERT INTO skater_game_stats (game_id, player_id, team_id, position, goals, assists, points,
                               plus_minus, shots, pim) VALUES
    ('g1', 10, 1, 'F', 2, 1, 3, 2, 6, 0),
    ('g1', 11, 1, 'D', 0, 2, 2, 1, 2, 2),
    ('g2', 10, 1, 'F', 1, 0, 1, 0, 4, 0),
    ('g2', 11, 1, 'D', 1, 1, 2, 1, 3, 0),
    ('g1', 20, 2, 'F', 1, 0, 1, -1, 3, 0),
    ('g2', 20, 2, 'F', 2, 0, 2, 1, 5, 0),
    ('g5', 10, 1, 'F', 1, 0, 1, -2, 3, 2);

INSERT INTO goalie_game_stats VALUES
    ('g1', 12, 1, TRUE, 23, 2, 25, 3600),
    ('g2', 12, 1, TRUE, 20, 2, 22, 2400),
    ('g2', 13, 1, FALSE, 5, 1, 6, 1500),
    ('g1', 21, 2, TRUE, 31, 4, 35, 3600),
    ('g2', 21, 2, TRUE, 27, 3, 30, 3900);

-- Every spelling; Ava also appeared as 'Avery Forward'
INSERT INTO player_names VALUES
    (10, '2025-26', 1, 'Ava Forward'), (10, '2026-27', 1, 'Ava Forward'),
    (10, '2026-27', 1, 'Avery Forward'), (11, '2026-27', 1, 'Ben Defense'),
    (12, '2026-27', 1, 'Cal Goalie'), (13, '2026-27', 1, 'Dee Backup'),
    (20, '2026-27', 2, 'Éli Rival'), (21, '2026-27', 2, 'Fay Keeper');

-- Id 99 was retired when it turned out to be Ava
INSERT INTO player_id_merges VALUES (99, 10, '2026-11-01');

-- g1 scoring and penalties
INSERT INTO goals VALUES
    ('g1', 1, 1, 1, 300, 'EV', FALSE, FALSE, FALSE, FALSE, FALSE, 10, 11, NULL, 1),
    ('g1', 2, 2, 1, 600, 'EV', FALSE, FALSE, FALSE, FALSE, FALSE, 20, NULL, NULL, 1),
    ('g1', 3, 1, 2, 100, 'PP', TRUE, FALSE, FALSE, FALSE, FALSE, 10, 11, 12, 2),
    ('g1', 4, 1, 3, 50, 'EV', FALSE, FALSE, FALSE, FALSE, FALSE, NULL, NULL, NULL, NULL),
    ('g1', 5, 2, 3, 900, 'PP', TRUE, FALSE, FALSE, FALSE, FALSE, NULL, NULL, NULL, NULL),
    ('g1', 6, 1, 3, 1150, 'EN', FALSE, FALSE, TRUE, FALSE, FALSE, NULL, NULL, NULL, NULL);
INSERT INTO penalties VALUES
    ('g1', 1, 2, 20, FALSE, 1, 120, 2, 'Hooking'),
    ('g1', 2, 1, NULL, TRUE, 2, 300, 2, 'Too Many Men');
