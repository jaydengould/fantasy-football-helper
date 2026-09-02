"""ffhelper.board.board_state must agree with cli._render_tick, exactly.

board.py holds a COPY of the derivation in _render_tick. It was written as a
copy because cli.py was frozen for the 2026 drafts; the freeze lifted
2026-09-01 and the fold was deliberately deferred anyway -- board.py's docstring
carries the current reasoning and the trigger for taking it.
A copy that drifts from its original is this project's signature failure --
Task 13 defects #1, #3 and #6 were all one component disagreeing with another
about who had been drafted. This test is what makes the copy safe.
"""
from dataclasses import dataclass

from ffhelper.board import board_state
from ffhelper.config import League, Tunables
from ffhelper.data import LeagueSettings, Player
from ffhelper import cli


@dataclass
class FakePick:
    sleeper_id: str
    pick_no: int
    draft_slot: int | None


def _pool() -> dict[str, Player]:
    # Deliberately NOT round numbers or a four-player pool: fixtures chosen for
    # arithmetic convenience are what hid seven of this project's defects.
    pool = {}
    for i in range(1, 61):
        pos = ["QB", "RB", "WR", "TE", "K", "DEF"][i % 6]
        pool[str(i)] = Player(
            sleeper_id=str(i), name=f"Player {i}", position=pos, team="KC",
            proj_pts=320.4 - i * 3.7, adp=float(i) + 0.6, adp_stdev=6.3 + i * 0.11,
            bye=(i % 14) + 1,
        )
    return pool


def _settings() -> LeagueSettings:
    return LeagueSettings(
        num_teams=12,
        scoring={"rec": 1.0, "pass_td": 6.0},
        roster_slots={"QB": 1, "RB": 2, "WR": 2, "TE": 1, "FLEX": 2, "K": 1, "DEF": 1},
        rounds=15,
    )


def test_board_state_matches_render_tick(monkeypatch):
    players = _pool()
    settings = _settings()
    league = League(name="t", platform="sleeper", league_id="1", draft_slot=5)
    tunables = Tunables()
    picks = [FakePick("3", 1, 1), FakePick("7", 2, 5), FakePick("11", 3, 9)]
    manual_gone = {"3", "7", "11", "20", "21"}
    manual_mine = {"20"}

    captured = {}

    def fake_render(board, limit, stale_seconds, my_roster, runs, divergence_flag_slots=10):
        captured["board"] = board
        captured["my_roster"] = my_roster
        captured["runs"] = runs
        return ""

    monkeypatch.setattr(cli, "render", fake_render)
    cli._render_tick(
        picks, None, players, settings, league, tunables, 20,
        manual_gone, manual_mine, league.draft_slot, "",
    )

    state = board_state(players, picks, manual_gone, manual_mine,
                        settings, league, tunables)

    assert state.board == captured["board"]
    assert state.my_roster == captured["my_roster"]
    assert state.runs == captured["runs"]


def test_board_state_agrees_when_a_claim_is_overruled(monkeypatch):
    # The path most likely to drift: the feed contradicting a self-mark.
    players = _pool()
    settings = _settings()
    league = League(name="t", platform="sleeper", league_id="1", draft_slot=5)
    tunables = Tunables()
    picks = [FakePick("20", 1, 9)]          # seat 9 took the player claimed as ours
    manual_gone = {"20"}
    manual_mine = {"20"}

    captured = {}
    monkeypatch.setattr(
        cli, "render",
        lambda board, limit, stale, my_roster, runs, div=10: captured.update(
            board=board, my_roster=my_roster) or "",
    )
    cli._render_tick(picks, None, players, settings, league, tunables, 20,
                     manual_gone, manual_mine, league.draft_slot, "")

    state = board_state(players, picks, manual_gone, manual_mine,
                        settings, league, tunables)

    assert state.overruled == {"20"}
    assert state.my_roster == captured["my_roster"] == []
    assert state.board == captured["board"]
