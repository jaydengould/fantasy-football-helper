"""Pure engine tests. Synthetic players only -- the engine is arithmetic and
does not care whether the numbers are real."""
import pytest

from ffhelper.data import ADP_UNKNOWN, Player
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
    """Found vacuous by mutation testing: with only two players and one gap the
    threshold is inf, so both land in tier 1 whether tiers are grouped by
    position or not -- the assertion held against a build that tiered the whole
    pool as one group.

    This pool discriminates. Per position the RB gaps are [50, 10] (pstdev 20,
    so only the 50 breaks) giving [1, 2, 2], and the WR gaps are [5, 5] (pstdev
    0, so both break) giving [1, 2, 3]. Pooled into one group the gaps become
    [50, 10, 140, 5, 5] with pstdev ~51.6, so only the 140 -- the artificial
    step between the two POSITIONS -- breaks, collapsing every RB into tier 1
    and every WR into tier 2.
    """
    rbs = [mk("rb1", "RB", 300.0), mk("rb2", "RB", 250.0), mk("rb3", "RB", 240.0)]
    wrs = [mk("wr1", "WR", 100.0), mk("wr2", "WR", 95.0), mk("wr3", "WR", 90.0)]
    players = [*rbs, *wrs]
    scores = {p.sleeper_id: p.proj_pts for p in players}

    tiers = assign_tiers(players, scores, sigma=1.0)

    assert [tiers[f"rb{i}"] for i in (1, 2, 3)] == [1, 2, 2]
    assert [tiers[f"wr{i}"] for i in (1, 2, 3)] == [1, 2, 3]
    assert tiers["wr1"] == 1, "each position starts its own tier 1"


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


def test_divergence_is_ranked_within_position_not_globally():
    """Task 13 defect. VBD is cross-position comparable only NEAR replacement.
    Deep in the pool it is not -- kickers cluster tightly around their baseline
    while skill players fall hundreds of points below theirs -- so a
    replacement-level kicker outranked a deep RB on a global VBD ranking while
    the market correctly ranked the RB higher, because you only ever need one
    kicker. The flag fired on 40% of top-20 rows led by five kickers.

    Here both kickers are ranked 1st and 2nd among kickers by BOTH projection
    and ADP, so their within-position divergence is exactly 0 -- the model and
    the market agree about them completely. Ten deep RBs are priced ahead of
    them but project below them, which is precisely the real situation.

    Against a global ranking each kicker scores +10 and this fails.
    """
    kickers = [mk("k1", "K", 5.0, adp=150.0), mk("k2", "K", 0.0, adp=160.0)]
    deep_rbs = [mk(f"rb{i}", "RB", -50.0 - i, adp=100.0 + i) for i in range(10)]
    players = [*kickers, *deep_rbs]
    scores = {p.sleeper_id: p.proj_pts for p in players}

    div = divergence(players, scores)

    assert div["k1"] == 0, "ranked 1st among kickers by both projection and ADP"
    assert div["k2"] == 0
    assert all(div[f"rb{i}"] == 0 for i in range(10)), "same order both ways"


def test_divergence_is_none_for_a_player_the_market_never_priced():
    """A third of the real pool (209 of 632) carries the ADP_UNKNOWN sentinel.
    They all tie at the sentinel, so under the old code they sorted to the
    bottom of the ADP ranking together and any of them with a decent projection
    manufactured a huge fake divergence -- Darren Waller at +399.

    `unpriced` here projects best in the pool but has no ADP. The old code
    ranked him 1st by projection and last by ADP and reported +3. He must
    report None instead: no opinion is not agreement, and it is not a +399
    bargain either.
    """
    players = [
        mk("a", "RB", 300.0, adp=30.0),
        mk("b", "RB", 250.0, adp=10.0),
        mk("c", "RB", 200.0, adp=20.0),
        mk("unpriced", "RB", 400.0, adp=ADP_UNKNOWN),
    ]
    scores = {"a": 300.0, "b": 250.0, "c": 200.0, "unpriced": 400.0}
    div = divergence(players, scores)

    assert div["unpriced"] is None
    # And his absence must not shift anyone else: the three rated players keep
    # exactly the ranks they had without him.
    assert (div["a"], div["b"], div["c"]) == (2, -1, -1)


def test_divergence_ranks_both_sides_over_the_same_rated_subset():
    """Ranking projections over ALL players while ranking ADP over only the
    rated ones would compare a rank out of N to a rank out of a smaller M, and
    bias every divergence positive. Adding unpriced players -- who project at
    the very top -- must not move a single rated player's number."""
    rated = [mk("a", "RB", 300.0, adp=30.0), mk("b", "RB", 250.0, adp=10.0),
             mk("c", "RB", 200.0, adp=20.0)]
    scores = {"a": 300.0, "b": 250.0, "c": 200.0}
    before = divergence(rated, scores)

    noise = [mk(f"n{i}", "RB", 500.0 + i, adp=ADP_UNKNOWN) for i in range(20)]
    scores.update({p.sleeper_id: p.proj_pts for p in noise})
    after = divergence([*rated, *noise], scores)

    assert {k: after[k] for k in ("a", "b", "c")} == before


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


from ffhelper.config import Tunables
from ffhelper.value import build_board, is_bench_only, is_redundant


def test_board_sorts_by_vona_and_fills_all_fields():
    """`board == sorted(board, key=lambda r: -r.vona)` is self-referential --
    it sorts the board by its own stored vona values, so it holds for ANY
    values including all zeros (e.g. under a `max(0, ...)` clamp). Assert the
    actual player-id ordering instead, independently derived below, so a
    clamp (or any other ordering bug) has something external to fail against.

    current_pick=1, my_slot=3, num_teams=12 -> at_pick =
    next_pick_number(1, 3, 12) == 3 (see test_snake_pick_sequence_for_slot_3_
    in_12_team). Computed directly via vona() (not re-derived by hand):
    vona(a) ~= 293.39, vona(b) ~= 283.39, vona(c) == 0.0 (c is the only WR
    and is certain to survive to pick 3, so waiting costs him nothing).
    Expected order by descending vona: a, b, c.
    """
    players = [
        mk("a", "RB", 300.0, adp=1.0, stdev=0.5),
        mk("b", "RB", 290.0, adp=2.0, stdev=0.5),
        mk("c", "WR", 280.0, adp=200.0, stdev=5.0),   # certain to survive
    ]
    board = build_board(
        available=players, my_roster=[], settings_slots=SLOTS, num_teams=12,
        current_pick=1, my_slot=3, tunables=Tunables(),
    )
    assert len(board) == 3
    assert [r.player.sleeper_id for r in board] == ["a", "b", "c"]
    assert board == sorted(board, key=lambda r: -r.vona)
    top = board[0]
    assert top.tier >= 1
    assert 0.0 <= top.survival <= 1.0
    assert isinstance(top.divergence, int)


def test_board_preserves_negative_vona():
    """Regression: build_board must let a genuinely negative VONA survive
    into the Row unchanged. Same setup as test_vona_negative_is_not_clamped_
    to_zero: `better` (150 pts, adp=200, near-certain to survive) dominates
    `cand` (100 pts, adp=45) at the next pick, so taking cand now is strictly
    worse than waiting -- VONA must be negative.

    current_pick=45, my_slot=None -> at_pick = current_pick + 1 = 46, the
    exact at_pick used by the unit test, so the expected value carries over
    unchanged: -50.0 (see test_vona_negative_is_not_clamped_to_zero for the
    full derivation).

    This test would FAIL under a `max(0, ...)` clamp wrapped around the VONA
    computation inside build_board: every row's vona would be flattened to
    0.0, so `row.vona < 0.0` would be False and
    `row.vona == pytest.approx(-50.0, abs=1.0)` would compare 0.0 to -50.0
    and fail. Nothing about this test depends on the board's own stored
    values (unlike the sortedness assertion above), so it has no vacuous
    pass mode.
    """
    cand = mk("cand", "WR", 100.0, adp=45.0, stdev=3.0)
    better = mk("better", "WR", 150.0, adp=200.0, stdev=20.0)  # certain to survive
    board = build_board(
        available=[cand, better], my_roster=[], settings_slots=SLOTS,
        num_teams=12, current_pick=45, my_slot=None, tunables=Tunables(),
    )
    row = next(r for r in board if r.player.sleeper_id == "cand")
    assert row.vona < 0.0
    assert row.vona == pytest.approx(-50.0, abs=1.0)


def test_board_without_draft_slot_still_builds():
    """draft_slot is often unknown pre-draft; the board must not fail."""
    players = [mk("a", "RB", 300.0), mk("b", "WR", 280.0)]
    board = build_board(players, [], SLOTS, 12, current_pick=5, my_slot=None,
                        tunables=Tunables())
    assert len(board) == 2


def test_compressed_vona_falls_back_to_value_instead_of_ranking_a_kicker_first():
    """Reproduces the opening-board defect found by running the real pool.

    When your next pick is a pick or two away -- pick 1, and both sides of every
    snake turn -- almost nobody gets taken in the gap, so VONA compresses toward
    0 for everyone and the board ends up ranking on floating-point dust. On the
    live 632-player pool this put four kickers in the top ten above Christian
    McCaffrey.

    Here `elite_rb` is behind `best_rb`, who is near-certain to survive, so his
    VONA is a large negative. `kicker` is only 2 points behind the one other
    kicker, so his VONA is about -2. Both say the same thing -- waiting is free
    -- but pre-fix the sort compared those magnitudes across positions and the
    kicker, worth 3 points over replacement, outranked an RB worth 190.
    """
    best_rb = mk("best_rb", "RB", 300.0, adp=200.0, stdev=20.0)   # certain to survive
    elite_rb = mk("elite_rb", "RB", 250.0, adp=200.0, stdev=20.0)
    repl_rb = mk("repl_rb", "RB", 60.0, adp=200.0, stdev=20.0)
    k1 = mk("k1", "K", 130.0, adp=200.0, stdev=20.0)
    kicker = mk("kicker", "K", 128.0, adp=200.0, stdev=20.0)

    board = build_board(
        # Kickers listed FIRST on purpose. Every VONA here floors to 0, so the
        # ordering rests entirely on the VBD tiebreak -- and with the kickers
        # already at the front of the list, a sort with no tiebreak would leave
        # them there on insertion order alone and pass this test vacuously.
        available=[k1, kicker, repl_rb, elite_rb, best_rb], my_roster=[],
        settings_slots=SLOTS, num_teams=12, current_pick=1, my_slot=2,
        tunables=Tunables(),
    )
    order = [r.player.sleeper_id for r in board]
    by_id = {r.player.sleeper_id: r for r in board}

    # Both are in the "waiting is free" regime -- the premise of the test.
    assert by_id["elite_rb"].vona < 0
    assert by_id["kicker"].vona < 0
    # ...and the kicker's negative VONA is the SMALLER one, which is exactly
    # why the pre-fix sort ranked him above the RB.
    assert by_id["kicker"].vona > by_id["elite_rb"].vona
    assert order.index("elite_rb") < order.index("kicker")
    # The stored VONA must stay negative -- only the sort key is floored.
    assert by_id["elite_rb"].vona == pytest.approx(-50.0, abs=1.0)


def test_lineup_value_never_starts_a_qb_or_kicker_in_a_flex_slot():
    """Found by mutation testing: deleting the `p.position in FLEX_ELIGIBLE`
    guard in `lineup_value`'s FLEX loop left the full suite green.

    Without it the FLEX slots take the highest-projection unused player of ANY
    position, so a second QB or a kicker starts at FLEX. That inflates
    `lineup_value`, which inflates `marginal_value`, which is the MARG column --
    and Phase 5's trade finder inherits the same function.

    Roster here has exactly one flex-worthy player left (rb2) and a high-scoring
    spare QB. SLOTS is QB1/RB2/WR2/TE1/FLEX2/K1/DEF1, so after the named slots
    fill, two FLEX slots are open and only rb2 may legally fill one.
    """
    roster = [
        mk("qb1", "QB", 400.0), mk("qb2", "QB", 390.0),      # qb2 is a bench QB
        mk("rb1", "RB", 200.0), mk("rb2", "RB", 190.0), mk("rb3", "RB", 180.0),
        mk("wr1", "WR", 150.0), mk("wr2", "WR", 140.0),
        mk("te1", "TE", 100.0), mk("k1", "K", 130.0), mk("d1", "DEF", 120.0),
    ]
    got = lineup_value(roster, SLOTS)
    # QB1 + RB1,RB2 + WR1,WR2 + TE1 + K + DEF + FLEX(rb3, wr-none left) ...
    # the only legal FLEX fills are rb3 (180) and then nothing else eligible.
    expected = 400 + 200 + 190 + 150 + 140 + 100 + 130 + 120 + 180
    assert got == pytest.approx(expected)
    # The bench QB (390) and nothing else may sneak into the second FLEX slot.
    assert got < expected + 390


def test_replacement_baseline_comes_from_the_full_pool_not_whats_left():
    """Task 13 defect. Replacement level is a property of the league -- what the
    last startable player at a position is worth -- not of whoever happens to
    remain. Computing it from `available` made the baseline collapse as the
    draft drained (QB 347.5 at pick 1 -> 165.9 by pick 164), which handed a
    backup quarterback a VBD of +149.0 against a true value of -32.5.

    Here the full pool has 20 RBs running 300 down to 110; only the top three
    are still available. Against the full pool the baseline is the 20th RB;
    against `available` it would be the 3rd, which is 170 points higher and
    would flatten every VBD on the board.
    """
    full = [mk(f"rb{i}", "RB", 300.0 - i * 10, adp=float(i + 1), stdev=5.0) for i in range(20)]
    available = full[:3]

    board = build_board(
        available=available, my_roster=[], settings_slots=SLOTS, num_teams=12,
        current_pick=40, my_slot=None, tunables=Tunables(), replacement_pool=full,
    )
    top = next(r for r in board if r.player.sleeper_id == "rb0")

    # RB replacement rank is 36 for this league; only 20 RBs exist, so the
    # baseline is the worst of them -- 110.0. 300 - 110 = 190.
    assert top.vbd == pytest.approx(190.0)
    # Against `available` alone the baseline would be rb2 (280), giving 20.0.
    assert top.vbd != pytest.approx(20.0)


def test_a_player_who_cannot_start_never_outranks_one_who_can():
    """Task 13 defect, and the reason that draft ended with three quarterbacks.

    VONA is position-relative and roster-BLIND: it stays large for a third QB
    you will never start. `filler` has the higher VONA but cannot crack the
    starting lineup (marginal 0); `starter` fills a genuinely empty slot. The
    board must lead with the one that helps.

    Against the ungated sort this fails: filler's larger VONA wins outright.
    """
    roster = [mk("have_wr1", "WR", 250.0), mk("have_wr2", "WR", 240.0),
              mk("have_rb1", "RB", 230.0), mk("have_rb2", "RB", 220.0),
              mk("have_flex1", "RB", 210.0), mk("have_flex2", "WR", 200.0),
              mk("have_te", "TE", 190.0), mk("have_k", "K", 100.0),
              mk("have_def", "DEF", 90.0)]
    # Every slot above is full EXCEPT QB.
    filler = mk("filler", "WR", 120.0, adp=50.0, stdev=2.0)      # cannot start
    starter = mk("starter", "QB", 300.0, adp=60.0, stdev=2.0)    # fills empty QB
    others = [mk(f"wr{i}", "WR", 119.0 - i, adp=200.0, stdev=20.0) for i in range(4)]
    qb2 = mk("qb2", "QB", 295.0, adp=200.0, stdev=20.0)

    board = build_board(
        available=[filler, starter, qb2, *others], my_roster=roster,
        settings_slots=SLOTS, num_teams=12, current_pick=55, my_slot=None,
        tunables=Tunables(),
    )
    by = {r.player.sleeper_id: r for r in board}
    assert by["filler"].marginal == pytest.approx(0.0)
    assert by["starter"].marginal > 0
    assert by["filler"].vona > by["starter"].vona, "premise: filler has the bigger raw VONA"
    order = [r.player.sleeper_id for r in board]
    assert order.index("starter") < order.index("filler")
    # The VONA column still reports true positional scarcity -- only the sort is gated.
    assert by["filler"].vona > 0


def test_a_second_kicker_ranks_last_once_you_already_have_one():
    """Task 13, bench mode. The roster-need gate alone is not enough: it ties a
    redundant kicker at 0 with everyone else, and then the VBD tiebreak floats
    him to the TOP, because by the late rounds every remaining RB/WR is below
    replacement while the best remaining kicker is still above it. That made a
    second kicker the top recommendation for the last four picks of the mock.

    Against the un-demoted sort the kicker leads and this fails.
    """
    roster = [mk("have_wr1", "WR", 250.0), mk("have_wr2", "WR", 240.0),
              mk("have_rb1", "RB", 230.0), mk("have_rb2", "RB", 220.0),
              mk("have_flex1", "RB", 210.0), mk("have_flex2", "WR", 200.0),
              mk("have_te", "TE", 190.0), mk("have_qb", "QB", 300.0),
              mk("have_k", "K", 100.0), mk("have_def", "DEF", 90.0)]
    spare_k = mk("spare_k", "K", 99.0, adp=200.0, stdev=20.0)
    spare_d = mk("spare_d", "DEF", 89.0, adp=200.0, stdev=20.0)
    scraps = [mk(f"rb{i}", "RB", 40.0 - i, adp=200.0, stdev=20.0) for i in range(3)]
    available = [spare_k, spare_d, *scraps]

    # The real late-round shape: nearly every kicker and defense is still
    # undrafted, so the best remaining one sits ABOVE league replacement, while
    # every remaining RB is far below it. That is what floats them to the top.
    full_pool = available + (
        [mk(f"k{i}", "K", 98.0 - i, adp=200.0, stdev=20.0) for i in range(14)]
        + [mk(f"d{i}", "DEF", 88.0 - i, adp=200.0, stdev=20.0) for i in range(14)]
        + [mk(f"stud{i}", "RB", 300.0 - i, adp=20.0, stdev=5.0) for i in range(40)]
    )

    board = build_board(available, roster, SLOTS, 12, 170, None, Tunables(),
                        replacement_pool=full_pool)
    order = [r.player.sleeper_id for r in board]
    by = {r.player.sleeper_id: r for r in board}

    assert by["spare_k"].vbd > by["rb0"].vbd, "premise: the spare K has the better VBD"
    assert set(order[-2:]) == {"spare_k", "spare_d"}
    assert order[0].startswith("rb"), "a real bench flyer should lead instead"


def test_a_first_kicker_is_not_demoted():
    """The rule is 'a SECOND kicker', not 'kickers'. With no K rostered, the
    kicker must rank normally -- otherwise you would never be told to draft one."""
    roster = [mk("have_qb", "QB", 300.0)]
    k = mk("k", "K", 140.0, adp=100.0, stdev=10.0)
    board = build_board([k], roster, SLOTS, 12, 90, None, Tunables())
    assert not is_redundant(k, roster, SLOTS)
    assert board[0].player.sleeper_id == "k"


def test_is_bench_only_detects_a_full_starting_lineup():
    """At pick 164 of the Task 13 mock, 0 of 469 available players improved the
    starting lineup, so any confident ordering was fabricated. The caller has to
    be able to detect that and say so."""
    roster = [mk("have_wr1", "WR", 250.0), mk("have_wr2", "WR", 240.0),
              mk("have_rb1", "RB", 230.0), mk("have_rb2", "RB", 220.0),
              mk("have_flex1", "RB", 210.0), mk("have_flex2", "WR", 200.0),
              mk("have_te", "TE", 190.0), mk("have_qb", "QB", 300.0),
              mk("have_k", "K", 100.0), mk("have_def", "DEF", 90.0)]
    scraps = [mk(f"x{i}", "WR", 50.0 - i, adp=200.0, stdev=20.0) for i in range(5)]

    full = build_board(scraps, roster, SLOTS, 12, 170, None, Tunables())
    assert is_bench_only(full) is True

    # One genuine upgrade is enough to make the board meaningful again.
    upgrade = mk("stud", "WR", 400.0, adp=200.0, stdev=20.0)
    assert is_bench_only(build_board([*scraps, upgrade], roster, SLOTS, 12, 170,
                                     None, Tunables())) is False


def test_board_of_empty_pool_is_empty():
    assert build_board([], [], SLOTS, 12, 1, 3, Tunables()) == []


def test_marginal_value_reflects_existing_roster():
    slots = {"RB": 1, "FLEX": 0}
    roster = [mk("have", "RB", 300.0)]
    players = [mk("new", "RB", 100.0, adp=50.0)]
    board = build_board(players, roster, slots, 12, 1, 3, Tunables())
    assert board[0].marginal == 0.0, "a worse RB behind a filled slot adds nothing"


from ffhelper.data import curve_stdev


def _clustered_points(n, start, intra_gap, inter_gap, cluster_sizes):
    """Points that fall into clusters (tiny intra-cluster gaps) separated by
    bigger jumps between clusters -- mirrors how real weekly rankings bunch
    players into tiers instead of spacing everyone evenly apart."""
    pts = []
    val = start
    idx_in_cluster = 0
    cluster_i = 0
    size = cluster_sizes[0]
    for _ in range(n):
        pts.append(round(val, 2))
        idx_in_cluster += 1
        if idx_in_cluster >= size:
            val -= inter_gap
            idx_in_cluster = 0
            cluster_i += 1
            size = cluster_sizes[cluster_i % len(cluster_sizes)]
        else:
            val -= intra_gap
    return pts


def _realistic_full_pool():
    """64 players (14 QB, 20 RB, 20 WR, 10 TE), ADPs overlapping across
    positions in a single band (10-100, ~7.5 rounds of a 12-team draft)
    instead of spanning the whole draft, non-round projections and ADPs,
    and clustered (not evenly-spaced) projections so assign_tiers produces
    genuine multi-player tiers rather than one tier per player."""
    players = []
    n_qb, n_rb, n_wr, n_te = 14, 20, 20, 10
    band_lo, band_hi = 10.0, 100.0

    qb_pts = _clustered_points(n_qb, 262.0, 0.6, 7.3, [2, 3])
    rb_pts = _clustered_points(n_rb, 271.0, 0.5, 6.1, [2, 3, 2])
    wr_pts = _clustered_points(n_wr, 256.0, 0.4, 5.7, [3, 2, 3])
    te_pts = _clustered_points(n_te, 191.0, 0.7, 8.4, [2, 2])

    for i in range(n_qb):
        adp = band_lo + i * (band_hi - band_lo) / (n_qb - 1) + 0.3
        players.append(mk(f"qb{i}", "QB", qb_pts[i], round(adp, 1), round(curve_stdev(adp), 2)))
    for i in range(n_rb):
        adp = band_lo + i * (band_hi - band_lo) / (n_rb - 1) + 0.6
        players.append(mk(f"rb{i}", "RB", rb_pts[i], round(adp, 1), round(curve_stdev(adp), 2)))
    for i in range(n_wr):
        adp = band_lo + i * (band_hi - band_lo) / (n_wr - 1) + 1.2
        players.append(mk(f"wr{i}", "WR", wr_pts[i], round(adp, 1), round(curve_stdev(adp), 2)))
    for i in range(n_te):
        adp = band_lo + i * (band_hi - band_lo) / (n_te - 1) + 2.1
        players.append(mk(f"te{i}", "TE", te_pts[i], round(adp, 1), round(curve_stdev(adp), 2)))
    return players


def test_board_at_realistic_scale_holds_up():
    """Every existing board test uses tiny, round, well-separated pools (adp
    1/2/200, 10-point gaps, stdev 0.5). Three real bugs in this project hid
    behind exactly that pattern. This test uses a 64-player pool spanning
    QB/RB/WR/TE with overlapping, non-round projections/ADPs and realistic
    survival probabilities, then asserts properties a broken implementation
    would violate.

    current_pick=50, my_slot=6, num_teams=12 -> at_pick =
    next_pick_number(50, 6, 12) == 54 (round 5 is odd, offset = slot = 6,
    pick = (5-1)*12 + 6 = 54; computed directly via next_pick_number, not
    re-derived by hand). curve_stdev(54) ~= 7.23 (computed directly via
    curve_stdev), and the pool's ADP band (10-100) puts most players within
    one or two such stdevs of at_pick=54 rather than six, so survival spans
    the genuine middle band instead of saturating at 0/1 for everyone --
    verified directly: of the 64 rows, 17 have survival strictly between
    0.05 and 0.95.
    """
    players = _realistic_full_pool()
    assert len(players) == 64
    board = build_board(
        available=players, my_roster=[], settings_slots=SLOTS, num_teams=12,
        current_pick=50, my_slot=6, tunables=Tunables(),
    )

    # Every available player appears exactly once: no drops, no duplicates.
    board_ids = [r.player.sleeper_id for r in board]
    assert len(board) == len(players)
    assert len(set(board_ids)) == len(board_ids), "no player appears more than once"
    assert set(board_ids) == {p.sleeper_id for p in players}, "no player was dropped"

    # Every field is populated and within its valid domain.
    for r in board:
        assert r.tier >= 1
        assert 0.0 <= r.survival <= 1.0
        assert isinstance(r.divergence, int)
        assert isinstance(r.vbd, float)
        assert isinstance(r.vona, float)
        assert isinstance(r.marginal, float)

    # The realistic pool exercises both sides of VONA, not one saturated
    # extreme -- and in particular is not silently clamped to all-zero/all-
    # non-negative.
    vonas = [r.vona for r in board]
    assert any(v > 0.0 for v in vonas)
    assert any(v < 0.0 for v in vonas)

    # At least one position genuinely clusters into multiple tiers.
    rb_tiers = {r.tier for r in board if r.player.position == "RB"}
    assert len(rb_tiers) >= 2
