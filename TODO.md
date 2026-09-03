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
7. **Phase 5 — trade finder. IN PROGRESS, branch `phase-5-trade-finder`.**
   Spec and plan committed; **tasks 1-4 of 9 done and committed, 472 tests.
   RESUME AT TASK 5** — but read 7a FIRST, it is an open defect.

   The SDD ledger at `.superpowers/sdd/2026-09-02-phase-5-trade-finder/progress.md`
   is the authority on what is finished; task briefs 1-9 are extracted beside it.

   | | |
   | --- | --- |
   | spec | `docs/superpowers/specs/2026-09-02-phase-5-trade-finder-design.md` |
   | plan | `docs/superpowers/plans/2026-09-02-phase-5-trade-finder.md` (9 tasks) |
   | done | 1 playoff calendar, 2 `week_weights`, 3 weighted `horizon_total`, 4 `best_drop` |
   | left | 5-7 `trade.py` (1-for-1, 2-for-1, 2-for-2 + pin), 8 the `trades` command, 9 acceptance + docs |

   **Nothing is half-finished** — every task ends at a commit and the suite is
   green (472 passed; the 1 warning predates this branch, confirmed against
   `main`).

   **The mutation run has NOT been done for tasks 1-4.** It is Task 9 step 3,
   deliberately, because `mutate.py` rewrites source in place and must run alone
   on a green suite. 37 `season.py` targets are staged, each verified to match
   exactly once — but a static uniqueness check is weaker evidence than a run,
   and this project has been bitten four times by mutation tooling reporting
   success while checking something else.

   **Shipped behaviour CHANGED and has not been re-run live:** `waivers` now
   sums to week 17 rather than 18 and applies week weights, so its numbers move.
   Task 9 re-runs it. **Do not merge before that.**

7a. **OPEN DEFECT, parked with a ruling — FIX THIS FIRST NEXT SESSION.**
   Found by Task 4's reviewer, Important, and it was mandated by the plan:
   `roster_upgrade` calls `best_drop([*roster, candidate])`, so **`best_drop` can
   return the CANDIDATE HIMSELF as the drop** — "cut the player you were trying
   to add", which is not a coherent recommendation. Two consequences:
   - `gain` is then exactly 0.0 by construction (the roster is unchanged), and
     the tie-break prefers the candidate whenever his own points are lowest.
   - `kept` at `season.py:290` then filters nothing, so `weeks_started` is
     computed against a 12-player superset rather than the 11-player post-swap
     roster. Wrong, not merely cosmetic.

   **Not reachable in shipped `waivers` under default config** — a 0.0 gain can
   never clear `close_call_points * sqrt(weeks) >= 3.0` — which is why it is
   parked rather than treated as live breakage. **It becomes reachable the
   moment Task 5 lands**, because the trade search calls `best_drop` DIRECTLY
   with no floor in front of it.

   **Ruling: fix in `roster_upgrade` only, never in `best_drop`.** `best_drop`
   is correctly general — in a real 2-for-1 a just-received player genuinely can
   be the right cut — but `roster_upgrade`'s contract is "who do I cut to make
   room for this add" and it must never answer "the add". After the call, if
   `drop.sleeper_id == candidate.sleeper_id`, re-run restricted to `roster`.
   Cost if wrong: the guard is unnecessary and costs `len(roster)` extra lineup
   evaluations on a path that already does 15 of them.

7b. **What Phase 5's probes established, before any code** (measured 2026-09-02
   against the live league; all of it is in the spec):
   - **1-for-1 trades are empty.** 2475 pairs across 11 opponents, 11 help both
     teams at all, and **zero clear the 12.7-point floor.**
   - **2-for-2 is where the surplus is** — 49 clear both floors across three
     opponents. Only a multi-player swap changes how many bodies a side carries
     at a position, which is what creates the surplus.
   - **The whole-league board is ONE row** (best-per-opponent, all shapes, 330s).
   - **THE ACCEPTANCE PRIOR IS DEAD.** `CLAUDE.md` said to rank by a
     transaction-history prior. The league has made **3 transactions all season,
     zero trades, and has no previous season.** Nothing replaces it.
   - **A prefilter that looked provable is unsound** — it silently dropped
     **22 of 49 real trades**. Sound for 1-for-1 only. Do not reintroduce it.
   - **`LAST_REGULAR_WEEK = 18` was wrong for this league** and shipped that way
     in `waivers`. `playoff_week_start: 15` + `playoff_teams: 6` ends the season
     at week 17. `trade_deadline: 11`, also read rather than assumed.
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

## 0. FINAL REVIEW IS DONE — read it first

**`docs/reviews/2026-08-25-phase-1-final-review.md`**

(The full build ledger — every task's commits, findings, and fix rounds — is at
`docs/reviews/2026-08-25-phase-1-build-ledger.md`. Both were copied out of
gitignored scratch so they survive.)

Verdict: **merge-ready as an engine, NOT draft-ready as shipped.** Four real
fixes, all small.

**All of them are now done** — branch `draft-night-fixes`, 151 tests. Its
finding #4 (survival) was investigated and deliberately rejected; see section 2.

---

## 1. DRAFT-NIGHT BLOCKERS — ALL DONE 2026-08-25

Every new test below was verified failing against pre-fix source before the fix
landed. `git stash push -- ffhelper && pytest -k <name>` is the check.

- **1a. The STALE banner could never fire — a dead feed looked healthy.** DONE.
  `fetch_json` gained `stale_ok: bool = True`; `SleeperFeed.get_picks` passes
  `False`, so a failed poll raises into the loop's existing guard instead of
  replaying the last good picks.
- **1b. The manual-input drain was the one unguarded per-tick statement.** DONE,
  root cause included: `str.isdigit()` is True for `'²'` but `int()` refuses it,
  so the predicate is now `str.isdecimal()`, which is exactly the set `int()`
  accepts. The drain is guarded **per command, not per drain**, so one bad line
  no longer discards the rest of the queue.
- **1c. Yahoo league config.** DONE — `[league.settings]` block written from the
  settings recorded in `CLAUDE.md`. `preflight --league yahoo-main` runs clean
  but for `draft_slot`: 10 teams, correct roster slots, `pass_td=6.0`, 632
  players. Only `league_id` is still a placeholder (section 7); nothing reads it.

### Also found this session — NOT in the review

**The opening board ranked four kickers in the top ten, above McCaffrey.** Found
by running `build_board` against the real 632-player pool. VONA compresses toward
0 for everyone whenever the next pick is a pick or two away — at pick 1, and on
**both sides of every snake turn**, so it would have hit on draft night. Below
the top four the board was sorting on VONA differences of 1e-12 to 5e-3, then on
negative-VONA magnitudes that are not comparable across positions (a kicker 2
points off the best kicker scores -2; McCaffrey behind the expected best RB
scores -20, so the kicker won).

Sort key is now `(-max(round(vona, 1), 0.0), -r.vbd)`: round to the tenth of a
point the board displays so the sort agrees with the numbers on screen, and floor
at 0 because every negative VONA says the same thing — waiting is free — and once
waiting is free, value decides. **`Row.vona` itself is untouched**; only the sort
key is floored, so the existing negative-VONA regression test still holds.

Boards at picks 27 and 51 are byte-identical to before. Only the compressed
regime changes.

---

## 2. REOPENED AND SHIPPED 2026-08-26 — conditioning was right after all

**Read the 2026-08-26 note at the end of this section first.** The 2026-08-25
rejection below stands as a record of correct reasoning on the evidence then
available, and the reopen condition it set was met exactly as written.

## 2 (historical). CLOSED 2026-08-25 — `survival_prob` stays unconditional.

The final review's finding #4 said the SURV column is wrong for fallers, citing
Nico Collins and George Pickens at pick 61 reading **SURV 0.00%** with inflated
VONA (60.9, 44.6) against a third place of 11.3.

**Investigated and rejected as a fix.** Three things the review got wrong:

**The scenario was constructed, not observed.** "Live check, real pool, pick 61
with two WRs slid past their ADP" is a board state the reviewer built by hand.
No draft has ever been run with this tool — Task 13 is still pending. Rebuilding
the same state reproduces 60.9 / 44.6 / 11.3 to the decimal.

**The gaussian tail is well calibrated.** FFC's `low` field is the latest pick a
player was ever taken across ~836 real drafts each. Over 123 players with
adp <= 120 (~100k player-drafts):

| | |
| --- | --- |
| gaussian prediction for worst fall over 836 drafts | 3.0 sigma |
| **observed median worst-case fall** | **2.9 sigma** |
| players ever falling >= 5 sigma | 3 |
| players ever falling >= 8 sigma | **0** |

Collins at pick 61 is 13.8 sigma. It has never happened.

**The frequency does not justify the blast radius.** The fabricated 0.00% starts
at 2 sigma (an 11-pick slide), so it is not purely theoretical — but expected
available players at >= 2 sigma past ADP run **0.02 (pick 25) to 0.11 (pick 100)
per board state**, i.e. one such row every few drafts. There are normally 1–5
fallers on the board and nearly all are barely past ADP and read fine.

Also note: **the shipped code cannot divide by zero.** It is unconditional, so
there is no division. The 8.3-sigma underflow is a property of the *proposed*
conditional fix only.

### Options costed and rejected

- **`S(at)/S(current)`** (the review's own suggestion) — returns 0.01% for
  Collins, barely different from the 0.00% it was meant to fix, because a
  gaussian's hazard rate explodes in the tail. Divides by zero past 8.3 sigma.
- **Re-anchor mean+spread to `current_pick`** — works (Collins 0.00% -> 12.98%,
  verified no-op for non-fallers) but flattens every faller to the same number
  regardless of how far they fell.
- **Conditional logistic**, variance-matched at `s = stdev*sqrt(3)/pi` — the best
  of the three: closed form, cannot underflow, keeps the gradient (Odunze 8.00%,
  Collins 0.36%, JSN 0.00%), top-20 board overlap 20/20 at picks 61 and 75. But
  17/20 at pick 27 — it moves three players in and out of the top 20 at a real
  pick, to fix a row seen once every few drafts. Bad trade on a 7-day deadline.

**If this is ever revisited, the conditional logistic is the option to take, and
it needs validation data first** — historical per-draft pick results, which FFC
does not expose but Sleeper's completed drafts do. Offseason work.

### REOPENED AND SHIPPED 2026-08-26 — the condition above was met exactly

**The validation data arrived**: three transcribed Yahoo mocks, 540 picks, rooms
measurably not list-followers. And it said the problem is far bigger than the
faller rows this section was arguing about.

**What 2026-08-25 got right:** the option (variance-matched conditional
logistic), the rejection of `S(at)/S(current)` on a gaussian, and refusing to
ship on a constructed board state. All three held.

**What it got wrong: the frequency.** This section costed the fix as repairing
"one row every few drafts" — the extreme fallers. But the unconditional form is
smaller than the conditional one for **every player on every board**, not just
fallers, because every player being evaluated has by definition already survived
to the current pick. So the bias is systematic, not tail-only:

| model says | unconditional (shipped until now) | conditional logistic | ideal |
| --- | --- | --- | --- |
| 0-20% | 46% | **30%** | 10% |
| 20-40% | 60% | **49%** | 30% |
| 40-60% | 72% | **64%** | 50% |
| 60-80% | 83% | **80%** | 70% |
| 80-100% | 93% | 91% | 90% |

**Weighted calibration error 0.145 → 0.081.** No fitted parameters — nothing is
tuned to these three drafts; it is the same distribution asked the right
question.

**Blast radius measured before shipping, which is what made it safe a week out:**
across board states at picks 2, 19, 42 and 79 on the real `yahoo-main` pool,
**0–3 of the top 10 rows reorder and no new player enters the top 10 at any of
them.** VONA raises survival proportionally within a position, so comparisons
survive. The 2026-08-25 objection — "17/20 at pick 27, bad trade" — was measured
on the *conditional gaussian*, not on this.

Gaussian and logistic tie on accuracy (0.081 vs 0.082). The logistic ships
because its tail degrades instead of lying: a gaussian's hazard explodes, so
`S(at)/S(from)` divides by ~0 and reports a fabricated 0.00% for exactly the
player most obviously still fallable.

`value.py` was unfrozen once, deliberately, for this. Covered by three new tests
(each verified red against pre-fix source) and five mutations.

---

## 3. CHEAP FIXES — ALL DONE 2026-08-25

- `tunables.divergence_flag_slots` was a **silent no-op**. DONE — threaded into
  `render(..., divergence_flag_slots)`; `cli.py` no longer hardcodes `>= 25`.
- `current_pick` derived from a set count, so a malformed pick row skipped by
  `parse_sleeper_picks` permanently shifted the horizon by one. DONE — now
  `max(len(drafted), highest pick_no) + 1`. (The review's suggested formula was
  off by one: `pick_no` is the number *of* that pick, so the `+1` is required.)
- Redundant `cache_dir` param on `_write_cache_atomic`. DONE — deleted, it reads
  `path.parent`.
- The two "no leftover temp files" tests passed identically on pre-fix code. DONE
  — they asserted steady state, not atomicity, because `os.replace` consumes the
  temp file either way. One now monkeypatches `os.replace` to raise and asserts
  the mkstemp file is unlinked, which is the path the handler actually exists
  for; the crosswalk duplicate is deleted (both callers share the same function).

**RESOLVED 2026-08-25 — `-<name>` takes one mark back.** This previously read
"know before you draft": a mismarked player stayed in `my_roster` forever, and
the only remedy was `u`, a single shared LIFO, so correcting a mistake from ten
picks ago meant ten undos and nine retypes. Unusable against a pick clock in the
Yahoo draft, where all ~150 picks are hand-entered.

`-<name>` now reaches one player directly. It searches **only hand-marked
players**, which both cuts keystrokes (`-robinson` resolves outright when only
one Robinson was marked) and makes it impossible to "un-draft" a feed-reported
pick, which would put a genuinely gone player back on the board. Disambiguation
still applies when the narrowed set is itself ambiguous.

`u` restores the previous state verbatim, including whether the mark was claimed
as yours — `MarkDrafted._history` records prior membership rather than a delta,
which is why one history serves mark, claim and unmark with no direction flag.

**Still open (section 9):** a self-mark contradicted by a *feed* pick from
another seat is not dropped automatically. Only affects leagues that have a feed,
where self-marking is rarely needed.

---

## 5. Task 13 — live Sleeper mock draft (NEEDS THE USER)

**The highest-value remaining work, and now the only item with real risk.**
Running the real thing has caught **nine** defects that a fully green test suite
passed over — including a frozen pick counter that would have invalidated every
survival number in the Yahoo draft, and the kicker-sort bug found this session,
which a 150-test suite passed over completely.

Steps:
1. Create a free mock draft in the Sleeper app
2. Read the `draft_id` from the mock draft URL
3. Add a temporary `[[league]]` entry pointing at it
4. `python -m ffhelper.cli run --league mock` and let picks come in

Watch for: drafted players leaving the board; VONA reordering as position runs
develop; survival falling as your next pick approaches; the stale banner appearing
if wifi is cut for ~20s and clearing when it returns.

**Two things this session changed that only a live draft can confirm:**
- **The board at your turn.** The kicker fix is exercised exactly when your next
  pick is 1–2 away, which is every snake turn. Check the top of the board at your
  own pick, not just mid-round.
- **The STALE banner.** It was unreachable before, so it has never once fired.
  Cut wifi for ~20s and confirm it appears, then clears.

**Do this several days before Sept 1**, not the night before.

---

## 6. DONE 2026-08-25 — `draft_slot` set for both leagues

`sleeper-main` is slot 5, `yahoo-main` is slot 2. Both `preflight` runs are now
**OK**. Set by hand and never read from the API — the tool deliberately never
guesses this, because a wrong slot produces the wrong next-pick number for every
pick of the draft without ever erroring.

**The trap that nearly ate this:** the Yahoo value was edited but left commented
out (`# draft_slot = 2`), so it was still a TOML comment and preflight still read
NOT SET. If the draft order is reshuffled before either draft, re-check both —
and re-run `preflight` afterwards rather than trusting the edit.

---

## 7. DONE 2026-08-25 — Yahoo `league_id` is set

`league_id = "723573"`, alongside the `[league.settings]` block from section 1c
(10 teams, roster slots, full scoring, validated by `preflight`).

**Note the reversal.** This file previously said the id would stay in `.env`
because `config.toml` is committed to a public repo. That is no longer true, and
it is fine: a Yahoo league id is not a credential (reading a private league still
needs OAuth *and* league membership), and **nothing in the codebase reads `.env`
at all** — `grep -rn "environ\|getenv\|dotenv" ffhelper/ scripts/` is empty, so
the `.env` plan was never actually wired up. The consumer key and secret are the
real secrets and they stay out of `config.toml`.

Still dead config until Phase 2's Yahoo feed lands — there is no API access, so
the Yahoo board runs entirely on hand-entered picks.

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
- **Phase 5** — trade finder. `lineup_value()` was built standalone specifically
  so this inherits it. Will not output an acceptance probability; ranks by a
  transaction-history prior instead.

---

## 11. Task 13 — DONE 2026-08-25. Ten defects found, all fixed.

A full 180-pick Sleeper mock (`1398139615038185472`, seat 5) was run live, then
replayed offline against the fixed engine. Everything below was found by running
the code; a 162-test green suite passed over every one of them.

| # | Defect | Symptom the user saw |
| --- | --- | --- |
| 1 | `my_roster` matched on `roster_id`, which is `None` on EVERY mock pick | roster empty all draft, so MARG was meaningless |
| 2 | The sort ignored MARG entirely | "still suggesting Purdy after drafting Stafford"; three QBs |
| 3 | `replacement_points` drawn from the AVAILABLE pool | baseline collapsed as the draft drained; backup QB VBD +149 vs a true -32.5 |
| 4 | No bench model once starters fill | confident case for a 3rd QB, then a 2nd kicker |
| 5 | A second K/DEF floated to the top late | McPherson top-recommended for the last four picks |
| 6 | `divergence` included the `adp=999` sentinel (209 of 632 players) | Darren Waller +399 on a player with no ADP at all |
| 7 | `divergence` ranked globally, not within position | flag fired on 41.7% of top-20 rows, led by five kickers |
| 8 | No on-the-clock indicator | "maybe something that shows it is currently your pick" |
| 9 | Full screen clear every 5s regardless of change | "annoying with updates every 5 seconds" |
| 10 | Task 13 could not be run as written — a mock has a draft_id but no league | `load_sleeper_settings` had nothing to fetch |

Replayed across all 15 turns after the fixes: picks 5-68 unchanged (the early
board was already right), picks 77-116 lead with the QB that was actually needed
instead of a receiver who could not crack the lineup, picks 140-173 flagged
`[BENCH]`.

**Not defects, recorded so they are not re-investigated:**
- Parker Washington and Jayden Reed over their ADP is Rotowire genuinely
  projecting them above the market (212 vs DK Metcalf's 183). The no-blend rule
  working as designed — see section 13 for the second-source answer.
- Recommending Purdy after Stafford at picks 101-125 is legitimate: Purdy
  projects 363.2 to Stafford's 344.2 and lasted to pick 129.

---

## 12. Settle `adp_source` with a HUMAN mock — highest-value open item

`sleeper-main` is set to `adp_source = "sleeper"`. **This is a judgement backed
by a mechanism, not by a measurement.** One line in `config.toml` reverts it.

Measured against the Task 13 mock, survival calibration by ADP source:

| model says | FFC | Sleeper | ideal |
| --- | --- | --- | --- |
| 0-20% | 74% | 4% | 10% |
| 20-40% | 82% | 17% | 30% |
| 40-60% | 89% | 52% | 50% |
| 60-80% | 90% | 91% | 70% |
| 80-100% | 94% | 100% | 90% |

**That comparison is CIRCULAR** — the mock's CPU drafters pick off Sleeper's own
list (36% took the literal top of it; median rank taken was 2). It cannot say
which ADP predicts twelve humans.

What it DOES establish, and what is not circular:
- The model FORM is sound. Sleeper ADP calibrates near-perfectly using the
  *fitted curve* stdev the design calls a weak fallback, so the MEAN matters far
  more than the spread.
- The problem is a wrong mean, not a narrow one. Multiplying FFC's stdev by
  1.5/2/3/4/6 drags the bottom bucket from 74% to 4% but leaves the middle
  buckets stuck at ~87% at every k. Widening cannot fix a location error.
- Restricting to FFC's 267 rated players changes nothing (73/81/88/89/94), which
  kills the "synthesized-stdev tail" theory. The 247-vs-180 over-count by pick
  180 is real arithmetic but is NOT what breaks calibration.

**The argument for "sleeper" is mechanistic:** Sleeper shows its own ADP on the
draft board to all twelve drafters during the draft. They anchor on the number
in front of them; most have never seen FFC's.

**The cost:** Sleeper's `adp_ppr` folds in TE-premium leagues. TEs read ~20 picks
earlier than a flat-scoring league would take them (QB +0.4, RB -1.4 identical;
WR -9.7). Partly self-fulfilling, since the room sees that same skewed number —
but treat TE survival with suspicion until measured.

**To settle it:** run a mock with real people, then

    .venv/bin/python scripts/calibrate.py <draft_id> <your_slot>

It prints the table above for both sources. Pick whichever is closer to
10/30/50/70/90 and set `adp_source` accordingly. **Yahoo stays on `ffc`** — those
drafters are not in the Sleeper app.

---

## 12a. The human mock runs on YAHOO — set up 2026-08-26, ready to run

Sleeper's mock drafts are against CPUs; there is no public lobby of strangers.
Yahoo has one. So the human mock moves to Yahoo, which is a **better** rehearsal
anyway: Yahoo has no pick feed, so every pick is hand-typed — exactly the Sept 1
interface, at full length, under a real clock, for the first time.

### What it can and cannot settle — read this before drawing a conclusion

**It cannot settle `sleeper-main`'s `adp_source`.** Section 12's whole argument
for `"sleeper"` is a mechanism: Sleeper drafters are anchored on the ADP Sleeper
prints on their own draft board. A Yahoo room is anchored on **Yahoo's** ADP,
which is a third number the tool does not carry. Whichever source wins on Yahoo
says nothing about which one predicts the Sept 6 Sleeper room. Do not carry the
result across.

**What it does settle, and this is new:**

- **Whether the manual-entry interface survives a full draft under a clock.**
  ~180 picks typed by hand, with disambiguation and corrections, while the pick
  timer runs. Nothing has ever tested this. It is the Sept 1 draft's *only*
  interface, and it is a week out.
- **The first non-circular calibration the model has ever had.** The Task 13
  numbers are circular — CPU drafters picking off Sleeper's own list. Humans
  anchored on a *third* ADP are an independent test of the model FORM (is a
  gaussian around an ADP mean the right shape at all?), even though it cannot
  rank the two means for a Sleeper room.
- **`yahoo-main`'s `adp_source` directly**, which is on `ffc` and is the league
  drafting first, on Sept 1.

### Setup, done

- **`config.toml` has a `yahoo-mock` block.** Three lines to set from the lobby
  before starting: `num_teams`, `draft_slot` (random, only known at draft time),
  and `rec` (1.0 / 0.5 / 0.0 for PPR / half / standard). Scoring is copied from
  `yahoo-main`; it does not affect survival calibration at all — that is pure
  ADP — and only mildly reorders the board. Delete the block afterwards.
- **`scripts/calibrate.py` takes a `.draft/*.jsonl` journal** in place of a
  Sleeper draft id. Pick order is reconstructed from the order marks were typed,
  with taken-back and undone marks excluded from the numbering.
- **It refuses to score a log it cannot trust.** Journal pick numbers are only
  as good as the typing: miss one pick and every number after it shifts, which
  silently moves every survival horizon. So the picks claimed with `me` must
  land exactly on the seat's snake positions, or it prints both lists and stops.
  Same rule `backtest.py` applies to a projection source — degrade, never
  fabricate. Verified working on the Task 13 mock (reproduces 73/82/89/90/94 and
  4/17/52/91/100) and on a constructed journal, both directions.

### Running it

1. Join a Yahoo mock. **Note the team count and scoring from the lobby**, edit
   those into `yahoo-mock`, and note your seat once the order is drawn.
2. `.venv/bin/python -m ffhelper.cli preflight --league yahoo-mock` — cheap, and
   it is the only thing that proves the `draft_slot` edit actually took.
3. `.venv/bin/python -m ffhelper.cli run --league yahoo-mock`
4. Type **every** pick as it happens, `me <player>` for your own. Falling behind
   costs the calibration but not the rehearsal — and the tool will say so rather
   than score a drifted log. The journal replays on restart, so a config edit
   mid-draft is recoverable: ctrl-C, edit, restart.
5. `.venv/bin/python scripts/calibrate.py .draft/yahoo-mock-<date>.jsonl <slot>`

### The thing most likely to go wrong

**The clock.** Yahoo mock lobbies run short pick timers and the room drafts fast.
Typing 12 picks per round while also making your own is the actual experiment.
If it turns out to be impossible, that is the single most important finding this
mock can produce, and it is worth knowing on Aug 26 rather than Sept 1 — the
answer would be to widen `_handle_command`'s notation, not to hope.

### RUN 1 (2026-08-26): ABANDONED IN ROUND 1 — and it was our bug

Did not survive one round. Names typed took seconds to appear; five picks behind
almost immediately. It read like a slow terminal. **It was `_run`.**

`_run` ended each tick with `time.sleep(interval)` and drained typed commands
only at tick boundaries, so a name typed just after a tick waited up to a full
poll interval. On Yahoo that is `poll_seconds = 12` — **spent waiting on a feed
that does not exist**, in the one mode where the board can only ever change
because you typed something. Compounding over consecutive names is exactly the
"five picks behind" that was observed.

Fixed: the loop now blocks on the input queue (`_wait_for_input`) with the poll
deadline as a *timeout*, so a keystroke wakes it at once and the interval paces
the network and nothing else. **Measured on the real 632-player pool, yahoo-mock,
12 names typed at 3/sec: median 34 ms, worst 39 ms from keystroke to redraw.**
Was up to 12 000 ms.

Two things worth keeping from how this was found:

- **The first suspect was wrong and measuring killed it in one run.** `build_board`
  looked like the obvious culprit — VONA re-sorts a position list per candidate.
  It is **20 ms** on the full pool at every pick number tested. Never the problem.
- **The first version of the fix's test was vacuous and `mutate.py` caught it.**
  It asserted `all(0.0 <= t <= interval)` on the wait timeout, which a mutation to
  a constant `0.0` passes happily — and a 0.0 timeout is not "instant", it is a
  busy spin at 100% CPU. The assertion now pins the first wait at 0.0 (poll
  immediately on startup) and every later one to the interval.

### RUN 2 (2026-08-26): responsive, still not finished — and that is fine

"Much better and much more responsive." Also abandoned: **the lobby clock is 30s
a pick**, and with instant autopicks that is roughly one pick every eight
seconds across 12 seats.

**The mock lobby is the wrong draft to optimise for, and the arithmetic says so.**

| | teams | hand-entry burden |
| --- | --- | --- |
| Sleeper, Sept 1 6pm | 12, 90s | **none — it has a live feed** |
| Yahoo, Sept 1 7pm | 10, **90s+** (user-confirmed) | ~150 picks, ≈1 per 36s over a 90-min draft |
| Yahoo mock | 12, 30s + autopicks | ~180 picks, ≈1 per 8s |

Hand-entry matters for exactly ONE draft, and the mock demanded it 4× faster
than that draft will. Run 2 did not fail; it passed a harder test than the real
one. **Do not build for the 30s case.**

Built anyway, because both are cheap and both help the real draft:

- **Comma-batching.** `nacua, me chase, gibbs` is one round trip instead of
  three, which is the catch-up path if Sept 1 ever gets ahead of you. This is
  why the separate pick-counter resync command was NOT built — batching covers
  the same need without letting the pool go knowingly stale.
- **Every command in a batch now reports its own outcome.** The status line used
  to be overwritten per command, so `a, nobody` showed only the last result.
  That is invariant #3 broken in the mode that needs it most — a batch is
  exactly where a miss hides, because the screen still looks like it worked.

### Getting calibration WITHOUT live typing — `scripts/transcribe.py`

Live entry and calibration were coupled only by accident. Survival is measured
from the ORDER players left the board, and a finished results page carries that
order with no clock on it. So paste the board in afterwards:

    .venv/bin/python scripts/transcribe.py yahoo-mock <slot> results.txt
    .venv/bin/python scripts/calibrate.py .draft/yahoo-mock-<date>-transcript.jsonl <slot>

**A draft too fast to type into is still a measurable draft.** That closes the
gap that made runs 1 and 2 feel wasted.

Two guards worth knowing:

- **It refuses to write unless every line resolves to exactly one player.** A
  dropped or guessed line shifts every pick number after it. Position in
  parentheses does the narrowing (Bijan vs Brian Robinson).
- **Transcripts are written as `<league>-<date>-transcript.jsonl`, never
  `<league>-<date>.jsonl`.** The latter is the live board's own journal and
  `ffhelper.cli run` REPLAYS it on startup — a transcript under that name would
  silently pour a finished draft into the next live board. Caught by running it,
  not by a test.

### Does your own autopicking corrupt the calibration? No.

Asked during run 2, and worth recording because the intuition is reasonable and
the answer is not obvious. `calibrate.py` never reads `my_roster`. Your picks
enter only as the turn boundaries `cur`→`nxt` between which the ROOM's picks are
scored, and those come from your SEAT, not your choices. Your one autopick per
turn is one player among the ~11 taken in that window, and he is equally gone
either way.

**What does corrupt it is how many OTHER seats autopicked**, because Yahoo's
autodraft picks straight down Yahoo's ADP — the Task 13 circularity arriving by a
new route. So `calibrate.py` now prints **room discipline**: the median rank, in
ADP order, of the player each pick took, plus the share that took the top
available. Validated against the known-circular Task 13 mock, where it
reproduces the numbers recorded in section 12 exactly — median 2, 36% at top —
and fires ONLY on the Sleeper source, not on FFC (median 8), which is correct:
those bots were picking off Sleeper's list, not FFC's.

**Read that line before believing any table under it.**

### FIRST NON-CIRCULAR CALIBRATION — 2026-08-26, 12-team Yahoo mock, seat 8

180 picks, transcribed from Yahoo's results page in one pass (every row resolved
first try — defenses, kickers and suffixed names included).

**Room discipline: median rank taken 7 (ffc) / 5 (sleeper), 14–15% took the top
available.** The Task 13 bot mock read median 2, 36%. So this room was
substantially looser than a bot room — **the first calibration this project has
that is not measuring an ADP list against itself.**

| model says | FFC | Sleeper | ideal |
| --- | --- | --- | --- |
| 0-20% | 62% | **42%** | 10% |
| 20-40% | 84% | **57%** | 30% |
| 40-60% | 80% | **68%** | 50% |
| 60-80% | 85% | **79%** | 70% |
| 80-100% | 92% | 94% | 90% |

Two readings, and they point opposite ways on confidence:

1. **Sleeper ADP discriminated markedly better than FFC in a YAHOO room.** FFC is
   near-flat and not even monotonic (84% then 80%); Sleeper is monotonic across
   all five buckets. **This contradicts section 12's stated reasoning** — "Yahoo
   stays on `ffc`, those drafters are not in the Sleeper app" — which was a
   mechanism argument that has now been measured and lost. A plausible mechanism
   for the reverse: Sleeper's ADP is simply a much larger national sample, and a
   better-sampled consensus predicts *any* room better, Sleeper app or not.
2. **Both are badly calibrated in the same direction**: everything survives more
   often than predicted. When the model says 0-20%, 42-62% actually lasted. The
   survival model is systematically too pessimistic against this room.

**THIS IS ONE DRAFT. Per this project's own rule it is a hypothesis, not a
finding, and `yahoo-main` has NOT been switched off `ffc` on the strength of it.**
The mock is also 12-team half-PPR/4-pt-TD, while `yahoo-main` is 10-team with a
completion bonus — a different room shape as well as a different sample.

**Getting n=2 and n=3 is now nearly free, and that is the point.** A mock no
longer has to be typed into: join, let it run, copy the results page, transcribe.
Three more mocks is an evening's work with no clock pressure at all. **Do that
before changing `adp_source` for either league.**

### A FOURTH DRAFT, 2026-08-27 — 10-TEAM, and it changes nothing

150 picks, seat 1, the first **10-team** room measured (both previous sets were
12-team, so this is the first matching `yahoo-main`'s actual team count).

| model says | FFC | Sleeper | ideal |
| --- | --- | --- | --- |
| 0-20% | 49% | **23%** | 10% |
| 20-40% | 58% | 58% | 30% |
| 40-60% | 70% | **52%** | 50% |
| 60-80% | 87% | **72%** | 70% |
| 80-100% | 92% | 91% | 90% |

Weighted calibration error **0.051 (sleeper) vs 0.116 (ffc)** — same direction as
the n=3 result that moved `yahoo-main`, so it corroborates and nothing changes.

**DO NOT read the 0.051 as the model improving.** It is better than the pooled
12-team figure of 0.081, but this room was measurably more list-following
(median ADP rank taken 5, 15% at top, against the human mocks' 7/9/10 and
11-13%), and **a room that follows the list makes ADP look better calibrated by
construction.** Circularity flatters this number. It sits between the human mocks
and the Task 13 all-bot mock (median 2, 36%), so treat it as partially circular.

**The user asked whether rounds 4+ were autopicks. The metric cannot answer it.**
Split at the pick where they stopped entering: picks 1-96 read median 5 / 16.7%
at top, picks 97-150 read median 16 / 3.7%. That looks like the late rounds were
*less* list-following, which is almost certainly an artifact rather than a fact —
late in a draft most remaining players have no ADP at all, and autodraft fills
roster requirements (K, DEF, positional minimums) instead of walking the list.
**Room discipline is not a trustworthy measure after the ADP pool thins out.**
Recorded so the number is not quoted later as evidence of a human room.

### SETTLED 2026-08-26 at n=3 — `yahoo-main` moved to `adp_source = "sleeper"`

Three 12-team half-PPR Yahoo mocks, **540 picks, seats 8 / 11 / 2**, pooled.
Both mock and `yahoo-main` resolve to the same ADP format (`half-ppr`), so only
team count differs between the test and the league.

| model says | FFC | Sleeper | ideal |
| --- | --- | --- | --- |
| 0-20% | 68% | **46%** | 10% |
| 20-40% | 82% | **60%** | 30% |
| 40-60% | 83% | **72%** | 50% |
| 60-80% | 87% | **83%** | 70% |
| 80-100% | 92% | 93% | 90% |

**FFC spans 24 points across its entire range and is not monotonic — close to no
discriminating power. Sleeper spans 47 and rises in every bucket.** The pattern
held in all three drafts individually, not just pooled.

**Not circular:** room discipline was median ADP rank taken 7 / 9 / 10 with
11–13% taking the top available, against the Task 13 bot mock's median 2 and 36%.
These rooms were not following a list.

This **reverses section 12's "Yahoo stays on `ffc`"**, which was a mechanism
argument ("those drafters are not in the Sleeper app") that had never been
measured. A mechanism that loses to a measurement is just a hypothesis. The
likely replacement mechanism: Sleeper's ADP is a far larger national sample, and
better sampling predicts any room, Sleeper app or not.

**`sleeper-main` is unchanged, and this evidence does NOT directly validate it.**
It is **full PPR** (synced from the API: `rec = 1.0`, `pass_td = 6.0`), so it
resolves to `fmt = ppr` and reads Sleeper's `adp_ppr` — a different column from
the `adp_half_ppr` these half-PPR mocks tested. It stays on `"sleeper"` for its
original mechanism, which is far stronger there than anywhere else: that room
literally sees Sleeper's own ADP printed on the draft board while picking.
Confirming it properly would need full-PPR 12-team mocks, which is now cheap —
join, don't type, paste the results page.

### FIXED 2026-08-26 — the level error was a model-form bug, not the ADP mean

**Superseded by section 2's reopen note; the diagnosis below was wrong and is
kept because the wrong turn is instructive.** I concluded the level bias had to
be the ADP mean, having ruled out the spread. It was neither: `survival_prob`
was answering the UNCONDITIONAL question `P(X > at)` when the board only ever
asks about players who are demonstrably still available, i.e. `P(X > at | X >
now)`. The unconditional form is smaller by construction, so it was pessimistic
for every row on every board.

Conditioning cut weighted calibration error from **0.145 to 0.081** and shipped;
board ordering barely moves (0–3 of the top 10 across four pick numbers). What
remains after the fix is still pessimistic (says 0–20%, 30% survive) but is now
roughly half the error it was, and the residue may genuinely be the ADP mean.

**The lesson worth keeping: "not the spread" did not entitle me to "therefore the
mean."** Those were not the only two options, and the third one — the model is
computing the wrong quantity — was the actual answer. I had eliminated one
suspect and announced the verdict.

### Historical: both sources are badly wrong in LEVEL

Not a tie-break between sources — it applies to whichever one is chosen. **The
model says 0–20% and roughly half of those players survive.** The whole curve
sits ~25–35 points below reality, worst in the low band and nearly right at the
top (93% vs 90%).

Consequence, since survival feeds VONA: **the board systematically overstates the
cost of waiting, i.e. it leans toward reaching.** The error is largest exactly
for the players it says are least likely to last — the top of the board.

**Deliberately NOT fixed in code, on two grounds.** `value.py` is frozen until
both drafts are done, and a shift fitted to three mock rooms containing autopick
seats may not transfer to ten humans in a real league. Before Sept 1 the fix is
awareness, exactly as with section 15: **read the SURV column as an ordering, not
as a probability.**

**Ruled out immediately: it is not the stdev.** The obvious suspect was that
moving to `adp_source = "sleeper"` also dropped FFC's real per-player spread,
leaving every player on the fitted `curve_stdev` the design calls weak. Measured
on the same 540 picks — restoring FFC's real stdev for the 208 players that have
one moves calibration from 46/60/72/83/93 to **43/62/72/86/92**, which is noise.
**The level error is in the ADP MEAN, not the spread**: these Yahoo rooms simply
drafted later than Sleeper's half-PPR ADP says. Third independent confirmation of
"widening cannot fix a location error".

Cheapest next investigation, offseason or if time allows: break the calibration
down BY POSITION. If the bias is uniform it is a model-level problem (the
gaussian's spread, or the ADP mean); if it is position-specific it is more likely
an artifact of these mocks' half-PPR / 4-pt-passing-TD scoring differing from the
full-PPR ADP the sources publish. Those have different fixes and only one of them
transfers to the real leagues.

### Scoring several drafts at once — added 2026-08-26

Transcripts are named after their INPUT file, so a morning's mocks do not
collide: `results2.txt` becomes `.draft/<league>-<date>-results2.jsonl`.

    .venv/bin/python scripts/transcribe.py yahoo-mock .draft/results2.txt
    .venv/bin/python scripts/calibrate.py .draft/yahoo-mock-2026-08-26-*.jsonl

**Several journals are POOLED into one table per source**, which is the right
statistic: the question is which ADP mean predicts a real room, and three rooms
answer it three times better than one. Verified by pooling a draft with a copy of
itself — n doubles, the percentages are identical.

**The seat is no longer an argument.** It is read out of each journal (your own
picks are recorded there, and the first of them is your seat in a snake) and
then proven against the snake. This closes the hole that scored the first real
transcript against another manager: `transcribe.py` takes the seat from
`config.toml` and prints it, `calibrate.py` infers it, and neither can now
disagree with the league. An explicit slot is still accepted as an override, and
`calibrate.py` says so when it differs from the configured one.

---

## 13. CLOSED 2026-08-25 — ESPN is measurably WORSE than Rotowire. Not building it.

Originally "investigated, viable, needs a decision". The decision was taken on
**measurement**, not preference: ESPN was backtested head-to-head against
Rotowire on real outcomes and lost. `scripts/backtest.py` reproduces everything
below in about a minute.

### The result

2025 season projections, MAE in season points against actual 2025 finishes.
Each source scored on ITS OWN top-N (20 QB/TE, 40 RB/WR) so neither is punished
for covering players the other does not rank.

| Position | Rotowire | ESPN | |
| --- | --- | --- | --- |
| QB | **75.3** | 93.2 | Rotowire by 18 points |
| RB | 63.8 | **62.5** | ESPN by 1.3 |
| WR | **75.0** | 80.3 | Rotowire |
| TE | 46.3 | **44.5** | ESPN by 1.8 |
| **ALL** | **66.5** | 70.5 | **Rotowire 6% better** |

ESPN is also more optimistic at every position (QB +58.2 vs +42.0, RB +38.8 vs
+15.2). Selecting on each source's own top-N guarantees *some* positive bias, but
both were selected identically, so the gap between them is real.

### Why the numbers can be trusted

**Both sources still serve preseason-FROZEN 2025 projections**, which is the only
reason a real out-of-sample test was possible. This was verified, not assumed —
a revised projection is hindsight in a projection's clothes and would have
inverted the answer:

- Sleeper/Rotowire: `gp = 18.0` for every player regardless of outcome. Ekeler
  projected 156, scored 13.1. Anthony Richardson projected 130.7, scored 2.2.
- ESPN 2025: 90% full-slate, median 17.0 games. Ekeler 207.8 over 17 games.

**The join is `espn_id -> sleeper_id` through the DynastyProcess crosswalk we
already fetch** (6223 pairs) — integer IDs, non-negotiable #1 intact.

**The check that makes the comparison legal:** the two platforms' *actual* 2025
point totals agree at **r = 0.9997**, mean difference 0.7 points over 573 joined
players. Same scoring, so the two MAEs are directly comparable. `backtest.py`
aborts if that ever drops below 0.99.

### The trap this nearly walked into

**ESPN's 2024 projections are CONTAMINATED** — median 15.12 projected games, 6%
full-slate, **minimum 0.05 games**. Nothing written before week 1 projects a
player for 0.05 games; those numbers were revised as the season played out.
`backtest.py` refuses to score a source that fails the frozen test, and names it,
rather than printing a flattering number.

That contamination ran in ESPN's favour, and 2024 still came out Rotowire 51.8 /
ESPN 58.7. The conclusion survives the ambiguity — but 2024 is **not** evidence
and should not be quoted as if it were. **The clean sample is one season.**

### The published record, which is the stronger evidence

n=1 is thin. Fantasy Football Analytics has run 2014–2025 across 11 sources: for
2023–2025 **ESPN ranks last overall (6.44 MAE) and last at QB by a wide margin
(86.7 against a best of 71.2)** — the same position the backtest flagged, from an
independent method and a longer sample. Rotowire is not in that study, so this
does not prove Rotowire is *good*; it independently confirms ESPN is the weakest
of the free majors.

<https://fantasyfootballanalytics.net/which-projections-are-most-accurate>

**On analyst reputation:** neither source's projections are elite. ESPN's are a
proprietary model with no named analyst. Rotowire's are algorithm plus editorial.
Neither appears on FantasyPros' 2023–2025 draft-accuracy leaderboard, which is
led by Jody Smith (Draft Sharks), Sean Koerner (Action Network), Joey Wright and
Dave Kluge (Footballguys), Jeff Ratcliffe (FTN). **Every measured accuracy leader
is paywalled** — the same wall that ruled out FantasyPros. There is no free
source demonstrably better than the one already in use.

### Averaging is also dead

Tested, because the published studies say "aggregation works":

| | Rotowire | ESPN | Average |
| --- | --- | --- | --- |
| 2024 (ESPN contaminated) | **51.8** | 58.7 | 54.1 |
| 2025 (clean) | **66.5** | 70.5 | 68.1 |

The average lands between the two every time and never wins. FFA's aggregation
result comes from pooling ~10 sources; averaging two, one of which is worse, just
drags you toward the worse one.

For the record, averaging projections would **not** have violated the no-blend
rule — that rule forbids mixing projections with ADP, i.e. value with price.
Averaging projections is a different axis. It is rejected on measurement, not on
principle.

### What was given up

The honest case for ESPN was never better numbers — it was a `SPLIT` diagnostic
flag for cases like Jayden Reed (Rotowire WR#83, ESPN WR#122), the player the
board pushed for four straight picks and the user flagged as suspicious. That
case survives, but it now costs ~2 sessions to add a flag sourced from the
demonstrably weaker projection, days before a draft. Bad trade.

**To reopen this, bring new data, not a fresh opinion:** run
`.venv/bin/python scripts/backtest.py <season>` on a season where ESPN wins.

---

## 18. FantasyPros ECR — a 20-minute LOCAL look, not an integration

Raised 2026-08-26: the ECR sheets download free by scoring format even though
the API is paid. Worth a look, with the scope fixed in advance.

**The ToU line is narrower than "FantasyPros is ruled out".** Downloading and
reading it locally is fine. What is barred is *reproducing* their content:
committing the sheet to this public repo, or shipping a fetcher. Their download
also sits behind a login, so an auto-fetcher is a ToU problem in a way Sleeper's
public endpoint is not — that is the difference from non-negotiable #5, which
permits runtime fetching of Sleeper projections.

**It cannot enter the engine regardless of quality.** ECR is RANKS. VBD is
`proj_pts - replacement_pts` and needs points. Manufacturing points from a rank
(borrowing Rotowire's points at that rank) is exactly the blend non-negotiable #2
forbids — it launders market consensus into the value axis. Their free consensus
PROJECTIONS pages carry real stat lines and would be the more useful artifact,
same ToU line for shipping.

**Do this test FIRST — it decides everything else.** ECR is expert consensus,
ADP is crowd consensus; both are PRICE, and the board already carries price twice
(FFC and Sleeper). **Correlate ECR rank against ADP rank.** Above ~0.95 and ECR is
a restatement of what the divergence flag already shows, so stop there.

**There is room for a third opinion, measured 2026-08-26 on the live board:**

| Spearman(market ADP, Rotowire projection rank) | |
| --- | --- |
| all 409 priced players | 0.884 |
| **top 100 by ADP** | **0.618** |

Median rank gap in the top 100 is 28 places. Price and projected value genuinely
disagree where it matters. (Do not quote the individual headline gaps — Aubrey
139, Lawrence 93 — they are mostly cross-position artifacts of ranking globally,
which the within-position divergence fix already addressed.)

**The catch: it cannot be backtested for free.** Historical preseason ECR is
behind the paid API/HOF tier; free access is current-season only. So a 2026
download shows WHERE Rotowire and the consensus disagree and never WHO IS RIGHT
— the same limitation already recorded for the ADP divergence flag, and the exact
standard that settled ESPN in section 13.

FantasyPros rates at or near the top of the FFA study at every position
2014–2025, but that measures their PROJECTIONS, not the free ECR sheet.

**Expected outcome: a better-informed human at the table, not a change to the
board.** Worth 20 minutes to settle permanently.

---

### CLOSED 2026-08-31 — run against the real sheets. Do not reopen for 2026.

Both sheets downloaded by the user (PPR for `sleeper-main`, half-PPR for
`yahoo-main`), joined to the live pool on `(norm_name, position, team)` — the
same key `apply_ffc_adp` uses. **Zero unmatched inside the ECR top 150 on both.**
Analysis ran in scratch; nothing was written into the repo and no fetcher exists.

**The stop condition fired.** Spearman(ECR rank, our Sleeper ADP rank):

| | overall | top 50 | top 100 |
| --- | --- | --- | --- |
| PPR (Sleeper) | +0.931 (n=313) | +0.877 | **+0.954** |
| half-PPR (Yahoo) | +0.800 (n=503) | **+0.956** | **+0.972** |

§18 set the bar at ~0.95 and both leagues clear it at the top 100. ECR also
correlates *better* with ADP than with our own value axis (ECR vs VBD rank:
+0.817 / +0.811 overall, +0.895 top-100 both) — which is the section's own
prediction confirmed: **it is PRICE, and the board already carries price twice.**
No integration. Nothing to build.

**The tier-break comparison was the better test, and it is valid ONLY at RB/WR.**
FP ships a GLOBAL tier; ours is per-position, so the two are comparable only
where a position is dense enough at the top that consecutive same-position
players sit adjacent in the overall order. Measured rather than assumed:

| | FP top tier sizes | RB spacing | WR spacing | QB spacing | TE spacing |
| --- | --- | --- | --- | --- | --- |
| PPR | 6 / 5 / 9 | median 2 | median 2 | median 6, max 17 | median 7, max 21 |
| half-PPR | 10 / 14 / 18 | median 2 | median 2 | median 3, max 18 | median 8, max 17 |

Against tiers of 5–9 players, consecutive QBs and TEs straddle a boundary almost
by construction. **Any QB or TE "cliff" read off FP's global tier is an artifact.**
The half-PPR sheet's own tiers are coarser (10/14/18), so "FP is coarser than us"
is only clean on the PPR sheet.

**The one real disagreement, and it lands on the Sleeper pick you actually own:**

    FP PPR tier 1 (6): Chase, Gibbs, Nacua, Bijan, JAXON SMITH-NJIGBA, AMON-RA ST. BROWN
    ours:              WR tier 1 = Nacua, Chase.  JSN and St. Brown are WR tier 2.
                       RB tier 1 = Gibbs, Bijan  -- both sources AGREE.

You draft at slot 5 and the four names above JSN are ECR 1–4. So pick 5 is
precisely the seat where our board says "you have dropped a tier" and a ~100-expert
consensus says you have not. §15 says the tier is the signal and the order inside
it is noise, so this is a legitimate second opinion on a CLIFF LOCATION — the one
axis where a second opinion can help. Same shape one rung down: FP groups
McCaffrey and Taylor with Lamb/Jefferson/London; we split them into two tiers.

**General pattern: `tier_break_sigma = 1.0` draws finer distinctions at the very
top than the consensus does.** Do NOT turn the knob on this. `value.py` is frozen,
it is one download of one season from one source, and §18's own limitation stands
— **historical preseason ECR is paywalled, so this shows WHERE the two disagree
and never WHO IS RIGHT.** It fails §13's standard by construction. Offseason
question if ever; the deliverable was awareness and awareness is delivered.

#### Bonus: our PROJECTIONS vs the consensus, within position

Asked afterwards, and it is the more interesting half. Spearman on the top of
each position (RB30/WR36/TE14/QB14), our VBD order against FP's positional rank:

| | RB | WR | TE | QB |
| --- | --- | --- | --- | --- |
| Sleeper (full PPR) | +0.987 | +0.949 | +0.947 | **+0.771** |
| Yahoo (half PPR) | +0.978 | +0.934 | +0.956 | **+0.437** |

Median disagreement at RB/WR/TE is **one place**. So ECR, ADP and Rotowire are
all one blob on RB/WR/TE — there is no third opinion to be had, which is an
argument FOR the tool: if every price and value source agrees on the ORDER, and
§15 says the order inside a tier is noise against real outcomes, then the edge
was never in the ordering. It is in survival and VONA, which none of them compute.

**QB is the exception and the cause is our own scoring, not a difference of
opinion.** The direction is identical in both leagues: we are HIGHER on Prescott,
Purdy, Nix, Lawrence and LOWER on Daniels, Hurts, Caleb Williams — pocket passers
up, rushing QBs down. That is precisely what `CLAUDE.md` predicted from
arithmetic on 2026-08-24 for Yahoo's 0.25/completion bonus, and Sleeper's 6-pt
passing TD does the same thing more weakly, which is why Yahoo (+0.437) diverges
far more than Sleeper (+0.771). **First external confirmation of the custom
scoring, from a source that has never seen `config.toml`.**

**It is NOT evidence our QB numbers are better.** The two are scoring different
rulebooks; who is right is a different question and this data cannot answer it.

---

## 17. DONE 2026-08-26 — hand-typed marks survive a restart

**The gap:** `MarkDrafted` lived only in memory. For Sleeper this never mattered
— a restart replays the feed and re-derives `my_roster` from `draft_slot`, so it
was crash-safe by accident. **Yahoo has no feed**, so all ~150 picks are typed by
hand and a mis-hit ctrl-C (deliberately wired to exit cleanly) wiped the lot.

Sized honestly before building: the loop is well guarded, so a real crash is
unlikely — the realistic losses are ctrl-C, a closed terminal, or the laptop
sleeping. Nor is it unrecoverable, since Yahoo's own UI shows every pick. It is
5–10 minutes of frantic re-typing at the worst possible moment. Low probability,
severe, survivable.

**Deliberately NOT Phase 2's SQLite draft log** — that is designed for season
mode and is over-built for this. `.draft/<league>-<date>.jsonl`, one JSON op per
line, appended open-and-close so a killed process cannot take a buffer with it.
No fsync: the threat is ctrl-C, not loss of power. Phase 2 can still do the real
thing later.

Design points that are load-bearing:

- **Ops are journalled, not a state snapshot.** Replay rebuilds `_history`, so
  `u` still works for everything typed before the crash. A snapshot would restore
  the sets and silently leave the user with no undo.
- **`undo` is itself an op.** Unlogged, replay would resurrect a mark the user
  had already taken back.
- **Logging is armed only AFTER the replay**, or reading the log would append it
  to itself. `scripts/mutate.py` caught this one: disarming it left every test
  green while silently losing the net for the REST of the draft — so surviving
  one crash cost you the next. Now covered.
- **The filename is dated**, so a mock on one day and the real draft on another
  never share a file. Replaying a mock's marks into a live draft would be worse
  than no log at all. ponytail: a draft crossing local midnight starts fresh; the
  restore banner reports 0, which is visible.
- **Write failures are never fatal.** Persistence is insurance, not a dependency:
  losing the net is survivable, losing the board mid-pick is not.
- **`DRAFT_LOG_DIR` is anchored to `ROOT`, not cwd.** A relative path means the
  log you recover depends on which directory you launched from, and the one time
  that matters is the restart when you are not thinking about your shell.

`.draft/` is gitignored — it is draft state, never source.

**Found by running the suite, not by design:** tests journalled into the real
repo and the next `_run` test restored them, breaking an unrelated feed-staleness
assertion. Worse, `_draft_log_path` calls `date.today()`, which consumes a
`time.time()` read — and that test fakes only the FIRST `time.time()` to seed
`last_ok`. The extra read stole the seed and the stale banner never fired. An
autouse fixture now isolates both.

---

## 16. Draft-day command cheat sheet — BUILD IT LAST, deliberately

A one-page reference for the manual-entry notation (`name`, `me name`, `-name`,
`2`, `u`), to pull up on a phone at the table rather than scrolling a terminal
back at pick 47.

**Deliberately not built yet.** The command set changed twice on 2026-08-25 alone
(the `me`-after-plain claim fix, then `-<name>`), and a cheat sheet that
disagrees with the tool is worse than none — at the table it would be trusted
over the screen. Build it once the notation has stopped moving.

**SCHEDULED: Aug 30–31.** Fixed by the user 2026-08-26, deliberately late and for
the reason this section already gives — the sheet must match the notation that
ships, and Phase 3 is being built between now and then. The terminal path is
Phase 3's fallback, so it may still move. Write the sheet last, from the source
of truth below, not from memory of this file.

Do not re-raise it before Aug 30. It is ~30 minutes and it is scheduled, not
outstanding.

Source of truth when writing it: `_handle_command`'s docstring in `ffhelper/cli.py`
and the on-screen help line in `render()`. Check both still match the table before
publishing, and re-check if anything in §3 or §9 lands afterwards.

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

## 20. Sleeper's CDN — FIXED 2026-08-28, and how to re-check it

Sleeper serves `/v1/draft/<id>/picks` as
`public, s-maxage=86400, stale-while-revalidate=300` behind Cloudflare, so a
plain poll is answered from the edge and never reaches origin. `feeds.py` now
appends `?_=<ms>`; a `Cache-Control: no-cache` REQUEST header is ignored.

**Measured on a live 180-pick draft**, polling both URLs once a second in
parallel: the plain URL was late on **180/180 picks, median 8.3s, p90 14.9s,
max 27.9s, never once ahead.** The delta held at ~8.6s in both halves, so it is
not a startup artifact.

**Read that number correctly.** The room ran at **2.48s per pick** (CPU
autopick). The Sleeper draft is a 90s clock, where an 8s staleness is nearly
invisible.
The fix is real and cheap, but it mattered most in a cadence only a mock
produces — the same lesson as §12a run 2, *the mock is not the draft to optimise
for.*

**The cache KEY must stay `picks_<draft_id>`.** The URL now varies per poll, so
keying the local cache on it writes one file per second for a whole draft. Both
halves carry a mutation.

To re-check after any Sleeper API change:

    curl -sD - -o /dev/null "https://api.sleeper.app/v1/draft/<id>/picks" | grep -i "cf-cache-status\|age:"

`MISS` and no `age` means the buster still works. `HIT` means it stopped.

---

## 21. `calibrate.py`'s draft-id path was broken for two days — FIXED 2026-08-28

`calibrate.py <draft_id> <slot>` raised `IndexError`; with a league argument it
fetched the **league name** as a draft id and scored the **19-digit draft id as
the seat number**. Introduced by the 2026-08-26 pooling refactor, which split
argv on `isdecimal()` — and every Sleeper draft id is all digits.

Green suite throughout. Nothing reached the branch, because reaching it needed
the network. Parsing is now `parse_draft_args`, split out **so it can be tested
without one**; two mutations cover it.

**The generalisable bit:** the pooling refactor was verified by running the
JOURNAL path, which is what it changed. The draft-id path shared the argument
parser and was never re-run. *A refactor's blast radius is every caller of what
it touched, not the feature it was for.*

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
