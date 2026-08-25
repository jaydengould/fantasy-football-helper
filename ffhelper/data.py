"""Fetching, caching, and joining of all external data into list[Player]."""
import json
import logging
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

    if path.exists() and (time.time() - path.stat().st_mtime) < ttl_seconds:
        return json.loads(path.read_text())

    try:
        text = fetcher(url)
    except Exception as exc:
        if path.exists():
            log.warning("fetch failed for %s (%s); using stale cache", cache_key, exc)
            return json.loads(path.read_text())
        raise

    path.write_text(text)
    return json.loads(text)
