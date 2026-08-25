"""Fetching, caching, and joining of all external data into list[Player]."""
import json
import logging
import os
import tempfile
import time
from pathlib import Path
from typing import Any, Callable

import requests

log = logging.getLogger(__name__)

CACHE_DIR = Path(__file__).resolve().parent.parent / ".cache"
TIMEOUT_SECONDS = 5


def _requests_get(url: str) -> str:
    resp = requests.get(url, timeout=TIMEOUT_SECONDS)
    resp.raise_for_status()
    return resp.text


def fetch_json(
    url: str,
    cache_key: str,
    ttl_seconds: int = 86_400,
    cache_dir: Path = CACHE_DIR,
    fetcher: Callable[[str], str] | None = None,
) -> Any:
    """Fetch JSON with a write-through disk cache and stale-on-failure fallback.

    Draft night depends on this: a failed refresh must degrade to stale data,
    never to an exception, whenever any cached copy exists.
    """
    fetcher = fetcher or _requests_get
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / f"{cache_key}.json"

    # Fresh cache path: try to load if within TTL.
    if path.exists() and (time.time() - path.stat().st_mtime) < ttl_seconds:
        try:
            return json.loads(path.read_text())
        except Exception as e:
            log.warning("corrupt cache for %s (%s); refetching", cache_key, e)
            # Fall through to fetch fresh data below.

    # Fetch fresh data.
    try:
        text = fetcher(url)
    except Exception as exc:
        # Stale fallback: if fetch fails and cache exists, use it despite corruption risk.
        if path.exists():
            try:
                log.warning("fetch failed for %s (%s); using stale cache", cache_key, exc)
                return json.loads(path.read_text())
            except Exception:
                # Cache is corrupt; re-raise the original fetch exception.
                log.warning("stale cache also corrupt for %s; raising original fetch error", cache_key)
                raise exc
        raise

    # Write cache atomically: write to temp file, then replace.
    fd = None
    tmp_path = None
    try:
        fd, tmp_path = tempfile.mkstemp(dir=cache_dir, prefix=cache_key, suffix=".json")
        os.write(fd, text.encode("utf-8"))
        os.close(fd)
        fd = None
        os.replace(tmp_path, path)
    except Exception:
        if fd is not None:
            os.close(fd)
        if tmp_path and Path(tmp_path).exists():
            Path(tmp_path).unlink()
        raise

    return json.loads(text)
