# SDD ledger — plan: docs/superpowers/plans/2026-08-24-phase-0-1-draft-engine.md

Branch: phase-0-1-draft-engine (created from main @ 4072b90)
Git rule: agents commit on this branch only. NEVER push, merge, rebase, or touch main.

Pre-flight scan: one conflict found and resolved with the user before dispatch —
the skill's review loop requires commits, which collided with the standing
"user owns git" rule. Resolved: agents may commit on the feature branch; push and
merge remain the user's. CLAUDE.md and the plan's Global Constraints updated.

Task 1 is a HUMAN HANDOFF (Yahoo app registration + league ID from browser URL).

Task 0: complete (commits 4072b90..6dcf719, review clean)
  - pyproject.toml, .gitignore, .env.example; .venv with requests 2.32.5, yfpy 17.0.0, pytest 9.1.1
  - reviewer confirmed .gitignore covers .env and .yahoo_token.json (public remote)
  - docs left uncommitted for the user as instructed

Task 1: BLOCKED (external) — Yahoo Fantasy API is no longer self-serve.
  sports.yahoo.com/developer/access/ now requires an application reviewed by the
  Yahoo Fantasy Sports team. Unknown turnaround; Yahoo draft is Sept 1 (8 days).
  Phase 1 is platform-independent, so this does not block Tasks 2-13.
  Consequence: manual mark-drafted mode is promoted from safety net to THE
  Sept 1 Yahoo plan, and must land before Sept 1.

Task 2: implemented ec98daa (2 passed). Review: spec OK, quality approved.
  Reviewer Minor (attributed to Task 0): pyproject.toml lacks [build-system], so
  `pip install -e .` registered no finder mapping. Bare `pytest` fails with
  ModuleNotFoundError; only `python -m pytest` works. CONTROLLER ESCALATION to
  Important: the plan has 11 remaining tasks that all run bare `pytest`.
  Fix dispatched as round 1.
  Second reviewer note (deferred, plan-contradicting -> asking user): Tunables
  dict defaults use whole-dict .get() fallback, not per-key merge. A partial
  [tunables.flex_share] in config.toml silently zeroes the unlisted positions
  and shifts replacement levels (WR 36 -> 24). Footgun in a user-tunable file.
Task 2: fix round 1/5 (2 addressed, 0 open; commits ec98daa..a098489)
  - 2c35c12 [build-system] added; bare pytest verified working by re-reviewer
  - a098489 per-key merge via {**defaults, **raw}; re-reviewer confirmed the 2 new
    merge tests WOULD fail under the old whole-dict logic (load-bearing, not vacuous)
  - no new breakage; no aliasing; no module-level state
Task 2: complete (commits 6dcf719..a098489, review clean, 5 tests passing)

Task 3: implemented 2ce3f3c (8 passed). Review: spec OK, quality approved.
  Reviewer verified the critical branch: ttl=0 forces refetch, stale returned on
  failure-with-cache, bare raise on failure-without-cache, write only after
  success, cache-hit test counts fetcher calls (not vacuous).
  Reviewer Minor -> CONTROLLER ESCALATION to Important: path.write_text is not
  crash-atomic. A truncated cache is read by the FRESH-cache path via a bare
  json.loads outside any try, so it raises on the happy path -- in the one module
  whose purpose is draft-night survival. Most likely victim is the 14.6MB player
  DB. Fix dispatched as round 1: atomic tmp+os.replace, plus tolerant read.
Task 3: fix round 1/5 (1 addressed, 0 open; commits 2ce3f3c..fbe537d)
  - re-reviewer confirmed tempfile.mkstemp(dir=cache_dir) -- os.replace stays on
    one filesystem, so atomicity is real, not nominal
  - 2 of 3 new tests would fail on revert; 3rd is weak (steady-state only)
Task 3: minor (deferred): test_no_leftover_temp_files_after_successful_fetch does
  not inject a write failure, so it guards steady state rather than orphan cleanup.
Task 3: PROCESS VIOLATION (no harm): implementer swept .env.example and the spec
  doc into fbe537d despite explicit instruction. Used git add -A or commit -a.
  Verified: .env.example still placeholders, .env NEVER committed on any branch.
  .gitignore was the only protection that held. Git instructions hardened for all
  remaining dispatches: explicit paths only, forbid -a/-A, verify with git show
  --stat before reporting done.
Task 3: complete (commits a098489..fbe537d, review clean, 11 tests passing)

Task 4: implemented 276a640 (15 passed). Review: spec MET, quality approved.
  Git constraint held this time -- only data.py + test_data.py staged.
  Reviewer correction to the plan's framing: "bijanrobinson" != "brianrobinson",
  so that test proves ID-vs-name lookup divergence, NOT same-name collision. The
  original design bug was from an abbreviated-name scheme. Test is still
  load-bearing (fails under a name-keyed join) but was oversold in the spec.
  Reviewer Minor -> CONTROLLER ESCALATION to Important: load_crosswalk hand-rolls
  its own cache, duplicating fetch_json and REINTRODUCING the non-atomic write +
  intolerant read fixed in fbe537d. Its docstring falsely claims fetch_json owns
  the caching. Origin: the plan's own brief, not the implementer. A truncated
  crosswalk cache silently yields MISSING yahoo_ids -- the exact failure this task
  exists to prevent. Fix dispatched as round 1: extract shared cache helpers.
Task 4: fix round 1/5 (1 addressed, 0 open; commits 276a640..3545d81)
  - single cache impl: _try_read_cache / _stale_fallback / _write_cache_atomic
  - re-reviewer ruled GENUINE DEDUP not over-abstraction: fetch_json body 57 -> 14
    lines; +13 net is helper docstring overhead
  - dir= confirmed present, so os.replace atomicity is real
Task 4: minor (deferred): _write_cache_atomic(path, cache_dir, text) -- cache_dir
  is redundant, equals path.parent at both call sites. Drop the parameter.
Task 4: minor (deferred): VACUOUS TEST, SECOND OCCURRENCE. Both
  test_no_leftover_temp_files_after_successful_fetch (Task 3) and
  test_load_crosswalk_no_leftover_temp_files (Task 4) pass identically on pre-fix
  code, which used path.write_text and never made a temp file. They assert
  steady state, not atomicity or orphan cleanup. False confidence in the suite.
  FINAL REVIEW: triage these two -- either make them inject a write failure and
  assert cleanup, or delete them.
Task 4: complete (commits fbe537d..3545d81, review clean, 18 tests passing)

Task 5: complete (commits 3545d81..42c7bbb, review clean, 22 tests passing)
  - LeagueSettings, score_stats, apply_projections, load_sleeper_settings,
    load_projections. roster_slots counts repeats and excludes BN; rounds counts
    the unfiltered list so bench rounds are included. All 6 positions fetched
    (K and DEF present -- both are starting slots).
  - CONTROLLER INDEPENDENT CHECK: score_stats against the REAL lg.json scoring
    payload with the full noisy Allen stat line (pts_ppr, gp, cmp_pct, pass_att,
    pass_cmp, adp_ppr, bonus_rush_td_qb) returns exactly 415.5. Descriptive-field
    filtering verified on real data, not just the curated test dict.
  - bonus_rush_td_qb exists in league scoring at 0.0 -- present but weightless.
  - Reviewer confirmed all 4 new tests discriminate; no new vacuous tests.

Task 6: implemented ad574c6 (27 tests). CONTROLLER LIVE CHECK found an Important
  defect the unit tests cannot see -- they use clean ASCII names, no K, no DEF.
  Ran apply_ffc_adp against the REAL FFC feed and the REAL Sleeper player DB:
  23.2% of FFC rows (62/267) failed to match. Four distinct bugs in the plan's
  norm_name / match_key design (mine, not the implementer's):
    1. generational suffixes kept: "James Cook III" -> jamescookiii vs jamescook.
       Silently drops Marvin Harrison Jr, Travis Etienne Jr, Michael Pittman Jr,
       Chris Godwin Jr, Brian Thomas Jr, Kyle Pitts Sr -- early-round picks.
    2. DEF never matches: FFC "Seattle Defense"; Sleeper DEF rows have
       full_name == '' and player_id == team code. Must match on team.
    3. position alias: FFC uses PK, Sleeper uses K. EVERY kicker failed.
    4. unicode: "Eddy Pineiro" -- n-tilde is stripped, not folded.
  Measured: 23.2% -> 17.6% (suffix) -> 8.2% (+DEF by team) -> 0.4% (+PK alias)
  -> 0% expected with NFKD folding. Verified on both the 12-team PPR and 10-team
  half-PPR feeds (the two leagues' actual ADP datasets).
  Harm was silent DEGRADATION, not corruption: unmatched players fall back to
  curve_stdev, losing the per-player ADP variance that is the ONLY reason FFC is
  in this project. Fix dispatched as round 1.
Task 6: fix round 1 -> 0f68512 (name matching: suffixes, DEF-by-team, PK alias,
  NFKD folding). LIVE VERIFIED via shipped code: 0/267 and 0/230 unmatched on the
  two real feeds, pool 3230->3230, Harrison/Etienne/Pittman/Godwin now carry real
  stdev, no over-stripping (Steve Young / Jared Verse / Bud Dupree intact).
Task 6: fix round 2 -> 87c539e (collision guard). Reviewer proved the name fix
  INTRODUCED a false-positive risk: by_key dict comprehension silently overwrote
  on duplicate match_key. 6 real collisions exist in live data (ronaldjones|RB|,
  joehorn|WR|, rodneysmith|RB| ...), all currently teamless free agents. Guard
  groups to dict[str,list[Player]] and excludes ambiguous keys, reporting them
  with an "AMBIGUOUS: " prefix. Return type stayed list[str] -- Task 12's caller
  is unaffected but can branch on the prefix. LIVE VERIFIED: forced collision
  reports AMBIGUOUS and BOTH players keep ID-keyed values.
Task 6: fix round 3 -> 8534fc9. Reviewer found the guard was applied to the name
  branch but NOT the sibling by_def_team dict comprehension -- same defect class,
  same function. Fixed. Also DELETED a vacuous test.
Task 6: THIRD VACUOUS TEST IN THIS SUITE. Pattern: implementers assert invariants
  no code path can violate (no temp files vs code that never made temp files;
  pool size vs code that only mutates attributes). All 3 passed on revert. Two
  remain (Task 3, Task 4) -- FINAL REVIEW must triage them. Every reviewer is now
  asked to reason explicitly about revert-failure rather than count passes.
Task 6: complete (commits 42c7bbb..8534fc9, review clean, 34 tests passing)
NOTE: spec doc reverted to an earlier state and again reads "RB30, WR36" at
  12 teams. The PLAN and task-7-brief carry the corrected RB36/WR36 and the code
  will follow the plan. Spec needs reconciling before it is trusted as the record.

Task 7: implemented 543fe8b, fixed 57939d1. Both APPROVED. Purity ruling CLEAN --
  value.py has no I/O, no network, no module-level mutable state.
  CONTROLLER LIVE CHECK found a design defect the 42-test suite passed over:
  assign_tiers computed its gap threshold over the ENTIRE position pool (~140 RBs).
  The near-zero gaps in the tail dragged pstdev below the top-of-board gaps, so
  top-8 RBs came out as SIX distinct tiers -- the column conveyed nothing exactly
  where draft decisions happen. Unit tests used 4-player synthetic groups.
  Fix: scope the threshold's input to draftable players (score > 0); assignment
  still walks the full group so every player gets a tier. sigma default unchanged.
  Measured [1,2,3,4,5,5,5,6] -> [1,1,2,3,4,4,4,4].
  LIVE VERIFIED both leagues: Sleeper Gibbs+Bijan T1, McCaffrey T2, Taylor T3,
  Cook/Achane/Brown T4; Nacua+Chase share WR T1. Yahoo similar, RB-heavier.
  Reviewer independently reproduced the revert analysis and corrected the
  implementer's arithmetic (pstdev 2.827 not 2.95; conclusion held).
Task 7: minor (deferred): dead import NormalDist at value.py:7 -- becomes live in
  Task 9 (survival_prob), so no action needed.
Task 7: minor (deferred): test_tiers_all_below_replacement_does_not_raise is a
  defensive edge-case check, not regression protection for this fix. Harmless;
  do not count it as a guard.
Task 7: complete (commits 8534fc9..57939d1, review clean, 45 tests passing)

Task 8: implemented 99d5cfb, test corrected d500d08. APPROVED, no Critical/Important.
  PLAN BUG (5th so far, all mine): test_third_rb_adds_less_than_first asserted a
  4th RB worth 180 adds 0.0 to a roster whose FLEX held a 150. Wrong -- 180
  displaces 150, true answer +30. The implementer COMMITTED THE FAILING TEST and
  reported it rather than altering lineup_value to satisfy it. Correct call:
  bending the function would have corrupted Phase 5's trade evaluator with a
  green suite. Fix touched tests/test_value.py ONLY (reviewer confirmed value.py
  untouched between the two commits).
  Corrected test is stronger than the original: 180 into empty roster, +30 as a
  4th RB (displacement upgrade), 0.0 for a candidate below the FLEX occupant.
  REVIEWER PROVED GREEDY OPTIMALITY rather than asserting it: the slot structure
  is a LAMINAR MATROID (disjoint per-position caps for QB/K/DEF plus a nested
  union cap over flex-eligible RB/WR/TE), and greedy weight-maximization on a
  matroid is provably optimal. Verified against canonical matroid greedy on
  constructed cases; no counterexample. My brief only asserted this.
  Mutation ruling: CLEAN. sorted() and [*roster, candidate] build new lists; no
  Player field is ever written, so marginal_value's two calls cannot drift.
  Purity CLEAN. Double-counting prevented by a used-set keyed on sleeper_id.
  CONTROLLER LIVE CHECK (real pool, real settings): RBs 1-4 return full marginal
  value (331.4/324.9/257.4/255.2), RB5 -> 0.0. Cross-position flex competition
  correct: both FLEX filled by WRs (285,281) -> a 257 RB yields 0.0, a 291 RB
  yields 10.5 (displaces the 281). TE full value while the TE slot is empty.
Task 8: minor (deferred): two narrow tests (ignores_players_beyond_slots,
  marginal_value_of_upgrade) are single-position; flex paths covered by siblings.
Task 8: complete (commits 57939d1..d500d08, review clean, 50 tests passing)

Task 9: implemented 2cbd98d, fixed 61ecd78, fixed 6f26a3d. All findings ADDRESSED.
  PLAN BUG #6 (mine): vona excluded the candidate from its own survival walk.
  When you wait, the best available at that position may BE the candidate. This
  systematically inflated urgency for high-survival players. Colston Loveland
  showed VONA 10.6 at 88% survival; true value -1.2. He ranked 4th and would have
  triggered a 3rd-round reach for a TE obtainable in the 5th. All 59 tests passed.
  PLAN BUG #7 (mine): survival_prob used `adp_stdev or curve_stdev(...)`, so a
  legitimate 0.0 fell through to the curve. Now `is not None`. LIVE VERIFIED:
  stdev=0.0 gives a step function (1.0/0.5/0.0 at picks 10/20/30); stdev=None
  gives the curve (0.999/0.5/0.001). Distinct.
  Minor: detect_run(window=0) returned the WHOLE list ([-0:] == [0:]). Guarded.
  TEST-REALISM GAP CLOSED. Reviewer showed the regression test I commissioned for
  bug #6 was ITSELF an extreme (adp=150/stdev=15 at pick 46 = 6.9 sigma). Every
  VONA test sat at survival ~0 or ~1 -- the band where the bug is invisible.
  Now covered: 0.4207/0.5/0.5793/0.6554 in one test, 0.29/0.90 in another, all
  independently recomputed by the reviewer against NormalDist and confirmed.
  All three new VONA tests verified to FAIL under the pre-fix candidate-excluded
  logic. One pre-existing test strengthened (pinned value, not loosened); no
  assertion anywhere was weakened.
Task 9: minor (deferred): in test_vona_accumulates_across_multiple_mid_band_
  survivors the loose bounds assert (2.896 < r < 41.996) is decorative -- the
  pre-fix value 17.6 sits inside it. Only the pinned approx(10.20, abs=0.05)
  discriminates. Harmless, but the bounds imply protection they do not give.
Task 9: complete (commits d500d08..6f26a3d, review clean, 67 tests passing)

=== PAUSED 2026-08-25 at user request. RESUME AT TASK 10. ===
State: branch phase-0-1-draft-engine @ 6f26a3d, 67 tests passing, no open findings.
Data layer (Tasks 2-6) and pure engine (Tasks 7-9) are COMPLETE.
Remaining: Task 10 (pick feed protocol + SleeperFeed), Task 11 (board assembly),
Task 12 (CLI render/loop/preflight + MANUAL MARK-DRAFTED), Task 13 (human: live
Sleeper mock draft).
Task 10 brief already extracted: .superpowers/sdd/.../task-10-brief.md
Next controller action: dispatch Task 10 implementer with BASE=6f26a3d.
Carry into Task 12: manual mark-drafted is the Sept 1 Yahoo interface (API
approval is 1-2 weeks out, draft is Sept 1) and needs partial-name search,
disambiguation, undo, and non-blocking input -- NOT the 10-line version.
Also carry: apply_ffc_adp returns list[str] where ambiguous entries are prefixed
"AMBIGUOUS: " -- Task 12's caller should branch on that prefix when printing.

=== RESUMED 2026-08-25. User committed docs as 0496086 (CLAUDE.md + plan). ===

Task 10: implemented 0436c37, hardened 8ba4900. Both findings ADDRESSED.
  ttl_seconds=0 CONFIRMED passed literally, not inherited -- the picks endpoint
  refetches every poll. Had it inherited the 24h default used for the player DB,
  the board would have shown a FROZEN pick list for an entire draft while looking
  healthy. Single missing argument, worst failure shape in the codebase.
  Finding 1: SleeperFeed had ZERO test coverage -- tests only exercised the
  module-level parser; the class that polls during the draft was never imported.
  Now covered end-to-end through the injected fetcher, using tmp_path (not the
  shared .cache, so no cross-run flakiness), with an exact-URL assertion.
  Freshness guard verified EMPIRICALLY by the implementer: patched a copy without
  ttl_seconds=0, test failed `assert 1 == 2`, restored.
  Finding 2: int(row["pick_no"]) was unguarded -- one malformed row raised out of
  get_picks(), and since the CLI retries identically it would freeze the board for
  the rest of the draft. Now skips uninterpretable rows with a logged warning.
  CONTROLLER CHECK on the risk I introduced by asking for skipping: a silently
  dropped VALID pick is WORSE than a crash (board shows a drafted player as
  available). Reviewer confirmed no valid shape is discarded -- numeric string
  "12" is kept, absent roster_id defaults to None correctly.
  LIVE VERIFIED: 6 rows with 4 malformed -> 2 valid picks, no raise, still sorted;
  real pre-draft feed returns [].
Task 10: minor (deferred): SleeperFeed empty-draft test is weak -- only fails on a
  crash. Confirms wiring; kept.
Task 10: complete (commits 0496086..8ba4900, review clean, 77 tests passing)

Task 11: implemented 624838e, hardened bc709fd. All findings ADDRESSED.
  Reviewer's key catch: the sortedness test was SELF-REFERENTIAL --
  `assert board == sorted(board, key=lambda r: -r.vona)` sorts the board by its
  OWN stored values, so it passes for any values including all zeros. It could
  NOT detect a max(0, vona) clamp, which is the exact regression it existed to
  guard. Negative VONA is real signal (waiting is strictly better); clamping
  destroys it silently. Now asserts an independently-derived id order, plus a
  board-level negative-VONA test pinned to approx(-50.0).
  Implementer verified empirically: applied the clamp, watched both new tests
  fail, reverted, diffed against backup to prove clean restore.
  Realistic-scale test added: 64 players (14QB/20RB/20WR/10TE), at_pick=54.
  Reviewer independently recomputed everything -- 17/64 mid-band survival,
  32 positive / 32 negative VONA, and added its own tail analysis: 24 low /
  17 mid / 23 high. Genuine three-way spread, not token realism.
  Minor fixed: my_slot used truthiness, so 0 took the unknown-slot path. Now
  `is not None`.
  Efficiency measured, not assumed: build_board is O(n^2) but 6.6ms on a
  396-player pool -- ~750x under the 5s re-render budget. Known, not fixed.
Task 11: complete (commits 8ba4900..bc709fd, review clean, 83 tests passing)

PLAN AMENDED 2026-08-25 after user pushback: "Just because I might not have the
API in time for my draft doesn't mean we should build an incomplete app."
  Correct, and the stronger version of the point: MANUAL LEAGUE SETTINGS ARE THE
  GENERAL CASE, not a deadline fallback. Yahoo needs per-developer approval that
  can be DENIED; ESPN has no official API; CBS/NFL.com none worth using; anyone
  cloning this public repo has no Yahoo access at all. API sync is an
  OPTIMISATION for platforms that permit it, layered over a manual path that must
  be equally tested and documented. Task 12 brief previously raised
  NotImplementedError for any non-Sleeper league -- a configured league the tool
  refuses to serve is a bug on its own terms, independent of any deadline.
  Plan now specifies: League gains `settings: dict | None`; resolve_settings()
  prefers the platform API and falls back to a [league.settings] config block;
  a league that later gains API access starts syncing with NO config change.
  Full Yahoo API integration (settings sync + YahooFeed + token refresh) REMAINS
  in Phase 2 scope. The delay changes ordering, not scope.
  Also split out TASK 12b: manual mark-drafted (partial-name search via norm_name,
  MANDATORY disambiguation -- Bijan vs Brian Robinson -- undo, non-blocking input,
  no new dependency). Separable from the CLI core and deserves its own gate.

Task 12: implemented e087570, fixed 5f44985, fixed d489835.
  FIRST CRITICAL OF THE BUILD, and it landed on the stated non-negotiable.
  The poll loop wrapped ONLY feed.get_picks(); build_board, render, detect_run,
  next_pick_number and the prints were all OUTSIDE the try. An exception from any
  of them ended the session mid-draft. The `# noqa: BLE001 - loop must never die`
  comment was attached to the one call that was already safe.
  Root cause worth remembering: the implementer wrapped the call that OBVIOUSLY
  fails (network). The dangerous exceptions are the unanticipated ones -- a
  KeyError in board assembly, a formatting edge in render. "Wrap what looks risky"
  is the wrong instinct; "nothing in this loop may propagate" is the right one.
  Fix: per-tick work split into two independently guarded stages. Implementer
  verified by reverting just the widening and watching RuntimeError propagate out
  of _run at the render() call, then restoring and diffing.
  Also fixed: "loop never dies" was NEVER TESTED -- no test invoked _run,
  _preflight, or main. Now tested with a bounded max_iterations seam that the
  reviewer confirmed is byte-equivalent to `while True` when unset.
  SIXTH VACUOUS TEST: test_render_shows_position_run asserted `"RB" in out and
  "5" in out`; "RB" appears in every POS cell and "5" inside "50%" from SURV, so
  it passed even with the run-summary line deleted. Now asserts the summary line
  content exactly.
  Final round: time.sleep(interval) sat outside both guards. The reviewer framed
  it as a crash path (negative interval -> ValueError). The likelier harm is the
  opposite: poll_seconds = 0 busy-loops and hammers Sleeper, which IP-blocks above
  ~1000 req/min -- losing the feed mid-draft, the exact failure the loop exists to
  prevent. Fixed at the VALUE (max(interval, 1)), not by wrapping the symptom.
  KeyboardInterrupt now has a test that drives the REAL loop, so broadening an
  inner handler to BaseException would be caught. Verified failing under that
  change.
  LIVE VERIFIED: preflight against the real sleeper-main league -- 12 teams,
  correct roster slots, pass_td=6.0, real draft_id, 632 players with projections,
  feed reachable, correctly reports INCOMPLETE while draft_slot is unset.
  Board renders with every column populated, injury/bye/divergence flags working.
Task 12: KNOWN GAP -> Task 12b: my_roster is always [], so the MARG column shows
  each player's FULL projection (Josh Allen 415.5) rather than marginal lineup
  value. A column labelled "marginal" showing raw points is misleading. Sleeper's
  draft object exposes slot_to_roster_id, so draft_slot -> roster_id -> the user's
  own picks. Seam is clean; 12b only replaces the [].
Task 12: minor (deferred): main() gained a try/except KeyError around get_league
  (scope creep beyond the findings, but tested and harmless).
Task 12: complete (commits bc709fd..d489835, review clean, 104 tests passing)

Task 12b: implemented 0f3deb4, then d7d1a41 (runnable manual mode), then 65b8664
  (pick counter). All findings ADDRESSED, no Critical.
  MY MISTAKE, TWICE THE SAME SHAPE: after the user pushed back on
  NotImplementedError I fixed the SETTINGS path (resolve_settings + config block,
  well tested) and left _run still hard-requiring a Sleeper draft_id. The feature
  was reachable in the type system and unreachable at runtime -- `run --league
  yahoo-main` failed before rendering anything. Fixed the layer the complaint
  pointed at without walking the whole path to check the feature worked end to end.
  Fix: explicit _select_feed (SleeperFeed when draft_id present, else NullFeed --
  one if, not a fallback chain), MANUAL MODE status line, no stale banner without
  a feed, and `me <query>` to mark your own pick so my_roster/MARG work feed-less.
  EIGHTH LIVE-CHECK FIND, and the worst: the pick counter NEVER ADVANCED in manual
  mode. It derived from feed picks, permanently empty without a feed, so the board
  believed it was always pick 1. next_pick_number returned a fixed turn,
  survival_prob was evaluated against a frozen horizon (97%/100%/100% mid-draft),
  and vona -- survival-weighted -- was wrong for EVERY player on EVERY tick.
  139 tests were green. MarkDrafted, find_players and build_board were each
  correct in isolation. Only driving _run exposed it.
  Fixed: current_pick = len(feed picks | manual marks) + 1, computed once and
  threaded into build_board, next_pick_number AND the footer -- no independent
  recomputation. LIVE VERIFIED: counter tracks marks 1:1 (0->1, 2->3, 4->5, 6->7,
  8->9) and the horizon shrinks 12->10->8 picks away with correct snake math for
  slot 4 of 10.
  Reviewer judgement worth keeping: the feed-only test passes against BOTH buggy
  and fixed code, which is CORRECT here -- it is a non-regression check proving
  the Sleeper path is a strict superset, not a bug discriminator. The other four
  new tests do the discriminating.
Task 12b: minor (deferred): no test covers a self-marked player later contradicted
  by a feed pick carrying someone else's roster_id (i.e. someone else drafted a
  player you self-marked). Only matters when a feed AND manual marks are both live.
Task 12b: minor (deferred): _stdin_reader's EOF warning path is never driven
  end-to-end through a real thread.
Task 12b: complete (commits d489835..65b8664, review clean, 144 tests passing)

=== ALL 12 CODE TASKS COMPLETE. Remaining: Task 13 (HUMAN mock draft) + final
    whole-branch review. ===

=== SESSION END 2026-08-25. Phase 1 code complete. ===
Branch phase-0-1-draft-engine @ 65b8664, 31 commits, 144 tests passing.
Tasks 0, 2-12, 12b complete and reviewed. Remaining work is in TODO.md at the
repo root -- read that first next session.
FINAL WHOLE-BRANCH REVIEW WAS DISPATCHED BUT ITS FINDINGS WERE NOT CAPTURED
(dispatched without a report file; result existed only as an in-session
notification). MUST BE RE-RUN. Package already generated at
review-4072b90..65b8664.diff -- have the re-run write to a file.
