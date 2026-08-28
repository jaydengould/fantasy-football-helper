import json
from pathlib import Path

import pytest

from ffhelper.feeds import Pick, SleeperFeed, parse_sleeper_picks


def test_parses_picks_in_order():
    raw = [
        {"pick_no": 2, "player_id": "8155", "roster_id": 4},
        {"pick_no": 1, "player_id": "9221", "roster_id": 10},
    ]
    picks = parse_sleeper_picks(raw)
    assert [p.pick_no for p in picks] == [1, 2]
    assert picks[0] == Pick(pick_no=1, sleeper_id="9221", roster_id=10)


def test_parses_draft_slot_including_when_roster_id_is_null():
    """A real row from the Task 13 mock. Sleeper mock drafts set `roster_id` to
    None on EVERY pick while populating `draft_slot` normally -- which is why
    my_roster is matched on draft_slot. If the parser drops draft_slot, the
    whole roster resolution silently returns nothing, exactly as it did for a
    full 180-pick draft.
    """
    raw = [{"pick_no": 5, "player_id": "4034", "roster_id": None, "draft_slot": 5,
            "round": 1, "picked_by": ""}]
    pick = parse_sleeper_picks(raw)[0]
    assert pick.draft_slot == 5
    assert pick.roster_id is None


def test_draft_slot_is_none_when_the_row_omits_it():
    raw = [{"pick_no": 1, "player_id": "9221", "roster_id": 10}]
    assert parse_sleeper_picks(raw)[0].draft_slot is None


def test_skips_picks_without_a_player():
    """A pick object can exist before the player is assigned."""
    raw = [
        {"pick_no": 1, "player_id": "9221", "roster_id": 10},
        {"pick_no": 2, "player_id": None, "roster_id": 4},
    ]
    assert len(parse_sleeper_picks(raw)) == 1


def test_empty_draft_returns_empty_list():
    assert parse_sleeper_picks([]) == []


def test_skips_row_with_non_numeric_pick_no():
    raw = [
        {"pick_no": 1, "player_id": "9221", "roster_id": 10},
        {"pick_no": "not-a-number", "player_id": "8155", "roster_id": 4},
        {"pick_no": 2, "player_id": "3333", "roster_id": 6},
    ]
    picks = parse_sleeper_picks(raw)
    assert [p.pick_no for p in picks] == [1, 2]


def test_skips_row_with_missing_pick_no():
    raw = [
        {"player_id": "9221", "roster_id": 10},
        {"pick_no": 1, "player_id": "3333", "roster_id": 6},
    ]
    picks = parse_sleeper_picks(raw)
    assert [p.pick_no for p in picks] == [1]


def test_skips_row_with_empty_player_id():
    raw = [
        {"pick_no": 1, "player_id": "9221", "roster_id": 10},
        {"pick_no": 2, "player_id": "", "roster_id": 4},
    ]
    picks = parse_sleeper_picks(raw)
    assert [p.pick_no for p in picks] == [1]


def test_sorted_by_pick_no_with_a_bad_row_mixed_in():
    raw = [
        {"pick_no": 3, "player_id": "5555", "roster_id": 1},
        {"pick_no": None, "player_id": "6666", "roster_id": 2},
        {"pick_no": 1, "player_id": "9221", "roster_id": 10},
        {"pick_no": "bad", "player_id": "7777", "roster_id": 3},
    ]
    picks = parse_sleeper_picks(raw)
    assert [p.pick_no for p in picks] == [1, 3]


def test_sleeper_feed_calls_fetcher_with_formatted_url_and_returns_picks(tmp_path: Path):
    calls = []

    def fake(url: str) -> str:
        calls.append(url)
        return json.dumps([
            {"pick_no": 1, "player_id": "9221", "roster_id": 10},
        ])

    feed = SleeperFeed("draft123", fetcher=fake, cache_dir=tmp_path)
    picks = feed.get_picks()

    # The draft id must reach the URL; the trailing `?_=<ms>` is the CDN
    # cache-buster (see test_each_picks_poll_uses_a_fresh_url_to_defeat_the_cdn),
    # so this pins the path and leaves the query string to that test.
    assert len(calls) == 1
    path, _, query = calls[0].partition("?")
    assert path == "https://api.sleeper.app/v1/draft/draft123/picks"
    assert query.startswith("_=")
    assert picks == [Pick(pick_no=1, sleeper_id="9221", roster_id=10)]


def test_sleeper_feed_never_serves_picks_from_cache(tmp_path: Path):
    """Regression guard for ttl_seconds=0. If SleeperFeed.get_picks stopped passing
    ttl_seconds=0 to fetch_json, the default 24h TTL would apply and the second
    call below would be served from the on-disk cache written by the first call
    instead of invoking the fetcher again -- calls would be 1, not 2, and this
    test would fail."""
    calls = []

    def fake(url: str) -> str:
        calls.append(url)
        return json.dumps([{"pick_no": len(calls), "player_id": "9221", "roster_id": 10}])

    feed = SleeperFeed("draft123", fetcher=fake, cache_dir=tmp_path)
    feed.get_picks()
    feed.get_picks()

    assert len(calls) == 2


def test_sleeper_feed_raises_on_a_failed_poll_instead_of_replaying_the_cache(tmp_path: Path):
    """A dead feed must reach the caller as an exception so the STALE banner can
    fire. Serving the previous poll's picks is indistinguishable from a healthy
    draft where nobody has picked yet.

    Against the pre-fix code -- `fetch_json` with its default stale-on-failure
    fallback -- the second call returns the first call's picks and this test
    fails with no exception raised.
    """
    calls = []

    def flaky(url: str) -> str:
        calls.append(url)
        if len(calls) == 1:
            return json.dumps([{"pick_no": 1, "player_id": "9221", "roster_id": 10}])
        raise ConnectionError("wifi dropped")

    feed = SleeperFeed("draft123", fetcher=flaky, cache_dir=tmp_path)
    assert len(feed.get_picks()) == 1
    with pytest.raises(ConnectionError):
        feed.get_picks()


def test_sleeper_feed_empty_draft_returns_empty_list(tmp_path: Path):
    feed = SleeperFeed("draft123", fetcher=lambda url: "[]", cache_dir=tmp_path)
    assert feed.get_picks() == []


def test_each_picks_poll_uses_a_fresh_url_to_defeat_the_cdn(tmp_path, monkeypatch):
    """Sleeper fronts the picks endpoint with Cloudflare at s-maxage=86400, so
    two identical URLs are answered from the edge cache -- measured as
    cf-cache-status HIT with `age` climbing across consecutive polls, which is
    the board running seconds behind the draft. A `Cache-Control: no-cache`
    request header is ignored by their edge; a unique query param is not.
    """
    seen: list[str] = []

    def fake(url: str) -> str:
        seen.append(url)
        return "[]"

    import time as _time

    feed = SleeperFeed("999", fetcher=fake, cache_dir=tmp_path)
    # Patch the shared stdlib module, not a dotted path through ffhelper.feeds:
    # pre-fix that module does not import time at all, and the test would fail
    # on ImportError rather than on the behaviour it is meant to pin.
    #
    # Move the clock FORWARD from the real now. `fetch_json(ttl_seconds=0)`
    # decides freshness as `(time.time() - st_mtime) >= 0`, so a clock frozen
    # at some small constant makes that age hugely negative and fakes a cache
    # hit -- the local cache is not stale in production, only under a rewound
    # test clock.
    now = [_time.time() + 10.0]
    monkeypatch.setattr(_time, "time", lambda: now[0])
    feed.get_picks()
    now[0] += 1.0
    feed.get_picks()

    assert len(seen) == 2
    assert all(u.startswith("https://api.sleeper.app/v1/draft/999/picks?") for u in seen)
    # The whole point: two polls must never present the CDN with one key.
    assert seen[0] != seen[1]


def test_the_picks_cache_key_does_not_grow_with_the_busted_url(tmp_path, monkeypatch):
    """The URL varies per poll; the local cache NAME must not, or a long draft
    litters .cache/ with one file per second.

    The clock must advance between polls. Without that all three land in the
    same millisecond, a cache key built from that millisecond is identical
    anyway, and the test passes against the very bug it exists to catch --
    which is exactly what mutate.py reported.
    """
    import time as _time

    def fake(url: str) -> str:
        return "[]"

    feed = SleeperFeed("999", fetcher=fake, cache_dir=tmp_path)
    now = [_time.time() + 10.0]
    monkeypatch.setattr(_time, "time", lambda: now[0])
    for _ in range(3):
        feed.get_picks()
        now[0] += 1.0
    assert len(list(tmp_path.glob("picks_*"))) == 1
