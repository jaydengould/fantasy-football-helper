import json
from pathlib import Path

import pytest

from ffhelper.data import fetch_json


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
