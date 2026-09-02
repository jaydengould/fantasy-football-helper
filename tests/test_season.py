"""ffhelper.season is PURE -- these tests never touch the network."""
import pytest
from dataclasses import dataclass

from ffhelper.data import Player
from ffhelper import season


def mk(pid: str, pos: str, pts: float = 0.0) -> Player:
    return Player(pid, f"P{pid}", pos, "SEA", proj_pts=pts)


def test_weekly_points_scores_raw_stats_under_this_leagues_rules():
    """The same stat line is worth different points in the two leagues. Scoring
    a WEEK is the identical operation as scoring a season -- score_stats is
    reused rather than reimplemented."""
    rows = [
        {"player_id": "a", "stats": {"rec": 5.0, "rec_yd": 60.0, "rec_td": 0.5}},
        {"player_id": "b", "stats": {"rec": 5.0, "rec_yd": 60.0, "rec_td": 0.5}},
    ]
    full_ppr = {"rec": 1.0, "rec_yd": 0.1, "rec_td": 6.0}
    half_ppr = {"rec": 0.5, "rec_yd": 0.1, "rec_td": 6.0}

    assert season.weekly_points(rows, full_ppr)["a"] == pytest.approx(5 + 6 + 3)
    assert season.weekly_points(rows, half_ppr)["a"] == pytest.approx(2.5 + 6 + 3)


def test_weekly_points_skips_rows_with_no_stats_rather_than_scoring_zero():
    """A player with no projection this week (bye, or not in the payload) must be
    ABSENT, not 0.0. Absent lets the caller say 'no projection'; 0.0 is a claim
    that he will score nothing, which is a fabricated number."""
    rows = [{"player_id": "a", "stats": None}, {"player_id": "b"},
            {"stats": {"rec": 1.0}}]
    assert season.weekly_points(rows, {"rec": 1.0}) == {}


def test_with_weekly_points_returns_new_players_and_never_mutates_the_pool():
    """optimal_lineup ranks on proj_pts, which holds SEASON points. Start/sit
    must rank on the WEEK. Copying rather than mutating keeps the season pool
    usable in the same process -- the draft board and this command share it."""
    roster = [mk("a", "RB", 250.0), mk("b", "RB", 200.0)]
    out = season.with_weekly_points(roster, {"a": 12.5})

    assert [p.proj_pts for p in out] == [12.5, 0.0]
    assert [p.proj_pts for p in roster] == [250.0, 200.0]
    assert out[0] is not roster[0]
