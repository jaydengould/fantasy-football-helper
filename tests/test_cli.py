import itertools
import json
import logging
import queue
import time

import pytest

from ffhelper.cli import (
    MarkDrafted, NullFeed, _claims_overruled_by_feed, _combine_my_roster, _draft_log_path,
    _handle_command, _restore_marks, _split_commands, _wait_for_input,
    _my_roster_from_picks, _preflight, _render_tick, _run, _select_feed, _stdin_reader,
    find_players, load_board_inputs, league_settings_from_config, main, render, resolve_settings,
)
from ffhelper.config import League, Tunables
from ffhelper.data import LeagueSettings, Player
from ffhelper.feeds import Pick
from ffhelper.value import Row, build_board


@pytest.fixture(autouse=True)
def _isolate_draft_log(tmp_path, monkeypatch):
    """Never let a test write into the real `.draft/`.

    Without this, `_run` tests journal marks to the repo and the NEXT test that
    calls `_run` restores them -- which is exactly how this was found: a feed
    staleness test started failing because it inherited two marks from an
    unrelated test earlier in the same run.
    """
    monkeypatch.setattr("ffhelper.cli.DRAFT_LOG_DIR", tmp_path / ".draft")
    # `_draft_log_path` calls date.today(), which consumes a time.time() read.
    # `test_run_survives_feed_failure...` fakes only the FIRST time.time() to
    # seed last_ok 30s in the past, so that extra read stole the seed and the
    # stale banner never fired. Pinning the path keeps the clock fake honest.
    monkeypatch.setattr("ffhelper.cli._draft_log_path",
                        lambda league: tmp_path / ".draft" / f"{league.name}.jsonl")


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


def test_render_says_so_when_every_pick_is_a_bench_pick():
    """Degrade, never fabricate. Once every starting slot is full, no player
    improves the lineup, so the residual ordering carries no information -- at
    pick 164 of the Task 13 mock that state produced a confident case for a
    third quarterback, then a second kicker. The board must say the signal is
    gone rather than present the order as advice."""
    bench = [Row(player=Player("a", "Backup Guy", "QB", "SF", adp=170.0, adp_stdev=20.0),
                 vbd=5.0, vona=0.0, marginal=0.0, tier=1, survival=0.9, divergence=0)]
    out = render(bench, limit=5, stale_seconds=0.0, my_roster=[], runs={})
    assert "STARTING LINEUP FULL" in out
    assert "BENCH" in out

    helpful = [Row(player=Player("b", "Real Starter", "RB", "SF", adp=40.0, adp_stdev=5.0),
                   vbd=50.0, vona=10.0, marginal=80.0, tier=1, survival=0.4, divergence=0)]
    assert "STARTING LINEUP FULL" not in render(helpful, 5, 0.0, [], {})


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


def test_draft_id_override_repoints_the_feed_but_keeps_the_leagues_scoring(monkeypatch):
    """A Sleeper MOCK draft has a draft_id but no league of its own, so its
    settings cannot be fetched. `league.draft_id` borrows the real league's
    synced scoring and roster and overrides only where picks come from -- which
    is what makes a mock draft usable as a rehearsal for the real one.

    Without the override the feed would poll the real league's draft, which sits
    in `pre_draft` returning zero picks forever, and the mock would never appear.
    """
    api = LeagueSettings(
        num_teams=12, scoring={"pass_td": 6.0}, roster_slots={"QB": 1}, rounds=1,
        draft_id="real-draft",
    )
    monkeypatch.setattr("ffhelper.cli.load_sleeper_settings", lambda league_id: api)
    league = League(name="mock", platform="sleeper", league_id="1", draft_id="mock-draft")

    got = resolve_settings(league)

    assert got.draft_id == "mock-draft"
    assert got.scoring == {"pass_td": 6.0}, "scoring must still be the league's"
    assert got.num_teams == 12


def test_no_draft_id_override_leaves_settings_exactly_as_synced(monkeypatch):
    """The override must be inert when unset -- the real league path is unchanged."""
    api = LeagueSettings(
        num_teams=12, scoring={"pass_td": 6.0}, roster_slots={"QB": 1}, rounds=1,
        draft_id="real-draft",
    )
    monkeypatch.setattr("ffhelper.cli.load_sleeper_settings", lambda league_id: api)
    league = League(name="sleeper-main", platform="sleeper", league_id="1")
    assert resolve_settings(league) is api


def _adp_source_fixture(monkeypatch, calls):
    """Sleeper ADP puts the player at 10.0; FFC would move him to 90.0."""
    players = {"1": Player("1", "Guy", "WR", "SF")}
    monkeypatch.setattr("ffhelper.cli.load_players", lambda: players)
    monkeypatch.setattr("ffhelper.cli.load_projections",
                         lambda season: [{"player_id": "1", "stats": {"rec": 100.0, "adp_ppr": 10.0}}])
    monkeypatch.setattr("ffhelper.cli.load_ffc_adp", lambda f, t, y: [
        {"name": "Guy", "position": "WR", "team": "SF", "adp": 90.0, "stdev": 7.0, "bye": 9}])
    monkeypatch.setattr(
        "ffhelper.cli.resolve_settings",
        lambda lg, season=None: LeagueSettings(
            num_teams=12, scoring={"rec": 1.0}, roster_slots={"WR": 1}, rounds=1, draft_id="d"),
    )
    return players


def test_adp_source_ffc_lets_ffc_overwrite_the_sleeper_baseline(monkeypatch):
    _adp_source_fixture(monkeypatch, [])
    league = League(name="l", platform="sleeper", league_id="1", adp_source="ffc")
    out, _ = load_board_inputs(league, Tunables())
    assert out["1"].adp == pytest.approx(90.0)
    assert out["1"].adp_stdev == pytest.approx(7.0)


def test_adp_source_sleeper_keeps_the_sleeper_adp_but_still_takes_the_bye(monkeypatch):
    """Survival is only as good as its ADP mean, so the source is a per-league
    knob. But bye weeks come from FFC and nowhere else -- Sleeper's player DB
    has no bye field -- so the FFC join must still run for enrichment even when
    it is not allowed to touch adp.

    Against an implementation that simply skips apply_ffc_adp, `bye` is None
    and this fails.
    """
    _adp_source_fixture(monkeypatch, [])
    league = League(name="l", platform="sleeper", league_id="1", adp_source="sleeper")
    out, _ = load_board_inputs(league, Tunables())
    assert out["1"].adp == pytest.approx(10.0), "Sleeper's ADP must survive"
    assert out["1"].bye == 9, "but the bye week still comes from FFC"


def test_unknown_adp_source_fails_loudly_naming_the_league(monkeypatch):
    """An unknown value must raise at load, not silently fall through to FFC
    partway through a draft."""
    _adp_source_fixture(monkeypatch, [])
    league = League(name="typo-league", platform="sleeper", league_id="1", adp_source="yahoo")
    with pytest.raises(ValueError, match="typo-league"):
        load_board_inputs(league, Tunables())


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
    monkeypatch.setattr("ffhelper.cli.apply_ffc_adp", lambda players, rows, set_adp=True: ["AMBIGUOUS: Robinson"])

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


def _instant_ticks(monkeypatch):
    """Drive `_run`'s loop with no real waiting.

    Two things have to be faked together, not one. The loop blocks on the input
    QUEUE (so typing wakes it immediately) but polls the feed on a monotonic
    DEADLINE (so a keystroke does not become a network request). Stubbing only
    the wait would spin iterations while the clock stood still, and the feed
    would be polled once for the whole test. Advancing the clock by more than
    any poll interval per call makes each test iteration equivalent to one real
    interval elapsing, which is what these tests mean by a tick.
    """
    monkeypatch.setattr("ffhelper.cli._wait_for_input", lambda q, timeout: None)
    clock = itertools.count(0.0, 1000.0)
    monkeypatch.setattr("ffhelper.cli.time.monotonic", lambda: next(clock))


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
    _instant_ticks(monkeypatch)

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
    _instant_ticks(monkeypatch)

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


def test_board_says_you_are_on_the_clock_only_on_your_own_pick(capsys):
    """Reported from the live mock: no indication of whose pick it is. Seat 3 in
    a 10-team snake owns picks 3, 18, 23 ... With 2 players gone the board is on
    pick 3 -- yours. With 3 gone it is on pick 4 -- not yours."""
    players = {str(i): Player(str(i), f"P{i}", "RB", "SF", proj_pts=100.0 - i,
                              adp=float(i), adp_stdev=3.0) for i in range(1, 6)}
    common = dict(last_ok=time.time(), players=players, settings=_loop_settings(),
                  league=_loop_league(draft_slot=3), tunables=Tunables(), limit=5,
                  manual_mine=set(), my_slot=None)

    _render_tick(picks=[], manual_gone={"1", "2"}, **common)
    assert "PICK 3 IS YOURS" in capsys.readouterr().out

    _render_tick(picks=[], manual_gone={"1", "2", "3"}, **common)
    out = capsys.readouterr().out
    assert "IS YOURS" not in out
    assert "your next pick: 18" in out


def test_identical_ticks_are_not_redrawn(monkeypatch):
    """Reported from the live mock: a full screen clear every 5 seconds is
    unreadable churn -- you cannot tell a real update from a repaint. Polling
    still happens every tick; only the redraw is skipped when nothing changed.
    """
    monkeypatch.setattr("ffhelper.cli.load_board_inputs",
                         lambda league, tunables: (_loop_players(), _loop_settings()))
    fake_feed = _FakeFeed(picks=[])
    monkeypatch.setattr("ffhelper.cli.SleeperFeed", lambda draft_id: fake_feed)
    _instant_ticks(monkeypatch)

    draws = {"n": 0}
    real = _render_tick

    def counting(*a, **kw):
        draws["n"] += 1
        return real(*a, **kw)

    monkeypatch.setattr("ffhelper.cli._render_tick", counting)

    _run(_loop_league(), Tunables(), limit=10, max_iterations=4, input_queue=queue.Queue())

    assert draws["n"] == 1, "nothing changed across 4 ticks -- draw once"
    assert fake_feed.calls == 4, "but keep polling every tick"


def test_a_new_pick_forces_a_redraw(monkeypatch):
    """The dedup must not suppress real updates."""
    monkeypatch.setattr("ffhelper.cli.load_board_inputs",
                         lambda league, tunables: (_loop_players(), _loop_settings()))
    _instant_ticks(monkeypatch)

    class GrowingFeed:
        def __init__(self):
            self.n = 0

        def get_picks(self):
            self.n += 1
            return [Pick(pick_no=i, sleeper_id="1", draft_slot=i) for i in range(1, self.n + 1)]

    monkeypatch.setattr("ffhelper.cli.SleeperFeed", lambda draft_id: GrowingFeed())

    draws = {"n": 0}
    real = _render_tick
    monkeypatch.setattr("ffhelper.cli._render_tick",
                         lambda *a, **kw: (draws.__setitem__("n", draws["n"] + 1), real(*a, **kw))[1])

    _run(_loop_league(), Tunables(), limit=10, max_iterations=3, input_queue=queue.Queue())

    assert draws["n"] == 3


def test_preflight_reports_ok_with_reachable_feed(monkeypatch, capsys):
    monkeypatch.setattr("ffhelper.cli.load_board_inputs",
                         lambda league, tunables: (_loop_players(), _loop_settings()))
    monkeypatch.setattr("ffhelper.cli.SleeperFeed", lambda draft_id: _FakeFeed(picks=[]))
    monkeypatch.setattr("ffhelper.cli.load_nfl_state",
                         lambda: {"week": 1, "season": "2026", "season_type": "regular"})
    monkeypatch.setattr("ffhelper.cli.load_league_rosters", lambda league_id: [])

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
    monkeypatch.setattr("ffhelper.cli.load_nfl_state",
                         lambda: {"week": 1, "season": "2026", "season_type": "regular"})
    monkeypatch.setattr("ffhelper.cli.load_league_rosters", lambda league_id: [])

    result = _preflight(_loop_league(draft_slot=13), Tunables())   # _loop_settings is 10 teams
    out = capsys.readouterr().out

    assert result == 1
    assert "OUT OF RANGE" in out
    assert "PREFLIGHT INCOMPLETE" in out


def test_preflight_reports_the_week_and_the_roster(monkeypatch, capsys):
    """preflight is the thing you run before trusting the output. Season mode
    adds three new ways to be silently wrong -- the wrong week, no roster, and
    someone else's roster -- so the week and the roster must both appear."""
    monkeypatch.setattr("ffhelper.cli.load_board_inputs",
                        lambda league, tunables: (_loop_players(), _loop_settings()))
    monkeypatch.setattr("ffhelper.cli.SleeperFeed", lambda draft_id: _FakeFeed(picks=[]))
    monkeypatch.setattr("ffhelper.cli.load_nfl_state",
                        lambda: {"week": 3, "season": "2026", "season_type": "regular"})
    monkeypatch.setattr("ffhelper.cli.load_league_rosters",
                        lambda league_id: [{"roster_id": 1, "players": ["1"]},
                                           {"roster_id": 2, "players": ["2"]}])
    # Non-empty rosters mean the new projections-join check would otherwise
    # make a real network call -- mocked here to keep this test hermetic.
    monkeypatch.setattr("ffhelper.cli.load_weekly_projections", lambda season, week: [])

    result = _preflight(_loop_league(draft_slot=3), Tunables())
    out = capsys.readouterr().out

    assert result == 0
    assert "nfl week        : 3" in out
    assert "2 teams" in out
    assert "PREFLIGHT OK" in out


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
    monkeypatch.setattr("ffhelper.cli.apply_ffc_adp", lambda p, rows, set_adp=True: [])
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
    _instant_ticks(monkeypatch)

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
    pending, pending_action, status = _handle_command("gibbs", pool, state, [])
    assert pending == []
    assert pending_action == ""
    assert state.drafted == {"gibbs"}
    assert state.mine == set()             # plain mark, not a self-mark
    assert "Jahmyr Gibbs" in status


def test_handle_command_multiple_matches_opens_disambiguation_then_selects():
    pool = _pool()
    state = MarkDrafted()
    pending, pending_action, status = _handle_command("robinson", pool, state, [])
    assert state.drafted == set()  # nothing marked yet -- ambiguous query alone never marks
    assert len(pending) == 2
    assert pending_action == ""

    pending2, pending_action2, status2 = _handle_command("1", pool, state, pending, pending_action)
    assert state.drafted == {pending[0].sleeper_id}
    assert pending2 == []


def test_handle_command_undo_via_u_or_undo():
    pool = _pool()
    state = MarkDrafted()
    _handle_command("gibbs", pool, state, [])
    _handle_command("undo", pool, state, [])
    assert state.drafted == set()


# --- Wiring my_roster from the user's own draft_slot so MARG is truthful. ---


def test_my_roster_from_picks_filters_by_draft_slot():
    players = _loop_players()
    players["2"] = Player("2", "B", "WR", "ATL", proj_pts=50.0)
    picks = [Pick(pick_no=1, sleeper_id="1", draft_slot=5),
             Pick(pick_no=2, sleeper_id="2", draft_slot=9)]

    roster = _my_roster_from_picks(picks, players, my_slot=5)

    assert [p.sleeper_id for p in roster] == ["1"]


def test_my_roster_from_picks_uses_draft_slot_when_roster_id_is_absent():
    """The Task 13 defect, found in a real 180-pick mock draft.

    Sleeper mock drafts return `roster_id: None` on EVERY pick while populating
    `draft_slot` normally. Matching on roster_id therefore produced an empty
    my_roster for the entire draft, silently -- and an empty roster makes MARG
    meaningless, which is what let the board keep recommending a quarterback
    after one had already been drafted.

    Against the roster_id version this returns [] and fails.
    """
    players = _loop_players()
    players["2"] = Player("2", "B", "WR", "ATL", proj_pts=50.0)
    picks = [Pick(pick_no=1, sleeper_id="1", roster_id=None, draft_slot=5),
             Pick(pick_no=2, sleeper_id="2", roster_id=None, draft_slot=9)]

    roster = _my_roster_from_picks(picks, players, my_slot=5)

    assert [p.sleeper_id for p in roster] == ["1"]


def test_my_roster_from_picks_empty_when_slot_unset():
    picks = [Pick(pick_no=1, sleeper_id="1", draft_slot=5)]
    assert _my_roster_from_picks(picks, _loop_players(), my_slot=None) == []


def test_my_roster_from_picks_warns_when_no_pick_carries_a_slot(caplog):
    """Degrade, never fabricate: an empty roster is indistinguishable from
    "you have not picked yet", and that silence is how the roster_id version
    hid for an entire draft. If no pick carries a slot at all, say so."""
    picks = [Pick(pick_no=1, sleeper_id="1", roster_id=3, draft_slot=None)]
    with caplog.at_level(logging.WARNING):
        assert _my_roster_from_picks(picks, _loop_players(), my_slot=5) == []
    assert "draft_slot" in caplog.text


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
    picks = [Pick(pick_no=1, sleeper_id="qb1", draft_slot=5)]
    settings = LeagueSettings(num_teams=10, scoring={}, roster_slots={"QB": 1}, rounds=1, draft_id="d1")
    league = _loop_league(draft_slot=3)

    captured = {}

    def spy_render(board, *a, **kw):
        captured["board"] = board
        return "ok"

    monkeypatch.setattr("ffhelper.cli.render", spy_render)

    _render_tick(
        picks, time.time(), players, settings, league, Tunables(), 10,
        manual_gone=set(), manual_mine=set(), my_slot=5,
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
    _instant_ticks(monkeypatch)

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
    _instant_ticks(monkeypatch)
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
    _instant_ticks(monkeypatch)
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
    _instant_ticks(monkeypatch)

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


def test_mark_drafted_claiming_an_already_marked_player_still_reaches_mine():
    """Recording a pick and THEN realising it was your own must still claim it.

    The idempotency guard used to drop the whole call when the id was already
    in `drafted`, so the `mine=True` was silently discarded -- the tool printed
    "as yours" while `mine` stayed empty, and MARG was then computed against a
    roster missing the user's own player. That is Task 13 defect #1 arriving by
    a different route, and it is silent, which makes it worse than a crash.
    """
    state = MarkDrafted()
    state.mark("bijan")                      # recorded as somebody's pick
    state.mark("bijan", mine=True)           # ...actually it was mine
    assert state.drafted == {"bijan"}
    assert state.mine == {"bijan"}


def test_mark_drafted_undo_reverses_only_the_claim_not_the_whole_mark():
    """Undo must reverse exactly what the last call changed.

    After a plain mark then a claim, one undo takes back the CLAIM only -- the
    player is still drafted, just no longer yours. A second undo removes him
    from the board. Discriminates against an undo that pops the id out of
    `drafted` too, which would put a genuinely drafted player back on the board
    mid-draft.
    """
    state = MarkDrafted()
    state.mark("bijan")
    state.mark("bijan", mine=True)

    state.undo()
    assert state.drafted == {"bijan"}        # still gone from the board
    assert state.mine == set()               # but no longer counted as yours

    state.undo()
    assert state.drafted == set()


def test_handle_command_claim_after_plain_mark_reports_truthfully():
    """The status line must not claim something the state does not reflect."""
    pool = _pool()
    state = MarkDrafted()
    _handle_command("gibbs", pool, state, [])
    _, _, status = _handle_command("me gibbs", pool, state, [])
    assert "yours" in status
    assert state.mine == {"gibbs"}


def test_mark_drafted_unmark_puts_a_player_back_and_undo_restores_the_mark():
    """Targeted take-back: `unmark` must clear BOTH sets for one player without
    disturbing anything else, and `u` must put the mark back exactly as it was
    -- including whether it was claimed as yours."""
    state = MarkDrafted()
    state.mark("bijan")
    state.mark("gibbs", mine=True)

    state.unmark("gibbs")
    assert state.drafted == {"bijan"}
    assert state.mine == set()

    state.undo()
    assert state.drafted == {"bijan", "gibbs"}
    assert state.mine == {"gibbs"}          # the claim comes back too


def test_mark_drafted_unmark_of_an_unmarked_player_is_a_noop_with_no_history():
    """Discriminates against an unmark that pushes a history entry regardless --
    a stray `-typo` would then eat the next `u`, silently leaving a real mistake
    in place while the user believes they undid it."""
    state = MarkDrafted()
    state.mark("bijan")
    state.unmark("gibbs")                   # never marked
    state.undo()
    assert state.drafted == set()           # the undo reversed the BIJAN mark


def test_handle_command_unmark_prefix_takes_a_player_back():
    pool = _pool()
    state = MarkDrafted()
    _handle_command("gibbs", pool, state, [])
    pending, action, status = _handle_command("-gibbs", pool, state, [])
    assert pending == []
    assert action == ""
    assert state.drafted == set()
    assert "unmarked" in status.lower()


def test_handle_command_unmark_searches_only_marked_players():
    """`-robinson` must not open a Bijan/Brian disambiguation when only one of
    them is marked. Scoping the search to what is actually marked is both fewer
    keystrokes against the clock and fewer chances to take back the wrong man.
    """
    pool = _pool()
    state = MarkDrafted()
    _handle_command("bijan", pool, state, [])
    pending, _, status = _handle_command("-robinson", pool, state, [])
    assert pending == []                    # resolved outright, no prompt
    assert state.drafted == set()
    assert "Bijan" in status


def test_handle_command_unmark_still_disambiguates_when_both_are_marked():
    """Scoping narrows the field; it never bypasses disambiguation. With both
    Robinsons marked, `-robinson` must ask rather than guess -- taking the wrong
    player back onto the board is the same class of error as marking him."""
    pool = _pool()
    state = MarkDrafted()
    _handle_command("bijan", pool, state, [])
    _handle_command("brian", pool, state, [])
    pending, action, status = _handle_command("-robinson", pool, state, [])
    assert {p.sleeper_id for p in pending} == {"bijan", "brian"}
    assert action == "unmark"
    assert state.drafted == {"bijan", "brian"}   # nothing taken back yet

    _, _, status2 = _handle_command("1", pool, state, pending, action)
    assert len(state.drafted) == 1


def test_handle_command_unmark_with_nothing_marked_says_so():
    pool = _pool()
    state = MarkDrafted()
    pending, _, status = _handle_command("-gibbs", pool, state, [])
    assert pending == []
    assert state.drafted == set()
    assert "no marked player" in status.lower()


def test_handle_command_unmark_cannot_reach_feed_reported_picks():
    """`-` only ever takes back a MANUAL mark. Feed picks are not in
    `mark_state`, and pretending to un-draft one would put a genuinely gone
    player back on the board."""
    pool = _pool()
    state = MarkDrafted()
    _, _, status = _handle_command("-gibbs", pool, state, [])   # gibbs is "feed-drafted"
    assert state.drafted == set()
    assert "no marked player" in status.lower()


def test_handle_command_me_prefix_single_match_marks_as_mine():
    pool = _pool()
    state = MarkDrafted()
    pending, pending_action, status = _handle_command("me gibbs", pool, state, [])
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
    pending, pending_action, status = _handle_command("me robinson", pool, state, [])
    assert state.drafted == set()          # nothing marked yet
    assert state.mine == set()
    assert pending_action == "mine"
    assert len(pending) == 2

    pending2, pending_action2, status2 = _handle_command("1", pool, state, pending, pending_action)
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
    picks = [Pick(pick_no=1, sleeper_id="1", draft_slot=5)]
    feed_roster = _my_roster_from_picks(picks, players, my_slot=5)

    combined = _combine_my_roster(feed_roster, mine_ids={"1"}, players=players)
    assert [p.sleeper_id for p in combined] == ["1"]


def test_combine_my_roster_adds_self_marked_players_the_feed_never_saw():
    """In feed-less mode `feed_roster` is always [] -- self-marked players
    must still surface in the combined roster."""
    players = _loop_players()
    combined = _combine_my_roster([], mine_ids={"1"}, players=players)
    assert [p.sleeper_id for p in combined] == ["1"]


def test_draft_log_path_is_dated_so_a_mock_never_replays_into_a_real_draft():
    """Same league, different day = different file. Replaying a mock's marks
    into the live draft would be far worse than having no log at all.

    (Calls the name imported at module load, which monkeypatch's module-attr
    patch in `_isolate_draft_log` does not rebind -- so this exercises the real
    implementation while `_run` still gets the pinned test path.)
    """
    from datetime import date
    path = _draft_log_path(_loop_league())
    assert path.name == f"loop-league-{date.today().isoformat()}.jsonl"
    assert path.parent.name == ".draft"


def test_mark_log_replay_restores_drafted_and_mine_exactly(tmp_path):
    """The Yahoo draft has no feed, so hand-typed marks are the ONLY record of
    it. A mis-hit ctrl-C at pick 90 must not cost ~100 re-typed names."""
    path = tmp_path / "draft.jsonl"
    state = MarkDrafted(log_path=path)
    state.mark("bijan")
    state.mark("gibbs", mine=True)
    state.unmark("bijan")

    restored, applied, skipped = _restore_marks(path)
    assert (applied, skipped) == (3, 0)
    assert restored.drafted == state.drafted == {"gibbs"}
    assert restored.mine == state.mine == {"gibbs"}


def test_marks_made_after_a_restore_are_journalled_too(tmp_path):
    """Surviving one crash must not cost the safety net for the next one.

    Caught by scripts/mutate.py: replacing `state.attach_log(path)` with `pass`
    left every earlier test green while silently disarming the log for the rest
    of the draft -- a second ctrl-C would then lose everything typed since the
    first restart, which is the exact scenario this feature exists for.
    """
    path = tmp_path / "draft.jsonl"
    first = MarkDrafted(log_path=path)
    first.mark("bijan")

    resumed, _, _ = _restore_marks(path)
    resumed.mark("gibbs", mine=True)             # typed after the "restart"

    again, applied, _ = _restore_marks(path)
    assert applied == 2
    assert again.drafted == {"bijan", "gibbs"}
    assert again.mine == {"gibbs"}


def test_mark_log_replay_restores_undo_history_too(tmp_path):
    """Replaying ops (not a state snapshot) rebuilds `_history`, so `u` still
    works after a restart. A snapshot would restore the sets but silently leave
    the user with no undo for everything typed before the crash."""
    path = tmp_path / "draft.jsonl"
    state = MarkDrafted(log_path=path)
    state.mark("bijan")
    state.mark("gibbs", mine=True)

    restored, _, _ = _restore_marks(path)
    restored.undo()
    assert restored.drafted == {"bijan"}
    assert restored.mine == set()


def test_mark_log_records_undo_so_it_is_not_replayed_away(tmp_path):
    """An undo is an op like any other. If it were not logged, replay would
    resurrect a mark the user had already taken back."""
    path = tmp_path / "draft.jsonl"
    state = MarkDrafted(log_path=path)
    state.mark("bijan")
    state.undo()

    restored, applied, _ = _restore_marks(path)
    assert applied == 2
    assert restored.drafted == set()


def test_mark_log_skips_corrupt_lines_without_dying(tmp_path):
    """Degrade, never fabricate: a truncated final line (the likely shape after
    a hard kill) must cost that one op, not the whole draft."""
    path = tmp_path / "draft.jsonl"
    state = MarkDrafted(log_path=path)
    state.mark("bijan")
    state.mark("gibbs")
    with path.open("a") as fh:
        fh.write('{"op": "mark", "id": "trunc')      # killed mid-write

    restored, applied, skipped = _restore_marks(path)
    assert (applied, skipped) == (2, 1)
    assert restored.drafted == {"bijan", "gibbs"}


def test_mark_log_replay_of_a_missing_file_is_empty_not_an_error(tmp_path):
    restored, applied, skipped = _restore_marks(tmp_path / "nope.jsonl")
    assert (applied, skipped) == (0, 0)
    assert restored.drafted == set()


def test_mark_still_works_when_the_log_cannot_be_written(tmp_path):
    """Persistence is insurance, never a dependency. If the disk is read-only
    the draft continues -- losing the safety net is survivable, losing the
    board mid-pick is not."""
    unwritable = tmp_path / "no-such-dir" / "draft.jsonl"
    state = MarkDrafted(log_path=unwritable)
    state.mark("bijan", mine=True)
    assert state.drafted == {"bijan"}
    assert state.mine == {"bijan"}


def test_mark_without_a_log_path_writes_nothing(tmp_path):
    state = MarkDrafted()
    state.mark("bijan")
    assert list(tmp_path.iterdir()) == []


def test_claims_overruled_by_feed_drops_a_claim_the_feed_gives_another_seat():
    """The feed is authoritative about WHO drafted whom. A `me <player>` on
    someone another seat actually took is provably wrong, and left standing it
    computes MARG against a roster the user does not have."""
    picks = [Pick(pick_no=1, sleeper_id="gibbs", draft_slot=9)]
    assert _claims_overruled_by_feed(picks, {"gibbs"}, my_slot=5) == {"gibbs"}


def test_claims_overruled_by_feed_keeps_a_claim_the_feed_confirms():
    """Same seat means the feed AGREES with the claim -- never drop it."""
    picks = [Pick(pick_no=1, sleeper_id="gibbs", draft_slot=5)]
    assert _claims_overruled_by_feed(picks, {"gibbs"}, my_slot=5) == set()


def test_claims_overruled_by_feed_ignores_picks_carrying_no_slot():
    """A pick with no `draft_slot` attributes to nobody. Overruling on it would
    guess, and this is exactly the Sleeper-mock shape that once emptied
    my_roster for a whole draft -- here it would silently DELETE the user's
    hand-built roster instead."""
    picks = [Pick(pick_no=1, sleeper_id="gibbs", draft_slot=None)]
    assert _claims_overruled_by_feed(picks, {"gibbs"}, my_slot=5) == set()


def test_claims_overruled_by_feed_is_inert_when_the_slot_is_unconfigured():
    """With no draft_slot configured, every pick's slot differs from `None`.
    A naive `!=` would overrule EVERY claim and wipe the roster -- the worst
    possible outcome from an unset config value."""
    picks = [Pick(pick_no=1, sleeper_id="gibbs", draft_slot=9),
             Pick(pick_no=2, sleeper_id="bijan", draft_slot=3)]
    assert _claims_overruled_by_feed(picks, {"gibbs", "bijan"}, my_slot=None) == set()


def test_claims_overruled_by_feed_leaves_unclaimed_picks_alone():
    picks = [Pick(pick_no=1, sleeper_id="bijan", draft_slot=9)]
    assert _claims_overruled_by_feed(picks, {"gibbs"}, my_slot=5) == set()


def test_render_tick_feed_overrules_a_bad_claim_and_says_so(monkeypatch, capsys):
    """End-to-end: a self-marked player the feed gives to another seat must
    leave my_roster, and the override must be VISIBLE -- silently editing the
    user's own roster is exactly the 'degrade, never fabricate' violation this
    project treats as the worst failure mode."""
    players = {
        "qb1": Player("qb1", "Roster QB", "QB", "SF", proj_pts=50.0, adp=50.0, adp_stdev=5.0),
        "qb2": Player("qb2", "Candidate QB", "QB", "KC", proj_pts=300.0, adp=1.0, adp_stdev=1.0),
    }
    settings = LeagueSettings(num_teams=10, scoring={}, roster_slots={"QB": 1}, rounds=1,
                              draft_id=None)
    league = _loop_league(draft_slot=5)
    captured = {}

    def spy_render(board, limit, stale, my_roster, *a, **kw):
        captured["my_roster"] = my_roster
        return "ok"

    monkeypatch.setattr("ffhelper.cli.render", spy_render)

    _render_tick(
        [Pick(pick_no=1, sleeper_id="qb1", draft_slot=9)], None, players, settings,
        league, Tunables(), 10, manual_gone={"qb1"}, manual_mine={"qb1"}, my_slot=5,
    )

    assert [p.sleeper_id for p in captured["my_roster"]] == []   # claim dropped
    out = capsys.readouterr().out
    assert "Roster QB" in out and "seat 9" in out


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
        manual_gone={"qb1"}, manual_mine={"qb1"}, my_slot=None,
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
    _instant_ticks(monkeypatch)
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
    pending_action = ""

    def tick() -> str:
        capsys.readouterr()
        _render_tick([], None, players, settings, league, Tunables(), 10,
                     state.drafted, state.mine, my_slot=None)
        return capsys.readouterr().out

    assert "pick 1   your next pick" in tick()

    for name in ["Aardvark", "Bobcat", "Cougar", "Dingo"]:
        pending, pending_action, _ = _handle_command(name, players, state, pending, pending_action)

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
                 state.drafted, state.mine, my_slot=None)
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
                 state.drafted, state.mine, my_slot=None)
    before = captured[0]["target"]

    for pid in ["1", "2", "3", "4"]:
        state.mark(pid)
    _render_tick([], None, players, settings, league, Tunables(), 10,
                 state.drafted, state.mine, my_slot=None)
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
                 manual_gone=set(), manual_mine=set(), my_slot=None)
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
    _instant_ticks(monkeypatch)

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
        manual_gone=set(), manual_mine=set(), my_slot=None,
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
    _instant_ticks(monkeypatch)

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
    _instant_ticks(monkeypatch)

    calls = {"n": 0}
    real = _handle_command

    def flaky(line, pool, mark_state, pending, pending_action=""):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("boom")
        return real(line, pool, mark_state, pending, pending_action)

    monkeypatch.setattr("ffhelper.cli._handle_command", flaky)

    q: queue.Queue = queue.Queue()
    q.put("bijan")
    q.put("brian")

    result = _run(_loop_league(), Tunables(), limit=10, max_iterations=1, input_queue=q)
    out = capsys.readouterr().out

    assert result == 0
    assert calls["n"] == 2
    assert "marked Brian Robinson" in out


def test_wait_for_input_returns_a_typed_line_at_once():
    q = queue.Queue()
    q.put("gibbs")
    assert _wait_for_input(q, 30.0) == "gibbs"          # no waiting on the clock


def test_wait_for_input_returns_none_when_nothing_is_typed():
    assert _wait_for_input(queue.Queue(), 0.01) is None


def test_the_loop_waits_on_the_queue_never_on_a_flat_sleep(monkeypatch):
    """A name typed just after a tick must be handled at once.

    The loop used to `time.sleep(interval)` and drain typed commands only at
    tick boundaries, so on Yahoo -- 12s poll, and NO feed to poll, so the board
    can only ever change because you typed something -- every name waited up to
    12 seconds. That is what fell five picks behind in the first live Yahoo
    mock, and it reads exactly like a slow terminal, which is why it needs a
    test rather than a memory.

    Pinned two ways: the wait must be on THE input queue (so a keystroke ends
    it), and `time.sleep` must never be reached at all.
    """
    monkeypatch.setattr("ffhelper.cli.load_board_inputs",
                        lambda league, tunables: (_loop_players(), _loop_settings()))
    monkeypatch.setattr("ffhelper.cli.SleeperFeed", lambda draft_id: _FakeFeed(picks=[]))

    def no_sleeping(_seconds):
        raise AssertionError("the loop slept instead of waiting on typed input")

    monkeypatch.setattr("ffhelper.cli.time.sleep", no_sleeping)

    waits = []

    def fake_wait(q, timeout):
        waits.append((q, timeout))
        return None

    monkeypatch.setattr("ffhelper.cli._wait_for_input", fake_wait)

    q = queue.Queue()
    tunables = Tunables(poll_seconds={"sleeper": 5})
    assert _run(_loop_league(), tunables, limit=10, max_iterations=3, input_queue=q) == 0

    assert [w[0] for w in waits] == [q, q, q]        # waited on the typed-input queue
    # The first tick polls straight away, so it waits for nothing. Every wait
    # after that must run out to the poll interval and no further: too long and
    # the feed falls behind, and a floor of 0.0 is not "instant" but a busy
    # spin at 100% CPU -- which is what a mutation of this line does, and what
    # an `all(t <= interval)` assertion happily allowed through.
    assert waits[0][1] == 0.0
    assert all(4.9 < t <= 5.0 for _, t in waits[1:])


def test_a_keystroke_does_not_become_a_network_request(monkeypatch):
    """Waking on input must not re-poll. Sleeper IP-blocks above ~1000 req/min,
    so a poll per typed character would be worse than the latency it fixes."""
    monkeypatch.setattr("ffhelper.cli.load_board_inputs",
                        lambda league, tunables: (_loop_players(), _loop_settings()))
    feed = _FakeFeed(picks=[])
    monkeypatch.setattr("ffhelper.cli.SleeperFeed", lambda draft_id: feed)
    # Clock stands still: no poll is ever due after the first.
    monkeypatch.setattr("ffhelper.cli.time.monotonic", lambda: 0.0)
    monkeypatch.setattr("ffhelper.cli._wait_for_input", lambda q, timeout: None)

    _run(_loop_league(), Tunables(), limit=10, max_iterations=5, input_queue=queue.Queue())

    assert feed.calls == 1


def test_split_commands_breaks_one_line_into_several():
    assert _split_commands("nacua, me chase, gibbs") == ["nacua", "me chase", "gibbs"]
    assert _split_commands("gibbs") == ["gibbs"]
    assert _split_commands("a,,b,") == ["a", "b"]          # stray commas drop out
    assert _split_commands("  ") == []


def test_a_comma_batch_marks_every_name_in_one_tick(monkeypatch):
    """Falling behind costs one line, not one line per pick.

    A 12-team Yahoo mock on a 30s clock hands over roughly one pick every eight
    seconds; catching up five picks one name at a time is what ended run 2.
    """
    pool = {
        "1": Player("1", "Aaron Alpha", "RB", "ATL", proj_pts=100.0, adp=1.0, adp_stdev=1.0),
        "2": Player("2", "Bobby Beta", "WR", "BUF", proj_pts=90.0, adp=2.0, adp_stdev=1.0),
    }
    monkeypatch.setattr("ffhelper.cli.load_board_inputs",
                        lambda league, tunables: (pool, _loop_settings()))
    monkeypatch.setattr("ffhelper.cli.SleeperFeed", lambda draft_id: _FakeFeed(picks=[]))
    _instant_ticks(monkeypatch)

    printed = []
    monkeypatch.setattr("builtins.print", lambda *a, **k: printed.append(" ".join(map(str, a))))

    q = queue.Queue()
    q.put("alpha, me beta")
    assert _run(_loop_league(draft_slot=1), Tunables(), limit=10,
                max_iterations=1, input_queue=q) == 0

    out = "\n".join(printed)
    assert "marked Aaron Alpha" in out
    assert "marked Bobby Beta" in out and "as yours" in out


def test_every_command_in_a_batch_reports_its_own_outcome(monkeypatch):
    """A miss inside a batch must not be swallowed by the command after it.

    The status line used to be overwritten per command, so `a, nobody` showed
    only the last outcome. Invariant #3 -- unmatched players are printed, never
    silently dropped -- and in a batch it is precisely the failures that are
    easy to miss, because the screen still looks like it worked.
    """
    pool = {
        "1": Player("1", "Aaron Alpha", "RB", "ATL", proj_pts=100.0, adp=1.0, adp_stdev=1.0),
        "2": Player("2", "Bobby Beta", "WR", "BUF", proj_pts=90.0, adp=2.0, adp_stdev=1.0),
    }
    monkeypatch.setattr("ffhelper.cli.load_board_inputs",
                        lambda league, tunables: (pool, _loop_settings()))
    monkeypatch.setattr("ffhelper.cli.SleeperFeed", lambda draft_id: _FakeFeed(picks=[]))
    _instant_ticks(monkeypatch)

    printed = []
    monkeypatch.setattr("builtins.print", lambda *a, **k: printed.append(" ".join(map(str, a))))

    q = queue.Queue()
    q.put("alpha, nobody at all")
    _run(_loop_league(), Tunables(), limit=10, max_iterations=1, input_queue=q)

    out = "\n".join(printed)
    assert "marked Aaron Alpha" in out              # the hit is still reported
    assert "no match for 'nobody at all'" in out    # and so is the miss


# --- the Dash -> CLI handover must carry your roster, not just your marks ---

def test_a_feedless_cli_derives_my_roster_from_the_seat(tmp_path):
    # Found 2026-08-27 testing the ctrl-C handover offline. The Dash board
    # derives my_roster from your SEAT; the feed-less CLI read only explicit
    # `me` marks, and clicking never writes those. The live mock's journal was
    # 108 marks, 0 mine -- so falling back to the terminal handed you an EMPTY
    # roster, which makes MARG meaningless and disables the sort's roster-need
    # gate. That is Task 13 defect #1 arriving at the worst possible moment.
    from ffhelper.cli import _manual_mine
    log = tmp_path / "log.jsonl"
    # 26 plain clicks, seat 2 of 12: the seat owns picks 2, 23, 26.
    log.write_text("".join(
        json.dumps({"op": "mark", "id": str(i), "mine": False}) + "\n"
        for i in range(1, 27)))
    got = _manual_mine(log, set(), draft_slot=2, num_teams=12, has_feed=False)
    assert got == {"2", "23", "26"}


def test_a_league_with_a_feed_is_left_alone(tmp_path):
    # Sleeper attributes picks by draft_slot from the FEED, which is
    # authoritative. Deriving from journal order there would double-count and
    # could contradict the feed. A league with a feed must not change at all.
    from ffhelper.cli import _manual_mine
    log = tmp_path / "log.jsonl"
    # Long enough that derivation WOULD add players (seat 2 owns 2, 23, 26), or
    # applying it here would be undetectable and this test would prove nothing.
    log.write_text("".join(
        json.dumps({"op": "mark", "id": str(i), "mine": False}) + "\n"
        for i in range(1, 27)))
    assert _manual_mine(log, {"7"}, draft_slot=2, num_teams=12, has_feed=True) == {"7"}


def test_an_unset_seat_derives_nothing(tmp_path):
    # Degrade, never fabricate: with no draft_slot the tool cannot know which
    # picks are yours, and guessing would silently build the wrong roster.
    from ffhelper.cli import _manual_mine
    log = tmp_path / "log.jsonl"
    log.write_text(json.dumps({"op": "mark", "id": "9", "mine": False}) + "\n")
    assert _manual_mine(log, set(), draft_slot=None, num_teams=12, has_feed=False) == set()


def test_a_typed_me_still_wins_and_a_not_mine_override_still_sticks(tmp_path):
    # Both explicit statements must beat the derived guess, in BOTH directions --
    # the same composition app.read_state uses, and the reason it is a shared
    # rule rather than two.
    from ffhelper.cli import _manual_mine
    log = tmp_path / "log.jsonl"
    ops = [{"op": "mark", "id": str(i), "mine": False} for i in range(1, 27)]
    ops += [{"op": "unmark", "id": "23"}, {"op": "mark", "id": "23", "mine": False}]
    log.write_text("".join(json.dumps(o) + "\n" for o in ops))
    got = _manual_mine(log, {"99"}, draft_slot=2, num_teams=12, has_feed=False)
    assert "23" not in got, "an explicit not-mine override was re-derived"
    assert "99" in got, "a typed `me` claim was dropped"


def test_the_restore_banner_counts_the_roster_you_will_actually_see(tmp_path, capsys, monkeypatch):
    # After the handover fix the banner said "0 yours" while the board below it
    # listed 9 players, because the banner counted TYPED `me` marks and the
    # board derives from the seat. Read during a real ctrl-C handover, "0 yours"
    # is exactly the wrong thing to tell someone -- it reports the failure the
    # fix removed.
    import ffhelper.cli as cli
    log = tmp_path / "log.jsonl"
    log.write_text("".join(
        json.dumps({"op": "mark", "id": str(i), "mine": False}) + "\n"
        for i in range(1, 27)))
    monkeypatch.setattr(cli, "_draft_log_path", lambda league: log)
    mark_state, applied, skipped = cli._restore_marks(log)
    cli._print_restore_banner(log, mark_state, applied, skipped,
                              draft_slot=2, num_teams=12, has_feed=False)
    out = capsys.readouterr().out
    assert "26 drafted, 3 yours" in out, out


def test_read_roster_file_resolves_names_and_reports_every_problem_line(tmp_path):
    """Yahoo has no API, so this file IS the roster. A silently dropped or
    wrongly-resolved line is a silently wrong lineup every week -- so ambiguous
    and unknown lines are REPORTED and excluded, never guessed at.

    Bijan and Brian Robinson are both ATL RBs. That is the real case."""
    import ffhelper.cli as cli
    from ffhelper.data import Player
    pool = {
        "1": Player("1", "Bijan Robinson", "RB", "ATL"),
        "2": Player("2", "Brian Robinson", "RB", "ATL"),
        "3": Player("3", "Josh Allen", "QB", "BUF"),
    }
    path = tmp_path / "yahoo-main.txt"
    path.write_text("Josh Allen\n\n# a comment\nrobinson\nNobody At All\n")

    players, problems = cli.read_roster_file(path, pool)

    assert [p.sleeper_id for p in players] == ["3"]
    assert len(problems) == 2
    assert any("robinson" in m and "Bijan Robinson" in m and "Brian Robinson" in m
               for m in problems), problems
    assert any("Nobody At All" in m for m in problems), problems


def test_read_roster_file_is_empty_and_quiet_when_there_is_no_file(tmp_path):
    import ffhelper.cli as cli
    players, problems = cli.read_roster_file(tmp_path / "missing.txt", {})
    assert players == [] and problems == []


def test_roster_file_age_is_reported_so_a_stale_roster_is_visible(tmp_path):
    """A hand-maintained roster drifts the moment you make a waiver claim, and a
    stale one silently produces a wrong lineup every week -- the same failure
    class as draft-mode attribution drift. The file's mtime is the roster's age
    and it must be on screen, not inferred."""
    import os, time
    import ffhelper.cli as cli
    path = tmp_path / "yahoo-main.txt"
    path.write_text("Josh Allen\n")
    old = time.time() - 9 * 86400
    os.utime(path, (old, old))

    assert cli.roster_file_age_days(path) == 9
    assert cli.roster_file_age_days(tmp_path / "missing.txt") is None


def test_cache_age_minutes_is_reported_so_a_stale_serve_is_visible(tmp_path, monkeypatch):
    """`fetch_json` silently serves a stale cache on a failed fetch (stale_ok=True
    by default) and says nothing. Same job as `roster_file_age_days` does for the
    hand-maintained roster file: an age on screen, so "healthy but wrong" is
    visible rather than inferred.

    Specified in the Task 6 brief but never landed in that task's diff --
    `_lineup` (this task) is its first real caller."""
    import os, time
    import ffhelper.cli as cli
    monkeypatch.setattr(cli, "CACHE_DIR", tmp_path)
    path = tmp_path / "rosters_123.json"
    path.write_text("{}")
    old = time.time() - 40 * 60
    os.utime(path, (old, old))

    assert cli.cache_age_minutes("rosters_123") == 40
    assert cli.cache_age_minutes("missing") is None


def test_render_lineup_shows_slots_bench_close_calls_and_every_degradation():
    """One frame of the lineup screen. Pure, so it tests without a network.

    Everything degraded must be VISIBLE: an unfilled slot, a player with no
    projection this week, an injury, and the notes the caller passes in."""
    import ffhelper.cli as cli
    from ffhelper import season
    starter = Player("1", "Jaxon Smith-Njigba", "WR", "SEA", proj_pts=16.2)
    hurt = Player("2", "Chris Olave", "WR", "NO", proj_pts=11.0,
                  injury_status="Questionable", practice_participation="Limited")
    bench = Player("3", "Jordan Addison", "WR", "MIN", proj_pts=9.5)
    state = season.StartSit(
        lineup=[("WR", starter), ("WR", hurt), ("RB", None)],
        bench=[bench],
        close_calls=[season.CloseCall("WR", hurt, bench, 1.5)],
        # The brief's fixture omitted `unprojected` -- StartSit has no default
        # for it (nor should it: a caller that forgets it should get a
        # TypeError, not a silently-empty list it never chose). Fixed here
        # rather than weakening StartSit with a default.
        unprojected=[],
    )
    out = cli.render_lineup(state, week=3, league_name="sleeper-main",
                            owner="jaydenpg", notes=["projections unavailable for 2 players"])

    assert "week 3" in out and "sleeper-main" in out and "jaydenpg" in out
    assert "Jaxon Smith-Njigba" in out and "16.2" in out
    assert "Questionable" in out and "Limited" in out
    assert "EMPTY" in out                      # the unfilled RB slot
    assert "Jordan Addison" in out             # the bench
    assert "CLOSE" in out and "1.5" in out     # the close call
    assert "projections unavailable for 2 players" in out


def test_render_lineup_prints_dashes_not_zero_for_a_starter_with_no_projection():
    """The 0.0 `with_weekly_points` invents for sorting must never reach the
    screen as if it were a real projection -- that is the exact fabrication
    this design exists to prevent, landing in the place the user trusts most."""
    import ffhelper.cli as cli
    from ffhelper import season
    starter = Player("1", "Bench Stash", "TE", "KC", proj_pts=0.0)
    state = season.StartSit(
        lineup=[("TE", starter)], bench=[], close_calls=[], unprojected=[starter],
    )
    out = cli.render_lineup(state, week=1, league_name="l", owner=None, notes=[])

    # The invented 0.0 legitimately appears once, in the "projected total" row
    # (documented as a FLOOR when any starter has no projection) -- what must
    # never happen is the PLAYER'S OWN row showing it as if it were his number.
    player_line = next(line for line in out.splitlines() if "Bench Stash" in line)
    assert "0.0" not in player_line
    assert "--" in player_line
    assert "NO PROJECTION" in out


def _lineup_settings(**overrides):
    from ffhelper.data import LeagueSettings
    base = dict(num_teams=12, scoring={"pass_td": 6.0}, roster_slots={"QB": 1},
                rounds=1, draft_id="D1")
    base.update(overrides)
    return LeagueSettings(**base)


def test_lineup_derives_roster_by_roster_id_not_draft_slot(monkeypatch, capsys):
    """THE MEASURED FACT this task must not lose: draft_slot is NOT roster_id.
    In the real league slot 5 maps to roster_id 3, and roster_id 5 is a
    DIFFERENT manager's team. If `_lineup` ever conflated the two -- by falling
    back to the slot number, say -- it would silently print someone else's
    roster as the user's own."""
    import ffhelper.cli as cli
    from ffhelper.config import League, Tunables
    from ffhelper.feeds import Pick

    league = League(name="sleeper-main", platform="sleeper", league_id="L1", draft_slot=5)
    settings = _lineup_settings()
    players = {
        "10": Player("10", "Correct Owners QB", "QB", "BUF"),
        "99": Player("99", "Wrong Roster QB", "QB", "KC"),
    }
    monkeypatch.setattr(cli, "resolve_settings", lambda lg: settings)
    monkeypatch.setattr(cli, "load_players", lambda: players)
    monkeypatch.setattr(cli, "load_nfl_state", lambda: {"week": 3, "season": "2026"})
    monkeypatch.setattr(cli, "load_weekly_projections",
                        lambda season, week: [{"player_id": "10", "stats": {"pass_td": 2}}])
    # roster_id 3 (mapped from draft_slot 5 via the pick below) is the correct
    # roster; roster_id 5 -- what a naive "slot == roster_id" bug would grab
    # instead -- belongs to a different manager entirely.
    monkeypatch.setattr(cli, "load_league_rosters", lambda league_id: [
        {"roster_id": 3, "owner_id": "u1", "players": ["10"]},
        {"roster_id": 5, "owner_id": "u2", "players": ["99"]},
    ])
    monkeypatch.setattr(cli, "load_league_users", lambda league_id: [
        {"user_id": "u1", "display_name": "jaydenpg"},
        {"user_id": "u2", "display_name": "someone-else"},
    ])
    monkeypatch.setattr(cli, "SleeperFeed", lambda draft_id: _FakeFeed(
        picks=[Pick(pick_no=5, sleeper_id="whatever", roster_id=3, draft_slot=5)]))
    monkeypatch.setattr(cli, "cache_age_minutes", lambda key: None)

    result = cli._lineup(league, Tunables(), week=3)
    out = capsys.readouterr().out

    assert result == 0
    assert "jaydenpg" in out
    assert "Correct Owners QB" in out
    assert "Wrong Roster QB" not in out


def test_lineup_reports_stale_roster_cache_visibly(monkeypatch, capsys):
    """A failed roster fetch silently serves a stale cached copy -- degrade,
    never fabricate means the age must show on screen."""
    import ffhelper.cli as cli
    from ffhelper.config import League, Tunables
    from ffhelper.feeds import Pick

    league = League(name="sleeper-main", platform="sleeper", league_id="L1", draft_slot=5)
    settings = _lineup_settings()
    players = {"10": Player("10", "A", "QB", "BUF")}
    monkeypatch.setattr(cli, "resolve_settings", lambda lg: settings)
    monkeypatch.setattr(cli, "load_players", lambda: players)
    monkeypatch.setattr(cli, "load_nfl_state", lambda: {"week": 3, "season": "2026"})
    monkeypatch.setattr(cli, "load_weekly_projections", lambda season, week: [])
    monkeypatch.setattr(cli, "load_league_rosters",
                        lambda league_id: [{"roster_id": 3, "owner_id": "u1", "players": ["10"]}])
    monkeypatch.setattr(cli, "load_league_users",
                        lambda league_id: [{"user_id": "u1", "display_name": "jaydenpg"}])
    monkeypatch.setattr(cli, "SleeperFeed", lambda draft_id: _FakeFeed(
        picks=[Pick(pick_no=5, sleeper_id="x", roster_id=3, draft_slot=5)]))
    monkeypatch.setattr(cli, "cache_age_minutes", lambda key: 45)

    cli._lineup(league, Tunables(), week=3)
    out = capsys.readouterr().out

    assert "45 minutes old" in out


def test_lineup_reads_hand_maintained_roster_for_a_platform_with_no_api(monkeypatch, tmp_path, capsys):
    """Yahoo has no feed, so the roster file IS the roster -- this is the path
    that must work for the Yahoo run in Step 5."""
    import ffhelper.cli as cli
    from ffhelper.config import League, Tunables

    league = League(name="yahoo-main", platform="yahoo", league_id="L2")
    settings = _lineup_settings(num_teams=10, roster_slots={"QB": 1}, draft_id=None)
    players = {"20": Player("20", "Justin Herbert", "QB", "LAC")}
    monkeypatch.setattr(cli, "resolve_settings", lambda lg: settings)
    monkeypatch.setattr(cli, "load_players", lambda: players)
    monkeypatch.setattr(cli, "load_nfl_state", lambda: {"week": 1, "season": "2026"})
    monkeypatch.setattr(cli, "load_weekly_projections",
                        lambda season, week: [{"player_id": "20", "stats": {"pass_td": 3}}])
    monkeypatch.setattr(cli, "ROSTER_DIR", tmp_path)
    (tmp_path / "yahoo-main.txt").write_text("Justin Herbert\n")

    result = cli._lineup(league, Tunables(), week=1)
    out = capsys.readouterr().out

    assert result == 0
    assert "Justin Herbert" in out
    assert "no roster:" not in out


def test_lineup_reports_missing_roster_file_visibly(monkeypatch, tmp_path, capsys):
    """No file at all must not render a quiet, empty-looking lineup -- it must
    say why."""
    import ffhelper.cli as cli
    from ffhelper.config import League, Tunables

    league = League(name="yahoo-main", platform="yahoo", league_id="L2")
    settings = _lineup_settings(num_teams=10, roster_slots={"QB": 1}, draft_id=None)
    monkeypatch.setattr(cli, "resolve_settings", lambda lg: settings)
    monkeypatch.setattr(cli, "load_players", lambda: {})
    monkeypatch.setattr(cli, "load_nfl_state", lambda: {"week": 1, "season": "2026"})
    monkeypatch.setattr(cli, "load_weekly_projections", lambda season, week: [])
    monkeypatch.setattr(cli, "ROSTER_DIR", tmp_path)

    result = cli._lineup(league, Tunables(), week=1)
    out = capsys.readouterr().out

    assert result == 0
    assert "no roster:" in out


def test_main_dispatches_lineup_and_returns_its_exit_code(monkeypatch):
    """Asserting only the exit code would pass unchanged if `--week` were wired
    to the wrong argparse attribute (`args.limit`, say) or hardcoded to None --
    so the arguments `_lineup` is actually called with are captured too."""
    league = _loop_league()
    monkeypatch.setattr("ffhelper.cli.load_config", lambda path: ([league], Tunables()))
    seen = {}

    def fake_lineup(lg, tun, week):
        seen["league"] = lg
        seen["week"] = week
        return 3

    monkeypatch.setattr("ffhelper.cli._lineup", fake_lineup)

    result = main(["lineup", "--league", "loop-league", "--week", "5"])

    assert result == 3
    assert seen["league"] is league
    assert seen["week"] == 5


def test_lineup_survives_a_dead_draft_feed_and_says_so(monkeypatch, capsys):
    """CRITICAL: `SleeperFeed.get_picks()` is built with stale_ok=False, so a
    failed poll RAISES by design -- every other call site (_preflight, _run)
    catches it. Bare in `_lineup`, a network blip, a Sleeper outage, or a
    rate-limit would produce an unhandled traceback and print NOTHING: no
    roster, no notes, no partial lineup. Degrade, never fabricate."""
    import ffhelper.cli as cli
    from ffhelper.config import League, Tunables

    league = League(name="sleeper-main", platform="sleeper", league_id="L1", draft_slot=5)
    settings = _lineup_settings()
    monkeypatch.setattr(cli, "resolve_settings", lambda lg: settings)
    monkeypatch.setattr(cli, "load_players", lambda: {})
    monkeypatch.setattr(cli, "load_nfl_state", lambda: {"week": 3, "season": "2026"})
    monkeypatch.setattr(cli, "load_weekly_projections", lambda season, week: [])
    monkeypatch.setattr(cli, "load_league_rosters", lambda league_id: [])
    monkeypatch.setattr(cli, "cache_age_minutes", lambda key: None)
    monkeypatch.setattr(cli, "SleeperFeed",
                        lambda draft_id: _FakeFeed(fail=True))

    result = cli._lineup(league, Tunables(), week=3)
    out = capsys.readouterr().out

    assert result == 0
    assert "feed unreachable" in out          # _FakeFeed's failure reason, named
    assert "roster_id" in out


def test_lineup_skips_the_feed_entirely_with_no_draft_slot_configured(monkeypatch, capsys):
    """No draft_slot means derivation cannot possibly succeed -- the network
    call must not even be attempted."""
    import ffhelper.cli as cli
    from ffhelper.config import League, Tunables

    league = League(name="sleeper-main", platform="sleeper", league_id="L1", draft_slot=None)
    settings = _lineup_settings()
    monkeypatch.setattr(cli, "resolve_settings", lambda lg: settings)
    monkeypatch.setattr(cli, "load_players", lambda: {})
    monkeypatch.setattr(cli, "load_nfl_state", lambda: {"week": 3, "season": "2026"})
    monkeypatch.setattr(cli, "load_weekly_projections", lambda season, week: [])
    monkeypatch.setattr(cli, "load_league_rosters", lambda league_id: [])
    monkeypatch.setattr(cli, "cache_age_minutes", lambda key: None)

    def boom(draft_id):
        raise AssertionError("SleeperFeed must not be constructed with no draft_slot")

    monkeypatch.setattr(cli, "SleeperFeed", boom)

    result = cli._lineup(league, Tunables(), week=3)
    out = capsys.readouterr().out

    assert result == 0
    assert "could not derive your roster_id" in out


def test_lineup_roster_id_override_wins_over_derivation(monkeypatch, capsys):
    """IMPORTANT 1: `league.roster_id` is a manual override -- when set, it is
    used outright (no feed call at all) and the override is announced, since a
    wrong hand-set id must not be silent either."""
    import ffhelper.cli as cli
    from ffhelper.config import League, Tunables

    league = League(name="sleeper-main", platform="sleeper", league_id="L1",
                    draft_slot=5, roster_id=7)
    settings = _lineup_settings()
    players = {"10": Player("10", "Overridden Roster QB", "QB", "BUF")}
    monkeypatch.setattr(cli, "resolve_settings", lambda lg: settings)
    monkeypatch.setattr(cli, "load_players", lambda: players)
    monkeypatch.setattr(cli, "load_nfl_state", lambda: {"week": 3, "season": "2026"})
    monkeypatch.setattr(cli, "load_weekly_projections",
                        lambda season, week: [{"player_id": "10", "stats": {"pass_td": 2}}])
    monkeypatch.setattr(cli, "load_league_rosters",
                        lambda league_id: [{"roster_id": 7, "owner_id": "u1", "players": ["10"]}])
    monkeypatch.setattr(cli, "load_league_users",
                        lambda league_id: [{"user_id": "u1", "display_name": "jaydenpg"}])
    monkeypatch.setattr(cli, "cache_age_minutes", lambda key: None)

    def boom(draft_id):
        raise AssertionError("the override must skip the draft feed entirely")

    monkeypatch.setattr(cli, "SleeperFeed", boom)

    result = cli._lineup(league, Tunables(), week=3)
    out = capsys.readouterr().out

    assert result == 0
    assert "Overridden Roster QB" in out
    assert "using roster_id 7 from config.toml (override)" in out


def test_lineup_reports_rostered_players_missing_from_the_player_pool(monkeypatch, capsys):
    """IMPORTANT 2: `missing = [i for i in ids if i not in players]` was
    reachable but undriven -- deleting the note would pass the suite and the
    mutation gate unnoticed."""
    import ffhelper.cli as cli
    from ffhelper.config import League, Tunables
    from ffhelper.feeds import Pick

    league = League(name="sleeper-main", platform="sleeper", league_id="L1", draft_slot=5)
    settings = _lineup_settings()
    players = {"10": Player("10", "A", "QB", "BUF")}
    monkeypatch.setattr(cli, "resolve_settings", lambda lg: settings)
    monkeypatch.setattr(cli, "load_players", lambda: players)
    monkeypatch.setattr(cli, "load_nfl_state", lambda: {"week": 3, "season": "2026"})
    monkeypatch.setattr(cli, "load_weekly_projections", lambda season, week: [])
    # roster carries "10" (known) and "999" (retired/unknown -- not in the pool)
    monkeypatch.setattr(cli, "load_league_rosters", lambda league_id: [
        {"roster_id": 3, "owner_id": "u1", "players": ["10", "999"]},
    ])
    monkeypatch.setattr(cli, "load_league_users",
                        lambda league_id: [{"user_id": "u1", "display_name": "jaydenpg"}])
    monkeypatch.setattr(cli, "SleeperFeed", lambda draft_id: _FakeFeed(
        picks=[Pick(pick_no=5, sleeper_id="x", roster_id=3, draft_slot=5)]))
    monkeypatch.setattr(cli, "cache_age_minutes", lambda key: None)

    cli._lineup(league, Tunables(), week=3)
    out = capsys.readouterr().out

    assert "1 rostered players are not in the player pool" in out
    assert "999" in out


def test_lineup_notes_an_orphaned_roster_id(monkeypatch, capsys):
    """MINOR (promoted): a `roster_id` the live picks feed reports that the
    rosters payload (cached up to 300s) does not contain must not render as a
    silent, unexplained EMPTY lineup -- `rid` is not None here, only absent
    from the rosters list, so the generic derivation-failed note never fires
    without an explicit check for this case."""
    import ffhelper.cli as cli
    from ffhelper.config import League, Tunables
    from ffhelper.feeds import Pick

    league = League(name="sleeper-main", platform="sleeper", league_id="L1", draft_slot=5)
    settings = _lineup_settings()
    monkeypatch.setattr(cli, "resolve_settings", lambda lg: settings)
    monkeypatch.setattr(cli, "load_players", lambda: {})
    monkeypatch.setattr(cli, "load_nfl_state", lambda: {"week": 3, "season": "2026"})
    monkeypatch.setattr(cli, "load_weekly_projections", lambda season, week: [])
    # The rosters payload knows nothing about roster_id 3 -- stale cache, most
    # plausibly, since a real league always has every roster_id.
    monkeypatch.setattr(cli, "load_league_rosters", lambda league_id: [
        {"roster_id": 99, "owner_id": "u2", "players": []},
    ])
    monkeypatch.setattr(cli, "load_league_users", lambda league_id: [])
    monkeypatch.setattr(cli, "SleeperFeed", lambda draft_id: _FakeFeed(
        picks=[Pick(pick_no=5, sleeper_id="x", roster_id=3, draft_slot=5)]))
    monkeypatch.setattr(cli, "cache_age_minutes", lambda key: None)

    result = cli._lineup(league, Tunables(), week=3)
    out = capsys.readouterr().out

    assert result == 0
    assert "roster_id 3 is not in this league's rosters" in out


# --- Final review, item 1: load_nfl_state is the only unguarded network call
# standing between `lineup --week N` and a lineup. ---


def test_lineup_falls_back_to_week_argument_when_nfl_state_is_unreachable(monkeypatch, capsys):
    """`lineup --week 4` is the obvious thing to try when the week on screen
    looks wrong -- it must work even when /state/nfl (a new, undocumented-by-us
    endpoint) is down. Against the old unguarded `load_nfl_state()` call this
    raises before a single line is printed."""
    import ffhelper.cli as cli
    from ffhelper.config import League, Tunables
    from ffhelper.feeds import Pick

    league = League(name="sleeper-main", platform="sleeper", league_id="L1", draft_slot=5)
    settings = _lineup_settings()
    players = {"10": Player("10", "A Real Starter", "QB", "BUF")}
    monkeypatch.setattr(cli, "resolve_settings", lambda lg: settings)
    monkeypatch.setattr(cli, "load_players", lambda: players)

    def boom():
        raise RuntimeError("state endpoint renamed or removed")
    monkeypatch.setattr(cli, "load_nfl_state", boom)
    monkeypatch.setattr(cli, "load_weekly_projections",
                        lambda season, week: [{"player_id": "10", "stats": {"pass_td": 2}}])
    monkeypatch.setattr(cli, "load_league_rosters", lambda league_id: [
        {"roster_id": 3, "owner_id": "u1", "players": ["10"]}])
    monkeypatch.setattr(cli, "load_league_users",
                        lambda league_id: [{"user_id": "u1", "display_name": "jaydenpg"}])
    monkeypatch.setattr(cli, "SleeperFeed", lambda draft_id: _FakeFeed(
        picks=[Pick(pick_no=5, sleeper_id="x", roster_id=3, draft_slot=5)]))
    monkeypatch.setattr(cli, "cache_age_minutes", lambda key: None)

    result = cli._lineup(league, Tunables(), week=4)
    out = capsys.readouterr().out

    assert result == 0
    assert "week 4" in out
    assert "A Real Starter" in out


def test_lineup_stops_with_a_visible_note_when_no_week_can_be_resolved(monkeypatch, capsys):
    """Neither the endpoint nor --week can supply a week -- the old `or 1`
    fallback GUESSED one instead. Guessing a week number is exactly the
    fabrication this design forbids, so the command must say so and stop."""
    import ffhelper.cli as cli
    from ffhelper.config import League, Tunables

    league = League(name="sleeper-main", platform="sleeper", league_id="L1", draft_slot=5)
    monkeypatch.setattr(cli, "resolve_settings", lambda lg: _lineup_settings())

    def boom():
        raise RuntimeError("state endpoint renamed or removed")
    monkeypatch.setattr(cli, "load_nfl_state", boom)

    def must_not_be_called(*a, **kw):
        raise AssertionError("must stop before fetching players/projections with no week")
    monkeypatch.setattr(cli, "load_players", must_not_be_called)
    monkeypatch.setattr(cli, "load_weekly_projections", must_not_be_called)

    result = cli._lineup(league, Tunables(), week=None)
    out = capsys.readouterr().out

    assert result == 1
    assert "--week" in out
    assert "no NFL week available" in out


# --- Final review, item 3: the roster_id override note names WHOSE roster. ---


def test_lineup_roster_id_override_note_names_the_owner(monkeypatch, capsys):
    """A wrong-but-valid override renders a completely coherent lineup for a
    teammate's team -- the owner name in the header is the only tell today,
    and the user has to notice it unaided. It must also be IN the note."""
    import ffhelper.cli as cli
    from ffhelper.config import League, Tunables

    league = League(name="sleeper-main", platform="sleeper", league_id="L1",
                    draft_slot=5, roster_id=7)
    settings = _lineup_settings()
    players = {"10": Player("10", "Overridden Roster QB", "QB", "BUF")}
    monkeypatch.setattr(cli, "resolve_settings", lambda lg: settings)
    monkeypatch.setattr(cli, "load_players", lambda: players)
    monkeypatch.setattr(cli, "load_nfl_state", lambda: {"week": 3, "season": "2026"})
    monkeypatch.setattr(cli, "load_weekly_projections",
                        lambda season, week: [{"player_id": "10", "stats": {"pass_td": 2}}])
    monkeypatch.setattr(cli, "load_league_rosters",
                        lambda league_id: [{"roster_id": 7, "owner_id": "u1", "players": ["10"]}])
    monkeypatch.setattr(cli, "load_league_users",
                        lambda league_id: [{"user_id": "u1", "display_name": "someone-else"}])
    monkeypatch.setattr(cli, "cache_age_minutes", lambda key: None)

    def boom(draft_id):
        raise AssertionError("the override must skip the draft feed entirely")
    monkeypatch.setattr(cli, "SleeperFeed", boom)

    result = cli._lineup(league, Tunables(), week=3)
    out = capsys.readouterr().out

    assert result == 0
    override_line = next(line for line in out.splitlines() if "override" in line)
    assert "someone-else" in override_line


# --- Final review, item 2: the projected total is a floor when a starter has
# no projection, and must say so rather than reading as an exact number. ---


def test_render_lineup_total_carries_a_floor_caveat_when_a_starter_is_unprojected():
    import ffhelper.cli as cli
    from ffhelper import season
    starter = Player("1", "Projected Guy", "WR", "SEA", proj_pts=16.2)
    stash = Player("2", "Bench Stash", "TE", "KC", proj_pts=0.0)
    state = season.StartSit(
        lineup=[("WR", starter), ("TE", stash)], bench=[], close_calls=[],
        unprojected=[stash],
    )
    out = cli.render_lineup(state, week=1, league_name="l", owner=None, notes=[])
    total_line = next(line for line in out.splitlines() if "projected total" in line)
    assert "floor" in total_line
    assert "1 starter" in total_line


def test_render_lineup_total_carries_no_caveat_when_every_starter_is_projected():
    """Discriminates against a caveat that fires unconditionally."""
    import ffhelper.cli as cli
    from ffhelper import season
    starter = Player("1", "Projected Guy", "WR", "SEA", proj_pts=16.2)
    state = season.StartSit(lineup=[("WR", starter)], bench=[], close_calls=[], unprojected=[])
    out = cli.render_lineup(state, week=1, league_name="l", owner=None, notes=[])
    total_line = next(line for line in out.splitlines() if "projected total" in line)
    assert "floor" not in total_line


# --- Final review, item 6: injury codes that are actively misleading if left
# raw ("NA" reads as "not applicable", it means "not active"). ---


def test_status_note_maps_injury_codes_to_plain_language():
    import ffhelper.cli as cli
    mapped = Player("1", "A", "RB", "GB", injury_status="NA")
    assert cli._status_note(mapped) == "  [not active]"


def test_status_note_leaves_self_explanatory_codes_alone():
    """Discriminates against a map that rewrites every code, including the
    ones (Out, Questionable, Doubtful) that were already readable."""
    import ffhelper.cli as cli
    unmapped = Player("1", "A", "RB", "GB", injury_status="Questionable")
    assert cli._status_note(unmapped) == "  [Questionable]"


# --- Final review, item 4: preflight must report projection-to-roster join
# coverage -- the spec's own Testing section names this and no task built it. ---


def test_preflight_reports_projection_coverage_for_rostered_players(monkeypatch, capsys):
    """The join is exactly what broke mid-build: most weekly-projection rows
    carry only descriptive fields for players who are not projected, and a bad
    guard once reported zero unprojected players when one was correct."""
    monkeypatch.setattr("ffhelper.cli.load_board_inputs",
                        lambda league, tunables: (_loop_players(), _loop_settings()))
    monkeypatch.setattr("ffhelper.cli.SleeperFeed", lambda draft_id: _FakeFeed(picks=[]))
    monkeypatch.setattr("ffhelper.cli.load_nfl_state",
                        lambda: {"week": 1, "season": "2026", "season_type": "regular"})
    monkeypatch.setattr("ffhelper.cli.load_league_rosters", lambda league_id: [
        {"roster_id": 1, "players": ["10", "11"]},
        {"roster_id": 2, "players": ["12"]},
    ])
    monkeypatch.setattr("ffhelper.cli.load_weekly_projections",
                        lambda season, week: [
                            {"player_id": "10", "stats": {"pass_td": 2}},
                            {"player_id": "99", "stats": {"pass_td": 1}},  # not rostered
                        ])

    result = _preflight(_loop_league(draft_slot=3), Tunables())
    out = capsys.readouterr().out

    assert result == 0
    # "league-wide" is load-bearing: this counts every team's players (both
    # rosters above), not yours. The hand-entered branch counts your roster
    # alone and says so differently.
    assert "projections     : 1 of 3 players rostered league-wide projected for week 1" in out


# --- Final review, item 1: /state/nfl and rosters must degrade to a visible
# line in preflight rather than aborting before the feed-reachability check. ---


def test_preflight_survives_a_dead_nfl_state_endpoint_and_reaches_the_feed_check(monkeypatch, capsys):
    monkeypatch.setattr("ffhelper.cli.load_board_inputs",
                        lambda league, tunables: (_loop_players(), _loop_settings()))
    monkeypatch.setattr("ffhelper.cli.SleeperFeed", lambda draft_id: _FakeFeed(picks=[]))

    def boom():
        raise RuntimeError("state endpoint renamed or removed")
    monkeypatch.setattr("ffhelper.cli.load_nfl_state", boom)
    monkeypatch.setattr("ffhelper.cli.load_league_rosters", lambda league_id: [])

    result = _preflight(_loop_league(draft_slot=3), Tunables())
    out = capsys.readouterr().out

    assert "nfl week        : NO" in out
    assert "feed reachable" in out          # reached the check below, not aborted


def test_preflight_survives_a_dead_rosters_endpoint_and_reaches_the_feed_check(monkeypatch, capsys):
    monkeypatch.setattr("ffhelper.cli.load_board_inputs",
                        lambda league, tunables: (_loop_players(), _loop_settings()))
    monkeypatch.setattr("ffhelper.cli.SleeperFeed", lambda draft_id: _FakeFeed(picks=[]))
    monkeypatch.setattr("ffhelper.cli.load_nfl_state",
                        lambda: {"week": 1, "season": "2026", "season_type": "regular"})

    def boom(league_id):
        raise RuntimeError("rosters endpoint renamed or removed")
    monkeypatch.setattr("ffhelper.cli.load_league_rosters", boom)

    result = _preflight(_loop_league(draft_slot=3), Tunables())
    out = capsys.readouterr().out

    assert "rosters         : NO" in out
    assert "feed reachable" in out          # reached the check below, not aborted


# --- Final review round 2: load_league_rosters inside _lineup was still
# unguarded -- its stale-cache fallback only saves you if a cache file
# already exists, and a first run on a new machine (or a cleared .cache/, or
# a brand-new league) raises instead. ---


def test_lineup_survives_a_dead_rosters_endpoint_and_says_so(monkeypatch, capsys):
    """Bare, `load_league_rosters` raising crashes _lineup with an unhandled
    traceback: no roster, no notes, no partial lineup -- the same defect
    class as the bare get_picks() a few lines below it in the same function.
    The roster_id override is used here to isolate this test from the draft
    feed, which already has its own guard and its own test."""
    import ffhelper.cli as cli
    from ffhelper.config import League, Tunables

    league = League(name="sleeper-main", platform="sleeper", league_id="L1",
                    draft_slot=5, roster_id=7)
    settings = _lineup_settings()
    monkeypatch.setattr(cli, "resolve_settings", lambda lg: settings)
    monkeypatch.setattr(cli, "load_players", lambda: {})
    monkeypatch.setattr(cli, "load_nfl_state", lambda: {"week": 3, "season": "2026"})
    monkeypatch.setattr(cli, "load_weekly_projections", lambda season, week: [])
    monkeypatch.setattr(cli, "cache_age_minutes", lambda key: None)

    def boom(league_id):
        raise ConnectionError("simulated: rosters endpoint down, no cache")
    monkeypatch.setattr(cli, "load_league_rosters", boom)

    def must_not_be_called(draft_id):
        raise AssertionError("the override must skip the draft feed entirely")
    monkeypatch.setattr(cli, "SleeperFeed", must_not_be_called)

    result = cli._lineup(league, Tunables(), week=3)
    out = capsys.readouterr().out

    assert result == 0
    assert "could not reach Sleeper's league rosters endpoint" in out
    assert "simulated: rosters endpoint down, no cache" in out


# --- Final review round 3: `load_league_users` was the LAST unguarded network
# call in _lineup. Rounds 1 and 2 guarded /state/nfl, the draft feed and
# /league/{id}/rosters; the users fetch sits on the same happy path, behind
# the same `fetch_json` whose stale_ok=True only helps when a cache file
# already exists. It supplies `owner`, which is a DISPLAY field -- crashing a
# whole lineup for a cosmetic name is the worst trade in the function. ---


def test_lineup_survives_a_dead_users_endpoint_and_still_prints_the_lineup(monkeypatch, capsys):
    """Bare, `load_league_users` raising crashes _lineup after the roster and
    the projections have both been fetched successfully -- the lineup is fully
    computed and then thrown away over a display name. It must degrade to an
    unnamed owner, exactly as the rosters and nfl-state guards degrade."""
    import ffhelper.cli as cli
    from ffhelper.config import League, Tunables

    league = League(name="sleeper-main", platform="sleeper", league_id="L1",
                    draft_slot=5, roster_id=3)
    settings = _lineup_settings()
    players = {"10": Player("10", "A Real Starter", "QB", "BUF")}
    monkeypatch.setattr(cli, "resolve_settings", lambda lg: settings)
    monkeypatch.setattr(cli, "load_players", lambda: players)
    monkeypatch.setattr(cli, "load_nfl_state", lambda: {"week": 3, "season": "2026"})
    monkeypatch.setattr(cli, "load_weekly_projections",
                        lambda season, week: [{"player_id": "10", "stats": {"pass_td": 2}}])
    monkeypatch.setattr(cli, "load_league_rosters", lambda league_id: [
        {"roster_id": 3, "owner_id": "u1", "players": ["10"]}])
    monkeypatch.setattr(cli, "cache_age_minutes", lambda key: None)

    def boom(league_id):
        raise ConnectionError("simulated: users endpoint down, no cache")
    monkeypatch.setattr(cli, "load_league_users", boom)

    result = cli._lineup(league, Tunables(), week=3)
    out = capsys.readouterr().out

    assert result == 0
    assert "A Real Starter" in out          # the lineup survived the failure
    assert "could not reach Sleeper's league users endpoint" in out
    # The override note still fires, and still refuses to claim an owner it
    # could not look up -- a wrong-but-valid override must stay visible.
    assert "an unrecognised owner" in out


# --- Final review round 3: three more from the scoped re-review of the fix
# wave itself. ---


def test_preflight_is_incomplete_when_the_projections_join_cannot_run(monkeypatch, capsys):
    """`projections` was the only failure branch that did not set ok=False --
    every sibling (nfl week, rosters, feed reachable) does. So a dead
    projections endpoint on the morning of week 1 printed PREFLIGHT OK and
    exited 0, from the one check that exists to prove season mode can run."""
    monkeypatch.setattr("ffhelper.cli.load_board_inputs",
                        lambda league, tunables: (_loop_players(), _loop_settings()))
    monkeypatch.setattr("ffhelper.cli.SleeperFeed", lambda draft_id: _FakeFeed(picks=[]))
    monkeypatch.setattr("ffhelper.cli.load_nfl_state",
                        lambda: {"week": 1, "season": "2026", "season_type": "regular"})
    monkeypatch.setattr("ffhelper.cli.load_league_rosters", lambda league_id: [
        {"roster_id": 1, "players": ["10"]}])

    def boom(season, week):
        raise ConnectionError("simulated: projections endpoint down")
    monkeypatch.setattr("ffhelper.cli.load_weekly_projections", boom)

    result = _preflight(_loop_league(draft_slot=3), Tunables())
    out = capsys.readouterr().out

    assert "projections     : NO -- simulated: projections endpoint down" in out
    assert "PREFLIGHT INCOMPLETE" in out
    assert result == 1


def test_preflight_treats_week_zero_as_no_week_just_as_lineup_does(monkeypatch, capsys):
    """Sleeper's /state/nfl serves `"week": 0` in the offseason. `_lineup`
    guards with `if not week` and refuses to guess; `_preflight` guarded with
    `if week is None`, so it fell through and made a real week-0 projections
    call, printing an alarming '0 of N ... for week 0' from a state its own
    sibling deliberately treats as 'no week'."""
    monkeypatch.setattr("ffhelper.cli.load_board_inputs",
                        lambda league, tunables: (_loop_players(), _loop_settings()))
    monkeypatch.setattr("ffhelper.cli.SleeperFeed", lambda draft_id: _FakeFeed(picks=[]))
    monkeypatch.setattr("ffhelper.cli.load_nfl_state",
                        lambda: {"week": 0, "season": "2026", "season_type": "pre"})
    monkeypatch.setattr("ffhelper.cli.load_league_rosters", lambda league_id: [
        {"roster_id": 1, "players": ["10"]}])

    def must_not_be_called(season, week):
        raise AssertionError("week 0 is not a week -- do not fetch projections for it")
    monkeypatch.setattr("ffhelper.cli.load_weekly_projections", must_not_be_called)

    _preflight(_loop_league(draft_slot=3), Tunables())
    out = capsys.readouterr().out

    assert "projections     : not checked -- no NFL week resolved" in out
    assert "week 0" not in out


def test_lineup_still_names_the_roster_id_override_when_rosters_are_unreachable(
        monkeypatch, capsys):
    """The override note moved inside the branch that needs a successful
    rosters fetch, so a dead endpoint left a user running a hand-set
    roster_id with no indication an override was in play at all. Both facts
    have to be on screen: an override is active, AND nothing was read."""
    import ffhelper.cli as cli
    from ffhelper.config import League, Tunables

    league = League(name="sleeper-main", platform="sleeper", league_id="L1",
                    draft_slot=5, roster_id=7)
    monkeypatch.setattr(cli, "resolve_settings", lambda lg: _lineup_settings())
    monkeypatch.setattr(cli, "load_players", lambda: {})
    monkeypatch.setattr(cli, "load_nfl_state", lambda: {"week": 3, "season": "2026"})
    monkeypatch.setattr(cli, "load_weekly_projections", lambda season, week: [])
    monkeypatch.setattr(cli, "cache_age_minutes", lambda key: None)

    def boom(league_id):
        raise ConnectionError("simulated: rosters endpoint down, no cache")
    monkeypatch.setattr(cli, "load_league_rosters", boom)

    result = cli._lineup(league, Tunables(), week=3)
    out = capsys.readouterr().out

    assert result == 0
    assert "could not reach Sleeper's league rosters endpoint" in out
    assert "roster_id 7" in out and "override" in out


# --- Phase 4b: the snapshot. `lineup` records what each source claimed at the
# moment the decision was taken, because none of it is re-served later. ---


def _snapshot_league(**kw):
    from ffhelper.config import League
    base = dict(name="sleeper-main", platform="sleeper", league_id="L1",
                draft_slot=5, roster_id=3)
    base.update(kw)
    return League(**base)


def _stub_lineup_world(monkeypatch, cli, week_from_state=1):
    """A working `lineup` run: one projected starter, one unprojected stash."""
    players = {"10": Player("10", "A Starter", "QB", "BUF"),
               "99": Player("99", "A Stash", "RB", "GB", injury_status="NA")}
    monkeypatch.setattr(cli, "resolve_settings", lambda lg: _lineup_settings())
    monkeypatch.setattr(cli, "load_players", lambda: players)
    monkeypatch.setattr(cli, "load_nfl_state",
                        lambda: {"week": week_from_state, "season": "2026"})
    monkeypatch.setattr(cli, "load_weekly_projections",
                        lambda season, week: [{"player_id": "10", "stats": {"pass_td": 2}}])
    monkeypatch.setattr(cli, "load_league_rosters", lambda league_id: [
        {"roster_id": 3, "owner_id": "u1", "players": ["10", "99"]}])
    monkeypatch.setattr(cli, "load_league_users",
                        lambda league_id: [{"user_id": "u1", "display_name": "jaydenpg"}])
    monkeypatch.setattr(cli, "cache_age_minutes", lambda key: None)


def test_lineup_records_a_snapshot_for_the_current_week(monkeypatch, capsys, tmp_path):
    """The inputs to a decision are not re-served, so a week not recorded
    before it is played can never be scored. This is the write that makes the
    advice measurable at all."""
    import sqlite3
    import ffhelper.cli as cli
    from ffhelper import store
    from ffhelper.config import Tunables

    monkeypatch.setattr(store, "DB_PATH", tmp_path / "season.db")
    _stub_lineup_world(monkeypatch, cli, week_from_state=1)

    result = cli._lineup(_snapshot_league(), Tunables(), week=1)
    out = capsys.readouterr().out

    assert result == 0
    assert "snapshot" in out and "2 players recorded for week 1" in out

    rows = sqlite3.connect(tmp_path / "season.db").execute(
        "SELECT player_id, proj_pts, started, matchup FROM snapshot ORDER BY player_id"
    ).fetchall()
    # The stash has NO projection: NULL, never the 0.0 sort value.
    assert rows == [("10", 12.0, 1, None), ("99", None, 0, None)]


def test_lineup_does_not_record_a_snapshot_for_a_past_week(monkeypatch, capsys, tmp_path):
    """`--week 1` run in December must print normally and write NOTHING.
    Re-running it would overwrite week 1's real inputs with December's
    projections -- silently destroying the exact record the table exists to
    protect, in the one command that touches it."""
    import ffhelper.cli as cli
    from ffhelper import store
    from ffhelper.config import Tunables

    db = tmp_path / "season.db"
    monkeypatch.setattr(store, "DB_PATH", db)
    # The season has moved on to week 14; we are asking about week 1.
    _stub_lineup_world(monkeypatch, cli, week_from_state=14)

    result = cli._lineup(_snapshot_league(), Tunables(), week=1)
    out = capsys.readouterr().out

    assert result == 0
    assert "A Starter" in out                 # the lineup still printed
    assert "not recorded" in out and "week 1" in out
    assert not db.exists()                    # nothing was written at all


def test_lineup_does_not_record_a_snapshot_with_no_current_week_to_check(
        monkeypatch, capsys, tmp_path):
    """With /state/nfl down there is no current week, so `--week N` cannot be
    confirmed as the live one. Assuming it is would let a past-week run
    overwrite a real record -- degrade, never guess."""
    import ffhelper.cli as cli
    from ffhelper import store
    from ffhelper.config import Tunables

    db = tmp_path / "season.db"
    monkeypatch.setattr(store, "DB_PATH", db)
    _stub_lineup_world(monkeypatch, cli)

    def boom():
        raise RuntimeError("state endpoint down")
    monkeypatch.setattr(cli, "load_nfl_state", boom)

    result = cli._lineup(_snapshot_league(), Tunables(), week=1)
    out = capsys.readouterr().out

    assert result == 0
    assert "A Starter" in out
    # The SPECIFIC refusal, not merely that something refused. Dropping this
    # guard lets the past-week check catch None by accident (1 != None) and
    # report "week 1 is not the current week (None)" -- which refuses for a
    # reason that is not true and names a week the user never mentioned.
    assert "no current week from /state/nfl" in out
    assert "is not the current week" not in out
    assert not db.exists()


def test_a_failing_snapshot_costs_a_line_and_never_the_lineup(monkeypatch, capsys, tmp_path):
    """The lineup is the product; the snapshot is a side effect. A database
    error must not throw away the thing you actually ran the command for --
    the same trade `load_league_users` was getting wrong one module over."""
    import ffhelper.cli as cli
    from ffhelper import store
    from ffhelper.config import Tunables

    monkeypatch.setattr(store, "DB_PATH", tmp_path / "season.db")
    _stub_lineup_world(monkeypatch, cli, week_from_state=1)

    def boom(*a, **kw):
        raise OSError("disk full")
    monkeypatch.setattr(store, "connect", boom)

    result = cli._lineup(_snapshot_league(), Tunables(), week=1)
    out = capsys.readouterr().out

    assert result == 0
    assert "A Starter" in out                 # the lineup survived
    assert "NOT RECORDED" in out and "disk full" in out


def test_lineup_shows_practice_status_from_nflverse(monkeypatch, tmp_path, capsys):
    """The join Sleeper cannot do: gsis_id, through the crosswalk already
    fetched. It lands in the existing status note rather than a new column."""
    import ffhelper.cli as cli
    from ffhelper.config import League, Tunables

    league = League(name="yahoo-main", platform="yahoo", league_id="L2")
    settings = _lineup_settings(num_teams=10, roster_slots={"QB": 1}, draft_id=None)
    players = {"20": Player("20", "Justin Herbert", "QB", "LAC", gsis_id="00-0036355")}
    monkeypatch.setattr(cli, "resolve_settings", lambda lg: settings)
    monkeypatch.setattr(cli, "load_players", lambda: players)
    monkeypatch.setattr(cli, "load_nfl_state", lambda: {"week": 4, "season": "2026"})
    monkeypatch.setattr(cli, "load_weekly_projections",
                        lambda season, week: [{"player_id": "20", "stats": {"pass_td": 2}}])
    monkeypatch.setattr(cli, "load_nfl_injuries",
                        lambda season, week: {"00-0036355": "Limited"})
    monkeypatch.setattr(cli, "ROSTER_DIR", tmp_path)
    (tmp_path / "yahoo-main.txt").write_text("Justin Herbert\n")

    cli._lineup(league, Tunables(), week=4)
    out = capsys.readouterr().out

    assert "[Limited]" in out
    assert "practice report : 1 players" in out


def test_lineup_says_the_practice_report_is_unavailable_rather_than_going_quiet(
        monkeypatch, tmp_path, capsys):
    """`injuries_<season>.csv` is a 404 until week 1 has been played, and a
    column that stops arriving must not do so silently. A LINE, not a "!!" note:
    an alarm here would fire on every run of the preseason."""
    import ffhelper.cli as cli
    from ffhelper.config import League, Tunables

    league = League(name="yahoo-main", platform="yahoo", league_id="L2")
    settings = _lineup_settings(num_teams=10, roster_slots={"QB": 1}, draft_id=None)
    monkeypatch.setattr(cli, "resolve_settings", lambda lg: settings)
    monkeypatch.setattr(cli, "load_players", lambda: {})
    monkeypatch.setattr(cli, "load_nfl_state", lambda: {"week": 1, "season": "2026"})
    monkeypatch.setattr(cli, "load_weekly_projections", lambda season, week: [])
    monkeypatch.setattr(cli, "load_nfl_injuries",
                        lambda season, week: (_ for _ in ()).throw(RuntimeError("404")))
    monkeypatch.setattr(cli, "ROSTER_DIR", tmp_path)

    assert cli._lineup(league, Tunables(), week=1) == 0
    out = capsys.readouterr().out

    assert "practice report : unavailable" in out
    assert "!! practice" not in out
