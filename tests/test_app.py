import time
from dataclasses import dataclass

import ffhelper.app as app
from ffhelper.app import banner_lines, board_rows, clock_line, read_state
from ffhelper.board import board_state
from ffhelper.config import League, Tunables
from ffhelper.data import LeagueSettings, Player


@dataclass
class FakePick:
    sleeper_id: str
    pick_no: int
    draft_slot: int | None


class FakeFeed:
    """No network, no mocking library -- a feed is just something with get_picks()."""

    def __init__(self, picks=None, raise_error=False):
        self._picks = picks if picks is not None else []
        self._raise_error = raise_error

    def get_picks(self):
        if self._raise_error:
            raise RuntimeError("feed down")
        return self._picks


def _pool(n: int = 40) -> dict[str, Player]:
    return {
        str(i): Player(
            sleeper_id=str(i), name=f"Player {i}",
            position=["QB", "RB", "WR", "TE", "K", "DEF"][i % 6], team="KC",
            proj_pts=310.2 - i * 4.1, adp=float(i) + 1.4, adp_stdev=5.9 + i * 0.13,
            bye=(i % 14) + 1,
        )
        for i in range(1, n + 1)
    }


def _settings() -> LeagueSettings:
    return LeagueSettings(
        num_teams=12, scoring={"rec": 1.0},
        roster_slots={"QB": 1, "RB": 2, "WR": 2, "TE": 1, "FLEX": 2, "K": 1, "DEF": 1},
        rounds=15,
    )


def _state(picks=(), gone=frozenset(), mine=frozenset(), players=None):
    players = players or _pool()
    return board_state(players, list(picks), set(gone), set(mine), _settings(),
                       League(name="t", platform="sleeper", league_id="1", draft_slot=5),
                       Tunables()), players


def test_board_rows_carry_the_player_id_so_a_click_never_matches_on_name():
    # Non-negotiable #1: load-bearing joins are on integer ids. A click that
    # resolved a row back to a player by NAME would reintroduce the exact
    # ambiguity (Bijan vs Brian Robinson) the whole design forbids.
    #
    # IDs here are deliberately NOT derivable from the names (unlike _pool(),
    # where id str(i) and name f"Player {i}" share the same index and a
    # name-for-id swap in app.py would still leave every row "truthy and
    # unique"). Asserting the id against a KNOWN value is what makes the test
    # fail if app.py ever reads r.player.name instead of r.player.sleeper_id.
    players = {
        "4017": Player(sleeper_id="4017", name="Bijan Robinson", position="RB",
                       team="ATL", proj_pts=300.0, adp=3.0, adp_stdev=4.0, bye=5),
        "9911": Player(sleeper_id="9911", name="Brian Robinson", position="RB",
                       team="WAS", proj_pts=180.0, adp=90.0, adp_stdev=8.0, bye=14),
    }
    state, _ = _state(players=players)
    rows = board_rows(state, limit=2, divergence_flag_slots=10)
    by_name = {r["player"]: r["id"] for r in rows}
    assert by_name["Bijan Robinson"] == "4017"
    assert by_name["Brian Robinson"] == "9911"


def test_board_rows_respect_the_limit_and_are_ranked_from_one():
    state, _ = _state()
    rows = board_rows(state, limit=7, divergence_flag_slots=10)
    assert len(rows) == 7
    assert [r["rank"] for r in rows] == list(range(1, 8))


def test_unpriced_players_show_a_dash_not_a_fabricated_zero():
    # divergence is None for a player the market never priced -- a third of the
    # pool. No opinion is not agreement.
    players = _pool()
    for p in players.values():
        p.adp = 999.0
    state, _ = _state(players=players)
    rows = board_rows(state, limit=5, divergence_flag_slots=10)
    assert all(r["div"] == "-" for r in rows)


def test_a_dead_feed_produces_a_stale_banner():
    state, players = _state()
    lines = banner_lines(state, stale_seconds=42.0, players=players)
    assert any("STALE" in line for line in lines)


def test_no_feed_says_so_rather_than_showing_a_staleness_clock():
    state, players = _state()
    lines = banner_lines(state, stale_seconds=None, players=players)
    assert any("MANUAL MODE" in line for line in lines)
    assert not any("STALE" in line for line in lines)


def test_an_overruled_claim_raises_a_standing_banner_naming_the_player():
    players = _pool()
    picks = [FakePick("20", 1, 9)]
    state, players = _state(picks=picks, gone={"20"}, mine={"20"}, players=players)
    lines = banner_lines(state, stale_seconds=None, players=players)
    assert any("CLAIM OVERRULED" in line and "Player 20" in line for line in lines)


# --- read_state: the safety property (a feed that never worked must not
# render as healthy) lives entirely in this function, and nothing above
# exercises it -- every test above hand-supplies stale_seconds. ---

def test_read_state_with_no_feed_stays_stale_none_even_when_get_picks_returns(
    monkeypatch, tmp_path,
):
    # Yahoo has no feed at all. That is a different statement from "the feed
    # has not answered recently" and must never collapse into a number, even
    # if whatever `feed` object was wired up happens to return an empty list.
    monkeypatch.setattr(app, "_draft_log_path", lambda league: tmp_path / "j.jsonl")
    league = League(name="rs-no-feed", platform="yahoo", league_id="1", draft_slot=5)
    state, stale = read_state(league, Tunables(), _pool(), _settings(),
                              FakeFeed(picks=[]), has_feed=False)
    assert stale is None


def test_read_state_successful_poll_reports_zero_stale(monkeypatch, tmp_path):
    monkeypatch.setattr(app, "_draft_log_path", lambda league: tmp_path / "j.jsonl")
    league = League(name="rs-ok", platform="sleeper", league_id="1", draft_slot=5)
    state, stale = read_state(league, Tunables(), _pool(), _settings(),
                              FakeFeed(picks=[]), has_feed=True)
    assert stale == 0.0


def test_read_state_failed_poll_reports_real_elapsed_never_a_fabricated_zero(
    monkeypatch, tmp_path,
):
    # The "feed that never worked" case, and the one that matters most: a
    # dead feed must show a real, growing staleness number, never 0.0 (which
    # reads as "just synced") and never None (which reads as "no feed at
    # all" -- also false, this league HAS a feed, it is just down).
    monkeypatch.setattr(app, "_draft_log_path", lambda league: tmp_path / "j.jsonl")
    league = League(name="rs-dead", platform="sleeper", league_id="1", draft_slot=5)
    # Mirrors what main()'s cache() does at load, before the first poll ever
    # runs: seed the clock so a feed that has never succeeded still reports
    # real elapsed time instead of "now minus now".
    app._LAST_OK[league.name] = time.time() - 5.0
    state, stale = read_state(league, Tunables(), _pool(), _settings(),
                              FakeFeed(raise_error=True), has_feed=True)
    assert stale is not None
    assert stale != 0.0
    assert stale >= 4.5


# --- clock_line: the ON THE CLOCK banner. Task 6 makes this the drift
# detector for seat-based roster attribution, so its snake-position logic
# needs coverage now, not after that lands on top of it. ---

def test_clock_line_says_yours_only_at_the_seats_snake_pick():
    # slot 5, 12 teams -> this seat's picks are 5, 8, 29, 32, ... The banner
    # must fire exactly on pick 5 and on neither neighbour.
    league = League(name="clock-test", platform="sleeper", league_id="1", draft_slot=5)
    settings = _settings()
    for gone_count, expect_yours in [(3, False), (4, True), (5, False)]:
        gone = {str(i) for i in range(1, gone_count + 1)}
        state = board_state(_pool(), [], gone, set(), settings, league, Tunables())
        assert state.current_pick == gone_count + 1
        line = clock_line(state, league, settings.num_teams)
        assert ("YOURS" in line) == expect_yours, (state.current_pick, line)
