"""
CHIRP scouting dashboard (Streamlit). Reads everything through the CHIRP API.

  make dashboard        -> http://127.0.0.1:8501   (or `make up` for the Docker version)

Pick a team (by default your team's next opponent) and how many recent games to look at.
Every "last N" number sits next to the season so far. The Win probability tab shows your
team's chance against the scouted team (win model v1, via the API).
"""

from __future__ import annotations

import datetime as dt

import altair as alt
import pandas as pd
import streamlit as st

from src.dashboard import client
from src.dashboard.logic import (
    DELTA_FORMAT,
    HEADLINE,
    TEAM_STATS,
    TIE,
    comparison_rows,
    default_last,
    delta_value,
    describe_game,
    difference_tones,
    fmt,
    fmt_delta,
    game_label,
    is_zero,
    meetings,
    next_game,
    side_by_side,
)

HOME_TEAM_NAME = "Boston University"
CACHE_SECONDS = 300

# Chart colors (reference palette; light and dark steps chosen separately)
PALETTE = {
    "light": {
        "pos": "#2a78d6",
        "neg": "#e34948",
        "line": "#2a78d6",
        "xg": "#eb6834",
        "expected": "#52514e",
        "ref": "#898781",
        "band": "#e1e0d9",
        "up": "#006300",
        "down": "#d03b3b",
        "tie": "#a86f00",
    },
    "dark": {
        "pos": "#3987e5",
        "neg": "#e66767",
        "line": "#3987e5",
        "xg": "#d95926",
        "expected": "#c3c2b7",
        "ref": "#898781",
        "band": "#2c2c2a",
        "up": "#0ca30c",
        "down": "#e66767",
        "tie": "#fab219",
    },
}

st.set_page_config(page_title="CHIRP Scouting", page_icon="🏒", layout="wide")


# ----------------------------------------------------------------------------
# Data (cached for a few minutes; the nightly refresh is the only thing that changes it)
# ----------------------------------------------------------------------------


@st.cache_data(ttl=CACHE_SECONDS, show_spinner=False)
def cached(fn_name: str, *args):
    return getattr(client, fn_name)(*args)


def palette() -> dict:
    theme = getattr(getattr(st.context, "theme", None), "type", None)
    return PALETTE["dark" if theme == "dark" else "light"]


def color_text(color: str) -> str:
    return f"color: {color}; font-weight: 600"


def style_differences(df: pd.DataFrame, tones: list[str]) -> object:
    """Difference column (numbers, so it sorts by value): green when the last N is better
    than the season, red when worse, each row formatted in its own unit."""
    if "Difference" not in df:
        return df
    colors = palette()
    css = {"better": color_text(colors["up"]), "worse": color_text(colors["down"]), "": ""}
    styler = df.style.apply(lambda col: [css[t] for t in tones], subset=["Difference"])
    for kind, pattern in DELTA_FORMAT.items():
        rows = [i for i, s in enumerate(TEAM_STATS) if s.kind == kind]
        styler = styler.format(pattern, subset=pd.IndexSlice[rows, ["Difference"]], na_rep="")
    text_rows = [i for i, s in enumerate(TEAM_STATS) if s.kind == "text"]
    return styler.format(lambda v: "", subset=pd.IndexSlice[text_rows, ["Difference"]])


def style_better(df: pd.DataFrame, mine: str, theirs: str) -> object:
    """Better column: green = your team, red = the opponent, yellow = tie."""
    colors = palette()
    css = {mine: colors["up"], theirs: colors["down"], TIE: colors["tie"]}
    return df.style.map(lambda v: color_text(css[v]) if v in css else "", subset=["Better"])


def style_signed(df: pd.DataFrame, column: str, kind: str) -> object:
    """A numeric +/- column where up is better: green up, red down, formatted in its unit
    (the values stay numbers, so sorting goes by value)."""
    if column not in df:
        return df
    colors = palette()

    def cell(v) -> str:
        if v is None or pd.isna(v) or v == 0:
            return ""
        return color_text(colors["up"] if v > 0 else colors["down"])

    return df.style.map(cell, subset=[column]).format(
        DELTA_FORMAT[kind], subset=[column], na_rep=""
    )


def stop_with(message: str) -> None:
    st.error(message)
    st.stop()


try:
    health = cached("health")
    seasons = cached("seasons")
except client.ApiError as e:
    stop_with(str(e))

# ----------------------------------------------------------------------------
# Sidebar: who and how many games
# ----------------------------------------------------------------------------

season_names = [s["season"] for s in seasons]
with st.sidebar:
    st.header("🏒 CHIRP Scouting")
    season = st.selectbox("Season", season_names, index=len(season_names) - 1)
    teams = cached("teams", season)
    by_name = {t["name"]: t for t in teams}
    names = sorted(by_name)
    home_name = st.selectbox(
        "Your team", names, index=names.index(HOME_TEAM_NAME) if HOME_TEAM_NAME in names else 0
    )
    home = by_name[home_name]

    home_schedule = cached("schedule", home["team_id"], season)
    upcoming = next_game(home_schedule, dt.date.today())

    mode = st.radio(
        "Scout",
        ["Next opponent", "Any team"],
        horizontal=True,
        disabled=upcoming is None or upcoming["opponent"] is None,
        index=0 if upcoming and upcoming["opponent"] else 1,
    )
    if mode == "Next opponent" and upcoming and upcoming["opponent"]:
        scouted = by_name.get(upcoming["opponent"]["name"]) or upcoming["opponent"]
        st.caption(f"{home_name}'s next game: **{describe_game(upcoming)}**")
        as_of_default = dt.date.fromisoformat(str(upcoming["date"]))
    else:
        others = [n for n in names if n != home_name]
        scouted = by_name[st.selectbox("Team to scout", others)]
        as_of_default = dt.date.today() + dt.timedelta(days=1)

    as_of = st.date_input(
        "Only games before",
        value=as_of_default,
        help="Defaults to the day of the game you're scouting, so nothing after it counts.",
    )

    season_form = cached("team_form", scouted["team_id"], season, None, as_of)
    scout_error = None  # shown in the scouting tabs; the Win probability tab still works
    games_played = season_form["games_played"] if season_form else 0
    if season_form is None:
        scout_error = f"{scouted['name']} hasn't played a game in {season} before {as_of:%b %-d}."
        last = 1
    elif games_played > 1:
        last = st.slider(
            "Last N games",
            min_value=1,
            max_value=games_played,
            value=default_last(games_played),
            help=f"{scouted['name']} has played {games_played} games before this date.",
        )
    else:
        last = 1
        st.caption("Only 1 game played so far.")
    full_season = last >= games_played

    data_as_of = health.get("data_as_of")
    if data_as_of:
        st.caption(
            f"Data refreshed {pd.Timestamp(data_as_of).tz_convert('America/New_York'):%b %-d, %-I:%M %p} ET"
        )
    last_run = health.get("last_refresh")
    if last_run and last_run["status"] in ("failed", "blocked"):
        st.warning(f"Latest refresh {last_run['status']}; the data is from the last good run.")


# ----------------------------------------------------------------------------
# Win probability: any team's next game (win model v1)
# ----------------------------------------------------------------------------

FACTOR_LABELS = {
    "close_shot_share": "Close-game shot share",
    "goal_diff_per_game": "Goal differential / game",
    "home_ice": "Home ice",
}


def probability_bar(team: str, p: float, opponent: str) -> alt.Chart:
    colors = palette()
    df = pd.DataFrame(
        [
            {"team": team, "share": p, "start": 0.0, "label": f"{team} {p:.0%}"},
            {"team": opponent, "share": 1 - p, "start": p, "label": f"{opponent} {1 - p:.0%}"},
        ]
    )
    df["end"] = df["start"] + df["share"]
    df["mid"] = df["start"] + df["share"] / 2
    color = alt.Color(
        "team:N",
        scale=alt.Scale(domain=[team, opponent], range=[colors["pos"], colors["ref"]]),
        legend=None,
    )
    bars = (
        alt.Chart(df)
        .mark_bar(height=34, cornerRadius=4)
        .encode(
            x=alt.X("start:Q", scale=alt.Scale(domain=[0, 1]), axis=None),
            x2="end:Q",
            color=color,
            tooltip=[alt.Tooltip("team:N", title="Team"), alt.Tooltip("share:Q", title="Chance", format=".1%")],
        )
    )
    labels = (
        alt.Chart(df)
        .mark_text(color="white", fontWeight="bold", fontSize=13)
        .encode(x="mid:Q", text="label:N")
    )
    return (bars + labels).properties(height=44)


VENUES = ["Home", "Away", "Neutral site"]


def show_prediction(pred: dict, team: dict, title: str) -> None:
    """One prediction from `team`'s side: the chance, the bar, and what drives it."""
    team_name = team["name"]
    is_home = pred["home"]["team"]["team_id"] == team["team_id"]
    mine, theirs = (pred["home"], pred["away"]) if is_home else (pred["away"], pred["home"])
    opp_name = theirs["team"]["name"]
    p = pred["home_win_probability"] if is_home else pred["away_win_probability"]
    sign = 1 if is_home else -1  # factors are from the home team's side

    st.subheader(title)
    c1, c2 = st.columns(2)
    c1.metric(f"{team_name} win", f"{p:.0%}")
    c2.metric(f"{opp_name} win", f"{1 - p:.0%}")
    st.altair_chart(probability_bar(team_name, p, opp_name), width="stretch")
    if not pred["reliable"]:
        st.warning(pred["note"])

    effects = {k: sign * v * 100 for k, v in pred["factors"].items()}
    biggest = max(effects, key=lambda k: abs(effects[k]))
    lean = "for" if effects[biggest] > 0 else "against"
    st.markdown(
        f"**Biggest factor: {FACTOR_LABELS[biggest].lower()}**, "
        f"{abs(effects[biggest]):.1f} points {lean} {team_name}."
    )

    def pct(v):
        return "–" if v is None else f"{v:.1%}"

    def num(v):
        return "–" if v is None else f"{v:+.2f}"

    where = "neutral site" if not pred["home_ice"] else ("home" if is_home else "away")
    rows = [
        {"Factor": FACTOR_LABELS["close_shot_share"], team_name: pct(mine["close_shot_share"]),
         opp_name: pct(theirs["close_shot_share"]), "Effect on chance": effects["close_shot_share"]},
        {"Factor": FACTOR_LABELS["goal_diff_per_game"], team_name: num(mine["goal_diff_per_game"]),
         opp_name: num(theirs["goal_diff_per_game"]), "Effect on chance": effects["goal_diff_per_game"]},
        {"Factor": FACTOR_LABELS["home_ice"], team_name: where,
         opp_name: {"home": "away", "away": "home"}.get(where, where), "Effect on chance": effects["home_ice"]},
        {"Factor": "Games played", team_name: str(mine["games_played"]),
         opp_name: str(theirs["games_played"]), "Effect on chance": None},
    ]
    st.dataframe(
        style_signed(pd.DataFrame(rows), "Effect on chance", "pct"),
        hide_index=True,
        width="stretch",
        placeholder="",
    )
    st.caption(
        f"Each team's season before {pd.Timestamp(pred['as_of']):%b %-d}, D-I games only. "
        "**Effect on chance**: how many points that factor moves "
        f"{team_name}'s chance, compared with it being even. Close-game shot share counts "
        "shots in periods that started tied or within one goal. Goal differential leaves "
        "out empty-net goals."
    )
    st.caption(
        f"Model {pred['model']}, trained on 2025-26. The chance is for a game that has a "
        "winner: about 7% of college games end tied. On 2026-27 games so far it predicts "
        "better than picking the home team, but treat it as a probability, not a pick."
    )


def render_win_probability() -> None:
    """Your team (sidebar) against the scouted team, like the other tabs.

    Next opponent: their scheduled game, using each team's games before that date.
    Any team: any opponent, scheduled or not, using games before the sidebar date, at a venue
    picked here (it starts at their next scheduled meeting's venue, or home).
    """
    if mode == "Next opponent" and upcoming and upcoming["opponent"]:
        pred = cached("prediction", upcoming["game_id"])
        if not pred or "home_win_probability" not in pred:
            st.info(
                f"No prediction for {home_name}'s next game ({describe_game(upcoming)}): "
                "the model covers games between two D-I teams only."
            )
            return
        show_prediction(pred, home, f"{home_name} {describe_game(upcoming)}")
        return

    if scouted["team_id"] == home["team_id"]:
        st.info("Pick a different team to compare.")
        return
    today = dt.date.today()
    meeting = next(
        (g for g in sorted(home_schedule, key=lambda g: (str(g["date"]), g["game_id"]))
         if not g["is_played"] and g["opponent"]
         and g["opponent"]["team_id"] == scouted["team_id"]
         and dt.date.fromisoformat(str(g["date"])) >= today),
        None,
    )
    default = "Home"
    if meeting:
        default = "Neutral site" if meeting.get("is_neutral") else ("Home" if meeting["is_home"] else "Away")
    venue = st.radio(
        f"Where {home_name} plays", VENUES, index=VENUES.index(default), horizontal=True,
        key="win_venue",
        help="Home ice is worth a few points; a neutral site gives no home edge.",
    )
    home_id, away_id = (scouted["team_id"], home["team_id"]) if venue == "Away" else (home["team_id"], scouted["team_id"])
    pred = cached("matchup", season, home_id, away_id, as_of, venue == "Neutral site")
    if not pred or "home_win_probability" not in pred:
        st.info(f"No prediction for {home_name} vs {scouted['name']}: the model covers D-I teams only.")
        return
    where = {"Home": "at home", "Away": "away", "Neutral site": "at a neutral site"}[venue]
    show_prediction(pred, home, f"{home_name} vs {scouted['name']}, {where}")
    note = f"A matchup, using each team's games before {as_of:%b %-d} (the sidebar date)."
    if meeting:
        note += f" They're scheduled to meet {describe_game(meeting).split(', ')[-1]}."
    st.caption(note)


# ----------------------------------------------------------------------------
# Header and tabs
# ----------------------------------------------------------------------------

st.title(scouted["name"])
header_caption = st.empty()
tab_team, tab_players, tab_h2h, tab_win = st.tabs(
    ["Team", "Players", f"vs {home_name}", "Win probability"]
)
with tab_win:
    render_win_probability()
if scout_error:
    with tab_team:
        st.error(scout_error)
    st.stop()

form = cached("team_form", scouted["team_id"], season, last, as_of)
players = cached("player_form", scouted["team_id"], season, last, as_of)
window = form["window"]
season_totals = form["season_totals"]  # None when the window is the whole season
window_label = "Season" if full_season else f"Last {form['games_used']}"

subtitle = [f"{window['record']} {window_label.lower()}"]
if season_totals:
    subtitle.append(f"{season_totals['record']} season")
if window.get("streak"):
    subtitle.append(f"streak {window['streak']}")
header_caption.caption(" · ".join(subtitle) + f" · {games_played} games before {as_of:%b %-d}")

# ----------------------------------------------------------------------------
# Team
# ----------------------------------------------------------------------------

with tab_team:
    st.caption(
        f"**{window_label}**" + ("" if full_season else ", with the change from the season so far")
    )
    cols = st.columns(len(HEADLINE))
    for col, key in zip(cols, HEADLINE, strict=True):
        stat = next(s for s in TEAM_STATS if s.key == key)
        delta = (
            fmt_delta(window.get(key), season_totals.get(key), stat.kind) if season_totals else None
        )
        unchanged = delta is not None and is_zero(delta)
        col.metric(
            stat.label,
            fmt(window.get(key), stat.kind),
            delta="no change" if unchanged else delta,
            delta_color="off" if unchanged else ("normal" if stat.higher_is_better else "inverse"),
        )

    st.subheader(f"{window_label}{'' if full_season else ' vs season'}")
    if not full_season:
        st.caption(
            "Difference: **green = better** over the last games than the season, **red = worse**."
        )
    st.dataframe(
        style_differences(
            pd.DataFrame(comparison_rows(window, season_totals)).rename(
                columns={"Last N": window_label}
            ),
            difference_tones(window, season_totals) if season_totals else [],
        ),
        hide_index=True,
        placeholder="",  # no difference to show (text stats, players who sat out)
        height=36 * (len(TEAM_STATS) + 1) + 3,  # every row, no inner scrolling
        width="stretch",
    )

    # Season charts, with the window shaded
    all_games = pd.DataFrame(list(reversed(season_form["games"])))  # oldest first
    all_games["game"] = range(1, len(all_games) + 1)
    all_games["date"] = pd.to_datetime(all_games["date"])
    all_games["opponent_name"] = [o["name"] for o in all_games["opponent"]]
    all_games["result_label"] = [game_label(g) for g in season_form["games"][::-1]]
    all_games["goal_diff"] = all_games["goals_for"] - all_games["goals_against"]
    all_games["shot_share"] = all_games["shots_for"] / (
        all_games["shots_for"] + all_games["shots_against"]
    )
    xg_total = all_games["xg_for"] + all_games["xg_against"]
    all_games["xg_share"] = (all_games["xg_for"] / xg_total).where(xg_total > 0)
    all_games["xg_diff"] = (all_games["xg_for"] - all_games["xg_against"]).round(2)
    all_games["in_window"] = all_games["game"] > games_played - form["games_used"]
    all_games["where"] = ["home" if h else "away" for h in all_games["is_home"]]
    colors = palette()

    first_in_window = games_played - form["games_used"] + 0.5
    band = (
        alt.Chart(pd.DataFrame({"x0": [first_in_window], "x1": [games_played + 0.5]}))
        .mark_rect(color=colors["band"], opacity=0.6)
        .encode(x="x0:Q", x2="x1:Q")
    )
    x_axis = alt.X(
        "game:Q",
        title="Game",
        scale=alt.Scale(domain=[0.5, games_played + 0.5], nice=False, zero=False),
        axis=alt.Axis(values=list(range(1, games_played + 1)), grid=False, format="d"),
    )
    tooltip = [
        alt.Tooltip("date:T", title="Date", format="%b %-d"),
        alt.Tooltip("opponent_name:N", title="Opponent"),
        alt.Tooltip("where:N", title="Home/away"),
        alt.Tooltip("result_label:N", title="Result"),
        alt.Tooltip("goal_diff:Q", title="Actual goal diff", format="+d"),
        alt.Tooltip("xg_diff:Q", title="Expected goal diff (xG)", format="+.2f"),
        alt.Tooltip("xg_for:Q", title="xG for", format=".2f"),
        alt.Tooltip("xg_against:Q", title="xG against", format=".2f"),
        alt.Tooltip("shot_share:Q", title="Shot share", format=".1%"),
        alt.Tooltip("xg_share:Q", title="xG share", format=".1%"),
        alt.Tooltip("shots_for:Q", title="Shots for"),
        alt.Tooltip("shots_against:Q", title="Shots against"),
    ]

    # Actual vs expected, both in goals so they share one axis: bars = what happened,
    # line = what the chances said (CHN xG for minus xG against)
    st.markdown("**Actual vs expected goal differential by game**")
    won, lost, expected = "Won by", "Lost by", "Expected (xG for − against)"
    legend_scale = alt.Scale(
        domain=[won, lost, expected], range=[colors["pos"], colors["neg"], colors["expected"]]
    )
    all_games["outcome"] = [won if d >= 0 else lost for d in all_games["goal_diff"]]
    all_games["expected_series"] = expected
    y = alt.Y("goal_diff:Q", title="Goal differential")
    bars = (
        alt.Chart(all_games)
        .mark_bar(size=14, cornerRadiusEnd=4)
        .encode(
            x=x_axis,
            y=y,
            color=alt.Color(
                "outcome:N", scale=legend_scale, legend=alt.Legend(title=None, orient="top")
            ),
            opacity=alt.condition(alt.datum.in_window, alt.value(1.0), alt.value(0.45)),
            tooltip=tooltip,
        )
    )
    expected_line = (
        alt.Chart(all_games.dropna(subset=["xg_diff"]))
        .mark_line(strokeWidth=2, point=alt.OverlayMarkDef(size=80, filled=True, shape="diamond"))
        .encode(
            x=x_axis,
            y=alt.Y("xg_diff:Q", title="Goal differential"),
            color=alt.Color(
                "expected_series:N", scale=legend_scale, legend=alt.Legend(title=None, orient="top")
            ),
            tooltip=tooltip,
        )
    )
    zero = alt.Chart(pd.DataFrame({"y": [0]})).mark_rule(color=colors["ref"]).encode(y="y:Q")
    st.altair_chart(
        (band + zero + bars + expected_line).resolve_scale(color="shared"), width="stretch"
    )
    caption = (
        "Bars: actual goal differential (blue = won by, red = lost by). Diamonds: expected "
        "goal differential from CHN's xG. **End of the bar above the diamond = better than "
        "expected; below = worse.** That holds for losses too: losing by 1 when expected to lose "
        "by 2 puts the bar's end above the diamond, so they outperformed. Shaded: the selected "
        "games. Hover for shot share, xG share and shots."
    )
    if all_games["xg_diff"].isna().any():
        caption += " Games without xG have no diamond."
    st.caption(caption)

    st.subheader(f"Games: {window_label.lower()}")
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Date": dt.date.fromisoformat(str(g["date"])).strftime("%a %b %-d"),
                    "Opponent": ("vs " if g["is_home"] else "at ") + g["opponent"]["name"],
                    "Result": game_label(g),
                    "Shots": f"{g['shots_for']}-{g['shots_against']}",
                    "Rest days": g["rest_days"],
                }
                for g in form["games"]
            ]
        ),
        hide_index=True,
        width="stretch",
    )

# ----------------------------------------------------------------------------
# Players
# ----------------------------------------------------------------------------

with tab_players:
    starter = players["likely_starter"]
    if starter:
        last_note = (
            "started the last game"
            if starter["started_last_game"]
            else "did not start the last game"
        )
        st.info(
            f"🥅 **Likely starter: {starter['name']}**: {starter['starts']} of the last "
            f"{starter['of_last']} starts, {last_note}."
        )

    DIFF_COLUMNS = ("P/GP", "SV%")  # higher is better for both: green up, red down

    def player_table(
        lines: list[dict], columns: dict[str, tuple[str, str]], extra: dict
    ) -> pd.DataFrame:
        rows = []
        for p in lines:
            row = {"Player": p["name"], **{k: f(p) for k, f in extra.items()}}
            for label, (key, kind) in columns.items():
                row[label] = fmt(p["window"][key], kind) if kind != "int" else p["window"][key]
            if p["season_totals"]:
                for label, (key, kind) in columns.items():
                    if key in (
                        "games",
                        "points",
                        "points_per_game",
                        "pp_points",
                        "goals",
                        "save_pct",
                        "gaa",
                        "starts",
                    ):
                        v = p["season_totals"][key]
                        row[f"Season {label}"] = fmt(v, kind) if kind != "int" else v
                for label in DIFF_COLUMNS:
                    if label in columns:
                        key, kind = columns[label]
                        row[f"{label} diff"] = delta_value(
                            p["window"][key], p["season_totals"][key], kind
                        )
            rows.append(row)
        df = pd.DataFrame(rows)
        # keep each season value and its difference right next to the stat, where they're visible
        for label in DIFF_COLUMNS:
            if f"{label} diff" in df:
                cols = [c for c in df.columns if c not in (f"Season {label}", f"{label} diff")]
                at = cols.index(label) + 1
                df = df[cols[:at] + [f"Season {label}", f"{label} diff"] + cols[at:]]
        return df

    st.subheader(
        f"Skaters · {window_label.lower()}" + ("" if full_season else " (season alongside)")
    )
    show_all = st.toggle("Include skaters who didn't play in these games", value=False)
    skaters = [s for s in players["skaters"] if show_all or s["window"]["games"] > 0]
    if not full_season:
        st.caption("P/GP diff: last games minus season. Green = scoring more, red = less.")
    st.dataframe(
        style_signed(
            player_table(
                skaters,
                {
                    "GP": ("games", "int"),
                    "G": ("goals", "int"),
                    "A": ("assists", "int"),
                    "P": ("points", "int"),
                    "P/GP": ("points_per_game", "num"),
                    "PP pts": ("pp_points", "int"),
                    "Shots": ("shots", "int"),
                    "Sh%": ("shooting_pct", "pct"),
                    "+/-": ("plus_minus", "int"),
                    "PIM": ("pim", "int"),
                },
                {"Pos": lambda p: p["position"]},
            ),
            "P/GP diff",
            "num",
        ),
        hide_index=True,
        placeholder="",  # no difference to show (text stats, players who sat out)
        width="stretch",
        height=min(38 * (len(skaters) + 1) + 3, 740),
    )

    st.subheader("Goalies")
    if not full_season:
        st.caption("SV% diff: last games minus season. Green = saving more, red = less.")
    st.dataframe(
        style_signed(
            player_table(
                players["goalies"],
                {
                    "GP": ("games", "int"),
                    "Starts": ("starts", "int"),
                    "SV%": ("save_pct", "pct"),
                    "GAA": ("gaa", "num"),
                    "Saves": ("saves", "int"),
                    "Shots against": ("shots_against", "int"),
                },
                {},
            ),
            "SV% diff",
            "pct",
        ),
        hide_index=True,
        placeholder="",  # no difference to show (text stats, players who sat out)
        width="stretch",
    )

# ----------------------------------------------------------------------------
# Head to head with your team
# ----------------------------------------------------------------------------

with tab_h2h:
    if scouted["team_id"] == home["team_id"]:
        st.info("Pick a different team to compare.")
    else:
        home_form = cached("team_form", home["team_id"], season, last, as_of)
        if home_form is None:
            st.info(f"{home_name} has no games before {as_of:%b %-d}.")
        else:
            st.subheader(f"Last {last} games each" if not full_season else "Season so far")
            st.caption(
                f"{scouted['name']}: {form['games_used']} games · {home_name}: "
                f"{home_form['games_used']} games. **Better**: green = {home_name}, "
                f"red = {scouted['name']}, yellow = tie."
            )
            st.dataframe(
                style_better(
                    pd.DataFrame(
                        side_by_side(window, home_form["window"], scouted["name"], home_name)
                    ),
                    mine=home_name,
                    theirs=scouted["name"],
                ),
                hide_index=True,
                width="stretch",
                height=36 * (len(TEAM_STATS) + 1) + 3,
            )
        past = meetings(home_schedule, scouted["team_id"])
        st.subheader("Meetings this season")
        if past:
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "Date": dt.date.fromisoformat(str(g["date"])).strftime("%a %b %-d"),
                            "Where": "home" if g["is_home"] else "away",
                            f"{home_name} result": game_label(g),
                            "Shots": f"{g['shots_for']}-{g['shots_against']}",
                        }
                        for g in past
                    ]
                ),
                hide_index=True,
                width="stretch",
            )
        else:
            st.caption("They haven't played yet this season.")
