# Fantasy Football Helper

Personal tool for live fantasy football drafts, growing into an in-season
dashboard. Python. Two runtime modes sharing one data layer: **draft mode**
(short-lived, high-frequency, local) and **season mode** (unattended, scheduled,
SQLite-backed).

**Full design:** `docs/superpowers/specs/2026-08-24-draft-mode-design.md`
This file is the running memory; the spec is the authority on design detail.

## Working convention

**Be brutally honest.** Push back when the user is wrong, state methodological flaws plainly, and never agree just to be agreeable.

**Do not simply agree with me. Be my sparring partner. Identify my blind spots,
structural risks, and faulty assumptions.**

**Update this CLAUDE.md at the end of each working session** — record decisions
made, schema/config changes, and what's next. It's the memory that survives
between sessions.

**The user owns the remote and `main`.** Never run `git push`, `git merge`,
`git rebase`, or any command that touches `main`. Pushing and merging are the
user's alone.

Agents **may** `git add` and `git commit` on a feature branch — this is required
for the review loop in `superpowers:subagent-driven-development`, which generates
reviewer diffs from a commit range. Outside that loop, prefer writing files and
reporting what's ready rather than committing unprompted. Read-only inspection
(`git status`, `git log`, `git diff`) is always fine.

## Leagues

| League | Platform | Draft | Format |
| --- | --- | --- | --- |
| Bros with no hoes (`1395959490938966016`) | Sleeper | **Sept 6 2026, 7:00 PM** | snake, 12 team, 15 rd, 120s clock |
| Yahoo league (id in `.env`) | Yahoo | **Sept 1 2026** | snake, **10 team** |

Sleeper scoring: full PPR, 0.1/yd rush+rec, 0.04/yd pass, **6-pt passing TDs**
(not Sleeper's default 4). Roster `QB/RB/RB/WR/WR/TE/FLEX/FLEX/K/DEF` + 5 bench.

**Yahoo scoring (user-supplied 2026-08-24, complete). Must be hand-entered — no
API access.** Roster `QB/WR/WR/RB/RB/TE/FLEX/FLEX/K/DEF` + 5 bench — same shape as
the Sleeper league, but 10 teams. Mapped to Sleeper stat keys for `score_stats`:

```
pass_cmp 0.25  pass_yd 0.04  pass_td 6   pass_int -2   pass_2pt 2
rush_yd  0.1   rush_td 6     rush_2pt 2
rec 0.5        rec_yd 0.1    rec_td 6    rec_2pt 2
fum_lost -2    fum_rec_td 6

K:   fgm_0_19 3  fgm_20_29 3  fgm_30_39 3  fgm_40_49 4  fgm_50_59 5
     fgm_60p 5   xpm 1        (no FG-miss penalty — differs from Sleeper's -1)

DEF: sack 1  int 2  fum_rec 2  def_td 6  def_st_td 6  st_td 6  safe 2  blk_kick 2
     pts_allow_0 10  _1_6 7  _7_13 4  _14_20 1  _21_27 0  _28_34 -1  _35p -4
```

Unmapped: "extra point returned 2" has no clean Sleeper key (negligible).

**Replacement levels:** Sleeper QB12/TE12/RB36/WR36; Yahoo QB10/TE10/RB30/WR30.

**The two leagues differ in ways that change the board, not just the numbers:**
- **10 teams vs 12** — shallower replacement (QB10, ~RB25, ~WR30), so elite players
  gain value relative to the pool.
- **Half PPR (0.5) vs full PPR (1.0)** — shifts RB/WR balance.
- **0.25 per completion** — unique to Yahoo. Allen's ~313 projected completions are
  worth **+78 points**, comparable to 13 passing TDs. Systematically favours
  high-volume pocket passers over rushing QBs. The two leagues want different QBs.
- **INT −2 vs −1.**

Known blind spot: return yards/TDs are scored in the Yahoo league but Sleeper's
projections carry no return stats, so those categories contribute ~0.

**Validated 2026-08-24 against real projections — the two boards diverge sharply:**

| | Sleeper | Yahoo |
| --- | --- | --- |
| QB1 off the board | pick 24 | **pick 18** |
| QB2–4 | 54, 56, 61 | **39, 40, 44** |
| QB2 identity | L. Jackson | **J. Burrow** |
| Top 13 | mixed | **9 of 13 are RBs** |

Draft strategy consequences: **take QBs ~15 picks earlier in Yahoo**, and **prefer
volume passers over rushing QBs there** — the completion bonus rewards attempts,
not legs, so Burrow rises to QB2 while Jackson leaves the top four. Inverted from
Sleeper. The RB tilt comes from half PPR plus 10-team shallower replacement.

## Code conventions

- **Python 3.12.** Stdlib first — `tomllib` for config, `statistics.NormalDist`
  for survival math, `sqlite3` for persistence.
- **Draft-mode dependencies are `requests`, `yfpy`, `dash`. Nothing else.**
  No pandas (the pool is ~560 players; a list of dicts is what Dash wants
  anyway). No scipy. No PyYAML. Adding a dependency needs a reason that a few
  lines of stdlib cannot cover.
- **`value.py` is pure.** No I/O, no network, no globals. All logic lives there
  so it tests without a network. If something in `value.py` wants to fetch, the
  design is wrong.
- **No module-level league state.** Every function takes league context. Two
  leagues on two platforms is a requirement, and a "current league" global is a
  rewrite to undo.
- Config is `config.toml`; secrets are `.env`, gitignored.
- Mark deliberate shortcuts with a `ponytail:` comment naming the ceiling and
  the upgrade path.
- Non-trivial logic leaves one runnable check behind. One `test_value.py` plus
  `preflight`. No mocking the network — the pure core doesn't need it.

## Non-negotiables

These exist because breaking them causes silent, hard-to-detect wrongness.

1. **Never join load-bearing data on player name.** Projections, the player DB,
   and the crosswalk all join on integer IDs. FFC is the one fuzzy join and it
   is enrichment-only, applied *after* the ID-keyed board is complete. Match key
   is (normalized full name, position, team) — last name + position + team is
   not enough (Bijan and Brian Robinson are both ATL RBs).
2. **Never blend projection rank with ADP rank into one number.** Surface the
   divergence as a flag. Blending pulls the board toward the field, and a board
   that tracks consensus produces consensus results — which removes the entire
   reason the tool exists.
3. **Unmatched players are printed, never silently dropped.**
4. **The live loop never dies.** Wrapped poll, logged exception, `continue`.
5. **Never commit cached projections.** Sleeper's projections endpoint is
   undocumented and the data is Rotowire's. Fetch at runtime. The repo is public
   and tied to a job search — same reasoning that ruled out FantasyPros.
6. **No auto-pick.** The tool advises; it never drafts.

## Decisions and why

Recorded so they don't get re-litigated. Reversing one needs a new reason, not a
fresh opinion.

- **Sleeper is the data backbone for *both* leagues** (projections, player DB,
  ADP) and *one of two* pick feeds. Yahoo replaces only the feed. The engine
  never knows which platform it serves.
- **DynastyProcess `db_playerids.csv` is a Phase 1 dependency, not season mode.**
  Sleeper's own `yahoo_id` is unusable: 0/302 rookies, 13/692 sophomores. Gibbs
  (RB1) has none. DP covers 99.9%.
- **FFC stays, as non-load-bearing enrichment.** Its per-player ADP `stdev`
  cannot be synthesized — fitting `stdev = 0.287 × adp^0.809` gives R² = 0.574,
  leaving 42.6% irreducible, and it fails worst exactly where survival matters
  (Keon Coleman: actual 47.7, curve 11.6). Fallback on join failure is Sleeper
  ADP plus that curve.
- **Engine is VBD + survival-weighted VONA.** Rejected: a static VBD board (a
  printed cheatsheet that never answers the question at the clock) and
  Monte-Carlo simulation (no data to fit an opponent model, too slow for a 120s
  clock, fails silently).
- **Custom scoring is correct but marginal.** The 6-pt passing TD moves raw
  totals a lot (Allen 361.5 → 415.5) but VBD is a difference and a uniform shift
  cancels at replacement (Allen's VBD 65.8 → 68.0). Build it — it's ~10 lines
  and simply right — but VONA and survival carry the edge. Do not oversell it.
- **`lineup_value()` is a standalone pure function.** Phase 1 needs it for
  starter-slot awareness; Phase 5's trade finder needs the identical function.
  Never inline it into the board.
- **Waiver notify-bot is cut.** The league is FAAB with scheduled batch
  processing (`waiver_clear_days: 2`), so claims resolve simultaneously and a
  same-day alert gives no timing edge.
- **Yahoo risk is confined to draft day.** The risk is unrepeatability, not
  difficulty. In-season Yahoo is *lower* risk than Sleeper draft mode. Phase 0
  OAuth is never wasted — season mode needs it regardless.
- **Trade finder will not output an acceptance probability.** Acceptance depends
  on attention, name-brand bias, and stubbornness; a confident percentage would
  dress up a guess. Rank by a transaction-history prior instead.
- **Ruled out:** FantasyPros (paid, ToU bars reproducing content), ESPN/Yahoo
  scraping, `nfl_data_py` (deprecated by nflverse → use `nflreadpy`).

## Phases

| Phase | What | Target | Status |
| --- | --- | --- | --- |
| 0 | Yahoo OAuth handshake; confirm league access, size, settings | Aug 25 | **blocked — awaiting Yahoo approval** |
| 1 | `data.py` + `value.py` + `cli.py`, Sleeper feed, multi-league config, **manual mark-drafted** | Aug 28 | in progress |
| 2 | Yahoo feed adapter + SQLite draft log | Aug 29–30 | not started (Yahoo half gated on approval) |
| 3 | Dash UI | Sept 5 | not started |
| 3.5 | Opponent needs, bye clustering, notifications, manual overrides | Sept 5 | not started |
| 4 | Season mode (`nflreadpy`) | after | not started |
| 5 | Trade finder (own spec) | in-season | not started |

Phase 1 builds against the Sleeper feed because it needs no auth and Sleeper
mock drafts are free — it is the test harness that de-risks the Yahoo adapter.

## Known open risks

- **YAHOO API ACCESS WILL NOT EXIST FOR THE SEPT 1 DRAFT. Confirmed, not assumed.**
  The Fantasy Sports API is no longer self-serve: access must be applied for at
  `sports.yahoo.com/developer/access/` and reviewed by the Yahoo Fantasy Sports
  team. Applied 2026-08-24; Yahoo replied that review takes **1–2 weeks**. Against
  a Sept 1 draft that is best-case Aug 31, worst-case Sept 7 — after both drafts.
  Read-only is the default tier, which is all this project needs.

  Three consequences, all binding on Phase 1:
  1. **No settings sync for Yahoo either.** `scoring_settings` and
     `roster_positions` are API features. `config.toml` must accept hand-entered
     league settings (scoring dict, roster slots, num_teams) for platforms with no
     API access — otherwise the Yahoo board is computed against the wrong scoring.
  2. **Manual mark-drafted is the Sept 1 Yahoo interface**, not a fallback. It
     needs partial-name search, disambiguation on ambiguous prefixes (the
     Bijan/Brian problem — a wrong pick silently corrupts the board), undo, and
     non-blocking input. The earlier "~10 lines" estimate was for the trivial
     safety-net version and is wrong for this.
  3. **Phase 2 splits.** SQLite draft log stays on schedule. The Yahoo feed
     adapter moves to whenever access arrives, targeting season mode — which is
     where Yahoo matters more anyway (weekly cadence, testable, no unrepeatable
     deadline). Frees Aug 29–30.

  The engine is platform-independent, so the board still works: the feed only
  supplies who is already gone, which the user reads off Yahoo's own UI.
- **Yahoo cannot be integration-tested before Sept 1** even if access is granted.
  Mock-lobby drafts aren't real leagues and expose no `league_key`. Only pre-draft
  test is a settings read plus empty `draft_results`.
- **Yahoo rate limits are undocumented** and enforced per registered app ID.
  Poll Yahoo at 10–15s, not 5s.
- **Single-source projections.** Everything downstream inherits Rotowire's
  opinions. The ADP divergence flag shows *where* they disagree with the market
  but cannot say who is right. A second source (ESPN) is offseason work.
- **Draft slot is not final** — Sleeper `draft_order` has 11 of 12 slots. Must be
  a config override, never trusted from the API.

## Session log

### 2026-08-24 — Brainstorming and spec

Researched all data sources against live endpoints rather than assumption.
Findings that changed the plan: Sleeper ships free Rotowire projections with raw
stat lines (makes league-custom scoring and VBD feasible at all); Sleeper's
`yahoo_id` is unusable for young players; FFC's ADP `stdev` is irreducible.

Corrected two of my own claims mid-design: custom scoring is marginal after VBD,
not the headline feature; and multi-source consensus was already available via
FFC ADP, which I'd been using only for survival.

Design spec written, self-reviewed, committed — `00b90e7`, updated `4072b90`
(ADP divergence flag, manual mark-drafted mode, Yahoo risk scoping).

**Next:** implementation plan for Phases 0–3, then Phase 0 — which needs ~2
minutes of the user's browser to register the Yahoo app.

### 2026-08-24 — Phase 0–1 execution begins

Plan written: `docs/superpowers/plans/2026-08-24-phase-0-1-draft-engine.md`,
scoped to Phases 0–1 only (Phase 2's detail depends on what Phase 0 discovers).
Writing it surfaced a spec contradiction — "commit fixtures" versus "never commit
projections" — resolved toward synthetic test data plus two inlined real records.

Working on branch `phase-0-1-draft-engine`. Git rule amended: agents commit on the
feature branch because the review loop generates diffs from commit ranges; push,
merge, and `main` remain the user's.

**Phase 0 paid off immediately and negatively: Yahoo API access now requires
approval.** See Known open risks. This is the phase working as designed — found
8 days out rather than on draft night.

Completed: Task 0 (scaffolding, venv — `6dcf719`), Task 2 (config loading —
`ec98daa`). Both passed review clean.

**Next:** Tasks 3–13 (all Sleeper/pure-Python, unaffected by the Yahoo block).
User to submit the Yahoo Fantasy API access application.

### 2026-08-25 — PAUSED after Task 9. Resume at Task 10.

**State:** branch `phase-0-1-draft-engine` @ `6f26a3d`, **67 tests passing, no open
findings.** Data layer (Tasks 2–6) and pure engine (Tasks 7–9) are COMPLETE.

To resume: say **"start task 10"**. Full detail is in the SDD ledger at
`.superpowers/sdd/2026-08-24-phase-0-1-draft-engine/progress.md` — it records every
task's commits, findings, and the next controller action.

| Task | What | Status |
| --- | --- | --- |
| 0, 2–6 | scaffolding, config, cache, players+crosswalk, scoring, ADP | ✅ |
| 7–9 | VBD/tiers, `lineup_value`, survival/VONA | ✅ |
| 10 | pick feed protocol + `SleeperFeed` | next |
| 11 | board assembly | pending |
| 12 | CLI render/loop/preflight + **manual mark-drafted** | pending |
| 13 | human: live Sleeper mock draft | pending |

**Yahoo applied 2026-08-24, reply says 1–2 weeks. Draft is Sept 1 — it will not
arrive.** Manual mark-drafted in Task 12 is therefore the real Sept 1 interface and
needs partial-name search, disambiguation, undo, and non-blocking input.

**Carry into Task 12:** `apply_ffc_adp` returns `list[str]` in which ambiguous
entries carry an `"AMBIGUOUS: "` prefix; the caller should branch on it when printing.

**Seven defects found so far were in the PLAN, not the implementations** —
RB30/RB36 contradiction, `load_crosswalk` cache duplication, FFC name matching
(23% miss on live data), tier threshold scope, a wrong `marginal_value` test
expectation, VONA excluding its own candidate, and a truthiness stdev fallback.
Three of those passed full green suites and were caught only by running the code
against the real player pool.

**The recurring cause: test fixtures chosen for arithmetic convenience** — round
numbers, 6σ separations, four-player pools — rather than resembling real data.
Keep running live checks against the real Sleeper pool after each data- or
engine-touching task; do not trust a green suite alone.
