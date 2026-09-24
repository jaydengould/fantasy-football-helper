# Decisions, risks, and phases

Referenced from `CLAUDE.md`. Every entry here is settled. **Reversing one
needs a new reason, not a fresh opinion** — most carry the measurement that
closed them and the condition that would reopen them.

## Decisions and why

- **Sleeper is the data backbone for *both* leagues** (projections, player DB,
  ADP) and *one of two* pick feeds. Yahoo replaces only the feed. The engine
  never knows which platform it serves.
- **DynastyProcess `db_playerids.csv` is a Phase 1 dependency, not season mode.**
  Sleeper's own `yahoo_id` is unusable: 0/302 rookies, 13/692 sophomores. Gibbs
  (RB1) has none. DP covers 99.9%.
- **All three leagues use `adp_source = "sleeper"`.** `Bush-League` moved off `ffc`
  2026-08-26 on 540 pooled picks across three Yahoo mocks: FFC's calibration
  spans 24 points and is not monotonic, Sleeper's spans 47 and rises throughout.
  This replaced an unmeasured mechanism argument. `TODO.md` §12a; one config line
  reverts it. **Known and unfixed: both are ~25–35 points too pessimistic in
  level, so SURV is an ordering, not a probability.**
- **FFC stays — but ONLY for bye weeks now, and that is the whole reason.**
  Since all three leagues moved to `adp_source = "sleeper"`, `apply_ffc_adp` runs with
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
- **`--live` and `--error` mean STATE on the board and DIRECTION on the
  homepage wire, and that is a scoped exception, not a repeal.** `board.css`'s
  original rule -- state colours are the only saturated ones, so hue always
  means position and never means state -- was written about the DRAFT BOARD,
  where forty rows each carrying a saturated colour would drown the one row
  that matters. The homepage wire panel is on `/`, the board is on `/draft`,
  and the two never render on one screen. Reusing the tokens beat inventing a
  second green a shade away from the first: two near-identical greens is a
  worse defect than one colour with a stated scope. In the wire the colour is
  REDUNDANT and never the signal -- the group heading says "Added" or
  "Dropped", because a drop count is a positive number of drops and carries no
  sign to separate it from an add count, which would leave a red-green
  colourblind reader with nothing. If the board and the wire ever share a
  screen, this reopens.

- **The "NATIONALLY -- NOT your league" qualifier is dropped from the homepage
  trending panel, and kept in the waivers table.** User ruling 2026-09-04, not
  a measurement. `load_trending`'s docstring had required the words next to
  every displayed count; `app.py` satisfied it twice on one panel -- as a
  subtitle AND appended to all ten rows -- to explain something the magnitude
  already says, since a 12-team league cannot produce a six-figure add count.
  The rule still holds in `waiver_rows`, where the count sits in a table of
  league-specific advice and the misreading "my leaguemates want him" is
  genuinely available. `load_trending`'s docstring carries the split.

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
- **Grading a received offer (2026-09-21, `/trades` "Grade an offer") is by
  hand, and says Accept / Decline / Too close to call, never a letter.**
  Sleeper's public API does not serve pending offers: `transactions/{week}`
  for weeks 1-3 of both Sleeper leagues held only `waiver`/`free_agent` rows,
  `complete` or `failed` — though with zero trades ever made, the absence of a
  pending row is inferred from an unauthenticated endpoint rather than
  observed. The private app API needs the user's token; not pursued. The
  verdict bands are the finder's own floor (`close_call_points ×
  √effective_weeks`), so it inherits TODO item 14's weakness in that 3.0 and
  adds no cutoff of its own; A–F would need cutoffs nobody measured (#8).
  Unlike the finder, MY roster can grow here (a 1-for-2 in my favour), so the
  grade cuts back to `settings.rounds` on both sides. Checked once on the real
  league: a forced cut chose a never-starting WR over a second DEF, because
  `horizon_total` credits streaming the better DEF each week — the model every
  season command already uses, not a grader defect.
  **Asked for and declined: weighting a forced drop "heavily".** The drop's
  projected cost is already inside the gain (the grade is scored AFTER the
  cut); a multiplier on top would be #8's invented weight. What the model
  cannot price is the cut as injury cover — no injury-rate model exists
  (same gap as TODO 6/7) — so the page states the cost in points, and says
  so when it is zero. **"Ask for fewer" was built, then REVERSED the same
  day**: for a RECEIVED offer it can never beat accepting and cutting, because
  the grade already cuts whoever is worth least, incoming players included.
  Measured: 9,408 fixture subsets and 381 real-league subsets, none better
  than the full offer beyond best_drop's 0.5 tie tolerance (max +0.14). As
  built it only ever handed the counterparty points. **Replaced by
  `keep_mine`:** offered only when the forced cut is one of MY players (131
  of 200 random real 1-for-2 / 2-for-3 offers), it names the smaller ask that
  keeps him and what that costs by projection. It exists for what projections
  cannot see (injury cover); the reader prices that, the page does not. When
  the cut is an incoming player the page says accept and cut. Real example:
  Coker for Pickens + 49ers DEF cuts Addison (+36.7); keeping Addison means
  leaving them the DEF, +26.3.
  **A verdict near the band edge moves with Sleeper's projection revisions,
  and that is the band working, not a defect.** Olave + Henderson for
  G. Wilson + B. Hall + A. Jones went Accept -> Too close to call within an
  afternoon: the gain is a difference of two ~1885-point season totals, so
  half a point a week on one player over 16 weeks moves it ~8, across an
  11.2 band. The current +5.99 was matched by an independent recomputation;
  the earlier input was overwritten (TODO 18). One offer, one afternoon: the
  mechanism is arithmetic, the specific cause is unobserved.
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

- **A close call is one per BENCH PLAYER, priced against the cheapest starter he
  can displace** (2026-09-08, reversing a decision a test called "deliberately
  accepted"). The old loop walked SLOTS and paired each with the best eligible
  bench player. Measured on the Yahoo shape: one bench RB produced **three**
  close calls, and the reported cost was wrong — bench WR D (12.0) was priced at
  2.0 against WR B (14.0) when the cheapest starter he can actually displace is
  RB B at 13.0 in FLEX, a true cost of 1.0 against a different player. He can
  occupy one slot, so he is one decision. Wording changed to "X for Y costs N"
  because N is what the lineup LOSES, not a gap between two players in a slot.
- **`injury_status` now gates the lineup; it was display-only** (2026-09-08).
  It reached `_status_note` and the snapshot and touched neither
  `optimal_lineup` nor the sort, so a player on IR carrying a projection was
  STARTED at full value. Demonstrated on a constructed Yahoo roster: an IR
  receiver at 15.7 took a FLEX slot and the week's projected total read 123.7
  against a reachable 121.0. `CANNOT_PLAY` is categorical — Out/IR/PUP/Sus/DNR/
  NA/COV, what the platform itself enforces — so it is not the hand-picked
  discount non-negotiable #8 bars. **Questionable and Doubtful are deliberately
  absent**: they mean MIGHT play, and turning "might" into a number fabricates a
  probability no source supplied. Excluded players get their own screen section
  and are still written to the snapshot with `started` 0.
- **Whether an Out player ever carries a live projection is UNMEASURED.** It
  could not be checked: 2026 weekly projections did not exist yet, and the 2025
  cache is the survivorship-filtered set, which by construction contains almost
  nobody who did not play. The guard is correct either way — a no-op if Sleeper
  zeroes them — but the frequency is unknown until week 1.

- **The snapshot records the startable POOL, not just your roster** (2026-09-08).
  As built it held 14-15 rows per league per week — ~44 across three leagues, of
  which roughly 6 were quarterbacks. That is ~36 QB-weeks after six weeks: far
  too thin to measure a per-position weekly error from, so the number meant to
  calibrate `close_call_points` would have arrived after the season it was meant
  to inform. `build_lineup` **already fetches and scores the full 364-row
  slate** for the lineup and then discarded everything off your roster, so the
  extra rows cost no fetch and no new endpoint. Measured on the real settings:
  120 / 90 / 90 rows a week for `bros-fantasy` / `Bush-League` / `sb-fantasy`,
  300 a week in total against ~44, ~5400 over a season in a gitignored SQLite
  file.
- **The recording depth is `replacement_ranks`, never a chosen number.** How
  many of a position the league starts in a week — so it falls out of the
  league's own settings and moves when they do (QB12/RB36/WR36/TE12 for the
  12-teamer; Bush-League's RB**20** from its single RB slot; sb-fantasy's RB25).
  A hand-picked "top 40" would be the invented number non-negotiable #8 bars,
  sitting in the hardest place to notice it later: the scope of the record
  everything else gets measured against. Below replacement a pair is not a
  decision — nobody chooses between WR80 and WR81.
- **`started` is NULL for a player who is not yours**, rather than 0. No
  start/sit advice was given about him, which is a different fact from "advised
  against", and 0 asserts the second. Same NULL-means-absent rule `proj_pts` and
  `matchup` already follow, so no schema change and no migration: `started IS
  NOT NULL` is your roster, `SUM(started)` is still the lineup. Roster rows are
  written first, so a player who is both keeps his roster row.

- **Rendering the web `/lineup` WRITES the snapshot, same as the CLI**
  (2026-09-09). A page render doing a database write is the kind of thing a
  later reader reverses on principle, so the reasoning is here. `write_snapshot`
  had exactly one caller — `cli._lineup` — so a week used entirely through the
  web app recorded nothing, and the inputs are never re-served: that week is
  gone, permanently. The homepage even said `snapshot NOT recorded for week N`
  while the page that would have fixed it was one click away and did not.
  Render-time is safe here on a fact about the layout, not a hope: the
  `dcc.Interval` lives in `/draft`'s layout alone, so the season routes render
  once per navigation rather than on a tick. The write
  stays in the layout, not in the row builders, so `season.py` and the renderers
  keep their purity, and the two surfaces are held to the same rows by test
  (`test_the_web_lineup_route_records_the_same_snapshot_as_the_cli`) rather
  than by intention.

- **The snapshot is append-only: `taken_at` is in the primary key**
  (2026-09-24). Under `INSERT OR REPLACE` the entry above was wrong: a repeat
  visit AFTER kickoff was not "the last look before kickoff". A Monday
  2026-09-21 render replaced 125 of bros-fantasy's 138 pre-kickoff week-2
  rows with post-game ones. The only guard, `week == /state/nfl week`, passed.
  Most likely Sleeper still reported week 2 on Monday afternoon (it had flipped
  by Monday 22:30 the week before). A stale-cache fallback (`stale_ok=True`)
  is not ruled out, and append-only covers both. Unrecoverable. The 2026-09-03 web spec named
  this failure and this fix. A write-time cutoff was rejected because kickoff
  is per game: a whole-week cutoff blocks the Sunday-morning run that carries
  late inactives, and a per-game one needs a schedule fetch whose failure
  loses the week. With appends, the reader picks each player's last look
  before HIS kickoff, and one run is one `taken_at`, so `SUM(started)` over a
  `taken_at` is that run's lineup. Evidence: one week, one league. The
  mechanism is in the code; the frequency is not measured.

- **The web app writes the Yahoo roster file as `<sleeper_id>  <name>` lines**
  (2026-09-23, spec `2026-09-23-yahoo-roster-editor-design.md`). A name the
  app writes does not always read back: over the full 3,232-player pool, 37 full
  names resolve to more than one player through `find_players`, 5 of them on an
  NFL team (Ian Thomas is inside Brian Thomas). A name-only writer would make
  those un-addable, and a silently re-resolved name breaks non-negotiable #1. A
  line whose first word is a pool key is read by ID; hand-typed names still
  work. Rejected: moving the Yahoo roster into SQLite. It is the cleaner model,
  but it moves hand-editing and the CLI read path too, and nothing needs that.
  Capacity counts file ENTRIES, not resolved players, because an ambiguous line
  is still a player the user rosters. The limit is `rounds`, exact only because
  Bush-League has no IR (read off Yahoo's settings by the user, 2026-09-23).

- **A lineup signal is gated on close calls, not on MAE — Test C** (2026-09-09).
  `backtest_weekly.py` rejected the matchup adjustment on MAE over ~6000
  projected player-weeks, but a lineup decision is a RANKING between two players
  eligible for one slot, and a signal can be net-negative over a whole pool and
  still positive where two players sit within a few points. Test C scores the
  same data that way: startable same-position pairs (`season.startable_pool`, so
  the depth comes from `replacement_ranks` and no hand-picked "top 40" enters),
  projections within N, "did the higher one outscore the other". N is SWEPT
  (1/2/3/5) rather than set to `close_call_points`, which is sourced to the same
  survivorship-filtered table the test exists to work around. The arm runs at
  the LOUDEST shrinkage in the sweep — the most picks it can change — and the
  table prints flips separately, because an arm that never changes a pick scores
  identically to the baseline and has proved nothing.

  **It did not rescue the matchup adjustment.** Hit rate baseline -> adjusted at
  N=3: 2025 QB 53.9->56.2, RB 56.2->52.5, WR 55.4->51.9, TE 56.8->48.1; 2024
  QB 50.3->52.5, RB 56.8->54.6, WR 54.4->50.7, TE 57.9->59.4. RB and WR lose in
  both seasons, TE swings -8.7 then +1.5 (Test A's sign flip, seen in a second
  instrument). QB gains in both, +2.3 and +2.2 — **a hypothesis on two seasons
  of one league's scoring at the position with the fewest pairs, not a finding**,
  and it may not be settled by a third pass over the same filtered set. The
  snapshot is the instrument for that.

  **One premise it sharpened.** It was built on "the overwhelming majority of
  player-weeks are not decisions", with the N-point gap named as the filter that
  separates them. Right about the population, wrong about the filter: the DEPTH
  cut removes 72% of Test B's rows (342 projected player-weeks a week to 96
  startable) and the gap then keeps 40-72% at N=3 and 15-33% at N=1. Among
  startable players a close call is the common case. The practical consequence
  is that N=5 (62-93% kept) is nearly "all startable pairs" and the narrow rows
  are the ones carrying information — Test C earns its place by scoring a
  decision rather than a distance, not by decisions being rare.

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
| 4a | Season mode — weekly start/sit (`lineup`) | week 1 (Sept 9) | **COMPLETE AND MERGE-CHECKED 2026-09-02**, branch `phase-4a-start-sit`, 377 tests / 153 mutations. Runs against both leagues. Merged to `main` (PR #6) |
| 4b | Matchup adjustment + weekly backtest + snapshot table + nflverse injuries | in-season | **COMPLETE 2026-09-02** (branch `phase-4b-snapshot`). Snapshot table shipped; `backtest_weekly.py` shipped and it **closed the matchup ADJUSTMENT** — measured on 2024 and 2025, it loses — so what ships is a descriptive opponent RANK that nothing consumes (see Decisions). nflverse practice report shipped and joins 14/15; `injuries_2026.csv` is a 404 until ~Sept 10, so it prints its degraded line today |
| 4c | Waivers — free-agent pool, ROS horizon, trending as the price signal | in-season | **COMPLETE AND MERGE-CHECKED 2026-09-02**, branch `phase-4c-waivers`, 454 tests / 184 mutations. `waivers` prints an EMPTY board in week 1, which is the correct output, and the pipeline was proved separately by turning the floor off. Sleeper-only, labelled. **No FAAB bid** — see the correction in Decisions |
| 5 | Trade finder (own spec) | in-season | **COMPLETE 2026-09-02**, branch `phase-5-trade-finder`, 500 tests / 204 mutations (1 documented equivalent survivor). `trades` runs against both leagues (refuses on Yahoo, exit 1); real-league board is ONE row and reproduces the pre-build measurement. Merged to `main` (PR #9) |
| 6 | Season mode on the web — `/`, `/lineup`, `/waivers`, `/trades` | in-season | **COMPLETE 2026-09-03**, branch `phase-6-web-season-mode`, 574 tests / 212 mutations. Merged to `main` (PR #10, `304d7be`). **Its appearance was not part of it and shipped 2026-09-04**: the four season routes had their own bare markup while `/draft` had `board.css`, which is why one evening's use produced nine complaints. One shared `shell()`, the add/drop wire, headshots, position colour — 601 tests / 232 mutations |

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

