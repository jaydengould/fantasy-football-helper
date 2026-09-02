"""The snapshot table: what each source claimed at the moment a decision was taken.

The APIs serve only current state -- no historical projections, no historical
lines -- so a lineup set on Tuesday cannot be scored in December unless the
inputs were recorded on Tuesday. That is the entire justification, and it is
enough: six weeks of it makes the ADVICE measurable (did the lineups this tool
recommended beat the ones actually started?), and none of it can be recovered
afterwards.

**This is the only stateful module in the package.** It holds no globals and
knows nothing about leagues: everything arrives as an argument, including the
connection, so the tests run against `:memory:` and never touch the real file.
It is deliberately the only place that knows sqlite exists -- deciding WHAT a
row says is logic and lives in `season.py`, which is pure.

What this is not: not a cache (`.cache/` already does that), not a source of
truth for rosters (Sleeper is), and not Phase 2's SQLite draft log, which was
cut. It records claims so they can be scored later.
"""
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Never relative to cwd. The one run where the path matters is the run where you
# are not thinking about your shell -- the same lesson `DRAFT_LOG_DIR` already
# carries. `*.db` is already gitignored.
DB_PATH = ROOT / "season.db"

# `proj_pts` and `matchup` are nullable ON PURPOSE and the code depends on it:
# NULL means "no projection existed", which is a different fact from a projection
# of 0.0 and must stay distinguishable in December. See `season.snapshot_rows`.
_SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshot (
  league   TEXT, season TEXT, week INTEGER, player_id TEXT,
  taken_at TEXT,                       -- ISO, when we asked
  proj_pts REAL,                       -- this league's scoring; NULL if unprojected
  matchup  REAL,                       -- the adjustment applied, NULL before 4b
  status   TEXT,                       -- injury/practice at decision time
  started  INTEGER,                    -- did the tool advise starting them
  PRIMARY KEY (league, season, week, player_id)
)
"""

_INSERT = """
INSERT OR REPLACE INTO snapshot
  (league, season, week, player_id, taken_at, proj_pts, matchup, status, started)
VALUES
  (:league, :season, :week, :player_id, :taken_at, :proj_pts, :matchup, :status, :started)
"""


def connect(path: Path | str | None = None) -> sqlite3.Connection:
    """Open the database, creating the table if it is not there yet.

    `IF NOT EXISTS` rather than a migration step: the second `lineup` of the
    week must not fail because the first one already made the table, and there
    is no version of this project where creating one table needs a framework.

    `path=None` resolves `DB_PATH` at CALL time, not as a default argument.
    A default binds once at import, so `DB_PATH` could never be redirected
    afterwards and every test of the write path would write to the real
    database -- untestable code is untested code.
    """
    conn = sqlite3.connect(DB_PATH if path is None else path)
    conn.execute(_SCHEMA)
    conn.commit()
    return conn


def write_snapshot(
    conn: sqlite3.Connection, league: str, season: str, week: int, rows: list[dict],
) -> int:
    """Record one row per rostered player. Returns how many were written.

    `INSERT OR REPLACE`, so re-running `lineup` in the same week overwrites that
    week rather than raising on the primary key. That is the chosen semantics:
    the record is the LAST look taken before kickoff, because late injury news
    is exactly what moves a lineup. `taken_at` says when that look happened.

    Named placeholders rather than positional ones -- nine columns of mostly
    strings is precisely where a positional tuple silently swaps two fields and
    nothing ever notices.
    """
    if not rows:
        # No roster (a failed rosters fetch already degraded to []). Writing
        # nothing beats leaving a half-written week that later reads as real.
        return 0
    conn.executemany(_INSERT, [{**r, "league": league, "season": season, "week": week}
                               for r in rows])
    conn.commit()      # the whole point is surviving to December
    return len(rows)
