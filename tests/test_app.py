import sqlite3
import time
from dataclasses import dataclass

import ffhelper.app as app
from ffhelper import store
from ffhelper.app import (
    banner_lines, board_rows, clock_line, read_state, snapshot_recorded, status_strip,
)
from ffhelper.board import board_state
from ffhelper.config import League, Tunables
from ffhelper.data import LeagueSettings, Player


@dataclass
class FakePick:
    sleeper_id: str
    pick_no: int
    draft_slot: int | None


class FakeFeed:
    """No network, no mocking library -- a feed is just something with get_picks()."""

    def __init__(self, picks=None, raise_error=False):
        self._picks = picks if picks is not None else []
        self._raise_error = raise_error

    def get_picks(self):
        if self._raise_error:
            raise RuntimeError("feed down")
        return self._picks


def _pool(n: int = 40) -> dict[str, Player]:
    return {
        str(i): Player(
            sleeper_id=str(i), name=f"Player {i}",
            position=["QB", "RB", "WR", "TE", "K", "DEF"][i % 6], team="KC",
            proj_pts=310.2 - i * 4.1, adp=float(i) + 1.4, adp_stdev=5.9 + i * 0.13,
            bye=(i % 14) + 1,
        )
        for i in range(1, n + 1)
    }


def _settings() -> LeagueSettings:
    return LeagueSettings(
        num_teams=12, scoring={"rec": 1.0},
        roster_slots={"QB": 1, "RB": 2, "WR": 2, "TE": 1, "FLEX": 2, "K": 1, "DEF": 1},
        rounds=15,
    )


def _state(picks=(), gone=frozenset(), mine=frozenset(), players=None):
    players = players or _pool()
    return board_state(players, list(picks), set(gone), set(mine), _settings(),
                       League(name="t", platform="sleeper", league_id="1", draft_slot=5),
                       Tunables()), players


def test_board_rows_carry_the_player_id_so_a_click_never_matches_on_name():
    # Non-negotiable #1: load-bearing joins are on integer ids. A click that
    # resolved a row back to a player by NAME would reintroduce the exact
    # ambiguity (Bijan vs Brian Robinson) the whole design forbids.
    #
    # IDs here are deliberately NOT derivable from the names (unlike _pool(),
    # where id str(i) and name f"Player {i}" share the same index and a
    # name-for-id swap in app.py would still leave every row "truthy and
    # unique"). Asserting the id against a KNOWN value is what makes the test
    # fail if app.py ever reads r.player.name instead of r.player.sleeper_id.
    players = {
        "4017": Player(sleeper_id="4017", name="Bijan Robinson", position="RB",
                       team="ATL", proj_pts=300.0, adp=3.0, adp_stdev=4.0, bye=5),
        "9911": Player(sleeper_id="9911", name="Brian Robinson", position="RB",
                       team="WAS", proj_pts=180.0, adp=90.0, adp_stdev=8.0, bye=14),
    }
    state, _ = _state(players=players)
    rows = board_rows(state, limit=2, divergence_flag_slots=10)
    by_name = {r["player"]: r["id"] for r in rows}
    assert by_name["Bijan Robinson"] == "4017"
    assert by_name["Brian Robinson"] == "9911"


def test_board_rows_respect_the_limit_and_are_ranked_from_one():
    state, _ = _state()
    rows = board_rows(state, limit=7, divergence_flag_slots=10)
    assert len(rows) == 7
    assert [r["rank"] for r in rows] == list(range(1, 8))


def test_unpriced_players_show_a_dash_not_a_fabricated_zero():
    # divergence is None for a player the market never priced -- a third of the
    # pool. No opinion is not agreement.
    players = _pool()
    for p in players.values():
        p.adp = 999.0
    state, _ = _state(players=players)
    rows = board_rows(state, limit=5, divergence_flag_slots=10)
    assert all(r["div"] == "-" for r in rows)


def test_a_dead_feed_produces_a_stale_banner():
    state, players = _state()
    lines = banner_lines(state, stale_seconds=42.0, players=players)
    assert any("STALE" in line for line in lines)


def test_no_feed_says_so_rather_than_showing_a_staleness_clock():
    state, players = _state()
    lines = banner_lines(state, stale_seconds=None, players=players)
    assert any("MANUAL MODE" in line for line in lines)
    assert not any("STALE" in line for line in lines)


def test_an_overruled_claim_raises_a_standing_banner_naming_the_player():
    players = _pool()
    picks = [FakePick("20", 1, 9)]
    state, players = _state(picks=picks, gone={"20"}, mine={"20"}, players=players)
    lines = banner_lines(state, stale_seconds=None, players=players)
    assert any("CLAIM OVERRULED" in line and "Player 20" in line for line in lines)


# --- read_state: the safety property (a feed that never worked must not
# render as healthy) lives entirely in this function, and nothing above
# exercises it -- every test above hand-supplies stale_seconds. ---

def test_read_state_with_no_feed_stays_stale_none_even_when_get_picks_returns(
    monkeypatch, tmp_path,
):
    # Yahoo has no feed at all. That is a different statement from "the feed
    # has not answered recently" and must never collapse into a number, even
    # if whatever `feed` object was wired up happens to return an empty list.
    monkeypatch.setattr(app, "_draft_log_path", lambda league: tmp_path / "j.jsonl")
    league = League(name="rs-no-feed", platform="yahoo", league_id="1", draft_slot=5)
    state, stale = read_state(league, Tunables(), _pool(), _settings(),
                              FakeFeed(picks=[]), has_feed=False)
    assert stale is None


def test_read_state_successful_poll_reports_zero_stale(monkeypatch, tmp_path):
    monkeypatch.setattr(app, "_draft_log_path", lambda league: tmp_path / "j.jsonl")
    league = League(name="rs-ok", platform="sleeper", league_id="1", draft_slot=5)
    state, stale = read_state(league, Tunables(), _pool(), _settings(),
                              FakeFeed(picks=[]), has_feed=True)
    assert stale == 0.0


def test_read_state_failed_poll_reports_real_elapsed_never_a_fabricated_zero(
    monkeypatch, tmp_path,
):
    # The "feed that never worked" case, and the one that matters most: a
    # dead feed must show a real, growing staleness number, never 0.0 (which
    # reads as "just synced") and never None (which reads as "no feed at
    # all" -- also false, this league HAS a feed, it is just down).
    monkeypatch.setattr(app, "_draft_log_path", lambda league: tmp_path / "j.jsonl")
    league = League(name="rs-dead", platform="sleeper", league_id="1", draft_slot=5)
    # Mirrors what main()'s cache() does at load, before the first poll ever
    # runs: seed the clock so a feed that has never succeeded still reports
    # real elapsed time instead of "now minus now".
    app._LAST_OK[league.name] = time.time() - 5.0
    state, stale = read_state(league, Tunables(), _pool(), _settings(),
                              FakeFeed(raise_error=True), has_feed=True)
    assert stale is not None
    assert stale != 0.0
    assert stale >= 4.5


# --- clock_line: the ON THE CLOCK banner. Task 6 makes this the drift
# detector for seat-based roster attribution, so its snake-position logic
# needs coverage now, not after that lands on top of it. ---

def test_clock_line_says_yours_only_at_the_seats_snake_pick():
    # slot 5, 12 teams -> this seat's picks are 5, 8, 29, 32, ... The banner
    # must fire exactly on pick 5 and on neither neighbour.
    league = League(name="clock-test", platform="sleeper", league_id="1", draft_slot=5)
    settings = _settings()
    for gone_count, expect_yours in [(3, False), (4, True), (5, False)]:
        gone = {str(i) for i in range(1, gone_count + 1)}
        state = board_state(_pool(), [], gone, set(), settings, league, Tunables())
        assert state.current_pick == gone_count + 1
        line = clock_line(state, league, settings.num_teams)
        assert ("YOURS" in line) == expect_yours, (state.current_pick, line)


# --- Task 4: click-to-mark and undo, journalled for CLI handover ---

import json

from ffhelper.app import apply_click, apply_undo
from ffhelper.cli import _restore_marks


def test_a_click_appends_one_mark_op_to_the_journal(tmp_path):
    path = tmp_path / "log.jsonl"
    apply_click(path, "42")
    ops = [json.loads(line) for line in path.read_text().splitlines()]
    assert ops == [{"op": "mark", "id": "42", "mine": False}]


def test_clicking_the_same_player_twice_is_idempotent(tmp_path):
    path = tmp_path / "log.jsonl"
    apply_click(path, "42")
    apply_click(path, "42")
    state, _applied, _skipped = _restore_marks(path)
    assert state.drafted == {"42"}


def test_undo_takes_back_the_last_mark(tmp_path):
    path = tmp_path / "log.jsonl"
    apply_click(path, "42")
    apply_click(path, "43")
    apply_undo(path)
    state, _applied, _skipped = _restore_marks(path)
    assert state.drafted == {"42"}


def test_undo_is_journalled_so_a_restart_does_not_resurrect_the_mark(tmp_path):
    # An unlogged undo replays away: the restart brings back a pick the user
    # had already taken back, and the pool goes quietly wrong.
    path = tmp_path / "log.jsonl"
    apply_click(path, "42")
    apply_undo(path)
    ops = [json.loads(line)["op"] for line in path.read_text().splitlines()]
    assert ops == ["mark", "undo"]


def test_a_click_survives_a_process_restart(tmp_path):
    # The whole point of the journal-as-database model, and the CLI handover.
    path = tmp_path / "log.jsonl"
    apply_click(path, "42")
    apply_click(path, "7")
    state, applied, skipped = _restore_marks(path)
    assert state.drafted == {"42", "7"}
    assert (applied, skipped) == (2, 0)


# --- the _write callback dispatch: resolve-by-id and the redraw bump ---

import dash as _dash  # local alias -- test_app.py otherwise has no dash import


def _make_write(monkeypatch, tmp_path, league_name="write-test"):
    """Build a bare app, register callbacks, hand back the raw _write
    callable plus the journal path it will write to."""
    path = tmp_path / "log.jsonl"
    monkeypatch.setattr(app, "_draft_log_path", lambda league: path)
    league = League(name=league_name, platform="sleeper", league_id="1")
    _refresh, write = app._register_callbacks(
        _dash.Dash(__name__, suppress_callback_exceptions=True),
        [league], Tunables(), lambda lg: None,
    )
    return write, path


def test_click_resolves_through_the_row_id_never_the_name(monkeypatch, tmp_path):
    # id cannot be derived from the display name -- this is the Bijan/Brian
    # Robinson trap: a click resolved by row position or by name would mark
    # (or fail to mark) the wrong player.
    write, path = _make_write(monkeypatch, tmp_path)
    monkeypatch.setattr(_dash.callback_context.__class__, "triggered_id",
                         property(lambda self: "board"))
    rows = [{"id": "4017", "player": "Bijan Robinson"}]
    write({"row": 0, "column": 0}, 0, 0, rows, "write-test", 0, None)
    ops = [json.loads(line) for line in path.read_text().splitlines()]
    assert ops == [{"op": "mark", "id": "4017", "mine": False}]


def test_a_successful_write_bumps_the_tick_for_an_immediate_redraw(monkeypatch, tmp_path):
    # Entry latency must never be paced by the poll interval -- see Session
    # log 2026-08-26 (Run 1's 12 000ms-per-keystroke abandonment).
    write, _path = _make_write(monkeypatch, tmp_path, league_name="write-test2")
    monkeypatch.setattr(_dash.callback_context.__class__, "triggered_id",
                         property(lambda self: "undo"))
    _status, n_after, _a, _l = write(None, 1, 0, [], "write-test2", 3, None)
    assert n_after == 4


# --- Task 6: seat-based attribution and the explicit override ---

from ffhelper.app import apply_override
from ffhelper.board import auto_mine, marks_in_entry_order


def test_the_seats_own_picks_land_in_my_roster_without_being_typed(tmp_path):
    path = tmp_path / "log.jsonl"
    for i in range(1, 25):                            # picks 1..24, seat 5 owns 5 and 20
        apply_click(path, str(i))
    order = marks_in_entry_order(path)
    assert auto_mine(order, seat=5, num_teams=12) == {"5", "20"}


def test_an_override_marks_a_player_as_yours_explicitly(tmp_path):
    path = tmp_path / "log.jsonl"
    apply_click(path, "42")
    apply_override(path, "42", mine=True)
    state, _applied, _skipped = _restore_marks(path)
    assert state.mine == {"42"}
    assert state.drafted == {"42"}


def test_an_override_can_take_a_claim_back_without_undrafting_the_player(tmp_path):
    # He really is gone -- just not to you. Removing him from `drafted` would
    # put a drafted player back on the board.
    path = tmp_path / "log.jsonl"
    apply_click(path, "42")
    apply_override(path, "42", mine=True)
    apply_override(path, "42", mine=False)
    state, _applied, _skipped = _restore_marks(path)
    assert state.mine == set()
    assert state.drafted == {"42"}


# --- Task 6, fix round 1: the review's Critical -- `derived` has no memory of
# an override, so `mine=False` must be subtracted back out on EVERY
# `read_state` call, not just honoured once. These go through `read_state`
# itself (not `apply_override`/`board.explicit_not_mine` in isolation),
# because the bug was in the composition, not in either piece alone.
#
# id/name fixtures deliberately non-derivable from each other -- reusing
# `str(i)`/`f"Player {i}"` would pass even if the composition read the wrong
# field.

_OVERRIDE_ID = "4017"
_OVERRIDE_PLAYERS = {
    _OVERRIDE_ID: Player(sleeper_id=_OVERRIDE_ID, name="Bijan Robinson", position="RB",
                         team="ATL", proj_pts=300.0, adp=1.0, adp_stdev=4.0, bye=5),
}


def _override_league(name: str) -> League:
    # draft_slot=1 with _settings()'s 12 teams: pick 1 is seat 1's own turn --
    # the simplest snake position to derive from.
    return League(name=name, platform="sleeper", league_id="1", draft_slot=1)


def test_a_not_mine_override_survives_a_second_read_state_call(monkeypatch, tmp_path):
    # THE regression test. Before the fix, `derived` (recomputed fresh every
    # call from pick position alone) silently re-added the player within one
    # tick, because the union `mark_state.mine | derived` can only ever ADD.
    path = tmp_path / "log.jsonl"
    monkeypatch.setattr(app, "_draft_log_path", lambda league: path)
    league = _override_league("override-not-mine")
    settings = _settings()
    apply_click(path, _OVERRIDE_ID)                # pick 1 -- auto-derived as seat 1's
    apply_override(path, _OVERRIDE_ID, mine=False)  # explicit correction: not mine

    for _ in range(2):                              # TWO calls: the bug only showed on the 2nd
        state, _stale = read_state(league, Tunables(), _OVERRIDE_PLAYERS, settings,
                                   FakeFeed(), has_feed=False)
        assert _OVERRIDE_ID not in {p.sleeper_id for p in state.my_roster}
        assert _OVERRIDE_ID in state.drafted        # never un-drafted


def test_a_mine_override_still_wins_over_derivation(monkeypatch, tmp_path):
    path = tmp_path / "log.jsonl"
    monkeypatch.setattr(app, "_draft_log_path", lambda league: path)
    league = _override_league("override-mine")
    settings = _settings()
    apply_click(path, _OVERRIDE_ID)
    apply_override(path, _OVERRIDE_ID, mine=True)

    state, _stale = read_state(league, Tunables(), _OVERRIDE_PLAYERS, settings,
                               FakeFeed(), has_feed=False)
    assert _OVERRIDE_ID in {p.sleeper_id for p in state.my_roster}
    assert _OVERRIDE_ID in state.drafted


def test_overriding_back_to_mine_after_not_mine_restores_the_roster(monkeypatch, tmp_path):
    path = tmp_path / "log.jsonl"
    monkeypatch.setattr(app, "_draft_log_path", lambda league: path)
    league = _override_league("override-back-to-mine")
    settings = _settings()
    apply_click(path, _OVERRIDE_ID)
    apply_override(path, _OVERRIDE_ID, mine=False)
    apply_override(path, _OVERRIDE_ID, mine=True)   # changed their mind back

    state, _stale = read_state(league, Tunables(), _OVERRIDE_PLAYERS, settings,
                               FakeFeed(), has_feed=False)
    assert _OVERRIDE_ID in {p.sleeper_id for p in state.my_roster}
    assert _OVERRIDE_ID in state.drafted


def test_override_button_flips_mine_through_the_row_id(monkeypatch, tmp_path):
    # Mirrors the existing "board"/"undo" direct-call tests -- the reviewer's
    # Minor finding was that the override branch of `_write` had no coverage
    # at all.
    write, path = _make_write(monkeypatch, tmp_path, league_name="write-override")
    apply_click(path, "4017")                       # already drafted, not yet claimed
    monkeypatch.setattr(_dash.callback_context.__class__, "triggered_id",
                         property(lambda self: "override"))
    rows = [{"id": "4017", "player": "Bijan Robinson"}]
    # The override acts on the last-marked id carried in the Store, since the
    # cell selection is cleared after every click.
    status, _n, _a, _l = write(None, 0, 1, rows, "write-override", 0, "4017")
    assert status == "4017 is yours"
    ops = [json.loads(line) for line in path.read_text().splitlines()]
    assert ops[-1] == {"op": "mark", "id": "4017", "mine": True}


# --- Task 7: tier bands, position filter, search ---

from ffhelper.app import filter_rows


def test_the_tier_badge_is_coloured_by_its_own_position():
    # TODO.md section 15: no position ranks its own top 12 better than ~+0.35
    # Spearman. The gap between tiers is real; the order inside one is close to
    # noise. The badge is what makes same-tier players read as interchangeable.
    #
    # `tier` is a PER-POSITION column, so RB tier 1 and WR tier 1 are not the
    # same claim. The badge separates them by COLOUR -- which is the whole
    # reason it replaced alternating bands, that could only group adjacent rows
    # and so said RB 4 and RB 5 were one group whenever a WR sat between them.
    by_pos = {s["if"]["filter_query"]: s for s in app.TIER_STYLES}
    assert len(by_pos) == len(app.POSITION_COLORS)
    for pos, colour in app.POSITION_COLORS.items():
        style = by_pos[f'{{pos}} = "{pos}"']
        assert style["if"]["column_id"] == "tier"
        assert style["color"] == colour
    # Two positions on the same tier number must never look the same.
    assert by_pos['{pos} = "RB"']["color"] != by_pos['{pos} = "WR"']["color"]


def test_filter_rows_by_position():
    rows = [{"player": "A", "pos": "QB"}, {"player": "B", "pos": "RB"}]
    assert filter_rows(rows, "RB", "") == [{"player": "B", "pos": "RB"}]


def test_filter_rows_all_is_a_passthrough():
    rows = [{"player": "A", "pos": "QB"}, {"player": "B", "pos": "RB"}]
    assert filter_rows(rows, "ALL", "") == rows


def test_search_is_case_insensitive_and_partial():
    rows = [{"player": "Ja'Marr Chase", "pos": "WR"}, {"player": "Bijan Robinson", "pos": "RB"}]
    assert filter_rows(rows, "ALL", "robin") == [rows[1]]
    assert filter_rows(rows, "ALL", "CHASE") == [rows[0]]


def test_search_and_position_filter_compose():
    rows = [{"player": "Bijan Robinson", "pos": "RB"},
            {"player": "Brian Robinson", "pos": "RB"},
            {"player": "Demario Douglas", "pos": "WR"}]
    assert filter_rows(rows, "WR", "robin") == []


def test_filter_then_trim_shows_a_full_screen_of_the_filtered_position():
    # The brief's core hazard: filtering a 40-row SLICE of the board would show
    # at most a handful of kickers, because the top 40 rows are almost all
    # skill players. The 200-row list must be built and filtered BEFORE the
    # 40-row display trim, not the other way around.
    wide = ([{"player": f"Skill {i}", "pos": "WR"} for i in range(190)]
            + [{"player": f"Kicker {i}", "pos": "K"} for i in range(10)])
    filtered = filter_rows(wide, "K", "")[:40]
    assert len(filtered) == 10
    assert all(r["pos"] == "K" for r in filtered)


def _make_refresh(monkeypatch, tmp_path, players, draft_slot=5, has_feed=True):
    """Register callbacks against a fixed pool and hand back the raw _refresh."""
    monkeypatch.setattr(app, "_draft_log_path", lambda league: tmp_path / "log.jsonl")
    league = League(name="refresh-test", platform="sleeper", league_id="1",
                    draft_slot=draft_slot)
    refresh, _write = app._register_callbacks(
        _dash.Dash(__name__, suppress_callback_exceptions=True),
        [league], Tunables(),
        lambda lg: (players, _settings(), FakeFeed(), has_feed),
    )
    return refresh


def _deep_pool() -> dict[str, Player]:
    """Skill players above every kicker, which is what a real board looks like."""
    out = {}
    for i in range(1, 121):
        out[str(i)] = Player(
            sleeper_id=str(i), name=f"Skill {i}",
            position=["QB", "RB", "WR", "TE"][i % 4], team="KC",
            proj_pts=340.0 - i * 1.5, adp=float(i) + 1.0, adp_stdev=6.0,
        )
    for i in range(200, 216):
        out[str(i)] = Player(
            sleeper_id=str(i), name=f"Kicker {i}", position="K", team="KC",
            proj_pts=140.0 - (i - 200) * 0.9, adp=float(i), adp_stdev=6.0,
        )
    return out


def test_refresh_filters_the_wide_board_before_trimming_to_the_screen(monkeypatch, tmp_path):
    # The hazard the 200/40 split exists for: filtering a 40-row SLICE would
    # show only the kickers that already cracked the top 40, which is almost
    # none. Reaching the callback is the point -- asserting it on a hand-built
    # list would pass against a build that filters after trimming.
    players = _deep_pool()
    refresh = _make_refresh(monkeypatch, tmp_path, players)

    unfiltered, *_rest = refresh(0, "refresh-test", "ALL", "")
    in_top_40 = sum(1 for r in unfiltered if r["pos"] == "K")

    kickers, *_rest = refresh(0, "refresh-test", "K", "")
    assert all(r["pos"] == "K" for r in kickers)
    assert len(kickers) == 16
    assert len(kickers) > in_top_40      # fails if the trim ran before the filter


def test_refresh_styles_match_by_query_never_by_row_position(monkeypatch, tmp_path):
    # The old alternating bands keyed on {"row_index": n}, so styling the
    # UNFILTERED list painted the wrong rows the moment a filter was on. Every
    # style is now a filter_query against the row's own data, which makes that
    # whole class of bug unreachable rather than merely tested for.
    players = _deep_pool()
    refresh = _make_refresh(monkeypatch, tmp_path, players)
    rows, styles, *_rest = refresh(0, "refresh-test", "QB", "")
    assert rows
    assert styles
    assert not any("row_index" in s["if"] for s in styles)
    assert all("filter_query" in s["if"] for s in styles)


def test_refresh_ships_the_position_and_tier_styles(monkeypatch, tmp_path):
    # Asserting this on POS_STYLES directly would pass against a callback that
    # never sends them, which is the whole defect. Reach it through _refresh.
    players = _deep_pool()
    refresh = _make_refresh(monkeypatch, tmp_path, players)
    rows, styles, *_rest = refresh(0, "refresh-test", "ALL", "")

    # Keyed on (query, COLUMN): POS_STYLES and TIER_STYLES share the same
    # filter_query, so a dict keyed on the query alone collapses them and the
    # assertion passes even when POS_STYLES is dropped entirely. mutate.py
    # caught exactly that -- the first version of this test proved nothing.
    keys = {(s["if"]["filter_query"], s["if"].get("column_id")) for s in styles}
    assert keys, "no conditional styles reached the table"
    for pos in {r["pos"] for r in rows}:
        q = f'{{pos}} = "{pos}"'
        assert (q, "pos") in keys, f"{pos}: POS cell colour missing"
        assert (q, "rank") in keys, f"{pos}: row stripe missing"
        assert (q, "tier") in keys, f"{pos}: tier badge missing"
    # Muted, and distinct per position -- a shared colour would say two
    # positions are one category.
    assert len(set(app.POSITION_COLORS.values())) == len(app.POSITION_COLORS)


def test_the_page_reports_live_state_only_at_the_seats_own_pick(monkeypatch, tmp_path):
    # The live class and the clock TEXT read one predicate. If they are ever
    # allowed to drift apart, the page glows on someone else's pick -- the one
    # piece of styling that can actively mislead at the table.
    players = _deep_pool()

    # Indexed, not tail-unpacked: outputs get appended over time and a
    # positional unpack silently starts reading the wrong one.
    CLOCK, PAGE_CLASS = 3, 5
    mine = _make_refresh(monkeypatch, tmp_path, players, draft_slot=1)
    out = mine(0, "refresh-test", "ALL", "")
    clock_mine, cls_mine = out[CLOCK], out[PAGE_CLASS]

    theirs = _make_refresh(monkeypatch, tmp_path, players, draft_slot=5)
    out = theirs(0, "refresh-test", "ALL", "")
    clock_theirs, cls_theirs = out[CLOCK], out[PAGE_CLASS]

    assert "ON THE CLOCK" in clock_mine and "page--live" in cls_mine
    assert "ON THE CLOCK" not in clock_theirs and "page--live" not in cls_theirs


def test_a_bye_clashes_only_with_the_same_position_already_on_your_roster():
    # A bye you already own at this position is a week you start nobody there.
    # Scoped to the SAME position deliberately: a WR sharing your RB's bye is
    # not the problem, and flagging it would make the warning noise.
    players = {
        "1": Player(sleeper_id="1", name="My Back", position="RB", team="CHI",
                    proj_pts=300.0, adp=1.0, adp_stdev=4.0, bye=6),
        "2": Player(sleeper_id="2", name="Same Bye RB", position="RB", team="GB",
                    proj_pts=290.0, adp=2.0, adp_stdev=4.0, bye=6),
        "3": Player(sleeper_id="3", name="Same Bye WR", position="WR", team="GB",
                    proj_pts=280.0, adp=3.0, adp_stdev=4.0, bye=6),
        "4": Player(sleeper_id="4", name="Other Bye RB", position="RB", team="GB",
                    proj_pts=270.0, adp=4.0, adp_stdev=4.0, bye=9),
    }
    # Player 1 is drafted AND claimed, so he is on the roster and off the board.
    state, _ = _state(gone={"1"}, mine={"1"}, players=players)
    assert [p.sleeper_id for p in state.my_roster] == ["1"]

    flags = {r["player"]: r["flags"] for r in
             board_rows(state, limit=10, divergence_flag_slots=10)}
    assert "BYE6 CLASH" in flags["Same Bye RB"]
    assert "CLASH" not in flags["Same Bye WR"] and "bye6" in flags["Same Bye WR"]
    assert "CLASH" not in flags["Other Bye RB"] and "bye9" in flags["Other Bye RB"]


def test_an_empty_roster_clashes_with_nothing():
    # The opening board. Every row shares a bye with something, and none of it
    # matters yet -- a board that opens covered in red warnings is a board you
    # stop reading.
    players = {
        "2": Player(sleeper_id="2", name="A", position="RB", team="GB",
                    proj_pts=290.0, adp=2.0, adp_stdev=4.0, bye=6),
        "3": Player(sleeper_id="3", name="B", position="RB", team="CHI",
                    proj_pts=280.0, adp=3.0, adp_stdev=4.0, bye=6),
    }
    state, _ = _state(players=players)
    assert state.my_roster == []
    rows = board_rows(state, limit=10, divergence_flag_slots=10)
    assert not any("CLASH" in r["flags"] for r in rows)


def test_the_override_is_hidden_when_the_feed_reports_who_drafted_whom(
    monkeypatch, tmp_path,
):
    """The override corrects SEAT-DERIVED attribution, which a league with a
    feed never uses -- the pick's own draft_slot is authoritative and cannot
    drift. On Sleeper it is a dead control.

    Undo is NOT hidden with it, on either league: a misclick unions into
    `drafted` and silently removes a player who is still available, and undo is
    the only way back.
    """
    players = _deep_pool()

    with_feed = _make_refresh(monkeypatch, tmp_path, players, has_feed=True)
    *_head, override_style = with_feed(0, "refresh-test", "ALL", "")
    assert override_style == {"display": "none"}

    without = _make_refresh(monkeypatch, tmp_path, players, has_feed=False)
    *_head, override_style = without(0, "refresh-test", "ALL", "")
    assert override_style != {"display": "none"}

    # The assertions above read a VALUE out of the tuple and cannot see which
    # component it lands on -- mutate.py proved that by retargeting the Output
    # at `undo` with the whole suite still green. Assert the wiring itself, so
    # hiding the one control that recovers a misclick cannot pass unnoticed.
    probe = _dash.Dash(__name__, suppress_callback_exceptions=True)
    app._register_callbacks(
        probe,
        [League(name="refresh-test", platform="sleeper", league_id="1", draft_slot=5)],
        Tunables(), lambda lg: (players, _settings(), FakeFeed(), True))
    wiring = " ".join(probe.callback_map)
    assert "override.style" in wiring
    assert "undo.style" not in wiring, "undo is the only misclick recovery"


def test_only_a_clash_flag_is_styled_red_not_an_ordinary_bye():
    # The style matches CASE: informational flags are `bye6`, a warning is
    # `BYE6 CLASH`. If it ever matched lowercase too, every row on the board
    # would turn red and the warning would carry no information at all.
    assert len(app.CLASH_STYLES) == 1
    q = app.CLASH_STYLES[0]["if"]["filter_query"]
    assert "CLASH" in q and "bye" not in q
    assert app.CLASH_STYLES[0]["if"]["column_id"] == "flags"


# --- Task 8: the roster panel ---

from ffhelper.app import roster_slots_view


def _p(name, pos, pts=100.0):
    return Player(sleeper_id=name, name=name, position=pos, team="KC", proj_pts=pts)


def test_empty_slots_are_shown_as_empty():
    slots = {"QB": 1, "RB": 2, "WR": 2, "TE": 1, "FLEX": 2, "K": 1, "DEF": 1}
    view = roster_slots_view([_p("Allen", "QB")], slots)
    assert ("QB", "Allen") in view
    assert view.count(("RB", None)) == 2
    assert sum(1 for _label, filled in view if filled is None) == 9


def test_flex_takes_an_overflow_rb_but_never_a_quarterback():
    # value.lineup_value would start a QB at FLEX if its guard were dropped --
    # a real mutation-testing find. The picture must not disagree with MARG.
    slots = {"QB": 1, "RB": 2, "FLEX": 1}
    view = roster_slots_view(
        [_p("Allen", "QB", 300.0), _p("Purdy", "QB", 290.0),
         _p("Gibbs", "RB", 280.0), _p("Robinson", "RB", 270.0), _p("Hall", "RB", 260.0)],
        slots,
    )
    assert ("FLEX", "Hall") in view
    assert ("FLEX", "Purdy") not in view


def test_slot_order_follows_the_configured_roster():
    slots = {"QB": 1, "RB": 2, "WR": 2}
    labels = [label for label, _filled in roster_slots_view([], slots)]
    assert labels == ["QB", "RB", "RB", "WR", "WR"]


def test_the_panel_starts_exactly_the_lineup_lineup_value_scores():
    # roster_slots_view USED to copy lineup_value's greedy assignment, because
    # value.py was frozen for the 2026 drafts. This test guarded that copy; the
    # freeze lifted 2026-09-01 and the fold happened, so it now guards the real
    # thing -- the panel and MARG cannot disagree about one roster.
    from ffhelper.value import lineup_value
    slots = {"QB": 1, "RB": 2, "WR": 2, "TE": 1, "FLEX": 2, "K": 1, "DEF": 1}
    roster = [
        _p("Allen", "QB", 380.1), _p("Purdy", "QB", 344.2),
        _p("Gibbs", "RB", 291.7), _p("Bijan", "RB", 288.0), _p("Hall", "RB", 240.5),
        _p("Chase", "WR", 310.4), _p("Nacua", "WR", 265.9), _p("JSN", "WR", 250.0),
        _p("Bowers", "TE", 244.3), _p("McBride", "TE", 200.1),
        _p("Aubrey", "K", 150.0), _p("Rams", "DEF", 130.0),
    ]
    view = roster_slots_view(roster, slots)
    by_name = {p.name: p.proj_pts for p in roster}
    # Starters only: lineup_value scores the starting lineup, and BN rows are
    # explicitly the players it does NOT count.
    panel_total = sum(by_name[n] for label, n in view
                      if n is not None and label != "BN")
    # Rounded because the two sum the SAME players in a different order and
    # float addition is not associative. A different lineup moves this by
    # points, not by 4e-13.
    assert round(panel_total, 6) == round(lineup_value(roster, slots), 6)


def test_flex_sits_where_the_config_puts_it_not_at_the_end():
    # FLEX is FILLED last (from whatever the fixed slots leave), but it must be
    # DISPLAYED where the roster defines it. Both leagues configure
    # ...TE, FLEX, FLEX, K, DEF, which is also how Sleeper and Yahoo draw it;
    # a panel that trails FLEX after DEF reads as a different roster.
    slots = {"QB": 1, "RB": 2, "TE": 1, "FLEX": 2, "K": 1, "DEF": 1}
    labels = [label for label, _filled in roster_slots_view([], slots)]
    assert labels == ["QB", "RB", "RB", "TE", "FLEX", "FLEX", "K", "DEF"]


# --- a dead feed must not erase the draft ---

def test_a_failed_poll_keeps_the_last_good_picks(monkeypatch, tmp_path):
    # Found by cutting wifi during the live Sleeper mock, 2026-08-27. read_state
    # re-initialises `picks` to [] on every call, so a failed poll rebuilt the
    # board from NO picks: back to pick 1, the whole pool available, an empty
    # roster. The CLI does not do this only because `picks` is a loop variable
    # that survives the except branch -- the stateless render has no such luck.
    # Fabricating an entire draft state is the worst possible degradation.
    monkeypatch.setattr(app, "_draft_log_path", lambda league: tmp_path / "log.jsonl")
    league = League(name="deadfeed", platform="sleeper", league_id="1", draft_slot=5)
    players, settings = _pool(), _settings()
    picks = [FakePick(sleeper_id="3", pick_no=1, draft_slot=1),
             FakePick(sleeper_id="9", pick_no=2, draft_slot=2)]

    healthy, _stale = app.read_state(league, Tunables(), players, settings,
                                     FakeFeed(picks), True)
    assert healthy.current_pick == 3

    dead, stale = app.read_state(league, Tunables(), players, settings,
                                 FakeFeed(raise_error=True), True)
    assert dead.current_pick == 3, "a dead feed reset the board to pick 1"
    on_board = {r.player.sleeper_id for r in dead.board}
    assert on_board.isdisjoint({"3", "9"}), "drafted players came back onto the board"
    assert stale is not None and stale >= 0


def test_bench_players_are_visible_not_just_starters():
    # From the live Sleeper mock, 2026-08-27: "you can't see your own bench
    # picks". In a 15-round draft with 10 starting slots that is a third of your
    # team invisible -- and the bench is exactly what you are choosing between
    # once the STARTING LINEUP FULL banner is up.
    slots = {"QB": 1, "RB": 2}
    roster = [_p("Allen", "QB", 380.0), _p("Gibbs", "RB", 291.0),
              _p("Bijan", "RB", 288.0), _p("Hall", "RB", 240.0),
              _p("Purdy", "QB", 220.0)]
    view = roster_slots_view(roster, slots, bench_slots=3)
    assert view[:3] == [("QB", "Allen"), ("RB", "Gibbs"), ("RB", "Bijan")]
    # Leftovers appear as bench, best first, and the unused bench slot is shown
    # so you can count the picks you still have.
    assert view[3:] == [("BN", "Hall"), ("BN", "Purdy"), ("BN", None)]


def test_bench_defaults_to_none_so_existing_callers_are_unchanged():
    assert roster_slots_view([_p("Allen", "QB")], {"QB": 1}) == [("QB", "Allen")]


def test_a_bench_overflow_is_still_shown_never_dropped():
    # Non-negotiable #3 applied to the roster: if entry drifts and you end up
    # attributed more players than the roster has room for, they must be on
    # screen, not silently swallowed.
    roster = [_p("Allen", "QB", 380.0), _p("Purdy", "QB", 300.0),
              _p("Mayfield", "QB", 250.0)]
    view = roster_slots_view(roster, {"QB": 1}, bench_slots=1)
    assert view == [("QB", "Allen"), ("BN", "Purdy"), ("BN", "Mayfield")]


def test_a_single_failed_poll_is_visible_immediately_not_after_15s():
    # Live Sleeper mock, 2026-08-27: 55s of continuous DNS failure and the user
    # reported never seeing the banner. The loud `!!` line only fires above 15s,
    # so the first three failed polls say NOTHING -- the board looks healthy
    # while being three picks behind. A quiet line from the first failure closes
    # that window; the loud one still escalates.
    state, players = _state()
    assert "feed" in " ".join(banner_lines(state, 4.0, players)).lower()


def test_a_healthy_feed_stays_quiet():
    # The counterpart: a working feed must not add a line of noise to a board
    # that is read under a pick clock.
    state, players = _state()
    assert not [l for l in banner_lines(state, 0.0, players) if "feed" in l.lower()]


def test_a_long_outage_still_escalates_to_the_loud_banner():
    state, players = _state()
    assert any(l.startswith("!!") for l in banner_lines(state, 40.0, players))


# --- the refresh interval is a config value, not a hardcoded 5s ---

def test_the_interval_comes_from_poll_seconds_not_a_hardcoded_5s():
    # "Is there no way to have our board update almost simultaneously with the
    # actual draft?" -- 2026-08-27, after the live Sleeper mock. cli.py already
    # reads this tunable and floors it at 1s; app.py hardcoded 5000ms, so the
    # one knob that controls lag did nothing for the web board.
    tun = Tunables(poll_seconds={"sleeper": 1, "yahoo": 12})
    assert app.poll_interval_ms(tun, "sleeper") == 1000
    assert app.poll_interval_ms(tun, "yahoo") == 12000


def test_the_interval_is_floored_at_one_second():
    # Same floor as cli.py, for the same two reasons: a 0 busy-loops, and
    # Sleeper IP-blocks above ~1000 req/min. 1s measured at 60 req/min.
    assert app.poll_interval_ms(Tunables(poll_seconds={"sleeper": 0}), "sleeper") == 1000
    assert app.poll_interval_ms(Tunables(poll_seconds={}), "unknown") == 5000


def test_build_app_actually_constructs_and_carries_the_interval():
    # This test exists because 299 tests and the full mutation suite passed over
    # a build_app that raised NameError on import of its own arguments -- the
    # app could not start at all. Nothing in the suite had ever CALLED it. The
    # cheapest guard against "the server does not boot" is to boot the layout.
    built = app.build_app(["a", "b"], "a", poll_ms=1000)
    found = []

    def walk(node):
        for child in getattr(getattr(node, "children", None), "__iter__", lambda: [])():
            walk(child)
        if type(node).__name__ == "Interval":
            found.append(node.interval)

    import dash
    walk(dash.page_registry["board"]["layout"])
    assert found == [1000], f"expected one 1s Interval, got {found}"


# --- clicking the same cell twice must register twice ---

def test_a_click_clears_the_selection_so_the_same_cell_works_twice(monkeypatch, tmp_path):
    # From the live Yahoo mock, 2026-08-27: "sometimes clicks don't register and
    # you have to click another part of the row" / "you can't click the spot
    # already highlighted from your prior selection". Dash fires a callback only
    # when a prop CHANGES, so clicking the cell that is already `active_cell` is
    # a no-op -- the mark is silently dropped. Under a pick clock that is how
    # you fall behind, and it is the likeliest cause of the pick-96 mess.
    write, path = _make_write(monkeypatch, tmp_path)
    monkeypatch.setattr(_dash.callback_context.__class__, "triggered_id",
                        property(lambda self: "board"))
    rows = [{"id": "4017", "player": "Bijan Robinson"}]
    _status, _n, active, _last = write({"row": 0, "column": 0}, 0, 0, rows,
                                       "write-test", 0, None)
    assert active is None, "selection must be cleared or the next identical click is lost"


def test_the_override_uses_the_last_marked_player_not_the_live_selection(monkeypatch, tmp_path):
    # Clearing active_cell would break the override if it still read from it,
    # so the id of the player just marked is carried explicitly. That is also
    # the better semantic: the override means "that pick I just entered was (or
    # was not) mine".
    write, path = _make_write(monkeypatch, tmp_path)
    monkeypatch.setattr(_dash.callback_context.__class__, "triggered_id",
                        property(lambda self: "board"))
    rows = [{"id": "4017", "player": "Bijan Robinson"}]
    _s, _n, _a, last = write({"row": 0, "column": 0}, 0, 0, rows, "write-test", 0, None)
    assert last == "4017"

    monkeypatch.setattr(_dash.callback_context.__class__, "triggered_id",
                        property(lambda self: "override"))
    status, _n, _a, _l = write(None, 0, 1, rows, "write-test", 1, last)
    assert status == "4017 is yours"
    ops = [json.loads(line) for line in path.read_text().splitlines()]
    assert ops[-1] == {"op": "mark", "id": "4017", "mine": True}


def test_flex_filter_shows_every_flex_eligible_position():
    # Requested during the live Yahoo mock: a FLEX/WRT option. It is the one
    # slot whose candidates span positions, so comparing them means seeing them
    # in one list. FLEX_ELIGIBLE is imported from value.py, not restated, for
    # the same reason the roster panel imports it: one rule, one place.
    rows = [{"player": "Gibbs", "pos": "RB"}, {"player": "Chase", "pos": "WR"},
            {"player": "Bowers", "pos": "TE"}, {"player": "Allen", "pos": "QB"},
            {"player": "Aubrey", "pos": "K"}]
    got = [r["player"] for r in filter_rows(rows, "FLEX", "")]
    assert got == ["Gibbs", "Chase", "Bowers"]


def test_flex_filter_composes_with_search():
    rows = [{"player": "Bijan Robinson", "pos": "RB"},
            {"player": "Wan'Dale Robinson", "pos": "WR"},
            {"player": "Jordan Love", "pos": "QB"}]
    assert len(filter_rows(rows, "FLEX", "robin")) == 2


# --- five routes, the league carried in the query string ---

import pytest
from ffhelper.app import league_from_search


@pytest.mark.parametrize("search,expected", [
    ("?league=yahoo-main", "yahoo-main"),
    ("?league=sleeper-main&x=1", "sleeper-main"),
    ("", "sleeper-main"),
    ("?league=", "sleeper-main"),
    ("?league=not-a-league", "sleeper-main"),
])
def test_league_from_search(search, expected):
    """An unknown or absent league falls back to the default, never raises.

    The query string is user-editable, so a typo must not 500 the page. It
    falls back rather than guessing at a near-match: a silently wrong league
    would advise on someone else's team.
    """
    names = ["sleeper-main", "yahoo-main"]
    assert league_from_search(search, names, "sleeper-main") == expected


def test_build_app_registers_all_five_routes_and_keeps_the_board_key():
    # test_build_app_actually_constructs_and_carries_the_interval (above) reads
    # dash.page_registry["board"] -- renaming that key when the path moved to
    # /draft would break it silently for anyone who greps for "board" instead
    # of "/draft".
    import dash
    app.build_app(["a", "b"], "a", poll_ms=1000)
    paths = {mod: page["path"] for mod, page in dash.page_registry.items()
             if mod in {"board", "home", "lineup", "waivers", "trades"}}
    assert paths == {
        "board": "/draft", "home": "/", "lineup": "/lineup",
        "waivers": "/waivers", "trades": "/trades",
    }


def test_season_page_layout_resolves_the_league_from_the_url_not_the_default(monkeypatch):
    # Dash calls a registered page's layout with the query string ALREADY
    # parsed into kwargs (e.g. league="b"), not the raw "?league=b" string.
    # league_from_kwargs hands that bare value straight to the shared
    # _resolve_league fallback -- without it, every season page would silently
    # ignore ?league= and always show the default league, which would defeat
    # the entire point of carrying the league in the URL.
    #
    # config/build_lineup are stubbed so this stays offline and independent of
    # config.toml's real league names -- "b" only has to satisfy
    # league_from_kwargs's fallback list, not an actual league.
    import dash
    fake_league = League(name="b", platform="sleeper", league_id="1")
    monkeypatch.setattr(app, "load_config", lambda path: ([fake_league], Tunables()))
    monkeypatch.setattr(pipeline, "build_lineup",
                        lambda league, tunables, **kw: pipeline.LineupView(
                            league_name=league.name, error="stub"))
    app.build_app(["a", "b"], "a", poll_ms=1000)
    layout = dash.page_registry["lineup"]["layout"]
    rendered = layout(league="b")
    links = rendered.children[0].children
    waivers_link = next(link for link in links if link.children == "WAIVERS")
    assert waivers_link.href == "/waivers?league=b"


def test_draft_page_shows_the_local_only_notice():
    # main() already prints this to the terminal at startup, where nobody
    # looking at the browser sees it -- the page itself has to say it too.
    import dash
    app.build_app(["a", "b"], "a", poll_ms=1000)
    layout = dash.page_registry["board"]["layout"]
    texts = []

    def walk(node):
        children = getattr(node, "children", None)
        if isinstance(children, str):
            texts.append(children)
        elif isinstance(children, list):
            for child in children:
                walk(child)
        elif children is not None:
            walk(children)

    walk(layout)
    assert app.DRAFT_NOTICE in texts


# --- homepage status strip ---

def test_snapshot_recorded_true_when_rows_exist():
    conn = store.connect(":memory:")
    conn.execute(
        "INSERT INTO snapshot (league, season, week, player_id, taken_at, started)"
        " VALUES ('sleeper-main','2026',3,'4046','2026-09-20T11:00:00',1)")
    conn.commit()
    assert snapshot_recorded(conn, "sleeper-main", "2026", 3) is True


def test_snapshot_recorded_false_when_week_empty():
    conn = store.connect(":memory:")
    assert snapshot_recorded(conn, "sleeper-main", "2026", 3) is False


def test_snapshot_recorded_none_when_unreadable():
    """None, not False. 'Could not check' is a different fact from 'no rows'.

    The strip omits the line on None. Reporting 'not recorded' for a database
    it cannot read is a fabricated value where a measured one is expected --
    non-negotiable #7. This is the case a suite skips because nothing happens.
    """
    class Broken:
        def execute(self, *a, **k):
            raise sqlite3.OperationalError("no such table: snapshot")
    assert snapshot_recorded(Broken(), "sleeper-main", "2026", 3) is None


def test_status_strip_omits_the_snapshot_line_when_the_week_is_unavailable(
    monkeypatch, tmp_path,
):
    # load_nfl_state down means there is no week to check the table against --
    # printing a snapshot line at all here would be a claim built on nothing.
    def broken(*a, **k):
        raise RuntimeError("state fetch failed")
    monkeypatch.setattr(app, "load_nfl_state", broken)
    # Never the machine's real .roster/ -- an empty tmp_path keeps this test's
    # pass/fail independent of whatever roster files happen to exist on disk.
    monkeypatch.setattr(app, "ROSTER_DIR", tmp_path)
    rendered = str(status_strip("sleeper-main"))
    assert "week unavailable" in rendered
    assert "snapshot" not in rendered


def test_status_strip_reports_snapshot_not_recorded_for_an_empty_table(
    monkeypatch, tmp_path,
):
    # store.DB_PATH is redirected to a fresh, empty per-test file by
    # tests/conftest.py, so an ordinary call reads a real, table-having, but
    # row-less database -- exactly the False case, not the None case.
    monkeypatch.setattr(app, "load_nfl_state", lambda: {"week": 3, "season": "2026"})
    monkeypatch.setattr(app, "ROSTER_DIR", tmp_path)
    rendered = str(status_strip("sleeper-main"))
    assert "snapshot NOT recorded for week 3" in rendered


def test_status_strip_shows_roster_age_only_when_the_file_exists(monkeypatch, tmp_path):
    monkeypatch.setattr(app, "load_nfl_state", lambda: {"week": 3, "season": "2026"})
    monkeypatch.setattr(app, "ROSTER_DIR", tmp_path)
    assert "roster file" not in str(status_strip("yahoo-main"))

    (tmp_path / "yahoo-main.txt").write_text("Bijan Robinson\n")
    assert "roster file" in str(status_strip("yahoo-main"))


# --- season pages render the CLI's text ---

from ffhelper.app import season_page_children
from ffhelper import pipeline


def test_season_page_renders_error_without_calling_renderer():
    """A view carrying an error renders the message, not an empty table.

    The refusal text IS the deliverable for a Yahoo waiver page -- an empty
    table would read as 'nothing available', which is a different claim.
    """
    view = pipeline.WaiverView(league_name="yahoo-main",
                               error="waivers needs every team's roster")
    children = season_page_children("waivers", view)
    rendered = str(children)
    assert "waivers needs every team's roster" in rendered
    assert "Table" not in rendered


def test_trades_page_builds_no_view_on_load(monkeypatch):
    """The one thing this task must not get wrong: a page render must never
    trigger the ~330s full sweep (pipeline.py's `build_trades` ponytail note).
    Task 9 wires a button; until then the page shows the caveat text only.
    """
    import dash

    def boom(*a, **k):
        raise AssertionError("build_trades must not run on page load")
    monkeypatch.setattr(pipeline, "build_trades", boom)
    app.build_app(["a", "b"], "a", poll_ms=1000)
    layout = dash.page_registry["trades"]["layout"]
    rendered = layout(league="b")
    assert "minutes" in str(rendered)


def test_waivers_page_layout_builds_its_view(monkeypatch):
    """Unlike /trades, /waivers builds its view in the layout itself."""
    import dash

    fake_league = League(name="b", platform="sleeper", league_id="1")
    monkeypatch.setattr(app, "load_config", lambda path: ([fake_league], Tunables()))
    monkeypatch.setattr(pipeline, "build_waivers",
                        lambda league, tunables, **kw: pipeline.WaiverView(
                            league_name=league.name, error="stub waivers view"))
    app.build_app(["a", "b"], "a", poll_ms=1000)
    layout = dash.page_registry["waivers"]["layout"]
    rendered = layout(league="b")
    assert "stub waivers view" in str(rendered)


# --- /lineup as an HTML table ---

from ffhelper.app import lineup_rows, simple_table
from ffhelper.season import CloseCall, StartSit


def test_lineup_rows_show_dash_for_unprojected_starter():
    """An unprojected starter renders '--', never '0.0'.

    The 0.0 is a sort value this code invented. Printing it as a projection is
    the fabrication non-negotiable #7 bars, arriving in the one place a user is
    most likely to trust it.
    """
    p = Player(sleeper_id="99", name="Stash Guy", position="TE", team="CHI",
               proj_pts=0.0)
    view = pipeline.LineupView(
        league_name="sleeper-main", week=3,
        state=StartSit(lineup=[("TE", p)], bench=[], close_calls=[],
                       unprojected=[p]))
    rows = lineup_rows(view)
    assert rows[0]["proj"] == "--"
    assert "0.0" not in str(rows[0])


def test_lineup_rows_projected_total_carries_the_floor_caveat():
    """The total is a floor when a starter has no projection -- render_lineup
    names that on screen next to the number; the table must too.
    """
    p = Player(sleeper_id="99", name="Stash Guy", position="TE", team="CHI",
               proj_pts=0.0)
    scored = Player(sleeper_id="1", name="Scored Guy", position="QB", team="KC",
                    proj_pts=20.0)
    view = pipeline.LineupView(
        league_name="sleeper-main", week=3,
        state=StartSit(lineup=[("QB", scored), ("TE", p)], bench=[], close_calls=[],
                       unprojected=[p]))
    rows = lineup_rows(view)
    total_row = rows[-1]
    assert total_row["player"] == "projected total"
    assert total_row["proj"] == "20.0"
    assert "1 starter" in total_row["flags"] and "unprojected" in total_row["flags"]


def test_lineup_rows_empty_slot_shows_empty_not_a_player():
    view = pipeline.LineupView(
        league_name="sleeper-main", week=3,
        state=StartSit(lineup=[("RB", None)], bench=[], close_calls=[], unprojected=[]))
    rows = lineup_rows(view)
    assert rows[0]["slot"] == "RB"
    assert "EMPTY" in rows[0]["player"]


def test_lineup_page_carries_close_calls_and_notes_not_just_starters():
    """SPEC GAP ruling: render_lineup also prints BENCH, an unprojected list,
    CLOSE CALLS, and '!!' notes -- the brief's lineup_rows only covers
    STARTERS and the total. An HTML page that dropped the rest would quietly
    show less than the text it replaced, so this holds the two sections most
    likely to be forgotten by a page that only wires the starters table.
    """
    starter = Player(sleeper_id="1", name="Starter Guy", position="RB", team="KC",
                     proj_pts=10.0)
    challenger = Player(sleeper_id="2", name="Bench Guy", position="RB", team="SF",
                        proj_pts=9.0)
    view = pipeline.LineupView(
        league_name="sleeper-main", week=3, owner="me",
        notes=["FAAB bid due Wednesday"],
        state=StartSit(
            lineup=[("RB", starter)], bench=[challenger],
            close_calls=[CloseCall(slot="RB", starter=starter, challenger=challenger,
                                   gap=1.0)],
            unprojected=[]))
    rendered = str(season_page_children("lineup", view))
    assert "Bench Guy" in rendered                            # BENCH section
    assert "Starter Guy" in rendered and "1.0" in rendered     # CLOSE CALLS
    assert "FAAB bid due Wednesday" in rendered                # !! notes


def test_lineup_page_carries_the_unprojected_section():
    p = Player(sleeper_id="99", name="Stash Guy", position="TE", team="CHI",
               proj_pts=0.0)
    view = pipeline.LineupView(
        league_name="sleeper-main", week=3,
        state=StartSit(lineup=[("TE", p)], bench=[], close_calls=[], unprojected=[p]))
    rendered = str(season_page_children("lineup", view))
    assert "NO PROJECTION THIS WEEK" in rendered


def test_simple_table_wraps_in_a_scrolling_div_not_a_datatable():
    """html.Table, not dash_table.DataTable -- read-only rows, no cell
    interaction, and the wide-table scroll stays inside its own container.
    """
    table = simple_table(["a", "b"], [{"a": "1", "b": "2"}])
    rendered = str(table)
    assert "DataTable" not in rendered
    assert "overflowX" in rendered
