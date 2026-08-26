# Outstanding work

Written 2026-08-25, first working session. **Revised 2026-08-25, second session.**
Ordered by deadline.

## What is left, in one place

**Everything from the final review is done.** Remaining work, in priority order:

1. **Task 13 — live Sleeper mock draft.** Section 5. Needs the user. This is the
   only remaining item with real risk attached, and running the code is what has
   caught every serious defect in this build.
2. **Set `draft_slot` for both leagues.** Section 6. One line each; it is the
   only reason `preflight` reports INCOMPLETE.
3. **Yahoo `league_id`** is still a placeholder in `config.toml` — section 7.
   Nothing reads it (no API access, no feed), so it blocks nothing.
4. Task 1 (Yahoo OAuth) is blocked externally; later phases have their own specs.

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
