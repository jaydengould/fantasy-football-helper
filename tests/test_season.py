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


SLOTS = {"QB": 1, "RB": 2, "WR": 2, "TE": 1, "FLEX": 1, "K": 1, "DEF": 1}


def test_start_sit_names_the_lineup_and_the_bench():
    """The lineup is value.optimal_lineup's -- imported, never re-derived. A
    second copy of the FLEX rule is what lets two views disagree about one
    roster (the Phase 3 lesson)."""
    roster = [mk("q", "QB", 20.0), mk("r1", "RB", 15.0), mk("r2", "RB", 12.0),
              mk("r3", "RB", 4.0), mk("w1", "WR", 14.0), mk("w2", "WR", 11.0),
              mk("t", "TE", 8.0), mk("k", "K", 7.0), mk("d", "DEF", 6.0)]
    got = season.start_sit(roster, SLOTS)

    assert [s for s, _ in got.lineup] == ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "K", "DEF"]
    assert [p.sleeper_id for _, p in got.lineup] == ["q", "r1", "r2", "w1", "w2", "t", "r3", "k", "d"]
    assert [p.sleeper_id for p in got.bench] == []


def test_start_sit_reports_a_close_call_and_ignores_a_blowout():
    """A 1.5-point gap is a decision; a 30-point gap is noise on the screen.
    Only the close ones are worth a human's attention."""
    roster = [mk("q", "QB", 20.0),
              mk("w1", "WR", 14.0), mk("w2", "WR", 11.0),
              mk("w3", "WR", 10.5),      # 0.5 behind w2 -- a real decision
              mk("w4", "WR", 2.0)]       # 9 behind -- not
    got = season.start_sit(roster, {"QB": 1, "WR": 2}, close_call_points=3.0)

    assert len(got.close_calls) == 1
    call = got.close_calls[0]
    assert (call.slot, call.starter.sleeper_id, call.challenger.sleeper_id) == ("WR", "w2", "w3")
    assert call.gap == pytest.approx(0.5)


def test_start_sit_never_offers_an_ineligible_challenger():
    """A kicker on the bench is not a challenger for a WR slot, however close his
    projection. FLEX_ELIGIBLE is value.py's rule and is imported, not restated."""
    roster = [mk("w1", "WR", 12.0), mk("k1", "K", 11.5), mk("k2", "K", 11.0)]
    got = season.start_sit(roster, {"WR": 1, "K": 1}, close_call_points=3.0)

    assert [(c.slot, c.challenger.sleeper_id) for c in got.close_calls] == [("K", "k2")]


def test_start_sit_reports_an_unfillable_slot_rather_than_hiding_it():
    """An empty slot is a roster problem the user must SEE -- it is the week's
    most important message and it must not be silently dropped."""
    got = season.start_sit([mk("q", "QB", 20.0)], {"QB": 1, "RB": 1})
    assert got.lineup == [("QB", got.lineup[0][1]), ("RB", None)]
