import json
from dataclasses import dataclass

import pytest

from ffhelper.board import auto_mine, board_state, marks_in_entry_order, my_turns
from ffhelper.config import League, Tunables
from ffhelper.data import LeagueSettings, Player


@dataclass
class FakePick:
    sleeper_id: str
    pick_no: int
    draft_slot: int | None


def _pool(n: int = 40) -> dict[str, Player]:
    return {
        str(i): Player(
            sleeper_id=str(i), name=f"Player {i}",
            position=["QB", "RB", "WR", "TE", "K", "DEF"][i % 6], team="KC",
            proj_pts=310.2 - i * 4.1, adp=float(i) + 1.4, adp_stdev=5.9 + i * 0.13,
        )
        for i in range(1, n + 1)
    }


def _settings(num_teams: int = 12) -> LeagueSettings:
    return LeagueSettings(
        num_teams=num_teams, scoring={"rec": 1.0},
        roster_slots={"QB": 1, "RB": 2, "WR": 2, "TE": 1, "FLEX": 2, "K": 1, "DEF": 1},
        rounds=15,
    )


def _league(slot: int | None = 5) -> League:
    return League(name="t", platform="sleeper", league_id="1", draft_slot=slot)


def test_current_pick_counts_manual_marks_when_there_is_no_feed():
    # Manual mode: picks is permanently empty. A count derived from `picks`
    # freezes the board at pick 1 for a whole draft -- Task 13 defect, and it
    # invalidates every survival and VONA number on every tick.
    state = board_state(_pool(), [], {"1", "2", "3", "4"}, set(),
                        _settings(), _league(), Tunables())
    assert state.current_pick == 5


def test_current_pick_prefers_the_feeds_highest_pick_no():
    # parse_sleeper_picks drops malformed rows, so len(picks) can understate
    # how far the draft has actually gone.
    picks = [FakePick("1", 1, 1), FakePick("2", 7, 7)]
    state = board_state(_pool(), picks, set(), set(),
                        _settings(), _league(), Tunables())
    assert state.current_pick == 8


def test_drafted_players_leave_the_available_pool():
    state = board_state(_pool(), [], {"3"}, set(), _settings(), _league(), Tunables())
    assert all(r.player.sleeper_id != "3" for r in state.board)


def test_a_player_reported_by_both_feed_and_mark_is_counted_once():
    picks = [FakePick("1", 1, 1)]
    state = board_state(_pool(), picks, {"1"}, set(),
                        _settings(), _league(), Tunables())
    assert state.current_pick == 2


def test_replacement_level_uses_the_full_pool_not_the_draining_one():
    # _pool(40) has six QBs (i = 6, 12, 18, 24, 30, 36); a 1-QB, 12-team league
    # (flex_share QB=0.0) wants replacement rank 12, which clamps to the 6th
    # (last, lowest-proj_pts) QB -- player "36". Drafting that exact player
    # away must NOT move the baseline: replacement level is a property of the
    # league's full pool, not of who happens to still be on the board. Using
    # `available` instead gave a backup QB a VBD of +149.0 in the Task 13 mock.
    pool = _pool()
    manual_gone = {"36"}
    state = board_state(pool, [], manual_gone, set(), _settings(), _league(), Tunables())
    row6 = next(r for r in state.board if r.player.sleeper_id == "6")
    expected_repl = pool["36"].proj_pts        # still the baseline, though drafted
    assert row6.vbd == pytest.approx(pool["6"].proj_pts - expected_repl)


def test_my_turns_are_the_seats_snake_positions():
    assert my_turns(seat=5, num_teams=12, through_pick=30) == [5, 20, 29]


def test_my_turns_at_the_turn_are_back_to_back():
    # Seat 12 in a 12-team snake picks 12 and 13 with nobody in between. The
    # board's whole thesis -- cost of waiting -- collapses if this is wrong.
    assert my_turns(seat=12, num_teams=12, through_pick=26) == [12, 13]


def test_auto_mine_claims_only_the_seats_own_picks():
    order = [str(i) for i in range(1, 25)]           # picks 1..24, entered in order
    assert auto_mine(order, seat=5, num_teams=12) == {"5", "20"}


def test_auto_mine_with_no_seat_claims_nothing():
    # Degrade, never fabricate: an unset draft_slot must not guess a roster.
    order = [str(i) for i in range(1, 25)]
    assert auto_mine(order, seat=None, num_teams=12) == set()


def test_marks_in_entry_order_excludes_undone_and_taken_back_marks(tmp_path):
    path = tmp_path / "log.jsonl"
    ops = [
        {"op": "mark", "id": "a", "mine": False},
        {"op": "mark", "id": "b", "mine": False},
        {"op": "undo"},                               # takes back b
        {"op": "mark", "id": "c", "mine": False},
        {"op": "mark", "id": "d", "mine": False},
        {"op": "unmark", "id": "d"},
    ]
    path.write_text("".join(json.dumps(o) + "\n" for o in ops))
    assert marks_in_entry_order(path) == ["a", "c"]


def test_a_missed_pick_shifts_attribution_by_one(tmp_path):
    # Recorded deliberately: this is the COST of auto-attribution, and the
    # reason the on-clock banner doubles as a drift detector. If this test ever
    # starts failing, attribution has silently changed behaviour.
    order = [str(i) for i in range(1, 25)]
    assert auto_mine(order, seat=5, num_teams=12) == {"5", "20"}
    assert auto_mine(order[1:], seat=5, num_teams=12) == {"6", "21"}
