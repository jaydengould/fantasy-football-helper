# Fantasy Football Helper

Personal tool for live fantasy football drafts, growing into an in-season
dashboard. Python. Two runtime modes sharing one data layer: **draft mode**
(short-lived, high-frequency, local) and **season mode** (unattended, scheduled,
SQLite-backed).

**Full design:** `docs/superpowers/specs/2026-08-24-draft-mode-design.md`
This file is the running memory; the spec is the authority on design detail.

## Working convention

**Be brutally honest.** Push back when the user is wrong, state methodological flaws plainly, and never agree just to be agreeable.

**Do not simply agree with me. Be my sparring partner. Identify my blind spots,
structural risks, and faulty assumptions.**

**A vivid result from a single sample is a hypothesis, not a finding.** Before
writing a measurement into this file or `TODO.md`, state what produced it and how
many independent samples it rests on. If it is one draft, one season, or one
constructed board state, either widen the sample or label it as provisional. This
has been the cause of three wrong claims now (a constructed pick-61 board; a
circular ADP comparison; a one-season "projections cannot rank QBs"), and the
tell is always the same — the number was striking, so the explanation got written
before the sample size got checked.

Corollary for data pulled from an API: **check provenance before building on it.**
Endpoints serve "projections" for seasons already played, and some were revised
mid-season. `scripts/backtest.py` makes a source prove it was frozen and refuses
to score it otherwise; do the same for any new source.

**Eliminating one suspect is not a verdict.** Twice now a confident diagnosis
has been announced after ruling out a single alternative ("not the spread,
therefore the mean" — it was neither; the model was computing the wrong
quantity). Before naming a cause, ask what the third option is.

**Update this CLAUDE.md at the end of each working session** — record decisions
made, schema/config changes, and what's next. It's the memory that survives
between sessions.

**Update `TODO.md` at the end of each working session too.** `CLAUDE.md` holds
decisions and context; `TODO.md` holds outstanding work, ordered by deadline.
Both get refreshed every session.

**Check `README.md` at the end of each working session too — but change it only
if it is actually wrong.** `CLAUDE.md` and `TODO.md` accumulate; `README.md` must
not. It is user-facing documentation for a stranger cloning the repo, and its
value is in staying short enough to read.

The test is: **would someone who has never seen this project be misled, blocked,
or surprised?** If yes, fix it. If the only thing that changed is *how we got
here*, leave it alone.

Edit it when:
- a number in it has drifted (test count, tunable defaults, dependency list)
- a command, config key, or flag was added, renamed, or removed
- behaviour changed in a way a user would hit (new banner, new recovery path)
- a sample no longer matches real output
- a claim in it became false

Never put in it:
- session narrative, defect tables, or what we tried and rejected — that is what
  the other two files are for
- rationale that only makes sense with this session's context
- anything true only this week

**Prefer replacing or deleting over appending**, and **generate samples by
running the code**, never by hand — the board excerpt in `README.md` sat there
with a `DIV` value that the configured threshold would have flagged, showing a
state the tool cannot actually produce.

**The user owns the remote and `main`.** Never run `git push`, `git merge`,
`git rebase`, or any command that touches `main`. Pushing and merging are the
user's alone.

Agents **may** `git add` and `git commit` on a feature branch — this is required
for the review loop in `superpowers:subagent-driven-development`, which generates
reviewer diffs from a commit range. Outside that loop, prefer writing files and
reporting what's ready rather than committing unprompted. Read-only inspection
(`git status`, `git log`, `git diff`) is always fine.

## Leagues

| League | Platform | Draft | Format |
| --- | --- | --- | --- |
| Bros with no hoes (`1395959490938966016`) | Sleeper | **DRAFTED 2026-09-01** | snake, 12 team, 15 rd, seat 5 |
| Yahoo league (id in `.env`) | Yahoo | **DRAFTED 2026-09-01** | snake, **10 team**, seat 2 |

**Both drafts are done.** Sleeper completed 180 picks and the roster reads from
the API; the Yahoo roster has no API and must be hand-entered for season mode.
The 2026 season starts **Sept 9** (`state/nfl`), so week 1 lineups are the first
live use of the tool after the drafts.

Sleeper scoring: full PPR, 0.1/yd rush+rec, 0.04/yd pass, **6-pt passing TDs**
(not Sleeper's default 4). Roster `QB/RB/RB/WR/WR/TE/FLEX/FLEX/K/DEF` + 5 bench.

**Yahoo scoring (user-supplied 2026-08-24, complete). Must be hand-entered — no
API access.** Roster `QB/WR/WR/RB/TE/FLEX/FLEX/K/DEF` + 5 bench —
**ONE RB slot, not two; confirmed by the user 2026-09-01 against Yahoo's own UI**
after they noticed it while drafting. Two FLEX, everything else unchanged. So it
is NOT the same shape as the Sleeper league (which starts two RBs), and it is 10
teams rather than 12. `config.toml` was corrected by the user the same day.
Mapped to Sleeper stat keys for `score_stats`:

```
pass_cmp 0.25  pass_yd 0.04  pass_td 6   pass_int -2   pass_2pt 2
rush_yd  0.1   rush_td 6     rush_2pt 2
rec 0.5        rec_yd 0.1    rec_td 6    rec_2pt 2
fum_lost -2    fum_rec_td 6

K:   fgm_0_19 3  fgm_20_29 3  fgm_30_39 3  fgm_40_49 4  fgm_50_59 5
     fgm_60p 5   xpm 1        (no FG-miss penalty — differs from Sleeper's -1)

DEF: sack 1  int 2  fum_rec 2  def_td 6  def_st_td 6  st_td 6  safe 2  blk_kick 2
     pts_allow_0 10  _1_6 7  _7_13 4  _14_20 1  _21_27 0  _28_34 -1  _35p -4
```

Unmapped: "extra point returned 2" has no clean Sleeper key (negligible).

**Replacement levels:** Sleeper QB12/TE12/RB36/WR36; Yahoo **QB10/TE10/RB20/WR30**.
Generated 2026-09-01 by running `replacement_ranks` against the corrected
settings, not by hand.

**CORRECTED 2026-09-01 — Yahoo was recorded as RB30 and it is RB20.** The cause
was the roster shape above: this file said two RB slots, Yahoo starts one. Two
consequences, one harmless and one not:

- **The board was NEVER wrong.** `config.toml` is what the engine reads, and it
  carried `RB = 2` until the user corrected it — so the pre-draft Yahoo board WAS
  computed against two RB slots and was wrong in exactly the way this file
  described. The draft is over, so that cost is spent and unrecoverable.
- **RB20 makes RBs worth LESS in Yahoo, not more** — the opposite of what the
  strategy table below concluded. One RB starter plus a shallower 10-team pool
  means replacement-level RB is a much better player than at RB36.

**The two leagues differ in ways that change the board, not just the numbers:**
- **10 teams vs 12** — shallower replacement (QB10, ~RB25, ~WR30), so elite players
  gain value relative to the pool.
- **Half PPR (0.5) vs full PPR (1.0)** — shifts RB/WR balance.
- **0.25 per completion** — unique to Yahoo. Allen's ~313 projected completions are
  worth **+78 points**, comparable to 13 passing TDs. Systematically favours
  high-volume pocket passers over rushing QBs. The two leagues want different QBs.
- **INT −2 vs −1.**

Known blind spot: return yards/TDs are scored in the Yahoo league but Sleeper's
projections carry no return stats, so those categories contribute ~0.

**Validated 2026-08-24 against real projections. THE RB ROW IS NOW INVALID** —
it was computed with `RB = 2` in config, and Yahoo starts one RB. The QB rows are
unaffected: QB replacement is QB10 either way, and the completion bonus that
drives them has nothing to do with the RB count.

| | Sleeper | Yahoo |
| --- | --- | --- |
| QB1 off the board | pick 24 | **pick 18** |
| QB2–4 | 54, 56, 61 | **39, 40, 44** |
| QB2 identity | L. Jackson | **J. Burrow** |
| Top 13 | mixed | ~~9 of 13 are RBs~~ **INVALID** — computed against two RB slots (see above) |

Draft strategy consequences: **take QBs ~15 picks earlier in Yahoo**, and **prefer
volume passers over rushing QBs there** — the completion bonus rewards attempts,
not legs, so Burrow rises to QB2 while Jackson leaves the top four. Inverted from
Sleeper. The RB tilt comes from half PPR plus 10-team shallower replacement.

**Precision caveat added 2026-08-25 (`TODO.md` §15).** The arithmetic above is
correct and is not in question. But measured across 2021–2025, **no position
ranks its own top 12 better than ~+0.35 Spearman** — the gap between tiers is
real, the order *within* a tier is close to noise. So the POSITIONAL call (QB is
scarcer in Yahoo, move it up) is far better supported than the IDENTITY call
(Burrow specifically over Jackson specifically). Take the tier early if the board
says so; do not agonise over which name inside it.

## Code conventions

- **Python 3.12.** Stdlib first — `tomllib` for config, `statistics.NormalDist`
  for survival math, `sqlite3` for persistence.
- **Draft-mode dependencies are `requests`, `yfpy`, `dash`. Nothing else.**
  No pandas (the pool is ~560 players; a list of dicts is what Dash wants
  anyway). No scipy. No PyYAML. Adding a dependency needs a reason that a few
  lines of stdlib cannot cover.
- **`value.py` is pure.** No I/O, no network, no globals. All logic lives there
  so it tests without a network. If something in `value.py` wants to fetch, the
  design is wrong. **`season.py` obeys the same rule** — including for the
  snapshot, where deciding what a row SAYS is logic and lives there, while
  `store.py` only knows how to write one.
- **`store.py` is the ONLY stateful module** (`season.db` at ROOT, gitignored).
  It takes an open connection and holds no globals. **No test may reach the real
  database** — `tests/conftest.py` redirects `store.DB_PATH` autouse and
  suite-wide, after a green suite was found writing rows into production under
  real league names, one of which would have replaced a real week-1 record.
- **No module-level league state.** Every function takes league context. Two
  leagues on two platforms is a requirement, and a "current league" global is a
  rewrite to undo.
- Config is `config.toml`; secrets are `.env`, gitignored.
- Mark deliberate shortcuts with a `ponytail:` comment naming the ceiling and
  the upgrade path.
- Non-trivial logic leaves one runnable check behind. One `test_value.py` plus
  `preflight`. No mocking the network — the pure core doesn't need it.
- **No test may reach the network**, guarded autouse and suite-wide in
  `tests/conftest.py` beside the database redirect. A test that quietly starts
  fetching keeps PASSING; the only symptom is that the suite gets slower, which
  nobody reads. That is exactly how it was found — wiring nflverse into
  `lineup` sent the whole suite to the network and the tell was 0.68s -> 4.78s.
  Loaders called with an explicit `fetcher` are unaffected; the guard closes the
  default path, which is the one a new call site picks up by accident.
- **A new test must be shown to fail before the fix**, by
  `git stash push -u -- ffhelper && pytest -k <name>`. A test written after a fix
  and never seen red is not evidence. **The `-u` is not optional when the test
  covers a NEW file**: plain `git stash push` leaves untracked files on disk, so
  the module stays present, the tests pass, and the run looks like evidence while
  proving nothing.
- **Add a mutation to `scripts/mutate.py` alongside non-trivial logic.** It is
  one line and it is the only mechanical check that a test does anything.
  **A surviving mutation is evidence about the TEST: fix the test, never weaken
  the mutation.** And if a mutation survives because no test can REACH the code
  — a callback sealed inside a registration function, a branch with no seam —
  that is the finding: untestable code is untested code, and the fix is to give
  it a seam, not to skip the mutation.
- **`scripts/mutate.py` rewrites source files in place. Run it in the
  FOREGROUND, alone**, never backgrounded and polled: anything else touching the
  tree at the same time collides, and a frozen file can show as modified until
  it restores. **"Alone" includes subagents** — a reviewer running its own
  mutation check concurrently corrupted two runs on 2026-09-02, and the results
  looked entirely normal. Capture `git status` before and after and diff them.
  The tool now refuses a mutation whose target string matches more than one
  place, because `replace(old, new, 1)` silently takes the first and then
  reports "killed" for breaking a function the label does not name.

## Non-negotiables

These exist because breaking them causes silent, hard-to-detect wrongness.

1. **Never join load-bearing data on player name.** Projections, the player DB,
   and the crosswalk all join on integer IDs. FFC is the one fuzzy join and it
   is enrichment-only, applied *after* the ID-keyed board is complete. Match key
   is (normalized full name, position, team) — last name + position + team is
   not enough (Bijan and Brian Robinson are both ATL RBs).
2. **Never blend projection rank with ADP rank into one number.** Surface the
   divergence as a flag. Blending pulls the board toward the field, and a board
   that tracks consensus produces consensus results — which removes the entire
   reason the tool exists.
3. **Unmatched players are printed, never silently dropped.**
4. **The live loop never dies.** Wrapped poll, logged exception, `continue`.
5. **Never commit cached projections.** Sleeper's projections endpoint is
   undocumented and the data is Rotowire's. Fetch at runtime. The repo is public
   and tied to a job search — same reasoning that ruled out FantasyPros.
6. **No auto-pick.** The tool advises; it never drafts.

## Decisions and why

Recorded so they don't get re-litigated. Reversing one needs a new reason, not a
fresh opinion.

- **Sleeper is the data backbone for *both* leagues** (projections, player DB,
  ADP) and *one of two* pick feeds. Yahoo replaces only the feed. The engine
  never knows which platform it serves.
- **DynastyProcess `db_playerids.csv` is a Phase 1 dependency, not season mode.**
  Sleeper's own `yahoo_id` is unusable: 0/302 rookies, 13/692 sophomores. Gibbs
  (RB1) has none. DP covers 99.9%.
- **Both leagues use `adp_source = "sleeper"`.** `yahoo-main` moved off `ffc`
  2026-08-26 on 540 pooled picks across three Yahoo mocks: FFC's calibration
  spans 24 points and is not monotonic, Sleeper's spans 47 and rises throughout.
  This replaced an unmeasured mechanism argument. `TODO.md` §12a; one config line
  reverts it. **Known and unfixed: both are ~25–35 points too pessimistic in
  level, so SURV is an ordering, not a probability.**
- **FFC stays — but ONLY for bye weeks now, and that is the whole reason.**
  Since both leagues moved to `adp_source = "sleeper"`, `apply_ffc_adp` runs with
  `set_adp=False` and contributes exactly one field: `bye`. Sleeper has no bye
  week anywhere — not in the 48-field player DB, not in the projection rows — so
  the join cannot be deleted, but its old justification is obsolete.
  **Superseded:** the original reason was that FFC's per-player `stdev` cannot be
  synthesized (fitting `stdev = 0.287 × adp^0.809` gives R² = 0.574). True, and
  no longer load-bearing: measured 2026-08-26 on 540 pooled picks, swapping the
  fitted curve for FFC's real stdev on the 208 players that have one moved
  calibration from 46/60/72/83/93 to 43/62/72/86/92 — noise. **Every player now
  uses `curve_stdev` and it costs nothing measurable.** Independent confirmation
  of the older "mean >> spread" result. (I then concluded the level error must
  therefore be the MEAN. Wrong — see the next entry; the model was computing the
  wrong quantity. Ruling out the spread eliminated one suspect, not two.)
- **Survival is CONDITIONAL on the player still being available**, as a
  variance-matched logistic. Changed 2026-08-26 after three transcribed mocks
  (540 picks) showed the old unconditional form was pessimistic for every row on
  every board, not just fallers: calibration error 0.145 → 0.081. `TODO.md` §2
  carries the full reopen note, including what the 2026-08-25 rejection got right
  and what it got wrong. Board ordering barely moves; the SURV column changes a
  lot.
- **Engine is VBD + survival-weighted VONA.** Rejected: a static VBD board (a
  printed cheatsheet that never answers the question at the clock) and
  Monte-Carlo simulation (no data to fit an opponent model, too slow for a 120s
  clock, fails silently).
- **Custom scoring is correct but marginal.** The 6-pt passing TD moves raw
  totals a lot (Allen 361.5 → 415.5) but VBD is a difference and a uniform shift
  cancels at replacement (Allen's VBD 65.8 → 68.0). Build it — it's ~10 lines
  and simply right — but VONA and survival carry the edge. Do not oversell it.
- **`lineup_value()` is a standalone pure function.** Phase 1 needs it for
  starter-slot awareness; Phase 5's trade finder needs the identical function.
  Never inline it into the board.
- **Waiver notify-bot is cut, and the reason survives a corrected premise.**
  Claims resolve in a scheduled batch (`waiver_clear_days: 2`,
  `waiver_day_of_week: 2`), so submission time buys nothing. That is what the
  cut rests on, and it is unaffected by the correction below.
- **CORRECTED 2026-09-02: the Sleeper league is NOT FAAB. It is ROLLING WAIVER
  PRIORITY.** Confirmed by the user against Sleeper's own UI. This file and both
  specs said FAAB, and the claim's entire provenance was `waiver_budget: 100` in
  the settings payload — **a field Sleeper returns by default whether or not
  bidding is on.** The live evidence points the other way: `waiver_type: 0`, and
  all 12 rosters carry a distinct `waiver_position` 1-12 with
  `waiver_budget_used: 0`. Same shape as the Yahoo one-RB-slot error — a league
  setting inferred from an API default instead of read off the platform's own
  screen. **Consequence for 4c: there is no bid to derive.** Priority is a
  consumable ordering, not a currency, so the honest output is your position and
  what a claim costs you, never a manufactured dollar figure.
- **Yahoo risk is confined to draft day.** The risk is unrepeatability, not
  difficulty. In-season Yahoo is *lower* risk than Sleeper draft mode. Phase 0
  OAuth is never wasted — season mode needs it regardless.
- **Trade finder will not output an acceptance probability.** Acceptance depends
  on attention, name-brand bias, and stubbornness; a confident percentage would
  dress up a guess. Rank by a transaction-history prior instead.
- **Sleeper's picks endpoint is CDN-cached and the poll must defeat it.** It is
  served `public, s-maxage=86400, stale-while-revalidate=300` behind Cloudflare,
  so a plain poll is answered from the edge and never reaches origin. Measured on
  a LIVE 180-pick draft by polling both ways at once: the plain URL was late on
  **180 of 180 picks, median 8.3s, p90 14.9s, max 27.9s, never once ahead.** A
  `Cache-Control: no-cache` REQUEST header is ignored; a unique query param is
  not. `feeds.py` now appends `?_=<ms>`; the CACHE KEY stays `picks_<draft_id>`
  or a long draft writes one cache file per second. Cost: RTT 146→303ms against
  a 1000ms poll, 60 req/min against the ~1000/min block threshold.
  **Right-size it:** that room ran at 2.48s/pick; at the Sleeper draft's 90s clock an 8s
  staleness is nearly invisible. Sleeper's own app uses a websocket, which is why
  its UI always looked ahead of the board.
- **Tiers are drawn from the FULL pool, not the available one.** Same defect as
  `TODO.md` §11 #3 (replacement level), one line below the fix that was already
  made for it. From `available`, labels drift upward all draft: 32 of the top 40
  rows carried a wrong tier by pick 20 and **all 40 did by pick 160**, where a
  preseason tier-11 receiver rendered as "tier 1" because he was merely the best
  one left. `value.py` was unfrozen a SECOND time for this, deliberately, on a
  measured blast radius: every row at picks 1/20/40/80/120/160 came back in the
  identical order, because `tier` is not in the sort key.
- **The web board's tier BANDS were replaced by a coloured tier BADGE.** Two
  alternating background shades cannot group a board that interleaves positions
  by VONA — RB tier 4 sat at rows 7, 8 and 10 with a WR between, and a band can
  only group ADJACENT rows. Found by the user reading a real board. The signal
  had to move into the row, not sit behind it.
- **The `toggle 'mine'` override hides itself on a league with a feed**, where it
  is inert: the pick's own `draft_slot` is authoritative and cannot drift. `undo`
  stays on BOTH — a misclick unions into `drafted` and silently removes a player
  who is still available, and undo is the only recovery.
- **The board will NOT fork per league.** Asked 2026-08-28: keep `DataTable` for
  Yahoo (click entry) and give Sleeper the custom table, switched by the dropdown.
  It works technically — `board_rows()` returns plain dicts and one consumer —
  and is rejected because every later board change would be built twice, and
  because the benefit (protecting a rehearsed click path) expires when Phase 3.7
  runs, which is after both drafts. Fork on TIME instead: one `html.Table`, the
  `DataTable` kept behind a config flag for one cycle, flag deleted once a live
  mock passes. A dual path with a deletion date is a migration; one keyed on
  league is a second implementation forever. `TODO.md` §19.
- **Ruled out:** FantasyPros (paid, ToU bars reproducing content), ESPN/Yahoo
  scraping, `nfl_data_py` (deprecated by nflverse → use `nflreadpy`).
  **Refined 2026-08-26:** the FantasyPros bar is on *reproducing* their content —
  committing a sheet here or shipping a fetcher — not on reading one locally. Their
  free ECR download is a legitimate 20-minute local look (`TODO.md` §18), but it
  can never enter the engine: ECR is RANKS, VBD needs POINTS, and manufacturing
  points from a rank is precisely the blend non-negotiable #2 forbids.
- **The MATCHUP ADJUSTMENT is CLOSED as of 2026-09-02 — on a measurement, and
  nothing is shown on screen.** The spec's own third guard said it may not
  reorder anything until it beats unadjusted projections out of sample.
  `scripts/backtest_weekly.py` scored it on 2024 AND 2025 (~8000 player-weeks,
  both leagues' scoring) and it **lost at every position and every shrinkage
  level**, with error rising monotonically as the adjustment gets louder — so
  the best shrinkage is the one that turns it off. Out of sample the factor
  correlates **+0.02 to +0.06** with a player's actual weekly deviation from his
  own mean, while the projection's OWN week-to-week movement correlates **+0.05
  to +0.22**: Rotowire already carries whatever weekly signal there is.
  **Ruling out one suspect is not a verdict, so the estimator was checked too** —
  a schedule-adjusted version (each game expressed against that offense's own
  season mean, which removes the confound of who a defense happened to face)
  behaves identically, and the split-half stability of the rate flips sign
  between seasons at the same position (WR +0.351 in 2025, −0.268 in 2024). A
  quantity that unstable is noise.
  **The spec's stated fallback — ship the points delta display-only — was
  declined**: a number with r≈0.04 to outcomes, printed beside a projection that
  has real signal, is the over-reaction the spec itself calls the commonest
  fantasy error a tool could automate. `season.points_allowed`,
  `matchup_factor`, `matchup_deltas` and `data.load_weekly_actuals` all stay —
  they are what the backtest scores and the one line that reopens it.
  **To reopen, bring a season where the adjustment wins that table.**
- **What ships instead is DESCRIPTIVE CONTEXT, and the distinction is the whole
  point** (chosen by the user 2026-09-02 after both alternatives were measured).
  Each row carries `vs CAR soft 31/32` — where that opponent RANKS in points
  allowed to that position so far this season, 1 = stingiest, under this
  league's own scoring. It states what a defense HAS given up, which is true and
  checkable; it never states what a player WILL score. No number it produces
  touches a projection, the sort key, or the snapshot's `matchup` column, and
  the line under the lineup says so on screen.
  **The tercile label was measured too, not assumed.** Residual (actual −
  projected) by matchup tercile, out of sample: RB and TE point the right way in
  both seasons, QB and WR point the WRONG way in 2024 (QB +1.00 → +0.76, WR
  +0.65 → +0.26). Under a null of no signal, ≥2 of 4 positions agreeing across
  two seasons happens ~69% of the time — so that table is not evidence either,
  and the column is presented as a fact about the past rather than a hint about
  the future. Silent below 3 completed games per defense, and silent in week 1.
- **Weekly projections for a PAST season are survivorship-filtered, and it
  bounds every weekly measurement this project will make.** Measured
  2026-09-02: 6165 projected player-weeks in 2025, **6 of which did not play
  (0.1%)**. A real week loses 1–3% of projected starters to inactives, so the
  set served today has been filtered after the fact to who played. The values
  themselves look untouched (r = 0.67–0.80 against actuals, MAE 3.5–4.7; a
  copied number would read r = 1.0), so the contamination is the POPULATION, not
  the numbers. Consequence: **absolute weekly accuracy from this source may
  never be quoted**, while a comparison scoring two arms on the identical rows
  survives. This is `backtest.py`'s frozen-source check finding a second, subtler
  failure mode — the source is not revised, it is pre-selected.
- **ESPN as a second projection source is CLOSED as of 2026-08-25 — on a
  measurement, not a preference.** It was reconsidered (its JSON API is not HTML
  scraping, and it joins on `espn_id` through the crosswalk we already fetch),
  then backtested head-to-head against Rotowire on real 2025 outcomes. **Rotowire
  won: MAE 66.5 vs 70.5 overall, and 75.3 vs 93.2 at QB.** Averaging the two
  never beat Rotowire alone. Fantasy Football Analytics' 2014–2025 study
  independently ranks ESPN last of 11 sources for 2023–2025 and last at QB. Every
  measured accuracy leader (Draft Sharks, Action Network, Footballguys, FTN) is
  paywalled — there is no free source demonstrably better than the one in use.
  Full costing in `TODO.md` §13; `scripts/backtest.py` reproduces it in a minute.
  **To reopen, bring a season where ESPN wins, not a fresh opinion.**

## Phases

| Phase | What | Target | Status |
| --- | --- | --- | --- |
| 0 | Yahoo OAuth handshake; confirm league access, size, settings | Aug 25 | **blocked — awaiting Yahoo approval** |
| 1 | `data.py` + `value.py` + `cli.py`, Sleeper feed, multi-league config, **manual mark-drafted** | Aug 28 | **COMPLETE** — incl. Task 13 |
| 2 | Yahoo feed adapter + ~~SQLite draft log~~ | — | **draft log CUT 2026-09-01** (crash recovery is moot with the drafts over; season mode designs its own persistence). Yahoo feed still gated on approval, and now targets season mode |
| 3 | Dash UI | Sept 5 | **COMPLETE** — Tasks 1-9, rehearsed live |
| 3.5 | Opponent needs, bye clustering, notifications, manual overrides | Sept 5 | not started — but the bye CLASH flag landed 2026-08-28 in `board_rows`, presentation only, sort untouched |
| 3.6 | Web board appearance — CSS/layout half (`assets/*.css`, no new dependency) | Aug 28 | **COMPLETE** — built early on the user's call |
| 3.7 | Web board — the `DataTable` replacement and what it unlocks | offseason | not started — `TODO.md` §19. **This is the half 3.6 deliberately cut**, not new scope. Also the trigger for the deferred `board.py` fold |
| 4a | Season mode — weekly start/sit (`lineup`) | week 1 (Sept 9) | **COMPLETE AND MERGE-CHECKED 2026-09-02**, branch `phase-4a-start-sit`, 377 tests / 153 mutations. Runs against both leagues. Awaiting the user's merge |
| 4b | Matchup adjustment + weekly backtest + snapshot table + nflverse injuries | in-season | **COMPLETE 2026-09-02** (branch `phase-4b-snapshot`). Snapshot table shipped; `backtest_weekly.py` shipped and it **closed the matchup ADJUSTMENT** — measured on 2024 and 2025, it loses — so what ships is a descriptive opponent RANK that nothing consumes (see Decisions). nflverse practice report shipped and joins 14/15; `injuries_2026.csv` is a 404 until ~Sept 10, so it prints its degraded line today |
| 4c | Waivers — free-agent pool, ROS horizon, trending as the price signal | in-season | not started. **Unblocked 2026-09-02**: every endpoint answers, weekly projections exist for all 18 weeks, byes read as an ABSENT ROW not a zero. **No FAAB bid** — see the correction in Decisions |
| 5 | Trade finder (own spec) | in-season | not started — unblocked earlier than expected: Sleeper serves every team's roster with no auth |

Phase 1 builds against the Sleeper feed because it needs no auth and Sleeper
mock drafts are free — it is the test harness that de-risks the Yahoo adapter.

## Known open risks

- **YAHOO API ACCESS STILL DOES NOT EXIST. No answer as of 2026-09-01.**
  The Fantasy Sports API is no longer self-serve: access must be applied for at
  `sports.yahoo.com/developer/access/` and reviewed by the Yahoo Fantasy Sports
  team. Applied 2026-08-24, quoted **1–2 weeks**; that window has now elapsed
  without a reply. Read-only is the default tier, which is all this project needs.

  **It cost nothing for the drafts and it costs more in season**, which is the
  reversal worth noticing: draft mode needed Yahoo for one evening and worked
  around it by hand, but season mode wants the Yahoo roster every week for
  seventeen weeks. Until it arrives, **Yahoo's roster is hand-entered and its
  transactions are invisible** — so Yahoo gets start/sit, and waivers and trades
  are Sleeper-only in practice.

  Three consequences, all of which shaped Phase 1 and still bind:
  1. **No settings sync for Yahoo either.** `scoring_settings` and
     `roster_positions` are API features. `config.toml` must accept hand-entered
     league settings (scoring dict, roster slots, num_teams) for platforms with no
     API access — otherwise the Yahoo board is computed against the wrong scoring.
  2. **Manual mark-drafted is the Sept 1 Yahoo interface**, not a fallback. It
     needs partial-name search, disambiguation on ambiguous prefixes (the
     Bijan/Brian problem — a wrong pick silently corrupts the board), undo, and
     non-blocking input. The earlier "~10 lines" estimate was for the trivial
     safety-net version and is wrong for this.
  3. **Phase 2 split, and half of it is now cut.** The Yahoo adapter moves to
     whenever access arrives, targeting season mode — where Yahoo matters more
     anyway (weekly cadence, testable, no unrepeatable deadline). The SQLite
     draft log is **cut** as of 2026-09-01: its stated payoffs were mid-draft
     crash recovery (moot) and being season mode's persistence layer (which
     should be designed for season mode, not inherited).

  The engine is platform-independent, so the board still works: the feed only
  supplies who is already gone, which the user reads off Yahoo's own UI.
- **Yahoo can now be integration-tested the moment access arrives** — the league
  is real, drafted, and in season, so `league_key`, rosters and `draft_results`
  all exist. The August version of this entry said the opposite, and it was true
  then: mock lobbies expose no `league_key`. **This risk is retired by the season
  starting, not by anything we built.**
- **Yahoo rate limits are undocumented** and enforced per registered app ID.
  Poll Yahoo at 10–15s, not 5s.
- **Single-source projections — accepted, no longer merely tolerated.**
  Everything downstream inherits Rotowire's opinions, and the ADP divergence flag
  shows *where* they disagree with the market but cannot say who is right. The
  obvious second source was tested and is worse (ESPN — see Decisions), and
  averaging the two was worse than Rotowire alone. The remaining risk is real but
  it is now a *measured* floor rather than an unexamined one: absolute accuracy
  is poor for everybody (2025 top-N MAE of 66.5 season points), so the honest
  upgrade is a confidence interval on the board, not another opinion. Offseason.
- **Draft slot is not final** — must be a config override, never trusted from
  the API. `draft_order` was incomplete (11 of 12, slot 8 open) at the 2026-08-25
  and 2026-08-31 checks; **as of 2026-09-01 pre-draft it is 12 of 12, and slot 5
  maps to `jaydenpg`** — the config value is now independently confirmed against
  display names rather than taken on the user's word alone.
- **SPENT 2026-09-01, kept as a record: the overlapping-drafts risk and the
  two-boards-at-once check.** Both drafts ran the same evening and are done.
  Whether the mitigations built for the overlap (comma batching, the on-clock
  banner as a drift detector, the per-row override) actually earned their keep is
  **not known and is not recorded here** — that is part of the outstanding
  debrief. The
  "run two boards at once" check was never executed and no longer needs to be —
  the user decided 2026-08-31 not to run the tool for Yahoo. **Neither of these
  is an open risk any more; do not re-raise them.** What carries into season mode
  from this is narrower: attribution derived from POSITION is fragile, and season
  mode should read rosters from the API wherever it can rather than re-deriving
  who owns whom.
- **NEW, and the season-mode equivalent of the single-source risk: three of the
  four data sources are undocumented.** Sleeper's projections, `lines/available`
  (props) and the trending endpoints are all unofficial and can change or vanish
  without notice — the same class as the projections endpoint, and the CDN
  behaviour in §20 is the precedent for how quietly it can happen. Every one of
  them must degrade to "column absent", never to a fabricated number, and none
  may be committed to this public repo.

## Session log

### 2026-09-02 (fourth block) — 4b FINISHED, and its headline feature was killed by its own gate

**State:** branch `phase-4b-snapshot`, **419 tests** (from 395), **175 mutations,
1 needing a look** (the documented `value.py` equivalent mutant), exit 0. New:
`scripts/backtest_weekly.py`. `lineup` re-run live on both leagues.

Phase 4b is complete: weekly actuals loader, the matchup adjustment, the weekly
backtest, and the nflverse injury report. **The matchup adjustment does not
appear anywhere on screen, because the backtest it was gated on says it should
not.**

#### The feature the slice was named for lost its own test, on two seasons

The spec's third guard was that matchup may not reorder anything until it beats
unadjusted projections out of sample. It does not:

| | 2025 | 2024 |
| --- | --- | --- |
| QB MAE, unadjusted -> adjusted | 7.68 -> 7.70 | 7.41 -> 7.48 |
| RB | 4.09 -> 4.10 | 3.91 -> 3.90 |
| WR | 4.07 -> 4.07 | 4.23 -> 4.25 |
| TE | 3.23 -> 3.24 | 3.20 -> 3.21 |

At the gentlest shrinkage tried, and **worse at every louder one** — error rises
monotonically with the size of the adjustment, so the optimal setting of the
tunable is the one that switches it off. Same answer under Yahoo's different
rulebook. Out of sample the factor correlates **+0.02 to +0.06** with a player's
actual weekly deviation; the projection's own week-to-week movement correlates
**+0.05 to +0.22**.

**Ruling out one suspect is not a verdict, so the estimator was tested too.** The
naive points-allowed rate is confounded by which offenses a defense happened to
face, so a schedule-adjusted version was measured — same instability, same sign
flips between seasons. It is not the estimator; the quantity is noise.

**The user was offered the spec's own fallback (ship it display-only) and a
middle option (a descriptive good/neutral/bad label rather than a points delta),
and chose neither.** Recorded because the flattering option was available and
declined: a number with r≈0.04 to outcomes, printed beside one with real signal,
is the over-reaction the spec calls the commonest fantasy error a tool could
automate.

The pure functions and the actuals loader STAY — they are what the backtest
scores, and they are the one line that reopens it.

#### What shipped instead: the rank, not the number

Asked for after the adjustment was cut, and it is a different kind of claim.
The row now reads

```
  WR    Puka Nacua               WR  LAR   22.3  vs BAL soft 31/32
  WR    George Pickens           WR  DAL   17.0  vs CAR tough 2/32
```

— what that defense HAS allowed to that position this season, ranked, under
this league's scoring. True and checkable. It touches no projection, no sort
key and not the snapshot's `matchup` column, and the line under the lineup says
the ranking ignores it.

**The label was measured before being built, not after.** Residual (actual −
projected) by matchup tercile, out of sample: RB and TE point the right way in
both seasons; **QB and WR point the wrong way in 2024** (QB +1.00 → +0.76, WR
+0.65 → +0.26). Under a null of no signal, ≥2 of 4 positions agreeing across two
seasons happens ~69% of the time. So the coarse form rescues nothing, and the
column is honest only as a statement about the past — which is exactly how it is
worded on screen.

Silent below 3 completed games per defense, and silent in week 1, because a rank
off two games is the over-reaction this was supposed to avoid. Ranked per
position, never pooled: in the real 2025 replay CAR reads `tough 2/32` to
receivers and `soft 31/32` to tight ends in the same week.

#### A new contamination shape, and `backtest.py`'s check did not cover it

`backtest.py` makes a source prove it was FROZEN. The weekly projections pass
that and fail a different one: of **6165 projected player-weeks in 2025, 6 did
not play — 0.1%**. A real week loses 1–3% of projected starters to inactives, so
what is served today has been filtered after the fact to who played. The values
look untouched (r = 0.67–0.80 against actuals; a copied number would read 1.0),
so **the population is contaminated, not the numbers** — the source is not
revised, it is pre-selected.

Consequence, and it binds every future weekly measurement: **absolute weekly
accuracy from this source may not be quoted.** A comparison scoring two arms on
the identical rows survives, because the bias is shared. `backtest_weekly.py`
prints the check and labels which of its own numbers survive it.

#### The suite was reaching the network and the only symptom was the clock

Wiring nflverse into `lineup` took the suite from 0.68s to 4.78s. **Every test
still passed.** The `_lineup` tests stub the loaders they know about, and a new
one is not on that list — the same shape as the snapshot writing into the
production database, and caught the same way, by a second number disagreeing.

`tests/conftest.py` now refuses the network autouse and suite-wide, beside the
database redirect, for the identical reason: a per-test rule is one the next
test forgets, and it fails in the direction nobody reads.

#### Mutation testing caught the injury test being vacuous

The week filter on the injury CSV survived its mutation. The fixture had the
same player on weeks 4 and 5, so dropping the filter let week 4 be overwritten
by week 5 and the assertion still passed — **the test could not see the bug it
was written for.** Fixed by making the extra row a DIFFERENT player, so removing
the filter adds a key. Mutation weakened: none.

#### nflverse ships, and it is a 404 today

`load_crosswalk` gained a `field` parameter rather than a second loader over the
same CSV — the cache key carries the field, or the second caller is served the
first one's mapping and every id is silently wrong. `Player.gsis_id` joins the
report: **14/15 and 13/14 on the real rosters**, the misses being team defenses,
which have no injury report at all.

`injuries_2026.csv` does not exist until week-1 games are reported (~Sept 10),
so what both leagues print today is the degraded line. **The join was therefore
proved against the 2025 file on the real roster** rather than left untested:
week 11, real report rows, correct players.

It fills the EXISTING `practice_participation` field rather than adding one,
which is why the status note and the snapshot picked it up with no change. It is
a printed LINE, not a `!!` note — the file is absent for the whole preseason and
an alarm that fires every run is one you learn to ignore.

### 2026-09-02 (third block) — the snapshot table ships. A green suite was writing to the production database.

**State:** branch `phase-4b-snapshot` (off `main` after the user merged 4a as
PR #6), **395 tests**, **161 mutations, 1 needing a look**, exit 0. New:
`ffhelper/store.py`, `tests/conftest.py`, `tests/test_store.py`.

**Week 1 is now recorded for both leagues** — 15 rows / 10 starters on Sleeper,
14 / 9 on Yahoo, one NULL projection, zero 0.0s. That is the point: the APIs
serve only current state, so a week not recorded before it is played can never
be scored. It was built before the rest of 4b for that reason alone.

#### A fully green suite was writing rows into the real `season.db`

**Found by running `lineup` for real and reading the rows back — the printed
count said 15 and the table held 17.** Not by any test.

Several `_lineup` tests stub `/state/nfl` to the same week they request, which
is exactly the condition the snapshot writes on, and nothing redirected the
path. One of the two stray rows was **`yahoo-main` week 1**, which shares a
primary key with the real week-1 record: `INSERT OR REPLACE` would have
overwritten a genuine decision with a test fixture. **Invisibly** — the row
stays present and well-formed, merely fabricated — in the one table whose
entire value is being trustworthy in December.

Fixed at the root: `tests/conftest.py` redirects `store.DB_PATH` for every
test, autouse and suite-wide. The per-test version is a rule the next
`_lineup` test forgets, and it fails silently in the only direction that
matters. Proved by deleting `season.db`, running the suite, and confirming it
does not come back; a test guards the fixture.

**The generalisable part is the discrepancy, not the bug.** Printing the count
and then querying the table is what surfaced it — two independent views of one
write. Neither alone would have said anything.

#### A default argument made the write path untestable

`connect(path=DB_PATH)` binds `DB_PATH` once at import, so monkeypatching the
module global afterwards does nothing and every test of the write path would
have hit the real file. Changed to `path=None` resolved at call time. This is
the conventions' own "untestable code is untested code" arriving in a new
disguise — and had it not been changed, the conftest fix above would have
silently failed too.

#### A survivor that was the TEST's fault, fixed in the direction the rule says

The `no current week` guard mutation survived: with it removed, the *past-week*
check catches `None` by accident (`1 != None`) and still refuses, so a loose
`"not recorded" in out` assertion passed. But it refuses **for a reason that is
not true**, naming a week the user never mentioned. The test now asserts the
specific message. **Mutation weakened: none. Test tightened: one.**

#### Design calls worth keeping

**`proj_pts` is NULL for an unprojected player, never 0.0.**
`with_weekly_points` assigns 0.0 as a *sort value* and `projected_ids` exists
solely to keep that distinct. Writing the sort value into the table built for
scoring would make an invented number indistinguishable from a measured one
months later — the exact fabrication the 4a review spent a round removing.
`matchup` is NULL for the same reason: 0.0 would read as "computed, and it came
to nothing".

**The snapshot line prints after the lineup, not inside `notes`.** Notes render
as `!!` alarms and a snapshot that worked is not an alarm — the same call 4a
made when unprojected players got a quiet section instead of a warning. But it
always prints something, because a silent record is one you never notice has
stopped working.

**A write failure costs the line, never the lineup.** The lineup is the
product; the snapshot is a side effect.

**Overwrite semantics, chosen by the user:** re-running in the current week
replaces that week, so the record is the last look before kickoff — late injury
news is exactly what moves a lineup. A past week is never overwritten, because
its inputs are not re-served.

### 2026-09-02 (second block) — 4a merge-checked and FINISHED. The verification tool was wrong twice.

**State:** branch `phase-4a-start-sit`, 20 commits, **377 tests** (from 373),
**153 mutations, 1 needing a look** (the documented `value.py` equivalent
mutant), exit 0. `lineup` and `preflight` re-run clean on both leagues.
**Phase 4a is finished. Merging is the user's.**

`TODO.md` item 3 (the merge check) is closed, and item 3a records the eight
defects the scoped re-review of `12e57b9..HEAD` turned up. Two of them are
worth carrying forward.

#### The mutation runner reported success while checking the wrong thing — AGAIN

`"panel hides empty slots instead of showing them"` used a bare
`"    return out"` as its target. That string matches **two** places in
`app.py`, and `replace(old, new, 1)` takes the FIRST — which is `board_rows`'s
filter, thirty lines above the roster panel the label names. The mutation
broke an unrelated function, that function's tests failed, and the run printed
**killed**. It has been reporting a pass for a check it never performed.

**This is the second time this tool has done this**, after the 2026-08-27
duplicate-key bug that silently dropped 26 mutations and printed a smaller
total. Same shape both times: the check reports success while checking
something else. So the fix is the guard, not the instance — an old-string
matching more than one place is now refused as `AMBIGUOUS` with the advice to
anchor on an adjacent line. Applying it immediately found nothing else wrong
(153/153 match exactly once), which is the point: it is cheap and it is now
impossible to reintroduce silently.

**Corollary the project already knew and had not applied here:** two sources of
truth disagree eventually. A mutation's LABEL and its TARGET STRING are two
descriptions of one line, and nothing was checking they agreed.

#### The first two mutation runs were contaminated by a subagent

The re-review agent ran its own `mutate.py` concurrently with mine. `mutate.py`
rewrites source in place, so for a window `ffhelper/cli.py` held a live
mutation while the other run's pytest was reading it. Both runs' `cli.py`
results were untrustworthy and were thrown away; the run was repeated alone,
with `git status` captured before and after and diffed to prove the tree came
back byte-identical.

**The recorded hazard said "run it in the foreground, never backgrounded and
polled." That was too narrow.** The real rule is that **nothing else may run it
at the same time, and a subagent counts as something else.** The conventions
now say so.

#### `load_league_users` — the sibling the fix wave missed

Rounds 1 and 2 guarded `/state/nfl`, the draft feed and the rosters endpoint.
`load_league_users` sat on the same happy path, behind the same `fetch_json`
whose `stale_ok=True` only helps once a cache file exists — so a first run on a
new machine with that endpoint down threw away a lineup whose roster AND
projections had both already been fetched successfully. Over a display name.

**Found by grepping the other callers of the endpoints the fix wave touched,
rather than by re-reading the paths it had already changed.** The fix wave had
been looking where the last defect was.

#### `preflight` said OK while the thing it exists to check was down

A failed weekly-projections join was the only failure branch that never set
`ok = False` — every sibling does — so a dead projections endpoint printed
`PREFLIGHT OK` and exited 0. Also found: `preflight` guarded on `week is None`
where `_lineup` guards on `not week`, and Sleeper serves `"week": 0` in the
offseason, so the two functions disagreed about what counts as "no week" and
one of them fetched projections for week 0.

And the `projections` line covered two different populations under one label —
**177 of 180 league-wide on Sleeper, 13 of 14 on your own roster on Yahoo.**
Both now say which.

### 2026-09-02 — PHASE 4a SHIPPED. `lineup` works on both leagues. The plan carried the defects, not the code.

**State:** branch `phase-4a-start-sit`, 16 commits, **362 tests** (from 322), 144
mutations (1 survivor, the documented equivalent mutant), suite 0.48s with no
network. Final whole-branch review: **sound, recommend merge, no Critical
findings.**

`.venv/bin/python -m ffhelper.cli lineup --league sleeper-main` prints the
optimal starting lineup for the current NFL week under that league's own
scoring, plus bench, players with no projection, and the close start/sit calls.
Yahoo runs off `.roster/yahoo-main.txt` because it has no API.

#### The one number that matters: three of four defects were in the PLAN

Every review round found real defects and **three of them were in briefs written
by the controller, shipped verbatim by implementers doing exactly as told:**

1. `with_weekly_points` fabricated 0.0 for a player with no projection, and that
   invented number drove a lineup decision with nothing recording it was
   invented. **The fabricating line was in the brief.** It violated the spec the
   brief was arguing from.
2. The fix's guard tested `stats is None`. **Real Sleeper rows for an
   unprojected player are `{"adp_dd_ppr": 1000.0}`** — a populated dict of
   descriptive fields. 2843 of 3304 week-1 rows have that shape. The guard
   passed them, `score_stats` returned 0.0, and the fabrication arrived one
   layer deeper. Found by the CONTROLLER running the code against the real
   roster, not by any test.
3. `_lineup` called `SleeperFeed.get_picks()` bare. Every other call site in the
   codebase guards it, and `get_picks` uses `stale_ok=False` **by design** so a
   failed poll raises — a contract that only holds because callers catch. A
   network blip produced a traceback and printed nothing.
4. The failure message told the user to set `roster_id` in `config.toml`, and
   `League` had no such field, so following the advice made `League(**entry)`
   raise and broke every command.

**The generalisable lesson is not "review works" — it is that a plan detailed
enough to be transcribed is detailed enough to transcribe a defect.** The
implementers were not careless; they built what was specified. Test fixtures
inherited from a brief inherit the brief's misconceptions, which is why (2)
survived a green suite and a passing mutation run.

#### `draft_slot` is NOT `roster_id`, and assuming so hands you another team

Measured before the plan was written: in the real league **draft_slot 5 maps to
roster_id 3, and roster_id 5 belongs to a different manager.** The derivation
goes through the draft's own picks and refuses (returns None) when the draft
cannot answer — Sleeper mocks set `roster_id: None` on every pick. The plan
carries a stop condition for it and the live run passes: owner reads `jaydenpg`.

#### Two design calls worth keeping

**A stale roster degrades differently in season mode than on draft night.** The
draft-night fix for a stale feed was to make failure RAISE, because a stale board
loses you a player. In season mode a twenty-minute-old roster still gives a
usable lineup, so the fix is an AGE ON SCREEN, not a hard failure. Same
information, opposite remedy, because the cost of staleness differs.

**A season-long absence must not fire a weekly alert.** Josh Jacobs is on the
Commissioner Exempt list and was drafted as a last-round stash, so he carries no
projection for MONTHS. Sleeper cannot say why — he reads `status: Active`,
`injury_status: Questionable`, body part Groin, which is simply wrong. The only
truthful signal is the ABSENCE of a projection. He renders under
"NO PROJECTION THIS WEEK -- not started, and not a zero" showing `--`, never
0.0, as a quiet section rather than a `!!` alert that would cry wolf from week 1
to week 18.

#### `practice_participation` is empty, and the spec said otherwise

Recorded because it was my error: the spec called four Sleeper fields "the
structured form of the news". Measured after shipping them — `injury_status` 256
players, `injury_body_part` 253, `depth_chart_order` 617, and
**`practice_participation` ZERO of 3231.** The claim was generalised from a
single populated row in an earlier probe. nflverse fills that gap (99% across
weeks 1-22, joining on `gsis_id` through the crosswalk already fetched) and is
scheduled for 4b — `injuries_2026.csv` is a 404 until week 1 is played.

### 2026-09-01 (post-draft) — both drafts done. The freeze lifted and was spent on one fold. Season mode scoped against live endpoints.

**State:** branch `main`, **322 tests**, 124 mutations (1 survivor, the documented
equivalent mutant). `value.py` unfrozen and edited once, deliberately;
`preflight --league sleeper-main` OK.

**The Sleeper draft completed: 180 picks, seat 5, full 15-man roster.** Pick 5
was **Jaxon Smith-Njigba** — the single player the 2026-08-31 FantasyPros
comparison identified as the one real tier disagreement, landing on the one pick
this seat owns. Recorded as a coincidence of interest, **not** as evidence the
analysis was right: nobody has scored either board against outcomes, and one
pick is not a sample.

**THE DEBRIEF, given by the user 2026-09-01 and recorded with its uncertainty
intact.** Two things, one good and one open:

- **"It worked fine, but I think it died at some point."** Unresolved, and
  **no forensic evidence survives to resolve it.** There is no journal (one is
  written only for MANUAL marks, and a Sleeper draft with a feed makes none), no
  log file (`logging.basicConfig` writes to stderr, so it lived in a terminal
  scrollback), and the picks cache mtime was overwritten by my own run an hour
  later. The draft itself ran 18:00:20 to 19:40:32 — 180 picks in 100 minutes.
  **Candidate cause, NAMED BUT NOT ENDORSED:** the 2026-08-27 mock's 14s/34s/49s
  client-side gaps were hypothesised (n=1) as Safari throttling `dcc.Interval` in
  a background tab, and dismissed on the reasoning that "the tab is foregrounded
  exactly when you are on the clock". **That reasoning does not survive a
  100-minute draft on a 90s clock**, where the tab is backgrounded most of the
  time. The user said "I think", so this is a second soft data point, not a
  finding. Do not write it up as a diagnosis without evidence.
- **The real, actionable outcome is that the tool cannot answer the question.**
  The Aug 27 mock was diagnosed only because a server log happened to be in the
  terminal. A real draft leaves nothing on disk. `TODO.md` carries the run-log
  item; it is small and it is what turns "I think it died" into an answerable
  question next time.

**Pick 5 was the user's own call, NOT the board's.** Asked directly: McCaffrey
was gone and they did not want Nacua, so they took Smith-Njigba. The earlier
entry noting that pick 5 landed on the one player the FantasyPros comparison
flagged is therefore a **coincidence and nothing more** — the tool gets no credit
for it, and the analysis was not what drove the pick. Recorded because the
opposite reading was available and would have been flattering.

The Yahoo roster was supplied by hand 2026-09-01 and lives in
`.roster/yahoo-main.txt` (gitignored): 14 players, all resolving unambiguously,
confirming the one-RB/two-FLEX shape.

#### The freeze lifted, and only ONE of the two folds was taken

`value.py` and `data.py` were frozen until the drafts. Both folds it was
blocking came due at once; only one was worth taking.

**TAKEN — `value.optimal_lineup`.** `lineup_value` returned a float and could
not say WHICH player filled WHICH slot, so `app.roster_slots_view` carried a
hand-copy of its greedy assignment. Season mode's start/sit output is precisely
that question, so this is a prerequisite rather than debt repayment.
`optimal_lineup` now returns `(slot, player)` pairs, `lineup_value` sums it, and
the panel calls it. `test_the_panel_starts_exactly_the_lineup_lineup_value_scores`
had been guarding the copy since August and now guards the real thing.

**Cost measured in both directions rather than assumed: `lineup_value` 2.9 ->
6.8 us a call, `build_board` 29.8 -> 35.2 ms on the real 626-player pool.**
Accepted and marked with a `ponytail:` comment naming the fast path if the trade
finder ever calls it hot. One tick against a 90s clock is invisible; two greedy
rules that can disagree are not.

**DEFERRED — the `board.py` / `cli._render_tick` fold.** The August note said
"after the drafts", and after the drafts the answer is still no: it buys nothing
functional (season mode never touches that derivation), the live draft path may
be exercised again at short notice, and the real cost is an import cycle
— `board.py` imports four helpers from `cli`, one of which builds a
`MarkDrafted` — so a clean fold means extracting a journal module, not moving
three functions. Reasoning and the trigger now live in `board.py`'s docstring.
**Phase 3.7 is the trigger**: that is when a board change would otherwise be
written twice.

#### Mutation testing caught a mutation I wrote badly

The new FLEX-ordering mutation SURVIVED — and it was an **equivalent mutant of my
own making**, not a coverage gap: replacing `continue` with `pass` leaves the
FLEX row matching no player whose `position == "FLEX"`, so pass 2 fills it
correctly anyway. Replaced with one that actually fills FLEX first (it then
steals the best RB, which the new assignment test kills). Two more app.py
mutations were STALE because the fold moved their target into `value.py`; one was
relocated rather than deleted.

**The rule held in the direction it is written**: a survivor is evidence about
the test — except when the survivor proves the MUTATION is vacuous, which is the
case a run only surfaces if you actually read what the mutation does.

#### Season mode (Phase 4) scoped — and the endpoints were probed, not assumed

Direction settled with the user: **start/sit + waivers as Phase 4, trades as
Phase 5**, CLI first with a Dash page after, one shared primitive
(`lineup_value` under different horizons). What the probes changed:

- **Weekly projections exist and are REVISED in-season.** Same undocumented
  Rotowire endpoint plus a week. Proved on 2025 rather than assumed: Ekeler reads
  12.1, 10.4, then 0.0 for every week after his week-3 injury; byes show as
  isolated zeroes; Barkley's line decays with his real usage. **Rest-of-season
  value is therefore a sum of remaining weeks** — the season endpoint is frozen
  preseason and is useless once anyone gets hurt.
- **Every Sleeper league endpoint is public and needs NO auth** — `rosters`,
  `users`, `matchups/<wk>` (starters, bench, per-player points), `transactions`
  (FAAB), `state/nfl`. So the trade finder's assumed blocker, reading other
  teams' rosters, does not exist on Sleeper.
- **`nflreadpy` is NOT the season-mode projection source.** The phases table has
  said "Season mode (`nflreadpy`)" since August; nflreadpy serves ACTUALS. It
  earns its place for usage (snap share, target share, red zone) and the official
  injury report, not for forward projections.
- **Sleeper serves free player PROPS, keyed on their own `player_id`**
  (`/lines/available`): receiving/rushing/passing yards, receptions, anytime TDs,
  passing TDs, interceptions, ~178 players weekly plus ~160 season-long. Those
  wager types map onto the stat keys `score_stats` already consumes, so a
  **market-implied projection in points** is buildable under each league's own
  scoring. First genuine second VALUE source the project has had — ID-joined, no
  scraping, no ToU problem.
- **The 52-field player DB already carries `injury_status`, `injury_body_part`,
  `practice_participation`, `depth_chart_order` and `news_updated`** and the code
  throws all of it away. That is "news" in structured form, free, already fetched.

**Rejected, and why:** FantasyPros ECR and scraped editorial (§18 settled the ToU
line; and converting "game-time decision" into a number fabricates a value the
source never stated). Game betting lines were checked and the free endpoints
serve only CURRENT odds — no history, so they fail §13's own standard.

**The discipline that falls out of it:** props and weekly projections are served
only as of NOW, so measuring any of this later requires snapshotting what each
source said at decision time. That — not draft-log crash recovery — is the real
justification for persistence, and it is one table. **Phase 2's SQLite draft log
is cut as scoped**: crash recovery is moot with the drafts over, and the
persistence season mode needs should be designed for season mode.

#### The spec was measured against, and three of its decisions reversed

Written, then tested against the live API before the user had to act on it. All
three reversals came from measurement, and two of them are the user's own
suspicions turning out to be right.

**1. Market props are CUT from Phase 4.** The user asked whether Sleeper's own
lines against Sleeper's own (Rotowire) projections really constitute a second
opinion. Measured per-stat: **r = +0.93 to +0.97**, median gaps 4–15%. Largely
the same view. Two traps found while getting there, both worth keeping:

- **The market number is systematically lower and that is NOT disagreement.** A
  line sits at the MEDIAN, a projection is a MEAN, and fantasy stats are
  right-skewed by long touchdowns. The first version of the analysis read that
  artifact as "the market is more pessimistic" — comparing two different
  statistics and calling the difference a finding.
- **A market-implied point TOTAL cannot be built for most players**, because
  props never cover every stat someone accumulates. Two successive versions
  produced confident nonsense (a slot receiver "projected" at 1.6 points) before
  the coverage gap was noticed. **Both errors were mine and both were caught by
  looking at which direction the residuals ran** — every "disagreement" pointing
  the same way is a bug, not a signal.

Reopen condition recorded: re-test on LIVE in-season lines in October, where
books react to injury news faster than projections and a preseason sample is
blind. Real sportsbook props are ~$30/month; free endpoints carry game lines
only, with no history, failing §13's standard.

**2. Matchup is NOT in the projections, and start/sit now carries an explicit
adjustment.** The user said matchup should count; I had assumed "weekly
projection" implied "matchup-adjusted" and never checked. **2026 preseason is a
clean natural experiment** — no injuries or usage news exist, so any variation is
schedule alone:

| | median week-to-week variation |
| --- | --- |
| top-40 RB/WR, 2026 preseason | **1.4%** of the player's own mean (max 3.4%) |
| same measure, 2025 in-season | 9.1% (max 48.9%) |

A top RB reads within a point of the same number against the best and worst run
defense in the league. The spec now builds points-allowed-by-position from
Sleeper's own weekly actuals, **shrunk toward the league mean, displayed as its
own column, and forbidden from reordering anything until it beats unadjusted
projections in a backtest** — because §15's rule against hand-picked discount
factors applies with full force to a number the tool invents for every player
every week.

**3. `nflreadpy` is OUT, reversing the user's own "everything in" call — in their
favour.** Sleeper's weekly ACTUALS endpoint carries `opponent`, `off_snp` /
`tm_off_snp`, `rec_tgt`, `rush_att` and `rush_rz_att`, which is everything
nflreadpy was wanted for. **Phase 4 therefore adds no new dependency at all.**
nflreadpy stays a candidate only for routes run, air yards and the official
participation report.

**Also raised by the user and unresolved: the Yahoo league may have ONE RB slot,
not two.** Flagged in Leagues above along with the three numbers that descend
from it. Cost nothing for the draft; costs a wrong lineup every week in season
mode.

#### Housekeeping

Deleted every `frozen until Sept 6` marker (four) and the two remaining date-
specific comments. **The `yahoo-mock` and `sleeper-mock` config blocks were KEPT,
reversing TODO's "delete them" item** — `calibrate.py` reads `num_teams` from the
named league, so deleting `yahoo-mock` destroys the ability to re-score the three
transcribed mocks, which are the only non-circular calibration data there is.
`sleeper-mock` is one `draft_id` edit away from serving a fill-in draft.

### 2026-08-31 — the Sleeper draft moved onto Yahoo's night. ECR closed on measurement.

**State:** branch `main`, **320 tests**, no code changed. `value.py` and `data.py`
untouched — the freeze held all session. Docs only, plus one new file:
`docs/2026-09-01-draft-day-strategy.md`.

**Sleeper moved Sept 6 -> Sept 1, 6:00 PM.** Yahoo is 7:00 PM the same evening, so
180 picks on a 120s clock means Sleeper is still running for the whole Yahoo draft.
Confirmed against the API rather than taken on trust: `start_time` reads
2026-09-01 18:00 local, settings unchanged at 12/15/snake/120s.

**`draft_order` re-checked, because a rescheduled draft is exactly when a league
re-rolls it.** It did not: still slot 5, still 11 of 12 with slot 8 open, identical
to the 2026-08-25 check. `config.toml`'s comment asked for precisely this and now
records the answer instead of the question.

#### The user will NOT use the tool for the Yahoo draft

Decided this session, and it is the right call — Yahoo is 100% hand-entry and
attention would be split against a live Sleeper clock. Two consequences:

- **The two-boards-at-once check is no longer needed.** It was the top outstanding
  item this morning. `--port` and the atomic cache make it work; nobody has to
  prove it now. The Known open risks entry stays as a record of the analysis.
- **§16 (the command cheat sheet) is close to moot.** Its whole purpose was the
  hand-typed Yahoo draft. Sleeper has a feed and needs no typing. Do not build it
  for Sept 1; re-raise only if a feed-less draft is ever run again.

#### §18 CLOSED — ECR fired its own stop condition

Both sheets downloaded by the user, joined on `(norm_name, position, team)`,
**zero unmatched in the ECR top 150**. Spearman vs our ADP at the top 100: +0.954
PPR, +0.972 half-PPR. §18 set the bar at ~0.95 and both clear it. ECR is PRICE and
the board already carries price twice. Nothing built, nothing committed from
FantasyPros, no fetcher — the ToU line held.

**The tier-break test was the better one, and I validated WHERE it is readable
before reading it.** FP ships a global tier; ours is per-position. Measured: RB/WR
sit ~2 apart in overall rank so a boundary between them is a real cliff, but QB
sit median 6 / max 17 apart and TE 7 / 21 against FP tiers of 5-9 players — so any
QB or TE "cliff" read off FP's global tier is an artifact. **I generated those rows
and then threw them out.** That check is the only reason the finding is trustworthy.

What survived: FP's tier 1 is six players including **Smith-Njigba and St. Brown**,
where ours is Nacua and Chase only. It lands on pick 5. Both sources agree RB tier
1 is Gibbs + Bijan.

#### Our projections vs the consensus — and the QB gap is OUR OWN SCORING

Asked as a follow-up and it was the better question. Within-position Spearman:
RB +0.99/+0.98, WR +0.95/+0.93, TE +0.95/+0.96 — median disagreement **one place**.
QB is the only exception: **+0.77 Sleeper, +0.44 Yahoo.**

Direction is identical in both leagues — we are higher on Prescott, Purdy, Nix,
Lawrence and lower on Daniels, Hurts, C. Williams. **Pocket passers up, rushing QBs
down: exactly what this file predicted from arithmetic on 2026-08-24 for the
0.25/completion bonus.** First external confirmation of the custom scoring, from a
source that has never seen `config.toml`.

**It is NOT evidence our QB numbers are better** — the two are scoring different
rulebooks, and who is right is a question this data cannot answer.

The wider result is worth keeping: ECR, ADP and Rotowire are one blob on RB/WR/TE.
There is no third opinion to be had, which argues FOR the tool rather than against
it — if every source agrees on the ORDER and §15 says order-within-tier is noise,
the edge was never in the ordering. It is in survival and VONA, which none of them
compute.

#### Two things nobody had noticed, both found by running the code

1. **Yahoo slot 2 picks back-to-back all draft** — 19/22, 39/42, 59/62, 79/82.
   Two or three apart every round from the second. You can take a PAIR, and you
   must never reach at the front of one. Nothing in the docs had said this.
2. **The real "take QBs earlier in Yahoo" rule is a TIER SHAPE, not a pick count.**
   This file says "~15 picks earlier", which was August arithmetic. Measured today:
   Sleeper is Allen then a flat **18-man** tier; Yahoo is Allen then **exactly
   three** (Burrow, Maye, Prescott) then flat. Also: Prescott is QB4 at ADP 84 and
   Purdy QB6 at ADP 124 — the completion bonus surfacing as a market error, right
   on the 79/82 pair.

#### Docs corrected, and what was deliberately left alone

Forward-looking, load-bearing statements only: the leagues table, the deadlines
table, Phase 3.7's "after Sept 6", §19/§20 labels, `config.toml`'s slot comment,
and README's "run one board at a time" (which was about to block a two-league
evening — it is per-LEAGUE, and the `--port` line is now there).

**Session-log entries and `docs/superpowers/` specs and plans were NOT edited.**
They record what was true when written; rewriting them falsifies the log.

**Also left undone on purpose: the `frozen until Sept 6` comments in `app.py`,
`board.py`, `cli.py` and three test files.** Wrong by four days, but `cli.py` is
the live draft path and it is not worth touching for a comment the night before a
draft. They self-obsolete Sept 2 — delete them then rather than editing them now.

#### Deliverable

`docs/2026-09-01-draft-day-strategy.md` — strategy differences only, no board
tutorial, every number generated by running the engine rather than transcribed.
Also published as a private phone-readable page (Artifact "Two Drafts, One Night")
since the Yahoo half has to work at a table with no tool. Two copies; keep them in
step by hand if either changes.

**Next session (Sept 1, pre-draft): get the Sleeper board running.**
`preflight --league sleeper-main` was already green today — draft_id
`1395959491899449344` resolves, feed reachable, slot 5 — but re-run it in the
morning anyway, because it is the only thing that catches an overnight settings
change.

### 2026-08-28 — PHASE 3.6. The board became a website; four defects fell out of it.

**State:** branch `phase-3.6-board-appearance`, **320 tests**, 122 mutations
(1 survivor, the documented equivalent mutant). New: `ffhelper/assets/board.css`,
`ffhelper/assets/logo.png`.

Built appearance BEFORE Phase 4 on the user's call, over my recommendation to do
the season-mode spec first. **They were right and my reasoning was half wrong:**
I argued layout work needs the "bones" of a finished dashboard, but that only
applies to LAYOUT — a token system (colour, type, spacing) is inherited free by
every page added later, so building it first is cheaper, not dearer. The binding
constraint was §19's rehearsal risk, not the bones.

Scope was cut to layout + palette, keeping `DataTable`: the click path IS
`active_cell`, and replacing it rebuilds the exact surface the Aug 27 mock found
a defect in. **The cut half is now PHASE 3.7**, written up in `TODO.md` §19 with
its five gated items — so "3.6 complete" cannot read as finishing the appearance
work. `dash_table.DataTable` is deprecated in Dash 4.4.1, so that swap is coming
regardless; the `html.Table` vs `dash-ag-grid` call is a new-dependency decision
to take at the START of 3.7.

#### Two of my own CSS rules were dead on arrival

- **The entire dropdown block matched nothing.** Dash 4.4.1 rewrote `dcc.Dropdown`;
  `.Select-control` and friends are Dash 3 and earlier. It shipped looking styled
  while doing nothing, and the control kept Dash's default `#fff` fill under
  `color: inherit` — near-white text on white, so the selected league was
  invisible. Fixed by overriding **Dash's own design tokens** (`--Dash-Fill-*`,
  `--Dash-Text-*`), which fixes every dcc control at once rather than one.
- **The green on-the-clock text never fired.** `#clock` (an ID, specificity 100)
  set `color`, beating `.page--live .topbar__clock` (two classes, 20). The border
  and glow went green; the text could not. **I wrote both rules myself, one
  cancelling the other** — the exact trap `frontend-design` warns about.

Both found by the user looking at the screen. Neither was findable by a test.

#### The user found a real engine defect by reading the tier column

Reported as "confusing"; it was `TODO.md` §11 #3 all over again, one line below
the line that fixed it. Full costing in Decisions above. **`value.py` unfrozen a
second time**, deliberately, after measuring that every row at six pick numbers
comes back in the identical order.

Worth recording HOW it was settled: the user described the symptom, I measured it
before proposing anything, and the numbers (40/40 rows wrong at pick 160) made the
decision obvious rather than a judgement call.

#### The lag was Sleeper's CDN, and I got the framing wrong

Diagnosed by measuring every layer instead of guessing — browser poll 1000ms,
server callback 154ms, our cache TTL 0, and Cloudflare serving `HIT` with `age`
climbing. Fix and numbers in Decisions.

**Then I over-claimed and the user caught it.** I said the lag was "worse than you
perceived" (8.3s vs their 3-5s). But their board was on the FIXED path during that
mock, so what they saw — near-instant — was correct; the 8.3s was the parallel
counterfactual, and their 3-5s came from a DIFFERENT draft. Two numbers from two
drafts on two code paths, presented as one correcting the other.
**Measuring correctly is not the same as reporting correctly.**

#### `calibrate.py`'s Sleeper draft-id path was entirely broken

`calibrate.py <id> <slot>` raised IndexError; with a league argument it fetched
the LEAGUE NAME as a draft id and scored the 19-digit id as the seat. Cause: the
2026-08-26 pooling refactor split argv on `isdecimal()`, and every Sleeper draft
id is all digits. Silent since that session; `tests/test_calibrate.py` green
throughout and never reached the branch. Parsing is now a `parse_draft_args`
seam **specifically so it can be tested without the network**, which is why it
survived.

#### Five Sleeper mocks will NOT settle `adp_source`

The user offered ~5 mocks matching the league exactly. Extraction is free —
Sleeper's picks endpoint is public, so `transcribe.py` (which exists only because
Yahoo has no API) is not needed. **But room discipline read median rank taken 2,
36% at top — identical to the Task 13 bot mock.** Sleeper mock lobbies are CPU,
which is why §12a moved the human mock to Yahoo in the first place. Pooling five
circular drafts would have produced a very confident wrong number. Recorded so
the offer is not re-accepted later.

#### mutation testing paid three times, and twice on tests written this session

1. `POS_STYLES` and `TIER_STYLES` share a `filter_query` string, so a dict keyed
   on the query alone collapsed them — drop POS_STYLES entirely and the test
   still passed. Now keyed on `(query, column)`.
2. The `undo`/`override` Output target could be swapped with the suite green: the
   test read a VALUE from the tuple and could not see which component it hit. Now
   asserts `app.callback_map` wiring.
3. The picks cache-key test made all three polls inside one millisecond, so the
   buggy key was identical anyway. It passed against the exact bug it existed for.

**Two mutation runs were also INVALID** — a stale assertion left the suite red,
and every mutation "kills" trivially against a failing suite. `mutate.py` reported
"0 needing a look", which reads like success. Check the suite is green before
believing a mutation run.

#### Verified live, by the user, in a Sleeper mock

Board tracking Sleeper's own UI instantaneously; tier badges correct; green clock
firing; bye clash working. Every change this session confirmed in a real draft
rather than a screenshot.

### 2026-08-27 (third block) — PHASE 3 COMPLETE. Click entry rehearsed; the handover fixed.

**State:** branch `phase-3-dash-ui` @ `15c17c8`, **309 tests**, 110 mutations
(1 survivor, the documented equivalent mutant). `value.py` and `data.py` untouched.

Task 9 steps 3 and 4 done, so **all nine tasks are complete**.

#### Step 3: the first click-entered draft. It works.

A 10-team Yahoo mock, seat 1, entered entirely by clicking, abandoned ~pick 96.
**"Much better than having to type out names. Much more responsive too with new
polling, almost instant."** Undo was used in anger — a pick missed six back — and
recovered to current.

**One defect, and it probably ended the run.** Clicking the cell already
highlighted did nothing: Dash fires a callback only when a prop CHANGES, so a
repeat click on the same cell is a silent no-op and the mark is dropped.
**The user diagnosed it from the symptom** ("you can't click the spot that is
already highlighted"), which was exactly right. `active_cell` is now cleared
after every write — which would have made the override permanently inert, so the
last-marked id moved into a Store. Also added FLEX/WRT to the filter, requested
live.

#### Step 4: the handover replayed perfectly and lost the roster anyway

Found by testing it offline BEFORE rehearsing it, which is the only reason it did
not burn the live run. The journal replay is exact — including the
`unmark` + `mark(mine=false)` override sequence nothing else produces. **But the
two boards derive `my_roster` differently**: Dash from your seat, the feed-less
CLI from typed `me` marks only. Clicking never writes those. The live journal is
**108 marks, 0 mine** — so the fallback handed you an empty roster, which makes
MARG meaningless and disables the sort's roster-need gate. Task 13 defect #1,
arriving silently at the moment you reach for the fallback.

**Fixed on the user's explicit decision**, in `cli.py`'s feed-less path only.
Verified against an INDEPENDENT source: the CLI now derives the same nine players
`transcribe.py` read off Yahoo's own results page. Handover measured at **0.48s**.

**Why an agreement test did not catch this.** `test_board_agreement` proves both
paths compute the same board from the same inputs. Attribution is an INPUT, and
the two paths built it differently — so the test was never wrong, it was aimed
one layer too low. Same shape as the dead-feed bug earlier today, where the
missing piece lived in the loop around the derivation rather than in it.
**Two defects in one day from the same blind spot: I test the join, and not what
is handed to the join.**

#### mutate.py silently lost 26 mutations, and reported success

I added a second `"cli.py"` key to the `MUTATIONS` dict. Python keeps the last
one, so an entire block vanished — and the run simply printed a smaller total
(106 → 80) with no warning. Caught only because I happened to compare the number
against the previous run. A guard now refuses to run on a duplicate key, checked
against the source text because by the time the dict exists the evidence is gone.

**This is the tooling equivalent of the project's own recurring lesson**: the
check reported "all killed" while checking 26 fewer things.

#### The fourth calibration draft, deliberately not acted on

150 picks, 10-team — the first room matching `yahoo-main`'s team count. Sleeper
0.051 weighted error against FFC's 0.116, same direction as the n=3 result, so it
corroborates and nothing changes. **The 0.051 must NOT be read as the model
improving**: this room was measurably more list-following (median ADP rank taken
5, 15% at top, against the human mocks' 7/9/10) and a room that follows the list
flatters ADP by construction.

**The user asked whether rounds 4+ were autopicks; the metric cannot answer it.**
Split at pick 96: early reads median 5 / 16.7%, late reads median 16 / 3.7%. That
looks like the late rounds were LESS list-following, which is an artifact — late
in a draft most remaining players have no ADP at all, and autodraft fills roster
requirements rather than walking a list. **Room discipline is untrustworthy once
the ADP pool thins.** Recorded so the number is never quoted as evidence.

### 2026-08-27 (second block) — the live Sleeper mock, and the worst bug yet

**State:** branch `phase-3-dash-ui` @ `540463b`, **297 tests**, 100 mutations
(1 survivor, the documented equivalent mutant). Frozen files untouched.

Task 9 **step 2 is DONE**: a full 180-pick all-autopick Sleeper mock
(`1398747013708894208`, seat 5) run live against the Dash board. **Three defects,
all past a 294-test green suite and all found by the user using the tool.**

#### 1. A DEAD FEED ERASED THE DRAFT. This is the worst defect this project has had.

`read_state` starts every call with `picks = []` and only fills it on a
successful poll. So a failed poll rebuilt the board from **no picks at all**:
back to **pick 1, the entire pool available, an empty roster** — a completely
fictional draft, rendered as though healthy.

**The CLI does not do this, and the reason is an accident of shape.** Its `picks`
is a loop variable that keeps its last good value through the `except` branch.
The Dash render is stateless and has no equivalent. Copying the derivation
faithfully (`board.py`) did not copy this, because it is not in the derivation —
**it is in the loop that surrounds it.** Worth generalising: an agreement test
proves two paths compute the same thing from the same inputs, and says nothing
about the inputs one of them silently fails to supply.

Fixed with `_LAST_PICKS`, a per-league cache of the feed's last good answer,
sitting beside the existing `_LAST_OK` and documented as poll bookkeeping rather
than draft state: never a second source of truth, never read on a healthy poll,
and a restart simply re-polls.

#### 2. The stale banner had a 15-second silent window

The banner fires above 15s, so **the first three failed polls said nothing** and
the board looked healthy while falling three picks behind. Now a quiet line fires
from the FIRST failure and escalates to the loud one at 15s.

**The user reported "wifi off about 20 seconds, never got the stale banner." The
server log says 55 seconds of continuous DNS failure.** The banner almost
certainly did appear near the end and was missed, but that is not the defect —
the defect is that nothing appeared for the first 15s of it. **Reading the log
rather than trusting either account is what separated the two.**

#### 3. You could not see your own bench

The roster panel showed starting slots only — in a 15-round draft with 10
starters that is a third of the team invisible, and the bench is *exactly* what
you are choosing between once `STARTING LINEUP FULL` is up. **The plan's own
interface line said "in roster order, then bench"; the implementation I took from
its step 3 dropped it.** Bench overflow is listed rather than truncated, since
being over the roster limit is a drift symptom.

#### What was NOT a defect, measured rather than assumed

- **"Very slow to update."** The board held its configured 5s cadence for **94 of
  122 refreshes**. Server-side work is 183 ms (callback) and 173 ms (HTTP round
  trip). 5s is right for a 120s-clock draft; an all-autopick mock lands a pick
  roughly every second, which no poll interval is going to match. **Same lesson as
  `TODO.md` §12a run 2: the mock is not the draft to optimise for.**
- **Three long gaps — 14s, 34s, 49s — were CLIENT-side**, with no server request
  in the window and no poll failure to explain them. Consistent with Safari
  throttling `dcc.Interval` in a background tab. **One sample, so a hypothesis,
  not a finding** — but the Sept 6 implication is mild either way: the tab is
  foregrounded exactly when you are on the clock, and it catches up within 5s.
- **TEs dominating the late board is `TODO.md` §14, now observed live** rather
  than merely predicted. All four late recommendations were flagged `BENCH`, so
  the tool was saying "trust yourself here" as designed. It recommended a third
  and fourth TE because bench ordering is static VBD and TE has the shallowest
  replacement. **Not fixable without inventing a number the projections do not
  carry** (§15's warning). The new position filter is the honest mitigation.

#### Our board vs the CPU autopicks: 2 of 15

Agreement only on picks 5 and 20 (McCaffrey, Chase Brown). **This says nothing
about who was right** — the autopicks walk down Sleeper ADP, the board ranks on
Rotowire VBD+VONA, and a mock has no outcome data. It is the `DIV` column
restated over a whole draft. Recorded as a shape, not a score.

**The room was all-autopick, so nothing here may touch `adp_source` or
calibration** — that is §12's circularity by the most direct route available.

#### My own errors this block, both killed by measuring

I hypothesised a **missing request timeout** causing a hang (there is one, 5s),
then **cold-start cost inside the first callback** (0.17s). Both wrong, both
disproved in under a minute. The actual cause of the long gaps was in the client,
which no amount of reading server code would have found — the server log's
*absence* of requests is what located it.

### 2026-08-27 — Phase 3 Tasks 7 and 8; the offline rehearsal is clean

**State:** branch `phase-3-dash-ui` @ Task 8, **290 tests**, 96 mutations
(1 survivor, the documented equivalent mutant). Frozen files untouched.

Task 7 (tier bands, position filter, search) and Task 8 (roster panel) are done.
**Task 9 steps 2-4 still need the user** — a live Sleeper mock, a live Yahoo mock,
and a timed ctrl-C handover. Step 1 (offline replay) is done and is below.

#### Two defects in the plan's own Task 7, both found by running it

- **The tier band grouped across positions.** The plan keyed the band on `tier`
  alone. `tier` is a PER-POSITION column, so on the real `sleeper-main` opening
  board that put Gibbs, Bijan, Nacua and Chase in ONE band — two positions, VONA
  50.1 down to 16.5. The band's whole message is "these are interchangeable",
  which is what `TODO.md` §15 supports *within* a position and what the VONA
  column contradicts *across* them. Now keyed on `(pos, tier)`.
  **Its ceiling, marked in the source:** two alternating colours cannot encode
  group identity on a board that interleaves positions — two non-adjacent runs of
  the same `(pos, tier)` can land on the same colour by chance. It only has to
  make each contiguous run read as one block.
- **The plan's test fixture had no `pos` key at all** — `{"rank": 1, "tier": 1}`.
  Same cause `CLAUDE.md` already names: a fixture built for arithmetic
  convenience rather than resembling the data the code actually meets.

#### The sealed-callback lesson from last session, applied rather than repeated

`_refresh` was reachable by no test, so the plan asserted Task 7's load-bearing
rule — **build 200 rows, filter, THEN trim to 40** — on a hand-composed list.
That test passes against a build that trims first, which is the whole defect.
`_register_callbacks` now returns `_refresh` alongside `_write`, and the seam
test was verified red by actually making that swap. Two mutations cover it.

#### Task 8: `FLEX_ELIGIBLE` is imported, the algorithm is copied, and the copy is guarded

The plan restated `_FLEX_ELIGIBLE` in `app.py`. `value.FLEX_ELIGIBLE` already
exists, and a second copy of that rule lets the panel start a quarterback at FLEX
while MARG says otherwise — **two views disagreeing about one roster.** Imported.

The greedy assignment itself still has to be copied: `lineup_value` returns a
total and cannot say which player filled which slot, and `value.py` is frozen
until Sept 6. Same shape as `board.py`, and handled the same way — an agreement
test asserts the panel starts exactly the lineup `lineup_value` scores, which is
also the proof that folding the two together after Sept 6 is a no-op.

**That agreement test failed on first run at `2550.9 != 2550.8999999999996`** —
the same players summed in a different order. Rounded, with the reason recorded
beside it: a genuinely different lineup moves this by points, not by 4e-13.

**FLEX is filled last but DISPLAYED where the config puts it** (before K/DEF).
The plan appended it after DEF, which is not how either platform draws a roster,
and the docstring claimed "roster order" while the code did something else.

#### Task 9 step 1: 543 board states replayed, no defects

All three transcribed mocks stepped pick-by-pick through the Dash callback.

| | result |
| --- | --- |
| board states rendered | **543** (3 × 181), zero exceptions |
| on-clock banner | **exactly 15 fires each, on exactly the seat's snake positions** — none spurious, none missed, all three seats |
| redundant K/DEF topping the board | **0 of 45 turns** |
| roster panel vs bench banner | agree at every state |

**Three of my own harness bugs on the way, and the third is the one that matters.**
(1) I grepped `banner_lines` for the on-clock text, which lives in `clock_line` —
reported 0 fires. (2) I applied the inferred seat AFTER `_register_callbacks` had
already closed over the league, so it silently did nothing. (3) **I took the seat
from `config.toml` — one number — for three transcripts that are seats 8, 11 and
2.** That is precisely the hole a previous session closed in `calibrate.py` by
inferring the seat from the journal, and I reintroduced it in a fresh harness one
day later. The fix was to call `calibrate.picks_from_journal` rather than write a
second seat source.

**And I nearly reported a defect that was not one.** With a full starting lineup
the board's top row was a second kicker (marg 6.0) with no bench banner — Task 13
defect #5 apparently back. It was an artifact of asking for a board at **pick 181
of a 180-pick draft**, a state no draft reaches. Measured across every real turn
instead: 0 of 45. `TODO.md` §2's rule — a constructed board state is not an
observation — caught it, applied to my own claim this time.

### 2026-08-26 (second block) — Phase 3 built to the cut line: the board is a tool

**State:** branch `phase-3-dash-ui` @ `1525cbd`, **276 tests**, 87 mutations
(1 survivor, the documented equivalent mutant). Frozen files untouched throughout.
New: `ffhelper/board.py`, `ffhelper/app.py`, `tests/test_board.py`,
`tests/test_board_agreement.py`, `tests/test_app.py`, `tests/test_dash_isolation.py`.

Spec: `docs/superpowers/specs/2026-08-26-phase-3-dash-ui-design.md`
Plan: `docs/superpowers/plans/2026-08-26-phase-3-dash-ui.md`

**Stopped deliberately at the plan's cut line.** Tasks 1-6 are done and reviewed;
7 (tier bands, filter, search), 8 (roster panel) and 9 (rehearsal) are not. Task 7
was interrupted mid-edit and its partial work is in `git stash@{0}`. The board is
a working draft tool as it stands.

#### What exists

`python -m ffhelper.app --league <name>` serves a Dash board that renders the same
engine the terminal renders. Click a row to mark a player drafted. Your roster is
DERIVED from your draft seat and pick number — the `me ` prefix does not exist on
the web board — with a per-row override when entry has drifted.

**The journal is the database.** Every render replays `.draft/<league>-<date>.jsonl`,
polls the feed, and rebuilds the board, so the process holds no draft state. That is
what makes the CLI handover exact: ctrl-C one, start the other, lose nothing.
**One process at a time** — the CLI replays only at startup, so it cannot see writes
made by a running web app.

#### Seat-based attribution is validated against real data

`auto_mine` reproduced **exactly** the roster all three transcribed Yahoo mocks
recorded independently — seats 8/11/2, 180 picks each, 15 own picks each, zero
differences. That is the check that permitted Task 6 to be built at all.

**Its accepted cost, unchanged:** attribution is derived from POSITION, so a missed
entry shifts every later pick and silently hands you the wrong roster. Mitigations
are the on-clock banner (visible drift detector) and the override.

#### A design bug of mine, caught by review, worth remembering

`read_state` composed `manual_mine = mark_state.mine | derived`. **A union can only
add.** So a "not mine" override was silently re-added by `derived` on the next
5-second tick: `auto_mine` recomputes from pick position alone, and "first mark wins"
keeps the player in his snake slot. `mine=True` overrides were durable; `mine=False`
overrides reverted — exactly backwards, since drift correction is the only reason the
override exists. The spec sold it as the mitigation making auto-attribution safe;
as written that was fiction.

Fixed by reading a record already in the journal rather than adding one:
`apply_override(mine=False)` writes `unmark` then `mark(mine=false)`, a sequence
nothing else produces. `board.explicit_not_mine` reads it, and the composition is now
`(derived - explicit_not_mine) | mark_state.mine` — explicit statements win in BOTH
directions. **A new journal op was rejected**: `cli._restore_marks` raises on unknown
ops, so a Dash-written journal would stop replaying cleanly in the terminal, breaking
the fallback the whole design rests on.

**It got through because every test called `apply_override` and `auto_mine` in
isolation. The composition seam had no test.** Same shape as Task 3's `read_state`
gap. The recurring lesson is narrower than "test more": *I test the pieces and not
the join.*

#### Mutation testing caught three vacuous tests, all specified by the plan

Not the implementations — the plan's own test code, which read as thorough:
1. Four `board_state` tests never exercised `replacement_pool`, so the mutation
   swapping the full pool for the draining one SURVIVED.
2. `test_board_rows_carry_the_player_id...` built names as `f"Player {i}"` and ids as
   `str(i)`, so swapping `sleeper_id` for `name` passed every assertion — a test
   asserting non-negotiable #1 while incapable of detecting its violation.
3. Two Task 4 mutations survived because the write callback was sealed inside
   `_register_callbacks` with nothing returned: **no test could reach it.**

(3) is why the conventions above now say untestable code is untested code.

#### Two defects in the plan document itself, found before dispatch

- **`git stash push -- ffhelper` does not stash untracked files.** Probed it directly.
  For a task that CREATES a module, the red-check would have run with the module still
  on disk, passed, and been reported as evidence. Now `-u`, and the convention above
  is corrected.
- **A module-level `server = None` populated inside `main()`** was sold as a free
  gunicorn hook. Gunicorn imports the module and never calls `main()`, so it is None
  exactly when a host reads it. Removed; the spec's "Hosting, later" now says the real
  retrofit needs league selection to leave `argv`.

#### `my_turns` is the first recursive caller of `next_pick_number`

Every other call site asks once per tick. Feeding its output back in makes a broken
"strictly after" contract a HANG rather than a fast failure — it crashed `mutate.py`
outright. Bounded loop + `RuntimeError` in `board.py`; `value.py` untouched. A hang is
the worst draft-day failure mode there is.

#### Deferred, deliberately

- **`board.py` is a COPY of `cli._render_tick`'s derivation, not an extraction.**
  Divergence requires an edit, nothing schedules one, and `cli.py` is the live draft
  path. `tests/test_board_agreement.py` guards it and is also the proof that the
  post-Sept-6 extraction is a no-op.
- Tasks 7-9. **Task 9 (rehearsal) is the one that matters** — nothing has yet
  confirmed the rendered board against the terminal's. The app has been verified only
  to start, serve HTTP 200, and pass its unit tests.

### 2026-08-26 — the human mock moves to Yahoo; calibration learns to read a journal

**State:** branch `main`, **203 tests, 54 mutations (53 killed — the survivor is
the documented equivalent mutant)**, `preflight --league yahoo-mock` OK.

Sleeper has no public mock lobby with strangers in it, so `TODO.md` §12's human
mock runs on **Yahoo** instead. Setup is done and it is ready to run; the full
runbook is `TODO.md` §12a.

**This is a better rehearsal than the Sleeper one would have been.** Yahoo has no
pick feed, so all ~180 picks are hand-typed — the exact Sept 1 interface, at full
length, under a real clock, which nothing has ever tested.

**But it cannot settle `sleeper-main`'s `adp_source`, and saying otherwise would
repeat this project's signature mistake.** §12's argument for `"sleeper"` is a
mechanism — Sleeper drafters anchor on the ADP Sleeper prints in front of them. A
Yahoo room anchors on *Yahoo's* ADP, a third number the tool does not carry.
Whichever source wins there says nothing about the Sept 6 Sleeper room. What it
*does* give is the first **non-circular** calibration the model has ever had (the
Task 13 numbers are CPU drafters picking off Sleeper's own list), and a direct
read on `yahoo-main`, which is on `ffc` and drafts first.

**`scripts/calibrate.py` now scores a hand-entered draft** from its
`.draft/*.jsonl` journal, since that journal is the only record a feed-less draft
leaves. Pick order is reconstructed from the order marks were typed; taken-back
and undone marks consume no pick number.

**It refuses to score a log it cannot trust**, which is the part worth keeping.
Journal pick numbers are only as good as the typing — miss one pick and every
number after it shifts, silently moving every survival horizon. So the picks
claimed with `me` must land exactly on the seat's snake positions, or it prints
both lists and stops. That is `backtest.py`'s "make the source prove itself"
applied to a second kind of evidence, and it is why a mock the user falls behind
in produces *no* number rather than a flattering one.

Verified by running it, not by the suite: reproduces the Task 13 mock exactly
(73/82/89/90/94 and 4/17/52/91/100) and both accepts and refuses a constructed
journal.

`scripts/mutate.py` keys can now name a path under ROOT (`scripts/calibrate.py`),
not just a module in the package.

#### Run 1 was abandoned in round 1, and the cause was ours

**State after the fix: 207 tests, 57 mutations (56 killed).**

The mock did not survive one round — typed names took seconds to land, five picks
behind almost at once. It presented as a slow terminal. It was `_run`.

**`_run` ended every tick with `time.sleep(interval)` and drained typed commands
only at tick boundaries.** A name typed just after a tick waited up to a full
poll interval — `poll_seconds = 12` on Yahoo, **spent waiting on a feed that does
not exist**, in the one mode where the board can only change because you typed
something. The loop now blocks on the input queue with the poll deadline as a
timeout (`_wait_for_input`), so a keystroke wakes it immediately and the interval
paces the network and nothing else. Measured on the real pool, yahoo-mock:
**median 34 ms, worst 39 ms** keystroke-to-redraw, from up to 12 000 ms.

**This is the ninth defect found by running the code rather than by testing it**,
and the first found by a human failing to use the tool rather than by reading
output. A full green suite covered this loop in thirteen places. None of them
could see it, because every one stubbed `time.sleep` to a no-op — **the tests
disabled the exact thing that was broken.** Worth generalising: a stub that
removes a cost also removes the ability to observe it, so wherever a test fakes
timing, nothing in that suite is evidence about timing.

**The obvious suspect was wrong, and measuring first cost one minute.** VONA
re-sorts a position list per candidate, so `build_board` looked like the culprit.
It is **20 ms** on all 632 players. Had I "optimised" it I would have shipped a
change to frozen `value.py` and fixed nothing.

**`mutate.py` caught the fix's own test being vacuous.** The first assertion was
`all(0.0 <= t <= interval)` on the wait timeout, which a mutation to a constant
`0.0` passes — and 0.0 is not "instant", it is a busy spin at 100% CPU. Second
time this session that mutation testing earned its line.

#### Run 2: responsive, still unfinished — and the mock was the wrong test

**State: 218 tests, 64 mutations (63 killed).** New file: `scripts/transcribe.py`.

Run 2 confirmed the latency fix ("much better and much more responsive") and was
abandoned anyway: **the lobby clock is 30s a pick**, which with instant autopicks
is one pick every ~8 seconds across 12 seats.

**The arithmetic says stop optimising for that.** Hand-entry matters for exactly
ONE draft — Sleeper has a live feed, so it needs no typing at all. Sept 1 is 10
teams on a **90s+ clock** (user-confirmed): ~150 picks over ~90 minutes is one
name every 36 seconds. The mock demanded it 4× faster. Run 2 did not fail a test
the real draft sets.

Built regardless, because both are cheap and both serve Sept 1:

- **Comma-batching** (`nacua, me chase, gibbs`) — one round trip instead of
  three, and the catch-up path if the real draft ever gets ahead. **This is why
  the pick-counter resync was NOT built:** batching covers the same need without
  letting the pool go knowingly stale.
- **Every command in a batch reports its own outcome.** `status` was overwritten
  per command, so `a, nobody` showed only the last result — invariant #3 broken
  in the one mode where a miss hides, because the screen still looks right.

#### The mocks were not wasted, and the reason generalises

**Live entry and calibration were coupled only by accident.** Survival is
measured from the ORDER players left the board; a finished results page carries
that order with no clock on it. `scripts/transcribe.py` turns a pasted board into
a journal `calibrate.py` reads, so **a draft too fast to type into is still a
measurable draft.**

It refuses to write unless every line resolves to exactly one player (position in
parentheses separates Bijan from Brian) — a dropped line shifts every pick number
after it.

**One hazard found by running it, not by a test:** the first version wrote to
`<league>-<date>.jsonl`, which is the live board's own journal — and
`ffhelper.cli run` REPLAYS that file on startup. A transcript under that name
would have poured a finished draft into the next live board. Transcripts now
carry a `-transcript` suffix. The overwrite guard is what surfaced it, by
refusing to clobber the real journal from run 2.

#### "Do my autopicks corrupt the calibration?" — no, but the question found a real one

`calibrate.py` never reads `my_roster`. Your picks enter only as the turn
boundaries between which the ROOM's picks are scored, and those come from your
SEAT, not your choices.

**What does corrupt it is how many OTHER seats autopicked**, since Yahoo's
autodraft walks straight down Yahoo's ADP — Task 13's circularity by a new route.
So `calibrate.py` now prints **room discipline**: median ADP rank taken, and the
share taking the top available. Validated against the known-circular Task 13
mock, where it reproduces §12's recorded numbers exactly (median 2, 36% at top)
and fires ONLY on the Sleeper source, not FFC (median 8) — correct, because those
bots picked off Sleeper's list.

**A user's "will this even work?" question produced a better diagnostic than the
plan had.** Worth noticing: the intuition was wrong in its specifics and right
about there being a problem.

#### The transcriber met the real Yahoo format, and the format was nothing like the guess

**State: 227 tests, 68 mutations (67 killed).**

I wrote the parser against an invented `1. (1) Ja'Marr Chase (Cin - WR)` and then
asked for the real paste instead of guessing further. That was the right call —
the real rows are

    (4) Paul - Seattle (Sea - DEF)
    (7) Christopher - Cook III, James (Buf - RB)

which differ in four ways that all matter: `(N)` is the pick **within its round**,
the manager's name sits between it and the player, names are **surname-first**,
and a defense is a bare city. Every one would have produced silent wrongness.
Rewritten against the file, all **180 rows resolved on the first run**.

What the real data forced, none of which the invented fixture would have:

- **Defenses join on the TEAM CODE.** The page writes `Los Angeles (LAC - DEF)`
  and there are two Los Angeles defenses. The city cannot separate them; the
  code is an identifier, which is what non-negotiable #1 asks for.
- **Suffixes must travel with the surname.** `Cook III, James` → `James Cook III`,
  so `norm_name`'s suffix stripping reaches the pool's `James Cook`. Reassembled
  the obvious way it becomes `James III Cook` and matches nothing.
- **Order comes from the reconstructed pick number, not from row order.** Round ×
  slot rebuilds the true number; rows are then SORTED by it and checked to be a
  complete 1..N run. That makes a board-view copy (even rounds right-to-left)
  work rather than merely refused, and catches a partial copy — which is the
  commonest paste mistake.

**I scored the first transcript against the wrong seat.** I passed slot 11 by
hand when `config.toml` already said 8. Root cause was the interface, not the
typo: the league carries `draft_slot`, and taking it as an argument let the two
disagree. `transcribe.py` now defaults to the config value and prints it;
`calibrate.py` warns when an explicit slot differs from the league's.

**Mutation testing paid twice more.** It found the defense team-code branch was
deletable with every test still green (plain name matching plus team narrowing
already handled "Los Angeles") — the branch earns its place only when the NAME
matches nothing, e.g. "LA Chargers", so that is now the test. And three
mutations went STALE against the rewrite, which is the script reporting honestly
that it was no longer testing anything.

#### First non-circular calibration — and it contradicts a documented assumption

Full table in `TODO.md` §12a. Room discipline read **median 7/5, 14–15% at top**
against the Task 13 bot mock's **median 2, 36%** — so this room was genuinely
looser than a list-follower, and the numbers are not measuring an ADP list
against itself for the first time in this project.

**Sleeper ADP discriminated markedly better than FFC in a YAHOO room**
(42/57/68/79/94, monotonic, vs FFC's near-flat and non-monotonic 62/84/80/85/92).
That **contradicts §12's reasoning** that "Yahoo stays on `ffc` — those drafters
are not in the Sleeper app", which was mechanism, not measurement. Both sources
are also too pessimistic in the same direction: everything survives longer than
predicted.

**It is one draft, so nothing was changed.** `yahoo-main` stays on `ffc` pending
n≥2. The important consequence is that **more samples are now nearly free** —
a mock no longer has to be typed into, only pasted afterwards — so the honest
next step is three more mocks, not a config edit.

#### Several drafts, pooled — and the seat stopped being an argument

**State: 231 tests, 71 mutations (70 killed).**

The user asked how to transcribe two more mocks from the same morning and spotted
that the output path was keyed only on date, so the second would hit the
overwrite guard. Correct. Transcripts are now named after their INPUT file
(`results2.txt` → `<league>-<date>-results2.jsonl`), and `calibrate.py` takes
**several journals and pools them into one table per source** — the right
statistic, since the question needs more than one room. Verified by pooling a
draft with a copy of itself: n doubles, percentages identical.

**The seat is no longer passed by hand anywhere.** `transcribe.py` reads it from
`config.toml`; `calibrate.py` infers it from the journal, because your own picks
are recorded in it and the first of them is your seat in a snake — then proves
the inference against the snake before scoring. That closes the hole that scored
the first real transcript against another manager. An explicit slot remains as an
override, and is announced when it differs from the league's.

**Worth noting how that bug was actually fixed.** The obvious repair was "be more
careful with the argument". The real repair was removing the argument: two
sources of truth for one fact will disagree eventually, and the log already knew.

#### n=3 SETTLED IT: `yahoo-main` moved to `adp_source = "sleeper"`

**State: 232 tests, 72 mutations (71 killed).**

Three 12-team half-PPR Yahoo mocks, **540 picks, seats 8 / 11 / 2**. Full table in
`TODO.md` §12a. **FFC spans 24 points across its whole predicted range and is not
monotonic; Sleeper spans 47 and rises in every bucket.** Consistent in all three
drafts individually. Room discipline 7/9/10 against the bot mock's 2, so this is
the non-circular evidence the question always needed.

**This reverses `CLAUDE.md`'s and §12's "Yahoo stays on `ffc`"** — which was a
mechanism ("those drafters are not in the Sleeper app") that had never been
measured, beaten by a measurement. Likely replacement mechanism: Sleeper's ADP is
a much larger national sample, and better sampling predicts any room.

**A measurement bug found in my own analysis before reporting it.** The turn set
was `[my_turns[0]] + my_turns[:-1]`, which scored the FIRST turn twice and
dropped the last — and the first turn is the earliest board state, where survival
is most extreme. Inherited from the original `calibrate.py`. Corrected to
`my_turns[:-1]` (one evaluation per consecutive pair of turns). **The numbers
barely moved**, so the conclusion held, but the order matters: it was found and
fixed before the user acted on the table, not after.

#### Session close — state and the one thing that is now due

**232 tests, 72 mutations (71 killed — the survivor is the documented equivalent
mutant). Both leagues preflight OK.** New files: `scripts/transcribe.py`,
`tests/test_calibrate.py`, `tests/test_transcribe.py`.

**Ctrl-C was re-verified against the new loop**, by subprocess and SIGINT, since
`_run` now blocks in `queue.get()` rather than `time.sleep()` and "the loop never
dies / exits cleanly" is a draft-day invariant: **exits in 0.03s, code 0,
prints `stopped`.** Not added to the suite — it needs a subprocess and the
network, and the suite's value is being 0.25s with neither. First attempt at this
test was invalid and said the opposite: a shell backgrounds jobs with SIGINT
ignored, so it was measuring the shell, not the code.

**Next session starts with `TODO.md` §16, the draft-day cheat sheet.** It was
deliberately held until the notation stopped moving; the notation moved once more
this session (comma batching) and has now stopped, the mocks are done, and the
Yahoo draft — the one where all ~150 picks are hand-typed — is six days out.

#### SHIPPED: survival is now CONDITIONAL. `value.py` unfrozen once, deliberately.

**State: 236 tests, 76 mutations (75 killed).**

The user pushed back on "nothing we can do about SURV", and the pushback was
right. **The level error was not the ADP mean. `survival_prob` was computing the
wrong quantity.** It returned the unconditional `P(X > at_pick)` when the board
only ever asks about players who are demonstrably still available — the question
is `P(X > at | X > now)`. The unconditional form is smaller by construction, so
it was pessimistic for **every row on every board**, not just the fallers
`TODO.md` §2 had been arguing about.

Fixed as a variance-matched conditional logistic (`s = stdev*sqrt(3)/pi`) —
which is exactly what §2 named as the right option "if this is ever revisited,
and it needs validation data first". **The validation data was the three
transcribed mocks.** The reopen condition set by a previous session was met as
written, which is the process working.

| model says | before | after | ideal |
| --- | --- | --- | --- |
| 0-20% | 46% | **30%** | 10% |
| 20-40% | 60% | **49%** | 30% |
| 40-60% | 72% | **64%** | 50% |
| 60-80% | 83% | **80%** | 70% |
| 80-100% | 93% | 91% | 90% |

**Weighted calibration error 0.145 → 0.081, with no fitted parameters.**

**Blast radius was measured BEFORE shipping, and that is what made it safe six
days out**: across board states at picks 2/19/42/79 on the real pool, 0–3 of the
top 10 rows reorder and no new player enters the top 10 at any of them. VONA
raises survival proportionally within a position, so comparisons survive.

Logistic over conditional gaussian on a tie (0.081 vs 0.082): a gaussian's hazard
explodes, so `S(at)/S(from)` divides by ~0 and reports a **fabricated 0.00%** for
the player most obviously still fallable. Degrade, never fabricate.

**Three of my own errors on the way, all caught by the discipline rather than by
luck.** (1) I told the user the level error "is a MEAN problem" after ruling out
the spread — but eliminating one suspect is not a verdict, and the real answer
was a third option. (2) My first board-comparison test asserted survival rises
when you stand later in the draft; it does not, because `at_pick` moves with
`current_pick`, so two boards share no horizon — the test caught my sloppy
premise. (3) Three existing tests failed on hardcoded gaussian constants; each
derivation was recomputed from the logistic formula independently rather than
read off the implementation.

**`README.md`'s sample board was regenerated by running the code**, per the rule
that samples are never hand-edited. It argues the thesis better now: Swift's
survival reads 71% rather than 61%, so "highest VBD on screen and still not the
pick" lands harder.

#### Historical: the level error, before it was diagnosed correctly

This is not a tie-break, it applies to whichever source wins. **The model says
0–20% and about half survive.** The curve sits ~25–35 points below reality,
worst in the low band, nearly right at the top.

Since survival feeds VONA, **the board systematically overstates the cost of
waiting — it leans toward reaching** — and it does so most for the players it
calls least likely to last, which are the top of the board.

**Not corrected in code**: `value.py` is frozen until both drafts are done, and a
shift fitted to three mock rooms containing autopick seats may not transfer to
ten humans. Before Sept 1 the fix is awareness, exactly as §15: **read SURV as an
ordering, not a probability.** The diagnostic next step is a per-position
breakdown — uniform bias means a model-level problem (gaussian spread or the ADP
mean), position-specific bias more likely means these mocks' half-PPR/4-pt-TD
scoring diverging from the full-PPR ADP the sources publish. Different fixes, and
only one of them transfers.

### 2026-08-25 (fourth block) — ESPN closed on measurement. Config complete.

**State:** branch `main`, **199 tests, 51 mutations (50 killed)**, `preflight` OK
for BOTH leagues for the first time. New file: `scripts/backtest.py`. Outstanding
work is `TODO.md` sections 12, 14, 15, 16.

#### Hand-typed marks now survive a restart (`TODO.md` §17)

`MarkDrafted` was memory-only. Sleeper was crash-safe by accident (a restart
replays the feed); **Yahoo has no feed**, so a mis-hit ctrl-C wiped ~150
hand-typed picks. Now journalled to `.draft/<league>-<date>.jsonl`.

**Deliberately not Phase 2's SQLite log** — that is season-mode design and
over-built for crash insurance. Ops, not snapshots, so replay rebuilds the undo
history; `undo` is itself an op, or replay would resurrect a mark already taken
back; the filename is dated so a mock never replays into a live draft.

**A judgement worth keeping: I argued against starting Phase 3 before the drafts
and the user was right to push back.** My objection was that drafting on an
unrehearsed UI is risky — but that only bites if you *use* it, and the fallback
to the terminal is free. The objection reduces to one real constraint, which is
now the rule: **freeze `value.py` and `data.py` until the drafts are done.**
Phase 3 lives behind its own entry point and never imports into the terminal
path; additive-only elsewhere. Phases 4 and 5 carry no draft-day risk at all.
Phase 3.5 is the one to watch, since opponent-needs and bye-clustering reach into
the board.

#### Manual entry hardened — the Sept 1 interface got a silent bug and a gap

Both found by reading the manual-entry path rather than by a test failing.

**The bug: claiming an already-marked player silently did nothing.** Typing a
name and then correcting it (`gibbs`, then `me gibbs`) printed "marked Jahmyr
Gibbs (RB DET) as yours" while `mine` stayed empty — the idempotency guard
dropped the whole call because the id was already in `drafted`. That is Task 13
defect #1 (empty `my_roster` → meaningless MARG) arriving by a different route,
and it is silent, which is worse. `mark()` is now idempotent **per field, not per
call.**

**The gap: no way to take back one mark.** `-<name>` added, scoped to hand-marked
players only. See `TODO.md` §3 for the full reasoning.

**`_history` now records prior membership, not a delta.** That one change makes
mark, claim and unmark all reverse through the same `undo` with no direction
flag — the unmark feature cost almost nothing because the data model was chosen
to absorb it. `pending_mine: bool` became `pending_action: str` ("" / "mine" /
"unmark") so an open disambiguation knows which command it belongs to.

**The feed now overrules a bad claim** (`TODO.md` §9). `me <player>` is a claim;
the feed is the authority on who drafted whom. A claim it contradicts is dropped
from `my_roster` — but never from `drafted`, since the player really is gone,
just not to you — and a standing `CLAIM OVERRULED` banner names the player and
the seat. Silently editing the user's own roster would violate invariant #5.

Both guards on that logic would be roster-wiping if dropped, so both carry tests
AND mutations: an unset `my_slot` overrules **nothing** (a naive `!=` makes every
pick's slot differ from `None` and wipes every claim), and a pick carrying no
`draft_slot` attributes to nobody (the exact Sleeper-mock shape that once left
`my_roster` empty for 180 picks — here it would have deleted the roster instead).

**A hint I nearly shipped was wrong twice over.** The banner first suggested a
concrete `'-nacua'` built from `name.split()[-1]` — which yields `"Jr."` for
"Marvin Harrison Jr.". Switching to `norm_name` was worse: it collapses
whitespace, so the hint became `-brandonaubrey`. Dropped the computed hint
entirely; the message names the player and the notation is on the help line
directly below. **A hint that does not match is worse than no hint at the table.**

#### `README.md` brought current, and the convention around it changed

It had not been touched in two sessions. Stale: test count (144 → 199),
`divergence_flag_slots` (25 → 10, and now within-position), and a dependency line
claiming `yfpy` is in use when it is declared but imported nowhere. Undocumented
entirely: `adp_source`, the crash journal, `CLAIM OVERRULED`, the bench and stale
banners, the `MODEL+`/`MARKET+` vocabulary, and all three scripts.

**The sample board was internally inconsistent** — it showed `DIV +17` with no
flag, a state the configured threshold makes impossible. Replaced with a real
board rendered at pick 45, which argues the thesis better than the invented one
did: Swift has the highest VBD on screen and is not the pick, because he is 61%
to survive while Maye is 23%.

**Convention changed at the user's request:** README is now checked every session
like the other two, but edited only when genuinely wrong, and kept lean —
`CLAUDE.md` and `TODO.md` accumulate, README must not. Full rule in Working
convention above, including "generate samples by running the code, never by
hand", which is what would have caught the bad excerpt.

**Config is done.** `sleeper-main` slot 5, `yahoo-main` slot 2 and league_id
723573. The Yahoo slot had been edited but left commented out (`# draft_slot =
2`), so it was still inert and preflight still read NOT SET — **re-run
`preflight` after touching config, do not trust the edit.**

#### ESPN: the question was "is their data better", and the answer is no

`scripts/backtest.py` settles "is source X better than what we use" against real
outcomes. On 2025, Rotowire beat ESPN 66.5 to 70.5 MAE overall and 75.3 to 93.2
at QB; averaging the two (68.1) never beat Rotowire alone. FFA's independent
2014–2025 study agrees, ranking ESPN last of 11 sources for 2023–2025 and last at
QB. Details and the reopen condition are in `TODO.md` §13.

**The methodological point is worth more than the result.** Both APIs happily
serve "season projections" for seasons already played, and some of those numbers
were revised as the season went — hindsight wearing a projection's clothes, which
would have inverted the answer. So `backtest.py` makes each source PROVE it is
frozen (a preseason projection gives nearly everyone a full slate, because it
cannot know who gets hurt) and **refuses to score a source that fails, naming
it**, rather than printing a flattering number. ESPN's 2024 fails outright: 6%
full-slate, median 15.12 games, **minimum 0.05 games**.

That check is `degrade, never fabricate` applied to analysis instead of to the
board, and it is the direct descendant of last block's lesson about checking the
provenance of evidence before building an argument on it.

#### I made that same mistake again anyway, and the data caught it

Off the 2025 backtest I wrote that "projections cannot rank QBs" — Rotowire's
top-12 QB Spearman was −0.287, ESPN's −0.232 independently, and the bust list
(Burrow QB5→QB29, Jackson QB1→QB20) was vivid. I put it in `TODO.md` as a live
strategy concern for the Sept 1 draft.

**It was one season.** Sleeper serves frozen projections back to 2021, so it was
checkable, and checking it killed the claim: QB top-12 ran +0.273 / +0.273 /
+0.657 / +0.727 in 2021–2024. **2025 was the outlier** (four elite QBs missed
significant time), and QB's five-year mean of +0.329 is second-best of the four
positions.

**Third time now**, so it goes in the conventions, not just the log: *a vivid
result from a single sample is a hypothesis, not a finding.* The tell is the same
every time — the number was striking, and I reached for the explanation before
the sample size.

#### What survived is better than what I thought I had

Reading that five-season table by column instead of by row: **no position ranks
its own top 12 better than ~+0.35 Spearman**, in any year. Every position has a
near-zero or negative season (RB −0.210 in 2021, TE +0.063 in 2023). Widening the
pool improves it, which is partly range restriction and so partly inevitable —
but the operational consequence stands: **the gap between tiers is real, the
order within a tier is close to noise.**

That is not a new feature request. `tier` is already a per-position column
computed from real gaps in projected points; the board just under-weights it
relative to the flat ordering. For Sept 1 the fix is awareness, not code.
`TODO.md` §15.

It also puts a precision caveat on this file's own Yahoo strategy: the positional
call (QB is scarcer in Yahoo, move it up ~15 picks) is far better supported than
the identity call (Burrow over Jackson). Burrow was 2025's signature QB bust.

### 2026-08-25 (third block) — TASK 13 DONE. Ten defects found by drafting.

**State:** branch `draft-night-fixes`, **174 tests, 37 mutations (36 killed)**.
Outstanding work is in `TODO.md`; sections 11-14 are new.

A full 180-pick Sleeper mock was run live (`1398139615038185472`, seat 5) and
then replayed offline against every fix. **Ten defects, every one past a green
suite.** The full table is `TODO.md` section 11. The four that mattered most:

1. **`my_roster` was empty for the entire draft.** Sleeper mocks set
   `roster_id: None` on every pick while populating `draft_slot` normally, and
   the code matched on `roster_id`. Now matched on `draft_slot`, which deleted
   `_lookup_roster_id` and a network call.
2. **The sort ignored MARG.** VONA is position-relative and roster-BLIND, so it
   stays large for a third QB you will never start. Gated by roster need in the
   sort only; `Row.vona` keeps the true positional number.
3. **`replacement_points` was drawn from the AVAILABLE pool**, so the baseline
   collapsed as the draft drained (QB 347.5 -> 165.9 by pick 164), handing a
   backup quarterback a VBD of +149.0 against a true -32.5. This drove every bad
   late-round number.
4. **`divergence` was noise.** The `adp=999` sentinel (209 of 632 players) all
   tied at the bottom of the ADP ranking and manufactured fake divergence
   (Darren Waller +399 on a player with no ADP), and ranking globally rather
   than within position reported a roster-rule artifact as a valuation
   disagreement. Flag fired on 41.7% of top-20 rows; now 6%.

**Fixing #1 alone changed zero recommendations** — replaying picks 68/77/92 with
a correct roster gives byte-identical ordering, because MARG was never in the
sort. Worth remembering: the obvious-looking bug was not the cause.

#### `adp_source` — a knob, and a judgement flagged as such

Survival calibration is governed by the accuracy of the ADP **mean** and almost
nothing else. FFC gives 74/82/89/90/94 (nearly flat); Sleeper gives 4/17/52/91/100.
That comparison is **circular** — the mock's bots pick off Sleeper's list — but
two things it establishes are not:

- The model FORM is sound: Sleeper ADP calibrates near-perfectly using the
  *fitted curve* stdev the design calls a weak fallback. Mean >> spread.
- It is a wrong mean, not a narrow one. Multiplying FFC's stdev by 1.5/2/3/4/6
  drags the bottom bucket 74% -> 4% but leaves the middle stuck at ~87% at every
  k. **Widening cannot fix a location error.** Restricting to FFC's 267 rated
  players changes nothing, which also kills the "synthesized-stdev tail" theory.

`sleeper-main` is set to `adp_source = "sleeper"` on a MECHANISM, not a
measurement: Sleeper shows its own ADP on the draft board to all twelve
drafters. Known cost — Sleeper's `adp_ppr` folds in TE-premium leagues, so TEs
read ~20 picks early (QB and RB are identical). **One config line reverts it**,
and `scripts/calibrate.py` settles it on a human mock. Yahoo stays on `ffc`.

#### Practices that earned their keep

- **`scripts/mutate.py` caught two vacuous tests this block**, including one
  written the same day (`isdecimal`, where the loop guard swallowed the error)
  and `test_tiers_are_per_position`, which held against a build that tiered the
  whole pool as one group. Add a mutation with every non-trivial change.
- **Replaying a completed draft offline** is the highest-value debugging tool
  this project has. `scripts/calibrate.py` and the `draft_id` override exist to
  make it repeatable.

#### Corrections I had to make, both the same mistake

Twice I drew a confident conclusion from a measurement without checking what
produced it. First: treating the review's constructed pick-61 board as an
observation, then arguing the gaussian tail was "falsified" on top of it.
Second: recommending a switch to Sleeper ADP off a "4x better" result, before
noticing the bots pick off that same list. **Check the provenance of evidence
before building an argument on it** — including my own.

### 2026-08-25 (second session) — Review findings cleared; one rejected on data

**State:** branch `draft-night-fixes` off `main`, 2 commits, **151 tests**.
Everything actionable from the final review is done. **Outstanding work is in
`TODO.md`; the only item with real risk left is Task 13.**

Done: both draft-night blockers (unreachable STALE banner, unguarded input
drain), all four cheap fixes, and the Yahoo `[league.settings]` block. Every new
test was verified failing against pre-fix source with
`git stash push -- ffhelper` before the fix landed.

#### A ninth defect found by running the code, not by testing it

**The opening board ranked four kickers in the top ten, above McCaffrey.** A
150-test suite passed over it completely. VONA compresses toward 0 for everyone
whenever the next pick is a pick or two away — pick 1, and **both sides of every
snake turn**, so this would have hit on draft night. Below the top four the board
sorted on VONA differences of 1e-12; below that, on negative-VONA magnitudes that
are not comparable across positions.

Sort key is now `(-max(round(vona, 1), 0.0), -r.vbd)` — round to the displayed
tenth of a point so the sort agrees with the screen, floor at 0 because every
negative VONA means the same thing and once waiting is free, value decides.
`Row.vona` is untouched; only the sort key is floored. Boards at picks 27 and 51
are byte-identical.

#### The review's survival finding was rejected — do not re-litigate

Finding #4 (`survival_prob` unconditional, SURV 0.00% for fallers) is **closed as
won't-fix**, with the full costing in `TODO.md` section 2. Three reasons:

1. **Its evidence was a constructed board state, not an observation.** "Live
   check, real pool, pick 61 with two WRs slid past their ADP" was built by hand.
   No draft has ever been run with this tool.
2. **The gaussian tail is well calibrated.** FFC's `low` field records the latest
   pick each player was ever taken across ~836 real drafts each. Predicted worst
   fall over that many drafts: 3.0 sigma. Observed median worst case: **2.9
   sigma.** Players ever falling >= 8 sigma: **zero**. The cited Collins case is
   13.8 sigma.
3. **Frequency doesn't justify blast radius.** The fabricated 0.00% does start at
   2 sigma (an 11-pick slide), but expected available players that far past ADP
   run 0.02–0.11 per board state — one row every few drafts.

The best fix, if ever revisited, is a **variance-matched conditional logistic**
(`s = stdev*sqrt(3)/pi`), not the conditioning the review proposed: a gaussian's
hazard rate explodes in the tail, so `S(at)/S(cur)` returns 0.01% for Collins and
divides by zero past 8.3 sigma. It needs real validation data first.

**The lesson worth keeping:** this project's rule is "run it against real data,
never trust a green suite." That rule cuts both ways — it also means **not acting
on a finding whose evidence is synthetic.** Both defects this session were found
by running real data; the one rejection was justified by real data too.

#### Audit of the review process itself, after that miss

Prompted by "what stops other bad findings getting through". Classifying the
final review's six substantive findings by the evidence behind each:

| Evidence type | Findings | Verdict |
| --- | --- | --- |
| Mechanically reproducible (a failing test, or a literal in a file) | 1, 2, 3, 5, 6 | **all five real** |
| Judgement about what a number *means* | 4 (survival) | **the only wrong one** |

The existing discipline — "write a test that fails before the fix" — is a strong
filter, and it filtered correctly. The gap is precisely for claims that cannot be
reduced to a failing test. Those need a different standard: **record whether the
evidence was observed or constructed, and quantify how often it occurs.**

**`scripts/mutate.py` added.** Breaks the engine on purpose, one line at a time,
and checks the suite notices. First run: **4 of 18 mutations survived**, 3 were
real coverage gaps —

- `lineup_value` would start a QB or kicker at FLEX; nothing caught it. Inflates
  MARG, and Phase 5's trade finder inherits the same function.
- `MarkDrafted`'s idempotency guard: `me gibbs` then `gibbs` then `u` leaves the
  player *out* of `drafted` but still in `mine` — back on the board and still
  counted in `my_roster`.
- The `isdecimal` fix from this same session: reverting it kept the suite green,
  because the loop guard added beside it swallows the error. **The test I wrote
  to prove that fix proved nothing.** Now driven directly against
  `_handle_command`.

Now 18 of 19 killed. The survivor is a genuine equivalent mutant (`>` vs `>=` on
float gaps, never exactly equal) and is documented in the script.

**Two doc claims were also false and are corrected:** `scripts/yahoo_auth.py`
was described as "written and untested" — it never existed and never was
committed. And finding 7's `adp_format_for` note was right: Sleeper emits
`adp_std`, not `adp_standard`, so a standard-scoring league silently kept adp 999
for every player and rendered a board that looked healthy. Fixed with an explicit
`SLEEPER_ADP_FIELD` map plus a warning when the field matches nothing.

### 2026-08-24 — Brainstorming and spec

Researched all data sources against live endpoints rather than assumption.
Findings that changed the plan: Sleeper ships free Rotowire projections with raw
stat lines (makes league-custom scoring and VBD feasible at all); Sleeper's
`yahoo_id` is unusable for young players; FFC's ADP `stdev` is irreducible.

Corrected two of my own claims mid-design: custom scoring is marginal after VBD,
not the headline feature; and multi-source consensus was already available via
FFC ADP, which I'd been using only for survival.

Design spec written, self-reviewed, committed — `00b90e7`, updated `4072b90`
(ADP divergence flag, manual mark-drafted mode, Yahoo risk scoping).

**Next:** implementation plan for Phases 0–3, then Phase 0 — which needs ~2
minutes of the user's browser to register the Yahoo app.

### 2026-08-24 — Phase 0–1 execution begins

Plan written: `docs/superpowers/plans/2026-08-24-phase-0-1-draft-engine.md`,
scoped to Phases 0–1 only (Phase 2's detail depends on what Phase 0 discovers).
Writing it surfaced a spec contradiction — "commit fixtures" versus "never commit
projections" — resolved toward synthetic test data plus two inlined real records.

Working on branch `phase-0-1-draft-engine`. Git rule amended: agents commit on the
feature branch because the review loop generates diffs from commit ranges; push,
merge, and `main` remain the user's.

**Phase 0 paid off immediately and negatively: Yahoo API access now requires
approval.** See Known open risks. This is the phase working as designed — found
8 days out rather than on draft night.

Completed: Task 0 (scaffolding, venv — `6dcf719`), Task 2 (config loading —
`ec98daa`). Both passed review clean.

**Next:** Tasks 3–13 (all Sleeper/pure-Python, unaffected by the Yahoo block).
User to submit the Yahoo Fantasy API access application.

### 2026-08-25 — Phase 1 COMPLETE. All 12 code tasks done, 144 tests.

**State:** branch `phase-0-1-draft-engine` @ `65b8664`, 31 commits, ~6000 lines,
144 tests passing in ~0.15s with no network. **Outstanding work is in `TODO.md`.**

**Final whole-branch review is complete:**
`docs/reviews/2026-08-25-phase-1-final-review.md` (full build ledger alongside it
at `docs/reviews/2026-08-25-phase-1-build-ledger.md`)
Verdict: **merge-ready as an engine, NOT draft-ready as shipped.** Two invariants
break — "degrade never fabricate" (the STALE banner is unreachable, so a dead feed
looks healthy) and "the loop never dies" (the manual-input drain is unguarded).
Both fixes are tiny. **Fix them before running Task 13**, since both only surface
on a live feed under real failure, which is what Task 13 exercises.

Tasks 0, 2–12 and 12b are complete and individually reviewed. Remaining: Task 13
(live Sleeper mock draft — needs the user), Task 1 (Yahoo OAuth, blocked on
external approval), and a re-run of the final whole-branch review whose findings
were lost.

**What works today:** projections scored against each league's real rules; VBD;
tiers; optimal-lineup marginal value; survival probability; VONA; ADP divergence
flags; run detection; live Sleeper feed; manual pick entry for any platform; a
terminal board that survives feed failure, malformed picks, and its own bugs.

#### The decision that shaped everything

The board sorts by **VONA — cost of waiting — not by value.** A player with the
highest VBD on screen and a 48% chance of surviving to your next pick is not the
pick; the scarce position is. That is the only thing a live tool can compute that
a printed sheet cannot, and every other feature exists to serve it.

#### Manual entry is a first-class path, not a fallback

Established after user pushback ("just because I might not have the API in time
for my draft doesn't mean we should build an incomplete app"). The stronger form
of that argument: Yahoo requires per-developer approval that can be **denied**,
ESPN has no official API, CBS and NFL.com none worth using, and anyone cloning
this public repo has no Yahoo access at all. **Manual settings and manual pick
entry are the general case; API sync is an optimisation for platforms that permit
it.** They carry the same tests and documentation. Never describe them as a
fallback in code, docs, or output.

#### Eight defects were found by running the code, not by testing it

Full green suites passed over all of them. This is the project's defining lesson.

| Defect | Suite said | Reality |
| --- | --- | --- |
| FFC name matching | all green | **23.2% of rows unmatched** — every kicker, every defense, Marvin Harrison Jr., Travis Etienne Jr. |
| Tier threshold scope | all green | top-8 RBs got **6 distinct tiers** — the column carried no information |
| VONA excluded its own candidate | 59 green | urgency inflated for likely-to-survive players; would have triggered a **3rd-round reach for a TE available in the 5th** |
| Manual-mode pick counter | 139 green | **frozen at pick 1 all draft** — every survival and VONA number wrong on every tick |

The common cause: **test fixtures chosen for arithmetic convenience** — round
numbers, 6σ separations, four-player pools, clean ASCII names — rather than data
resembling what the code actually meets. Seven of the defects traced to the plan's
specification, not to the implementations.

**Practice to keep:** after any task touching data or the engine, run it against
the real Sleeper pool and both leagues' real settings. Never trust a green suite
alone. Ask every reviewer to reason about whether a test would *fail* if the logic
broke, rather than counting passes — that discipline caught six vacuous tests.

#### Architectural invariants (do not break)

1. Player identity joins on **integer IDs, never names**. FFC is the sole
   exception and is confined to a final, non-load-bearing enrichment step that
   reports unmatched and ambiguous names rather than guessing.
2. `ffhelper/value.py` is **pure** — no I/O, no network, no module-level state.
3. Projection rank and ADP rank are **never blended**. Divergence is a flag.
4. **The live loop never dies.** Every per-tick statement guarded,
   `except Exception` never `BaseException`, `KeyboardInterrupt` exits cleanly.
5. **Degrade, never fabricate.** Unknown slot, dead feed, ambiguous name, missing
   settings — each produces a visible labelled degradation, never a guess.
6. Runtime dependencies are exactly `requests` and `yfpy`.

#### Notes for the next session

- `poll_seconds` is floored at 1s — Sleeper IP-blocks above ~1000 req/min, and a
  `0` in config would busy-loop and lose the feed mid-draft.
- `apply_ffc_adp` returns `list[str]` where ambiguous entries carry an
  `"AMBIGUOUS: "` prefix.
- `.cache/` is shared mutable state across six loaders with different TTLs. The
  picks endpoint uses `ttl_seconds=0` deliberately — inheriting the 24h default
  would freeze the pick list for an entire draft while looking healthy.
- The spec doc at `docs/superpowers/specs/` is **stale** — it still says RB30 at
  12 teams where the plan and code correctly say RB36. Reconcile before trusting
  it as the design record.

---

### 2026-08-25 — PAUSED after Task 9. Resume at Task 10.

**State:** branch `phase-0-1-draft-engine` @ `6f26a3d`, **67 tests passing, no open
findings.** Data layer (Tasks 2–6) and pure engine (Tasks 7–9) are COMPLETE.

To resume: say **"start task 10"**. Full detail is in the SDD ledger at
`.superpowers/sdd/2026-08-24-phase-0-1-draft-engine/progress.md` — it records every
task's commits, findings, and the next controller action.

| Task | What | Status |
| --- | --- | --- |
| 0, 2–6 | scaffolding, config, cache, players+crosswalk, scoring, ADP | ✅ |
| 7–9 | VBD/tiers, `lineup_value`, survival/VONA | ✅ |
| 10 | pick feed protocol + `SleeperFeed` | next |
| 11 | board assembly | pending |
| 12 | CLI render/loop/preflight + **manual mark-drafted** | pending |
| 13 | human: live Sleeper mock draft | pending |

**Yahoo applied 2026-08-24, reply says 1–2 weeks. Draft is Sept 1 — it will not
arrive.** Manual mark-drafted in Task 12 is therefore the real Sept 1 interface and
needs partial-name search, disambiguation, undo, and non-blocking input.

**Carry into Task 12:** `apply_ffc_adp` returns `list[str]` in which ambiguous
entries carry an `"AMBIGUOUS: "` prefix; the caller should branch on it when printing.

**Seven defects found so far were in the PLAN, not the implementations** —
RB30/RB36 contradiction, `load_crosswalk` cache duplication, FFC name matching
(23% miss on live data), tier threshold scope, a wrong `marginal_value` test
expectation, VONA excluding its own candidate, and a truthiness stdev fallback.
Three of those passed full green suites and were caught only by running the code
against the real player pool.

**The recurring cause: test fixtures chosen for arithmetic convenience** — round
numbers, 6σ separations, four-player pools — rather than resembling real data.
Keep running live checks against the real Sleeper pool after each data- or
engine-touching task; do not trust a green suite alone.
