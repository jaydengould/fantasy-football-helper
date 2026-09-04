# Fantasy Football Helper

Personal tool for live fantasy football drafts, now an in-season dashboard.
Python 3.12. Two runtime modes sharing one data layer: **draft mode**
(short-lived, high-frequency, local) and **season mode** (unattended, scheduled,
SQLite-backed). Both drafts are done; season mode is the live surface.

## Where things are written down

Read these when you need them, not before.

| Path | What is in it |
| --- | --- |
| `docs/leagues.md` | Both leagues' scoring, roster shape, replacement levels, and the strategy differences that follow. **Read before touching anything that scores or ranks.** |
| `docs/decisions.md` | Settled decisions with the measurement that closed each one, the phase table, and open risks. **Read before reopening any "why don't we just…" question.** |
| `docs/superpowers/specs/` | Design authority per phase. `2026-08-24-draft-mode-design.md` is the original. |
| `docs/superpowers/plans/` | Task-by-task build plans, one per phase. |
| `docs/session-log-archive.md` | Full narrative session log, newest first. Evidence, never authority. |
| `docs/todo-archive.md` | Closed TODO sections, numbers preserved. |
| `TODO.md` | The open queue only. |
| `README.md` | User-facing. Short on purpose. |

## Working convention

**Be brutally honest. Be a sparring partner, not an assistant.** Push back when
the user is wrong, name methodological flaws plainly, identify blind spots and
faulty assumptions. Never agree to be agreeable.

**A vivid result from a single sample is a hypothesis, not a finding.** Before
writing a measurement anywhere, state what produced it and how many independent
samples it rests on. One draft, one season, or one constructed board state gets
labelled provisional or gets widened. This caused three wrong claims; the tell is
always the same — the number was striking, so the explanation got written before
the sample size got checked.

**Check provenance before building on API data.** Endpoints serve "projections"
for seasons already played, and some were revised mid-season. `scripts/backtest.py`
makes a source prove it was frozen and refuses to score it otherwise. Do the same
for any new source. A second failure mode exists: weekly projections for a past
season are *survivorship-filtered* (pre-selected to who played), so absolute
weekly accuracy from that source may never be quoted.

**Eliminating one suspect is not a verdict.** Twice a confident diagnosis was
announced after ruling out a single alternative, and it was neither. Before naming
a cause, ask what the third option is.

**Never force output to keep a feature visible.** An empty board is a valid
deliverable. Never lower a bar so a command has something to print.

**The user owns the remote and `main`.** Never run `git push`, `git merge`,
`git rebase`, or anything touching `main`. Agents may `git add` / `git commit` on a
feature branch (the review loop in `superpowers:subagent-driven-development` needs
a commit range); outside that loop, prefer writing files and reporting what is
ready. Read-only git inspection is always fine.

## Documentation rules

These exist because `CLAUDE.md` reached 1626 lines and was being loaded in full
every session.

- **`CLAUDE.md` stays under 200 lines.** It holds standards, pointers, and
  recurring mistakes — nothing else. If a section grows, it moves to `docs/` and
  leaves a table row behind.
- **`CLAUDE.md` is not a diary.** At the end of a session the narrative goes to
  `docs/session-log-archive.md` (newest first). `CLAUDE.md` changes only when a
  *rule* changes: a new convention, a reversed decision, a new recurring mistake.
- **Never write here what the agent can find by reading the code** — module
  structure, function signatures, past fixes, git history, framework common
  knowledge. Write only what the codebase cannot tell you: league rules read off a
  platform's UI, why an approach was rejected, what a measurement showed.
- **Prefer replacing or deleting over appending.** Two entries on the same subject
  means one is stale.
- **`TODO.md` is a queue, not a record.** Closed items move to
  `docs/todo-archive.md` keeping their numbers.
- **`README.md` changes only when it is actually wrong** — a drifted number, a
  renamed flag, changed behaviour, a stale sample, a false claim. Never session
  narrative or rationale. The test: would a stranger cloning the repo be misled,
  blocked, or surprised?
- **Generate samples by running the code**, never by hand. A hand-written board
  excerpt once sat in `README.md` showing a state the tool cannot produce.

## Code conventions

- **Stdlib first.** `tomllib`, `statistics.NormalDist`, `sqlite3`.
- **Dependencies are `requests`, `yfpy`, `dash`. Nothing else.** No pandas (the
  pool is ~560 players), no scipy, no PyYAML. A new dependency needs a reason a
  few lines of stdlib cannot cover.
- **`value.py` and `season.py` are pure.** No I/O, no network, no globals. If
  something in them wants to fetch, the design is wrong. That includes the
  snapshot: deciding what a row SAYS is logic and lives in `season.py`; `store.py`
  only knows how to write one.
- **`store.py` is the only stateful module** (`season.db` at repo root,
  gitignored). Takes an open connection, holds no globals. Resolve paths at call
  time, never in a default argument — a default binds at import and makes the
  write path untestable.
- **No module-level league state.** Every function takes league context. A
  "current league" global is a rewrite to undo.
- Config is `config.toml`; secrets are `.env`, gitignored.
- Mark deliberate shortcuts with a `ponytail:` comment naming the ceiling and the
  upgrade path.
- **`lineup_value()` / `optimal_lineup()` are shared primitives** — the board, the
  weekly lineup, waivers and the trade finder all call them. Never inline a second
  greedy assignment; two rules that can disagree is the defect that produced them.

### Testing

- Non-trivial logic leaves one runnable check behind. `tests/` plus `preflight`.
  **No mocking the network** — the pure core does not need it, and loaders take an
  explicit `fetcher`.
- **No test may reach the network or the real database.** Both are guarded autouse
  and suite-wide in `tests/conftest.py`. A per-test rule is one the next test
  forgets, and both failures are silent: the suite stays green and merely gets
  slower (0.68s → 4.78s was the only tell), or it writes fixture rows into
  production under real league names.
- **A new test must be shown to fail before the fix**, via
  `git stash push -u -- ffhelper && pytest -k <name>`. **The `-u` is not optional**
  for a test covering a new file — plain `stash` leaves untracked files on disk, so
  the module stays present and the run proves nothing.
- **Add a mutation to `scripts/mutate.py` alongside non-trivial logic.** A
  surviving mutation is evidence about the TEST: fix the test, never weaken the
  mutation. If it survives because no test can *reach* the code, that is the
  finding — untestable code is untested code, and the fix is a seam.
- **Mutation runs: green suite first, foreground, alone.** Against a red suite
  every mutation "kills" trivially. "Alone" includes subagents — a reviewer running
  its own concurrently corrupted two runs and the results looked normal. Capture
  `git status` before and after and diff them.

## Non-negotiables

Breaking these causes silent, hard-to-detect wrongness.

1. **Never join load-bearing data on player name.** Integer IDs only. FFC is the
   one fuzzy join, enrichment-only, applied after the ID-keyed board is complete,
   keyed on (normalized full name, position, team) — Bijan and Brian Robinson are
   both ATL RBs.
2. **Never blend projection rank with ADP rank into one number.** Surface the
   divergence as a flag. A board that tracks consensus produces consensus results,
   which removes the reason the tool exists. This also bars consensus trade-value
   charts and ECR: a consensus ranking is PRICE, not value.
3. **Unmatched players are printed, never silently dropped.**
4. **The live loop never dies.** Wrapped poll, logged exception, `continue`.
5. **Never commit cached projections.** The repo is public and the data is
   Rotowire's, served from an undocumented endpoint. Fetch at runtime.
6. **No auto-pick.** The tool advises; it never drafts.
7. **Degrade to "column absent", never to a fabricated number.** A sort value of
   0.0 must never be written where a measured 0.0 would be read later.
8. **Never introduce a hand-picked discount, multiplier, or weight.** It invents a
   number the data does not supply. A weight ships only with a derivation
   (`week_weights` is the probability you play that week) or a backtest that beats
   the unweighted version out of sample. `season.py` and `value.py` carry comments
   pointing here.

## Recurring mistakes — check these before shipping

Each of these has happened at least twice. Update this list when a new pattern
earns a second occurrence.

- **A league rule inferred from an API default instead of read off the platform's
  own screen.** Three times: Yahoo's one-RB slot (recorded as two), FAAB (it is
  rolling waiver priority; `waiver_budget: 100` is returned by default whether or
  not bidding is on), and `LAST_REGULAR_WEEK = 18` (the bracket ends week 17). Ask
  the user to read the setting off the UI.
- **A fix applied to the file the finding named, not to every place the defect
  lives.** `LAST_REGULAR_WEEK` was fixed in `trades` and left live in `waivers`; a
  redaction was applied to `README.md` and left in four other tracked files. Grep
  for the pattern, not the filename.
- **A plan detailed enough to transcribe is detailed enough to transcribe a
  defect.** Eight of Phase 5's defects and three of Phase 4a's were in the task
  brief, shipped verbatim by implementers doing exactly as told. Run the plan's own
  fixture numbers by hand before implementing.
- **A verification tool reporting success while checking something else.** Three
  times in `mutate.py` alone (duplicate dict key, ambiguous target string, stale
  `.pyc`). Each was fixed with a *guard in the tool*, not a correction of the
  instance, which is why none recurred. Two sources of truth — a mutation's label
  and its target string — disagree eventually.
- **A green suite is not evidence the thing you changed is covered.** Every
  significant defect found late was found by a human running the code against real
  data, or by two independent views of one write disagreeing (the printed count
  said 15, the table held 17).
- **Guarding the path the last defect took, and missing its siblings.** Grep the
  other callers of every endpoint or helper a fix wave touches.

## Current state

Both drafts are done (2026-09-01); the 2026 season starts Sept 9. Phases 0–5 are
complete except Phase 0 (Yahoo OAuth, blocked on Yahoo's approval since
2026-08-24) and Phase 3.7 (the `DataTable` swap, offseason). Full table and the
open risks are in `docs/decisions.md`; the queue is `TODO.md`.
