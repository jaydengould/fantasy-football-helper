import pytest

from ffhelper.cli import load_board_inputs, league_settings_from_config, render, resolve_settings
from ffhelper.config import League, Tunables
from ffhelper.data import LeagueSettings, Player
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
    assert "RB" in out and "5" in out


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
