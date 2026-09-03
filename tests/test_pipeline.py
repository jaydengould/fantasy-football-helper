import pytest
from ffhelper import pipeline
from ffhelper.config import League, Tunables


def test_build_lineup_reports_error_when_week_unresolvable(monkeypatch):
    """No week from /state/nfl and none passed: a message, not a traceback.

    Guessing a week is the fabrication the design forbids, so the builder must
    surface the same refusal the CLI prints.
    """
    monkeypatch.setattr(pipeline, "_resolve_week", lambda w: (None, "2026", [], None))
    league = League(name="sleeper-main", platform="sleeper", league_id="1")
    view = pipeline.build_lineup(league, Tunables(), week=None)
    assert view.error is not None
    assert "--week" in view.error
    assert view.state is None
