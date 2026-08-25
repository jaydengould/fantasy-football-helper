from ffhelper.feeds import Pick, parse_sleeper_picks


def test_parses_picks_in_order():
    raw = [
        {"pick_no": 2, "player_id": "8155", "roster_id": 4},
        {"pick_no": 1, "player_id": "9221", "roster_id": 10},
    ]
    picks = parse_sleeper_picks(raw)
    assert [p.pick_no for p in picks] == [1, 2]
    assert picks[0] == Pick(pick_no=1, sleeper_id="9221", roster_id=10)


def test_skips_picks_without_a_player():
    """A pick object can exist before the player is assigned."""
    raw = [
        {"pick_no": 1, "player_id": "9221", "roster_id": 10},
        {"pick_no": 2, "player_id": None, "roster_id": 4},
    ]
    assert len(parse_sleeper_picks(raw)) == 1


def test_empty_draft_returns_empty_list():
    assert parse_sleeper_picks([]) == []
