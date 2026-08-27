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

import dash
from dash import Input, Output, dash_table, dcc, html

from ffhelper.board import (
    BoardState, auto_mine, board_state, explicit_not_mine, marks_in_entry_order,
)
from ffhelper.cli import (
    DRAFT_LOG_DIR, ROOT, _draft_log_path, _restore_marks, _select_feed,
    load_board_inputs,
)
from ffhelper.config import League, Tunables, get_league, load_config
from ffhelper.data import Player
from ffhelper.value import is_bench_only, next_pick_number

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
    rows = []
    for i, r in enumerate(state.board[:limit], 1):
        flags = []
        if r.player.injury_status:
            flags.append(r.player.injury_status)
        # None means the market never priced him -- a third of the pool. No
        # opinion is not agreement, so no flag and a dash, never a 0.
        if r.divergence is not None and abs(r.divergence) >= divergence_flag_slots:
            flags.append(f"{'MODEL' if r.divergence > 0 else 'MARKET'}+{abs(r.divergence)}")
        if r.player.bye:
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


def banner_lines(
    state: BoardState, stale_seconds: float | None, players: dict[str, Player],
) -> list[str]:
    """Degrade, never fabricate: every degraded condition says so on screen."""
    lines: list[str] = []
    if stale_seconds is None:
        lines.append("MANUAL MODE: no pick feed -- picks are entered by hand only")
    elif stale_seconds > 15:
        lines.append(f"!! FEED STALE {stale_seconds:.0f}s -- board may be out of date")
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


def clock_line(state: BoardState, league: League, num_teams: int) -> str:
    if not league.draft_slot:
        return f"pick {state.current_pick}"
    nxt = next_pick_number(state.current_pick, league.draft_slot, num_teams)
    # next_pick_number is strictly-after, so ask from one pick earlier and see
    # whether it lands here.
    if next_pick_number(state.current_pick - 1, league.draft_slot, num_teams) == state.current_pick:
        return (f">>> PICK {state.current_pick} IS YOURS -- YOU ARE ON THE CLOCK <<<"
                f"   (next after this: {nxt})")
    return (f"pick {state.current_pick}   your next pick: {nxt} "
            f"({nxt - state.current_pick} away)")


# Poll bookkeeping only -- NOT draft state. The board itself is rebuilt from the
# journal every tick and nothing about who was drafted lives in this process.
_LAST_OK: dict[str, float] = {}


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
        if has_feed:
            stale_seconds = time.time() - _LAST_OK.get(league.name, time.time())
    else:
        if has_feed:
            _LAST_OK[league.name] = time.time()
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


def build_app(league_names: list[str], default_league: str) -> dash.Dash:
    app = dash.Dash(__name__, use_pages=True, pages_folder="")
    dash.register_page("board", path="/", layout=_layout(league_names, default_league))
    app.layout = html.Div([dash.page_container])
    return app


def _layout(league_names: list[str], default_league: str):
    return html.Div([
        dcc.Dropdown(id="league", options=league_names, value=default_league,
                     clearable=False, style={"width": "20rem"}),
        html.Pre(id="banners"),
        html.Pre(id="clock"),
        dash_table.DataTable(
            id="board", columns=COLUMNS, data=[], cell_selectable=True,
            style_cell={"fontFamily": "monospace", "textAlign": "left"},
        ),
        html.Button("undo", id="undo", n_clicks=0),
        html.Button("toggle 'mine' on selected", id="override", n_clicks=0),
        html.Pre(id="status"),
        dcc.Interval(id="tick", interval=5000),
    ])


def _register_callbacks(app, leagues, tunables, cache):
    @app.callback(
        Output("board", "data"), Output("banners", "children"),
        Output("clock", "children"),
        Input("tick", "n_intervals"), Input("league", "value"),
    )
    def _refresh(_n, league_name):
        league = get_league(leagues, league_name)
        players, settings, feed, has_feed = cache(league)
        state, stale = read_state(league, tunables, players, settings, feed, has_feed)
        return (
            board_rows(state, limit=40,
                       divergence_flag_slots=tunables.divergence_flag_slots),
            "\n".join(banner_lines(state, stale, players)),
            clock_line(state, league, settings.num_teams),
        )

    @app.callback(
        Output("status", "children"), Output("tick", "n_intervals"),
        Input("board", "active_cell"), Input("undo", "n_clicks"),
        Input("override", "n_clicks"),
        dash.State("board", "data"), dash.State("league", "value"),
        dash.State("tick", "n_intervals"),
        prevent_initial_call=True,
    )
    def _write(active_cell, _undo_clicks, _override_clicks, rows, league_name, n):
        league = get_league(leagues, league_name)
        path = _draft_log_path(league)
        trigger = dash.callback_context.triggered_id
        try:
            if trigger == "undo":
                status = apply_undo(path)
            elif trigger == "override" and active_cell and rows:
                pid = rows[active_cell["row"]]["id"]
                state, _a, _s = _restore_marks(path)
                status = apply_override(path, pid, mine=pid not in state.mine)
            elif active_cell and rows:
                # Resolve the click through the row's id, never its name.
                status = apply_click(path, rows[active_cell["row"]]["id"])
            else:
                status = ""
        except Exception as exc:                      # noqa: BLE001 - never fatal
            log.error("write failed: %s", exc, exc_info=True)
            status = f"could not apply that -- {exc}"
        # Bump the tick so the board redraws immediately rather than waiting for
        # the poll interval. Entry latency must never be paced by the network:
        # that coupling is what abandoned mock run 1 at 12 000 ms per keystroke.
        return status, (n or 0) + 1

    return _write  # exposed for direct testing -- dash strips the app.callback
                   # wiring before returning, so this is the raw callable.


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

    app = build_app(names, args.league)
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
