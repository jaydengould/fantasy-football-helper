"""Test C's scoring rule: a lineup call is a RANKING, not a distance.

Test B asks how far a projection was from the truth over every projected
player-week. Test C asks the question the lineup screen actually asks -- given
two players who could fill one slot and are projected within a few points, did
the higher projection outscore the other? These cover the three things that
rule has to get right and that a MAE cannot: who is even eligible to be in a
pair, which pairs have a right answer at all, and whether an arm CHANGED the
pick (an arm that never flips one scores identically to the baseline and has
proved nothing).

No network, no database: hand-built projection and actual rows throughout.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import pytest

from backtest_weekly import WEEKS, close_call_pairs, summarize
from ffhelper.data import LeagueSettings, Player

SCORING = {"rec": 1.0}
SETTINGS = LeagueSettings(
    num_teams=1, scoring=SCORING, roster_slots={"RB": 3}, rounds=3)
FLEX_SHARE = {"RB": 0.0, "WR": 0.0, "TE": 0.0}


def mk(pid: str, pos: str = "RB") -> Player:
    return Player(pid, f"P{pid}", pos, "SEA")


def act(pid: str, week: int, pts: float, opponent: str = "DEN") -> dict:
    return {"player_id": pid, "week": week, "opponent": opponent,
            "stats": {"rec": pts}}


def full_season(proj: dict[int, dict], acts: dict[int, list]) -> tuple[dict, dict]:
    """Pad a week or two of fixture out to the shape load_season returns."""
    return ({w: dict(proj.get(w, {})) for w in WEEKS},
            {w: list(acts.get(w, [])) for w in WEEKS})


def test_only_startable_players_form_pairs():
    """The pool is `startable_pool` -- RB1..RB3 in this one-team league. The
    two players below that depth are 0.2 apart, the closest call on the board,
    and nobody chooses between them: no such pair may be scored."""
    players = {p: mk(p) for p in "abcd"}
    proj, acts = full_season(
        {2: {"a": 10.0, "b": 9.5, "c": 5.0, "d": 4.8}},
        {2: [act("a", 2, 1.0), act("b", 2, 20.0),
             act("c", 2, 3.0), act("d", 2, 20.0)]})

    scored = close_call_pairs(proj, acts, players, SETTINGS, FLEX_SHARE, 0.0)

    assert sorted(round(s.gap, 2) for s in scored["RB"]) == [0.5, 4.5, 5.0]


def test_a_pair_with_no_right_answer_is_not_a_decision():
    """Both players scored the same. There is no pick that was correct, so
    counting it as a hit or a miss would move the rate either way for free."""
    players = {p: mk(p) for p in "ab"}
    proj, acts = full_season(
        {2: {"a": 10.0, "b": 9.5}},
        {2: [act("a", 2, 12.0), act("b", 2, 12.0)]})

    assert close_call_pairs(proj, acts, players, SETTINGS, FLEX_SHARE, 0.0)["RB"] == []


def test_the_baseline_is_scored_on_projection_order():
    players = {p: mk(p) for p in "ab"}
    proj, acts = full_season(
        {2: {"a": 10.0, "b": 9.5}},
        {2: [act("a", 2, 1.0), act("b", 2, 20.0)]})

    (pair,) = close_call_pairs(proj, acts, players, SETTINGS, FLEX_SHARE, 0.0)["RB"]

    assert pair.gap == pytest.approx(0.5)
    assert not pair.base_hit          # a was projected higher and lost
    assert not pair.flipped           # factor 1.0 both sides -> same pick


def test_a_flip_is_recorded_and_scored_on_its_own():
    """Week 1 says DEN smothers running backs and SF is a sieve. That is enough
    for the matchup arm to reverse a 1.0-point projection gap -- and here the
    reversal is right, so the flip counts as a hit for the arm and a miss for
    the baseline on the SAME pair."""
    players = {p: mk(p) for p in "abxy"}
    proj, acts = full_season(
        {2: {"a": 10.0, "b": 9.0}},
        {1: [act("x", 1, 2.0, "DEN"), act("y", 1, 20.0, "SF")],
         2: [act("a", 2, 5.0, "DEN"), act("b", 2, 8.0, "SF")]})

    (pair,) = close_call_pairs(proj, acts, players, SETTINGS, FLEX_SHARE, 0.0)["RB"]

    assert pair.flipped
    assert not pair.base_hit
    assert pair.arm_hit


def test_summary_share_is_close_calls_over_every_scored_pair():
    """The share column is item 15's own premise, measured: how few of the
    startable pairs are decisions at all."""
    players = {p: mk(p) for p in "abc"}
    proj, acts = full_season(
        {2: {"a": 10.0, "b": 9.5, "c": 1.0}},
        {2: [act("a", 2, 1.0), act("b", 2, 20.0), act("c", 2, 30.0)]})

    scored = close_call_pairs(proj, acts, players, SETTINGS, FLEX_SHARE, 0.0)
    summary = summarize(scored["RB"], gap=1.0)

    assert summary.n == 1                         # only (a, b) is within 1.0
    assert summary.share == pytest.approx(1 / 3)  # of three scored pairs
    assert summary.base == pytest.approx(0.0)
    assert summary.flips == 0
