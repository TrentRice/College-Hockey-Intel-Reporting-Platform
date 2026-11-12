"""Response models: the shape of every response, which also documents it at /docs."""

from __future__ import annotations

import datetime as dt
from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, Field

SEASON_PATTERN = r"^\d{4}-\d{2}$"


class RefreshRun(BaseModel):
    started_at: dt.datetime
    finished_at: dt.datetime | None
    status: Literal["running", "success", "failed", "blocked"] = Field(
        description="blocked = validation stopped the load; the data is from the last success"
    )
    trigger: Literal["manual", "scheduled"]
    failed_step: str | None
    new_games: int | None = Field(description="Games that became final in this run")


class Health(BaseModel):
    status: Literal["ok"]
    database: Literal["ok"]
    data_as_of: dt.datetime | None = Field(description="When the last successful refresh finished")
    last_refresh: RefreshRun | None = Field(
        description="The most recent refresh, whatever its result"
    )


class Season(BaseModel):
    season: str = Field(examples=["2026-27"])
    start_year: int
    games: int = Field(description="Scheduled games")
    played: int = Field(description="Games with a final score")


class TeamRef(BaseModel):
    team_id: int
    name: str


class TeamSummary(TeamRef):
    is_d1: bool
    chn_team_id: int | None
    conference: str | None = Field(description="Conference in the requested season")


class TeamSeason(BaseModel):
    season: str
    conference: str | None


class TeamDetail(TeamRef):
    is_d1: bool
    chn_team_id: int | None
    aliases: list[str] = Field(description="Every name the team has appeared under")
    seasons: list[TeamSeason]


class TeamGame(BaseModel):
    game_id: str
    date: dt.date
    season: str
    opponent: TeamRef | None = Field(description="None when the opponent is still TBD")
    is_home: bool
    is_neutral: bool
    is_conference: bool
    is_played: bool
    goals_for: int | None
    goals_against: int | None
    result: Literal["W", "L", "T"] | None = Field(
        description="T includes shootout games; None if not played"
    )
    ot_periods: int
    shootout_won: bool | None = Field(description="None if there was no shootout")
    shots_for: int | None
    shots_against: int | None
    game_type: str | None
    event: str | None
    venue: str | None


class TeamSeasonStats(BaseModel):
    team: TeamRef
    season: str
    games: int
    wins: int
    losses: int
    ties: int = Field(description="Includes games decided by shootout")
    record: str = Field(examples=["17-17-2"])
    goals_for: int
    goals_against: int
    goal_diff: int
    shots_for: int
    shots_against: int
    pp_pct: float | None = Field(description="Power-play goals / opportunities")
    pk_pct: float | None = Field(description="1 - PP goals against / times shorthanded")
    faceoff_pct: float | None


class SkaterLine(BaseModel):
    player_id: int
    name: str
    position: Literal["F", "D"] | None
    games: int
    goals: int
    assists: int
    points: int
    plus_minus: int
    shots: int | None
    pim: int
    faceoffs_won: int | None
    faceoffs_lost: int | None


class GoalieLine(BaseModel):
    player_id: int
    name: str
    games: int
    starts: int
    saves: int
    shots_against: int
    goals_against: int
    save_pct: float | None
    gaa: float | None = Field(description="Goals against per 60 minutes")
    toi_seconds: int


class Roster(BaseModel):
    team: TeamRef
    season: str
    skaters: list[SkaterLine]
    goalies: list[GoalieLine]


# ----------------------------------------------------------------------------
# Paging
# ----------------------------------------------------------------------------

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int = Field(description="Rows matching the filters, across all pages")
    limit: int
    offset: int


class PlayerRef(BaseModel):
    player_id: int
    name: str


# ----------------------------------------------------------------------------
# Games
# ----------------------------------------------------------------------------


class GameSummary(BaseModel):
    game_id: str
    season: str
    date: dt.date
    home: TeamRef | None = Field(description="None when still TBD")
    away: TeamRef | None
    home_goals: int | None
    away_goals: int | None
    is_played: bool
    is_neutral: bool
    is_conference: bool
    ot_periods: int
    shootout_winner: TeamRef | None
    game_type: str | None
    event: str | None
    venue: str | None


class GameInfo(GameSummary):
    shootout_score: str | None
    game_note: str | None
    attendance: int | None
    referees: list[str] | None
    asst_referees: list[str] | None
    box_score_url: str | None


class TeamGameStats(BaseModel):
    goals: int
    goals_by_period: list[int | None] = Field(description="1st, 2nd, 3rd, OT")
    shots: int
    shots_by_period: list[int | None]
    pp_goals: int
    pp_opportunities: int
    sh_goals: int
    en_goals: int
    penalties: int
    pim: int
    faceoffs_won: int
    faceoffs_lost: int
    xg: float | None
    empty_net_seconds: int


class SkaterGameLine(BaseModel):
    player_id: int
    name: str
    position: Literal["F", "D"]
    goals: int
    assists: int
    points: int
    plus_minus: int
    shots: int | None
    pim: int
    toi_seconds: int | None
    faceoffs_won: int | None
    faceoffs_lost: int | None


class GoalieGameLine(BaseModel):
    player_id: int
    name: str
    is_starter: bool
    saves: int
    shots_against: int
    goals_against: int
    toi_seconds: int


class TeamBox(BaseModel):
    team: TeamRef
    is_home: bool
    stats: TeamGameStats | None = Field(description="None until the game is played")
    skaters: list[SkaterGameLine] = Field(description="Empty for non-D1 teams")
    goalies: list[GoalieGameLine]


class Goal(BaseModel):
    goal_number: int
    period: int = Field(description="4 = overtime")
    time: str = Field(description="Elapsed in the period, m:ss", examples=["14:28"])
    team: TeamRef
    strength: str = Field(examples=["EV", "PP", "SH,EN"])
    is_pp: bool
    is_sh: bool
    is_en: bool
    is_extra_attacker: bool
    is_penalty_shot: bool
    scorer: PlayerRef | None = Field(description="None when CHN credits no scorer")
    assists: list[PlayerRef]


class Penalty(BaseModel):
    penalty_number: int
    period: int
    time: str
    team: TeamRef
    player: PlayerRef | None = Field(description="None for a bench penalty")
    is_bench: bool
    minutes: int
    infraction: str | None


class BoxScore(BaseModel):
    game: GameInfo
    teams: list[TeamBox] = Field(description="Away team first, then home")
    goals: list[Goal]
    penalties: list[Penalty]


# ----------------------------------------------------------------------------
# Players
# ----------------------------------------------------------------------------


class PlayerSummary(PlayerRef):
    position: Literal["F", "D", "G"] | None
    chn_player_id: int | None
    team: TeamRef = Field(description="Most recent team")
    first_season: str
    last_season: str


class SkaterTotals(BaseModel):
    games: int
    goals: int
    assists: int
    points: int
    plus_minus: int
    shots: int | None
    pim: int
    faceoffs_won: int | None
    faceoffs_lost: int | None


class GoalieTotals(BaseModel):
    games: int
    starts: int
    saves: int
    shots_against: int
    goals_against: int
    save_pct: float | None
    gaa: float | None
    toi_seconds: int


class PlayerSeason(BaseModel):
    season: str
    team: TeamRef
    position: Literal["F", "D", "G"] | None
    name: str = Field(description="Spelling used that season")
    link: str = Field(description="How this season was tied to the player (see docs/schema.md)")
    skater: SkaterTotals | None
    goalie: GoalieTotals | None


class PlayerDetail(PlayerRef):
    position: Literal["F", "D", "G"] | None
    chn_player_id: int | None
    names: list[str] = Field(description="Every spelling the player has appeared under")
    seasons: list[PlayerSeason]


class SkaterGameStats(BaseModel):
    goals: int
    assists: int
    points: int
    plus_minus: int
    shots: int | None
    pim: int
    toi_seconds: int | None


class GoalieGameStats(BaseModel):
    is_starter: bool
    saves: int
    shots_against: int
    goals_against: int
    toi_seconds: int


class PlayerGame(BaseModel):
    game_id: str
    date: dt.date
    season: str
    team: TeamRef
    opponent: TeamRef | None
    is_home: bool
    result: Literal["W", "L", "T"] | None = Field(description="The player's team's result")
    skater: SkaterGameStats | None
    goalie: GoalieGameStats | None


# ----------------------------------------------------------------------------
# Leaders
# ----------------------------------------------------------------------------


class SkaterLeader(SkaterLine):
    rank: int = Field(description="Ties share a rank")
    team: TeamRef
    points_per_game: float


class GoalieLeader(GoalieLine):
    rank: int
    team: TeamRef
