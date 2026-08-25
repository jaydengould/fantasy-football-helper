import json
from pathlib import Path

import pytest

from ffhelper.data import fetch_json, load_crosswalk


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


def test_raises_when_no_cache_and_fetch_fails(tmp_path: Path):
    def boom(url: str) -> str:
        raise ConnectionError("network down")

    with pytest.raises(ConnectionError):
        fetch_json("http://x/y", "k", cache_dir=tmp_path, fetcher=boom)


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


CROSSWALK_CSV = "sleeper_id,yahoo_id\n1,100\n2,200\n"


def test_load_crosswalk_corrupt_cache_within_ttl_refetches(tmp_path: Path):
    """Corrupt crosswalk cache within TTL should be skipped and fresh data fetched, not crash."""
    call_count = [0]

    def fetcher(url: str) -> str:
        call_count[0] += 1
        return CROSSWALK_CSV

    result1 = load_crosswalk(cache_dir=tmp_path, fetcher=fetcher)
    assert result1 == {"1": "100", "2": "200"}

    cache_file = tmp_path / "crosswalk.json"
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

    cache_file = tmp_path / "crosswalk.json"
    cache_file.write_text("{bad json")

    with pytest.raises(ConnectionError, match="network down"):
        load_crosswalk(cache_dir=tmp_path, fetcher=boom)


def test_load_crosswalk_no_leftover_temp_files(tmp_path: Path):
    """After a successful load_crosswalk, cache dir should contain only crosswalk.json."""

    def fetcher(url: str) -> str:
        return CROSSWALK_CSV

    load_crosswalk(cache_dir=tmp_path, fetcher=fetcher)

    files = list(tmp_path.iterdir())
    assert len(files) == 1, f"expected 1 file, found {len(files)}: {files}"
    assert files[0].name == "crosswalk.json", f"expected crosswalk.json, found {files[0].name}"


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
