import logging
import queue
import time

import pytest

from ffhelper.cli import (
    MarkDrafted, NullFeed, _combine_my_roster, _handle_command, _lookup_roster_id,
    _my_roster_from_picks, _preflight, _render_tick, _run, _select_feed, _stdin_reader,
    find_players, load_board_inputs, league_settings_from_config, main, render, resolve_settings,
)
from ffhelper.config import League, Tunables
from ffhelper.data import LeagueSettings, Player
from ffhelper.feeds import Pick
from ffhelper.value import Row, build_board


def row(pid: str, name: str, pos: str, vona: float, surv: float, div: int = 0,
        injury: str | None = None) -> Row:
    p = Player(pid, name, pos, "SF", injury_status=injury, adp=10.0, adp_stdev=3.0)
    return Row(player=p, vbd=vona, vona=vona, marginal=vona, tier=1,
               survival=surv, divergence=div)


def test_divergence_flag_threshold_comes_from_tunables_not_a_hardcoded_25():
    """`tunables.divergence_flag_slots` was loaded, defaulted, and never read --
    turning the knob did nothing. Against that code the first assertion fails:
    a divergence of 10 stays unflagged no matter what threshold is passed."""
    r = [row("a", "Jahmyr Gibbs", "RB", 50.0, 0.2, div=10)]
    loose = render(r, limit=10, stale_seconds=0.0, my_roster=[], runs={},
                   divergence_flag_slots=5)
    tight = render(r, limit=10, stale_seconds=0.0, my_roster=[], runs={},
                   divergence_flag_slots=25)
    assert "MODEL+10" in loose
    assert "MODEL+10" not in tight


def test_render_includes_players_and_headers():
    out = render([row("a", "Jahmyr Gibbs", "RB", 50.0, 0.2)], limit=10,
                 stale_seconds=0.0, my_roster=[], runs={})
    assert "Jahmyr Gibbs" in out
    assert "VONA" in out and "SURV" in out


def test_render_respects_limit():
    board = [row(str(i), f"Player {i}", "RB", 50.0 - i, 0.5) for i in range(30)]
    out = render(board, limit=5, stale_seconds=0.0, my_roster=[], runs={})
    assert "Player 4" in out
    assert "Player 5" not in out


def test_render_shows_stale_banner_only_when_stale():
    board = [row("a", "A", "RB", 1.0, 0.5)]
    assert "STALE" in render(board, 5, stale_seconds=45.0, my_roster=[], runs={})
    assert "STALE" not in render(board, 5, stale_seconds=2.0, my_roster=[], runs={})


def test_render_flags_injuries():
    out = render([row("a", "Hurt Guy", "RB", 50.0, 0.5, injury="PUP")],
                 limit=5, stale_seconds=0.0, my_roster=[], runs={})
    assert "PUP" in out


def test_render_shows_position_run():
    out = render([row("a", "A", "RB", 1.0, 0.5)], limit=5, stale_seconds=0.0,
                 my_roster=[], runs={"RB": 5, "WR": 3})
    # Match the run-summary LINE itself, not substrings ("RB" also appears in
    # every row's POS column, and "5" inside "50%" in the SURV column -- both
    # occur even if this summary line is deleted, which is why a plain
    # substring check on "RB"/"5" would pass against a build with no summary
    # line at all).
    lines = out.splitlines()
    summary_lines = [line for line in lines if line.startswith("last 8 picks:")]
    assert summary_lines == ["last 8 picks:  RB 5  WR 3"]


def test_render_empty_board_does_not_crash():
    assert isinstance(render([], 10, 0.0, [], {}), str)


def test_render_manual_mode_shows_status_and_never_a_stale_banner():
    """stale_seconds=None (no feed at all) must show a clear manual-entry
    status line and MUST NOT show the stale-feed banner -- there is no feed
    to be stale, so showing one would be false. Against a build that treats
    None like any other number (e.g. `stale_seconds > 15` with None raising,
    or a leftover branch that always prints FEED STALE for non-floats), this
    fails on either the missing status line or a wrongly-shown STALE banner.
    """
    board = [row("a", "A", "RB", 1.0, 0.5)]
    out = render(board, 5, stale_seconds=None, my_roster=[], runs={})
    assert "MANUAL" in out
    assert "STALE" not in out


# --- Manual league settings: a first-class path, not a fallback. ---

MANUAL_SETTINGS = {
    "num_teams": 10,
    "bench": 5,
    "roster_slots": {"QB": 1, "RB": 2, "WR": 2, "TE": 1, "FLEX": 2, "K": 1, "DEF": 1},
    "scoring": {
        "pass_cmp": 0.25, "pass_yd": 0.04, "pass_td": 6, "pass_int": -2,
        "rush_yd": 0.1, "rush_td": 6, "rec": 0.5, "rec_yd": 0.1, "rec_td": 6,
        "fum_lost": -2,
    },
}


def test_league_settings_from_config_builds_settings():
    settings = league_settings_from_config(MANUAL_SETTINGS)
    assert settings.num_teams == 10
    assert settings.roster_slots["RB"] == 2
    assert settings.scoring["pass_td"] == 6.0
    assert settings.rounds == sum(MANUAL_SETTINGS["roster_slots"].values()) + 5


def test_league_settings_from_config_missing_roster_slots_raises():
    bad = {**MANUAL_SETTINGS, "roster_slots": {}}
    with pytest.raises(ValueError, match="roster_slots"):
        league_settings_from_config(bad)


def test_league_settings_from_config_missing_scoring_raises():
    bad = {**MANUAL_SETTINGS, "scoring": {}}
    with pytest.raises(ValueError, match="scoring"):
        league_settings_from_config(bad)


def test_resolve_settings_uses_config_block_for_non_api_platform():
    league = League(name="yahoo-main", platform="yahoo", league_id="1", settings=MANUAL_SETTINGS)
    settings = resolve_settings(league)
    assert settings.num_teams == 10
    assert settings.roster_slots["FLEX"] == 2


def test_resolve_settings_raises_naming_league_when_no_settings_and_no_api():
    league = League(name="my-friend-league", platform="yahoo", league_id="1")
    with pytest.raises(ValueError, match="my-friend-league"):
        resolve_settings(league)


def test_resolve_settings_sleeper_prefers_api_even_with_settings_block(monkeypatch):
    """A Sleeper league still prefers the API even when a [league.settings]
    block is present -- manual settings never shadow a working platform sync."""
    sentinel = LeagueSettings(
        num_teams=12, scoring={"pass_td": 6.0}, roster_slots={"QB": 1}, rounds=1,
        draft_id="abc123",
    )
    monkeypatch.setattr("ffhelper.cli.load_sleeper_settings", lambda league_id: sentinel)
    league = League(name="sleeper-main", platform="sleeper", league_id="1", settings=MANUAL_SETTINGS)
    assert resolve_settings(league) is sentinel


def test_load_board_inputs_manual_league_produces_correct_board(monkeypatch):
    """A config-only league (no platform API) produces a correct, ranked board."""
    players = {
        "1": Player("1", "Bijan Robinson", "RB", "ATL"),
        "2": Player("2", "Justin Jefferson", "WR", "MIN"),
        "3": Player("3", "Zero Projection Guy", "WR", "MIN"),
    }
    projections = [
        {"player_id": "1", "stats": {"rush_yd": 1200, "rush_td": 10}},
        {"player_id": "2", "stats": {"rec": 100, "rec_yd": 1400, "rec_td": 10}},
    ]
    monkeypatch.setattr("ffhelper.cli.load_players", lambda: players)
    monkeypatch.setattr("ffhelper.cli.load_projections", lambda season: projections)
    monkeypatch.setattr("ffhelper.cli.load_ffc_adp", lambda fmt, teams, year: [])

    league = League(name="manual-league", platform="yahoo", league_id="1", settings=MANUAL_SETTINGS)
    tunables = Tunables()
    result_players, settings = load_board_inputs(league, tunables, season="2026")

    # Zero-projection player dropped; the other two survive.
    assert set(result_players) == {"1", "2"}
    assert settings.num_teams == 10

    board = build_board(
        list(result_players.values()), [], settings.roster_slots, settings.num_teams,
        current_pick=1, my_slot=None, tunables=tunables,
    )
    assert len(board) == 2
    assert isinstance(board[0], Row)


def test_load_board_inputs_keeps_ambiguous_prefix_visible(monkeypatch, capsys):
    """apply_ffc_adp prefixes ambiguous matches "AMBIGUOUS: " so they can be told
    apart from plain unmatched names -- that distinction must survive printing."""
    players = {"1": Player("1", "Robinson", "RB", "ATL")}
    projections = [{"player_id": "1", "stats": {"rush_yd": 100}}]
    monkeypatch.setattr("ffhelper.cli.load_players", lambda: players)
    monkeypatch.setattr("ffhelper.cli.load_projections", lambda season: projections)
    monkeypatch.setattr("ffhelper.cli.load_ffc_adp", lambda fmt, teams, year: [])
    monkeypatch.setattr("ffhelper.cli.apply_ffc_adp", lambda players, rows: ["AMBIGUOUS: Robinson"])

    league = League(name="manual-league", platform="yahoo", league_id="1", settings=MANUAL_SETTINGS)
    load_board_inputs(league, Tunables(), season="2026")

    assert "AMBIGUOUS: Robinson" in capsys.readouterr().err


# --- The draft loop: never dies, whatever a tick throws. ---


class _FakeFeed:
    """A PickFeed stand-in with no network -- returns fixed picks, or always
    raises, depending on the test."""

    def __init__(self, picks: list[Pick] | None = None, fail: bool = False):
        self._picks = picks or []
        self.fail = fail
        self.calls = 0

    def get_picks(self) -> list[Pick]:
        self.calls += 1
        if self.fail:
            raise RuntimeError("feed unreachable")
        return self._picks


def _loop_league(draft_slot=None):
    return League(name="loop-league", platform="sleeper", league_id="1", draft_slot=draft_slot)


def _loop_settings():
    return LeagueSettings(
        num_teams=10, scoring={"pass_td": 6.0}, roster_slots={"QB": 1}, rounds=1,
        draft_id="d1",
    )


def _loop_players():
    return {"1": Player("1", "A", "RB", "ATL", proj_pts=100.0, adp=1.0, adp_stdev=1.0)}


def test_run_survives_render_failure_and_keeps_going(monkeypatch):
    """Regression guard for the CRITICAL fix: an exception from anywhere past
    the feed poll (build_board, render, printing...) must not kill the loop.

    Against the pre-fix code -- where only `feed.get_picks()` sat inside a
    try/except and everything else, including `render`, ran unguarded -- this
    RuntimeError propagates straight out of `_run` on the first iteration and
    this test fails with that exception instead of observing a clean return.
    """
    monkeypatch.setattr("ffhelper.cli.load_board_inputs",
                         lambda league, tunables: (_loop_players(), _loop_settings()))
    fake_feed = _FakeFeed(picks=[])
    monkeypatch.setattr("ffhelper.cli.SleeperFeed", lambda draft_id: fake_feed)
    monkeypatch.setattr("ffhelper.cli.time.sleep", lambda s: None)

    render_calls = {"n": 0}

    def flaky_render(*args, **kwargs):
        render_calls["n"] += 1
        raise RuntimeError("boom")

    monkeypatch.setattr("ffhelper.cli.render", flaky_render)

    result = _run(_loop_league(), Tunables(), limit=10, max_iterations=3)

    assert result == 0
    assert render_calls["n"] == 3          # every iteration was attempted
    assert fake_feed.calls == 3            # the loop kept polling too


def test_run_survives_feed_failure_and_still_renders_with_stale_banner(monkeypatch, capsys):
    monkeypatch.setattr("ffhelper.cli.load_board_inputs",
                         lambda league, tunables: (_loop_players(), _loop_settings()))
    fake_feed = _FakeFeed(fail=True)
    monkeypatch.setattr("ffhelper.cli.SleeperFeed", lambda draft_id: fake_feed)
    monkeypatch.setattr("ffhelper.cli.time.sleep", lambda s: None)

    # Only the very first time.time() call (which seeds last_ok in _run) is
    # faked, 30s into the past -- everything else (the stale calc, and the
    # logging module's own internal clock reads for the "poll failed"
    # warnings) keeps using the real clock. Since the feed always fails,
    # last_ok never advances, so every render tick is already well past the
    # 15s stale threshold.
    #
    # `input_queue` is passed explicitly (see `_run`'s docstring) so no real
    # background stdin-reader thread spawns: that thread now logs on exit
    # (Fix 4), and logging's own internal `time.time()` read would otherwise
    # race the single seeded call below on a separate thread, making which
    # call gets the -30s offset nondeterministic.
    real_time = time.time
    seeded = {"done": False}

    def fake_time():
        if not seeded["done"]:
            seeded["done"] = True
            return real_time() - 30
        return real_time()

    monkeypatch.setattr("ffhelper.cli.time.time", fake_time)

    result = _run(_loop_league(), Tunables(), limit=10, max_iterations=3,
                  input_queue=queue.Queue())
    out = capsys.readouterr().out

    assert result == 0
    assert fake_feed.calls == 3            # loop kept polling despite failures
    assert "A" in out                      # still rendered from last known (empty) picks
    assert "FEED STALE" in out             # banner showed once the threshold passed


def test_preflight_reports_ok_with_reachable_feed(monkeypatch, capsys):
    monkeypatch.setattr("ffhelper.cli.load_board_inputs",
                         lambda league, tunables: (_loop_players(), _loop_settings()))
    monkeypatch.setattr("ffhelper.cli.SleeperFeed", lambda draft_id: _FakeFeed(picks=[]))

    result = _preflight(_loop_league(draft_slot=3), Tunables())
    out = capsys.readouterr().out

    assert result == 0
    assert "PREFLIGHT OK" in out


def test_preflight_rejects_a_draft_slot_outside_the_league_size(monkeypatch, capsys):
    """draft_slot is hand-entered and deliberately never guessed, so a typo is
    likely. Slot 13 in a 10-team league silently yields wrong next-pick numbers
    for the entire draft -- preflight is the one place that can catch it."""
    monkeypatch.setattr("ffhelper.cli.load_board_inputs",
                         lambda league, tunables: (_loop_players(), _loop_settings()))
    monkeypatch.setattr("ffhelper.cli.SleeperFeed", lambda draft_id: _FakeFeed(picks=[]))

    result = _preflight(_loop_league(draft_slot=13), Tunables())   # _loop_settings is 10 teams
    out = capsys.readouterr().out

    assert result == 1
    assert "OUT OF RANGE" in out
    assert "PREFLIGHT INCOMPLETE" in out


def test_standard_scoring_uses_sleepers_adp_std_not_adp_standard(monkeypatch):
    """Sleeper emits `adp_std`; the format string is "standard". Deriving the key
    by string munging produced `adp_standard`, which does not exist, so every
    player silently kept adp 999 and the board rendered as if healthy.

    Against that code this asserts on a field name of 'adp_standard' and fails.
    """
    seen = {}
    monkeypatch.setattr("ffhelper.cli.load_players", lambda: _loop_players())
    monkeypatch.setattr("ffhelper.cli.load_projections", lambda season: [])
    monkeypatch.setattr("ffhelper.cli.apply_projections", lambda p, pr, sc: None)
    monkeypatch.setattr("ffhelper.cli.load_ffc_adp", lambda f, t, y: [])
    monkeypatch.setattr("ffhelper.cli.apply_ffc_adp", lambda p, rows: [])
    monkeypatch.setattr("ffhelper.cli.apply_sleeper_adp",
                         lambda players, proj, field: seen.update(field=field))
    monkeypatch.setattr(
        "ffhelper.cli.resolve_settings",
        lambda lg, season=None: LeagueSettings(
            num_teams=10, scoring={"rec": 0.0}, roster_slots={"QB": 1}, rounds=1,
            draft_id="d1"),
    )

    load_board_inputs(_loop_league(), Tunables())

    assert seen["field"] == "adp_std"


def test_main_dispatches_preflight_and_returns_its_exit_code(monkeypatch):
    league = _loop_league()
    monkeypatch.setattr("ffhelper.cli.load_config", lambda path: ([league], Tunables()))
    monkeypatch.setattr("ffhelper.cli._preflight", lambda lg, tun: 7)

    result = main(["preflight", "--league", "loop-league"])

    assert result == 7


def test_main_unknown_league_is_a_clear_error_not_a_traceback(monkeypatch, capsys):
    monkeypatch.setattr("ffhelper.cli.load_config", lambda path: ([], Tunables()))

    result = main(["preflight", "--league", "does-not-exist"])
    err = capsys.readouterr().err

    assert result == 1
    assert "does-not-exist" in err


def test_main_keyboard_interrupt_exits_cleanly(monkeypatch):
    league = _loop_league()
    monkeypatch.setattr("ffhelper.cli.load_config", lambda path: ([league], Tunables()))

    def raise_interrupt(lg, tun, limit):
        raise KeyboardInterrupt

    monkeypatch.setattr("ffhelper.cli._run", raise_interrupt)

    result = main(["run", "--league", "loop-league"])

    assert result == 0


def test_run_propagates_keyboard_interrupt_from_feed(monkeypatch):
    """KeyboardInterrupt from the feed must propagate out of _run, not be caught
    by the inner `except Exception` handlers (which exist only for transient feed
    or render failures). This test guards against a regression where an inner
    handler is broadened to `except BaseException`.

    If an inner handler caught BaseException (or bare `except:`), KeyboardInterrupt
    would be caught and logged as a generic exception instead of propagating, and
    this test would fail: _run would return 0 instead of raising KeyboardInterrupt.
    """
    monkeypatch.setattr("ffhelper.cli.load_board_inputs",
                         lambda league, tunables: (_loop_players(), _loop_settings()))

    class _InterruptFeed:
        def get_picks(self):
            raise KeyboardInterrupt("user stop")

    monkeypatch.setattr("ffhelper.cli.SleeperFeed", lambda draft_id: _InterruptFeed())
    monkeypatch.setattr("ffhelper.cli.time.sleep", lambda s: None)

    # KeyboardInterrupt should propagate out, not be caught internally.
    with pytest.raises(KeyboardInterrupt):
        _run(_loop_league(), Tunables(), limit=10, max_iterations=1)


# --- Manual mark-drafted: find_players + MarkDrafted. ---


def _pool():
    return {
        "bijan": Player("bijan", "Bijan Robinson", "RB", "ATL"),
        "brian": Player("brian", "Brian Robinson", "RB", "ATL"),
        "gibbs": Player("gibbs", "Jahmyr Gibbs", "RB", "DET"),
        "pineiro": Player("pineiro", "Eddy Piñeiro", "K", "CAR"),
        "harrison": Player("harrison", "Marvin Harrison Jr.", "WR", "ARI"),
    }


def test_find_players_partial_name_case_insensitive():
    # Discriminates against exact-match-only or case-sensitive search.
    assert [p.sleeper_id for p in find_players(_pool(), "GiBbS")] == ["gibbs"]


def test_find_players_accent_and_suffix_via_norm_name():
    # Discriminates against a hand-rolled normaliser that doesn't fold accents
    # or strip generational suffixes the way norm_name does.
    assert [p.sleeper_id for p in find_players(_pool(), "pineiro")] == ["pineiro"]
    assert [p.sleeper_id for p in find_players(_pool(), "harrison")] == ["harrison"]


def test_find_players_ambiguous_query_returns_both_in_stable_order():
    """The Bijan/Brian Robinson case: silently returning one is the exact bug
    disambiguation exists to prevent (the wrong player leaves the board)."""
    result = find_players(_pool(), "robinson")
    assert {p.sleeper_id for p in result} == {"bijan", "brian"}
    assert len(result) == 2
    assert [p.sleeper_id for p in result] == [p.sleeper_id for p in find_players(_pool(), "robinson")]


def test_find_players_no_match_returns_empty_list_not_raise():
    assert find_players(_pool(), "zzz_nobody_by_this_name") == []


def test_mark_drafted_removes_from_pool_and_undo_restores_exactly_that_player():
    pool = _pool()
    state = MarkDrafted()
    state.mark("bijan")
    state.mark("gibbs")

    available_ids = {pid for pid in pool if pid not in state.drafted}
    assert available_ids == {"brian", "pineiro", "harrison"}

    state.undo()  # undoes gibbs, the most recently marked
    available_ids = {pid for pid in pool if pid not in state.drafted}
    assert "gibbs" in available_ids       # restored
    assert "bijan" not in available_ids   # still gone -- undo only touches the last mark


def test_mark_drafted_undo_on_empty_history_is_noop_and_does_not_raise():
    state = MarkDrafted()
    state.undo()
    assert state.drafted == set()
    state.mark("bijan")
    state.undo()
    state.undo()  # second undo: history is already empty
    assert state.drafted == set()


def test_mark_drafted_marking_already_marked_player_is_idempotent():
    """Discriminates against a mark() that pushes a duplicate history entry
    for an id already marked -- if it did, a single undo would not fully
    clear the id."""
    state = MarkDrafted()
    state.mark("bijan")
    state.mark("bijan")
    assert state.drafted == {"bijan"}
    state.undo()
    assert state.drafted == set()


def test_handle_command_single_match_marks_directly():
    pool = _pool()
    state = MarkDrafted()
    pending, pending_mine, status = _handle_command("gibbs", pool, state, [])
    assert pending == []
    assert pending_mine is False
    assert state.drafted == {"gibbs"}
    assert state.mine == set()             # plain mark, not a self-mark
    assert "Jahmyr Gibbs" in status


def test_handle_command_multiple_matches_opens_disambiguation_then_selects():
    pool = _pool()
    state = MarkDrafted()
    pending, pending_mine, status = _handle_command("robinson", pool, state, [])
    assert state.drafted == set()  # nothing marked yet -- ambiguous query alone never marks
    assert len(pending) == 2
    assert pending_mine is False

    pending2, pending_mine2, status2 = _handle_command("1", pool, state, pending, pending_mine)
    assert state.drafted == {pending[0].sleeper_id}
    assert pending2 == []


def test_handle_command_undo_via_u_or_undo():
    pool = _pool()
    state = MarkDrafted()
    _handle_command("gibbs", pool, state, [])
    _handle_command("undo", pool, state, [])
    assert state.drafted == set()


# --- Wiring my_roster from slot_to_roster_id so MARG is truthful. ---


def test_lookup_roster_id_is_none_when_draft_slot_unset():
    # Never guesses: no draft_slot means no lookup at all.
    assert _lookup_roster_id(_loop_league(draft_slot=None), _loop_settings()) is None


def test_lookup_roster_id_maps_configured_slot_to_roster_id(monkeypatch):
    league = _loop_league(draft_slot=3)
    settings = _loop_settings()
    monkeypatch.setattr(
        "ffhelper.cli.fetch_json",
        lambda url, key, **kw: {"slot_to_roster_id": {"3": 7, "1": 2}},
    )
    assert _lookup_roster_id(league, settings) == 7


def test_lookup_roster_id_degrades_to_none_on_fetch_failure(monkeypatch):
    league = _loop_league(draft_slot=3)
    settings = _loop_settings()

    def boom(*a, **kw):
        raise RuntimeError("network down")

    monkeypatch.setattr("ffhelper.cli.fetch_json", boom)
    assert _lookup_roster_id(league, settings) is None


def test_my_roster_from_picks_filters_by_roster_id():
    players = _loop_players()
    players["2"] = Player("2", "B", "WR", "ATL", proj_pts=50.0)
    picks = [Pick(pick_no=1, sleeper_id="1", roster_id=5), Pick(pick_no=2, sleeper_id="2", roster_id=9)]

    roster = _my_roster_from_picks(picks, players, roster_id=5)

    assert [p.sleeper_id for p in roster] == ["1"]


def test_my_roster_from_picks_empty_when_roster_id_none():
    picks = [Pick(pick_no=1, sleeper_id="1", roster_id=5)]
    assert _my_roster_from_picks(picks, _loop_players(), roster_id=None) == []


def test_render_tick_wires_my_roster_and_marg_reflects_it(monkeypatch):
    """CLI-level regression guard for the hardcoded-[] bug: with a full QB
    slot already on the user's roster, a high-projection QB candidate's
    marginal value must land strictly below his raw projection. Against the
    old `my_roster: list[Player] = []` hardcode this fails, because marginal
    would equal the raw 300.0 projection instead of 250.0.
    """
    players = {
        "qb1": Player("qb1", "Roster QB", "QB", "SF", proj_pts=50.0, adp=50.0, adp_stdev=5.0),
        "qb2": Player("qb2", "Candidate QB", "QB", "KC", proj_pts=300.0, adp=1.0, adp_stdev=1.0),
    }
    picks = [Pick(pick_no=1, sleeper_id="qb1", roster_id=5)]
    settings = LeagueSettings(num_teams=10, scoring={}, roster_slots={"QB": 1}, rounds=1, draft_id="d1")
    league = _loop_league(draft_slot=3)

    captured = {}

    def spy_render(board, *a, **kw):
        captured["board"] = board
        return "ok"

    monkeypatch.setattr("ffhelper.cli.render", spy_render)

    _render_tick(
        picks, time.time(), players, settings, league, Tunables(), 10,
        manual_gone=set(), manual_mine=set(), roster_id=5,
    )

    rows = {r.player.sleeper_id: r for r in captured["board"]}
    assert rows["qb2"].marginal == 250.0
    assert rows["qb2"].marginal < players["qb2"].proj_pts


def test_run_wires_manual_marks_into_the_board(monkeypatch, capsys):
    """Manual marks reach the board through the same `drafted` exclusion as
    feed picks -- `input_queue` is passed directly so no real stdin/thread is
    involved and nothing sleeps or blocks. If `_run` stopped draining the
    queue into `_handle_command`/`MarkDrafted`, this status line would never
    appear and the player would still show up on the board.
    """
    monkeypatch.setattr("ffhelper.cli.load_board_inputs",
                         lambda league, tunables: (_loop_players(), _loop_settings()))
    monkeypatch.setattr("ffhelper.cli.SleeperFeed", lambda draft_id: _FakeFeed(picks=[]))
    monkeypatch.setattr("ffhelper.cli.time.sleep", lambda s: None)

    q: queue.Queue = queue.Queue()
    q.put("A")  # matches the sole player in _loop_players(), id "1"

    result = _run(_loop_league(), Tunables(), limit=10, max_iterations=2, input_queue=q)
    out = capsys.readouterr().out

    assert result == 0
    assert "marked A (RB ATL)" in out
    # the board itself is empty now -- "A" was excluded, not just narrated
    assert "1   A " not in out


# --- Fix 1: `run` without a pick feed (no draft_id, or no feed for the platform). ---


def test_select_feed_uses_sleeper_feed_when_draft_id_resolved(monkeypatch):
    """Discriminates against a selector that always returns NullFeed, or one
    that instantiates SleeperFeed unconditionally regardless of platform."""
    sentinel = _FakeFeed()
    monkeypatch.setattr("ffhelper.cli.SleeperFeed", lambda draft_id: sentinel)
    feed, has_feed = _select_feed(_loop_league(), _loop_settings())
    assert feed is sentinel
    assert has_feed is True


def test_select_feed_uses_null_feed_when_no_draft_id():
    settings = LeagueSettings(num_teams=10, scoring={}, roster_slots={"QB": 1}, rounds=1,
                               draft_id=None)
    feed, has_feed = _select_feed(_loop_league(), settings)
    assert isinstance(feed, NullFeed)
    assert has_feed is False
    assert feed.get_picks() == []


def test_select_feed_uses_null_feed_for_non_sleeper_platform():
    """Even with a draft_id-shaped value present, a platform with no real feed
    implementation (Yahoo/ESPN/CBS/a friend's league) must not get SleeperFeed."""
    league = League(name="yahoo-main", platform="yahoo", league_id="1")
    settings = LeagueSettings(num_teams=10, scoring={}, roster_slots={"QB": 1}, rounds=1,
                               draft_id="some-id")
    feed, has_feed = _select_feed(league, settings)
    assert isinstance(feed, NullFeed)
    assert has_feed is False


def test_run_with_no_draft_id_starts_and_renders_a_board(monkeypatch, capsys):
    """Fix 1's core guarantee: `run` on a league with no draft_id (the Yahoo/
    ESPN/CBS/manual-league case) must render a full board instead of exiting
    early. Against the pre-fix `if not settings.draft_id: return 1` guard,
    this fails: result would be 1 and the player would never be printed.
    """
    settings = LeagueSettings(num_teams=10, scoring={"pass_td": 6.0}, roster_slots={"QB": 1},
                               rounds=1, draft_id=None)
    monkeypatch.setattr("ffhelper.cli.load_board_inputs",
                         lambda league, tunables: (_loop_players(), settings))
    monkeypatch.setattr("ffhelper.cli.time.sleep", lambda s: None)
    league = League(name="yahoo-main", platform="yahoo", league_id="1")

    result = _run(league, Tunables(), limit=10, max_iterations=2)
    out = capsys.readouterr().out

    assert result == 0
    assert "A" in out                      # the one player in _loop_players() rendered


def test_run_with_no_draft_id_shows_manual_status_and_no_stale_banner(monkeypatch, capsys):
    """Feed-less mode must say so plainly and must never show a stale-feed
    clock -- there is no feed to be stale. Against a build that leaves
    `last_ok` as a real timestamp when there is no feed, this fails because
    `stale_seconds` would be a tiny real number instead of None, and neither
    the manual line nor (once past 15s) the correct banner would show.
    """
    settings = LeagueSettings(num_teams=10, scoring={"pass_td": 6.0}, roster_slots={"QB": 1},
                               rounds=1, draft_id=None)
    monkeypatch.setattr("ffhelper.cli.load_board_inputs",
                         lambda league, tunables: (_loop_players(), settings))
    monkeypatch.setattr("ffhelper.cli.time.sleep", lambda s: None)
    league = League(name="yahoo-main", platform="yahoo", league_id="1")

    result = _run(league, Tunables(), limit=10, max_iterations=2)
    out = capsys.readouterr().out

    assert result == 0
    assert "MANUAL MODE" in out
    assert "FEED STALE" not in out


def test_run_sleeper_league_with_draft_id_is_unaffected_by_null_feed_path(monkeypatch, capsys):
    """A Sleeper league with a resolved draft_id must still use the real feed
    and must never show the manual-mode line. Against a build where feed
    selection is broken (e.g. always picks NullFeed), this fails: the fake
    feed would never be called and "MANUAL MODE" would incorrectly appear.
    """
    monkeypatch.setattr("ffhelper.cli.load_board_inputs",
                         lambda league, tunables: (_loop_players(), _loop_settings()))
    fake_feed = _FakeFeed(picks=[])
    monkeypatch.setattr("ffhelper.cli.SleeperFeed", lambda draft_id: fake_feed)
    monkeypatch.setattr("ffhelper.cli.time.sleep", lambda s: None)

    result = _run(_loop_league(), Tunables(), limit=10, max_iterations=1)
    out = capsys.readouterr().out

    assert result == 0
    assert fake_feed.calls == 1
    assert "MANUAL MODE" not in out


# --- Fix 2: marking a player as the user's own pick, explicitly. ---


def test_mark_drafted_mine_tracks_membership_separately_from_drafted():
    """`mine` must stay a subset of `drafted`, tracked independently -- a
    plain (non-self) mark must never leak into `mine`.
    """
    state = MarkDrafted()
    state.mark("bijan")              # plain mark: drafted, not mine
    state.mark("gibbs", mine=True)   # self mark: drafted AND mine
    assert state.drafted == {"bijan", "gibbs"}
    assert state.mine == {"gibbs"}


def test_mark_drafted_undo_reverses_self_mark():
    """undo() must remove a self-marked player from BOTH `drafted` and
    `mine`. Discriminates against an undo that only pops `_marked` but
    leaves a stale id sitting in `_mine`, which would leave a departed
    player permanently stuck in my_roster.
    """
    state = MarkDrafted()
    state.mark("bijan", mine=True)
    assert state.drafted == {"bijan"}
    assert state.mine == {"bijan"}

    state.undo()

    assert state.drafted == set()
    assert state.mine == set()


def test_handle_command_me_prefix_single_match_marks_as_mine():
    pool = _pool()
    state = MarkDrafted()
    pending, pending_mine, status = _handle_command("me gibbs", pool, state, [])
    assert pending == []
    assert state.drafted == {"gibbs"}
    assert state.mine == {"gibbs"}
    assert "yours" in status


def test_handle_command_me_prefix_ambiguous_query_opens_disambiguation_marks_nothing():
    """The self-mark path must disambiguate exactly like a plain mark does --
    "me robinson" matching both Bijan and Brian Robinson must never resolve
    silently. Against a build that marks the first match for "me " searches
    (skipping disambiguation because it only special-cased the plain path),
    this fails: state.drafted/mine would be non-empty after the first call.
    """
    pool = _pool()
    state = MarkDrafted()
    pending, pending_mine, status = _handle_command("me robinson", pool, state, [])
    assert state.drafted == set()          # nothing marked yet
    assert state.mine == set()
    assert pending_mine is True
    assert len(pending) == 2

    pending2, pending_mine2, status2 = _handle_command("1", pool, state, pending, pending_mine)
    assert state.drafted == {pending[0].sleeper_id}
    assert state.mine == {pending[0].sleeper_id}  # the chosen player is self-marked
    assert pending2 == []


def test_handle_command_plain_search_never_marks_as_mine():
    """Guards the "explicit only" rule the other direction: a search with no
    "me " prefix must never end up in `mine`, even for a single-match hit."""
    pool = _pool()
    state = MarkDrafted()
    _handle_command("gibbs", pool, state, [])
    assert state.mine == set()


def test_combine_my_roster_merges_feed_and_self_marked_without_double_counting():
    """A player the feed already reports under the user's roster_id, who was
    ALSO self-marked (e.g. marked on a hunch before the feed caught up), must
    appear exactly once in the combined roster -- never twice.
    """
    players = _loop_players()               # {"1": Player("1", "A", "RB", ...)}
    picks = [Pick(pick_no=1, sleeper_id="1", roster_id=5)]
    feed_roster = _my_roster_from_picks(picks, players, roster_id=5)

    combined = _combine_my_roster(feed_roster, mine_ids={"1"}, players=players)
    assert [p.sleeper_id for p in combined] == ["1"]


def test_combine_my_roster_adds_self_marked_players_the_feed_never_saw():
    """In feed-less mode `feed_roster` is always [] -- self-marked players
    must still surface in the combined roster."""
    players = _loop_players()
    combined = _combine_my_roster([], mine_ids={"1"}, players=players)
    assert [p.sleeper_id for p in combined] == ["1"]


def test_render_tick_self_mark_adds_to_my_roster_and_depresses_marg(monkeypatch):
    """CLI-level regression guard for Fix 2 in a feed-less draft: self-marking
    the player already filling the QB slot must both remove him from the pool
    and land him in my_roster, so a same-position candidate's marginal value
    drops below his raw projection. Against a build that only reads
    manual_gone (drops the player from the pool) but never folds manual_mine
    into my_roster, this fails: marginal would equal the raw 300.0 projection.
    """
    players = {
        "qb1": Player("qb1", "Roster QB", "QB", "SF", proj_pts=50.0, adp=50.0, adp_stdev=5.0),
        "qb2": Player("qb2", "Candidate QB", "QB", "KC", proj_pts=300.0, adp=1.0, adp_stdev=1.0),
    }
    settings = LeagueSettings(num_teams=10, scoring={}, roster_slots={"QB": 1}, rounds=1,
                               draft_id=None)
    league = _loop_league(draft_slot=None)

    captured = {}

    def spy_render(board, *a, **kw):
        captured["board"] = board
        return "ok"

    monkeypatch.setattr("ffhelper.cli.render", spy_render)

    _render_tick(
        [], None, players, settings, league, Tunables(), 10,
        manual_gone={"qb1"}, manual_mine={"qb1"}, roster_id=None,
    )

    rows = {r.player.sleeper_id: r for r in captured["board"]}
    assert "qb1" not in rows                       # removed from the available pool
    assert rows["qb2"].marginal == 250.0
    assert rows["qb2"].marginal < players["qb2"].proj_pts


def test_run_self_mark_via_me_prefix_reaches_my_roster_end_to_end(monkeypatch, capsys):
    """End-to-end: typing "me a" through `_run`'s input_queue (no feed, no
    real stdin) must both exclude the player from the board and list it under
    "my roster:" -- the same wiring `test_run_wires_manual_marks_into_the_board`
    checks for a plain mark, but for the self-mark path.
    """
    settings = LeagueSettings(num_teams=10, scoring={"pass_td": 6.0}, roster_slots={"QB": 1},
                               rounds=1, draft_id=None)
    monkeypatch.setattr("ffhelper.cli.load_board_inputs",
                         lambda league, tunables: (_loop_players(), settings))
    monkeypatch.setattr("ffhelper.cli.time.sleep", lambda s: None)
    league = League(name="yahoo-main", platform="yahoo", league_id="1")

    q: queue.Queue = queue.Queue()
    q.put("me a")

    result = _run(league, Tunables(), limit=10, max_iterations=2, input_queue=q)
    out = capsys.readouterr().out

    assert result == 0
    assert "my roster:  A (RB)" in out
    assert "1   A " not in out              # excluded from the ranked board


# --- Fix 4: a dead stdin reader must be logged, not silent. ---


def test_stdin_reader_logs_warning_when_stdin_closes(monkeypatch, caplog):
    """EOF (stdin closes, e.g. piped/redirected input) must not fail silently.
    Against the pre-fix bare `except Exception: pass` with no warning on a
    natural (non-exception) loop exit, this fails: no WARNING record at all.
    """
    monkeypatch.setattr("ffhelper.cli.sys.stdin", iter([]))
    with caplog.at_level(logging.WARNING, logger="ffhelper.cli"):
        _stdin_reader(queue.Queue())
    assert any("stdin" in rec.message.lower() for rec in caplog.records)


def test_stdin_reader_logs_warning_on_exception(monkeypatch, caplog):
    class _BoomStdin:
        def __iter__(self):
            raise RuntimeError("stdin gone")

    monkeypatch.setattr("ffhelper.cli.sys.stdin", _BoomStdin())
    with caplog.at_level(logging.WARNING, logger="ffhelper.cli"):
        _stdin_reader(queue.Queue())
    assert any("stdin" in rec.message.lower() for rec in caplog.records)


# --- Fix 5: current pick derived from ALL drafted players (feed union manual),
# not from the feed's pick list alone -- the frozen-pick-1 bug. ---


def _five_player_pool() -> dict[str, Player]:
    """Distinct, letters-only names -- `norm_name` strips digits entirely, so
    "Player 1".."Player 5" would all collapse to the same normalised token and
    become ambiguous. `target` is never marked in any of the tests below; it
    exists purely so its own survival probability can be read back."""
    names = ["Aardvark", "Bobcat", "Cougar", "Dingo"]
    fillers = {
        str(i): Player(str(i), n, "RB", "ATL", proj_pts=100.0 - i, adp=float(i), adp_stdev=1.0)
        for i, n in enumerate(names, 1)
    }
    fillers["target"] = Player("target", "Zeta Target", "RB", "ATL", proj_pts=90.0,
                                adp=40.0, adp_stdev=5.0)
    return fillers


def test_render_tick_manual_marks_advance_pick_and_undo_reverses_it(monkeypatch, capsys):
    """Drives the exact per-tick pipeline `_run` uses -- `_handle_command`
    feeding a persistent `MarkDrafted`, then `_render_tick` reading its
    `.drafted` set -- across four marks and an undo, and reads the reported
    pick number back out of the printed footer.

    Against the frozen-counter bug (`current_pick=len(picks) + 1`, and
    `picks` is permanently `[]` in manual mode since there is no feed), the
    footer would read "pick 1" on every single tick below, marks or no marks,
    and this test fails on the very first advancing assertion.
    """
    players = _five_player_pool()
    settings = LeagueSettings(num_teams=10, scoring={}, roster_slots={"RB": 1}, rounds=1,
                               draft_id=None)
    league = _loop_league(draft_slot=3)  # draft_slot needed for the footer line to print
    state = MarkDrafted()
    pending: list[Player] = []
    pending_mine = False

    def tick() -> str:
        capsys.readouterr()
        _render_tick([], None, players, settings, league, Tunables(), 10,
                     state.drafted, state.mine, roster_id=None)
        return capsys.readouterr().out

    assert "pick 1   your next pick" in tick()

    for name in ["Aardvark", "Bobcat", "Cougar", "Dingo"]:
        pending, pending_mine, _ = _handle_command(name, players, state, pending, pending_mine)

    assert "pick 5   your next pick" in tick()   # 4 marks -> current_pick advances to 5

    state.undo()
    assert "pick 4   your next pick" in tick()   # undo restores exactly one pick


def test_render_tick_self_mark_advances_pick_count_same_as_plain_mark(monkeypatch, capsys):
    """A `me <query>` self-mark takes a player off the board exactly like a
    plain mark -- it must consume a pick in the count too. Against a build
    that only unions `manual_gone` for the available-pool filter but keeps
    computing `current_pick` from `len(picks)` alone, this fails: the footer
    would stay on "pick 1" after the self-mark.
    """
    players = _five_player_pool()
    settings = LeagueSettings(num_teams=10, scoring={}, roster_slots={"RB": 1}, rounds=1,
                               draft_id=None)
    league = _loop_league(draft_slot=3)
    state = MarkDrafted()

    _handle_command("me Aardvark", players, state, [], False)

    capsys.readouterr()
    _render_tick([], None, players, settings, league, Tunables(), 10,
                 state.drafted, state.mine, roster_id=None)
    out = capsys.readouterr().out

    assert "pick 2   your next pick" in out


def test_render_tick_survival_decreases_as_manual_marks_accumulate(monkeypatch):
    """The core regression guard: a player who is never marked must see his
    OWN survival probability strictly decrease once several other players are
    marked drafted between ticks, because `at_pick` (derived from
    `current_pick`) is moving forward under him.

    Verified this fails against the frozen-counter behaviour: with
    `current_pick=len(picks) + 1` and `picks` always `[]` in manual mode,
    `current_pick` -- and therefore `at_pick` fed into `survival_prob` --
    is bit-for-bit identical on both calls below regardless of how many
    players get marked in between, so `before == after` and the `<`
    assertion fails (97%/100%/100% all draft long, exactly as observed
    against the real loop).
    """
    players = _five_player_pool()
    settings = LeagueSettings(num_teams=10, scoring={}, roster_slots={"RB": 1}, rounds=1,
                               draft_id=None)
    league = _loop_league(draft_slot=None)

    captured = []

    def spy_render(board, *a, **kw):
        captured.append({r.player.sleeper_id: r.survival for r in board})
        return "ok"

    monkeypatch.setattr("ffhelper.cli.render", spy_render)

    state = MarkDrafted()
    _render_tick([], None, players, settings, league, Tunables(), 10,
                 state.drafted, state.mine, roster_id=None)
    before = captured[0]["target"]

    for pid in ["1", "2", "3", "4"]:
        state.mark(pid)
    _render_tick([], None, players, settings, league, Tunables(), 10,
                 state.drafted, state.mine, roster_id=None)
    after = captured[1]["target"]

    assert after < before


def test_render_tick_feed_only_pick_count_matches_feed_with_no_manual_marks(capsys):
    """Sleeper-with-a-real-feed guarantee: with no manual marks at all, the
    reported pick count must equal the feed's own pick count exactly --
    `len(picks) + 1`, unchanged from before this fix. Against a build that
    (over-)counts differently (e.g. double-counts, or adds 1 twice), this
    fails on the exact footer text.
    """
    players = _five_player_pool()
    settings = LeagueSettings(num_teams=10, scoring={}, roster_slots={"RB": 1}, rounds=1,
                               draft_id="d1")
    league = _loop_league(draft_slot=3)
    picks = [
        Pick(pick_no=1, sleeper_id="1", roster_id=None),
        Pick(pick_no=2, sleeper_id="2", roster_id=None),
        Pick(pick_no=3, sleeper_id="3", roster_id=None),
    ]

    _render_tick(picks, time.time(), players, settings, league, Tunables(), 10,
                 manual_gone=set(), manual_mine=set(), roster_id=None)
    out = capsys.readouterr().out

    assert "pick 4   your next pick" in out    # len(picks) + 1, no manual marks in play


def test_run_action_status_shows_on_its_tick_and_is_gone_the_next(monkeypatch, capsys):
    """The transient action confirmation (e.g. "marked A (RB ATL)") must be
    shown for the tick the action happened on and cleared afterward. A single
    command is queued before the loop starts, so it is drained and marked on
    the FIRST tick only; the SECOND tick has nothing new in the queue.

    Against the pre-fix code -- where `status` is a variable outside the loop
    that is only ever overwritten, never reset, so an empty queue leaves it
    holding the previous tick's value -- the confirmation would print on
    BOTH of the two rendered frames and `out.count(...)` would be 2, not 1.
    """
    monkeypatch.setattr("ffhelper.cli.load_board_inputs",
                         lambda league, tunables: (_loop_players(), _loop_settings()))
    monkeypatch.setattr("ffhelper.cli.SleeperFeed", lambda draft_id: _FakeFeed(picks=[]))
    monkeypatch.setattr("ffhelper.cli.time.sleep", lambda s: None)

    q: queue.Queue = queue.Queue()
    q.put("A")  # matches the sole player in _loop_players(), id "1"

    result = _run(_loop_league(), Tunables(), limit=10, max_iterations=2, input_queue=q)
    out = capsys.readouterr().out

    assert result == 0
    assert out.count("marked A (RB ATL)") == 1


def test_current_pick_follows_the_feeds_highest_pick_no_not_the_row_count(capsys):
    """`parse_sleeper_picks` drops malformed rows, so counting surviving picks
    permanently shifts the draft horizon back by one for every row dropped --
    every survival and VONA number is then computed against the wrong pick.

    Two picks arrive numbered 1 and 3 (pick 2's row was malformed and skipped).
    The board is on pick 4. Against the count-only code it says pick 3.
    """
    _render_tick(
        picks=[Pick(pick_no=1, sleeper_id="1"), Pick(pick_no=3, sleeper_id="2")],
        last_ok=time.time(), players=_two_robinsons(), settings=_loop_settings(),
        league=_loop_league(draft_slot=1), tunables=Tunables(), limit=5,
        manual_gone=set(), manual_mine=set(), roster_id=None,
    )
    assert "pick 4 " in capsys.readouterr().out


def test_disambiguation_accepts_only_real_decimal_digits():
    """Found by mutation testing: reverting `isdecimal()` to `isdigit()` in
    `_handle_command` left the full suite green, because the loop-level guard
    added alongside it swallows the ValueError -- so the loop-survival test
    passes either way and proves nothing about the parse.

    This drives `_handle_command` directly, with no guard in the way: '²' must
    be treated as a NEW SEARCH (isdigit True, isdecimal False), never fed to
    int(). Under `isdigit()` this raises ValueError instead of returning.
    """
    pool = _two_robinsons()
    state = MarkDrafted()
    pending = list(pool.values())

    new_pending, _, status = _handle_command("²", pool, state, pending)

    assert state.drafted == set()          # nothing was marked
    assert "no match" in status            # fell through to the search branch
    assert new_pending == []


def test_remarking_your_own_pick_as_a_plain_mark_cannot_desync_mine_from_drafted():
    """Found by mutation testing: deleting the idempotency guard in
    `MarkDrafted.mark` left the full suite green.

    The guard matters for one specific interleaving. "me gibbs" then later
    "gibbs" (easy to do out of habit at the clock) pushes a second history
    entry carrying mine=False. Undo then pops THAT entry: it discards from
    `_marked` but -- because the entry says mine=False -- leaves `_mine`
    holding the player. He is now absent from `drafted` while still in `mine`,
    so he is back on the board AND still counted in `my_roster`, which is what
    MARG is computed against.

    The guard makes the second mark a no-op, so undo reverses the original.
    """
    state = MarkDrafted()
    state.mark("a", mine=True)
    state.mark("a", mine=False)          # no-op under the guard
    state.undo()

    assert state.drafted == set()
    assert state.mine == set(), "mine must never outlive drafted"


def _two_robinsons():
    return {
        "1": Player("1", "Bijan Robinson", "RB", "ATL", proj_pts=300.0, adp=2.0, adp_stdev=1.0),
        "2": Player("2", "Brian Robinson", "RB", "WAS", proj_pts=180.0, adp=60.0, adp_stdev=8.0),
    }


def test_superscript_digit_at_a_disambiguation_prompt_does_not_kill_the_loop(monkeypatch):
    """`str.isdigit()` is True for '²' but `int('²')` raises ValueError.

    Against the pre-fix code the drain sits outside both try blocks, so that
    ValueError propagates straight out of `_run` on the first tick -- the user
    loses the board mid-draft with their pick clock running. This test fails
    with that ValueError instead of observing a clean return.
    """
    monkeypatch.setattr("ffhelper.cli.load_board_inputs",
                         lambda league, tunables: (_two_robinsons(), _loop_settings()))
    monkeypatch.setattr("ffhelper.cli.SleeperFeed", lambda draft_id: _FakeFeed(picks=[]))
    monkeypatch.setattr("ffhelper.cli.time.sleep", lambda s: None)

    q: queue.Queue = queue.Queue()
    q.put("robinson")   # ambiguous -> opens the disambiguation list
    q.put("²")     # isdigit() True, int() raises

    assert _run(_loop_league(), Tunables(), limit=10, max_iterations=2, input_queue=q) == 0


def test_a_raising_command_leaves_the_rest_of_the_queue_drainable(monkeypatch, capsys):
    """The drain's guard must not abandon the queue: a later valid command on
    the same tick still has to be processed."""
    monkeypatch.setattr("ffhelper.cli.load_board_inputs",
                         lambda league, tunables: (_two_robinsons(), _loop_settings()))
    monkeypatch.setattr("ffhelper.cli.SleeperFeed", lambda draft_id: _FakeFeed(picks=[]))
    monkeypatch.setattr("ffhelper.cli.time.sleep", lambda s: None)

    calls = {"n": 0}
    real = _handle_command

    def flaky(line, pool, mark_state, pending, pending_mine=False):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("boom")
        return real(line, pool, mark_state, pending, pending_mine)

    monkeypatch.setattr("ffhelper.cli._handle_command", flaky)

    q: queue.Queue = queue.Queue()
    q.put("bijan")
    q.put("brian")

    result = _run(_loop_league(), Tunables(), limit=10, max_iterations=1, input_queue=q)
    out = capsys.readouterr().out

    assert result == 0
    assert calls["n"] == 2
    assert "marked Brian Robinson" in out
