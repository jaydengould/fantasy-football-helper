# Phase 3 — Dash UI design

Written 2026-08-26. Supersedes the one-line "Phase 3 — Dash UI" entry in
`2026-08-24-draft-mode-design.md`; that document remains the authority on the
engine, this one on the web layer.

**Deadlines this design is written against:** Yahoo draft **Sept 1 2026** (10
team, no pick feed, ~150 picks entered by hand), Sleeper draft **Sept 6 2026**
(12 team, live feed, nothing typed).

## What Phase 3 is

A Dash web board that reads the same engine the terminal reads, and — unlike the
terminal — is the thing you *drive* the draft from. Picks are entered by clicking
a row, not by typing a name.

The multi-page shell exists from the first line, but **only one page is built.**
Three season-mode pages are wanted (start/sit, waiver board, trade finder) and
all three need Phase 4 data that does not exist yet. "Shell" therefore means
`dash.register_page` and nothing else — no plugin layer, no stub pages, no
abstraction whose second implementation is hypothetical.

## What Phase 3 is not

- **Not an engine change.** `value.py` and `data.py` are frozen until both drafts
  are done. Every field the board displays is one `build_board` already returns.
- **Not a replacement for the CLI.** The terminal path stays working and stays
  the fallback (see "Fallback", below).
- **Not Phase 3.5.** Opponent needs and bye clustering reach into the board and
  are out of scope here.
- **Not multi-user.** Single user, localhost, one browser.

## Decisions

Recorded with what would reverse them, so they are not re-litigated.

### The journal is the database

Every render tick replays `.draft/<league>-<date>.jsonl`, polls the feed, and
rebuilds the board. Clicking a row appends one op. **There is no server-side
mutable state.**

Considered and rejected:

- **A `DraftSession` registry keyed by league.** Faster (no per-tick replay), and
  gives feed pacing for free. Rejected because it makes the CLI hand-off lossy in
  the one direction it would be used — the CLI writes to the journal, Dash holds
  memory, and the two disagree at exactly the moment something has already gone
  wrong. It is also the "module-level league state" the project banned, wearing a
  dict as a disguise.
- **A background poll thread, like `_run`.** Rejected hard: Dash's dev reloader
  runs two processes, which is two pollers and two writers into one journal.
  Journal corruption on draft night is unrecoverable in a way a slow board is not.

The per-tick replay cost is not a concern: ~180 JSON lines is microseconds
against `build_board`'s measured 20 ms on the full 632-player pool.

`MarkDrafted` is still the object that reads and writes the journal — it is
rebuilt by `_restore_marks` on each tick and discarded, so it is transient
working state, never state the server holds between requests. A click replays,
calls `mark()` (which appends the op), and re-renders.

**What made this affordable:** click-to-mark has no disambiguation — the row
carries the player id — so the entire `pending` / `_handle_command` /
`_split_commands` state machine has nowhere to appear. That state machine was the
only candidate for state that could not live in the journal.

**Reverse it if** state appears that genuinely cannot be journalled. None is known.

### Feed pacing needs no throttle layer

One `dcc.Interval` at the league's `poll_seconds`. Click callbacks fire
immediately and independently, so entry latency is not tied to the poll interval
— the defect that abandoned mock run 1 cannot recur here by construction.

The Yahoo league has **no feed at all**, so in the league where hand-entry
matters every render is click-driven and the interval only advances the clock.

### `my_roster` is derived from seat and pick number, not typed

The `me <player>` prefix does not exist in the web UI. The Nth op in the journal
is pick N; the seat's snake positions come from `next_pick_number` iterated from
pick 0; a mark landing on one of those positions is yours.

This is not new machinery. Sleeper already works this way (`_my_roster_from_picks`
attributes on `draft_slot`, nothing is typed), and `calibrate.py` already
reconstructs pick order from journal order and checks it against the seat's snake
positions — validated against three real transcribed mocks. Auto-attribution
makes manual mode match feed mode instead of being the exception.

**The cost, stated plainly.** Today `me` is explicit evidence. Auto-attribution
couples roster correctness to entry *completeness*: miss one pick and every pick
number after it shifts by one, which today skews only the survival horizon but
under auto-attribution also silently hands you the wrong roster — and a wrong
roster makes MARG meaningless. That is Task 13 defect #1 arriving by a new route.
It also removes the only existing signal that the log has drifted.

Two mitigations, both nearly free:

1. **The on-clock banner is the drift detector.** `_render_tick` already computes
   whether the current pick is yours. If the board announces your turn at the
   wrong moment you notice at once — it is the most prominent element on screen
   and reality checks it every ~36 seconds. That is a better detector than a
   prefix typed without thinking.
2. **A one-click per-row override** ("actually mine" / "not mine") writes an
   explicit op. The only reason to need it is drift, so it is also the cue to
   re-check the pick count.

**Scoped to the web path only.** `cli.py` keeps `me` untouched until after
Sept 6: journal ops carry a `mine` flag either way so the two remain
interchangeable, but changing the terminal notation six days out is draft-path
risk for no draft-day gain, and it would move `TODO.md` §16's cheat sheet again.

### The board derivation is COPIED, not extracted — for now

`_render_tick` (`cli.py:623-641`) derives the drafted set, `current_pick`,
`available`, `feed_roster`, `overruled`, `my_roster` and `recent`, then prints.
`app.py` needs the first half and none of the second.

The structurally right answer is `ffhelper/board.py` imported by both. **It is
deferred to after Sept 6**, and the reasoning is worth recording because the
first version of this decision was wrong.

The argument for extracting immediately was that a copy diverges silently, which
is the shape of Task 13 defects #1, #3 and #6. That argument fails on inspection:
**divergence requires an edit.** `value.py` and `data.py` are frozen, nothing
schedules a change to those twelve lines, so a faithful copy cannot drift inside
the draft window. It is a long-term maintenance risk being mistaken for a
draft-night one. Extraction touches the live draft path six days out and buys
nothing before October.

Note also that this was never a choice between importing `cli` and importing
`board`: `app.py` imports `MarkDrafted`, `_restore_marks`, `_draft_log_path`,
`load_board_inputs`, `_select_feed`, `_my_roster_from_picks`,
`_claims_overruled_by_feed` and `_combine_my_roster` from `cli.py` either way.
The choice is only whether to *edit* `cli.py`.

**The copy carries a `ponytail:` comment naming `board.py` as the upgrade path,
and it carries the agreement test below**, which is what turns dormant divergence
into detected divergence — and which doubles as the proof that October's
extraction is a no-op.

### `DataTable`, with its ceiling named

`dash.dash_table.DataTable` gives sorting, filtering and cell-click for free,
which is most of 3b and 3d at no cost, and the original spec anticipated it
("a list of dicts is what Dash's DataTable wants").

**Its ceiling:** no arbitrary markup inside a row. No sparklines, no per-row
buttons, and no true `── TIER 2 ──` separator rows. Tier bands are therefore
alternating *background colour* via `style_data_conditional`, not header rows.

**Upgrade path:** row-building callbacks are pure `(state) -> list[dict]` and
carry no styling, so swapping `DataTable` for a hand-rolled table rewrites the
view and leaves the tested logic alone. `ponytail:` comment says so at the call
site.

### `dash` is an optional dependency

`[project.optional-dependencies] web = ["dash>=2.17"]`. Base dependencies stay
`requests` and `yfpy`.

`python -m ffhelper.cli run` must work on a machine with no `dash` installed —
draft night must not depend on a package added for a dashboard. Enforced by a
test that imports `ffhelper.cli` with `dash` blocked from `sys.modules`.

**`app.py` imports `cli.py`. `cli.py` never imports `app.py`.** One direction,
covered by the same test.

## Fallback

The CLI stays as a different render path with 236 tests and a live 180-pick mock
behind it. Its value is not that it is better — it is that it is *proven*, and
`app.py` will not be until it has survived a draft.

**Sequential only. Never both at once.** Dash re-reads the journal every tick, but
the CLI holds `MarkDrafted` in memory and replays only at startup, so a running
CLI will not see Dash's later writes.

| direction | works | why |
| --- | --- | --- |
| Dash → CLI | yes | ctrl-C Dash, start the CLI, it replays the journal |
| CLI → Dash | yes | Dash picks the file up on its next tick |
| both running | **no** | the CLI's memory goes stale against the file |

**The only failure that actually needs the fallback is a deterministic bug in the
Dash render path** — a callback that crashes or renders wrong on a specific board
state (bench-only mode, your first pick, the last kicker leaving). A closed tab,
a hung page, a raised callback or a dead process all recover by reopening or
restarting, because the state is in the journal.

That failure is not hypothetical. It is the most likely draft-night failure,
because `app.py` is the only new code in the stack, and this project's record is
nine-plus defects found by running the thing, every one past a green suite.

**The switch is therefore rehearsed, not merely available** — a timed ctrl-C →
CLI handover is part of 3f.

## The page

One page, three regions.

```
┌────────────────────────────────┬──────────────────┐
│  banners: STALE / BENCH / runs │  MY ROSTER       │
│  pick 47 · YOUR PICK · next 52 │  QB  Allen       │
├────────────────────────────────┤  RB  Gibbs       │
│  [ALL][QB][RB][WR][TE][K][DEF] │  RB  ▢ empty     │
│  search: ____                  │  WR  Nacua       │
├────────────────────────────────┤  WR  ▢ empty     │
│  ── tier band ─────────────    │  TE  ▢ empty     │
│  Jefferson  WR  22.1  61%      │  FLX ▢ empty     │
│  Chase      WR  21.8  58%      │  K   ▢ empty     │
│  ── tier band ─────────────    │  bench 0/5       │
│  Nabers     WR  14.2  71%      │                  │
└────────────────────────────────┴──────────────────┘
```

- **Banners** reproduce `render()`'s: manual-mode, `FEED STALE`, bench-only,
  `CLAIM OVERRULED`, and the `last 8 picks:` run summary. A live pick ticker was
  considered and dropped — the run summary already serves the reach-or-wait
  decision.
- **Columns** are the terminal's: `#`, player, pos, VONA, VBD, MARG, TIER, SURV,
  DIV, flags (injury, `MODEL+`/`MARKET+`, bye).
- **Tier bands** via `style_data_conditional` on the existing per-position `tier`
  column, so same-tier rows read as one block. This is `TODO.md` §15's own
  recommended fix, and it is the strongest single argument for a UI over the
  terminal: the gap between tiers is real, the order inside one is close to noise.
- **Click a row** marks it drafted. A per-row override cell corrects attribution.
  An undo button appends an `undo` op.
- **Filter and search** are `DataTable`'s native `filter_action` plus position
  toggles.
- **Roster panel** renders `settings.roster_slots` against `my_roster`,
  greedy-filled by the same rule `lineup_value` uses so the picture cannot
  disagree with MARG. Empty slots are drawn as empty — that is what turns MARG
  from a number into a picture.

## Build order

Split by **runnable increment**, never by layer: every sub-phase ends in
something openable in a browser and checkable against real data. That practice is
what found nine defects a green suite passed over.

The sub-phases that can *corrupt* state (3b, 3c) deliberately precede the ones
that can only *look wrong* (3d, 3e).

| | What | Runnable check |
| --- | --- | --- |
| **3a** | Shell + read-only board: `app.py`, `register_page`, `dcc.Interval`, copied derivation, `DataTable` | Replay a transcribed mock; diff rows against the terminal at the same picks — **the agreement test lands here** |
| **3b** | Write path: click → journal op; undo button | Click 20 picks in, ctrl-C, start the CLI, confirm it replays all 20 and the boards match |
| **3c** | Auto-attribution + on-clock banner + per-row override | Replay a mock, assert the derived roster matches that seat's known picks — `calibrate.py` supplies the ground truth |
| — | **cut line** — everything above is a working draft tool | |
| **3d** | Tier bands, position filter, search | Board at picks 1 / 27 / 61 / 140 by eye against the terminal |
| **3e** | Roster panel with empty slots | Slots agree with MARG on a replayed mock |
| **3f** | Rehearsal — the Task 13 equivalent | Below |

**3a is first because it is the riskiest unknown** (does the pipeline work inside
a callback at all), not because it is the easiest.

**The cut line is real.** If Sept 1 gets close, 3d and 3e are dropped and the
board is still a working draft tool. Moving 3d above the line is a one-line plan
change if tier bands prove to matter more than the roster panel.

### 3f — rehearsal

1. Replay all three transcribed mocks offline: every board state including
   bench-only mode, on-clock transitions, and a claim overrule.
2. One live **Sleeper** mock — exercises the feed path with nothing typed.
3. One live **Yahoo** mock — exercises click-entry and auto-attribution under a
   real clock.
4. One **timed ctrl-C → CLI handover**, so the fallback is a rehearsed motion.

## Testing

Same standard as `value.py`: the logic tests without a browser and without a
network.

- **Callbacks are pure** `(ops, picks, pool) -> list[dict]`, called directly.
  Nothing in the test suite starts a server.
- **The agreement test.** Replay the Task 13 mock; monkeypatch `cli.render` to
  capture the `board` it is handed; run `app.py`'s derivation over the same
  journal; assert the `Row` lists are identical at every turn. ~20 lines. It is
  the guard on the copied derivation and the proof that October's extraction is a
  no-op.
- **Import isolation.** `ffhelper.cli` imports with `dash` blocked from
  `sys.modules`; `cli.py` never imports `app.py`.
- **Auto-attribution** tested against a transcript with a known seat.
- Every new test verified failing first with `git stash push -- ffhelper`, and
  non-trivial logic gets a mutation in `scripts/mutate.py`.

## Known risks

- **`app.py` is unproven until it has drafted.** Mitigated by 3f and by the CLI
  fallback, not eliminated. Accept it.
- **Auto-attribution couples the roster to entry completeness.** Mitigated by the
  on-clock drift detector and the per-row override. The residual risk is a user
  who misses a pick *and* ignores a banner claiming the wrong turn.
- **The copied derivation.** Guarded by the agreement test; scheduled for
  extraction to `ffhelper/board.py` after Sept 6.
- **Two writers to one journal.** Structurally prevented only by discipline —
  the rule is one process at a time. Worth a startup notice in `app.py` if it is
  cheap.

## Hosting, later — what this build does and does not foreclose

Phase 3 runs on localhost. The eventual want is a hosted dashboard where config
changes (switching leagues, editing settings) happen in the browser rather than
in `config.toml` — a season-mode concern, not a draft-night one.

**GitHub Pages cannot host this, ever.** Pages is static file serving; Dash is a
Flask app and needs a live Python process. Any host that runs one works
(Fly.io, Render, Railway, a small VPS, or Tailscale onto your own machine):
`gunicorn app:server`.

**Nothing in this design blocks that**, largely because the project's existing
rules already point that way — no module-level league state, paths anchored to
`ROOT` rather than cwd, and decision A's "no server-side mutable state" is
precisely what a multi-process host requires. One free line now keeps the door
open: expose `server = app.server` at module level rather than only calling
`app.run()` under `__main__`.

**What hosting would newly require, none of it built here:**

- **Authentication.** There is none today. A public URL carrying league data and
  a config editor is a config editor for whoever finds it.
- **Secrets on a server.** Yahoo OAuth tokens, whenever access arrives.
- **Persistent storage.** `.cache/` and `.draft/` need a real volume. Most cheap
  PaaS filesystems are ephemeral, which would wipe the draft journal on redeploy
  — silently, and the journal is the database.
- **No CLI fallback.** The fallback works because both processes read the same
  local file. Hosted, that story is gone — which is fine in-season and is the
  reason draft night stays local regardless of what gets hosted later.

### League switching vs config editing — two different asks

**Switching leagues is already in this design and costs nothing**: a dropdown
feeding league context to the callbacks, exactly as the original spec called for.
No config write is involved.

**Editing config values from the browser is deferred**, and needs care rather
than effort. `config.toml` is load-bearing for correctness — scoring, roster
slots, `draft_slot`, `adp_source` — and `preflight` exists because an edit that
silently fails to take produces a wrong board that looks healthy. `CLAUDE.md`
records exactly that happening (`# draft_slot = 2`, left commented, preflight
caught it). Two consequences for whenever this is built:

1. **Writing TOML back out loses comments** — `tomllib` is read-only and a writer
   is a new dependency the project resists. The likely answer is a separate
   UI-owned overlay (JSON) rather than rewriting the file a human maintains.
2. **Any UI config change must re-run `preflight` and show the result.**
   Otherwise the UI reintroduces the one failure mode `preflight` was built to
   catch.

## Deferred

- **`ffhelper/board.py` extraction** — after Sept 6, when the freeze lifts and
  `app.py` has two real drafts telling us what the interface should be.
- **Season-mode pages** (start/sit, waiver board, trade finder) — all three need
  Phase 4 data. They are why the shell exists; they are not built here.
- **Phase 3.5** — opponent needs, bye clustering, notifications.
- **`me` removal from the CLI** — after Sept 6, if at all.
- **Hosting and in-browser config editing** — see "Hosting, later". The league
  dropdown ships now; writing config from the UI does not.
