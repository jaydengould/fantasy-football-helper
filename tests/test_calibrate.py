"""Scoring a HAND-ENTERED draft. Yahoo has no pick feed, so the human mock's
only record is the manual-entry journal, and its pick ORDER is reconstructed
rather than read. These cover that reconstruction and the completeness check
that decides whether the reconstruction can be trusted at all.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import pytest

from calibrate import (
    LEAGUE_FROM_LOG, load_draft, parse_draft_args, picks_from_journal, snake_turns,
)


def write_log(tmp_path: Path, ops: list[dict]) -> Path:
    path = tmp_path / "yahoo-mock-2026-08-26.jsonl"
    path.write_text("".join(json.dumps(op) + "\n" for op in ops), encoding="utf-8")
    return path


def test_journal_order_is_pick_order(tmp_path):
    path = write_log(tmp_path, [
        {"op": "mark", "id": "a", "mine": False},
        {"op": "mark", "id": "b", "mine": True},
        {"op": "mark", "id": "c", "mine": False},
    ])
    drafted_at, my_turns = picks_from_journal(path)
    assert drafted_at == {"a": 1, "b": 2, "c": 3}
    assert my_turns == [2]


def test_taken_back_marks_do_not_consume_a_pick_number(tmp_path):
    """`-name` and `u` remove a player from the board, so they must also remove
    him from the pick numbering -- otherwise every pick after a correction is
    off by one and every survival horizon shifts with it."""
    path = write_log(tmp_path, [
        {"op": "mark", "id": "a", "mine": False},
        {"op": "mark", "id": "wrong", "mine": False},
        {"op": "unmark", "id": "wrong"},
        {"op": "mark", "id": "b", "mine": False},
        {"op": "mark", "id": "slip", "mine": False},
        {"op": "undo"},
        {"op": "mark", "id": "c", "mine": True},
    ])
    drafted_at, my_turns = picks_from_journal(path)
    assert drafted_at == {"a": 1, "b": 2, "c": 3}
    assert my_turns == [3]


def test_corrupt_final_line_costs_only_itself(tmp_path):
    path = write_log(tmp_path, [{"op": "mark", "id": "a", "mine": False}])
    with path.open("a", encoding="utf-8") as fh:
        fh.write('{"op": "mark", "id": "b"')            # killed mid-write
    drafted_at, _ = picks_from_journal(path)
    assert drafted_at == {"a": 1}


def test_snake_turns_reverse_on_even_rounds():
    assert snake_turns(1, 12, 36) == [1, 24, 25]
    assert snake_turns(12, 12, 36) == [12, 13, 36]
    assert snake_turns(5, 12, 30) == [5, 20, 29]
    assert snake_turns(5, 12, 4) == []                  # draft shorter than one round


def write_marks(tmp_path: Path, name: str, mine_at: list[int], total: int) -> Path:
    path = tmp_path / name
    path.write_text("".join(
        json.dumps({"op": "mark", "id": f"p{i}", "mine": i in mine_at}) + "\n"
        for i in range(1, total + 1)), encoding="utf-8")
    return path


def test_the_seat_is_read_out_of_the_journal_not_asked_for(tmp_path):
    """Your own picks are recorded in the log, and in a snake the first of them
    IS your seat. Asking for it again is how the first real transcript got
    scored against another manager -- the argument and config.toml disagreed."""
    path = write_marks(tmp_path, "lg-2026-08-26-a.jsonl", mine_at=[2, 3], total=4)
    drafted_at, turns, slot = load_draft(path, num_teams=2, slot_override=None)
    assert slot == 2
    assert len(drafted_at) == 4
    # One evaluation per CONSECUTIVE PAIR of turns: stand at turn 2, ask what
    # survives to turn 3. The last turn is dropped -- nothing follows it -- and
    # the first is NOT repeated, which is the bug this pins.
    assert turns == [2]


def test_a_log_that_does_not_fit_the_snake_is_refused(tmp_path):
    """A missed pick shifts every number after it, moving every survival
    horizon. Better no answer than a flattering one over a drifted log."""
    path = write_marks(tmp_path, "lg-2026-08-26-a.jsonl", mine_at=[1, 3], total=4)
    with pytest.raises(ValueError, match="does not line up with seat 1"):
        load_draft(path, num_teams=2, slot_override=None)


def test_a_log_with_no_claimed_picks_is_refused(tmp_path):
    path = write_marks(tmp_path, "lg-2026-08-26-a.jsonl", mine_at=[], total=4)
    with pytest.raises(ValueError, match="no picks are marked as yours"):
        load_draft(path, num_teams=2, slot_override=None)


def test_league_name_survives_any_tag_after_the_date():
    """Transcripts are named after their input file so several drafts can be
    scored in one day, so the league is whatever precedes the date."""
    for stem, expected in [
        ("yahoo-mock-2026-08-26", "yahoo-mock"),
        ("yahoo-mock-2026-08-26-results2", "yahoo-mock"),
        ("yahoo-mock-2026-08-26-transcript", "yahoo-mock"),
        ("sleeper-main-2026-09-06-x-y", "sleeper-main"),
    ]:
        assert LEAGUE_FROM_LOG.match(stem).group("league") == expected


def test_the_first_turn_is_scored_once_not_twice(tmp_path):
    """`[my_turns[0]] + my_turns[:-1]` duplicated the first turn and dropped the
    last. The first turn is the earliest board state, where survival is most
    extreme, so the duplicate skewed every pooled table it appeared in."""
    # Four teams, four rounds: seat 1 owns 1, 8, 9, 16.
    path = write_marks(tmp_path, "lg-2026-08-26-a.jsonl", mine_at=[1, 8, 9, 16], total=16)
    _drafted, turns, slot = load_draft(path, num_teams=4, slot_override=None)
    assert slot == 1
    assert turns == [1, 8, 9]           # not [1, 1, 8, 9]; 16 has no next pick
    assert turns.count(turns[0]) == 1


def test_a_numeric_sleeper_draft_id_is_not_mistaken_for_the_seat():
    """Every Sleeper draft id is all digits, so an isdecimal() split files it
    with the slot. That is what happened: `calibrate.py <id> <slot>` raised
    IndexError, and `<id> <slot> <league>` fetched the LEAGUE NAME as a draft
    id while scoring the real id as the seat number. Both silent until run.
    """
    assert parse_draft_args(["1399171308415102976", "5"]) == (
        "1399171308415102976", 5, "sleeper-main")
    # The regression exactly: the id must never end up in the slot.
    _id, slot, _lg = parse_draft_args(["1399171308415102976", "5"])
    assert slot == 5


def test_an_explicit_league_is_read_from_the_third_slot_not_guessed():
    assert parse_draft_args(["1399171308415102976", "5", "sleeper-mock"]) == (
        "1399171308415102976", 5, "sleeper-mock")


def test_a_malformed_draft_invocation_prints_usage_rather_than_crashing():
    assert parse_draft_args(["1399171308415102976"]) is None
    assert parse_draft_args([]) is None
    assert parse_draft_args(["1399171308415102976", "five"]) is None
