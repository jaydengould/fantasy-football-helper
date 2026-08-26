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
2. **Set `draft_slot` for both leagues.** Section 6. One line each; the only
   reason `preflight` reports INCOMPLETE for `sleeper-main`.
3. **Add ESPN as a second projection source.** Section 13. Investigated and
   found viable; needs a decision on reversing the "ESPN ruled out" call.
4. **Bench-mode ordering.** Section 14. Honest but still weak once starters fill.
5. **Yahoo `league_id`** placeholder — section 7. Nothing reads it, blocks nothing.
6. Task 1 (Yahoo OAuth) is blocked externally; later phases have their own specs.

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

**Know before you draft:** if you `me <player>` someone another team then drafts,
he stays in `my_roster` forever and MARG is computed against a roster you don't
have. The only remedy is `u`, a single shared LIFO — so undoing a mismark from ten
picks ago means undoing and retyping ten marks.

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

## 6. Set `draft_slot` for both leagues

`config.toml` has it commented out. Preflight reports INCOMPLETE without it and
the board degrades to next-pick survival instead of your real turn. Sleeper's
`draft_order` had 11 of 12 slots assigned at design time, so it must be set by
hand once the order is final — the tool deliberately never guesses it.

---

## 7. Yahoo `league_id` is still a placeholder

The `[league.settings]` block is DONE (section 1c) — 10 teams, roster slots,
full scoring, validated by `preflight`. Only `league_id` is still
`"REPLACE_WITH_YAHOO_LEAGUE_ID"`.

**This blocks nothing.** There is no Yahoo API access and no Yahoo feed, so
`league_id` is dead config; the board runs entirely on hand-entered picks. It
matters when Phase 2's Yahoo feed lands. The real id is in `.env`; deliberately
not copied into `config.toml`, which is committed to a public repo.

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
- No test covers a self-marked player later contradicted by a feed pick carrying
  someone else's `roster_id`.
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

## 13. ESPN as a second projection source — investigated, viable, needs a decision

Prompted by "are we sure Rotowire is the best data available?" Checked against
the live endpoint rather than assumed.

**It clears every constraint:**

| Requirement | ESPN |
| --- | --- |
| Raw stat lines (custom scoring needs them) | yes — Gibbs 283 att / 1372 rush yds / 14.45 rush TD |
| Integer-ID join (non-negotiable #1) | yes — `espn_id`, already in the crosswalk we fetch, 8152 populated |
| Coverage | 584 season projections; 446 skill players overlap our pool |
| Auth / cost | none |

    https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/2026
        /segments/0/leaguedefaults/3?view=kona_player_info
    header: X-Fantasy-Filter: {"players":{"limit":1500,...}}
    season projection = statSourceId 1, statSplitTypeId 0

**And the sources disagree enough to be worth having:** median |rank difference|
22 places; 210 of 446 differ by 25+; 95 by 50+. Notably **Jayden Reed is WR#83
to Rotowire and WR#122 to ESPN** — the player the board pushed for four straight
picks and the user flagged as suspicious. ESPN is also far higher on Breece Hall
(#70 vs #31) and Josh Jacobs (#80 vs #43).

**The one real risk, and its antidote.** ESPN keys stats numerically (24 = rush
yds, 53 = receptions...) and a wrong mapping would silently corrupt projections
— the worst failure mode this project has. But ESPN returns `appliedTotal`
ALONGSIDE the raw stats: implement the map plus ESPN's own default scoring, and
if it reproduces `appliedTotal` for every player, the mapping is *proven*. That
turns the main risk into a mechanical check.

**Two things to settle before building:**
1. `CLAUDE.md` explicitly ruled out "ESPN/Yahoo scraping". This is an
   undocumented JSON API, not HTML scraping, and the project already depends on
   Sleeper's equally undocumented projections endpoint — but it IS a recorded
   decision, and the repo is public and tied to a job search (the same reasoning
   that killed FantasyPros). **User's call.**
2. What to do with two sources. **Recommendation: do NOT average — surface the
   disagreement.** A `SPLIT` flag where sources diverge 25+ places says "this is
   one analyst's opinion, not a consensus", which is exactly what was needed
   about Jayden Reed. Averaging would have moved him #83 -> ~#100 and explained
   nothing. Same philosophy as the divergence flag: show disagreement, never
   average it away.

Note averaging PROJECTIONS does not violate the no-blend rule — that rule is
about mixing projections with ADP, i.e. value with price. Averaging projections
is a better estimate of value and never touches price. Different axis.

**Estimate: ~2 working sessions.** Fits before Sept 6.

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
