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
