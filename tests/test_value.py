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
    """Pin the actual value implied by curve_stdev, not just 0 < x < 1 (which
    passes for nearly any formula). at_pick=20 == adp=20 would give 0.5
    regardless of which stdev is used, so evaluate off-center (at_pick=25)
    where the curve's stdev actually drives the number.

    curve_stdev(20) = 0.287 * 20**0.809 = 3.239031... (see ffhelper/data.py).
    survival = 1 - NormalDist(20, 3.239031).cdf(25) = 0.061334 (computed via
    statistics.NormalDist directly, not re-derived from the implementation).
    """
    p = Player("a", "A", "RB", "SF", proj_pts=200.0, adp=20.0, adp_stdev=None)
    assert survival_prob(p, at_pick=25) == pytest.approx(0.061334, abs=1e-4)


def test_survival_uses_real_zero_stdev_not_curve_fallback():
    """Regression guard for the truthiness bug: adp_stdev=0.0 is a real,
    present value (certain to go at exactly his ADP) and must NOT trigger the
    curve_stdev fallback, which only fires when the value is absent (None).

    With the true stdev clamped to the 0.1 floor (0.0 itself would make
    NormalDist degenerate), survival is a near step function around adp=50:
    at pick 49 (before ADP) survival ~1.0; at pick 51 (after) survival ~0.0;
    at pick 50 (exactly at ADP) survival is exactly 0.5 by symmetry.

    If the old `or` fallback fired instead, adp_stdev=0.0 would route to
    curve_stdev(50)=6.797, giving survival(at_pick=49) ~0.558 -- nowhere near
    the ~1.0 this test requires. That's the discriminating case.
    """
    p = Player("a", "A", "RB", "SF", proj_pts=200.0, adp=50.0, adp_stdev=0.0)
    assert survival_prob(p, at_pick=49) > 0.999999
    assert survival_prob(p, at_pick=51) < 0.000001
    assert survival_prob(p, at_pick=50) == pytest.approx(0.5, abs=1e-9)


def test_vona_is_zero_when_an_equal_player_survives():
    """If someone just as good is certain to last, waiting costs nothing."""
    cand = mk("a", "RB", 200.0, adp=1.0, stdev=0.5)
    clone = mk("b", "RB", 200.0, adp=300.0, stdev=1.0)   # certain to survive
    assert vona([cand, clone], cand, at_pick=20) == pytest.approx(0.0, abs=0.5)


def test_vona_is_large_when_nobody_survives():
    cand = mk("a", "RB", 200.0, adp=1.0, stdev=0.5)
    other = mk("b", "RB", 100.0, adp=2.0, stdev=0.5)     # also certain to be gone
    assert vona([cand, other], cand, at_pick=50) > 190.0


def test_vona_near_zero_when_candidate_himself_likely_survives():
    """Regression guard for the exclusion bug: if the candidate is both the
    best point-scorer at his position AND overwhelmingly likely to still be
    there at the next pick, waiting costs ~nothing -- the "next available"
    player at that future pick is very likely him.

    A better player (other, 150 pts) is drafted early and certainly gone
    (adp=5, survival~0 at pick 46); the candidate (100 pts) has adp=150 so
    he survives to pick 46 with probability ~1.

    Discriminates: the old `p is not candidate` filter drops the candidate
    from the walk entirely, leaving only `other` whose survival is ~0, so
    expected~0 and vona = 100 - 0 = 100.0 (verified directly against the
    pre-fix code). Under the fix the candidate re-enters the walk as the
    dominant surviving player, expected~100, and vona collapses to ~0. This
    test fails under the reverted exclusion logic (100.0 is not < 5.0).
    """
    cand = mk("cand", "TE", 100.0, adp=150.0, stdev=15.0)   # near-certain to survive
    other = mk("other", "TE", 150.0, adp=5.0, stdev=2.0)    # near-certain to be gone
    result = vona([cand, other], cand, at_pick=46)
    assert result < 5.0
    assert result == pytest.approx(0.0, abs=1.0)


def test_vona_large_positive_with_steep_drop_behind_low_survival_candidate():
    """Main-case check: candidate and the next-best player are both almost
    certainly gone by the next pick; only a much weaker player (50 pts, deep
    drop) is likely to survive. Waiting should cost close to the full gap
    between the candidate and that survivor -- large and positive, and this
    number is unaffected by the fix since the candidate's own survival is
    ~0 either way (his inclusion/exclusion barely changes the sum)."""
    cand = mk("cand", "RB", 200.0, adp=1.0, stdev=0.5)     # certain to be gone
    rival = mk("rival", "RB", 190.0, adp=2.0, stdev=0.5)   # also certain to be gone
    survivor = mk("survivor", "RB", 50.0, adp=100.0, stdev=10.0)  # steep drop, survives
    result = vona([cand, rival, survivor], cand, at_pick=46)
    assert result == pytest.approx(150.0, abs=1.0)


def test_vona_negative_is_not_clamped_to_zero():
    """If a much better player at the position is almost certain to survive
    to the next pick, taking the (weaker) candidate now is strictly worse
    than waiting -- VONA must be negative, not floored at 0. A clamp would
    turn this -50 into 0.0 and this assertion would fail."""
    cand = mk("cand", "WR", 100.0, adp=45.0, stdev=3.0)
    better = mk("better", "WR", 150.0, adp=200.0, stdev=20.0)  # certain to survive
    result = vona([cand, better], cand, at_pick=46)
    assert result < 0.0
    assert result == pytest.approx(-50.0, abs=1.0)


def test_vona_mid_band_positive_but_less_than_full_points():
    """Realistic middle-of-the-range case (the Colston Loveland-shaped bug):
    candidate's own survival ~50%, with a meaningful drop to the next player
    behind him. VONA must be materially positive (waiting is a real risk) but
    strictly less than his own proj_pts (half the time he's still there).

    Derivation (via statistics.NormalDist directly):
    cand: proj_pts=200, adp=46, stdev=10. at_pick=46 == adp, so by symmetry
    survival_prob(cand, 46) = 1 - cdf(46) = exactly 0.5, no computation needed.
    backup: proj_pts=70, adp=120, stdev=15. z = (46-120)/15 = -4.93, survival
    = 1 - NormalDist(120,15).cdf(46) = 0.9999995958 (computed directly),
    indistinguishable from 1.0 at the precision used below.

    expected = 0.5*200 + (1-0.5)*0.9999995958*70 = 100 + 34.99998... = 134.99999
    vona = 200 - 134.99999 = 65.00001
    """
    cand = mk("cand", "RB", 200.0, adp=46.0, stdev=10.0)
    backup = mk("backup", "RB", 70.0, adp=120.0, stdev=15.0)
    result = vona([cand, backup], cand, at_pick=46)
    assert result == pytest.approx(65.0, abs=0.01)
    assert 0.0 < result < 200.0


def test_vona_urgency_tracks_scarcity_not_just_value():
    """Two candidates with nearly identical proj_pts (150 vs 150) but very
    different survival (~29% vs ~90%) must produce strictly different VONA,
    with the lower-survival player's being higher. Each is evaluated against
    its own pool (itself plus a common, near-certain-to-survive filler at
    70pts) so the comparison isolates survival as the driver, not points --
    a shared pool would make the VONA delta collapse to just the ~0-point
    proj_pts gap between the two candidates, which would not test this at all.

    Derivation (via statistics.NormalDist directly):
    low: adp=40, stdev=11 -> survival(at_pick=46) = 0.292720...
    high: adp=60, stdev=11 -> survival(at_pick=46) = 0.898443...
    filler: proj_pts=60, adp=140, stdev=15 -> survival(46) = 0.99999999982,
      i.e. ~1.0 (essentially certain to still be on the board).

    expected_low  = 0.292720*150 + (1-0.292720)*1.0*60 = 43.908 + 42.437 = 86.345
    vona_low      = 150 - 86.345 = 63.655

    expected_high = 0.898443*150 + (1-0.898443)*1.0*60 = 134.766 + 6.094 = 140.860
    vona_high     = 150 - 140.860 = 9.140
    """
    low_surv = mk("low", "RB", 150.0, adp=40.0, stdev=11.0)
    high_surv = mk("high", "RB", 150.0, adp=60.0, stdev=11.0)
    filler = mk("filler", "RB", 60.0, adp=140.0, stdev=15.0)

    vona_low = vona([low_surv, filler], low_surv, at_pick=46)
    vona_high = vona([high_surv, filler], high_surv, at_pick=46)

    assert vona_low == pytest.approx(63.655, abs=0.05)
    assert vona_high == pytest.approx(9.140, abs=0.05)
    assert vona_low > vona_high, "lower survival must mean strictly higher VONA"


def test_vona_accumulates_across_multiple_mid_band_survivors():
    """When several comparable players at the position ALL sit in the
    realistic mid-band (survival roughly 40-70%), the survival-weighted walk
    must genuinely accumulate contributions from more than just the first
    term -- a suite that only ever puts one player in the mid-band can't see
    a bug where the walk stops early or ignores later terms.

    Four RBs, all with survival in [0.42, 0.66] at pick 46 (adp=44,46,48,50,
    stdev=10 each): cand(140), p2(135), p3(130), p4(125).
    survival(cand)=0.420740 (adp=44, off-center, needs NormalDist)
    survival(p2)=0.5 exactly (adp=46 == at_pick, symmetric, no computation)
    survival(p3)=0.579260, survival(p4)=0.655422 (both computed directly).

    Bounds, derived from the walk arithmetic without needing p3/p4's exact
    values:
    - Upper bound on VONA: use only the first two terms (cand, p2) and drop
      p3/p4, whose contributions can only ever be >= 0 and so can only push
      expected up / VONA down. expected_2term = 0.420740*140 +
      (1-0.420740)*0.5*135 = 58.904 + 39.100 = 98.004 -> VONA <= 140-98.004
      = 41.996.
    - Lower bound on VONA: cap the entire remaining (1-survival(cand)) mass
      at the highest-value remaining player's points (p2=135) as if it were
      certain to be there (survival=1), which over-estimates expected and so
      under-estimates VONA: expected_cap = 0.420740*140 +
      (1-0.420740)*135 = 58.904 + 78.200 = 137.104 -> VONA >= 140-137.104
      = 2.896.

    The true 4-term result (10.20, computed directly via NormalDist) falls
    well inside (2.896, 41.996) -- and well below the single-term-only
    estimate of 140*(1-0.420740)=81.10 that a walk which ignored the other
    three players entirely would produce, showing the extra terms are doing
    real work.
    """
    cand = mk("cand", "RB", 140.0, adp=44.0, stdev=10.0)
    p2 = mk("p2", "RB", 135.0, adp=46.0, stdev=10.0)
    p3 = mk("p3", "RB", 130.0, adp=48.0, stdev=10.0)
    p4 = mk("p4", "RB", 125.0, adp=50.0, stdev=10.0)

    result = vona([cand, p2, p3, p4], cand, at_pick=46)
    assert 2.896 < result < 41.996
    assert result == pytest.approx(10.20, abs=0.05)


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


def test_detect_run_window_zero_or_negative_is_empty_not_everything():
    """`recent_positions[-0:]` is `[0:]` -- the WHOLE list, not an empty
    slice. window=0 must mean "count nothing", not "count everything"."""
    positions = ["RB"] * 5 + ["WR"] * 3
    assert detect_run(positions, window=0) == {}
    assert detect_run(positions, window=-1) == {}
