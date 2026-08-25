import queue
import time

import pytest

from ffhelper.cli import (
    MarkDrafted, _handle_command, _lookup_roster_id, _my_roster_from_picks, _preflight,
    _render_tick, _run, find_players, load_board_inputs, league_settings_from_config, main,
    render, resolve_settings,
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
    real_time = time.time
    seeded = {"done": False}

    def fake_time():
        if not seeded["done"]:
            seeded["done"] = True
            return real_time() - 30
        return real_time()

    monkeypatch.setattr("ffhelper.cli.time.time", fake_time)

    result = _run(_loop_league(), Tunables(), limit=10, max_iterations=3)
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
    pending, status = _handle_command("gibbs", pool, state, [])
    assert pending == []
    assert state.drafted == {"gibbs"}
    assert "Jahmyr Gibbs" in status


def test_handle_command_multiple_matches_opens_disambiguation_then_selects():
    pool = _pool()
    state = MarkDrafted()
    pending, status = _handle_command("robinson", pool, state, [])
    assert state.drafted == set()  # nothing marked yet -- ambiguous query alone never marks
    assert len(pending) == 2

    pending2, status2 = _handle_command("1", pool, state, pending)
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
        manual_gone=set(), roster_id=5,
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
