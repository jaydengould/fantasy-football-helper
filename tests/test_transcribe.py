"""Transcribing a finished draft board into a journal.

Fixtures are the REAL shape of Yahoo's results page, taken from a completed
12-team mock, not a convenient invention -- test fixtures chosen for arithmetic
convenience are this project's most repeated source of defects.

This path runs with no clock on it, so it can be strict where the live board
cannot: a row it cannot resolve to exactly one player is refused, never guessed
and never dropped.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from calibrate import room_discipline
from ffhelper.data import Player
from transcribe import parse_board, parse_line, resolve


def _p(pid, name, position, team="BUF", adp=100.0):
    return Player(sleeper_id=pid, name=name, position=position, team=team,
                  proj_pts=100.0, adp=adp)


POOL = {
    "1": _p("1", "Bijan Robinson", "RB", "ATL"),
    "2": _p("2", "Brian Robinson", "RB", "ATL"),
    "3": _p("3", "James Cook", "RB", "BUF"),
    "4": _p("4", "Josh Allen", "QB", "BUF"),
    # Same position deliberately: position usually narrows, so a same-position
    # substring collision is the only thing exercising the exact-name rule.
    # A mutation check found that test passing vacuously.
    "5": _p("5", "Josh Allender", "QB", "BUF"),
    "6": _p("6", "Amon-Ra St. Brown", "WR", "DET"),
    "7": _p("7", "Demarcus Robinson", "WR", "SF"),
    "LAC": _p("LAC", "Los Angeles Chargers", "DEF", "LAC"),
    "LAR": _p("LAR", "Los Angeles Rams", "DEF", "LAR"),
}

# A complete two-team, two-round board in Yahoo's real row shape. Complete on
# purpose: the ordering check requires a full 1..N run, because the commonest
# copy-paste mistake is selecting only part of the page.
REAL_BOARD = """Round 1
(1) Jayden - Robinson, Bijan (Atl - RB)
(2) jeremy - St. Brown, Amon-Ra (Det - WR)

Round 2
(1) jeremy - Cook III, James (Buf - RB)
(2) Jayden - Los Angeles (LAC - DEF)
"""


def test_parses_yahoos_real_row_shape():
    """Manager name, surname-first player, then team and position."""
    assert parse_line("(1) mohamed - Gibbs, Jahmyr (Det - RB)") == (
        "Jahmyr Gibbs", "RB", "DET", "mohamed")


def test_a_trailing_suffix_moves_with_the_surname():
    """"Cook III, James" is James Cook III -- and `norm_name` strips the III to
    reach the pool's "James Cook". Reassembling it as "James III Cook" does not."""
    assert parse_line("(7) Christopher - Cook III, James (Buf - RB)")[0] == "James Cook III"
    assert parse_line("(6) Christopher - Samuel Sr., Deebo (SF - WR)")[0] == "Deebo Samuel Sr."
    assert parse_line("(10) Malik Moore - Brown, A.J. (NE - WR)")[0] == "A.J. Brown"


def test_a_defense_row_has_no_comma_and_keeps_its_city():
    assert parse_line("(4) Paul - Seattle (Sea - DEF)") == ("Seattle", "DEF", "SEA", "Paul")


def test_platform_position_spellings_survive_tokenising():
    """"D/ST" must not be split into "D" and "ST", which matches nothing and
    would leave the row with no position to disambiguate on."""
    assert parse_line("(4) Paul - Seattle (Sea - D/ST)") == ("Seattle", "DEF", "SEA", "Paul")
    assert parse_line("(7) Chris - Aubrey, Brandon (Dal - PK)")[1] == "K"


def test_a_column_header_row_is_not_a_pick():
    assert parse_line("Pick   Player   Team") is None


def test_a_row_without_a_manager_still_parses():
    assert parse_line("1. Ja'Marr Chase (Cin - WR)") == ("Ja'Marr Chase", "WR", "CIN", None)


def test_round_headers_and_blanks_are_not_picks():
    assert parse_line("Round 3") is None
    assert parse_line("   ") is None


def test_overall_pick_numbers_are_rebuilt_from_round_and_slot():
    picks, problems = parse_board(REAL_BOARD, num_teams=2)
    assert [p[0] for p in picks] == [1, 2, 3, 4]
    assert [p[1] for p in picks] == [
        "Bijan Robinson", "Amon-Ra St. Brown", "James Cook III", "Los Angeles"]
    assert problems == []


def test_rows_are_reordered_by_pick_number_not_by_where_they_appear():
    """A snake's even rounds run right-to-left, so a copy of the BOARD view
    arrives with round 2 reversed. Scoring that as written would invert every
    survival horizon in every even round -- but the numbers say the true order,
    so use them."""
    swapped = REAL_BOARD.replace(
        "(1) jeremy - Cook III, James (Buf - RB)\n(2) Jayden - Los Angeles (LAC - DEF)",
        "(2) Jayden - Los Angeles (LAC - DEF)\n(1) jeremy - Cook III, James (Buf - RB)")
    picks, problems = parse_board(swapped, num_teams=2)
    assert problems == []
    assert [p[0] for p in picks] == [1, 2, 3, 4]
    assert picks[2][1] == "James Cook III"          # pick 3, despite being listed last


def test_a_partial_copy_is_refused_rather_than_scored():
    """The commonest paste mistake is selecting only part of the page. Missing
    rows shift every pick number after them."""
    partial = REAL_BOARD.replace("(1) Jayden - Robinson, Bijan (Atl - RB)\n", "")
    _picks, problems = parse_board(partial, num_teams=2)
    assert problems and "not a complete 1..3 run" in problems[0]


def test_a_defense_joins_on_its_team_code_not_its_city():
    """The page writes "Los Angeles (LAC - DEF)" and there are TWO Los Angeles
    defenses. The city cannot pick between them; the team code is an identifier."""
    assert [p.name for p in resolve(POOL, "Los Angeles", "DEF", "LAC")] \
        == ["Los Angeles Chargers"]
    assert [p.name for p in resolve(POOL, "Los Angeles", "DEF", "LAR")] \
        == ["Los Angeles Rams"]


def test_a_defense_resolves_even_when_its_name_matches_nothing():
    """Defense naming is where platforms disagree most -- "LA Chargers",
    "Chargers", "Los Angeles Chargers". The team code is the only identifier
    that survives that, so it alone must be enough.

    Without this, the team-code branch looks redundant: plain name matching plus
    team narrowing already handles "Los Angeles". A mutation check showed the
    branch could be deleted with every other test still green.
    """
    assert [p.name for p in resolve(POOL, "LA Chargers", "DEF", "LAC")] \
        == ["Los Angeles Chargers"]


def test_position_narrows_where_the_name_cannot():
    assert len(resolve(POOL, "Robinson", None, None)) == 3        # refuses to choose
    assert [p.name for p in resolve(POOL, "Robinson", "WR", "SF")] == ["Demarcus Robinson"]
    # ...and where it still cannot narrow to one, it still refuses: Bijan and
    # Brian are both ATL RBs, which is the case non-negotiable #1 names.
    assert len(resolve(POOL, "Robinson", "RB", "ATL")) == 2


def test_an_exact_name_beats_a_substring_match():
    """"Josh Allen" is a substring of "Josh Allender", same position, same team."""
    assert [p.name for p in resolve(POOL, "Josh Allen", "QB", "BUF")] == ["Josh Allen"]


def test_unresolvable_name_returns_nothing_rather_than_a_guess():
    assert resolve(POOL, "Nobody At All", None, None) == []


def test_room_discipline_flags_a_room_drafting_straight_down_the_list():
    """A bot room takes the top available every time: median rank 1, 100% at top.
    This is the check that stops a beautiful, circular calibration being believed."""
    pool = {str(i): _p(str(i), f"P{i}", "RB", adp=float(i)) for i in range(1, 11)}
    in_adp_order = {str(i): i for i in range(1, 11)}
    assert room_discipline(pool, in_adp_order) == (1, 1.0, 10)


def test_room_discipline_reports_a_room_that_ignores_the_list():
    """Reverse order: every pick is the worst player still available.

    `at_top` is 1/10, not 0: the LAST pick of any completed draft is trivially
    the top of what remains, because it is all that remains. Worth knowing that
    floor before reading a real number off a finished board.
    """
    pool = {str(i): _p(str(i), f"P{i}", "RB", adp=float(i)) for i in range(1, 11)}
    reversed_order = {str(i): 11 - i for i in range(1, 11)}
    median, at_top, scored = room_discipline(pool, reversed_order)
    assert at_top == 0.1 and median > 2 and scored == 10
