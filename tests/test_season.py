"""ffhelper.season is PURE -- these tests never touch the network."""
import pytest
from dataclasses import dataclass

from ffhelper.data import Player
from ffhelper import season


@dataclass
class FakePick:
    """Duck-types feeds.Pick. season.py must not import feeds or gain any
    dependency on the feed layer's shape -- it is pure, tested with synthetic
    data, and stays that way regardless of what feeds.py happens to import.
    (`requests` is already present via data.py by the time season.py is
    imported, so the old "keeps requests out" reasoning was false -- the rule
    was right, the reason was not.) tests/test_board_agreement.py uses the
    same shape for the same reason."""
    draft_slot: int | None
    roster_id: int | None


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


def test_start_sit_unprojected_excluded_from_close_calls():
    """A player absent from projected_ids (e.g. on exempt list) lands in unprojected,
    is NOT offered as a close-call challenger to any filled slot."""
    roster_raw = [mk("w1", "WR", 14.0), mk("w2", "WR", 11.0),
                  mk("w3", "WR", 9.0), mk("stash", "WR", 15.0)]  # stash has high season score
    # Only w1, w2, w3 have projections this week; stash is unprojected
    weekly = {"w1": 14.0, "w2": 11.0, "w3": 9.0}  # stash absent
    roster = season.with_weekly_points(roster_raw, weekly)

    got = season.start_sit(roster, {"WR": 2}, close_call_points=3.0,
                           projected_ids=set(weekly))

    assert [p.sleeper_id for p in got.unprojected] == ["stash"]
    # stash is benched (0.0 proj_pts), so only w3 is on bench
    # w3 is the challenger (not offered from unprojected)
    assert [c.challenger.sleeper_id for c in got.close_calls] == ["w3"]
    assert got.close_calls[0].gap == pytest.approx(2.0)


def test_start_sit_projected_ids_none_is_backward_compatible():
    """`projected_ids=None` assumes everyone was projected, leaving unprojected
    empty and preserving all existing behaviour."""
    roster = [mk("q", "QB", 20.0),
              mk("w1", "WR", 14.0), mk("w2", "WR", 11.0), mk("w3", "WR", 10.5)]
    # With projected_ids=None, all players treated as projected
    got = season.start_sit(roster, {"QB": 1, "WR": 2}, close_call_points=3.0,
                           projected_ids=None)

    assert got.unprojected == []
    # Close call still reported
    assert len(got.close_calls) == 1
    assert got.close_calls[0].challenger.sleeper_id == "w3"


def test_start_sit_distinguishes_zero_projection_from_missing():
    """A player with a genuine 0.0 projection who IS in projected_ids is NOT
    reported as unprojected -- this is the critical distinction."""
    roster = [mk("q", "QB", 20.0), mk("w1", "WR", 3.0), mk("w2", "WR", 0.0),
              mk("stash", "RB", 1.0)]
    # w2 has a genuine 0.0 projection; stash is unprojected (on exempt list)
    got = season.start_sit(roster, {"QB": 1, "WR": 1}, close_call_points=3.0,
                           projected_ids={"q", "w1", "w2"})

    assert [p.sleeper_id for p in got.unprojected] == ["stash"]
    # w2 can still challenge (has a projection, even if zero); stash cannot
    assert len(got.close_calls) == 1
    assert got.close_calls[0].challenger.sleeper_id == "w2"
    assert got.close_calls[0].gap == pytest.approx(3.0)


def test_start_sit_same_bench_player_can_challenge_multiple_slots():
    """The same bench player can be offered as a challenger for different slots
    (a player positioned between two filled starters might challenge both). This
    behaviour is deliberately accepted and tested here."""
    roster = [mk("rb1", "RB", 12.0), mk("rb2", "RB", 11.0), mk("rb3", "RB", 9.0)]
    got = season.start_sit(roster, {"RB": 2}, close_call_points=3.0)

    # rb3 can challenge both rb1 (gap 3.0) and rb2 (gap 2.0) -- both within threshold
    challenger_ids = [c.challenger.sleeper_id for c in got.close_calls]
    assert challenger_ids.count("rb3") == 2


def test_weekly_points_omits_rows_with_only_descriptive_stats():
    """Real Sleeper rows for unprojected players carry descriptive fields like adp_dd_ppr
    but NO scoring keys. These must be omitted, not scored as 0.0."""
    rows = [
        {"player_id": "jacobs", "stats": {"adp_dd_ppr": 1000.0}},  # real shape
        {"player_id": "projected", "stats": {"rec": 5.0}},  # real projection
    ]
    scoring = {"rec": 1.0, "rec_yd": 0.1}
    
    result = season.weekly_points(rows, scoring)
    
    # jacobs absent (unprojected), projected included
    assert "jacobs" not in result
    assert result["projected"] == pytest.approx(5.0)


def test_weekly_points_includes_genuine_zero_projection():
    """A player with a real but zero stat line (e.g., 0 receptions) IS projected
    and scores 0.0 -- this is NOT unprojected."""
    rows = [
        {"player_id": "zero_proj", "stats": {"rec": 0.0, "rec_yd": 0.0}},
        {"player_id": "no_proj", "stats": {"adp_dd_ppr": 1000.0}},
    ]
    scoring = {"rec": 1.0, "rec_yd": 0.1}
    
    result = season.weekly_points(rows, scoring)
    
    # zero_proj IS included (genuine zero); no_proj is not
    assert result["zero_proj"] == pytest.approx(0.0)
    assert "no_proj" not in result


def test_start_sit_unprojected_from_descriptive_only_rows():
    """Players in rows with only descriptive stats land in unprojected and do not
    appear in close calls."""
    roster_raw = [mk("proj", "RB", 10.0), mk("jacobs", "RB", 15.0)]
    # Only "proj" has scoring keys; jacobs row is descriptive-only
    rows = [
        {"player_id": "proj", "stats": {"rec": 5.0}},
        {"player_id": "jacobs", "stats": {"adp_dd_ppr": 1000.0}},
    ]
    scoring = {"rec": 1.0}
    weekly = season.weekly_points(rows, scoring)
    roster = season.with_weekly_points(roster_raw, weekly)
    
    st = season.start_sit(roster, {"RB": 1}, close_call_points=3.0,
                          projected_ids=set(weekly))
    
    assert [p.sleeper_id for p in st.unprojected] == ["jacobs"]
    assert len(st.close_calls) == 0


def test_start_sit_no_close_call_when_starter_is_unprojected():
    """No close call is emitted when the starter is unprojected, even if a projected
    player on the bench could challenge it. There is no meaningful comparison when
    the incumbent has no number (fabricated 0.0)."""
    # Construct case: unprojected RB will be chosen as starter (higher proj_pts than zero_proj)
    # but is actually unprojected (no scoring keys), while zero_proj is genuine 0.0
    roster_raw = [mk("unprojected", "RB", 10.0), mk("zero_proj", "RB", 0.0)]
    rows = [
        {"player_id": "zero_proj", "stats": {"rec": 0.0}},
        {"player_id": "unprojected", "stats": {"adp_dd_ppr": 1000.0}},
    ]
    scoring = {"rec": 1.0}
    weekly = season.weekly_points(rows, scoring)  # unprojected absent from weekly
    roster = season.with_weekly_points(roster_raw, weekly)  # unprojected gets 0.0, zero_proj stays 0.0

    st = season.start_sit(roster, {"RB": 1}, close_call_points=3.0,
                          projected_ids=set(weekly))

    # unprojected is in the unprojected list (never projected)
    assert [p.sleeper_id for p in st.unprojected] == ["unprojected"]
    # No close call for the RB slot, even though unprojected was started and zero_proj is on bench
    # (the guard prevents close calls when starter is unprojected)
    assert len(st.close_calls) == 0


def test_roster_id_is_derived_from_the_draft_not_assumed_equal_to_the_slot():
    """MEASURED on the real 2026 league: draft_slot 5 is roster_id 3, and
    roster_id 5 belongs to another manager. Assuming slot == roster_id hands the
    user someone else's team and every downstream number is silently wrong."""
    picks = [FakePick(5, 3), FakePick(1, 10), FakePick(5, 3)]
    assert season.roster_id_for_slot(picks, 5) == 3


def test_roster_id_is_none_when_the_draft_cannot_answer():
    """Sleeper MOCK drafts set roster_id to None on every pick. Returning a
    number anyway -- or defaulting to the slot -- is the fabrication this whole
    function exists to prevent."""
    assert season.roster_id_for_slot([FakePick(5, None)], 5) is None
    assert season.roster_id_for_slot([FakePick(1, 9)], 5) is None
    assert season.roster_id_for_slot([], 5) is None


def test_roster_id_refuses_to_choose_when_the_draft_disagrees_with_itself():
    """One slot mapping to two roster ids means the feed is malformed. Picking
    the first is a coin flip on which team you manage."""
    picks = [FakePick(5, 3), FakePick(5, 7)]
    assert season.roster_id_for_slot(picks, 5) is None


def test_roster_player_ids_returns_the_named_roster_only():
    rosters = [{"roster_id": 3, "players": ["a", "b"]},
               {"roster_id": 5, "players": ["c"]}]
    assert season.roster_player_ids(rosters, 3) == ["a", "b"]
    assert season.roster_player_ids(rosters, 99) == []


# --- Phase 4b: the snapshot rows. Pure -- deciding WHAT a row says is logic and
# belongs here; `store.py` only knows how to write one. ---


def _slots():
    return {"QB": 1, "RB": 1, "FLEX": 1}


def test_snapshot_rows_marks_who_the_tool_advised_starting():
    """`started` is the advice itself -- without it the table records what was
    projected but not what was recommended, and scoring the ADVICE is the whole
    reason the table exists."""
    roster = [mk("qb", "QB", 22.0), mk("rb", "RB", 15.0), mk("wr", "WR", 11.0),
              mk("bench", "WR", 2.0)]
    state = season.start_sit(roster, _slots(), projected_ids={"qb", "rb", "wr", "bench"})

    rows = {r["player_id"]: r for r in
            season.snapshot_rows(state, projected_ids={"qb", "rb", "wr", "bench"},
                                 taken_at="2026-09-08T10:00:00")}

    assert rows["qb"]["started"] == 1
    assert rows["rb"]["started"] == 1
    assert rows["wr"]["started"] == 1        # FLEX
    assert rows["bench"]["started"] == 0


def test_snapshot_rows_records_an_unprojected_player_as_None_not_zero():
    """THE load-bearing assertion. `with_weekly_points` hands an unprojected
    player proj_pts=0.0 as a SORT value, and `projected_ids` exists solely to
    keep that separate from a real zero. If the sort value is written here,
    then in December an invented number is indistinguishable from a measured
    one, in the one table built to tell them apart."""
    roster = [mk("qb", "QB", 22.0), mk("stash", "RB", 0.0)]
    # `stash` is absent from projected_ids: no projection at all this week.
    state = season.start_sit(roster, _slots(), projected_ids={"qb"})

    rows = {r["player_id"]: r for r in
            season.snapshot_rows(state, projected_ids={"qb"}, taken_at="T")}

    assert rows["qb"]["proj_pts"] == pytest.approx(22.0)
    assert rows["stash"]["proj_pts"] is None
    # Not merely falsy -- 0.0 is falsy too, and that is the bug being excluded.
    assert rows["stash"]["proj_pts"] is not 0.0        # noqa: F632 - identity is the point


def test_snapshot_rows_covers_every_rostered_player_exactly_once():
    """An unprojected STARTER appears in both `lineup` and `unprojected` -- a
    known overlap from the 4a review. Emitting him twice would over-report the
    count and, with a primary key on the player, write one row while claiming
    two."""
    roster = [mk("qb", "QB", 0.0), mk("rb", "RB", 15.0), mk("bench", "WR", 1.0)]
    # The QB has no projection but is still the only QB, so he starts.
    state = season.start_sit(roster, _slots(), projected_ids={"rb", "bench"})
    assert any(p.sleeper_id == "qb" for _, p in state.lineup if p is not None)
    assert any(p.sleeper_id == "qb" for p in state.unprojected)

    rows = season.snapshot_rows(state, projected_ids={"rb", "bench"}, taken_at="T")

    ids = [r["player_id"] for r in rows]
    assert sorted(ids) == ["bench", "qb", "rb"]
    assert len(ids) == len(set(ids))


def test_snapshot_rows_carries_status_at_decision_time_and_None_when_absent():
    """Absent means absent, not healthy -- the same rule `_status_note` follows
    on screen. A blank string would later read as 'we checked and he was fine'."""
    hurt = Player("h", "H", "RB", "SEA", injury_status="Questionable",
                  practice_participation="DNP", proj_pts=9.0)
    fine = mk("f", "QB", 20.0)
    state = season.start_sit([hurt, fine], _slots(), projected_ids={"h", "f"})

    rows = {r["player_id"]: r for r in
            season.snapshot_rows(state, projected_ids={"h", "f"}, taken_at="T")}

    assert rows["h"]["status"] == "Questionable / DNP"
    assert rows["f"]["status"] is None


def test_snapshot_rows_leaves_matchup_None_because_no_adjustment_is_applied():
    """The column exists so an adjustment could be recorded WITH the decision it
    influenced. None is ever applied -- 4b measured the matchup adjustment on
    2024 and 2025 and it lost to unadjusted projections at every position and
    every shrinkage level (scripts/backtest_weekly.py) -- so this stays NULL.
    Never 0.0, which would read as 'the adjustment was computed and came to
    nothing' rather than 'none was made'."""
    state = season.start_sit([mk("qb", "QB", 20.0)], _slots(), projected_ids={"qb"})
    rows = season.snapshot_rows(state, projected_ids={"qb"}, taken_at="T")
    assert rows[0]["matchup"] is None


def test_snapshot_rows_stamps_every_row_with_the_same_taken_at():
    """One run is one observation. Rows drifting apart in time would make a
    week look like several separate looks when it was one."""
    roster = [mk("qb", "QB", 20.0), mk("rb", "RB", 10.0)]
    state = season.start_sit(roster, _slots(), projected_ids={"qb", "rb"})
    rows = season.snapshot_rows(state, projected_ids={"qb", "rb"}, taken_at="2026-09-08T10:00:00")
    assert {r["taken_at"] for r in rows} == {"2026-09-08T10:00:00"}


# --- matchup ---------------------------------------------------------------
#
# Fixtures use real team codes and stat lines that do not divide evenly, for
# the reason this project has traced seven defects to: a fixture built for
# arithmetic convenience stops resembling the data the code actually meets.

MATCHUP_SCORING = {"rec": 1.0, "rec_yd": 0.1, "rec_td": 6.0, "rush_yd": 0.1, "rush_td": 6.0}


def act(pid, week, team, opponent, **stats):
    """One weekly-actuals row, in Sleeper's shape."""
    return {"player_id": pid, "week": week, "team": team,
            "opponent": opponent, "stats": stats}


MATCHUP_POOL = {
    "4034": Player("4034", "Christian McCaffrey", "RB", "SF"),
    "6794": Player("6794", "Amon-Ra St. Brown", "WR", "DET"),
    "9221": Player("9221", "Jahmyr Gibbs", "RB", "DET"),
}


def test_points_allowed_credits_the_defense_faced_not_the_players_own_team():
    """`opponent` is the defense; `team` is the man scoring against it. Reading
    the wrong one inverts every matchup on the board -- the softest defense in
    the league would render as the hardest, and nothing on screen would say so."""
    rows = [act("4034", 1, "SF", "SEA", rush_yd=87.0, rec=4.0, rush_td=1.0)]
    rates = season.points_allowed(rows, MATCHUP_POOL, MATCHUP_SCORING)

    assert ("SEA", "RB") in rates.allowed
    assert ("SF", "RB") not in rates.allowed
    assert rates.allowed[("SEA", "RB")] == pytest.approx(8.7 + 4 + 6)


def test_points_allowed_divides_by_games_actually_faced_not_weeks_elapsed():
    """A defense on a bye, or a week whose rows never arrived, must not drag its
    per-game rate down. The divisor is the DISTINCT weeks the rows cover."""
    rows = [act("9221", 1, "DET", "GB", rush_yd=64.0, rec=3.0),
            act("9221", 4, "DET", "GB", rush_yd=112.0, rec=2.0, rush_td=1.0)]
    rates = season.points_allowed(rows, MATCHUP_POOL, MATCHUP_SCORING)

    assert rates.games[("GB", "RB")] == 2
    assert rates.allowed[("GB", "RB")] == pytest.approx(((6.4 + 3) + (11.2 + 2 + 6)) / 2)


def test_points_allowed_sums_every_player_at_a_position_into_one_game():
    """A defense faces a whole position group, not one man. Two RBs in the same
    game are one game's worth of RB points allowed, not two."""
    rows = [act("9221", 2, "DET", "CHI", rush_yd=71.0, rec=4.0),
            act("4034", 2, "SF", "CHI", rush_yd=53.0, rec=6.0)]
    rates = season.points_allowed(rows, MATCHUP_POOL, MATCHUP_SCORING)

    assert rates.games[("CHI", "RB")] == 1
    assert rates.allowed[("CHI", "RB")] == pytest.approx(7.1 + 4 + 5.3 + 6)


def test_points_allowed_skips_a_player_the_pool_does_not_know():
    """Position is the grouping key and it comes from the player pool. A row for
    somebody not in it cannot be grouped, and guessing a position would file
    points against the wrong matchup."""
    rows = [act("999999", 1, "SF", "SEA", rush_yd=40.0),
            act("4034", 1, "SF", "SEA", rush_yd=87.0)]
    rates = season.points_allowed(rows, MATCHUP_POOL, MATCHUP_SCORING)

    assert rates.allowed[("SEA", "RB")] == pytest.approx(8.7)


def test_matchup_factor_is_exactly_neutral_in_week_one():
    """Week 1 has no completed games, so there is no matchup to know. The honest
    adjustment is none -- and it must be EXACTLY 1.0, because anything else is a
    number invented out of an empty sample."""
    empty = season.points_allowed([], MATCHUP_POOL, MATCHUP_SCORING)

    assert season.matchup_factor(empty, "SEA", "RB", shrink_k=4.0) == 1.0


def test_matchup_factor_shrinks_toward_neutral_as_the_sample_stays_small():
    """Two games against a generous defense is mostly noise. `shrink_k` is what
    stops the tool automating the commonest fantasy error there is, so a small
    sample must move the factor LESS than the raw ratio does."""
    rows = [act("9221", w, "DET", "GB", rush_yd=150.0, rec=5.0) for w in (1, 2)]
    rows += [act("4034", w, "SF", "SEA", rush_yd=30.0, rec=1.0) for w in (1, 2)]
    rates = season.points_allowed(rows, MATCHUP_POOL, MATCHUP_SCORING)

    raw = season.matchup_factor(rates, "GB", "RB", shrink_k=0.0)
    shrunk = season.matchup_factor(rates, "GB", "RB", shrink_k=4.0)
    heavy = season.matchup_factor(rates, "GB", "RB", shrink_k=16.0)

    assert raw > shrunk > heavy > 1.0
    assert shrunk == pytest.approx(1.0 + (2 / 6) * (raw - 1.0))


def test_matchup_factor_is_neutral_for_a_defense_it_has_never_seen():
    """Degrade, never fabricate: an unknown opponent removes the adjustment
    rather than producing one from the league mean alone."""
    rows = [act("9221", 1, "DET", "GB", rush_yd=64.0)]
    rates = season.points_allowed(rows, MATCHUP_POOL, MATCHUP_SCORING)

    assert season.matchup_factor(rates, "KC", "RB", shrink_k=4.0) == 1.0
    assert season.matchup_factor(rates, "GB", "QB", shrink_k=4.0) == 1.0


def test_matchup_deltas_leave_an_unprojected_player_out_entirely():
    """His proj_pts is the 0.0 SORT value `with_weekly_points` invented. Scaling
    it produces a 0.0 delta, which in the snapshot table reads as 'computed, and
    it came to nothing' -- indistinguishable months later from a real zero."""
    rows = [act("9221", w, "DET", "GB", rush_yd=150.0, rec=5.0) for w in (1, 2)]
    rows += [act("4034", w, "SF", "SEA", rush_yd=30.0, rec=1.0) for w in (1, 2)]
    rates = season.points_allowed(rows, MATCHUP_POOL, MATCHUP_SCORING)
    roster = [mk("9221", "RB", 14.2), mk("4034", "RB", 0.0)]

    deltas = season.matchup_deltas(roster, {"9221": "GB", "4034": "GB"}, rates,
                                   projected_ids={"9221"}, shrink_k=4.0)

    assert set(deltas) == {"9221"}
    assert deltas["9221"] == pytest.approx(
        14.2 * (season.matchup_factor(rates, "GB", "RB", 4.0) - 1.0))


def test_matchup_deltas_skip_a_player_with_no_opponent():
    """A bye week has no opponent in the projection rows, so there is no matchup
    to show. Absent, not zero -- the same rule the projection column follows."""
    rows = [act("9221", 1, "DET", "GB", rush_yd=64.0)]
    rates = season.points_allowed(rows, MATCHUP_POOL, MATCHUP_SCORING)

    deltas = season.matchup_deltas([mk("9221", "RB", 11.9)], {}, rates,
                                   projected_ids={"9221"}, shrink_k=4.0)

    assert deltas == {}


def test_opponents_reads_the_projection_rows_already_fetched():
    """No schedule endpoint: the weekly projection row carries `opponent`, and a
    row without one (a bye) must be absent rather than mapped to something."""
    rows = [{"player_id": "9221", "opponent": "GB", "stats": {"rush_yd": 60.0}},
            {"player_id": "4034", "stats": {"rush_yd": 40.0}},
            {"opponent": "SEA"}]

    assert season.opponents(rows) == {"9221": "GB"}


def test_with_practice_status_fills_the_field_sleeper_leaves_empty():
    """Sleeper carries `practice_participation` for ZERO of 3231 players --
    measured, after the spec claimed otherwise off one populated row. nflverse
    fills that existing field, which is what lets the status note and the
    snapshot pick it up with no change to either."""
    roster = [Player("9221", "Jahmyr Gibbs", "RB", "DET", gsis_id="00-0038543"),
              Player("4034", "Christian McCaffrey", "RB", "SF", gsis_id="00-0033280")]

    out = season.with_practice_status(roster, {"00-0038543": "Limited"})

    assert out[0].practice_participation == "Limited"
    assert out[1].practice_participation is None      # absent, never "Full"
    assert roster[0].practice_participation is None   # copies, never mutation


def test_with_practice_status_keeps_sleepers_own_value_if_it_ever_arrives():
    """Sleeper's field is updated continuously; the nflverse file is the
    Wednesday-to-Friday report. Fresher wins for a Sunday morning lineup."""
    roster = [Player("1", "P", "WR", "SEA", gsis_id="00-0000001",
                     practice_participation="Full")]

    assert season.with_practice_status(roster, {})[0].practice_participation == "Full"


def test_with_practice_status_leaves_a_player_with_no_gsis_id_alone():
    """A team defense has no gsis_id and no injury report at all. Joining on a
    None key would file somebody else's practice status against it."""
    roster = [Player("SEA", "Seahawks", "DEF", "SEA")]

    assert season.with_practice_status(roster, {None: "DNP"})[0].practice_participation is None
