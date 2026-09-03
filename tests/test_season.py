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


def _allowed(pairs, position="RB", games=4):
    """MatchupRates with a chosen points-allowed rate per defense."""
    return season.MatchupRates(
        allowed={(d, position): v for d, v in pairs},
        games={(d, position): games for d, _ in pairs},
        league_mean={position: sum(v for _, v in pairs) / len(pairs)})


def test_matchup_notes_rank_one_is_the_stingiest_defense():
    """The direction has to be fixed and stated, because a rank read the wrong
    way round recommends the exact opposite of what the data says. 1 allows the
    FEWEST points, so a high rank is the soft matchup, and the label carries the
    direction so it never has to be remembered."""
    rates = _allowed([("SF", 11.4), ("GB", 17.9), ("CAR", 24.6)])
    roster = [mk("a", "RB", 12.0), mk("b", "RB", 9.5)]

    notes = season.matchup_notes(roster, {"a": "SF", "b": "CAR"}, rates)

    assert (notes["a"].rank, notes["a"].label) == (1, "tough")
    assert (notes["b"].rank, notes["b"].label) == (3, "soft")
    assert notes["a"].of == 3


def test_matchup_notes_stay_silent_on_a_sample_too_small_to_rank():
    """A rank off one or two games is noise, and the early season is exactly when
    people over-react to it. Week 1 has no completed games at all, so nothing is
    printed rather than a rank built on nothing."""
    rates = _allowed([("SF", 11.4), ("GB", 17.9), ("CAR", 24.6)], games=2)

    assert season.matchup_notes([mk("a", "RB", 12.0)], {"a": "SF"}, rates) == {}


def test_matchup_notes_rank_only_against_defenses_with_a_real_sample():
    """A defense with two games must not sit in the ranking and shift everyone
    else's position -- it is excluded, and `of` says how many were ranked."""
    rates = season.MatchupRates(
        allowed={("SF", "RB"): 11.4, ("GB", "RB"): 17.9, ("CAR", "RB"): 24.6},
        games={("SF", "RB"): 4, ("GB", "RB"): 4, ("CAR", "RB"): 1},
        league_mean={"RB": 17.9})

    notes = season.matchup_notes([mk("a", "RB", 12.0), mk("b", "RB", 8.0)],
                                 {"a": "GB", "b": "CAR"}, rates)

    assert notes["a"].of == 2
    assert "b" not in notes


def test_matchup_notes_are_per_position_never_pooled():
    """A defense that is generous to tight ends may be the stingiest in the
    league against running backs. Ranking the two together is the same defect as
    tiering across positions."""
    rates = season.MatchupRates(
        allowed={("GB", "RB"): 24.6, ("SF", "RB"): 11.4,
                 ("GB", "TE"): 4.1, ("SF", "TE"): 9.8},
        games={k: 4 for k in (("GB", "RB"), ("SF", "RB"), ("GB", "TE"), ("SF", "TE"))},
        league_mean={"RB": 18.0, "TE": 6.9})
    roster = [mk("rb", "RB", 12.0), mk("te", "TE", 7.0)]

    notes = season.matchup_notes(roster, {"rb": "GB", "te": "GB"}, rates)

    assert notes["rb"].rank == 2 and notes["rb"].of == 2      # softest to RBs
    assert notes["te"].rank == 1                              # stingiest to TEs


def test_matchup_notes_skip_a_player_on_a_bye():
    """No opponent, no matchup. Absent rather than a neutral-looking rank."""
    rates = _allowed([("SF", 11.4), ("GB", 17.9), ("CAR", 24.6)])

    assert season.matchup_notes([mk("a", "RB", 12.0)], {}, rates) == {}


# --- Phase 4c: the free-agent pool and what a claim costs --------------------


def _pool():
    return {
        "4034": Player(sleeper_id="4034", name="Josh Allen", position="QB", team="BUF"),
        "8151": Player(sleeper_id="8151", name="Jahmyr Gibbs", position="RB", team="DET"),
        "6790": Player(sleeper_id="6790", name="Dalton Schultz", position="TE", team="HOU"),
        "1234": Player(sleeper_id="1234", name="Marcedes Lewis", position="TE", team=None),
    }


def test_free_agent_pool_removes_every_rostered_player_not_just_mine():
    rosters = [{"roster_id": 3, "players": ["4034"]}, {"roster_id": 5, "players": ["8151"]}]
    got = season.free_agent_pool(_pool(), rosters, {"4034", "8151", "6790", "1234"})
    assert [p.sleeper_id for p in got] == ["6790", "1234"]


def test_free_agent_pool_keeps_only_players_with_a_projection():
    # 3051 of the 3231-player pool are unrostered, and most are retired or on a
    # practice squad. Without this filter the board is a list of retirees.
    rosters = [{"roster_id": 3, "players": ["4034"]}]
    got = season.free_agent_pool(_pool(), rosters, {"8151", "6790"})
    assert [p.sleeper_id for p in got] == ["8151", "6790"]


def test_free_agent_pool_survives_a_roster_with_players_none():
    # Sleeper serves "players": null for an empty roster; `or []` is required.
    rosters = [{"roster_id": 3, "players": None}, {"roster_id": 5, "players": ["4034"]}]
    got = season.free_agent_pool(_pool(), rosters, {"4034", "8151"})
    assert [p.sleeper_id for p in got] == ["8151"]


def test_waiver_position_reads_my_row_and_counts_the_league():
    rosters = [
        {"roster_id": 3, "settings": {"waiver_position": 8}},
        {"roster_id": 5, "settings": {"waiver_position": 1}},
    ]
    assert season.waiver_position(rosters, 3) == (8, 2)


def test_waiver_position_is_none_when_the_payload_carries_none():
    # Degrade, never fabricate: a missing position must not become 1.
    rosters = [{"roster_id": 3, "settings": {}}]
    assert season.waiver_position(rosters, 3) == (None, 1)


# --- Phase 4c: the add-and-drop primitive -----------------------------------


def _waiver_slots():
    return {"QB": 1, "RB": 2, "WR": 2, "TE": 1, "FLEX": 1, "K": 1, "DEF": 1}


def _roster_for_upgrade():
    # Shaped like the real sleeper-main roster: one TE, a backup QB, RB depth.
    return [
        Player(sleeper_id="4034", name="Josh Allen", position="QB", team="BUF"),
        Player(sleeper_id="4892", name="Kyler Murray", position="QB", team="ARI"),
        Player(sleeper_id="4988", name="D'Andre Swift", position="RB", team="CHI"),
        Player(sleeper_id="9509", name="TreVeyon Henderson", position="RB", team="NE"),
        Player(sleeper_id="7591", name="Kenny Gainwell", position="RB", team="PIT"),
        Player(sleeper_id="9226", name="Jaxon Smith-Njigba", position="WR", team="SEA"),
        Player(sleeper_id="6794", name="Chris Olave", position="WR", team="NO"),
        Player(sleeper_id="8130", name="Christian Watson", position="WR", team="GB"),
        Player(sleeper_id="8144", name="Jake Ferguson", position="TE", team="DAL"),
        Player(sleeper_id="7839", name="Jason Myers", position="K", team="SEA"),
        Player(sleeper_id="DEN", name="Denver Broncos", position="DEF", team="DEN"),
    ]


_WK = {
    "4034": 24.4, "4892": 20.1, "4988": 13.5, "9509": 10.0, "7591": 9.5,
    "9226": 19.7, "6794": 16.2, "8130": 13.7, "8144": 9.7, "7839": 7.8, "DEN": 7.4,
}


# --- Phase 5: week_weights reaches horizon_total and the waiver floor --------


def test_horizon_total_scales_each_week_by_its_weight():
    """A half-weighted week contributes half its lineup value. Without this the
    weight vector is inert and every downstream number ignores the calendar."""
    roster = [mk("a", "QB", 0.0)]
    slots = {"QB": 1}
    wbw = {1: {"a": 10.0}, 2: {"a": 10.0}}
    assert season.horizon_total(roster, slots, wbw) == pytest.approx(20.0)
    assert season.horizon_total(roster, slots, wbw, {1: 1.0, 2: 0.5}) == pytest.approx(15.0)


def test_horizon_total_treats_a_week_missing_from_the_weights_as_full():
    """A weight vector built for a different horizon must not silently zero a
    week -- absent means 'not specified', which is 1.0, never 0.0."""
    roster = [mk("a", "QB", 0.0)]
    wbw = {1: {"a": 10.0}, 2: {"a": 10.0}}
    assert season.horizon_total(roster, {"QB": 1}, wbw, {1: 1.0}) == pytest.approx(20.0)


def test_effective_weeks_is_the_sum_of_the_weights():
    """The floor grows as sqrt(n) because independent weekly errors partially
    cancel. A week counted at 0.33 contributes a third of a week's worth of
    error, so the effective sample size is the SUM of the weights, not the
    count. With flat weights this reduces to 4c's rule exactly."""
    wbw = {1: {}, 2: {}, 3: {}}
    assert season.effective_weeks(wbw) == pytest.approx(3.0)
    assert season.effective_weeks(wbw, {1: 1.0, 2: 1.0, 3: 0.5}) == pytest.approx(2.5)


def test_the_waiver_floor_scales_with_the_weights_not_the_week_count():
    """A down-weighted horizon is a smaller sample, so the bar must fall with
    it. Using the raw count keeps a season-length bar over a horizon that is
    effectively one week long, which silences real upgrades.

    Arithmetic, worked before implementing:
      base   = 4 weeks x 0.25 x 10.0 (qb_good starts) = 10.0
      after  = 4 weeks x 0.25 x 14.0 (qb_better starts, qb_bad cut) = 14.0
      gain   = 4.0
      effective weeks = 4 x 0.25 = 1.0 -> floor 3.0 * sqrt(1.0) = 3.0 -> PRINTS
      raw week count  = 4          -> floor 3.0 * sqrt(4.0) = 6.0 -> would NOT
    """
    roster = [mk("qb_good", "QB"), mk("qb_bad", "QB")]
    pool = [mk("qb_better", "QB")]
    slots = {"QB": 1}
    wbw = {w: {"qb_good": 10.0, "qb_bad": 0.0, "qb_better": 14.0}
           for w in range(1, 5)}
    weights = {w: 0.25 for w in range(1, 5)}

    out = season.waiver_targets(roster, pool, slots, wbw, 3.0, weights=weights)
    assert [t.player.sleeper_id for t in out] == ["qb_better"]
    assert out[0].gain == pytest.approx(4.0)
    assert out[0].drop.sleeper_id == "qb_bad"


def test_roster_upgrade_pays_for_the_add_with_a_drop():
    roster = _roster_for_upgrade()
    cand = Player(sleeper_id="6790", name="Dalton Schultz", position="TE", team="HOU")
    weekly = {1: {**_WK, "6790": 12.0}}
    gain, drop, weeks_started = season.roster_upgrade(roster, cand, _waiver_slots(), weekly)
    # Schultz (12.0) starts at TE over Ferguson (9.7): +2.3. The drop must be a
    # player who was not starting, or the gain would be smaller.
    assert gain == pytest.approx(2.3)
    assert drop.sleeper_id == "7591"          # Gainwell: RB3, lowest own points
    assert weeks_started == 1


def test_roster_upgrade_is_negative_when_nobody_can_be_spared():
    # A candidate worse than everyone still forces a drop, so the honest answer
    # is <= 0. Reporting 0.0 would say "free", which it is not.
    roster = _roster_for_upgrade()
    cand = Player(sleeper_id="0001", name="Practice Squad Guy", position="WR", team="LV")
    weekly = {1: {**_WK, "0001": 0.5}}
    gain, _, weeks_started = season.roster_upgrade(roster, cand, _waiver_slots(), weekly)
    assert gain <= 0.0
    assert weeks_started == 0


def test_roster_upgrade_sums_the_whole_horizon_not_just_the_first_week():
    roster = _roster_for_upgrade()
    cand = Player(sleeper_id="6790", name="Dalton Schultz", position="TE", team="HOU")
    one = {1: {**_WK, "6790": 12.0}}
    three = {1: {**_WK, "6790": 12.0}, 2: {**_WK, "6790": 12.0}, 3: {**_WK, "6790": 12.0}}
    g1, _, s1 = season.roster_upgrade(roster, cand, _waiver_slots(), one)
    g3, _, s3 = season.roster_upgrade(roster, cand, _waiver_slots(), three)
    assert g3 == pytest.approx(g1 * 3)
    assert (s1, s3) == (1, 3)


def test_roster_upgrade_counts_only_the_weeks_the_candidate_actually_starts():
    # A bye is an ABSENT ROW, not a zero -- verified against the live endpoint
    # (Gibbs has no week-6 row). A candidate missing from a week must not be
    # counted as having started it, and the lineup check ALONE does not say so:
    # on a week with no row his proj_pts is the 0.0 SORT value, and if he is the
    # only player left at his position he fills the slot anyway. Here the drop
    # is the Broncos, so the added defense is the only DEF on the roster, and
    # week 2 -- where neither defense has a row -- must still count as no start.
    roster = _roster_for_upgrade()
    cand = Player(sleeper_id="NE", name="New England Patriots", position="DEF", team="NE")
    week2 = {k: v for k, v in _WK.items() if k != "DEN"}
    weekly = {1: {**_WK, "NE": 9.0}, 2: week2}
    _, drop, weeks_started = season.roster_upgrade(roster, cand, _waiver_slots(), weekly)
    assert drop.sleeper_id == "DEN"
    assert weeks_started == 1


def test_roster_upgrade_breaks_a_drop_tie_on_the_droppeds_own_points():
    # Three drops tie EXACTLY here at +1.6 -- Murray, Gainwell and the Broncos --
    # because upgrading DEF gains the same 1.6 whoever is cut, as long as they
    # were not starting or are the defense being replaced. Naming an arbitrary
    # member of a tie is fabrication, and list order would name Murray. The rule
    # takes the lowest own points, which is the Broncos (7.4) -- and swapping one
    # defense for a better one is also the move a human would make.
    roster = _roster_for_upgrade()
    cand = Player(sleeper_id="NE", name="New England Patriots", position="DEF", team="NE")
    weekly = {1: {**_WK, "NE": 9.0}}
    gain, drop, _ = season.roster_upgrade(roster, cand, _waiver_slots(), weekly)
    assert gain == pytest.approx(1.6)
    assert drop.sleeper_id == "DEN"


def test_best_drop_takes_the_lowest_scorer_among_tied_cuts():
    """Ties are real -- in the real week-1 run five drops tied EXACTLY -- and
    naming an arbitrary member of a tie is fabrication: a name presented as
    computed when it was positional. Among cuts within drop_tie_points of the
    best, take the one with the fewest points of his own, then the id."""
    # Two bench players who never start: cutting either costs the lineup
    # nothing, so the totals tie exactly and only their own points separate them.
    roster = [mk("qb", "QB"), mk("rb1", "RB"), mk("rb2", "RB"),
              mk("bench_hi", "RB"), mk("bench_lo", "RB")]
    slots = {"QB": 1, "RB": 2}
    wbw = {1: {"qb": 20.0, "rb1": 15.0, "rb2": 14.0,
               "bench_hi": 9.0, "bench_lo": 1.0}}
    total, dropped = season.best_drop(roster, slots, wbw)
    assert dropped.sleeper_id == "bench_lo"
    assert total == pytest.approx(20.0 + 15.0 + 14.0)


def test_best_drop_will_cut_a_starter_when_that_is_genuinely_best():
    """The rule is not 'cut a bench player' -- it is 'maximise what remains'.
    A roster whose only cut is a starter must still return one."""
    roster = [mk("qb", "QB"), mk("qb2", "QB")]
    slots = {"QB": 1}
    wbw = {1: {"qb": 20.0, "qb2": 3.0}}
    total, dropped = season.best_drop(roster, slots, wbw)
    assert dropped.sleeper_id == "qb2"
    assert total == pytest.approx(20.0)


# --- Phase 4c: the ranking and the significance floor ------------------------


def test_waiver_targets_ranks_by_gain_and_respects_the_limit():
    roster = _roster_for_upgrade()
    pool = [
        Player(sleeper_id="6790", name="Dalton Schultz", position="TE", team="HOU"),
        Player(sleeper_id="8110", name="Chig Okonkwo", position="TE", team="TEN"),
    ]
    weekly = {1: {**_WK, "6790": 22.0, "8110": 18.0}}
    got = season.waiver_targets(roster, pool, _waiver_slots(), weekly,
                                close_call_points=3.0, limit=1)
    assert [t.player.sleeper_id for t in got] == ["6790"]
    assert got[0].gain == pytest.approx(12.3)


def test_waiver_targets_floor_is_close_call_points_on_a_one_week_horizon():
    roster = _roster_for_upgrade()
    # Ferguson starts TE at 9.7; an 11.7 TE gains exactly 2.0, under the 3.0 bar.
    pool = [Player(sleeper_id="6790", name="Dalton Schultz", position="TE", team="HOU")]
    weekly = {1: {**_WK, "6790": 11.7}}
    assert season.waiver_targets(roster, pool, _waiver_slots(), weekly,
                                 close_call_points=3.0) == []
    # 13.7 gains 4.0 and clears it.
    weekly = {1: {**_WK, "6790": 13.7}}
    assert len(season.waiver_targets(roster, pool, _waiver_slots(), weekly,
                                     close_call_points=3.0)) == 1


def test_waiver_targets_floor_scales_as_sqrt_of_the_horizon():
    # THE POINT OF THE SQRT. close_call_points is calibrated to ONE week's
    # error; independent weekly errors partially cancel, so the bar on a
    # 9-week total is 3.0*3 = 9.0, not 3.0*9 = 27.0. A flat per-week bar is
    # ~4x too strict and silences real upgrades.
    roster = _roster_for_upgrade()
    pool = [Player(sleeper_id="6790", name="Dalton Schultz", position="TE", team="HOU")]
    # +1.3 a week over 9 weeks = 11.7 total. Bar is 9.0, so it clears.
    weekly = {w: {**_WK, "6790": 11.0} for w in range(1, 10)}
    got = season.waiver_targets(roster, pool, _waiver_slots(), weekly, close_call_points=3.0)
    assert len(got) == 1 and got[0].weeks_started == 9
    # A flat 3.0/week bar would have demanded 27.0 and printed nothing.
    assert got[0].gain < 27.0
    # And the bar really does GROW with the horizon: +0.5 a week is 4.5 over
    # nine weeks -- above a flat 3.0, below the 9.0 the sqrt demands -- so it is
    # silenced. Without the sqrt this noise-level target would be listed.
    quiet = {w: {**_WK, "6790": 10.2} for w in range(1, 10)}
    assert season.waiver_targets(roster, pool, _waiver_slots(), quiet,
                                 close_call_points=3.0) == []


def test_waiver_targets_returns_empty_when_nothing_clears_and_that_is_a_result():
    # The measured healthy-roster case: the best thing available is 0.46 pts a
    # week. An empty board is the honest answer and the caller prints it as one.
    roster = _roster_for_upgrade()
    pool = [Player(sleeper_id="0001", name="Deep Bench Guy", position="WR", team="LV")]
    weekly = {w: {**_WK, "0001": 1.0} for w in range(1, 19)}
    assert season.waiver_targets(roster, pool, _waiver_slots(), weekly,
                                 close_call_points=3.0) == []


def test_week_weights_are_one_for_every_regular_season_week():
    w = season.week_weights(_settings(), range(1, 15))
    assert set(w.values()) == {1.0}


def test_week_weights_derive_playoff_weeks_from_the_bracket():
    """6 of 12 teams make it, top two seeded on a bye. So week 15 is played by
    the four unseeded qualifiers, week 16 by four, week 17 by two -- and the
    weight is the share of the league that plays it. Derived from the payload,
    NOT a picked multiplier: a hand-chosen number is what CLAUDE.md forbids."""
    w = season.week_weights(_settings(), range(15, 18))
    assert w[15] == pytest.approx(4 / 12)
    assert w[16] == pytest.approx(4 / 12)
    assert w[17] == pytest.approx(2 / 12)


def test_week_weights_shrink_the_bracket_for_a_four_team_playoff():
    """Two rounds, not three. The round sizes must follow playoff_teams."""
    w = season.week_weights(_settings(playoff_teams=4), range(15, 17))
    assert w[15] == pytest.approx(4 / 12)
    assert w[16] == pytest.approx(2 / 12)


def test_playoff_weight_overrides_the_derivation_for_playoff_weeks_only():
    """The knob exists because the direction is contested -- the literature
    weights playoff weeks UP. Setting it must not touch weeks 1-14."""
    w = season.week_weights(_settings(), range(13, 18), playoff_weight=2.0)
    assert w[13] == 1.0 and w[14] == 1.0
    assert w[15] == 2.0 and w[16] == 2.0 and w[17] == 2.0


def test_week_weights_are_flat_when_the_league_serves_no_playoff_block():
    """Degrade to flat, never to a guessed bracket."""
    w = season.week_weights(_settings(playoff_week_start=None, playoff_teams=None),
                            range(1, 19))
    assert set(w.values()) == {1.0}


def _settings(**kw):
    """A LeagueSettings with the real sleeper-main shape, overridable per test."""
    from ffhelper.data import LeagueSettings
    base = dict(
        num_teams=12,
        scoring={"rec": 1.0, "rec_yd": 0.1, "rec_td": 6.0},
        roster_slots={"QB": 1, "RB": 2, "WR": 2, "TE": 1, "FLEX": 2, "K": 1, "DEF": 1},
        rounds=15,
        playoff_week_start=15,
        playoff_teams=6,
        playoff_round_type=0,
    )
    base.update(kw)
    return LeagueSettings(**base)


def test_last_scoring_week_is_the_final_playoff_week_not_week_18():
    """6 teams is a 3-round bracket, so 15 -> 17. Week 18 is played by nobody
    and contributes to no fantasy outcome; summing it silently pads every
    rest-of-season total with a week that cannot be won."""
    week, note = season.last_scoring_week(_settings())
    assert week == 17
    assert note is None


def test_last_scoring_week_handles_a_four_team_bracket():
    """ceil(log2(4)) = 2 rounds, so 15 -> 16. The arithmetic must follow the
    bracket, not a constant offset."""
    week, note = season.last_scoring_week(_settings(playoff_teams=4))
    assert week == 16
    assert note is None


def test_last_scoring_week_refuses_multi_week_rounds_and_says_so():
    """playoff_round_type != 0 means a round spans two weeks, which this tool
    does not model. Fall back to the constant and NAME the reason -- computing
    a confident wrong last week is the fabrication this project forbids."""
    week, note = season.last_scoring_week(_settings(playoff_round_type=1))
    assert week == season.LAST_REGULAR_WEEK
    assert note is not None and "round" in note


def test_last_scoring_week_falls_back_when_the_league_serves_no_playoff_fields():
    """Yahoo's hand-entered settings carry no playoff block at all. Degrade to
    the constant with a note, never to a guessed bracket."""
    week, note = season.last_scoring_week(
        _settings(playoff_week_start=None, playoff_teams=None, playoff_round_type=None))
    assert week == season.LAST_REGULAR_WEEK
    assert note is not None
