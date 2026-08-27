from dataclasses import dataclass

import pytest

from ffhelper.board import board_state
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
