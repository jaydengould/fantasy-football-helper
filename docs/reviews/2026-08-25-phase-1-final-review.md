# Final whole-branch review — 2026-08-25

Branch `phase-0-1-draft-engine` @ `65b8664`, 31 commits, 18 files, ~6000 lines,
144 tests. Reviewed against the diff `review-4072b90..65b8664.diff`.

## Verdict

**Merge-ready as an engine; NOT draft-ready as shipped.** Five of six
architectural invariants hold end to end. Data joins, `value.py` purity, the
no-blend rule, and the dependency limit all verified. Two invariants break:
"degrade never fabricate" (finding 1) and "the loop never dies" (finding 3).
All four real fixes are small. Test quality is genuinely good — no vacuous
survivors beyond the two the ledger already names.

---

## 1. The STALE banner is unreachable — a dead feed looks perfectly healthy

`ffhelper/feeds.py:56-62` → `ffhelper/data.py:89-92`

`fetch_json` catches the fetch error and returns the stale cache, so
`get_picks()` returns **normally** on a failed poll. `cli.py:443-447` therefore
sets `last_ok = time.time()` every tick, and `render`'s `stale_seconds > 15`
branch (`cli.py:170`) never fires. The `log.warning` is wiped by the
`\033[2J\033[H` screen clear on the same tick.

Verified: three polls with the network down after the first — all three returned
the same pick list, no exception raised.

**Failure scenario.** Wifi blips at pick 40 of the Sleeper draft. Picks freeze →
`drafted` freezes → `current_pick` freezes → `next_pick_number` and
`survival_prob` evaluate against a dead horizon → VONA is wrong for every player,
already-drafted players still show as available, and the board looks completely
healthy.

This is the Task 12b pick-counter defect arriving through a different door.

**Fix:** add `stale_ok: bool = True` to `fetch_json`; pass `False` from
`get_picks` so a failed poll raises into the loop's existing guard. ~4 lines.

---

## 2. The Yahoo league cannot run at all

`config.toml:22-25` — `league_id = "REPLACE_AFTER_TASK_1"`, no
`[league.settings]` block. `run --league yahoo-main` dies with an uncaught
`ValueError` from `cli.py:212`.

`league_settings_from_config` is correct and tested; the data was simply never
filled in. The complete scoring table and roster are in `CLAUDE.md:46-61`.

**Sept 1 is the nearer draft.** After filling it in, dry-run
`preflight --league yahoo-main` and confirm `adp_format_for` returns `half-ppr`
and replacement lands at QB10 / TE10 / RB30 / WR30.

---

## 3. The manual-input drain is the one unguarded per-tick statement

`cli.py:437-440` sits outside both try blocks. `_handle_command` raises
`ValueError` at `cli.py:119` on any character where `str.isdigit()` is True but
`int()` fails — e.g. a superscript `²`.

Verified: raises straight out of `_run` through `main`, killing the loop
mid-draft.

Task 12's own lesson was "nothing in this loop may propagate". This statement was
added *after* that fix and never brought under it.

**Fix:** wrap the drain in the existing guard, or `try: idx = int(line) except
ValueError:` at the parse site.

---

## 4. `survival_prob` is unconditional — the SURV column is wrong for fallers

`ffhelper/value.py:150-157`. It computes P(survive to `at_pick`) from ADP alone,
never conditioning on "still available at `current_pick`".

Live check, real pool, pick 61 with two WRs slid past their ADP: Nico Collins
(adp 21) and George Pickens (adp 20.3) rank #1 and #2 with **SURV 0.00%** — their
unconditional survival underflows to exactly 0.0 — and correspondingly inflated
VONA (60.9 and 44.6) against a board whose third place is 11.3.

The ordering is defensible (VBD 140 at pick 61 is a real pick), but 0.00% is a
fabricated number for a player the room demonstrably passed on forty times, and it
systematically converts fallers into reaches.

Conditioning is `S(at_pick) / S(current_pick)`, but it needs `current_pick`
threaded into `survival_prob` and **it changes the sort**.

**Recommendation with seven days to the draft: document it and leave the math
alone, OR fix it and re-run Task 13 against a live mock. Do not fix it
unwatched.**

---

## 5. `tunables.divergence_flag_slots` is a silent no-op

Loaded, merged and defaulted in `config.py:21,43`; **never read**. `cli.py:184`
hardcodes `>= 25`. The spec (line 133) calls the threshold tunable. Editing
`config.toml` changes nothing and reports no error.

**Fix:** thread `tunables` into `render`, or delete the knob.

---

## 6. `current_pick` derives from a set count, not from `pick_no`

`cli.py:363-364`. Correct for manual mode, but a malformed row skipped by
`parse_sleeper_picks` (`feeds.py:37-39`) permanently shifts the horizon by one
pick with no indication.

**Fix:** `max(len(drafted), max(p.pick_no for p in picks))`. Low impact, cheap.

---

## 7. Minor — real, but leave them

- `apply_ffc_adp` uses truthiness for `stdev`/`bye` (`data.py:363,365`) — same
  class as the bug fixed in `survival_prob`, but FFC stdev is never 0 in practice.
  A player given an FFC `adp` with no `stdev` keeps a `curve_stdev` fitted to the
  *Sleeper* ADP.
- `adp_format_for` returning `"standard"` builds key `adp_standard`, which Sleeper
  does not emit (it uses `adp_std`) — every player would keep adp 999. Neither of
  this user's leagues is standard scoring.
- `_render_tick:377` uses `if league.draft_slot:` truthiness where `build_board`
  uses `is not None` — harmless since slots are 1-indexed, but it is the exact bug
  Task 11 fixed one layer up.
- `_preflight` never checks `draft_slot <= num_teams`.

---

## `.cache` as shared mutable state

**Clean apart from finding 1.** Keys do not collide across leagues or formats;
every write goes through `_write_cache_atomic` with `dir=cache_dir` so
`os.replace` stays same-filesystem; `_try_read_cache` swallows corrupt JSON and
refetches; no reader globs the directory, so orphaned temp files are inert. A
corrupt cache with the network down raises loudly at cold start rather than
degrading — correct. `ttl_seconds=0` on picks confirmed to force a refetch every
poll.

---

## Triage of the 11 deferred minors

**None are must-fix on their own.**

**Do the cheap two:**
- `_write_cache_atomic(path, cache_dir, ...)` redundant parameter (Task 4) — pure
  deletion.
- Delete or strengthen the two temp-file tests (Tasks 3, 4) — they pass on pre-fix
  code and are the false-confidence pattern this build repeatedly got burned by.

**Leave, genuinely fine:** dead `NormalDist` import (now live);
`test_tiers_all_below_replacement_does_not_raise`; the two narrow single-position
`marginal_value` tests; the decorative loose bounds in
`test_vona_accumulates_...` (the pinned `approx` beside it does the work); the
weak `SleeperFeed` empty-draft test; `main()`'s `KeyError` guard;
`_stdin_reader`'s EOF path (both branches log-asserted at
`test_cli.py:820,831`).

**Leave, but know the workaround:** the self-mark-contradicted-by-feed gap
(Task 12b). If you `me <player>` someone another team then drafts,
`_combine_my_roster` keeps him in `my_roster` forever and MARG is computed against
a roster you do not have. The only remedy is `u`, a single shared LIFO — undoing a
mismark made ten picks ago means undoing and retyping ten marks. **Worth knowing
before you are at the clock**; not worth building targeted un-mark this week.

---

## Could not verify

- **Task 13 (live mock draft) has not run.** Findings 1 and 3 both only surface on
  a real live feed under real failure — which is exactly what Task 13 is for. Run
  it *after* fixing them, not before.
- Yahoo settings-path correctness is unverifiable until the config block exists.
