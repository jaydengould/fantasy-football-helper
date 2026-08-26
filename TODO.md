# Outstanding work

Written 2026-08-25, first working session. **Revised 2026-08-25, second session.**
Ordered by deadline.

## What is left, in one place

**Task 13 is DONE** — a full 180-pick mock was run and every defect it exposed is
fixed (section 11). Remaining work, in priority order:

1. **Run a HUMAN mock and settle `adp_source`.** Section 12. The single largest
   remaining accuracy question. `sleeper-main` is now on `adp_source =
   "sleeper"` on a mechanistic argument, NOT a measurement — one line to revert.
   `scripts/calibrate.py <draft_id> <slot>` settles it.
2. **Treat the top of each position as a tier, not a ranking.** Section 15 —
   NEW. Across 2021–2025 no position ranks its own top 12 better than ~+0.35
   Spearman. The tier column already carries this; the board under-uses it.
   Awareness is probably the whole fix before Sept 1.
3. **Draft-day command cheat sheet.** Section 16 — NEW. Held back on purpose
   until the notation stops changing; trigger is after the human mock, and no
   later than Aug 30.
4. **Bench-mode ordering.** Section 14. Honest but still weak once starters fill.
5. **FantasyPros ECR local look.** Section 18 — 20 minutes, needs a manual
   download. Run the ECR-vs-ADP correlation first; it decides the rest.
6. **Deferred minors.** Section 9 — two left, both trivial, neither load-bearing.
7. Task 1 (Yahoo OAuth) is blocked externally; later phases have their own specs.

**Phases 3, 4 and 5 can now be built in parallel with all of the above**, under
one rule: **`value.py` and `data.py` are frozen until both drafts are done.**
Phase 3 lives behind its own entry point and never imports into the terminal
path. Phase 3.5 is the exception to watch — opponent-needs and bye-clustering
reach into the board.

**Closed since:** `draft_slot` for both leagues (section 6 — `preflight` is now
OK for `sleeper-main` and `yahoo-main`), the Yahoo `league_id` placeholder
(section 7), and **ESPN as a second projection source (section 13 — measured,
rejected, do not reopen without new data).**

## Deadlines

| Event | Date | Days out |
| --- | --- | --- |
| Yahoo draft | **Sept 1 2026** | 7 |
| Sleeper draft | **Sept 6 2026, 7:00 PM** | 12 |
| Yahoo API approval (applied Aug 24, quoted 1–2 weeks) | Aug 31 – Sept 7 | will miss Sept 1 |

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

## 2. CLOSED 2026-08-25 — `survival_prob` stays unconditional. Do not reopen.

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

**Trigger: after the human mock (section 12) and any changes it prompts, and no
later than Aug 30** — before the Sept 1 Yahoo draft, which is the one with no
feed and therefore all ~150 picks hand-typed.

Source of truth when writing it: `_handle_command`'s docstring in `ffhelper/cli.py`
and the on-screen help line in `render()`. Check both still match the table before
publishing, and re-check if anything in §3 or §9 lands afterwards.

---

## 14. Bench-mode ordering is honest but still weak

Once every starting slot is full, `is_bench_only` fires and the board says so
rather than presenting the residual order as advice. The K/DEF demotion stops it
recommending a second kicker. But the ordering underneath is still just static
VBD, which by the late rounds favours whatever is least far below replacement —
now TEs instead of kickers.

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
2. **Make the tier visually dominant** in the Phase 3 Dash UI rather than a
   column — group rows by tier instead of listing them. Real, but Phase 3.
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
