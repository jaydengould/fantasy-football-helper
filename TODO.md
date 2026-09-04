# Outstanding work

The queue only. Closed items and the reasoning behind them live in
`docs/todo-archive.md`, section numbers preserved — a `§13` or `§19` reference
anywhere in the repo resolves there.

Rewritten 2026-09-03. Ordered by what blocks what.

## Blocking / dated

1. **The weekly snapshot must keep running.** Nothing schedules it — a `lineup`
   run is what writes the row, and the APIs serve current state only, so a week
   not recorded before it is played can never be scored. Week 1 is recorded for
   both leagues.
2. **`.roster/yahoo-main.txt` must be updated after every Yahoo add/drop.** No
   API. `lineup` and `preflight` both print its age for this reason.
3. **Yahoo OAuth (Phase 0, §8) — blocked externally**, no reply since
   2026-08-24. `scripts/yahoo_auth.py` does not exist and is deliberately not
   written: an untested handshake against an unreachable API is speculative, and
   the yfpy constructor arguments cannot be verified without access. Costs more
   now than it did — season mode wants that roster every week, and without it
   waivers and trades are Sleeper-only.

## Open work

4. **A run log.** The user reported the board "died at some point" during the live
   Sleeper draft and **nothing on disk can confirm or refute it** — no journal
   (feeds write none), no log file (stderr only), and the picks cache mtime is
   overwritten by the next run. Write poll successes, failures and callback
   timings to a dated file under `.draft/` or `.cache/`, the same append-and-close
   shape as the mark journal. Cheap; it is the difference between a diagnosis and
   a shrug.
5. **Phase 3.7 — the `DataTable` swap** (§19). Offseason. Carries a decision to
   take FIRST: `html.Table` or `dash-ag-grid`. Also the trigger for the deferred
   `board.py` fold — 3.7 is the point where a board change would otherwise be
   written twice, which is the only reason to pay that cost.
6. **Leverage weighting** (§7c) — weight playoff weeks UP by win probability
   instead of down by play probability, the reading the literature uses. Needs a
   playoff-odds simulation; data confirmed available (11 distinct pairings weeks
   1–14, rosters carry `wins`/`losses`/`fpts`). **Live window to build and
   validate is weeks 8–11** — earlier the schedule sample is too thin, later the
   playoff picture is decided and the feature answers a settled question.
7. **Win-probability lineups** (§7c) — optimise win probability (high floor when
   favoured, high ceiling as underdog) rather than points. Needs a per-player
   weekly variance this project has never estimated, the same missing ingredient
   as item 6. **Gate: run `scripts/backtest_weekly.py` on 2024 AND 2025 first** —
   the standard the matchup adjustment was held to and failed. Do not build the
   variance model until it clears that bar out of sample.

## Known-weak, unfixed, not actionable yet

8. **Bench-mode ordering** (§14). Once every starting slot is full the board says
   so rather than presenting the residual order as advice, but the ordering
   underneath is still static VBD — which by the late rounds recommends a third
   and fourth tight end. Observed live. The position filter is the honest
   mitigation. Fixing it properly needs a handcuff model or an upside/variance
   signal, and projections carry neither.
9. **The top of every position is a TIER, not a ranking** (§15). Measured
    2021–2025: no position ranks its own top 12 better than ~+0.35 Spearman. The
    gap between tiers is real; the order within one is close to noise. Take the
    tier early if the board says so; do not agonise over the name inside it. The
    honest fix is a confidence interval per position, which `backtest.py` can now
    produce the input for — offseason. **Do not** discount a position's VBD by a
    hand-picked factor.

## Deferred minors — pick up only if touching the same code

10. From Phase 5 (§7d): two near-duplicate `last_scoring_week` fallback strings;
    `playoff_round_type` semantics in a comment rather than a named constant; a
    missing `Iterable[int]` hint on `week_weights`; `effective_weeks`'
    all-zero-weight case untested; the pinned-mode empty board printing a generic
    header; `load_league_users` fetching twice per `trades` call (both
    cache-guarded).
11. From Phase 4a (§6): roster-file inline comments and duplicates (both fail
    safe), `SUPER_FLEX`/`WRRB_FLEX` printing a false "no eligible player" line, an
    unprojected starter appearing in two sections, close-call lines not repeating
    both projections. **Plus one risk taken deliberately:** a wrong-but-valid
    hand-set `League.roster_id` produces a coherent lineup for someone else's
    team; the override note names the owner, which is the passive check made
    active.
12. From Phase 1 (§9): `norm_name` strips one suffix, not in a loop (harmless for
    real names); `_stdin_reader`'s EOF warning path is never driven end-to-end.
13. **Cross-cutting, decide once or not at all:** print the trade/waiver FLOOR
    value on an empty board, so the "nothing clears it" claim is checkable. It is
    one call for both commands, not a Phase 5 defect.

## Deadlines

| Event | Date | Note |
| --- | --- | --- |
| NFL week 1 | Sept 9 2026 | season mode built and merge-checked ahead of kickoff — `lineup`, `waivers`, `trades` all shipped |
| Leverage-weighting build window | weeks 8–11 | item 6; the only dated piece of open work |
| Yahoo API approval | overdue | applied Aug 24, 1–2 weeks quoted, no reply |

## Do not rebuild

- **Phase 2's SQLite draft log** (cut 2026-09-01). Crash recovery mid-draft is
  moot with the drafts over, and season mode's persistence is one snapshot table,
  specced with the thing that needs it.
- **`load_league_transactions`** — no consumer once the FAAB bid died. It is what
  a revived acceptance prior would need; reopen only if the league actually trades.
- **The `yahoo-mock` / `sleeper-mock` blocks in `config.toml` stay.**
  `calibrate.py` reads `num_teams` from the named league, so deleting `yahoo-mock`
  destroys the ability to re-score the three transcribed mocks — the only
  non-circular calibration data the project has.
