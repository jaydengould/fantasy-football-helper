"""The snapshot table. The only stateful module, so the only tests that touch
a database -- and they use `:memory:` or tmp_path, never the real season.db."""
import sqlite3

import pytest

from ffhelper.store import connect, write_snapshot


def _row(player_id, proj_pts=12.5, matchup=None, status=None, started=1, taken_at="2026-09-08T10:00:00"):
    return {"player_id": player_id, "taken_at": taken_at, "proj_pts": proj_pts,
            "matchup": matchup, "status": status, "started": started}


def test_connect_creates_the_table_and_is_safe_to_call_twice(tmp_path):
    """`CREATE TABLE IF NOT EXISTS`: the second run of `lineup` in a week must
    not fail because the first one already made the table."""
    path = tmp_path / "season.db"
    connect(path).close()
    conn = connect(path)
    names = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert "snapshot" in names


def test_write_snapshot_records_one_row_per_player_and_returns_the_count():
    conn = connect(":memory:")
    n = write_snapshot(conn, "sleeper-main", "2026", 1,
                       [_row("10"), _row("11", started=0)])
    assert n == 2
    got = conn.execute(
        "SELECT league, season, week, player_id, started FROM snapshot "
        "ORDER BY player_id").fetchall()
    assert got == [("sleeper-main", "2026", 1, "10", 1),
                   ("sleeper-main", "2026", 1, "11", 0)]


def test_a_second_run_in_the_same_week_overwrites_and_keeps_the_newer_view():
    """The chosen semantics: the record is the LAST look you took before
    kickoff, because late injury news is exactly what moves a lineup. A
    plain INSERT would raise on the primary key here instead."""
    conn = connect(":memory:")
    write_snapshot(conn, "sleeper-main", "2026", 1,
                   [_row("10", proj_pts=12.5, taken_at="TUE", started=1)])
    write_snapshot(conn, "sleeper-main", "2026", 1,
                   [_row("10", proj_pts=3.0, taken_at="SUN", started=0)])

    got = conn.execute(
        "SELECT taken_at, proj_pts, started FROM snapshot").fetchall()
    assert got == [("SUN", 3.0, 0)]


def test_the_same_player_in_two_leagues_is_two_rows_not_a_collision():
    """`league` is part of the key: both leagues roster the same players and
    score them under different rules, so one row per player would silently
    throw one league's record away."""
    conn = connect(":memory:")
    write_snapshot(conn, "sleeper-main", "2026", 1, [_row("10", proj_pts=24.4)])
    write_snapshot(conn, "yahoo-main", "2026", 1, [_row("10", proj_pts=31.2)])
    got = conn.execute(
        "SELECT league, proj_pts FROM snapshot ORDER BY league").fetchall()
    assert got == [("sleeper-main", 24.4), ("yahoo-main", 31.2)]


def test_an_unprojected_player_round_trips_as_NULL_and_not_as_zero():
    """The load-bearing one. `with_weekly_points` assigns 0.0 as a SORT value
    for a player with no projection, and the whole `projected_ids` mechanism
    exists to keep that distinct from a real zero. If the sort value reaches
    this table, then months later an invented number is indistinguishable from
    a measured one -- in the one table built to score them."""
    conn = connect(":memory:")
    write_snapshot(conn, "sleeper-main", "2026", 1, [_row("99", proj_pts=None)])

    (stored,) = conn.execute("SELECT proj_pts FROM snapshot").fetchone()
    assert stored is None
    # And SQL can tell the two apart, which is the point of storing NULL.
    assert conn.execute(
        "SELECT COUNT(*) FROM snapshot WHERE proj_pts IS NULL").fetchone()[0] == 1
    assert conn.execute(
        "SELECT COUNT(*) FROM snapshot WHERE proj_pts = 0.0").fetchone()[0] == 0


def test_write_snapshot_writes_nothing_at_all_when_given_no_rows():
    """An empty roster (a failed rosters fetch already degraded to []) must not
    leave a half-written week behind."""
    conn = connect(":memory:")
    assert write_snapshot(conn, "sleeper-main", "2026", 1, []) == 0
    assert conn.execute("SELECT COUNT(*) FROM snapshot").fetchone()[0] == 0


def test_the_write_is_committed_so_a_crash_after_lineup_keeps_the_record(tmp_path):
    """The snapshot's whole purpose is surviving to December. An uncommitted
    write is discarded when the process exits, so this asserts durability by
    reading through a SECOND connection rather than the one that wrote."""
    path = tmp_path / "season.db"
    conn = connect(path)
    write_snapshot(conn, "sleeper-main", "2026", 1, [_row("10")])

    other = sqlite3.connect(path)
    assert other.execute("SELECT COUNT(*) FROM snapshot").fetchone()[0] == 1


def test_no_test_in_this_suite_can_reach_the_real_season_db():
    """Guards the guard. `tests/conftest.py` redirects `store.DB_PATH` for
    every test; if that fixture is ever removed or renamed, a green suite goes
    back to writing into the production database under real league names --
    which is how this was found in the first place, by reading the real rows
    rather than by any test failing."""
    import ffhelper.store as store_mod
    assert store_mod.DB_PATH != store_mod.ROOT / "season.db"
