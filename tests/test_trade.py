"""ffhelper.trade is PURE -- these tests never touch the network."""
import pytest

from ffhelper.data import Player
from ffhelper import trade


def mk(pid: str, pos: str) -> Player:
    return Player(pid, f"P{pid}", pos, "SEA", proj_pts=0.0)


SLOTS = {"QB": 1, "RB": 2, "WR": 2, "TE": 1, "FLEX": 1}


def _swap_case():
    """A roster pair with a REAL surplus, not a contrived one.

    THE ORIGINAL VERSION OF THIS FIXTURE WAS WRONG. With exactly 7 players on
    a 7-slot roster (1 QB + 2 RB + 3 WR + 1 TE against QB/RB2/WR2/TE/FLEX),
    every flex-eligible player fills a slot -- there is no bench on either
    side, `lineup_value` is just the sum of the roster, and a 1-for-1 swap is
    then exactly zero-sum (gain_me == -gain_them). No fixture shaped like that
    can ever produce a mutually beneficial trade. Caught by doing the "compute
    by hand first" step the brief asks for, the same way the 4c plan's tie
    fixture was caught.

    The fix is a genuine bench on both sides. Each roster carries a second TE
    (`te2` / `tte2`) as a bystander who is good enough to win the FLEX spot
    outright -- which is what pushes a real player (WR3 for me, RB3 for them)
    onto the bench instead of into it by force of arithmetic. I hold 3 good
    WRs and only 2 RBs; WR3 (16.0) loses the FLEX job to my own te (16.2) and
    sits on my bench doing nothing. They hold 3 good RBs and only 2 WRs;
    RB3 (13.0) loses their FLEX job to their own tte2 (14.0) the same way.

    Trading my benched WR3 for their benched RB3 costs each of us a player who
    was contributing zero, and each of us receives a player who promptly
    displaces a WEAKER STARTER (RB3 bumps my rb2 out of a required RB slot;
    WR3 bumps their weaker required WR) -- a real upgrade on both sides from a
    swap that cost neither side an active player. That is the actual
    lineup-constraint mechanism, not an assumption.

    Verified exhaustively (all 8x8 one-for-one combinations, via
    `trade.trade_options` itself) before writing the assertions below: this
    is the only pair with a floor-clearing gain_me, and it is the max one at
    14.0 vs the next-best 13.6.
    """
    mine = [mk("qb", "QB"), mk("rb1", "RB"), mk("rb2", "RB"),
            mk("wr1", "WR"), mk("wr2", "WR"), mk("wr3", "WR"),
            mk("te", "TE"), mk("te2", "TE")]
    theirs = [mk("tqb", "QB"), mk("trb1", "RB"), mk("trb2", "RB"), mk("trb3", "RB"),
              mk("twr1", "WR"), mk("twr2", "WR"), mk("tte", "TE"), mk("tte2", "TE")]
    week = {
        "qb": 25.0, "rb1": 12.0, "rb2": 6.0,
        "wr1": 20.0, "wr2": 19.0, "wr3": 16.0,
        "te": 16.2, "te2": 22.0,
        "tqb": 19.0, "trb1": 30.0, "trb2": 15.0, "trb3": 13.0,
        "twr1": 14.0, "twr2": 14.5,
        "tte": 20.0, "tte2": 14.0,
    }
    return mine, theirs, {1: week, 2: dict(week)}


def test_a_mutually_beneficial_one_for_one_is_found():
    """My benched WR3 (16.0) upgrades their weaker required WR slot; their
    benched RB3 (13.0) upgrades my weaker required RB slot -- each of us
    unlocks a STARTING-slot improvement from a player who was contributing
    nothing, which is why both gain. Numbers computed by hand and checked
    exhaustively before implementing (see `_swap_case`'s docstring)."""
    mine, theirs, wbw = _swap_case()
    out = trade.trade_options(mine, theirs, opponent=7, roster_slots=SLOTS,
                              weekly_by_week=wbw, floor=1.0)
    assert out, "the surplus case must produce at least one proposal"
    best = out[0]
    assert {p.sleeper_id for p in best.give} == {"wr3"}
    assert {p.sleeper_id for p in best.get} == {"trb3"}
    assert best.gain_me > 1.0 and best.gain_them > 1.0
    assert best.their_drop is None      # roster-neutral, nobody is cut
    assert best.opponent == 7


def test_a_proposal_that_helps_only_me_is_refused():
    """The board is an argument you send to another human. A swap the
    counterparty loses on is not a proposal, it is a fantasy."""
    mine, theirs, wbw = _swap_case()
    out = trade.trade_options(mine, theirs, opponent=7, roster_slots=SLOTS,
                              weekly_by_week=wbw, floor=1.0)
    assert all(p.gain_them > 1.0 for p in out)


def test_the_floor_applies_to_BOTH_sides():
    """Measured on the real league: requiring only 'positive for them' is the
    difference between 11 rows of noise and 1 real row. A gain smaller than the
    error on the number that produced it cannot be defended."""
    mine, theirs, wbw = _swap_case()
    loose = trade.trade_options(mine, theirs, 7, SLOTS, wbw, floor=0.0)
    strict = trade.trade_options(mine, theirs, 7, SLOTS, wbw, floor=100.0)
    assert loose and not strict


def test_results_are_deterministic_across_runs():
    """A board that renames a package when nothing changed is one nobody can
    trust -- the same rule roster_upgrade's tie-break already follows."""
    mine, theirs, wbw = _swap_case()
    a = trade.trade_options(mine, theirs, 7, SLOTS, wbw, floor=0.5)
    b = trade.trade_options(list(reversed(mine)), list(reversed(theirs)), 7,
                            SLOTS, wbw, floor=0.5)
    assert [( [p.sleeper_id for p in x.give], [p.sleeper_id for p in x.get]) for x in a] \
        == [( [p.sleeper_id for p in x.give], [p.sleeper_id for p in x.get]) for x in b]
