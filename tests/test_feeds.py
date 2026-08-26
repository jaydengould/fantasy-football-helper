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

    assert calls == ["https://api.sleeper.app/v1/draft/draft123/picks"]
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
