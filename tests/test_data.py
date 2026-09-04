import json
from pathlib import Path

import pytest

from ffhelper.data import fetch_json, fetch_text, load_crosswalk, load_league_rosters, rosters_cache_key


def test_fetches_and_caches(tmp_path: Path):
    calls = []

    def fake(url: str) -> str:
        calls.append(url)
        return json.dumps({"v": 1})

    a = fetch_json("http://x/y", "k", cache_dir=tmp_path, fetcher=fake)
    b = fetch_json("http://x/y", "k", cache_dir=tmp_path, fetcher=fake)
    assert a == b == {"v": 1}
    assert len(calls) == 1, "second call should hit the disk cache"


def test_falls_back_to_stale_cache_on_failure(tmp_path: Path):
    def ok(url: str) -> str:
        return json.dumps({"v": 1})

    def boom(url: str) -> str:
        raise ConnectionError("network down")

    fetch_json("http://x/y", "k", cache_dir=tmp_path, fetcher=ok)
    # ttl=0 forces a refetch attempt, which fails; stale cache must be returned
    got = fetch_json("http://x/y", "k", ttl_seconds=0, cache_dir=tmp_path, fetcher=boom)
    assert got == {"v": 1}


def test_stale_ok_false_raises_even_though_a_usable_cache_exists(tmp_path: Path):
    """Live data (the pick feed) must FAIL LOUDLY rather than silently serve the
    last good answer -- a frozen pick list looks perfectly healthy and makes
    every survival and VONA number on the board wrong.

    Against the pre-fix code (no `stale_ok` at all) this returns {"v": 1} from
    the stale cache and never raises, so this test fails.
    """
    fetch_json("http://x/y", "k", cache_dir=tmp_path, fetcher=lambda url: json.dumps({"v": 1}))

    def boom(url: str) -> str:
        raise ConnectionError("network down")

    with pytest.raises(ConnectionError):
        fetch_json("http://x/y", "k", ttl_seconds=0, cache_dir=tmp_path,
                   fetcher=boom, stale_ok=False)


def test_raises_when_no_cache_and_fetch_fails(tmp_path: Path):
    def boom(url: str) -> str:
        raise ConnectionError("network down")

    with pytest.raises(ConnectionError):
        fetch_json("http://x/y", "k", cache_dir=tmp_path, fetcher=boom)


def test_fetch_text_fetches_and_caches(tmp_path: Path):
    calls = []

    def fake(url: str) -> str:
        calls.append(url)
        return "<rss>body</rss>"

    a = fetch_text("http://x/y", "k", cache_dir=tmp_path, fetcher=fake)
    b = fetch_text("http://x/y", "k", cache_dir=tmp_path, fetcher=fake)
    assert a == b == "<rss>body</rss>"
    assert len(calls) == 1, "second call should hit the disk cache"


def test_fetch_text_falls_back_to_stale_cache_on_failure(tmp_path: Path):
    """The one behaviour Ruling T10-A is about: reusing fetch_json's cache
    helpers UNCHANGED for text would parse every read as JSON, so a plain-text
    stale cache would never be found usable and this would raise instead of
    returning the stale body. Against that (pre-fix) code, this test fails.
    """
    def ok(url: str) -> str:
        return "<rss>fresh</rss>"

    def boom(url: str) -> str:
        raise ConnectionError("network down")

    fetch_text("http://x/y", "k", cache_dir=tmp_path, fetcher=ok)
    # ttl=0 forces a refetch attempt, which fails; stale cache must be returned
    got = fetch_text("http://x/y", "k", ttl_seconds=0, cache_dir=tmp_path, fetcher=boom)
    assert got == "<rss>fresh</rss>"


def test_fetch_text_and_fetch_json_do_not_collide_on_cache_key(tmp_path: Path):
    """`fetch_json` writes `{key}.json`; `fetch_text` must not land on the same
    filename for the same cache_key, or one would silently clobber the other."""
    fetch_json("http://x/y", "shared_key", cache_dir=tmp_path, fetcher=lambda u: json.dumps({"v": 1}))
    fetch_text("http://x/y", "shared_key", cache_dir=tmp_path, fetcher=lambda u: "plain text")

    assert fetch_json("http://x/y", "shared_key", cache_dir=tmp_path,
                      fetcher=lambda u: (_ for _ in ()).throw(AssertionError("should hit cache"))) == {"v": 1}
    assert fetch_text("http://x/y", "shared_key", cache_dir=tmp_path,
                      fetcher=lambda u: (_ for _ in ()).throw(AssertionError("should hit cache"))) == "plain text"


def test_corrupt_cache_within_ttl_refetches(tmp_path: Path):
    """Corrupt/truncated cache within TTL should be skipped and fresh data fetched."""
    call_count = [0]

    def fetcher(url: str) -> str:
        call_count[0] += 1
        return json.dumps({"v": call_count[0]})

    # First fetch populates cache.
    result1 = fetch_json("http://x/y", "k", cache_dir=tmp_path, fetcher=fetcher)
    assert result1 == {"v": 1}

    # Corrupt the cache file by truncating it.
    cache_file = tmp_path / "k.json"
    cache_file.write_text("{corrupted")

    # Second fetch should detect corruption, refetch, and return new data (not stale).
    result2 = fetch_json("http://x/y", "k", ttl_seconds=3600, cache_dir=tmp_path, fetcher=fetcher)
    assert result2 == {"v": 2}, "should refetch when cache is corrupt"
    assert call_count[0] == 2, "should have called fetcher twice"


def test_corrupt_cache_with_failing_fetcher_raises_fetch_error(tmp_path: Path):
    """Corrupt stale cache + failed fetch should raise the fetch exception, not JSON error."""
    def ok(url: str) -> str:
        return json.dumps({"v": 1})

    def boom(url: str) -> str:
        raise ConnectionError("network down")

    # First fetch populates cache.
    fetch_json("http://x/y", "k", cache_dir=tmp_path, fetcher=ok)

    # Corrupt the cache file.
    cache_file = tmp_path / "k.json"
    cache_file.write_text("{bad json")

    # Try to fetch with a failing fetcher and no TTL (forces refetch).
    # Should raise ConnectionError (the fetch failure), not JSONDecodeError (cache corruption).
    with pytest.raises(ConnectionError, match="network down"):
        fetch_json("http://x/y", "k", ttl_seconds=0, cache_dir=tmp_path, fetcher=boom)


def test_no_leftover_temp_files_after_successful_fetch(tmp_path: Path):
    """After a successful fetch, cache dir should contain only the .json file, no temp files."""
    def fetcher(url: str) -> str:
        return json.dumps({"v": 1})

    fetch_json("http://x/y", "k", cache_dir=tmp_path, fetcher=fetcher)

    # Check that only the expected .json file exists.
    files = list(tmp_path.iterdir())
    assert len(files) == 1, f"expected 1 file, found {len(files)}: {files}"
    assert files[0].name == "k.json", f"expected k.json, found {files[0].name}"


def test_failed_cache_write_leaves_no_temp_file_behind(tmp_path: Path, monkeypatch):
    """The success case above passes with or without the cleanup handler --
    os.replace consumes the temp file either way, so it asserts steady state,
    not atomicity. This drives the path the handler exists for: os.replace
    fails, and the mkstemp file must be unlinked rather than accumulating one
    orphan per failed write for the life of the .cache directory.

    Delete the handler in `_write_cache_atomic` and this test fails; the one
    above still passes.
    """
    def boom(src, dst):
        raise OSError("cross-device link")

    monkeypatch.setattr("ffhelper.data.os.replace", boom)

    with pytest.raises(OSError):
        fetch_json("http://x/y", "k", cache_dir=tmp_path,
                   fetcher=lambda url: json.dumps({"v": 1}))

    assert list(tmp_path.iterdir()) == []


CROSSWALK_CSV = "sleeper_id,yahoo_id\n1,100\n2,200\n"


def test_load_crosswalk_corrupt_cache_within_ttl_refetches(tmp_path: Path):
    """Corrupt crosswalk cache within TTL should be skipped and fresh data fetched, not crash."""
    call_count = [0]

    def fetcher(url: str) -> str:
        call_count[0] += 1
        return CROSSWALK_CSV

    result1 = load_crosswalk(cache_dir=tmp_path, fetcher=fetcher)
    assert result1 == {"1": "100", "2": "200"}

    cache_file = tmp_path / "crosswalk_yahoo_id.json"
    cache_file.write_text("{corrupted")

    result2 = load_crosswalk(cache_dir=tmp_path, fetcher=fetcher)
    assert result2 == {"1": "100", "2": "200"}, "should refetch when cache is corrupt, not raise"
    assert call_count[0] == 2, "should have called fetcher twice"


def test_load_crosswalk_corrupt_cache_with_failing_fetcher_raises_fetch_error(tmp_path: Path):
    """Corrupt stale crosswalk cache + failed fetch should raise the fetch exception, not a JSON error."""

    def ok(url: str) -> str:
        return CROSSWALK_CSV

    def boom(url: str) -> str:
        raise ConnectionError("network down")

    load_crosswalk(cache_dir=tmp_path, fetcher=ok)

    cache_file = tmp_path / "crosswalk_yahoo_id.json"
    cache_file.write_text("{bad json")

    with pytest.raises(ConnectionError, match="network down"):
        load_crosswalk(cache_dir=tmp_path, fetcher=boom)


# (A duplicate "no leftover temp files after load_crosswalk" test lived here.
#  Both callers share `_write_cache_atomic`, so the two tests above cover it.)


from ffhelper.data import Player, norm_name, build_players


def test_norm_name_strips_punctuation_and_case():
    assert norm_name("Ja'Marr Chase") == "jamarrchase"
    assert norm_name("Amon-Ra St. Brown") == "amonrastbrown"


def test_crosswalk_join_is_by_id_not_name():
    """Bijan and Brian Robinson are both ATL RBs. Name+pos+team collides;
    sleeper_id does not. This is a real bug hit during design."""
    raw = {
        "9221": {"full_name": "Jahmyr Gibbs", "position": "RB", "team": "DET",
                 "active": True, "injury_status": None},
        "8155": {"full_name": "Bijan Robinson", "position": "RB", "team": "ATL",
                 "active": True, "injury_status": None},
        "7588": {"full_name": "Brian Robinson", "position": "RB", "team": "ATL",
                 "active": True, "injury_status": "Questionable"},
    }
    crosswalk = {"9221": "40059", "8155": "40000", "7588": "34000"}
    players = build_players(raw, crosswalk)

    assert len(players) == 3, "no player may be dropped or merged"
    assert players["8155"].name == "Bijan Robinson"
    assert players["7588"].name == "Brian Robinson"
    assert players["8155"].yahoo_id == "40000"
    assert players["7588"].yahoo_id == "34000"
    assert players["9221"].yahoo_id == "40059"
    assert players["7588"].injury_status == "Questionable"


def test_missing_crosswalk_entry_leaves_yahoo_id_none():
    raw = {"1": {"full_name": "Nobody Special", "position": "WR", "team": "SF",
                 "active": True, "injury_status": None}}
    players = build_players(raw, {})
    assert players["1"].yahoo_id is None


def test_inactive_and_irrelevant_positions_excluded():
    raw = {
        "1": {"full_name": "Active WR", "position": "WR", "team": "SF",
              "active": True, "injury_status": None},
        "2": {"full_name": "Retired Guy", "position": "WR", "team": None,
              "active": False, "injury_status": None},
        "3": {"full_name": "Some Guard", "position": "OG", "team": "SF",
              "active": True, "injury_status": None},
    }
    assert set(build_players(raw, {})) == {"1"}


from ffhelper.data import LeagueSettings, apply_projections, score_stats

# Josh Allen's real 2026 projection, inlined. One record for a golden value is
# de minimis; the bulk dataset is never committed.
ALLEN_STATS = {
    "pass_yd": 3650.0, "pass_td": 27.0, "pass_int": 10.0, "pass_2pt": 1.0,
    "rush_yd": 535.0, "rush_td": 11.0, "rush_2pt": 1.0, "fum_lost": 3.0,
    "pts_ppr": 361.5,
}
# The league's real scoring: full PPR with SIX-point passing TDs.
LEAGUE_SCORING = {
    "pass_yd": 0.04, "pass_td": 6.0, "pass_int": -1.0, "pass_2pt": 2.0,
    "rush_yd": 0.1, "rush_td": 6.0, "rush_2pt": 2.0, "fum_lost": -2.0,
    "rec": 1.0, "rec_yd": 0.1, "rec_td": 6.0,
}


def test_custom_scoring_golden_value():
    """6-pt passing TDs put Allen at 415.5, not Sleeper's canned 361.5."""
    assert round(score_stats(ALLEN_STATS, LEAGUE_SCORING), 1) == 415.5


def test_scoring_ignores_non_scoring_stat_keys():
    """pts_ppr, gp, cmp_pct etc. appear in stats but are not scoring categories."""
    noisy = dict(ALLEN_STATS, gp=18.0, cmp_pct=66.03, pass_att=474.0)
    assert round(score_stats(noisy, LEAGUE_SCORING), 1) == 415.5


def test_full_ppr_skill_players_match_canned_pts_ppr():
    """RB/WR/TE scoring is standard here, so custom must equal canned."""
    gibbs = {"rush_yd": 1251.0, "rush_td": 12.0, "rec": 63.0, "rec_yd": 533.0,
             "rec_td": 3.0, "fum_lost": 1.0, "rush_2pt": 1.0}
    assert round(score_stats(gibbs, LEAGUE_SCORING), 1) == 331.4


def test_apply_projections_sets_points_and_skips_unknown_ids():
    players = {"9221": Player("9221", "Jahmyr Gibbs", "RB", "DET")}
    proj = [
        {"player_id": "9221", "stats": {"rush_yd": 1000.0, "rush_td": 10.0}},
        {"player_id": "0000", "stats": {"rush_yd": 500.0}},   # not in our pool
        {"player_id": "9221", "stats": None},                  # malformed, ignore
    ]
    apply_projections(players, proj, LEAGUE_SCORING)
    assert players["9221"].proj_pts == 160.0


from ffhelper.data import apply_ffc_adp, apply_sleeper_adp, curve_stdev


def test_curve_stdev_matches_fitted_parameters():
    # stdev = 0.287 * adp^0.809, fitted from FFC 12-team PPR data
    assert round(curve_stdev(1.0), 3) == 0.287
    assert curve_stdev(100.0) > curve_stdev(10.0), "variance grows with ADP"


def test_sleeper_adp_applied_by_id_before_ffc():
    players = {"9221": Player("9221", "Jahmyr Gibbs", "RB", "DET")}
    proj = [{"player_id": "9221", "stats": {"adp_ppr": 1.0, "pts_ppr": 331.4}}]
    apply_sleeper_adp(players, proj, "adp_ppr")
    assert players["9221"].adp == 1.0
    assert players["9221"].adp_stdev == pytest.approx(curve_stdev(1.0))


def test_ffc_overwrites_stdev_on_match():
    players = {"9221": Player("9221", "Jahmyr Gibbs", "RB", "DET", adp=1.0)}
    unmatched = apply_ffc_adp(
        players, [{"name": "Jahmyr Gibbs", "position": "RB", "team": "DET",
                   "adp": 1.5, "stdev": 0.7, "bye": 6}]
    )
    assert unmatched == []
    assert players["9221"].adp == 1.5
    assert players["9221"].adp_stdev == 0.7
    assert players["9221"].bye == 6


def test_ffc_miss_is_reported_and_player_keeps_id_keyed_values():
    """A fuzzy-join failure must never drop or corrupt a player."""
    players = {"9221": Player("9221", "Jahmyr Gibbs", "RB", "DET",
                              adp=1.0, adp_stdev=0.287)}
    unmatched = apply_ffc_adp(
        players, [{"name": "Someone Unknown", "position": "WR", "team": "XXX",
                   "adp": 50.0, "stdev": 9.9, "bye": 7}]
    )
    assert unmatched == ["Someone Unknown"]
    assert len(players) == 1, "no player added or dropped by the fuzzy join"
    assert players["9221"].adp == 1.0, "ID-keyed ADP survives an FFC miss"
    assert players["9221"].adp_stdev == 0.287


def test_norm_name_strips_generational_suffix_tokens():
    """Suffixes must be stripped as whole trailing tokens, so the suffixed and
    unsuffixed forms of a name land on the same key."""
    assert norm_name("Marvin Harrison Jr.") == norm_name("Marvin Harrison") == "marvinharrison"
    assert norm_name("James Cook III") == norm_name("James Cook") == "jamescook"
    # Negative case: ordinary names must not be mangled by the suffix stripper.
    # Neither ends in a suffix TOKEN even though "Ridley" and "Calvin" both
    # contain suffix-like letters ("v", "iv") mid-word.
    assert norm_name("Trevor Lawrence") == "trevorlawrence"
    assert norm_name("Calvin Ridley") == "calvinridley"


def test_norm_name_folds_unicode_to_ascii():
    """Accents must be folded, not deleted: Piñeiro -> Pineiro, not Pieiro."""
    assert norm_name("Eddy Piñeiro") == norm_name("Eddy Pineiro") == "eddypineiro"


def test_ffc_pk_position_matches_sleeper_kicker():
    """FFC's 'PK' position code must join against Sleeper's 'K'."""
    players = {"1": Player("1", "Justin Tucker", "K", "BAL")}
    unmatched = apply_ffc_adp(players, [
        {"name": "Justin Tucker", "position": "PK", "team": "BAL",
         "adp": 120.0, "stdev": 15.0, "bye": 14}
    ])
    assert unmatched == []
    assert players["1"].adp == 120.0
    assert players["1"].adp_stdev == 15.0
    assert players["1"].bye == 14


def test_ffc_defense_matches_by_team_code_not_name():
    """Sleeper DEF entries have full_name == '' and are keyed by team code, so
    FFC's 'Seattle Defense' must join on team, never on name."""
    players = {"SEA": Player("SEA", "", "DEF", "SEA")}
    unmatched = apply_ffc_adp(players, [
        {"name": "Seattle Defense", "position": "DEF", "team": "SEA",
         "adp": 45.0, "stdev": 5.0, "bye": 8}
    ])
    assert unmatched == []
    assert players["SEA"].adp == 45.0
    assert players["SEA"].adp_stdev == 5.0
    assert players["SEA"].bye == 8


def test_ffc_does_not_merge_bijan_and_brian():
    players = {
        "8155": Player("8155", "Bijan Robinson", "RB", "ATL"),
        "7588": Player("7588", "Brian Robinson", "RB", "ATL"),
    }
    apply_ffc_adp(players, [
        {"name": "Bijan Robinson", "position": "RB", "team": "ATL",
         "adp": 2.0, "stdev": 0.8, "bye": 5},
        {"name": "Brian Robinson", "position": "RB", "team": "ATL",
         "adp": 150.0, "stdev": 20.0, "bye": 5},
    ])
    assert players["8155"].adp == 2.0
    assert players["7588"].adp == 150.0


def test_ffc_ambiguous_key_matches_neither_player():
    """Two different players sharing a match_key (e.g. the real Ronald Jones
    collision) must both be skipped, not have one silently overwritten."""
    players = {
        "5052": Player("5052", "Ronald Jones", "RB", None,
                        adp=200.0, adp_stdev=25.0),
        "4955": Player("4955", "Ronald Jones", "RB", None,
                        adp=210.0, adp_stdev=26.0),
    }
    unmatched = apply_ffc_adp(players, [
        {"name": "Ronald Jones", "position": "RB", "team": "",
         "adp": 5.0, "stdev": 1.0, "bye": 9},
    ])
    assert unmatched == ["AMBIGUOUS: Ronald Jones"]
    # Neither player is touched -- pre-existing ID-keyed values survive intact.
    assert players["5052"].adp == 200.0
    assert players["5052"].adp_stdev == 25.0
    assert players["4955"].adp == 210.0
    assert players["4955"].adp_stdev == 26.0


def test_ffc_unique_key_still_matches_despite_ambiguity_guard():
    """A player who shares no match_key with anyone must match normally --
    proving the ambiguity guard doesn't break ordinary matching."""
    players = {
        "5052": Player("5052", "Ronald Jones", "RB", None,
                        adp=200.0, adp_stdev=25.0),
        "4955": Player("4955", "Ronald Jones", "RB", None,
                        adp=210.0, adp_stdev=26.0),
        "9221": Player("9221", "Jahmyr Gibbs", "RB", "DET", adp=999.0),
    }
    unmatched = apply_ffc_adp(players, [
        {"name": "Ronald Jones", "position": "RB", "team": "",
         "adp": 5.0, "stdev": 1.0, "bye": 9},
        {"name": "Jahmyr Gibbs", "position": "RB", "team": "DET",
         "adp": 1.5, "stdev": 0.3, "bye": 6},
    ])
    assert unmatched == ["AMBIGUOUS: Ronald Jones"]
    assert players["9221"].adp == 1.5
    assert players["9221"].adp_stdev == 0.3
    assert players["9221"].bye == 6


def test_ffc_ambiguous_def_team_matches_neither():
    """Two DEF entries sharing a team code must both be skipped, not have one
    silently overwritten. Both retain their pre-existing ID-keyed adp/adp_stdev,
    and the FFC row is reported with the AMBIGUOUS prefix."""
    players = {
        "SEA": Player("SEA", "", "DEF", "SEA", adp=45.0, adp_stdev=5.0),
        "SEA_ALT": Player("SEA_ALT", "", "DEF", "SEA", adp=50.0, adp_stdev=6.0),
    }
    unmatched = apply_ffc_adp(players, [
        {"name": "Seattle Defense", "position": "DEF", "team": "SEA",
         "adp": 20.0, "stdev": 2.0, "bye": 8}
    ])
    assert unmatched == ["AMBIGUOUS: Seattle Defense"]
    # Neither player is touched -- pre-existing ID-keyed values survive intact.
    assert players["SEA"].adp == 45.0
    assert players["SEA"].adp_stdev == 5.0
    assert players["SEA_ALT"].adp == 50.0
    assert players["SEA_ALT"].adp_stdev == 6.0


def test_load_weekly_projections_asks_for_the_week_and_caches_per_week(tmp_path):
    """The season endpoint is frozen preseason; only the weekly one is revised
    in-season. The cache key must carry the week, or week 2 is served week 1's
    numbers for the rest of the season while looking healthy."""
    from ffhelper.data import load_weekly_projections
    seen = []

    def fake(url):
        seen.append(url)
        return '[{"player_id": "4034", "stats": {"pts_ppr": 21.5, "rush_yd": 88.0}}]'

    rows = load_weekly_projections("2026", 3, cache_dir=tmp_path, fetcher=fake)

    assert all("/2026/3?" in u for u in seen), seen
    assert len(rows) == 6          # one call per position
    assert rows[0]["stats"]["rush_yd"] == 88.0
    names = sorted(p.name for p in tmp_path.iterdir())
    assert any("wk3" in n for n in names), names


def test_build_players_carries_status_fields_and_tolerates_their_absence():
    """Sleeper's player DB has 52 fields and we keep six. These four are the
    structured form of the injury news start/sit needs, and depth_chart_order is
    the waiver signal: the backup who becomes the starter on Wednesday.

    Absent fields must be None, never 0 -- depth_chart_order 0 would read as
    'first on the depth chart' for every player Sleeper has no data for."""
    raw = {
        "1": {"player_id": "1", "full_name": "Hurt Guy", "position": "RB", "team": "SEA",
              "active": True, "injury_status": "Questionable", "injury_body_part": "Ankle",
              "practice_participation": "Limited", "depth_chart_order": 1},
        "2": {"player_id": "2", "full_name": "Fine Guy", "position": "RB", "team": "SEA",
              "active": True},
    }
    players = build_players(raw, crosswalk={})

    assert players["1"].injury_status == "Questionable"
    assert players["1"].injury_body_part == "Ankle"
    assert players["1"].practice_participation == "Limited"
    assert players["1"].depth_chart_order == 1
    assert players["2"].practice_participation is None
    assert players["2"].depth_chart_order is None


def test_league_loaders_hit_the_right_urls_and_cache_per_league(tmp_path):
    seen = []

    def fake(url):
        seen.append(url)
        return '[{"roster_id": 3, "players": ["a"]}]'

    got = load_league_rosters("123", cache_dir=tmp_path, fetcher=fake)
    assert seen == ["https://api.sleeper.app/v1/league/123/rosters"]
    assert got[0]["roster_id"] == 3
    # The LITERAL filename. Deriving it from `rosters_cache_key` -- the very
    # function under test -- made this assertion pass for any key format at
    # all, including the "rosters_123_v2" case the comment claimed to catch:
    # both sides moved together. The exact string is the only form that
    # actually pins the on-disk name.
    assert (tmp_path / "rosters_123.json").exists()
    assert rosters_cache_key("123") == "rosters_123"


def test_load_weekly_actuals_carries_the_week_and_the_opponent(tmp_path):
    """The actuals endpoint is the mirror of the projections one, and `opponent`
    is the whole reason it exists -- it is the join for matchup strength. Same
    per-week cache key for the same reason: without the week, every week after
    the first is served week 1's results while looking healthy."""
    from ffhelper.data import load_weekly_actuals
    seen = []

    def fake(url):
        seen.append(url)
        return ('[{"player_id": "4034", "week": 3, "team": "SF", "opponent": "SEA", '
                '"stats": {"pts_ppr": 18.4, "rush_yd": 76.0}}]')

    rows = load_weekly_actuals("2025", 3, cache_dir=tmp_path, fetcher=fake)

    assert all("/stats/nfl/2025/3?" in u for u in seen), seen
    assert len(rows) == 6          # one call per position
    assert rows[0]["opponent"] == "SEA"
    names = sorted(p.name for p in tmp_path.iterdir())
    assert any("stats_2025_wk3" in n for n in names), names


def test_load_nfl_injuries_keeps_only_the_asked_for_week(tmp_path):
    """One CSV holds every week of the season. Without the week filter a lineup
    would carry September's practice report in December, looking healthy."""
    from ffhelper.data import load_nfl_injuries

    csv_text = (
        "season,week,gsis_id,full_name,report_status,practice_status\n"
        # A DIFFERENT player, so dropping the week filter ADDS a key rather than
        # being overwritten by the week-5 row for the same man -- the first
        # version of this test could not see the bug it existed for.
        "2025,4,00-0035676,Last Week Only,,Limited Participation in Practice\n"
        "2025,5,00-0038543,Jahmyr Gibbs,Questionable,Did Not Participate In Practice\n"
        "2025,5,00-0033280,Christian McCaffrey,,Full Participation in Practice\n"
        "2025,5,,No Id Guy,,Full Participation in Practice\n"
        "2025,5,00-0000009,No Practice Filed,Out,\n"
    )
    out = load_nfl_injuries("2025", 5, cache_dir=tmp_path, fetcher=lambda url: csv_text)

    assert out == {"00-0038543": "DNP", "00-0033280": "Full"}


def test_load_trending_maps_player_id_to_count(tmp_path):
    from ffhelper.data import load_trending

    body = '[{"player_id": "11237", "count": 279845}, {"player_id": "8800", "count": 188559}]'
    got = load_trending("add", cache_dir=tmp_path, fetcher=lambda url: body)
    assert got == {"11237": 279845, "8800": 188559}


def test_load_trending_cache_key_separates_add_from_drop(tmp_path):
    # Without the kind in the key, the second caller is served the first one's
    # answer and every "dropped" count is silently an "added" count. Same defect
    # as the weekly-projection cache key that had to carry the week.
    from ffhelper.data import load_trending

    load_trending("add", cache_dir=tmp_path,
                  fetcher=lambda url: '[{"player_id": "1", "count": 5}]')
    got = load_trending("drop", cache_dir=tmp_path,
                        fetcher=lambda url: '[{"player_id": "2", "count": 9}]')
    assert got == {"2": 9}


def test_load_trending_rejects_an_unknown_kind(tmp_path):
    from ffhelper.data import load_trending

    with pytest.raises(ValueError):
        load_trending("sideways", cache_dir=tmp_path, fetcher=lambda url: "[]")


def test_load_trending_skips_rows_with_no_player_id(tmp_path):
    from ffhelper.data import load_trending

    body = '[{"count": 5}, {"player_id": "8800", "count": 12}]'
    got = load_trending("add", cache_dir=tmp_path, fetcher=lambda url: body)
    assert got == {"8800": 12}


def test_sleeper_settings_carry_the_playoff_calendar(tmp_path):
    """The horizon end is a league RULE and must be read, not assumed. Same
    class as the one-RB-slot and FAAB errors, both of which came from taking an
    API default as fact."""
    payload = {
        "total_rosters": 12,
        "scoring_settings": {"rec": 1.0},
        "roster_positions": ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "FLEX",
                             "K", "DEF", "BN", "BN", "BN", "BN", "BN"],
        "draft_id": "123",
        "settings": {"playoff_week_start": 15, "playoff_teams": 6,
                     "playoff_round_type": 0, "trade_deadline": 11},
    }
    from ffhelper.data import load_sleeper_settings

    st = load_sleeper_settings(
        "L1", cache_dir=tmp_path, fetcher=lambda url: json.dumps(payload))
    assert st.playoff_week_start == 15
    assert st.playoff_teams == 6
    assert st.playoff_round_type == 0
    assert st.trade_deadline == 11


def test_sleeper_settings_playoff_fields_are_none_when_absent(tmp_path):
    """A payload without a settings block must yield None, not 0 -- 0 would
    read as 'playoffs start week 0' and produce a nonsense horizon."""
    from ffhelper.data import load_sleeper_settings

    payload = {"total_rosters": 12, "scoring_settings": {}, "roster_positions": ["QB"]}
    st = load_sleeper_settings(
        "L1", cache_dir=tmp_path, fetcher=lambda url: json.dumps(payload))
    assert st.playoff_week_start is None
    assert st.playoff_teams is None
