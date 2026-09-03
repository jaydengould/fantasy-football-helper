# Outstanding work

Written 2026-08-25. **Rewritten 2026-09-01, after both drafts.** Ordered by
what blocks what.

The numbered sections below are the historical record — decisions, measurements
and the reasoning behind them. They are not a queue. **This summary is the
queue.**

## What is left, in one place

**Both drafts are done (2026-09-01).** Everything scheduled against them is
closed: the cheat sheet (§16, its purpose was the hand-typed Yahoo draft), the
two-boards check, the `value.py` / `data.py` freeze, and every "before Sept 1"
item. The project is now a season-mode project.

1. ~~**THE DRAFT DEBRIEF.**~~ **DONE 2026-09-01**, recorded in `CLAUDE.md`. Two
   outcomes: the board may have stopped updating mid-draft and NOTHING on disk
   can say (hence item 2), and pick 5 was the user's own call, not the board's.
   Why it mattered, kept because the reasoning generalises: nine of this
   project's defects were found by a human USING the tool and none by the suite,
   so what the user noticed is evidence nothing else can produce — and it decays
   within days.
2. **A RUN LOG — small, and the draft debrief is what proves it is needed.**
   The user reported the board "died at some point" during the live Sleeper
   draft, and **nothing on disk can confirm or refute it**: no journal (feeds
   write none), no log file (stderr only), and the picks cache mtime gets
   overwritten by the next run. The 2026-08-27 mock was diagnosable ONLY because
   a server log happened to sit in a terminal. Write poll successes, failures and
   callback timings to a dated file under `.draft/` or `.cache/`, the same
   append-and-close shape as the mark journal, so the next "I think it died" is
   answerable. Cheap, and it is the difference between a diagnosis and a shrug.
3. ~~**FINISH THE 4a MERGE CHECK.**~~ **DONE 2026-09-02.** Branch
   `phase-4a-start-sit`, 20 commits, **377 tests**, **153 mutations, 1 needing a
   look** (the documented `value.py` tier-threshold equivalent mutant), exit 0,
   run in the foreground alone and verified byte-identical before and after.
   `lineup` and `preflight` re-run clean on both leagues. **PHASE 4a IS
   FINISHED; the branch is ready for the user to merge.**
   Two corrections to what this item claimed:
   - **The rosters-guard mutation HAD been added** (in `fc47a73`, after this
     item was written) and is killed. Nothing was missing.
   - **The first two mutation runs were contaminated and thrown away.** The
     re-review agent ran its own `mutate.py` concurrently with mine — the exact
     hazard below, arriving from a second process rather than an interrupted
     one. The tree recovered via the in-flight run's `finally`, but the results
     were untrustworthy and the run was repeated alone. **The hazard is not
     just "don't interrupt it" — it is "nothing else may run it at the same
     time", and a subagent counts.**
   **HAZARD, now hit twice:** `mutate.py` rewrites source files in place. The
   2026-09-02 session killed an agent mid-run and left `ffhelper/value.py`
   holding a live mutation (`prob_all_gone *= surv` instead of `1.0 - surv`).
   Caught by `git diff` and restored. **Always check `git status` is clean before
   trusting a suite after an interrupted mutation run.**
3a. **What the scoped re-review found — eight defects, none Critical, all
   fixed** (`c45a8cd`, `1a23576`). Recorded because six of the eight are the
   same shape as defects this project has already had:
   - **`load_league_users` was the last unguarded fetch in `_lineup`**, on the
     happy path, and it threw away a lineup whose roster and projections had
     both already succeeded — over a display name. Rounds 1 and 2 guarded
     `/state/nfl`, the feed and the rosters endpoint and missed the sibling.
     **Found by grepping the other callers of the endpoints the fix wave
     touched, not by re-reading the paths it had changed.**
   - **`preflight` printed `PREFLIGHT OK` and exited 0 with the projections
     endpoint down** — the only failure branch that never set `ok = False`,
     in the one check that exists to prove season mode can run.
   - **`preflight` and `_lineup` disagreed about what "no week" means**
     (`week is None` vs `not week`); Sleeper serves `"week": 0` in the
     offseason, so preflight fetched projections for week 0.
   - **One `projections` label covered two different populations** — 177 of 180
     league-wide on Sleeper, 13 of 14 on your own Yahoo roster.
   - **The `roster_id` override note vanished when the rosters fetch failed**,
     leaving a hand-set override unmentioned in exactly the run that read
     nothing. TODO item 6 calls that note "the passive check made active".
   - **`mutate.py` was checking the wrong thing, again.** The
     `"panel hides empty slots"` mutation used a bare `"    return out"`, which
     matches TWO places in `app.py`; `replace(old, new, 1)` took the first, so
     it broke `board_rows`'s filter and reported **killed** for a function it
     does not name. **Root cause fixed rather than the instance**: an
     old-string matching more than one place is now refused as `AMBIGUOUS`.
     Identical failure shape to the 2026-08-27 duplicate-key bug — the check
     reporting success while checking something else. That is now twice, from
     the same tool.
   - **A test asserted a filename by deriving it from the function under
     test**, so it passed for any key format — including the exact
     `"rosters_123_v2"` case its own comment claimed to catch. Now the literal,
     verified red by actually changing the key format.
4. ~~**Phase 4 — season mode: start/sit.**~~ **4a COMPLETE AND MERGE-CHECKED
   2026-09-02**, branch `phase-4a-start-sit`, 20 commits, 377 tests, 153
   mutations. `lineup` runs against both leagues. Final whole-branch review plus
   a scoped re-review of the fix wave: sound, merge recommended, no Criticals.
   **Merging is the user's call — agents never touch `main`.**
   What is left of Phase 4:
   - ~~**the snapshot table**~~ **DONE 2026-09-02**, branch `phase-4b-snapshot`,
     `ffhelper/store.py`. Pulled ahead of the matchup work because it is the
     only outstanding item with an unrecoverable deadline: the APIs serve
     current state only, so a week not recorded before it is played can never
     be scored. **Week 1 is recorded for both leagues.** It must keep running
     weekly — nothing schedules it, a `lineup` run is what writes it.
   - ~~**4b — the matchup adjustment**~~ **CLOSED 2026-09-02 ON A MEASUREMENT.
     What ships is a descriptive opponent RANK (`vs CAR soft 31/32`) that
     nothing consumes — no projection, no sort key, no snapshot column. The
     ADJUSTMENT is what lost:** `scripts/backtest_weekly.py`
     scored it on 2024 and 2025 (~8000 player-weeks) under both leagues'
     scoring, and it LOST at every position and every shrinkage level, with
     error rising monotonically as the adjustment gets louder. Out of sample the
     factor correlates **+0.02 to +0.06** with a player's actual weekly
     deviation, against **+0.05 to +0.22** for the projection's own week-to-week
     movement — Rotowire already carries whatever weekly signal exists. The
     split-half stability of the underlying rate flips sign between seasons
     (WR +0.351 in 2025, −0.268 in 2024), and a schedule-adjusted estimator
     behaves the same way, so the estimator is not the problem.
     `season.points_allowed` / `matchup_factor` / `matchup_deltas` and
     `data.load_weekly_actuals` STAY — they are what the backtest scores, and
     one line reopens it. **To reopen, bring a season where the adjustment wins
     that table.** Full numbers in `scripts/backtest_weekly.py`'s docstring.
     - **The coarse good/neutral/bad form was measured too, before building it.**
       Residual (actual − projected) by matchup tercile, out of sample: RB and TE
       point the right way in both seasons, **QB and WR point the wrong way in
       2024** (QB +1.00 → +0.76, WR +0.65 → +0.26). Under a null of no signal,
       ≥2 of 4 positions agreeing across two seasons happens ~69% of the time —
       no evidence. So the column is worded as a fact about the past, is silent
       below 3 completed games per defense and in week 1, and is ranked per
       position (in the 2025 replay CAR reads `tough 2/32` to WRs and
       `soft 31/32` to TEs in the same week).
     - **A second finding from the same run, and it constrains every future
       weekly measurement**: the served weekly projections for a PAST season
       are survivorship-filtered. 6165 projected player-weeks in 2025, of which
       **6 did not play (0.1%)** — a real week loses 1–3% of projected starters
       to inactives. The VALUES look untouched (r = 0.67–0.80 vs actuals), so it
       is the POPULATION that is contaminated. Absolute weekly accuracy from
       this source may not be quoted; a relative comparison scored on the same
       rows still holds. `backtest_weekly.py` prints the check and says which
       of its numbers survive it.
   - ~~**nflverse injury report**~~ **BUILT 2026-09-02**, joining on `gsis_id`
     through the crosswalk already fetched (`load_crosswalk(field=...)`).
     Coverage on the real rosters is **14/15 and 13/14**, the only misses being
     team defenses, which have no injury report. `lineup` prints a practice
     report line every run. **`injuries_2026.csv` is STILL a 404** — it appears
     once week-1 games are reported, ~Sept 10 — so the degraded line is what
     both leagues print today, and the join is proved against the 2025 file
     instead (real roster, real report, week 11).
   - ~~**4c — waivers**~~ **BUILT AND MERGE-CHECKED 2026-09-02**, branch
     `phase-4c-waivers`, 8 commits, **454 tests**, **184 mutations, 1 needing a
     look** (the documented `value.py` equivalent mutant), tree byte-identical
     before and after. `waivers --league sleeper-main` prints **an empty board
     in week 1**, which is the acceptance criterion the plan named, and it was
     PROVED to be empty for the right reason: with the floor turned off in a
     scratch script the pipeline produces rows (ten tight ends, best +8.3 ROS —
     the number the spec measured). 4.8s warm, ~46s on a cold cache (108 files).
     Yahoo refuses, labelled, exit 1. Three things the build turned up:
     - **`scripts/mutate.py` was leaving MUTATED BYTECODE behind.** Python
       validates a `.pyc` on the source's mtime-in-seconds plus its size, so a
       mutation the same length as the original, written and restored inside one
       second, leaves cached bytecode that looks valid and is not. The full run
       ended with a clean `git status`, a tree identical to HEAD, and one FAILING
       test; `touch ffhelper/cli.py` fixed it with no source change. The
       dangerous direction is the reverse — a restored file running mutant
       bytecode reports `killed` for a check that never ran. Fixed at the root:
       `mutate.py` now unlinks the `.pyc` on every write, with a test.
       **Third time this tool has reported success while checking something
       else** (duplicate dict key 2026-08-27, ambiguous target 2026-09-02).
     - **Two mutations SURVIVED against a green suite** after an earlier "killed"
       had been read off a RED one — a test helper I appended to
       `tests/test_season.py` shadowed an existing `_slots()` and quietly broke
       the snapshot test. Both survivors were vacuous tests and both were fixed
       in the direction the rule says. The lesson is the recorded one, arriving
       again: check the suite is green before believing a mutation run.
     - **The plan's tie fixture was wrong** and the plan's own instruction caught
       it: run the numbers by hand first. Its expected drop was Gainwell; the tie
       includes the DEFENSE being replaced, whose own points are lower, so the
       answer is the Broncos — which is also the move a human would make.
     Two things the plan flagged and the build took the better half of: the
     `roster_id` re-derivation in `_waivers` is gone (`_resolve_my_roster`
     returns the id it already resolved), and `mutate.py` gained an optional
     label filter so one new mutation can be checked in seconds.
     What it looked like before it was built, kept because the probe is the
     record of why the shape is what it is:
     free-agent pool, rest-of-season horizon, trending
     add/drop as the price signal. **Nothing blocked it as of 2026-09-02** —
     probed live: `state/nfl` reads week 1 `in_season`, weekly projections exist
     for **all 18 weeks** (so the ROS horizon is buildable), trending and
     transactions both answer, and 12 rosters give a 3051-player free-agent pool.
     Three things the probe changed:
     - **THE LEAGUE IS NOT FAAB. It is rolling waiver priority** (user-confirmed
       against Sleeper's UI). The FAAB claim in `CLAUDE.md` and both specs came
       from `waiver_budget: 100`, which Sleeper returns by default; the live
       settings say `waiver_type: 0` with distinct `waiver_position` 1-12.
       **The "derived FAAB bid" deliverable is dead** — priority is an ordering
       you spend, not a currency, so the output is your position and the cost of
       burning it. The notify-bot cut is unaffected: it rests on batch
       processing, which is still true.
     - **A bye is an ABSENT ROW, not a zero** (Gibbs wk6, Allen wk7, Nacua wk11).
       So is an unprojected player. Summing an ROS horizon over "weeks that
       answered" silently loses the 4a distinction between a measured 0.0 and no
       number at all — print the count of projected weeks beside the total.
     - **The raw pool is 3051 of 3231 players**, i.e. mostly retired and
       practice-squad. It needs a filter before it is a list anyone reads.
     Preseason weekly projections are flat (Nacua 20.4-21.0 across all 18), so
     ROS today is season value x weeks left; the feature only becomes measurable
     once week 1 is played.
     Spec and plan: `docs/superpowers/specs/2026-09-02-phase-4c-waivers-design.md`
     and `docs/superpowers/plans/2026-09-02-phase-4c-waivers.md` (8 tasks, all
     executed).
     Two things the plan settled that are easy to lose:
     - **`load_league_transactions` was cut** — it has no consumer once the FAAB
       bid is gone. Position comes from the `rosters` payload, and the
       cost-of-spending line is arithmetic on two already-computed targets.
     - **The floor is `close_call_points * sqrt(weeks)`, and sqrt(1) = 1**, so
       the THIS WEEK section is the rest-of-season function called with a
       one-week horizon. One code path, no second threshold. The first version
       of this rule was a flat 3.0/week bar and was wrong — it is calibrated to
       a SINGLE week's error, and weekly errors partially cancel, so a flat bar
       is ~4x too strict. Caught in spec self-review, before any code.
5. ~~**The Yahoo roster must be hand-entered.**~~ **DONE 2026-09-01.**
   `.roster/yahoo-main.txt`, 14 players, all resolving unambiguously, gitignored.
   It must be UPDATED after every add/drop — `lineup` and `preflight` both print
   its age for exactly that reason.
6. **Deferred minors from the 4a review, none blocking** — all triaged as ship
   in the final review: roster-file inline comments and duplicates (both fail
   safe), `SUPER_FLEX`/`WRRB_FLEX` slot names printing a false "no eligible
   player" line, an unprojected starter appearing in two sections, close-call
   lines not repeating both projections, and one stale test comment.
   **Plus one risk introduced deliberately:** a wrong-but-valid hand-set
   `League.roster_id` produces a coherent lineup for someone else's team. The
   override note now names the owner, which is the passive check made active.
   A derive-and-compare cross-check was considered and rejected — it
   re-introduces the feed dependency in the one path whose purpose is to survive
   a missing draft, and only helps when both values are set, which is the case
   that was already right.
7. ~~**Phase 5 — trade finder.**~~ **DONE 2026-09-02, closed out 2026-09-03,
   branch `phase-5-trade-finder`, 500 tests, 204 mutations (1 documented
   equivalent survivor; 202 from the last full run plus 2 hand-verified in
   `f15cd2e`). Awaiting the user's merge.** The final whole-branch review's fix
   wave is `f15cd2e` (ranking-layer test coverage, the unbounded pin, the
   opponent-roster degradation note, two undocumented tunables) and the
   leaguemate handle it left in four other tracked files is redacted in
   `7dbd401`. `trades --league sleeper-main` ran for real: 2:39 wall clock, one
   row league-wide (reproduces the pre-build measurement below exactly), "17
   weeks scored". `--player <name>` pins the search (12s). `--league
   yahoo-main` refuses, exit 1 (needs every roster; Yahoo serves none). Full
   detail in `CLAUDE.md`'s session log and Decisions.
   `.superpowers/sdd/2026-09-02-phase-5-trade-finder/progress.md` is the full
   ledger if the specifics of any task are ever needed again.

7a. **CLOSED 2026-09-02, commit `5b1e86b`.** `best_drop` could return the
   just-added candidate himself as the drop (0.0 gain by construction, a
   12-player superset feeding `weeks_started`) — not reachable in shipped
   `waivers` (0.0 can't clear the floor) but live the moment the trade search
   calls `best_drop` directly with no floor. Fixed with an opt-in `keep`
   parameter that only `roster_upgrade` passes; `best_drop`'s general default
   (a just-received player CAN legitimately be the right cut) is untouched —
   confirmed live in Task 6's fixture.
7b. **CLOSED 2026-09-02 — folded into Phase 5's build.** What the pre-build
   probes established now lives in `CLAUDE.md`'s Decisions and session log:
   1-for-1 trades are empty against the real league (zero of 2475 pairs clear
   the floor), 2-for-2 is where the surplus is, the whole-league board is one
   row, the acceptance prior is dead (3 transactions all season, zero trades,
   no prior season), the prefilter is unsound (drops 22 of 49 real trades),
   and `LAST_REGULAR_WEEK = 18` was wrong (season ends week 17).
7c. **Two slices deferred out of Phase 5's spec, not started, each gated on a
   missing prerequisite:**
   - **Leverage weighting** — weight playoff weeks UP by win probability
     instead of down by play probability, the reading the published
     literature uses. Needs a playoff-odds simulation over the remaining
     schedule. Data confirmed available: 11 distinct pairings across weeks
     1-14, and Sleeper rosters carry `wins`/`losses`/`fpts` to seed it. Live
     window to build and validate it against real standings is **weeks 8-11**
     — before that the schedule sample is too thin, after it the playoff
     picture is largely decided and the feature answers a question already
     settled.
   - **Win-probability lineups** — optimise for win probability (high floor
     favoured, high ceiling as underdog) rather than points. Needs a
     per-player weekly score VARIANCE this project has never estimated — the
     same missing ingredient leverage weighting needs. Gate: run
     `scripts/backtest_weekly.py` on 2024 AND 2025 first, the same standard
     the matchup adjustment was held to and failed; do not build the variance
     model until it clears that bar out of sample.
7d. **Deferred minors from Phase 5, triaged as non-blocking, not as
   non-existent** — pick up if touching the same code:
   - Two near-duplicate `last_scoring_week` fallback note strings; templatize
     if a third case appears.
   - `playoff_round_type` 0/multi-week semantics live in a comment, not a
     named constant.
   - `week_weights`'s `weeks` param lacks the `Iterable[int]` type hint the
     brief specified.
   - Weighting ternary was briefly duplicated between `horizon_total` and the
     `own` dict; Task 4 folded it into `best_drop`, so this is closed but the
     pattern (a brief time-boxing a duplication) is worth watching for.
   - `effective_weeks`' all-zero-weight and out-of-horizon-key behaviour is
     sane by inspection; the out-of-horizon case now has a mutation-driven
     test (closed 2026-09-02, commit `e89cf31`), the all-zero case does not.
   - Pinned-mode empty board prints the generic "trade search for X" header
     rather than a return/cost-specific one — cosmetic, a `render_trades`
     signature gap, surfaces only on a genuine no-trade-found pin.
   - `load_league_users` fetches twice per `trades` call (owner name +
     opponent-name map); both cache-guarded, YAGNI to unify for one command.
   - Printing the trade/waiver FLOOR value on an empty board (making the
     "nothing clears it" claim checkable) is a cross-cutting call for both
     commands together, not a Phase 5 defect — decide once or not at all.
8. **Phase 3.7 — the `DataTable` swap** (§19). Offseason. Carries a decision to
   take FIRST: `html.Table` or `dash-ag-grid`. **It is also the trigger for the
   deferred `board.py` fold** — 3.7 is the point where a board change would
   otherwise be written twice, which is the only reason to pay that cost.
9. **Bench-mode ordering** (§14) and **tier-not-ranking awareness** (§15) are
   both still true and both still unfixed. Neither is actionable without either
   an upside model or a confidence interval — §15 option 3 is the honest fix and
   `backtest.py` can now produce its input.
10. **Deferred minors** (§9) — two left, both trivial, neither load-bearing.
11. **Task 1 (Yahoo OAuth)** — still no reply, 1–2 weeks quoted on 2026-08-24.
   Now costs MORE than it did: season mode wants that roster every week.

**Cut 2026-09-01, do not rebuild:** Phase 2's SQLite draft log. Crash recovery
mid-draft is moot with the drafts over, and "it is season mode's persistence
layer anyway" is not a reason to inherit a draft-log schema — season mode's
persistence is one snapshot table and is specced with the thing that needs it.

**Kept 2026-09-01, reversing this file's own earlier instruction:** the
`yahoo-mock` and `sleeper-mock` blocks in `config.toml`. `calibrate.py` reads
`num_teams` from the named league, so deleting `yahoo-mock` would destroy the
ability to re-score the three transcribed 12-team mocks — the only non-circular
calibration data the project has. `sleeper-mock` is one `draft_id` edit from
serving a fill-in draft. The reasoning now lives in `config.toml` beside them.

## Deadlines

| Event | Date | Note |
| --- | --- | --- |
| Sleeper draft | ~~Sept 1~~ | **DONE** — 180 picks, seat 5 |
| Yahoo draft | ~~Sept 1~~ | **DONE** — hand-entered, no feed |
| **NFL week 1** | **Sept 9 2026** | first live use of season mode. **start/sit is BUILT and checked**; 4b (matchup) is what remains and is not a blocker for week 1 |
| Yahoo API approval (applied Aug 24, quoted 1–2 weeks) | overdue | no reply as of Sept 1 |

---

**The closed sections (§0-§3, §5-§7, §11-§13, §16-§18, §20-§21) moved to
`docs/todo-archive.md`** on 2026-09-02, keeping their numbers. What is left
below is open.

---

## 8. Task 1 — Yahoo OAuth handshake (BLOCKED, external)

Blocked on Yahoo's approval of the Fantasy Sports API application submitted
2026-08-24. `.env` already holds the consumer key, secret, and league id.

**Correction 2026-08-25: `scripts/yahoo_auth.py` DOES NOT EXIST.** This file
previously said it was "written and untested against a live account." It was
never written and never committed — `git log --all -- 'scripts/*'` is empty and
nothing in `.gitignore` covers it. Deliberately still not written: an untested
OAuth handshake against an API nobody can reach is speculative work, and the
yfpy constructor arguments cannot be verified without access anyway.

When approval arrives:
1. **Write** `scripts/yahoo_auth.py` first — it does not exist
2. Expect the yfpy constructor arguments to need adjustment — they change across
   versions and could not be verified without access. See
   https://yfpy.uberfastman.com/query/
3. Confirm `get_league_draft_results()` returns cleanly with 0 picks pre-draft —
   that is the strongest signal the Phase 2 feed will work
4. Record the real league id, team count, and scoring in `CLAUDE.md`

**Not on the critical path.** Manual entry covers the Sept 1 draft. This matters
for season mode, which is four months of use versus one draft night.

---

## 9. Deferred minors — triage in the final review

All recorded with context in
`.superpowers/sdd/2026-08-24-phase-0-1-draft-engine/progress.md`. The two temp-file
tests and the redundant `_write_cache_atomic` param are DONE (section 3). What is
left:

- Suffix stripping in `norm_name` strips once, not in a loop. Harmless for real
  names; a malformed "X Y Jr III" keeps the inner suffix.
- ~~A self-mark contradicted by a feed pick from another seat is never
  dropped.~~ **DONE 2026-08-25.** `_claims_overruled_by_feed` drops a claim the
  feed attributes to a different seat, and `_render_tick` prints a standing
  `CLAIM OVERRULED` banner naming the player and the seat — silently editing the
  user's own roster would be a "degrade, never fabricate" violation. The player
  stays in `drafted` (he really is gone, just not to you). Two guards, each of
  which turns the feature into a roster-wiping disaster if dropped, and both
  covered by tests and mutations: an unset `my_slot` overrules nothing (every
  slot differs from `None`), and a pick with no `draft_slot` attributes to
  nobody. Verified by replaying the real 180-pick mock.
- `_stdin_reader`'s EOF warning path is never driven end-to-end through a real
  thread.

---

## 10. Later phases (not started, own spec cycles)

- **Phase 2** — Yahoo feed adapter (gated on approval) + SQLite draft log
- **Phase 3** — Dash web UI reading the same `value.py`
- **Phase 4** — season mode via `nflreadpy`. **Without the waiver notify-bot** —
  the league uses FAAB with scheduled batch processing, so claims resolve
  simultaneously and a same-day alert gives no timing edge.
- ~~**Phase 5** — trade finder.~~ **DONE 2026-09-02**, see item 7 above. The two
  slices left out of its spec (leverage weighting, win-probability lineups)
  are item 7c above, not here — they were deferred, not unstarted scope.

---

## 19. The web board's APPEARANCE — not in any phase, raised 2026-08-27

The board is functionally rehearsed and visually untouched: **two style
declarations in the whole app** (`width: 20rem` on the league dropdown, monospace
cells) and **no `assets/` directory**. Everything else is default Dash chrome.

**It needs no new dependency, which is the point.** Dash auto-serves any file in
`ffhelper/assets/`, so a plain `.css` file there is applied with no config, no
build step and no package. "Make it look good" is normally where a React/Tailwind
toolchain arrives; here it does not have to.

Fully controllable now: fonts, colour, dark mode, spacing, page chrome. The
banners, clock and roster panel are `html.Pre` and style trivially. `DataTable`
exposes `style_cell`, `style_header`, `style_data_conditional` (already carrying
the tier bands), `style_table`, and a `css` escape hatch.

**The one real ceiling is `DataTable`'s fixed internal DOM.** Custom row markup —
a true `-- TIER 2 --` separator row, two-line rows, inline badges, sparklines —
cannot be done inside it. Replacing it with a hand-rolled `html.Table` is the
upgrade path, and it is already cheap **by design**: `board_rows()` returns plain
dicts precisely so that swap touches no tested logic (see the `ponytail:` comment
on `tier_styles`).

**STATUS 2026-08-28: the CSS half is DONE.** `ffhelper/assets/board.css` plus a
two-column layout, cards, a sticky header, dark palette, position colours and the
tier badge all shipped. `logo.png` is the user's own artwork — the first logo was
an NFL trademark and was removed before commit, since the repo is public.

### The deferred half is now PHASE 3.7. Do not let "3.6 complete" bury it.

The restructure was split in two at the start of the 2026-08-28 session, on a
measured cost, and **only the first half shipped.** Phase 3.6 is complete as
scoped; the rest is Phase 3.7 and is listed here so merging 3.6 does not read as
finishing the appearance work.

**The blocker for all of it is one thing: `DataTable` cannot hold custom row
markup.** Replacing it with a hand-rolled `html.Table` unlocks every item below
at once, and nothing below is worth doing separately.

**Why it is expensive, and it is not the markup.** The click path IS the
DataTable:

- `Input("board", "active_cell")` is how a click marks a player
- `dash.State("board", "data")` resolves that click to a row id
- `Output("board", "active_cell") -> None` is the fix for the repeat-click no-op
  the user diagnosed live on 2026-08-27
- `style_data_conditional` is how POS_STYLES, TIER_STYLES and CLASH_STYLES land

An `html.Table` has none of those props, so the entry mechanism is rebuilt from
scratch on pattern-matching callbacks and **needs its own live rehearsal** —
against the exact defect class the Aug 27 mock already found once.

**Phase 3.7 scope, all of it gated on that swap:**

1. **Real `-- RB · TIER 2 --` separator rows.** The badge is the DataTable-shaped
   answer; a separator row is the right one.
2. **Per-severity banner colours.** STALE amber, CLAIM OVERRULED red. Needs
   `banner_lines` to return structure instead of a newline-joined string, which
   is tested, mutation-covered code — so it is a real change, not a CSS tweak.
3. **SURV as a bar behind the number.** Also the honest rendering: §15 says read
   SURV as an ordering, and a bar reads as ordering where `71%` reads as
   precision.
4. **`MODEL+` / `MARKET+` in colour**, so divergence stops hiding in a text
   column.
5. **Live page title** — `🏈 pick 42 — sleeper-main` in the tab.
6. **Two-line rows / inline badges** (team, bye, DIV on a second line).

**Decide `dash-ag-grid` vs `html.Table` at the START of 3.7, not during it.**
The suite now warns on every run:

    DeprecationWarning: dash_table.DataTable will be removed from the builtin
    dash components in a future major version. We recommend dash-ag-grid.

So the swap is coming regardless of appearance. But **`dash-ag-grid` is a new
dependency**, and the draft-mode dependency rule is `requests`, `yfpy`, `dash`
and nothing else. `html.Table` is stdlib-shaped and keeps that rule; ag-grid
buys sorting/virtualisation the board does not need for 40 rows. Weigh it once,
record the answer, do not re-litigate mid-build.

**`board_rows()` returning plain dicts is what keeps this cheap** — the swap
touches no tested ranking logic. That was designed in deliberately; see the
`ponytail:` comment it still carries.

### How to land it: fork on TIME, not on LEAGUE

Asked 2026-08-28: could Yahoo keep `DataTable` (it needs click entry) while
Sleeper gets the custom table (its feed supplies the picks), switched by the
league dropdown?

**Technically yes, and cleanly** — `board_rows()` returns plain dicts with a
single consumer in `app.py`, and rendering both while hiding one avoids
`suppress_callback_exceptions` entirely, the same trick the `override` button
already uses.

**Rejected anyway, on this project's own recurring lesson.** The six `"board"`
references across two callbacks become twelve across four, and every later board
change gets built twice — Phase 3.5's opponent needs and bye clustering both
reach into the board. `board.py` is already one deliberate copy of the render
path, guarded by an agreement test and recorded as debt. A second copy of the
thing you stare at while drafting is worse.

**And the benefit expires exactly when it would be collected.** The reason to
keep `DataTable` for Yahoo is that its click path is REHEARSED. Phase 3.7 is
scheduled after BOTH drafts, so by then there is no rehearsal left to protect and
an entire offseason to rehearse a new one. That is a permanent maintenance cost
bought to protect something that has stopped needing protection.

The axis is also wrong: the two leagues do not want different tables, they want
the same table under different interaction pressure. An `html.Table` clicks fine
— it simply has not been proven yet.

**So take the same de-risking on a better axis:**

1. Build ONE `html.Table`, with click-to-mark.
2. Keep the `DataTable` path behind a config flag (`board_table = "datatable" |
   "html"`) for exactly one cycle, so a bad rehearsal is **one line to revert**.
   Same shape as `adp_source`, which is already documented as one config line.
3. Run one live mock on the new table. Yahoo-shaped is the harder test, since
   every pick is clicked.
4. **Delete the flag and the `DataTable` branch** once that passes.

The difference from the per-league fork is a deletion date. A temporary
dual-path with a scheduled removal is a migration; a permanent one keyed on
league is a second implementation to maintain forever.

**If step 4 slips, that is the finding** — write down why rather than letting the
flag calcify, which is how a migration quietly becomes a fork.

**Do it AFTER Sept 1, or keep it purely additive before.** Appearance work cannot
break the engine — it never touches `value.py` or `data.py` — but the board has
just been rehearsed under a clock, and changing where things sit un-rehearses the
muscle memory that rehearsal bought. Colours, fonts and dark mode are safe any
time; moving or restructuring controls is not.

**Where it belongs:** its own small phase, not 3.5. Phase 3.5 (opponent needs,
bye clustering) reaches into the board's LOGIC and is the risky one; this is
presentation only and shares none of that risk.

---

## 14. Bench-mode ordering is honest but still weak — OBSERVED LIVE 2026-08-27

Once every starting slot is full, `is_bench_only` fires and the board says so
rather than presenting the residual order as advice. The K/DEF demotion stops it
recommending a second kicker. But the ordering underneath is still just static
VBD, which by the late rounds favours whatever is least far below replacement —
now TEs instead of kickers.

**Seen in a real draft now, not just predicted.** In the live Sleeper mock the
last four recommendations at seat 5's turns were all tight ends (Brenton Strange
twice, Hockenson, Schultz) with a TE already started and a second on the bench.
All four carried the `BENCH` flag, so the tool was saying "trust yourself here"
exactly as designed — but a third and fourth TE is what static VBD produces when
TE has the shallowest replacement of any position.

**The position filter added in Phase 3 Task 7 is the honest mitigation**: in bench
mode, filter to RB or WR and pick your own upside. That is a human making the call
the data cannot, which is what the banner already asks for.

The tool has no model of bench value: upside, handcuffs, injury insurance. The
banner tells the user to trust themselves. Fixing it properly needs either a
handcuff model (which RB backs up a starter you roster) or an explicit
variance/upside signal, and projections do not carry either.

---

## 15. The top of every position is a TIER, not a ranking — OPEN, hits both drafts

Found while backtesting ESPN (section 13). **This is not a bug report. The code
is doing what it should; the question is how much confidence the input earns.**

### The false start, recorded so it is not repeated

The first version of this section said "projections cannot rank QBs", built on
2025 alone: Rotowire's preseason top-12 QB ordering came out at Spearman
**−0.287**, worse than a coin flip, and ESPN's was −0.232 independently.

**That was overreading one season.** Sleeper serves preseason-frozen projections
back to 2021 (verified: 100% full-slate for 2021–2025; 2020 fails), so the claim
was checkable, and checking it killed it:

| Rotowire, top-12 Spearman vs actual finish | 2021 | 2022 | 2023 | 2024 | 2025 | mean |
| --- | --- | --- | --- | --- | --- | --- |
| QB | +0.273 | +0.273 | +0.657 | +0.727 | **−0.287** | **+0.329** |
| RB | −0.210 | +0.720 | +0.259 | +0.126 | +0.392 | +0.257 |
| WR | +0.455 | +0.413 | +0.245 | +0.490 | +0.280 | +0.376 |
| TE | +0.357 | +0.552 | +0.063 | +0.587 | +0.119 | +0.336 |

**2025 was a QB outlier, not the normal state** — Burrow, Jackson, Daniels and
Murray all missed significant time. QB's five-year mean is second-best of the
four positions. There is nothing specifically wrong with the QB board.

### The finding that actually survives

Read the table by column instead of by row. **No position ranks its own top 12
well, in any year.** Means run +0.26 to +0.38; every position has a near-zero or
negative season (RB −0.210 in 2021, TE +0.063 in 2023, QB in 2025).

Widen the pool and it improves — QB top-48 in 2025 reaches +0.714, and RB/WR/TE
top-N beat their own top-12 in most years. Part of that is range restriction and
therefore a mathematical inevitability, not a data failure. But the operational
consequence is the same either way: **within the top tier of a position, the
ordering carries very little information.** The gap between projected RB1 and RB6
is real; the order of RB1 through RB6 is close to noise.

### What this means for the two drafts

`CLAUDE.md` records a validated Yahoo strategy: **"take QBs ~15 picks earlier"**
(QB1 at pick 18 vs 24) and **"prefer volume passers — Burrow rises to QB2 while
Jackson leaves the top four."**

**The arithmetic is still correct and is not in question.** Yahoo's
0.25/completion really is worth ~78 points on Allen's volume, and it really does
favour pocket passers. What the five-season table says is that the *positional*
call (QB is scarcer in Yahoo, so move it up) is far better supported than the
*identity* call (Burrow specifically over Jackson specifically). Take the tier
early if the board says to; do not agonise over which name inside it.

### What to do about it

The tool **already computes the right answer and under-uses it**: `tier` is a
per-position column derived from real gaps in projected points. The board sorts
by VONA within a flat ordering, but the tier column is what deserves the weight
near the top.

Options, cheapest first:

1. **Awareness only.** At the top of the board, treat same-tier players as
   interchangeable and break ties on your own read. Zero cost, and given the
   Sept 1 deadline this is almost certainly the right call for this year.
2. ~~**Make the tier visually dominant** in the Phase 3 Dash UI rather than a
   column.~~ **DONE 2026-08-27, then REDONE 2026-08-28.** The banding shipped
   first and was wrong by construction: the board interleaves positions by VONA,
   so a `(pos, tier)` group is **not contiguous** — RB tier 4 sat at rows 7, 8
   and 10 with a WR between — and two alternating shades can only group ADJACENT
   rows. Found by the user reading a real board: "you have to double check the
   position and tier of that position." Replaced by a **tier badge coloured by
   position**, so the group travels with the row instead of sitting behind it.

   **And the number itself was wrong.** Tiers were computed from `available`, so
   the labels drifted upward all draft — 32 of the top 40 rows carried a wrong
   tier by pick 20 and **all 40 did by pick 160**, where a preseason tier-11
   receiver rendered as "tier 1" for being the best one left. Same defect as
   §11 #3, one line below it. Fixed by drawing tiers from the full pool;
   `value.py` unfrozen a second time on a measured zero change to ordering.
3. **Give the board an interval instead of a point estimate.** The honest fix:
   `backtest.py` can now produce the historical projection-vs-outcome error
   distribution per position, which is exactly the input a confidence band needs.
   Offseason work, not a 6-day job.

**Do not** discount a position's VBD by a hand-picked factor. It invents a number
the data does not supply, and the data says the problem is not position-specific.

### Reproducing this

`scripts/backtest.py` prints the projected-vs-actual name table automatically for
any position whose rank correlation comes out negative — it self-selects, no flag
needed. The multi-season table above is a five-line variation on the same
loaders; fold it into the script if this gets picked up again.
