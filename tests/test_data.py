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
