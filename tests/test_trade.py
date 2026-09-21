"""ffhelper.trade is PURE -- these tests never touch the network."""
import pytest

from ffhelper.data import Player
from ffhelper import season, trade


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
    exhaustively before implementing (see `_swap_case`'s docstring).

    Found by SHAPE, not by rank: once Task 7 adds 2-for-2, a 2-for-2 (te+wr2
    for trb3+tte, gain_me 15.6) legitimately outranks this 14.0 1-for-1 -- that
    is 2-for-2 doing exactly what it is for, not a regression. `out[0]` was
    Task 5's assumption before a bigger shape existed to compete with it."""
    mine, theirs, wbw = _swap_case()
    out = trade.trade_options(mine, theirs, opponent=7, roster_slots=SLOTS,
                              weekly_by_week=wbw, floor=1.0)
    one_for_one = [p for p in out if len(p.give) == 1 and len(p.get) == 1]
    assert one_for_one, "the surplus case must produce at least one 1-for-1 proposal"
    best = one_for_one[0]
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


def test_two_for_one_names_the_cut_the_counterparty_must_make():
    """They receive two and send one, so they land at 16 players -- illegal.
    The league forces a cut, that cut is part of what the trade costs them, and
    a proposal that hides it is quoting them a price they have not been told."""
    mine, theirs, wbw = _swap_case()
    out = trade.trade_options(mine, theirs, 7, SLOTS, wbw, floor=0.5)
    two_for_one = [p for p in out if len(p.give) == 2 and len(p.get) == 1]
    assert two_for_one, "the 2-for-1 shape must be searched"
    assert all(p.their_drop is not None for p in two_for_one)
    assert all(p.their_drop.sleeper_id not in {g.sleeper_id for g in p.get}
               for p in two_for_one), "they cannot cut the player they just sent"


def test_my_fourteen_man_roster_is_not_refilled_from_the_wire():
    """A 2-for-1 leaves me at 14, which is LEGAL, so nothing is invented. The
    first probe added a free agent here and inflated every gain by whatever the
    wire happened to be worth -- conflating a trade with a waiver add, which
    `waivers` already answers separately."""
    mine, theirs, wbw = _swap_case()
    out = trade.trade_options(mine, theirs, 7, SLOTS, wbw, floor=0.5)
    for p in out:
        if len(p.give) == 2 and len(p.get) == 1:
            kept = [x for x in mine if x.sleeper_id not in {g.sleeper_id for g in p.give}]
            expected = season.horizon_total([*kept, *p.get], SLOTS, wbw) \
                - season.horizon_total(mine, SLOTS, wbw)
            assert p.gain_me == pytest.approx(expected)


def test_two_for_two_is_searched_and_is_roster_neutral():
    """The shape that carries the surplus. Measured on the real league: 1-for-1
    clears the floor zero times, 2-for-2 clears it 49 times across three
    opponents, because only a multi-player swap can change how many bodies each
    side carries at a position."""
    mine, theirs, wbw = _swap_case()
    out = trade.trade_options(mine, theirs, 7, SLOTS, wbw, floor=0.5)
    two_two = [p for p in out if len(p.give) == 2 and len(p.get) == 2]
    assert two_two
    assert all(p.their_drop is None for p in two_two), "nobody is cut, both stay at 7"


def test_pinning_a_player_of_mine_keeps_only_offers_that_send_him():
    """'What is the best return for X?' -- so every row must send X."""
    mine, theirs, wbw = _swap_case()
    pin = next(p for p in mine if p.sleeper_id == "wr3")
    out = trade.trade_options(mine, theirs, 7, SLOTS, wbw, floor=0.5, pin=pin)
    assert out
    assert all("wr3" in {g.sleeper_id for g in p.give} for p in out)


def test_pinning_a_player_of_theirs_keeps_only_offers_that_acquire_him():
    """'What would it take to get Y?' -- so every row must receive Y. The side
    is chosen by roster MEMBERSHIP, not by an argument the caller passes: two
    sources of truth for one fact disagree eventually."""
    mine, theirs, wbw = _swap_case()
    pin = next(p for p in theirs if p.sleeper_id == "trb3")
    out = trade.trade_options(mine, theirs, 7, SLOTS, wbw, floor=0.5, pin=pin)
    assert out
    assert all("trb3" in {g.sleeper_id for g in p.get} for p in out)


def test_pinning_still_requires_both_sides_to_clear_the_floor():
    """Pinning narrows the search; it does not lower the bar."""
    mine, theirs, wbw = _swap_case()
    pin = next(p for p in mine if p.sleeper_id == "wr3")
    out = trade.trade_options(mine, theirs, 7, SLOTS, wbw, floor=100.0, pin=pin)
    assert out == []


def test_their_drop_is_computed_after_stripping_the_players_they_sent():
    """`their_drop.sleeper_id not in get` (above) is structurally guaranteed
    whatever best_drop does, because `_without` already removes every `get`
    player from `theirs` before best_drop ever runs -- proven by mutating that
    strip away and finding the assertion still passes. This proves the strip
    directly, by recomputing the counterparty's post-trade total the same way
    `consider` should and checking it against what came out."""
    mine, theirs, wbw = _swap_case()
    out = trade.trade_options(mine, theirs, 7, SLOTS, wbw, floor=0.5)
    two_for_one = [p for p in out if len(p.give) == 2 and len(p.get) == 1]
    assert two_for_one
    base_them = season.horizon_total(theirs, SLOTS, wbw)
    for p in two_for_one:
        after = [*trade._without(theirs, p.get), *p.give]
        expected_total, expected_drop = season.best_drop(after, SLOTS, wbw)
        assert p.gain_them == pytest.approx(expected_total - base_them)
        assert p.their_drop.sleeper_id == expected_drop.sleeper_id


def _grade(give, get, floor=1.0, my_limit=8, their_limit=8):
    mine, theirs, wbw = _swap_case()
    by = {p.sleeper_id: p for p in [*mine, *theirs]}
    return trade.grade_offer(mine, theirs, [by[i] for i in give], [by[i] for i in get],
                             SLOTS, wbw, floor, my_limit, their_limit)


def test_grade_scores_both_sides_of_a_received_offer():
    """wr3 for trb3, by hand: my RB pair 12+6 -> 13+12 (+7/wk); their WRs
    14.5+14 -> 16+14.5 with twr1 taking the flex at 14 (+2/wk). Two weeks."""
    g = _grade(["wr3"], ["trb3"])
    assert (g.gain_me, g.gain_them) == (pytest.approx(14.0), pytest.approx(4.0))
    assert g.verdict == "accept"
    assert g.my_drops == () and g.their_drops == ()


def test_grade_declines_an_offer_that_costs_me_more_than_the_floor():
    """wr1 (20, a starter) for tqb (19, behind my 25): WRs 20+19 -> 19+16,
    flex stays te 16.2 -- -4/wk, -8 over two."""
    g = _grade(["wr1"], ["tqb"])
    assert g.gain_me == pytest.approx(-8.0)
    assert g.verdict == "decline"


def test_grade_inside_the_floor_is_too_close_to_call_on_both_signs():
    """te2 (22) for tte (20): -2/wk, -4 total. The bands are strict: exactly
    the floor is not enough to call it either way."""
    assert _grade(["te2"], ["tte"], floor=5.0).verdict == "too close to call"
    assert _grade(["te2"], ["tte"], floor=4.0).verdict == "too close to call"
    assert _grade(["te2"], ["tte"], floor=3.9).verdict == "decline"
    assert _grade(["wr3"], ["trb3"], floor=14.0).verdict == "too close to call"
    assert _grade(["wr3"], ["trb3"], floor=13.9).verdict == "accept"


def test_receiving_more_than_i_give_forces_my_own_cut():
    """The shape the finder never builds: they send two for one, and my full
    roster must cut someone. tte2 (14) cannot crack my lineup and neither
    can rb2 (6) once trb3 arrives; rb2 carries fewer points of his own."""
    g = _grade(["wr3"], ["trb3", "tte2"])
    assert [p.sleeper_id for p in g.my_drops] == ["rb2"]
    assert g.gain_me == pytest.approx(14.0)
    # An open roster spot absorbs the extra player: no phantom cut.
    assert _grade(["wr3"], ["trb3", "tte2"], my_limit=9).my_drops == ()


def test_their_forced_cut_is_named_when_they_receive_more():
    g = _grade(["wr3", "rb2"], ["trb3"])
    assert [p.sleeper_id for p in g.their_drops] == ["rb2"]
    assert g.my_drops == ()


def test_a_forced_cut_that_empties_a_starting_slot_shows_its_cost():
    """my_limit 6 on wr3-for-trb3: two cuts. rb2 is free (benched once trb3
    arrives); the second is rb1, whose RB slot then sits EMPTY -- 12/wk, 24
    over two. The drop is not weighted, it is counted: 14 - 24 = -10."""
    g = _grade(["wr3"], ["trb3"], my_limit=6)
    assert [p.sleeper_id for p in g.my_drops] == ["rb2", "rb1"]
    assert g.drop_cost == pytest.approx(24.0)
    assert g.gain_me == pytest.approx(-10.0)
    assert _grade(["wr3"], ["trb3"]).drop_cost == 0.0


# keep_mine: hand-built so a bench player matters. RB/WR slots, a full
# three-man roster, two weeks, my rb on bye in week 2 so the bench RB starts.
#   base:  wk1 rb 10 + wr 10 = 20;  wk2 bn 4 + wr 10 = 14      -> 34
KEEP_SLOTS = {"RB": 1, "WR": 1}


def _keep_case(get_ids, trb=5.0, floor=1.5):
    mine = [mk("rb", "RB"), mk("wr", "WR"), mk("bn", "RB")]
    theirs = [mk("w1", "WR"), mk("w2", "WR"), mk("trb", "RB")]
    wk = {"rb": 10.0, "wr": 10.0, "bn": 4.0, "w1": 13.0, "w2": 12.0, "trb": trb}
    wbw = {1: wk, 2: {**wk, "rb": 0.0}}
    by = {p.sleeper_id: p for p in [*mine, *theirs]}
    args = (mine, theirs, [by["wr"]], [by[i] for i in get_ids], KEEP_SLOTS, wbw,
            floor, 3, 9)
    return trade.grade_offer(*args), trade.keep_mine(*args)


def test_keeping_my_bench_player_is_offered_with_its_cost():
    """wr for w1 + trb. Cutting bn keeps trb, who beats him in week 2 (5 v 4):
    wk1 rb 10 + w1 13, wk2 trb 5 + w1 13 -> 41, +7. The ask keeps bn by
    leaving trb with them: wk2 bn 4 + w1 13 -> 40, +6. Keeping him costs 1.0,
    and the ask is shown anyway -- whether bn is worth 1.0 is the reader's."""
    full, ask = _keep_case(["w1", "trb"])
    assert [p.sleeper_id for p in full.my_drops] == ["bn"]
    assert full.gain_me == pytest.approx(7.0)
    assert [p.sleeper_id for p in ask.get] == ["w1"]
    assert ask.gain_me == pytest.approx(6.0)
    assert ask.my_drops == ()


def test_no_ask_when_the_cut_is_a_player_i_would_receive():
    """trb at 3.0 loses the week-2 start to bn (4), so HE is the cut. Accept
    and cut him: asking for fewer changes nothing."""
    full, ask = _keep_case(["w1", "trb"], trb=3.0)
    assert [p.sleeper_id for p in full.my_drops] == ["trb"]
    assert ask is None


def test_no_ask_when_the_smaller_offer_would_not_be_accepted():
    """+6 against a 6.5 floor is too close to call -- not worth countering with."""
    full, ask = _keep_case(["w1", "trb"], floor=6.5)
    assert full.gain_me == pytest.approx(7.0) and ask is None


def test_the_best_keep_ask_wins_not_the_first_one_found():
    """wr for w2 + w1 + trb: two cuts, bn (mine) and w2. Asks that cut none
    of mine: w2 alone +4 (found FIRST), w1 alone +6, w2+w1 +6 (cuts w2, who
    is theirs). Best for me, then fewest players: w1 alone."""
    full, ask = _keep_case(["w2", "w1", "trb"])
    assert "bn" in [p.sleeper_id for p in full.my_drops]
    assert [p.sleeper_id for p in ask.get] == ["w1"]
    assert ask.gain_me == pytest.approx(6.0)
