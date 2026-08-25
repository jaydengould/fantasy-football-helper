"""Pure engine tests. Synthetic players only -- the engine is arithmetic and
does not care whether the numbers are real."""
import pytest

from ffhelper.data import Player
from ffhelper.value import (
    assign_tiers, replacement_points, replacement_ranks, vbd,
    lineup_value, marginal_value,
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


def _realistic_rb_pool():
    """8 draftable RBs with real gaps (one small, two big, one big, then a
    tight cluster), followed by a 110-player below-replacement tail with
    near-zero gaps. Mirrors the ~140-player real pool that exposed the bug:
    a whole-pool stdev is dragged near zero by the tail, so it clears real
    top-of-board gaps that a draftable-only stdev correctly keeps as breaks.
    """
    top8_scores = [65.5, 62.5, 44.5, 26.5, 9.5, 6.5, 3.5, 0.5]
    players = [mk(f"top{i}", "RB", s) for i, s in enumerate(top8_scores)]
    scores = {p.sleeper_id: s for p, s in zip(players, top8_scores)}
    for i in range(110):
        pid = f"tail{i}"
        val = round(0.0 - 0.01 * i, 4)  # 0.0, -0.01, ... all <= 0 (non-draftable)
        players.append(mk(pid, "RB", val))
        scores[pid] = val
    return players, scores


def test_tiers_scope_threshold_to_draftable_players():
    """Regression test for the whole-pool-stdev defect. The 110-player tail
    has tiny gaps (~0.01) that, if included in the threshold's stdev, drag it
    down to ~2.95 -- below the top group's own "small" gaps of 3.0, so every
    one of those gaps would incorrectly clear threshold and each of the top 8
    would land in its own tier: [1,2,3,4,5,6,7,8].

    Verified against the pre-fix formula (threshold = sigma * pstdev(ALL
    gaps in the position)) run standalone against this exact data: it
    produces top-8 tiers [1, 2, 3, 4, 5, 6, 7, 8] -- fully fragmented, so
    this test fails on that implementation. Scoping the stdev to the 8
    draftable players' own gaps ([3, 18, 18, 17, 3, 3, 3], pstdev ~7.27)
    keeps the "3" gaps below threshold and only the real 18/18/17 gaps break,
    giving [1, 1, 2, 3, 4, 4, 4, 4].
    """
    players, scores = _realistic_rb_pool()
    tiers = assign_tiers(players, scores, sigma=1.0)
    top8 = [tiers[f"top{i}"] for i in range(8)]
    assert top8 == [1, 1, 2, 3, 4, 4, 4, 4]
    assert len(tiers) == len(players), "every player, draftable or not, gets a tier"


def test_tiers_all_below_replacement_does_not_raise():
    """No player clears replacement (all scores <= 0) -- draftable_n is 0, so
    the threshold must fall back to the full gap set rather than dividing by
    a zero-length stdev input or raising. This discriminates against an
    implementation that assumes at least one positive score exists."""
    players = [mk(str(i), "RB", -float(i)) for i in range(6)]
    scores = {p.sleeper_id: -float(i) for i, p in enumerate(players)}
    tiers = assign_tiers(players, scores, sigma=1.0)
    assert len(tiers) == 6
    assert all(isinstance(t, int) and t >= 1 for t in tiers.values())


def test_sigma_is_a_coarseness_knob_on_realistic_pool():
    """Larger sigma must yield the same or fewer distinct tiers. On the
    realistic pool, sigma=0.5 breaks all 8 draftable gaps except the cluster
    (4 distinct tiers among the top 8 plus tail tiers); sigma=3.0 clears
    every gap in the top group (1 tier). A no-op sigma would make both equal
    or unrelated to input; here they must differ."""
    players, scores = _realistic_rb_pool()
    small_sigma_tiers = assign_tiers(players, scores, sigma=0.5)
    large_sigma_tiers = assign_tiers(players, scores, sigma=3.0)
    small_count = len(set(small_sigma_tiers.values()))
    large_count = len(set(large_sigma_tiers.values()))
    assert small_count == 4
    assert large_count == 1
    assert large_count <= small_count


def test_lineup_value_fills_dedicated_slots_then_flex():
    slots = {"QB": 1, "RB": 2, "WR": 2, "TE": 1, "FLEX": 1}
    roster = [
        mk("q", "QB", 300.0),
        mk("r1", "RB", 250.0), mk("r2", "RB", 200.0), mk("r3", "RB", 150.0),
        mk("w1", "WR", 240.0), mk("w2", "WR", 190.0),
        mk("t", "TE", 120.0),
    ]
    # 300 + 250 + 200 + 240 + 190 + 120 + flex(best leftover = r3 150) = 1450
    assert lineup_value(roster, slots) == 1450.0


def test_lineup_value_ignores_players_beyond_slots():
    slots = {"QB": 1}
    roster = [mk("q1", "QB", 300.0), mk("q2", "QB", 290.0)]
    assert lineup_value(roster, slots) == 300.0


def test_third_rb_adds_less_than_first():
    """The core insight the trade finder inherits: lineup constraints create
    diminishing returns, so a later RB adds less than the first. A fourth RB
    only upgrades the roster if he beats the current flex player."""
    slots = {"RB": 2, "FLEX": 1}
    empty: list[Player] = []
    three_rb = [mk("r1", "RB", 250.0), mk("r2", "RB", 200.0), mk("r3", "RB", 150.0)]

    # The same candidate added to an empty roster is worth the full amount.
    cand_180 = mk("new_180", "RB", 180.0)
    first = marginal_value(empty, cand_180, slots)
    assert first == 180.0

    # Added to a three-RB roster (250, 200, 150 in RB/RB/FLEX), the 180 upgrades
    # the FLEX slot from 150 to 180, adding exactly 30 points (diminishing return).
    fourth = marginal_value(three_rb, cand_180, slots)
    assert fourth == 30.0

    # A candidate worse than the current FLEX player adds nothing.
    cand_100 = mk("new_100", "RB", 100.0)
    assert marginal_value(three_rb, cand_100, slots) == 0.0

    # Verify the diminishing-returns relationship: first > fourth > zero
    assert first > fourth > 0.0


def test_marginal_value_of_upgrade_is_the_difference():
    slots = {"QB": 1}
    roster = [mk("q1", "QB", 300.0)]
    assert marginal_value(roster, mk("q2", "QB", 350.0), slots) == 50.0


def test_lineup_value_of_empty_roster_is_zero():
    assert lineup_value([], {"QB": 1, "RB": 2}) == 0.0


from ffhelper.value import (
    detect_run, divergence, next_pick_number, survival_prob, vona,
)


def test_snake_pick_sequence_for_slot_3_in_12_team():
    # slot 3 picks at 3, 22, 27, 46, 51 ...
    assert next_pick_number(current_pick=1, slot=3, num_teams=12) == 3
    assert next_pick_number(current_pick=3, slot=3, num_teams=12) == 22
    assert next_pick_number(current_pick=22, slot=3, num_teams=12) == 27
    assert next_pick_number(current_pick=27, slot=3, num_teams=12) == 46


def test_snake_endpoints_turn_correctly():
    # slot 1 picks 1 then 24; slot 12 picks 12 then 13 (the turn)
    assert next_pick_number(1, 1, 12) == 24
    assert next_pick_number(12, 12, 12) == 13


def test_survival_decreases_as_pick_number_rises():
    p = mk("a", "RB", 200.0, adp=20.0, stdev=5.0)
    probs = [survival_prob(p, at_pick=k) for k in (10, 20, 30, 40)]
    assert probs == sorted(probs, reverse=True), "survival must be monotonic"
    assert probs[0] > 0.95
    assert probs[-1] < 0.05


def test_survival_at_adp_is_about_half():
    p = mk("a", "RB", 200.0, adp=20.0, stdev=5.0)
    assert survival_prob(p, at_pick=20) == pytest.approx(0.5, abs=0.01)


def test_survival_falls_back_to_curve_when_stdev_missing():
    p = Player("a", "A", "RB", "SF", proj_pts=200.0, adp=20.0, adp_stdev=None)
    assert 0.0 < survival_prob(p, at_pick=20) < 1.0


def test_vona_is_zero_when_an_equal_player_survives():
    """If someone just as good is certain to last, waiting costs nothing."""
    cand = mk("a", "RB", 200.0, adp=1.0, stdev=0.5)
    clone = mk("b", "RB", 200.0, adp=300.0, stdev=1.0)   # certain to survive
    assert vona([cand, clone], cand, at_pick=20) == pytest.approx(0.0, abs=0.5)


def test_vona_is_large_when_nobody_survives():
    cand = mk("a", "RB", 200.0, adp=1.0, stdev=0.5)
    other = mk("b", "RB", 100.0, adp=2.0, stdev=0.5)     # also certain to be gone
    assert vona([cand, other], cand, at_pick=50) > 190.0


def test_divergence_flags_projection_vs_market_gaps():
    # 'sleeper' is ranked 1st by projection but 3rd by ADP -> +2 divergence
    players = [
        mk("a", "RB", 300.0, adp=30.0),
        mk("b", "RB", 250.0, adp=10.0),
        mk("c", "RB", 200.0, adp=20.0),
    ]
    scores = {"a": 300.0, "b": 250.0, "c": 200.0}
    div = divergence(players, scores)
    assert div["a"] == 2, "projection rank 1, ADP rank 3"
    assert div["b"] == -1
    assert div["c"] == -1


def test_detect_run_counts_recent_positions():
    assert detect_run(["RB"] * 5 + ["WR"] * 3) == {"RB": 5, "WR": 3}
    assert detect_run(["QB"] + ["RB"] * 10, window=8)["RB"] == 8
    assert detect_run([]) == {}
