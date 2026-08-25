# Outstanding work

Written 2026-08-25 at the end of the first working session. Ordered by deadline.

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
fixes, all small. Everything below in sections 1–3 comes from it.

---

## 1. DRAFT-NIGHT BLOCKERS — fix before Task 13

### 1a. The STALE banner can never fire — a dead feed looks perfectly healthy

`feeds.py:56-62` → `data.py:89-92`. `fetch_json` returns the stale cache on a
failed fetch, so `get_picks()` never raises, so `last_ok` refreshes every tick and
the `stale_seconds > 15` branch is unreachable.

Wifi blips at pick 40 → picks freeze → `current_pick` freezes → survival and VONA
are wrong for every player, drafted players still show available, **and the board
looks healthy.** This is the Task 12b pick-counter bug through a different door.

Fix: `stale_ok: bool = True` on `fetch_json`, passed `False` from `get_picks` so a
failed poll raises into the loop's existing guard. ~4 lines.

### 1b. The manual-input drain is the one unguarded per-tick statement

`cli.py:437-440` sits outside both try blocks. `_handle_command` raises
`ValueError` at `cli.py:119` on a character where `str.isdigit()` is True but
`int()` fails (e.g. superscript `²`). Verified to kill the loop mid-draft.

Task 12's lesson was "nothing in this loop may propagate" — this line was added
after that fix and never brought under it.

### 1c. Fill in the Yahoo league config (see section 4 below)

`run --league yahoo-main` currently dies with an uncaught `ValueError`. Sept 1 is
the nearer draft.

---

## 2. JUDGEMENT CALL — do not fix unwatched

**`survival_prob` is unconditional, so the SURV column is wrong for fallers.**
`value.py:150-157`. It never conditions on "still available at `current_pick`".

Live at pick 61: Nico Collins (adp 21) and George Pickens (adp 20.3) rank #1 and
#2 with **SURV 0.00%** and inflated VONA (60.9, 44.6) against a third place of
11.3. The ordering is defensible; the 0.00% is fabricated for players the room
passed on forty times, and it systematically turns fallers into reaches.

Conditioning is `S(at_pick)/S(current_pick)` — but it needs `current_pick`
threaded through and **it changes the sort**.

**Seven days out: either document it and leave the math alone, or fix it and
re-run Task 13 against a live mock.** Do not change it without watching a draft.

---

## 3. CHEAP FIXES — worth doing, not blocking

- `tunables.divergence_flag_slots` is a **silent no-op** — loaded and defaulted in
  `config.py:21,43`, never read; `cli.py:184` hardcodes `>= 25`. Thread `tunables`
  into `render` or delete the knob.
- `current_pick` derives from a set count, so a malformed pick row skipped by
  `parse_sleeper_picks` permanently shifts the horizon by one. Use
  `max(len(drafted), max(p.pick_no for p in picks))`.
- Drop the redundant `cache_dir` param from `_write_cache_atomic` (it equals
  `path.parent` at both call sites) — pure deletion.
- Delete or strengthen the two temp-file tests (Tasks 3, 4) — they pass on pre-fix
  code, the false-confidence pattern this build kept getting burned by.

**Know before you draft:** if you `me <player>` someone another team then drafts,
he stays in `my_roster` forever and MARG is computed against a roster you don't
have. The only remedy is `u`, a single shared LIFO — so undoing a mismark from ten
picks ago means undoing and retyping ten marks.

---

## 2. Task 13 — live Sleeper mock draft (NEEDS THE USER)

**The highest-value remaining work.** Running the real thing has caught eight
defects that a fully green test suite passed over, including a frozen pick counter
that would have invalidated every survival number in the Yahoo draft.

Steps:
1. Create a free mock draft in the Sleeper app
2. Read the `draft_id` from the mock draft URL
3. Add a temporary `[[league]]` entry pointing at it
4. `python -m ffhelper.cli run --league mock` and let picks come in

Watch for: drafted players leaving the board; VONA reordering as position runs
develop; survival falling as your next pick approaches; the stale banner appearing
if wifi is cut for ~20s and clearing when it returns.

**Do this several days before Sept 1**, not the night before.

---

## 3. Set `draft_slot` for the Sleeper league

`config.toml` has it commented out. Preflight reports INCOMPLETE without it and
the board degrades to next-pick survival instead of your real turn. Sleeper's
`draft_order` had 11 of 12 slots assigned at design time, so it must be set by
hand once the order is final — the tool deliberately never guesses it.

---

## 4. Add the Yahoo league to `config.toml`

The Yahoo entry still has `league_id = "REPLACE_AFTER_TASK_1"` and no
`[league.settings]` block. The real settings are recorded in `CLAUDE.md` and a
working config was validated during the session at
`scratchpad/yahoo_test.toml` (preflight OK: 10 teams, correct roster slots,
`pass_td=6.0`, 556 players, `draft_slot 4`).

Copy that block into `config.toml` with the real league id from the league URL.

---

## 5. Task 1 — Yahoo OAuth handshake (BLOCKED, external)

Blocked on Yahoo's approval of the Fantasy Sports API application submitted
2026-08-24. `.env` already holds the consumer key, secret, and league id.
`scripts/yahoo_auth.py` is written and untested against a live account.

When approval arrives:
1. Run `.venv/bin/python scripts/yahoo_auth.py`
2. Expect the yfpy constructor arguments to need adjustment — they change across
   versions and could not be verified without access. See
   https://yfpy.uberfastman.com/query/
3. Confirm `get_league_draft_results()` returns cleanly with 0 picks pre-draft —
   that is the strongest signal the Phase 2 feed will work
4. Record the real league id, team count, and scoring in `CLAUDE.md`

**Not on the critical path.** Manual entry covers the Sept 1 draft. This matters
for season mode, which is four months of use versus one draft night.

---

## 6. Deferred minors (11) — triage in the final review

All recorded with context in
`.superpowers/sdd/2026-08-24-phase-0-1-draft-engine/progress.md`. Highlights:

- Two "no leftover temp files" tests (Tasks 3 and 4) pass identically on pre-fix
  code — they assert steady state, not atomicity. Strengthen or delete.
- `_write_cache_atomic(path, cache_dir, text)` — `cache_dir` is redundant, equals
  `path.parent` at both call sites.
- Suffix stripping in `norm_name` strips once, not in a loop. Harmless for real
  names; a malformed "X Y Jr III" keeps the inner suffix.
- No test covers a self-marked player later contradicted by a feed pick carrying
  someone else's `roster_id`.
- `_stdin_reader`'s EOF warning path is never driven end-to-end through a real
  thread.

---

## 7. Later phases (not started, own spec cycles)

- **Phase 2** — Yahoo feed adapter (gated on approval) + SQLite draft log
- **Phase 3** — Dash web UI reading the same `value.py`
- **Phase 4** — season mode via `nflreadpy`. **Without the waiver notify-bot** —
  the league uses FAAB with scheduled batch processing, so claims resolve
  simultaneously and a same-day alert gives no timing edge.
- **Phase 5** — trade finder. `lineup_value()` was built standalone specifically
  so this inherits it. Will not output an acceptance probability; ranks by a
  transaction-history prior instead.
