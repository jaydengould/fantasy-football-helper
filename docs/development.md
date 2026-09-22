# Development

```bash
.venv/bin/pip install -e ".[web,dev]"
.venv/bin/pytest          # no network, no real database, a few seconds
```

`ffhelper/value.py` and `ffhelper/season.py` are pure (no I/O, no network, no
module state), so the ranking engine tests without a network. Contributor rules
live in `CLAUDE.md`; the two that matter most:

- **A new test must be shown to fail before the fix:**
  `git stash push -u -- ffhelper && pytest -k <name>`. The `-u` matters when the
  test covers a new file, or the module stays on disk and the run proves nothing.
- **Add a mutation to `scripts/mutate.py` alongside non-trivial logic.** It is
  the only mechanical check that a test catches anything.

## Scripts

Tools that answer questions the board cannot.

```bash
.venv/bin/python scripts/backtest.py [season ...]                       # is projection source X better?
.venv/bin/python scripts/backtest_weekly.py [--league L] [--season Y]   # weekly accuracy, matchup adjustment
.venv/bin/python scripts/calibrate.py <draft_id> <slot>                 # score survival on a Sleeper draft
.venv/bin/python scripts/calibrate.py <log.jsonl> [more.jsonl ...]      # ...or on pooled journals
.venv/bin/python scripts/transcribe.py <league> [slot] [results.txt]    # results page -> journal
.venv/bin/python scripts/mutate.py                                      # break the engine, check tests notice
```

**`backtest.py`** scores a projection source against what happened. Sleeper and
ESPN both serve "season projections" for seasons already played, some revised
mid-season, so a source must prove it was frozen before week 1 or it is named and
skipped. This is how ESPN was rejected as a second source: on 2025, Rotowire beat
it 66.5 to 70.5 MAE overall and 75.3 to 93.2 at QB, and averaging the two never
beat Rotowire alone.

**`backtest_weekly.py`** is the weekly version, and the reason there is no
matchup adjustment: on 2024 and 2025 it made projections worse at every position.
Weekly projections for a past season are filtered to players who actually played,
so absolute accuracy from them is never quoted; two-arm comparisons on the same
rows still are. It also scores close calls ("of two startable players projected
within N points, did the higher one win?"), the gate any lineup signal must clear.

**`calibrate.py`** replays a finished draft and buckets "will he last to my next
pick?" by what the model predicted. Pass several journals to pool them: one draft
is a hypothesis, not a finding. It also reports room discipline (median ADP rank
of each pick); a room drafting straight down the list makes the table measure the
list against itself.

**`transcribe.py`** turns a finished draft's results page into a journal
`calibrate.py` can score: `pbpaste > .draft/results.txt`, then run it. It refuses
to write if any row resolves to zero or two players, or the picks are not a
complete `1..N` run.

**`mutate.py`** applies one-line mutations to the engine and checks the suite
fails for each. Run it on a green suite, in the foreground, alone.
