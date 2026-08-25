"""Pure engine tests. Synthetic players only -- the engine is arithmetic and
does not care whether the numbers are real."""
import pytest

from ffhelper.data import Player
from ffhelper.value import (
    assign_tiers, replacement_points, replacement_ranks, vbd,
)

SLOTS = {"QB": 1, "RB": 2, "WR": 2, "TE": 1, "FLEX": 2, "K": 1, "DEF": 1}
FLEX_SHARE = {"RB": 0.5, "WR": 0.5, "TE": 0.0}


def mk(pid: str, pos: str, pts: float, adp: float = 50.0, stdev: float = 5.0) -> Player:
    return Player(pid, f"P{pid}", pos, "SF", proj_pts=pts, adp=adp, adp_stdev=stdev)


def test_replacement_ranks_for_real_league():
    """Sleeper league: 12 teams, 1QB/2RB/2WR/1TE/2FLEX, flex split 50/50.
    RB = 12 * (2 + 0.5*2) = 36. WR the same. QB and TE take no flex share."""
    got = replacement_ranks(SLOTS, num_teams=12, flex_share=FLEX_SHARE)
    assert got["QB"] == 12
    assert got["TE"] == 12
    assert got["RB"] == 36
    assert got["WR"] == 36


def test_replacement_ranks_scale_with_league_size():
    """Yahoo league: same roster shape, 10 teams -> everything shallower."""
    got = replacement_ranks(SLOTS, num_teams=10, flex_share=FLEX_SHARE)
    assert got["QB"] == 10
    assert got["TE"] == 10
    assert got["RB"] == 30
    assert got["WR"] == 30


def test_flex_share_shifts_replacement_between_positions():
    """The flex_share knob must actually move replacement depth, or it is
    decoration. A WR-heavy flex pushes WR deeper and RB shallower."""
    wr_heavy = replacement_ranks(SLOTS, 12, {"RB": 0.25, "WR": 0.75, "TE": 0.0})
    assert wr_heavy["RB"] == 30
    assert wr_heavy["WR"] == 42


def test_vbd_is_points_over_replacement():
    players = [mk(str(i), "RB", 100.0 - i) for i in range(5)]
    repl = replacement_points(players, {"RB": 3})
    assert repl["RB"] == 98.0          # 3rd best RB
    scores = vbd(players, repl)
    assert scores["0"] == 2.0
    assert scores["4"] == -2.0


def test_replacement_uses_last_player_when_pool_is_short():
    players = [mk("0", "TE", 200.0), mk("1", "TE", 150.0)]
    repl = replacement_points(players, {"TE": 12})
    assert repl["TE"] == 150.0, "shallow pool falls back to the worst available"


def test_tiers_break_on_large_gaps():
    # 300, 295 | 200, 198 -- one huge gap, so two tiers
    players = [mk("a", "RB", 300.0), mk("b", "RB", 295.0),
               mk("c", "RB", 200.0), mk("d", "RB", 198.0)]
    scores = {p.sleeper_id: p.proj_pts for p in players}
    tiers = assign_tiers(players, scores, sigma=1.0)
    assert tiers["a"] == tiers["b"] == 1
    assert tiers["c"] == tiers["d"] == 2


def test_tiers_are_per_position():
    players = [mk("a", "RB", 300.0), mk("b", "WR", 299.0)]
    tiers = assign_tiers(players, {"a": 300.0, "b": 299.0}, sigma=1.0)
    assert tiers["a"] == 1 and tiers["b"] == 1


def test_tiers_handle_single_player_position():
    players = [mk("a", "K", 120.0)]
    assert assign_tiers(players, {"a": 120.0}, sigma=1.0) == {"a": 1}
