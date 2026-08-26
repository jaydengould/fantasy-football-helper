from pathlib import Path

from ffhelper.config import get_league, load_config


def test_loads_two_leagues_and_defaults(tmp_path: Path):
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        """
[tunables]
tier_break_sigma = 1.0

[[league]]
name = "sleeper-main"
platform = "sleeper"
league_id = "1395959490938966016"
draft_slot = 3

[[league]]
name = "yahoo-main"
platform = "yahoo"
league_id = "12345"
"""
    )
    leagues, tun = load_config(cfg)
    assert [lg.name for lg in leagues] == ["sleeper-main", "yahoo-main"]
    assert get_league(leagues, "sleeper-main").draft_slot == 3
    assert get_league(leagues, "yahoo-main").draft_slot is None
    assert tun.tier_break_sigma == 1.0
    # defaults applied for unspecified tunables
    assert tun.divergence_flag_slots == 10
    assert tun.flex_share == {"RB": 0.5, "WR": 0.5, "TE": 0.0}
    assert tun.poll_seconds == {"sleeper": 5, "yahoo": 12}


def test_unknown_league_raises(tmp_path: Path):
    cfg = tmp_path / "config.toml"
    cfg.write_text('[[league]]\nname = "a"\nplatform = "sleeper"\nleague_id = "1"\n')
    leagues, _ = load_config(cfg)
    try:
        get_league(leagues, "nope")
    except KeyError as e:
        assert "nope" in str(e)
    else:
        raise AssertionError("expected KeyError")


def test_partial_flex_share_merges_with_defaults(tmp_path: Path):
    """Partial flex_share edit should override only specified keys, inherit the rest."""
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        """
[tunables.flex_share]
RB = 0.6
"""
    )
    _, tun = load_config(cfg)
    assert tun.flex_share == {"RB": 0.6, "WR": 0.5, "TE": 0.0}


def test_partial_poll_seconds_merges_with_defaults(tmp_path: Path):
    """Partial poll_seconds edit should override only specified keys, inherit the rest."""
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        """
[tunables.poll_seconds]
yahoo = 20
"""
    )
    _, tun = load_config(cfg)
    assert tun.poll_seconds == {"sleeper": 5, "yahoo": 20}


def test_no_tunables_section_yields_all_defaults(tmp_path: Path):
    """Missing [tunables] section should result in all default tunable values."""
    cfg = tmp_path / "config.toml"
    cfg.write_text('[[league]]\nname = "test"\nplatform = "sleeper"\nleague_id = "1"\n')
    _, tun = load_config(cfg)
    assert tun.tier_break_sigma == 1.0
    assert tun.divergence_flag_slots == 10
    assert tun.flex_share == {"RB": 0.5, "WR": 0.5, "TE": 0.0}
    assert tun.poll_seconds == {"sleeper": 5, "yahoo": 12}
