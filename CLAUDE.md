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
- **A mutation run must start from a GREEN suite, and `mutate.py` must be the
  only thing running.** Against a red suite every mutation "kills" trivially and
  the run means nothing — that happened again on 2026-09-02, when a test helper
  appended to `tests/test_season.py` shadowed an existing one and two survivors
  were reported as killed. The same day the tool was found leaving MUTATED
  BYTECODE behind: Python validates a `.pyc` on the source's mtime-in-seconds
  plus its size, so a same-length mutation written and restored inside one
  second leaves cached bytecode that looks valid and is not. Fixed at the root
  (`mutate.py` unlinks the `.pyc` on every write); the symptom was a clean `git
  status`, a tree identical to HEAD, and a failing test that `touch` repaired.
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
  dress up a guess. ~~Rank by a transaction-history prior instead.~~
  **CORRECTED 2026-09-02: THE PRIOR HAS NO DATA AND NOTHING REPLACES IT.**
  Measured against the live league: **3 transactions all season, all free-agent
  moves, ZERO trades ever, and `previous_league_id` is None** — no prior season
  to draw on. So "does this manager trade at all, how often, do they take
  2-for-1s" cannot be answered, and fitting a manager model to an empty sample
  would be the FAAB bid by a new route. The board ranks by **my own gain** and
  states on screen that it cannot say whether anyone will accept. The refusal to
  print a probability now rests on a measurement rather than a judgement.
  **Reopen in November if the league has by then actually traded**;
  `load_league_transactions` (cut in 4c) is what it would need.
  **Shipped 2026-09-02 in Phase 5's `trades` command**, which prints this on
  screen verbatim rather than a number. The real-league board is one row
  (league-wide, one manager holds a pairing surplus) and has never been
  scored against an actual accepted trade — it is one night's measurement,
  not a validated system.
- **The trade finder has no prefilter and enumerates every shape (1-for-1,
  2-for-1, 2-for-2) in full.** A prefilter that looks sound — drop incoming
  players who can't crack my lineup — is only sound for 1-for-1: measured
  before being added, it silently dropped 22 of 49 real trades, because
  giving away two players can open a slot the pruned player then fills. The
  industry's dominant approach (a single consensus trade-value number per
  player, FantasyPros/dynasty charts) is barred outright by non-negotiable
  #2 — a consensus ranking is PRICE, and folding it into the value axis is
  the blend that rule forbids, the same reason §18 closed ECR.
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
| 4c | Waivers — free-agent pool, ROS horizon, trending as the price signal | in-season | **COMPLETE AND MERGE-CHECKED 2026-09-02**, branch `phase-4c-waivers`, 454 tests / 184 mutations. `waivers` prints an EMPTY board in week 1, which is the correct output, and the pipeline was proved separately by turning the floor off. Sleeper-only, labelled. **No FAAB bid** — see the correction in Decisions |
| 5 | Trade finder (own spec) | in-season | **COMPLETE 2026-09-02**, branch `phase-5-trade-finder`, 500 tests / 204 mutations (1 documented equivalent survivor). `trades` runs against both leagues (refuses on Yahoo, exit 1); real-league board is ONE row and reproduces the pre-build measurement. Awaiting the user's merge |

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
- **SPENT with the drafts — do not re-raise the overlapping-drafts risk or the
  two-boards-at-once check.** What carries into season mode is narrower:
  attribution derived from POSITION is fragile, so season mode reads rosters from
  the API wherever it can rather than re-deriving who owns whom.
- **NEW, and the season-mode equivalent of the single-source risk: three of the
  four data sources are undocumented.** Sleeper's projections, `lines/available`
  (props) and the trending endpoints are all unofficial and can change or vanish
  without notice — the same class as the projections endpoint, and the CDN
  behaviour in §20 is the precedent for how quietly it can happen. Every one of
  them must degrade to "column absent", never to a fabricated number, and none
  may be committed to this public repo.

## Session log

### 2026-09-03 — Phase 5 closed out. The final review's fix wave, and a handle that was in five files, not one.

**State:** branch `phase-5-trade-finder`, **500 tests** (from 494), **204
mutations** — 202 from the last full run plus the 2 added in `f15cd2e` and
hand-verified to die there; **no full mutation run this session.** Tree clean.

`f15cd2e` closed the whole-branch review: `_trades`' ranking layer had no test
driving it to a NON-EMPTY board (so the best-per-opponent max/min swap and the
pin-direction sort swap both survived), the pinned search was unbounded and
`--limit` never reached `_trades`, an opponent roster's unresolvable ids
silently understated their baseline, and `tunables.playoff_weight` /
`close_call_points` were undocumented in both `config.toml` and `README.md`.

**The leaguemate's handle was fixed in `README.md` and left in four other
tracked files** — `CLAUDE.md`, `tests/test_cli.py`, and the phase 5 spec and
plan. Same shape as the `LAST_REGULAR_WEEK` miss one session earlier: a real
fix applied to the file the finding named rather than to every place the
defect lived. The privacy argument never depended on which file it sat in.
`README.md`'s sample was re-captured genuinely (names endpoint forced to fail,
the tool's own degradation path); the rest are hand-redacted to `leaguemate`,
and **git history still carries it across 5 commits** — the user's call, and
they have declined it.

**Phase 5 is finished. Merging is the user's.**

### 2026-09-02 (seventh block) — PHASE 5 SHIPPED. `trades` runs against the real league; eight of its defects were in the PLAN.

**State:** branch `phase-5-trade-finder`, **494 tests** (from 454), **202
mutations, 1 needing a look** (the documented `value.py` equivalent mutant,
sole survivor since August), tree byte-identical before and after the run.
Key commits: `2dbeca6` (1-for-1), `687f016` (2-for-1), `844e9d9` (2-for-2 +
pin), `68bf8dd` (the `trades` command), `d64b536` (fix round closing two
surviving cli.py mutations), `f024705` (Task 8a — the calendar fix wired into
`waivers` too), `e89cf31` (closed the one mutation the run turned up).

`.venv/bin/python -m ffhelper.cli trades --league sleeper-main` searches every
opponent for the best 1-for-1 / 2-for-1 / 2-for-2 that clears the floor on
BOTH sides, and prints the best offer per opponent. Real run tonight: **2:39
wall clock, "17 weeks scored", one row league-wide** — one opponent, a 2-for-2
(give Shakir+Watson, get Pickens+Chargers DEF), me +29.1 / them +12.8. That
**reproduces the spec's own pre-build measurement, unchanged**: across 2475
1-for-1 pairs zero clear the 12.7-point floor, 2-for-2 is where surplus lives
(49 clear both floors across three opponents in the pre-build probe), and only
one manager in twelve holds a surplus that pairs with ours. `--player
"smith-njigba"` runs in **12s** (13x faster — pinning narrows the search) and
prints an empty board as a sentence, correctly, since none clears the floor for
him. `--league yahoo-main` refuses, exit 1: the search needs every roster and
Yahoo serves none. **This is one real league on one night, not a backtest** —
the board has never been scored against an actual accepted trade.

**The leaguemate's handle is redacted everywhere, 2026-09-03.** The repo is
public. `README.md`'s sample was re-captured with the names endpoint forced to
fail (the tool's own degradation path, so the output is still genuine); this
file, `tests/test_cli.py` and the phase 5 spec/plan are hand-redacted to
`leaguemate`, which is the one case where editing a spec/plan after the fact is
right. **Git history still carries it** — rewriting that is the user's call.

The board states on screen that it **cannot say whether anyone will accept**
("this league has never made a trade, so there is no history to rank managers
by") — the shipped confirmation of the dead acceptance prior recorded below.

#### `LAST_REGULAR_WEEK = 18` was wrong, and the fix reached only half the code until a controller catch

`playoff_week_start: 15` + `playoff_teams: 6` is a three-round bracket, so the
season ends **week 17**, not 18 — the **third** time a league rule was
inferred from an API default instead of read off the payload (after the Yahoo
one-RB-slot error and the FAAB/rolling-priority error). Tasks 1-3 built
`last_scoring_week` and weighted `week_weights` and wired them into `trades`
— but not into `waivers`, which kept reading `LAST_REGULAR_WEEK` (=18) with
flat weights, so the very bug the phase exists to fix stayed live in the
command the user runs every week. **No task brief covered changing
`_waivers`; the plan built the fix and applied it only to the new command.**
Caught by the controller reading the plan against the diff, not by any test
or reviewer, and closed as Task 8a before Task 9 ran: `waivers` and `trades`
now both call `last_scoring_week`/`week_weights` identically, confirmed by
grepping `LAST_REGULAR_WEEK` out of `cli.py` entirely. Tonight's cache mtimes
confirm it live — `wk17` fetches from tonight, `wk18` untouched.

#### Week weights point the OPPOSITE way to the literature, deliberately

A point scored in a week you do not play is worth nothing, so a week's weight
is the probability you play it: 1.0 through week 14, then 4/12, 4/12, 2/12 on
a 6-of-12 bracket. **That weights the playoffs DOWN**, where the published
playoff-biasing work weights them up. Theirs is conditional value, reachable
only through a matchup win-probability model nobody has validated — the
hand-picked factor §15 forbids. `tunables.playoff_weight` takes the other
reading; the default is the one with a derivation behind it.

#### Eight of Phase 5's defects were in the PLAN, not the implementations

Three caught by the preflight scan before dispatch (a vacuous
`assert ... is not None` mandated for the significance floor; three `...`
test-body placeholders; `trade_deadline` added to `LeagueSettings` in two
tasks). Five more surfaced during execution:

1. **A fixture mathematically incapable of passing its own test.** Task 5's
   brief gave both sides exactly 7 players against a 7-slot lineup, so every
   player always starts and a 1-for-1 trade's `gain_me` and `gain_them` are
   identically `-(each other)` — the brief's own first assertion ("a mutually
   beneficial one-for-one is found") cannot pass against the brief's own
   fixture. Found by the implementer, fixed with a bench slot per side and
   verified against all 64 1-for-1 combinations.
2. **The plan's own sample output couldn't be produced by its own function
   signature** — Task 8's target header names a floor value `render_trades`
   was never given one to print. Resolved by matching the shipped
   `render_waivers` precedent, which doesn't print its floor either.
3. **Two mutations the plan mandated, its own tests could not kill** —
   an ambiguous `--player` pin silently taking the first match, and the
   horizon running to the NFL's last week instead of the league's — because
   no test drove `_trades` with `player=` at all, and the one test reaching
   the fetch loop set the floor to 1e6 so the board was empty regardless of
   which week count was used. One fix round, both closed.
4. **`horizon_total`'s mutation target matched TWO places** in `season.py` —
   found by an implementer, not the scan. Left alone, `mutate.py` takes the
   first and reports "killed" for a function the label doesn't name. The
   AMBIGUOUS guard caught it.
5. **The plan built a fix and applied it to only one of the two commands
   that had the bug** — the `LAST_REGULAR_WEEK` case above.

**Same recurring shape as 4a: a plan detailed enough to transcribe is detailed
enough to transcribe a defect.** None of these were implementer carelessness;
every one was built exactly as briefed.

#### `roster_upgrade`'s `best_drop` seam, parked mid-phase and closed before Task 5

Task 4 extracted `best_drop` so `waivers` and the trade search share one rule
for which player a team cuts. The refactor's equivalence held (28 test
insertions, 0 deletions), but the brief's own prescribed call let `best_drop`
return the just-added CANDIDATE as the drop — unreachable in shipped
`waivers` (0.0 gain can't clear a floor) but reachable the instant the trade
search calls it with no floor in front. Fixed with an opt-in `keep` parameter
that only `roster_upgrade` passes, leaving `best_drop`'s general default
untouched — which the trade search needed, since a just-received player can
legitimately be the right cut in a real 2-for-1 (confirmed live in Task 6's
fixture).

#### No prefilter, ever — measured, not assumed

Pruning incoming players who can't crack my lineup is sound for 1-for-1 and
unsound here: giving away two players opens a slot the pruned player then
fills. Measured before it could be added: **it silently dropped 22 of 49 real
trades.** The search stays a full enumeration — 15v15 rosters run ~141,075
shapes per league, order of minutes, which is what tonight's 2:39 measured.

#### Industry research, and why it changed nothing

**The dominant commercial approach is a single trade-value number per player**
(FantasyPros from expert consensus, dynasty charts from analysts).
**Non-negotiable #2 bars it**: a consensus ranking is PRICE, and folding it into
the value axis is the blend the rule forbids — the reason §18 closed ECR.

The better tier personalises by "roster depth, slot count, position importance",
which is `lineup_value`, except they apply a positional adjustment where this
computes the actual lineup effect. **ESPN's published system uses an explicit
diversity constraint** — independent confirmation of the near-duplicate problem
measured here. **An arXiv genetic algorithm is rejected**: 330s enumerates one
team exhaustively, and a GA returns different answers on different runs, which
`roster_upgrade`'s tie-break already ruled out.

**Start/sit research surfaced one genuinely different idea, deferred with a
gate:** optimise win probability rather than points (high floor when favoured,
high ceiling when an underdog). It needs a per-player variance this project has
never estimated — the same missing ingredient as the deferred playoff-leverage
weighting, so both wait on one prerequisite.



### 2026-09-02 (sixth block) — PHASE 4c SHIPPED, and its correct output is nothing

**State:** branch `phase-4c-waivers`, 8 commits, **454 tests** (from 419),
**184 mutations, 1 needing a look** (the documented `value.py` equivalent
mutant), tree byte-identical before and after. New: `tests/test_mutate.py`.

`.venv/bin/python -m ffhelper.cli waivers --league sleeper-main` ranks the
free-agent pool by add-and-drop marginal value over two horizons, and on the
real roster in week 1 it prints:

```
WAIVERS -- sleeper-main (jaydenpg) -- week 1
  waiver priority 8 of 12 -- a successful claim sends you to 12th

  nothing on the wire beats what you already have.
```

**That empty board is the acceptance criterion, not a failure** — rows on a
healthy 15-man roster in week 1 would have meant the floor was wrong or the pool
polluted. 4.8s warm, ~46s cold (108 files). Yahoo refuses, labelled, exit 1,
because the pool is every player minus the union of EVERY roster and Yahoo
serves none.

**An empty board and a broken pipeline look identical on screen**, so the
pipeline was made to prove itself: with `close_call_points=0.0` in a scratch
script the board fills with tight ends, best +8.3 over 18 weeks — the number the
spec measured before any code existed. The floor (3.0 × √18 = 12.7) silences
all of them, which is the design working.

#### `mutate.py` was leaving mutated bytecode behind, and the tree looked clean

The full mutation run ended with `184 mutations, 1 needing a look`, a `git
status` diff of nothing, a tree identical to HEAD — **and one failing test**.
`inspect.getsource` showed the guard the test wanted, present and correct.
`touch ffhelper/cli.py` fixed it with no source change at all.

Python validates a `.pyc` on the source's mtime-in-SECONDS plus its size. A
mutation the same length as the original, written and restored inside one
second, leaves cached bytecode that looks valid and is not. **The direction that
bit here was harmless (a false failure); the dangerous one is the reverse — a
restored file running mutant bytecode reports `killed` for a check that never
ran.** Fixed at the root: every write unlinks the `.pyc`, with a red-checked
test.

**This is the third time this tool has reported success while checking something
else** — the duplicate dict key that silently dropped 26 mutations
(2026-08-27), the ambiguous target string that mutated a different function
(2026-09-02), and now this. The pattern is worth naming: each fix was a GUARD in
the tool, not a correction of the instance, which is why none of them recurred.

#### Two mutations "killed" against a RED suite, and the cause was my own test

Tasks 4 and 5 reported killed. Re-run later they SURVIVED. Between the two runs
the suite went green: a `_slots()` helper I appended to `tests/test_season.py`
had **shadowed an existing one of the same name**, breaking the snapshot test —
and a mutation run against a red suite kills everything trivially. The recorded
rule ("check the suite is green before believing a mutation run") was written in
August and would have caught it; I did not apply it until the numbers disagreed.

Both survivors were vacuous tests, fixed in the direction the rule says:
- **`weeks_started`**: the lineup check ALONE cannot see a bye. A candidate who
  is the only player at his position fills the slot on the 0.0 sort value, so
  the absent-row guard needed a fixture where that actually happens.
- **The √weeks floor**: the old fixture only proved the bar was not too HIGH.
  It now also proves a 4.5-point gain over nine weeks is silenced.

#### The plan's own instruction caught the plan's own error

Task 4 said to run every fixture number by hand before implementing. Its
expected drop was Gainwell; **the tie also contains the DEFENSE being replaced**,
whose own points are lower, so the rule names the Broncos — which is also the
move a human would make (you stream a defense by dropping the old one). Fixture
corrected, assertion not loosened.

Two other plan calls taken at the better end: `_resolve_my_roster` returns the
`roster_id` it already resolved, so `_waivers` re-derives nothing (the plan
flagged its own re-derivation as a smell); and the pool mutation SURVIVED the
plan's fixture, because the other team's roster in it was empty — the fixture
now puts the league's best quarterback on another team, where offering him is
the most attractive row on the board and the one thing that cannot be done.

#### What is deliberately absent

`load_league_transactions` was never built — with the FAAB bid gone it has no
consumer. There is no snapshot of waiver advice and no Dash page; both are out
of scope in the plan and remain so.

### 2026-09-02 (fifth block) — 4c unblocked and specced; a documented league rule turned out to be wrong

**State:** branch `phase-4c-waivers` off `main` (4b merged as PR #7), two
commits, **no code touched**, 419 tests still green. Spec and 8-task plan
written; **implementation deferred to the next session by the user.**

**Start next session at Task 1** of
`docs/superpowers/plans/2026-09-02-phase-4c-waivers.md` — the
`_resolve_week` / `_resolve_my_roster` extraction from `_lineup`.

#### The league is NOT FAAB, and the claim came from an API default

`CLAUDE.md`, `TODO.md` and both specs said "Waivers are FAAB
(`waiver_budget: 100`)". **It is rolling waiver priority**, confirmed by the
user against Sleeper's own UI. The live settings say `waiver_type: 0`, and all
twelve rosters carry a distinct `waiver_position` (1-12) with
`waiver_budget_used: 0`.

**The entire provenance of the wrong claim was `waiver_budget: 100` in the
settings payload — a field Sleeper returns by default whether or not bidding is
on.** Identical shape to the Yahoo one-RB-slot error: a league rule inferred
from an API payload instead of read off the platform's own screen, then written
down as fact and inherited by three documents. **So 4c's stated deliverable, a
derived FAAB bid, does not exist.** The notify-bot cut is unaffected — it rests
on batch processing (`waiver_clear_days: 2`), which is still true.

#### The measurement says the feature should usually print nothing

Probed against the real roster and pool before designing anything:

| best available upgrade, week 1 | +1.2 pts |
| best available ROS upgrade | **+8.3 over 18 weeks = 0.46/wk** |
| base lineup | 2399.0 pts |
| measured TE weekly MAE | **3.23** |

The best thing on the wire is inside the noise by a factor of seven. What the
wire IS worth is positional depth: **losing Ferguson (the only TE) is +163.9
ROS; losing Josh Allen is only +37.7**, because Murray backs him up.

So the command carries a significance floor and **an empty board is the
shipped, correct week-1 output.** The user's instruction, recorded because it
generalises: *"Never force things just to have something when it is wrong."*

#### My own floor rule was wrong, and spec self-review caught it

First version was a flat `close_call_points` (3.0) per week on both horizons.
**That is calibrated to a SINGLE week's error**; independent weekly errors
partially cancel, so the standard error of a season total grows as sqrt(n), not
n — a flat bar is ~4x too strict and would have silenced real upgrades. It also
contradicted the mockup the user had approved. Corrected to
`close_call_points * sqrt(weeks)`, and since sqrt(1) = 1 the two sections
collapse to **one code path with no second threshold**.

#### Two things cut during planning

`load_league_transactions` has **no consumer** once the FAAB bid is gone, so it
was cut rather than built unused. And a bye is an **ABSENT ROW, not a zero**
(verified: Gibbs has no week-6 row, Allen no week-7, Nacua no week-11) — so is
an injured or unprojected player, which means every ROS total must print the
count of weeks that actually contributed, or the 4a distinction between a
measured 0.0 and no number at all is lost across fourteen weeks.


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

---

**Older entries (2026-08-24 to 2026-08-27, Phases 0-3) live in
`docs/session-log-archive.md`.** Moved there 2026-09-02 to keep this file under
the context limit. Their durable lessons are already in the sections above.
