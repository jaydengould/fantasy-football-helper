from ffhelper import cli, pipeline
from ffhelper.config import League, Tunables
from ffhelper.data import LeagueSettings


def test_build_lineup_reports_error_when_week_unresolvable(monkeypatch):
    """No week from /state/nfl and none passed: a message, not a traceback.

    Guessing a week is the fabrication the design forbids, so the builder must
    surface the same refusal the CLI prints.

    Both `cli.resolve_settings` and `cli._resolve_week` are patched -- `pipeline`
    calls both through the `cli` module object, matching the original `_lineup`'s
    order (settings first), so `resolve_settings` must be stubbed too or this
    test would hit the network under conftest's `_no_network` guard.
    """
    stub_settings = LeagueSettings(num_teams=12, scoring={"pass_td": 6.0},
                                   roster_slots={"QB": 1}, rounds=1, draft_id="D1")
    monkeypatch.setattr(cli, "resolve_settings", lambda lg: stub_settings)
    monkeypatch.setattr(cli, "_resolve_week", lambda w: (None, "2026", [], None))
    league = League(name="sleeper-main", platform="sleeper", league_id="1")
    view = pipeline.build_lineup(league, Tunables(), week=None)
    assert view.error is not None
    assert "--week" in view.error
    assert view.state is None


def test_build_waivers_refuses_non_sleeper_platform():
    """Yahoo serves no rosters, so the free-agent pool cannot be built.

    A pool derived from one hand-entered roster would be silently wrong, which
    is worse than absent -- so this is a refusal, not a degradation.
    """
    league = League(name="yahoo-main", platform="yahoo", league_id="9")
    view = pipeline.build_waivers(league, Tunables())
    assert view.error is not None
    assert "yahoo" in view.error
    assert "Sleeper-only" in view.error
    assert view.this_week == []


def test_build_trades_past_deadline_is_not_an_error(monkeypatch):
    """A passed deadline is a legal state: exit 0, not 1.

    Printing proposals you are not allowed to make is worse than printing none,
    but it is not a failure -- and the CLI's exit code must stay 0.

    Patched on `cli`, not `pipeline`: `build_trades` calls both names through
    the `cli` module object (see the module docstring), so patching bare names
    on `pipeline` would silently miss and fall through to the real network
    call, which conftest's `_no_network` guard would then trip.
    """
    class S:
        trade_deadline = 5
        roster_slots = {"QB": 1}
        scoring = {}
    monkeypatch.setattr(cli, "resolve_settings", lambda lg: S())
    monkeypatch.setattr(cli, "_resolve_week", lambda w: (9, "2026", [], 9))
    league = League(name="sleeper-main", platform="sleeper", league_id="1")
    view = pipeline.build_trades(league, Tunables(), week=9)
    assert view.deadline_passed is True
    assert view.error is not None
    assert "week 5" in view.error
    assert view.best == []
