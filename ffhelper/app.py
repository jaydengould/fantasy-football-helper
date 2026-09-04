"""Dash draft board. The only module in this package that imports dash.

State model: the `.draft/<league>-<date>.jsonl` journal IS the database. Every
render replays it, polls the feed, and rebuilds the board, so this process holds
no mutable draft state at all. That is what lets the terminal board take over at
any moment by replaying the same file -- ctrl-C here, `python -m ffhelper.cli
run --league <name>` there, and nothing is lost.

ONE PROCESS AT A TIME. The CLI holds MarkDrafted in memory and replays only at
startup, so it will not see writes made here while it is running. The handover
is sequential in both directions, never concurrent.
"""
import argparse
import logging
import sys
import time
from urllib.parse import parse_qs

import dash
from dash import Input, Output, dash_table, dcc, html

from ffhelper import pipeline, store
from ffhelper.board import (
    BoardState, auto_mine, board_state, explicit_not_mine, marks_in_entry_order,
)
from ffhelper.cli import (
    DRAFT_LOG_DIR, DROP_CAVEAT, ROOT, ROSTER_DIR, SEASON, TRADE_CAVEAT, _draft_log_path,
    _matchup_note, _restore_marks, _select_feed, _status_note, load_board_inputs,
    roster_file_age_days,
)
from ffhelper.config import League, Tunables, get_league, load_config
from ffhelper.data import Player, load_nfl_state
from ffhelper.value import FLEX_ELIGIBLE, is_bench_only, next_pick_number, optimal_lineup

log = logging.getLogger(__name__)
CONFIG_PATH = ROOT / "config.toml"

COLUMNS = [
    {"name": "#", "id": "rank"}, {"name": "PLAYER", "id": "player"},
    {"name": "POS", "id": "pos"}, {"name": "VONA", "id": "vona"},
    {"name": "VBD", "id": "vbd"}, {"name": "MARG", "id": "marg"},
    {"name": "TIER", "id": "tier"}, {"name": "SURV", "id": "surv"},
    {"name": "DIV", "id": "div"}, {"name": "FLAGS", "id": "flags"},
]


def board_rows(state: BoardState, limit: int, divergence_flag_slots: int) -> list[dict]:
    """One dict per displayed row. Data only -- no styling, no dash types.

    ponytail: rows are plain dicts precisely so the DataTable can be swapped for
    a hand-rolled table later without touching this function. DataTable's
    ceiling is that a row cannot contain arbitrary markup -- no sparklines, no
    per-row buttons, no true tier separator rows -- so tier grouping, if it is
    ever added, would use per-row background colour rather than header rows.
    Not implemented yet: no such styling exists in this module today.
    """
    # Byes already spoken for, by position. Built once per render, not per row.
    rostered_byes = {(p.position, p.bye) for p in state.my_roster if p.bye}
    rows = []
    for i, r in enumerate(state.board[:limit], 1):
        flags = []
        if r.player.injury_status:
            flags.append(r.player.injury_status)
        # None means the market never priced him -- a third of the pool. No
        # opinion is not agreement, so no flag and a dash, never a 0.
        if r.divergence is not None and abs(r.divergence) >= divergence_flag_slots:
            flags.append(f"{'MODEL' if r.divergence > 0 else 'MARKET'}+{abs(r.divergence)}")
        # A bye you already own at this position is a week you start nobody
        # there. Lowercase `bye6` is information; uppercase CLASH is a warning,
        # and the case difference is what the red style matches on.
        if r.player.bye:
            if (r.player.position, r.player.bye) in rostered_byes:
                flags.append(f"BYE{r.player.bye} CLASH")
            else:
                flags.append(f"bye{r.player.bye}")
        rows.append({
            "rank": i,
            "id": r.player.sleeper_id,      # every click resolves through this
            "player": r.player.name,
            "pos": r.player.position,
            "vona": round(r.vona, 1),
            "vbd": round(r.vbd, 1),
            "marg": round(r.marginal, 1),
            "tier": r.tier,
            "surv": f"{r.survival:.0%}",
            "div": "-" if r.divergence is None else f"{r.divergence:+d}",
            "flags": " ".join(flags),
        })
    return rows


# Position colour is CATEGORICAL and deliberately muted. State (on the clock,
# stale, overruled) is the only thing on this page allowed a saturated colour,
# so the two signals can never be confused: they use different channels --
# hue for position, intensity and area for state. Forty rows each carrying a
# saturated border is noise, and it would drown the one row that matters.
POSITION_COLORS = {
    "QB": "#c98bb0", "RB": "#7fb894", "WR": "#7fa3cc",
    "TE": "#c9a978", "K": "#8b95a3", "DEF": "#9b8bc4",
}

# Static filter_query rules, not a per-row pass: `pos` is a real column id, so
# the table matches these itself. Two per position -- the POS cell's text and a
# stripe down the first column, which is what makes a row scan as one unit.
POS_STYLES = [
    style
    for pos, colour in POSITION_COLORS.items()
    for style in (
        {"if": {"filter_query": f'{{pos}} = "{pos}"', "column_id": "pos"},
         "color": colour, "fontWeight": "600"},
        {"if": {"filter_query": f'{{pos}} = "{pos}"', "column_id": "rank"},
         "borderLeft": f"3px solid {colour}"},
    )
]


def _alpha(hex_colour: str, a: float) -> str:
    """#rrggbb -> rgba(). Keeps one source of truth for the position hues."""
    r, g, b = (int(hex_colour[i:i + 2], 16) for i in (1, 3, 5))
    return f"rgba({r}, {g}, {b}, {a})"


# The TIER cell is a badge in its OWN position's colour, which is what makes
# "who is interchangeable with whom" a one-cell read.
#
# This REPLACED alternating background bands, which were wrong by construction:
# the board interleaves positions by VONA, so a (pos, tier) group is not
# contiguous -- RB tier 4 sat at rows 7, 8 and 10 with a WR between. A
# background band can only group ADJACENT rows, so it could never express the
# grouping, and two shades cycling over eight groups said nothing at all. The
# signal has to travel with the row, not sit behind it.
TIER_STYLES = [
    {"if": {"filter_query": f'{{pos}} = "{pos}"', "column_id": "tier"},
     "color": colour,
     "backgroundColor": _alpha(colour, 0.14),
     "fontWeight": "700"}
    for pos, colour in POSITION_COLORS.items()
]

# Uppercase CLASH never appears in an informational flag, so this matches the
# warning and nothing else. Red is a STATE colour, which is why no position is
# allowed one: a clash has to out-shout the row it sits in.
CLASH_STYLES = [
    {"if": {"filter_query": '{flags} contains "CLASH"', "column_id": "flags"},
     "color": "#ef4444", "fontWeight": "700"},
]


def filter_rows(rows: list[dict], position: str, query: str) -> list[dict]:
    """Narrow the displayed rows. Presentation only -- never changes the board."""
    out = rows
    if position == "FLEX":
        # The one slot whose candidates span positions, so comparing them means
        # seeing them in one list. FLEX_ELIGIBLE is value.py's rule, imported
        # rather than restated -- the same reason the roster panel imports it.
        out = [r for r in out if r["pos"] in FLEX_ELIGIBLE]
    elif position and position != "ALL":
        out = [r for r in out if r["pos"] == position]
    q = (query or "").strip().lower()
    if q:
        out = [r for r in out if q in r["player"].lower()]
    return out


def roster_slots_view(
    my_roster: list[Player], roster_slots: dict[str, int], bench_slots: int = 0,
) -> list[tuple[str, str | None]]:
    """Starting slots in roster order, then the bench. Each filled or empty.

    Greedy by projected points within a position, FLEX last from whatever is
    left. The FLEX rule is value.py's and is never restated here: a second copy
    would let the panel start a quarterback at FLEX while MARG says otherwise,
    and the two would disagree about one roster.

    The assignment itself is `value.optimal_lineup`, not a copy of it. It WAS a
    copy while value.py was frozen for the 2026 drafts; the freeze lifted on
    2026-09-01 and the fold happened, which is what
    test_the_panel_starts_exactly_the_lineup_lineup_value_scores had been
    guarding all along.
    """
    view = optimal_lineup(my_roster, roster_slots)
    started = {p.sleeper_id for _, p in view if p is not None}
    remaining = [p for p in sorted(my_roster, key=lambda p: -p.proj_pts)
                 if p.sleeper_id not in started]
    # The bench is not decoration: once STARTING LINEUP FULL is up, every
    # remaining pick goes here, and a panel that hides it shows a third of your
    # team. Overflow past `bench_slots` is still listed -- never silently
    # dropped -- because being over the roster limit is a drift symptom you need
    # to see, not one to hide.
    out = [(slot, p.name if p is not None else None) for slot, p in view]
    out += [("BN", p.name) for p in remaining]
    out += [("BN", None)] * max(0, bench_slots - len(remaining))
    return out


def banner_lines(
    state: BoardState, stale_seconds: float | None, players: dict[str, Player],
) -> list[str]:
    """Degrade, never fabricate: every degraded condition says so on screen."""
    lines: list[str] = []
    if stale_seconds is None:
        lines.append("MANUAL MODE: no pick feed -- picks are entered by hand only")
    elif stale_seconds > 15:
        lines.append(f"!! FEED STALE {stale_seconds:.0f}s -- board may be out of date")
    elif stale_seconds > 0:
        # There must be NO silent window. A 55s outage in the live Sleeper mock
        # read as a healthy board for its first 15 seconds, because only the
        # loud banner above existed -- and 15s is three picks. This line is
        # quiet by design (the board is barely stale and probably recovering)
        # but it is never absent while a poll is failing.
        lines.append(f"feed not answering -- last good poll {stale_seconds:.0f}s ago")
    if is_bench_only(state.board):
        lines.append("STARTING LINEUP FULL: no player improves your starters. "
                     "These are BENCH picks, ordered by value over league replacement. "
                     "The tool has no model of upside or handcuffs -- trust yourself here.")
    for pid in sorted(state.overruled):
        name = players[pid].name if pid in players else pid
        lines.append(f"CLAIM OVERRULED: the feed says {name} was taken from another "
                     f"seat, not yours -- dropped from your roster.")
    if state.runs:
        summary = "  ".join(f"{pos} {n}" for pos, n in
                            sorted(state.runs.items(), key=lambda kv: -kv[1]))
        lines.append(f"last 8 picks:  {summary}")
    return lines


def is_on_the_clock(state: BoardState, league: League, num_teams: int) -> bool:
    """True when the current pick belongs to this seat.

    Extracted so the clock TEXT and the page's live-state styling read one
    predicate instead of two copies. Same reasoning as the roster panel
    importing FLEX_ELIGIBLE rather than restating it: two views of one fact
    that can drift apart will eventually disagree, and here they would disagree
    about whether you are on the clock.
    """
    if not league.draft_slot:
        return False
    # next_pick_number is strictly-after, so ask from one pick earlier and see
    # whether it lands here.
    return next_pick_number(
        state.current_pick - 1, league.draft_slot, num_teams) == state.current_pick


def clock_line(state: BoardState, league: League, num_teams: int) -> str:
    if not league.draft_slot:
        return f"pick {state.current_pick}"
    nxt = next_pick_number(state.current_pick, league.draft_slot, num_teams)
    if is_on_the_clock(state, league, num_teams):
        return (f">>> PICK {state.current_pick} IS YOURS -- YOU ARE ON THE CLOCK <<<"
                f"   (next after this: {nxt})")
    return (f"pick {state.current_pick}   your next pick: {nxt} "
            f"({nxt - state.current_pick} away)")


# Poll bookkeeping only -- NOT draft state. The board itself is rebuilt from the
# journal every tick and nothing about who was drafted lives in this process.
_LAST_OK: dict[str, float] = {}

# The last picks the feed successfully returned, per league. This is a CACHE of
# the feed's answer, not a second source of truth: it is never written to, never
# read on a healthy poll, and a restart simply re-polls. It exists because a
# stateless render has no equivalent of the CLI loop's `picks` variable, which
# survives the except branch and is the only reason the terminal degrades
# correctly. Without it a failed poll rebuilt the board from NO picks -- pick 1,
# the whole pool back on the board, an empty roster -- which is a fabricated
# draft, not a degraded one. Found by cutting wifi during the live Sleeper mock.
_LAST_PICKS: dict[str, list] = {}


def read_state(league, tunables, players, settings, feed, has_feed):
    """Replay the journal, poll the feed, derive the board. -> (state, stale_seconds)

    Every failure degrades rather than raising: a dead feed must leave the board
    on screen with an honest staleness banner, not an error page.

    `stale_seconds is None` means there is no feed at all (Yahoo), which is a
    different statement from "the feed has not answered recently" and must read
    differently on screen.
    """
    log_path = _draft_log_path(league)
    mark_state, _applied, _skipped = _restore_marks(log_path)
    # Seat-based attribution replaces the terminal's typed "me " prefix, but an
    # explicit statement always wins over the derived guess in BOTH directions
    # -- it exists precisely for the case where entry has drifted. `derived` is
    # recomputed from pick POSITION alone on every tick and has no memory of an
    # override, so a `mine=False` correction must be subtracted back out here
    # every time, not just applied once -- otherwise the very next tick
    # silently re-derives the player as mine again.
    derived = auto_mine(marks_in_entry_order(log_path), league.draft_slot,
                        settings.num_teams)
    manual_mine = (derived - explicit_not_mine(log_path)) | mark_state.mine

    picks, stale_seconds = [], None
    try:
        picks = feed.get_picks()
    except Exception as exc:                          # noqa: BLE001 - never fatal
        log.warning("poll failed: %s", exc)
        # Show the last board we know to be true, behind the staleness banner.
        # An empty list here would be a claim that nobody has been drafted.
        picks = _LAST_PICKS.get(league.name, [])
        if has_feed:
            stale_seconds = time.time() - _LAST_OK.get(league.name, time.time())
    else:
        if has_feed:
            _LAST_OK[league.name] = time.time()
            _LAST_PICKS[league.name] = picks
            stale_seconds = 0.0
    state = board_state(players, picks, mark_state.drafted, manual_mine,
                        settings, league, tunables)
    return state, stale_seconds


def apply_click(log_path, player_id: str) -> str:
    """Mark one player drafted. Replay, apply, append -- never hold state.

    Replaying before every write is what makes the CLI handover exact: the
    journal on disk is the only thing either process trusts, so a mark typed
    into the terminal a moment ago is already accounted for here.
    """
    state, _applied, _skipped = _restore_marks(log_path)
    state.mark(player_id)
    return f"marked {player_id}"


def apply_override(log_path, player_id: str, mine: bool) -> str:
    """Correct attribution for one player, without changing whether he is drafted.

    The only reason to need this is that entry has drifted -- a missed or
    doubled pick shifts every pick number after it -- so it is also the cue to
    re-check the pick count against the platform's own board.
    """
    state, _applied, _skipped = _restore_marks(log_path)
    if mine:
        state.mark(player_id, mine=True)
        return f"{player_id} is yours"
    # unmark then re-mark: he is still drafted, just not by you. Removing him
    # from `drafted` would put a genuinely gone player back on the board.
    state.unmark(player_id)
    state.mark(player_id, mine=False)
    return f"{player_id} is not yours"


def apply_undo(log_path) -> str:
    state, _applied, _skipped = _restore_marks(log_path)
    if not state._history:
        return "nothing to undo"
    state.undo()
    return "undone"


ROUTES = [("/", "home"), ("/draft", "draft"), ("/lineup", "lineup"),
          ("/waivers", "waivers"), ("/trades", "trades")]


def _resolve_league(value: str, names: list[str], default: str) -> str:
    """A candidate league name, or the default when it is unknown.

    The one place the fallback rule lives: unknown, empty, or malformed input
    means the default, never a raise -- a typo or a stray edit to the URL must
    not 500 the page, and never fuzzy-matches, either, which would silently
    advise on the wrong league.
    """
    return value if value in names else default


def league_from_search(search: str, names: list[str], default: str) -> str:
    """The league named in `?league=`, or the default. See `_resolve_league`."""
    got = parse_qs((search or "").lstrip("?")).get("league", [""])[0]
    return _resolve_league(got, names, default)


def league_from_kwargs(kw: dict, names: list[str], default: str) -> str:
    """`_resolve_league`, wired for how Dash actually calls a page layout.

    A registered page's layout callable is invoked with the URL's query
    parameters already parsed into individual kwargs (e.g. `league="x"`), not
    with the raw "?league=x" string, so the bare value is handed straight to
    the shared fallback rule instead of round-tripping it back through a query
    string just to have `league_from_search` decode it again.
    """
    return _resolve_league(kw.get("league", ""), names, default)


def nav(active: str, league: str) -> html.Div:
    """The same five links on every page, with the league carried across."""
    return html.Div([
        dcc.Link(label.upper(), href=f"{path}?league={league}",
                 style={"marginRight": "18px",
                        "fontWeight": "700" if label == active else "400"})
        for path, label in ROUTES
    ], style={"padding": "12px 0"})


def snapshot_recorded(conn, league: str, season: str, week: int) -> bool | None:
    """Whether this week is in the snapshot table. None means 'could not check'.

    Three-valued on purpose. False is a measurement -- the table was read and
    the week is not in it, so a snapshot is due. None is the absence of a
    measurement, and the caller must omit the line rather than print False's
    wording. Non-negotiable #7: degrade to absent, never to a fabricated value.
    """
    try:
        row = conn.execute(
            "SELECT 1 FROM snapshot WHERE league=? AND season=? AND week=? LIMIT 1",
            (league, season, week)).fetchone()
    except Exception:                        # noqa: BLE001 - absent, not fabricated
        return None
    return row is not None


def status_strip(league: str) -> html.Div:
    """Homepage line-per-fact summary: NFL week, snapshot status, roster age.

    Every fact degrades independently and by OMISSION, never a fabricated
    substitute -- non-negotiable #7. `snapshot_recorded`'s None is the reason
    this exists: an unreadable database drops the line instead of claiming the
    week is missing.

    ponytail: "Yahoo league" is read off roster-file existence rather than a
    platform lookup. No `League` config object reaches this page -- `build_app`
    only ever carries league NAMES -- and `.roster/<league>.txt` is written by
    nothing in this codebase; `cli.py` only READS it, and only on the
    non-sleeper branch. So the file's mere presence already implies the
    platform, without a config load this page has no other reason to do.
    """
    lines = []
    week = season = None
    try:
        state = load_nfl_state()
        week = state.get("week")
        season = str(state.get("season") or SEASON)
        lines.append(f"nfl week {week} ({season} {state.get('season_type')})")
    except Exception:                          # noqa: BLE001 - degrade, never fabricate
        lines.append("week unavailable")

    if week is not None:
        conn = None
        try:
            conn = store.connect()
            recorded = snapshot_recorded(conn, league, season, week)
        except Exception:                      # noqa: BLE001 - degrade, never fabricate
            recorded = None
        finally:
            if conn is not None:
                conn.close()
        if recorded is True:
            lines.append(f"snapshot recorded for week {week}")
        elif recorded is False:
            lines.append(f"snapshot NOT recorded for week {week} -- run a snapshot")
        # recorded is None: could not check, so the line is omitted entirely.

    age = roster_file_age_days(ROSTER_DIR / f"{league}.txt")
    if age is not None:
        lines.append(f"roster file: {age}d old")

    return html.Div([html.P(line, style={"margin": "4px 0"}) for line in lines],
                    style={"fontFamily": _SANS, "fontSize": "13px", "padding": "8px 0"})


def home_layout(league: str, league_names: list[str]) -> html.Div:
    """Nav plus the status strip: current week, snapshot status, roster age."""
    return html.Div([nav("home", league), status_strip(league)])


_LINEUP_HEADERS = ["slot", "player", "pos", "team", "proj", "flags"]


def lineup_rows(view) -> list[dict]:
    """One row per starter slot, plus a projected-total row.

    Mirrors `render_lineup`'s STARTERS section and total line branch for
    branch (cli.py) -- two rules that can disagree is the defect this project
    calls out repeatedly. `--`, never `0.0`, for an unprojected starter: the
    0.0 is a sort value this code invented, and printing it as a projection
    is the fabrication non-negotiable #7 bars, arriving in the one place a
    user is most likely to trust it.
    """
    state = view.state
    unprojected_ids = {p.sleeper_id for p in state.unprojected}
    rows = []
    total = 0.0
    unprojected_starters = 0
    for slot, p in state.lineup:
        if p is None:
            rows.append({"slot": slot, "player": "-- EMPTY --", "pos": "", "team": "",
                        "proj": "", "flags": "no eligible player on this roster"})
            continue
        total += p.proj_pts
        if p.sleeper_id in unprojected_ids:
            unprojected_starters += 1
            rows.append({"slot": slot, "player": p.name, "pos": p.position,
                        "team": p.team or "", "proj": "--",
                        "flags": f"NO PROJECTION{_status_note(p)}".strip()})
        else:
            rows.append({"slot": slot, "player": p.name, "pos": p.position,
                        "team": p.team or "", "proj": f"{p.proj_pts:.1f}",
                        "flags": f"{_matchup_note(p, view.matchups)}"
                                f"{_status_note(p)}".strip()})
    # Same caveat render_lineup prints next to the total, for the same reason:
    # unprojected starters contribute their invented 0.0 to `total`, so an
    # unqualified number would understate a lineup with a gap in it.
    caveat = (f"(floor -- {unprojected_starters} starter"
             f"{'s' if unprojected_starters != 1 else ''} unprojected)"
             if unprojected_starters else "")
    rows.append({"slot": "", "player": "projected total", "pos": "", "team": "",
                "proj": f"{total:.1f}", "flags": caveat})
    return rows


def bench_rows(view) -> list[dict]:
    """Projected bench, mirroring `render_lineup`'s BENCH section.

    Excludes anything in `state.unprojected` -- those get their own section
    below, same split the text renderer makes.
    """
    state = view.state
    projected_bench = [p for p in state.bench if p not in state.unprojected]
    return [{"slot": "", "player": p.name, "pos": p.position, "team": p.team or "",
            "proj": f"{p.proj_pts:.1f}",
            "flags": f"{_matchup_note(p, view.matchups)}{_status_note(p)}".strip()}
           for p in projected_bench]


def unprojected_player_rows(view) -> list[dict]:
    """'NO PROJECTION THIS WEEK' -- not started, and not a zero.

    Mirrors `render_lineup`'s own section of that name: a stash can carry no
    number for months, so this is a quiet list, never a '!!' note.
    """
    return [{"slot": "", "player": p.name, "pos": p.position, "team": p.team or "",
            "proj": "--", "flags": _status_note(p).strip()}
           for p in view.state.unprojected]


def simple_table(headers: list[str], rows: list[dict]) -> html.Div:
    """A read-only `html.Table` from plain dicts.

    Not `dash_table.DataTable` -- these rows take no clicks, and DataTable's
    styling machinery would be dead weight here. Wrapped in its own
    `overflowX: auto` div so a wide table scrolls inside its own container,
    never the page body.
    """
    head = html.Tr([html.Th(h.upper(), style=_TABLE_HEADER) for h in headers])
    body = [html.Tr([html.Td(row.get(h, ""), style=_TABLE_CELL) for h in headers])
           for row in rows]
    table = html.Table([html.Thead(head), html.Tbody(body)],
                       style={"borderCollapse": "collapse", "width": "100%"})
    return html.Div(table, style={"overflowX": "auto"})


def _lineup_children(view) -> list:
    """Every `render_lineup` section as HTML: starters, bench, unprojected,
    close calls, notes. SPEC GAP ruling for task 7 -- the brief's
    `lineup_rows` covers only STARTERS and the total, but `render_lineup`
    also prints BENCH, an unprojected list, CLOSE CALLS, and '!!' notes, and
    an HTML page that dropped them would quietly show less than the text
    page it replaces. Nothing here is new logic; each section reuses the row
    builders above or reads the same view fields the text renderer does.
    """
    state = view.state
    who = f"  ({view.owner})" if view.owner else ""
    children = [
        html.P(f"{view.league_name}{who}   week {view.week}",
              style={"fontFamily": _SANS, "fontWeight": "700"}),
        simple_table(_LINEUP_HEADERS, lineup_rows(view)),
    ]

    bench = bench_rows(view)
    if bench:
        children += [html.P("BENCH", style={"fontWeight": "700", "marginTop": "16px"}),
                     simple_table(_LINEUP_HEADERS, bench)]

    unprojected = unprojected_player_rows(view)
    if unprojected:
        children += [html.P("NO PROJECTION THIS WEEK -- not started, and not a zero",
                            style={"fontWeight": "700", "marginTop": "16px"}),
                     simple_table(_LINEUP_HEADERS, unprojected)]

    if state.close_calls:
        children += [
            html.P("CLOSE CALLS -- worth your own read",
                  style={"fontWeight": "700", "marginTop": "16px"}),
            html.Ul([
                html.Li(f"{c.slot}: starting {c.starter.name} over {c.challenger.name} "
                       f"by {c.gap:.1f}{_status_note(c.challenger)}".strip())
                for c in state.close_calls
            ]),
        ]

    if view.notes:
        children.append(html.Ul([html.Li(f"!! {n}") for n in view.notes],
                                style={"marginTop": "16px"}))

    # Unconditional, matching the pre-table text renderer: both
    # cli._matchup_context and cli._practice_status are contracted to
    # "always return a line" (their own docstrings), so there is no real
    # empty case to guard here -- only LineupView's dataclass defaults are
    # empty strings, and those never reach a view with `error` unset.
    children.append(html.P(f"{view.matchup_line}  {view.practice_line}",
                           style={"fontSize": "12px", "color": "#8b95a3",
                                  "marginTop": "16px"}))
    return children


_WAIVER_HEADERS = ["pos", "player", "gain", "drop", "starts", "trending"]


def waiver_rows(view, section: str) -> list[dict]:
    """One row per target in THIS WEEK (`section="this_week"`) or REST OF
    SEASON (`section="ros"`), mirroring `render_waivers`'s `section` closure
    (cli.py) line for line -- including its section-dependent `of` starts
    denominator: 1 for THIS WEEK, `weeks_scored` for REST OF SEASON. Two
    rules that can disagree is the defect this project calls out repeatedly.

    `trending` carries `load_trending`'s NATIONALLY -- NOT your league
    qualifier in the cell itself, not just a header the user can miss.
    """
    targets = view.this_week if section == "this_week" else view.ros
    of = 1 if section == "this_week" else view.weeks_scored
    rows = []
    for t in targets:
        count = view.trending.get(t.player.sleeper_id)
        trending = (f"+{count:,} adds NATIONALLY -- NOT your league" if count else "")
        rows.append({
            "pos": t.player.position, "player": t.player.name,
            "gain": f"+{t.gain:.1f}", "drop": t.drop.name,
            "starts": f"{t.weeks_started} of {of} starts",
            "trending": trending,
        })
    return rows


def waivers_children(view) -> list:
    """Every `render_waivers` section as HTML: '!!' notes, the waiver-priority
    line, THIS WEEK / REST OF SEASON tables (or the empty-board result), and
    DROP_CAVEAT. SPEC GAP ruling for task 8, same shape as task 7's
    `_lineup_children`: `waiver_rows` covers only the two target tables, but
    `render_waivers` also prints the notes and the priority line, and both
    carry information the table cannot restate -- league shape and the cost
    of a claim.
    """
    who = f" ({view.owner})" if view.owner else ""
    children = [
        html.P(f"WAIVERS -- {view.league_name}{who} -- week {view.week}",
              style={"fontFamily": _SANS, "fontWeight": "700"}),
    ]
    if view.notes:
        children.append(html.Ul([html.Li(f"!! {n}") for n in view.notes]))
    if view.position is not None and view.teams:
        children.append(html.P(
            f"waiver priority {view.position} of {view.teams} -- a successful "
            f"claim sends you to {view.teams}th"))

    this_week = waiver_rows(view, "this_week")
    if this_week:
        children += [
            html.P(f"THIS WEEK -- upgrade to your week {view.week} lineup",
                  style={"fontWeight": "700", "marginTop": "16px"}),
            simple_table(_WAIVER_HEADERS, this_week),
        ]

    ros = waiver_rows(view, "ros")
    if ros:
        children += [
            html.P(f"REST OF SEASON -- upgrade over weeks {view.week}-{view.last_week}",
                  style={"fontWeight": "700", "marginTop": "16px"}),
            simple_table(_WAIVER_HEADERS, ros),
        ]

    if not this_week and not ros:
        # A RESULT, not a blank. On a healthy roster the best thing available
        # is inside the measured weekly error, and saying nothing at all
        # would read as a failed fetch.
        children += [
            html.P("nothing on the wire beats what you already have.",
                  style={"marginTop": "16px"}),
            html.P("(a target must gain more than the weekly projection error "
                  "to be listed.)"),
        ]
    else:
        children.append(html.P(DROP_CAVEAT, style={"marginTop": "16px",
                                                    "whiteSpace": "pre-wrap"}))
    return children


def _package_html(players) -> str:
    """`give`/`get`'s player list, exactly as `cli._package` renders it."""
    return " + ".join(f"{p.name} ({p.position})" for p in players)


def trades_children(view) -> list:
    """Every `render_trades` section as HTML: the weeks-scored header, '!!'
    notes, the mode line, one block per proposal (opponent, gains, shape,
    give, get, the forced `their_drop`), the empty-result line, and
    TRADE_CAVEAT. SPEC GAP ruling for task 9, same shape as tasks 7-8's
    `_lineup_children`/`waivers_children`: the brief's proposal fields cover
    only the per-trade blocks, but `render_trades` (cli.py) also prints the
    header count, the notes, the mode line, the empty result, and the
    caveat, and an HTML page that dropped them would quietly show less than
    the text page it replaces.

    Handles `view.error` itself rather than trusting every caller to check
    first -- `season_page_children` already gates on it, but a direct call
    (as this module's own tests make) must not crash on a deadline-passed or
    platform-refusal view, which never carries a `best` list, a `week`, or
    `names` to render.
    """
    if view.error:
        return [html.Div(view.error, style={"padding": "16px", "maxWidth": "60ch"})]

    who = f" ({view.owner})" if view.owner else ""
    children = [
        html.P(f"TRADES -- {view.league_name}{who} -- week {view.week}, "
              f"{view.weeks_scored} weeks scored",
              style={"fontFamily": _SANS, "fontWeight": "700"}),
    ]
    if view.notes:
        children.append(html.Ul([html.Li(f"!! {n}") for n in view.notes]))

    best = view.best
    pinned = view.pinned
    if pinned is None:
        mode = "best offer per opponent"
    elif best and any(p.sleeper_id == pinned.sleeper_id for p in best[0].give):
        mode = f"best return for {pinned.name}"
    elif best and any(p.sleeper_id == pinned.sleeper_id for p in best[0].get):
        mode = f"cost to acquire {pinned.name}"
    else:
        mode = f"trade search for {pinned.name}"
    children.append(html.P(mode, style={"fontWeight": "700", "marginTop": "16px"}))

    if not best:
        children.append(html.P(
            "no trade with any opponent clears the floor for both sides.",
            style={"marginTop": "16px"}))
    else:
        for p in best:
            name = view.names.get(p.opponent, f"roster {p.opponent}")
            shape = f"{len(p.give)}-for-{len(p.get)}"
            children.append(html.P(
                f"{name}   you +{p.gain_me:.1f}   them +{p.gain_them:.1f}   [{shape}]",
                style={"fontWeight": "700", "marginTop": "16px"}))
            children.append(html.P(f"give {_package_html(p.give)}"))
            children.append(html.P(f"get  {_package_html(p.get)}"))
            if p.their_drop is not None:
                # Part of the offer, not a footnote -- mirrors render_trades'
                # own comment (cli.py): the counterparty notices the cut
                # before they notice the gain.
                children.append(html.P(f"they must also drop {p.their_drop.name} "
                                       f"({p.their_drop.position})"))

    children.append(html.P(TRADE_CAVEAT,
                           style={"marginTop": "16px", "whiteSpace": "pre-wrap"}))
    return children


def trades_landing(league: str) -> html.Div:
    """The /trades landing state, before the sweep runs: TRADE_CAVEAT, the
    expected-wait line, and the RUN button -- never followed automatically.
    `build_trades`'s full sweep is a measured ~330s (pipeline.py's own
    ponytail note), so a page that computed on navigation would hang the
    browser for five minutes; an accidental visit to /trades must cost
    nothing.

    Carries the league in a hidden `dcc.Store`: the callback below is wired
    to `Input("trades-run", "n_clicks")` alone, which carries no league, so
    without this a click would always sweep the DEFAULT league regardless of
    `?league=` -- silent, and a wasted 330s on the wrong league.
    """
    return html.Div([
        dcc.Store(id="trades-league", data=league),
        html.P(TRADE_CAVEAT, style={"whiteSpace": "pre-wrap", "maxWidth": "60ch"}),
        html.P("the full sweep takes about five minutes -- eleven opponents, "
              "three shapes each",
              style={"fontWeight": "700", "marginTop": "12px"}),
        html.Button("RUN THE SEARCH", id="trades-run"),
    ], id="trades-content")


def season_page_children(name: str, view):
    """One season view as page content. /lineup, /waivers and /trades all
    render as HTML (tasks 7-9): `trades_children` carries `render_trades`'s
    header, notes, mode line, per-proposal blocks and TRADE_CAVEAT, exactly
    as `_lineup_children`/`waivers_children` do for their own text renderers.
    """
    if view.error:
        return html.Div(view.error, style={"padding": "16px", "maxWidth": "60ch"})
    if name == "lineup":
        return html.Div(_lineup_children(view))
    elif name == "waivers":
        return html.Div(waivers_children(view))
    return html.Div(trades_children(view))


def _season_layout_for(name: str, league_names: list[str], default_league: str):
    """Layout factory for /lineup, /waivers, /trades.

    Returns the Dash page-layout callable itself (not the layout), since
    `register_page` needs a function it can call once per request with that
    request's query kwargs -- a plain `html.Div(...)` built here would freeze
    the league at registration time and never see `?league=` changes.
    """
    def layout(**kw) -> html.Div:
        league = league_from_kwargs(kw, league_names, default_league)
        if name == "trades":
            # No view built here -- build_trades' full sweep is ~330s
            # (pipeline.py's ponytail note); the button below is the only
            # thing allowed to trigger it (see _register_callbacks).
            return html.Div([nav(name, league), dcc.Loading(trades_landing(league))])
        leagues, tunables = load_config(CONFIG_PATH)
        lg = get_league(leagues, league)
        builder = pipeline.build_lineup if name == "lineup" else pipeline.build_waivers
        view = builder(lg, tunables)
        return html.Div([nav(name, league), season_page_children(name, view)])
    return layout


def build_app(league_names: list[str], default_league: str,
              poll_ms: int = 5000) -> dash.Dash:
    app = dash.Dash(__name__, use_pages=True, pages_folder="")
    # Key stays "board" -- only the path moves to /draft. tests/test_app.py
    # reads dash.page_registry["board"], and the registry key is internal;
    # the path is the user-visible thing this task actually changes.
    dash.register_page(
        "board", path="/draft",
        layout=_layout(league_names, default_league, poll_ms))
    dash.register_page("home", path="/", layout=lambda **kw: home_layout(
        league_from_kwargs(kw, league_names, default_league), league_names))
    for path, name in [("/lineup", "lineup"), ("/waivers", "waivers"),
                       ("/trades", "trades")]:
        dash.register_page(
            name, path=path,
            layout=_season_layout_for(name, league_names, default_league))
    app.layout = html.Div([dash.page_container])
    return app


def poll_interval_ms(tunables: Tunables, platform: str) -> int:
    """How often the browser asks for a fresh board, in ms.

    Same rule and same floor as cli.py's poll loop, deliberately: the two boards
    read one tunable so they cannot drift apart on the only knob that controls
    how far behind the draft you are. Floored at 1s because a 0 busy-loops and
    Sleeper IP-blocks above ~1000 req/min -- 1s measured at 60 req/min, 0
    failures over 30 consecutive polls.
    """
    return max(tunables.poll_seconds.get(platform, 5), 1) * 1000


_SANS = ('-apple-system, BlinkMacSystemFont, "Segoe UI", Inter, Roboto, '
         '"Helvetica Neue", Arial, sans-serif')

# Numbers are the reason the board was monospace. tabular-nums gives a
# proportional font fixed-width DIGITS, so the columns still line up and the
# page stops reading as a terminal -- which was the whole point.
_TABLE_CELL = {
    "fontFamily": _SANS,
    "fontVariantNumeric": "tabular-nums",
    "textAlign": "left",
    "backgroundColor": "transparent",
    "color": "#e6e9ee",
    "border": "none",
    "borderBottom": "1px solid #262c35",
    "padding": "9px 12px",
    "fontSize": "13px",
}

_TABLE_HEADER = {
    "backgroundColor": "#171b21",
    "color": "#8b95a3",
    "fontFamily": _SANS,
    "fontSize": "11px",
    "fontWeight": "700",
    "letterSpacing": "0.06em",
    "textTransform": "uppercase",
    "border": "none",
    "borderBottom": "1px solid #262c35",
    "padding": "10px 12px",
}

_NUMERIC_COLUMNS = ("rank", "vona", "vbd", "marg", "tier", "surv", "div")

# The journal file IS the database (see the module docstring), which is what
# makes the CLI-takeover fallback work at all -- and exactly why this page is
# not hosted: two processes writing the same local disk only stays sound
# because there is only ever one browser tab open on it. main() already prints
# this to the terminal, where nobody looking at the browser sees it.
DRAFT_NOTICE = ("LOCAL ONLY -- one process at a time. Do NOT run "
                "`ffhelper.cli run` for this league while this page is open: "
                "the CLI replays the journal once at ITS startup, so it would "
                "quietly show a stale board.")


def _layout(league_names: list[str], default_league: str, poll_ms: int = 5000):
    return html.Div(id="page", className="page", children=[
        nav("draft", default_league),
        html.Div(DRAFT_NOTICE, style={
            "fontFamily": _SANS, "fontSize": "13px", "fontWeight": "600",
            "color": "#ef4444", "border": "1px solid #ef4444",
            "borderRadius": "6px", "padding": "10px 14px", "margin": "0 0 12px",
        }),
        # DOM order IS the grid order: brand, clock, league. The clock sits in
        # the centre track, which is where the eye goes first on the clock.
        html.Header(className="topbar", children=[
            html.Div(className="topbar__brand", children=[
                # Literal path: Dash serves ffhelper/assets/ at /assets/ and
                # this app never reconfigures assets_url_path.
                html.Img(src="/assets/logo.png", className="topbar__logo",
                         alt="FFHelper"),
                html.Span("FFHelper"),
            ]),
            html.Pre(id="clock", className="topbar__clock"),
            html.Div(className="topbar__league", children=[
                dcc.Dropdown(id="league", options=league_names,
                             value=default_league, clearable=False),
            ]),
        ]),
        html.Pre(id="banners"),
        html.Div(className="grid", children=[
            html.Main(className="col-main", children=[
                html.Div(className="card", children=[
                    html.Div(className="controls", children=[
                        dcc.RadioItems(
                            id="pos", value="ALL", inline=True,
                            options=["ALL", "FLEX", "QB", "RB", "WR", "TE", "K", "DEF"]),
                        dcc.Input(id="search", type="text",
                                  placeholder="search name", debounce=False),
                    ]),
                ]),
                html.Div(className="card card--flush board-card", children=[
                    dash_table.DataTable(
                        id="board", columns=COLUMNS, data=[], cell_selectable=True,
                        style_as_list_view=True,
                        style_cell=_TABLE_CELL,
                        style_header=_TABLE_HEADER,
                        style_cell_conditional=[
                            {"if": {"column_id": c}, "textAlign": "right"}
                            for c in _NUMERIC_COLUMNS
                        ],
                        style_table={"overflowX": "auto"},
                    ),
                ]),
            ]),
            html.Aside(className="col-side", children=[
                html.Div(className="card", children=[
                    html.P("Roster", className="card__title"),
                    html.Pre(id="roster"),
                ]),
                html.Div(className="card", children=[
                    html.P("Actions", className="card__title"),
                    html.Div(className="actions", children=[
                        html.Button("undo", id="undo", n_clicks=0),
                        html.Button("toggle 'mine' on selected", id="override",
                                    n_clicks=0),
                    ]),
                    html.Pre(id="status"),
                ]),
            ]),
        ]),
        dcc.Store(id="last_marked"),
        dcc.Interval(id="tick", interval=poll_ms),
    ])


def _register_callbacks(app, leagues, tunables, cache):
    @app.callback(
        Output("board", "data"), Output("board", "style_data_conditional"),
        Output("banners", "children"), Output("clock", "children"),
        Output("roster", "children"), Output("page", "className"),
        Output("override", "style"),
        Input("tick", "n_intervals"), Input("league", "value"),
        Input("pos", "value"), Input("search", "value"),
    )
    def _refresh(_n, league_name, position, query):
        league = get_league(leagues, league_name)
        players, settings, feed, has_feed = cache(league)
        state, stale = read_state(league, tunables, players, settings, feed, has_feed)
        # Build wide, filter, THEN trim. Filtering a 40-row slice would show
        # three kickers when K is selected, because the top 40 rows are almost
        # all skill players.
        rows = filter_rows(
            board_rows(state, limit=200,
                       divergence_flag_slots=tunables.divergence_flag_slots),
            position, query,
        )[:40]
        # All three match by filter_query and target different column_ids, so
        # none of them contend for the same declaration.
        return (
            rows, POS_STYLES + TIER_STYLES + CLASH_STYLES,
            "\n".join(banner_lines(state, stale, players)),
            clock_line(state, league, settings.num_teams),
            "\n".join(f"{label:<5} {filled or '(empty)'}"
                      for label, filled in roster_slots_view(
                          state.my_roster, settings.roster_slots,
                          bench_slots=max(0, settings.rounds
                                          - sum(settings.roster_slots.values())))),
            "page page--live" if is_on_the_clock(state, league, settings.num_teams)
            else "page",
            # The override corrects SEAT-DERIVED attribution, which a league
            # with a feed never uses: the pick's own draft_slot says who took
            # whom and cannot drift. Undo stays on BOTH -- it is the only
            # recovery from a misclick, which unions into `drafted` and quietly
            # removes a player who is in fact still available.
            {"display": "none"} if has_feed else {},
        )

    @app.callback(
        Output("status", "children"), Output("tick", "n_intervals"),
        Output("board", "active_cell"), Output("last_marked", "data"),
        Input("board", "active_cell"), Input("undo", "n_clicks"),
        Input("override", "n_clicks"),
        dash.State("board", "data"), dash.State("league", "value"),
        dash.State("tick", "n_intervals"), dash.State("last_marked", "data"),
        prevent_initial_call=True,
    )
    def _write(active_cell, _undo_clicks, _override_clicks, rows, league_name,
               n, last_marked):
        league = get_league(leagues, league_name)
        path = _draft_log_path(league)
        trigger = dash.callback_context.triggered_id
        try:
            if trigger == "undo":
                status = apply_undo(path)
            elif trigger == "override" and last_marked:
                # The player just entered, NOT the live selection: the selection
                # is cleared after every click (see below), so reading it here
                # would leave the override permanently inert.
                state, _a, _s = _restore_marks(path)
                status = apply_override(path, last_marked,
                                        mine=last_marked not in state.mine)
            elif trigger == "board" and active_cell and rows:
                # Resolve the click through the row's id, never its name.
                last_marked = rows[active_cell["row"]]["id"]
                status = apply_click(path, last_marked)
            else:
                status = ""
        except Exception as exc:                      # noqa: BLE001 - never fatal
            log.error("write failed: %s", exc, exc_info=True)
            status = f"could not apply that -- {exc}"
        # Bump the tick so the board redraws immediately rather than waiting for
        # the poll interval. Entry latency must never be paced by the network:
        # that coupling is what abandoned mock run 1 at 12 000 ms per keystroke.
        # active_cell is returned as None so the NEXT click on the same cell is
        # still a change and still fires. Dash only calls a callback when a prop
        # changes, so without this, re-clicking the highlighted cell silently
        # does nothing -- reported live as "sometimes clicks don't register".
        return status, (n or 0) + 1, None, last_marked

    @app.callback(
        Output("trades-content", "children"),
        Input("trades-run", "n_clicks"),
        dash.State("trades-league", "data"),
    )
    def _run_trades(n_clicks, league_name):
        if n_clicks is None:
            # Dash fires every callback once at page load, using each
            # Input's value at that moment -- the button's n_clicks stays
            # unset (None) until it is actually clicked, because the layout
            # never gives it a starting n_clicks=0 the way "undo" does above.
            # This is the entire guard against an accidental navigation
            # costing the ~330s sweep (pipeline.py's build_trades ponytail
            # note): the state is returned unchanged.
            return dash.no_update
        # league_name comes from the State store trades_landing wrote, not
        # from a default -- a callback wired to n_clicks alone carries no
        # league, and get_league(leagues, DEFAULT) would silently sweep the
        # wrong one.
        league = get_league(leagues, league_name)
        view = pipeline.build_trades(league, tunables, progress=None)
        return trades_children(view)

    # All three exposed for direct testing: a callback sealed inside this
    # function is code no test can reach, and untestable code is untested code.
    return _refresh, _write, _run_trades


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Dash draft board")
    ap.add_argument("--league", required=True)
    ap.add_argument("--port", type=int, default=8050)
    args = ap.parse_args(argv)

    leagues, tunables = load_config(CONFIG_PATH)
    names = [lg.name for lg in leagues]
    get_league(leagues, args.league)                  # fail fast on a bad name
    DRAFT_LOG_DIR.mkdir(exist_ok=True)

    # ONE PROCESS AT A TIME. Said at startup, not only in the docstring: the
    # CLI replays the journal once, at ITS startup, so a CLI left running
    # alongside this app will quietly show a stale board.
    print("ffhelper web board. Do NOT run `ffhelper.cli run` for this league at "
          "the same time -- stop one before starting the other.")

    loaded: dict[str, tuple] = {}

    def cache(league: League):
        """Cold start once per league. The POOL is cached; the board is not."""
        if league.name not in loaded:
            players, settings = load_board_inputs(league, tunables)
            feed, has_feed = _select_feed(league, settings)
            # Seed the staleness clock at load, so the FIRST failed poll reports
            # real elapsed time instead of 0 and hides a feed that never worked.
            _LAST_OK[league.name] = time.time()
            loaded[league.name] = (players, settings, feed, has_feed)
        return loaded[league.name]

    app = build_app(names, args.league,
                    poll_interval_ms(tunables, get_league(leagues, args.league).platform))
    _register_callbacks(app, leagues, tunables, cache)
    app.run(port=args.port)
    return 0


# NO module-level `server` for gunicorn. It was in the design as a "free line
# that keeps hosting open", and it is not free: gunicorn imports this module and
# never calls main(), so a `server` populated inside main() is always None -- a
# decorative hook that fails the moment it is used. The real retrofit is to build
# the app at import time, which means league selection has to move out of argv
# and into config or the environment. That is a genuine change, and pretending
# otherwise with a dead global is worse than admitting it. See the spec's
# "Hosting, later".


if __name__ == "__main__":
    sys.exit(main())
