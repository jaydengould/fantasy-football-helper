# Phase 4 — season mode: start/sit and waivers

**Written 2026-09-01, hours after both drafts.** Scope is Phase 4 only. The
trade finder is Phase 5 and gets its own spec; it inherits every primitive
defined here and adds only the two-sided search.

**Authority:** `CLAUDE.md` holds the standing decisions and non-negotiables.
Where this spec and that file disagree, that file wins and this one is wrong.

## The question season mode answers

Draft mode answered *what does waiting cost me*. Season mode answers three
narrower questions, all of which are the same arithmetic under different
horizons:

| feature | horizon | question |
| --- | --- | --- |
| start/sit | this week | which nine of my players score the most? |
| waivers | rest of season | which free agent most improves my starting lineup? |
| trades (Phase 5) | rest of season | which two-sided swap improves it? |

`value.lineup_value()` already answers all three. It was built standalone in
Phase 1 for exactly this, and `value.optimal_lineup()` was folded out of the web
board on 2026-09-01 so the answer can name **which player fills which slot** —
which is the whole output of a start/sit command.

**There is no new ranking engine in Phase 4.** If this spec ever seems to need
one, the design is wrong.

## Non-goals

- **No auto-anything.** No auto-set lineup, no auto-claim. Non-negotiable #6
  ("no auto-pick") generalises: the tool advises and a human acts.
- **No waiver notify-bot.** Cut in the original design and still cut: the league
  is FAAB with scheduled batch processing, so claims resolve simultaneously and a
  same-day alert gives no timing edge.
- **No acceptance probability on trades** (Phase 5, recorded here so it is not
  re-litigated).
- **No web page in Phase 4.** CLI first, on the user's call. The Dash page reads
  the same pure functions afterwards, the same way `board.py` reads the engine.
- **No blending of sources into one number.** See "Three sources".

## Data sources, and what was verified against the live API

Everything below was probed against the live API on 2026-09-01 rather than taken
from documentation. Provenance matters here for the same reason it did in
`backtest.py`: an endpoint that quietly serves revised numbers will flatter any
measurement built on it.

### 1. Weekly projections — the base

`https://api.sleeper.com/projections/nfl/{season}/{week}?season_type=regular&position[]={pos}`

The same undocumented Rotowire endpoint `data.py` already uses, plus a week.
Full stat lines, so `score_stats` applies unchanged and each league's own
scoring is honoured with no new code.

**Verified revised in-season, which is the property the whole feature rests on.**
Checked on 2025 week by week: Ekeler reads 12.1, 10.4, then 0.0 for every week
after his week-3 injury; byes appear as isolated zeroes (Gibbs week 8, Barkley
week 9); Barkley's line decays with his real usage. A frozen preseason curve
would show none of that.

**Consequence: rest-of-season value is the SUM OF REMAINING WEEKS, never the
season endpoint.** The season projection is frozen preseason — that is exactly
what `backtest.py` proves about it — so it is worthless once anyone is hurt.

### 2. League state — free, no auth

| endpoint | supplies |
| --- | --- |
| `league/<id>/rosters` | every team's roster, keyed by `player_id` |
| `league/<id>/users` | display names, to label opponents |
| `league/<id>/matchups/<wk>` | starters, bench, per-player points, pairings |
| `league/<id>/transactions/<wk>` | adds, drops, waivers, FAAB spend |
| `state/nfl` | current week and season |

All public. **The trade finder's assumed blocker — reading other teams' rosters
— does not exist on Sleeper.** The free-agent pool is the full player pool minus
the union of every roster; it is not a separate endpoint.

### 3. Weekly ACTUALS — matchup and usage, from an endpoint we already use

`https://api.sleeper.com/stats/nfl/{season}/{week}?season_type=regular&position[]={pos}`

The mirror of the projections endpoint, and it carries more than points:

| field | gives |
| --- | --- |
| `opponent` | who each player faced that week — the join for matchup strength |
| `off_snp` / `tm_off_snp` | snap share |
| `rec_tgt` | targets (team totals by summing) |
| `rush_att`, `rush_rz_att` | volume and red-zone carries |
| full stat line | actual points under THIS league's scoring, via `score_stats` |

**This is why Phase 4 needs no new dependency.** `nflreadpy` was in the plan for
exactly these fields; Sleeper serves them already, ID-keyed, from a loader that
exists. It remains a candidate only for what Sleeper genuinely lacks — routes
run, air yards, the official participation report — and is out of Phase 4.

### 4. Player status — already fetched, currently discarded

Sleeper's player DB carries 52 fields and `build_players` keeps about six.
Unused and wanted: `injury_status`, `injury_body_part`, `injury_notes`,
`injury_start_date`, `practice_participation`, `practice_description`,
`news_updated`, `depth_chart_order`, `depth_chart_position`, `status`.

This is the structured form of the news the user asked about, and it costs one
dataclass change. `depth_chart_order` is a direct waiver signal: the backup who
becomes the starter on Wednesday is the claim you want on Tuesday.

### 5. Trending adds/drops — a PRICE signal

`players/nfl/trending/add|drop?lookback_hours=24&limit=N`, ID-keyed, counts in
the hundreds of thousands. This is crowd consensus on the wire.

**It belongs in the price column and never in the value column.** Its job is the
FAAB bid (how contested is this claim) and a divergence flag (the wire is
chasing someone our numbers do not like). Feeding it into value would be
non-negotiable #2 by a new route.

### 6. `nflreadpy` — NOT in Phase 4

It was in the plan for usage data (snap share, target share, red zone) and the
official injury report. **Sleeper's own weekly actuals serve all of that**
(source 3), ID-keyed, from a loader that already exists — so the dependency buys
nothing Phase 4 needs.

**Phase 4 therefore adds NO new dependency.** `requests`, `yfpy`, `dash` stands.

Reopen it only for what Sleeper genuinely lacks: routes run, air yards, and the
official participation report with its practice designations. If it is ever
added it must load lazily and season mode must run without it.

### Rejected, with reasons that are already settled

- **FantasyPros ECR / expert rankings.** §18 closed it: ToU bars shipping a
  fetcher, it sits behind a login, and it is RANKS where VBD needs POINTS.
- **Scraped editorial news.** Converting "game-time decision" into a number
  fabricates a value the source never stated. The structured injury fields are
  the same information without the invention.
- **Game betting lines (spreads, totals).** Checked 2026-09-01: the free
  endpoints serve current odds and drop them after the game, so there is no free
  history — which fails §13's standard exactly as ECR did. **Reopen only with a
  historical source**, at which point an implied team total is a legitimate
  matchup input.
- **Player props** — measured and cut from Phase 4; see the section below for the
  numbers and the reopen condition.

## Matchup — the gap this spec was written without

**Measured 2026-09-01, and it changed the design.** 2026 preseason is a natural
experiment: no injuries or usage news exist yet, so any week-to-week variation in
a player's projection can only come from the schedule.

```
top-40 RB/WR, 2026 preseason:  median week-to-week variation 1.4% of the player's own mean (max 3.4%)
same measure, 2025 in-season:  9.1% (max 48.9%)
```

**The projections contain essentially no matchup.** A top RB reads within a point
of the same number against the best and the worst run defense in the league. The
in-season figure is larger but conflates matchup with usage and injury, so it is
not evidence the schedule is priced in.

So start/sit needs an explicit opponent adjustment, built from measured outcomes:

1. For each defense and position, compute **points allowed under THIS league's
   scoring** from the weekly actuals — not a generic "fantasy points against",
   which is a different rulebook.
2. **Shrink toward the league mean.** In week 3 a defense has faced two or three
   opponents; the raw number is mostly noise and the early season is exactly when
   people over-react to it. The shrinkage weight is a documented tunable, not a
   taste, and it starts at full shrinkage in week 1 — where there is no data at
   all and the honest adjustment is zero.
3. **Display it as its own column, never fold it silently into the projection.**
   The user must be able to see that a start/sit call turned on the matchup.
4. **It must prove itself before it is allowed to reorder anything.**
   `backtest_weekly.py` scores adjusted against unadjusted projections on 2025.
   Until it wins there, the column is shown and the ranking ignores it.

Point 4 is the whole discipline. §15's standing rule is **do not discount by a
hand-picked factor** — it invents a number the data does not supply. An
adjustment derived from measured points-allowed and validated out of sample is
the opposite of that, but only if step 4 actually happens.

## Sources, deliberately not blended

| source | unit | role |
| --- | --- | --- |
| Rotowire weekly projections | points | the base |
| Matchup adjustment | points delta | its own column, gated on validation |
| Usage (snap share, targets, red-zone) | shares | context: why a projection may be stale |
| Trending adds/drops | counts | PRICE — the FAAB bid, never the value |

Non-negotiable #2 forbids blending value with price, and the trending counts are
price. Usage never becomes points at all; it explains a number rather than
changing it.

## Market props — CUT from Phase 4, with a reopen condition

Props were specced as a second value source and then measured, which is the
project's own rule working. Compared like-for-like, Rotowire's projected stat
against Sleeper's line for the same stat:

| market | n | r | Rotowire | line | median gap |
| --- | --- | --- | --- | --- | --- |
| receiving yards | 125 | +0.964 | 41.3 | 36.0 | 15.5% |
| receptions | 117 | +0.929 | 3.5 | 3.4 | 11.9% |
| rushing yards | 58 | +0.967 | 42.8 | 39.7 | 9.2% |
| passing yards | 30 | +0.853 | 233.7 | 225.7 | 4.1% |
| passing TDs | 28 | +0.652 | 1.6 | 1.4 | 11.2% |

At r = 0.93–0.97 this is largely the same view, not an independent one — which is
what the user suspected before any of it was measured.

**Two methodological traps found on the way, both worth keeping:**

- **The market number is systematically lower and that is NOT disagreement.** A
  betting line sits at the MEDIAN; a projection is a MEAN; fantasy stat
  distributions are right-skewed by long touchdowns. Comparing them naively
  compares two different statistics. The first version of this analysis read that
  artifact as "the market is more pessimistic".
- **A market-implied point TOTAL cannot be built for most players.** Props never
  cover every stat someone accumulates — no rushing line for most QBs, no
  receiving line for most RBs — so any total is a floor, not an estimate. Two
  successive versions of the comparison produced confident nonsense (a slot
  receiver "projected" at 1.6 points) before the coverage gap was noticed.

**Reopen condition:** re-run the per-stat comparison on LIVE in-season lines in
October. Book lines move on injury news within minutes, sometimes ahead of
projections, and a preseason sample is blind to exactly that. If the in-season
correlation drops materially, or the line reacts to news the projection has not
absorbed, props come back — as a per-stat disagreement flag, never as a total.

**Real sportsbook props are paid** (~$30/month for a props tier). Free endpoints
serve game lines only, with no history, which fails §13's standard. Unofficial
book endpoints are out on the same grounds that ruled out ESPN/Yahoo scraping.

## Architecture

| file | role |
| --- | --- |
| `data.py` | loaders only, as today. Weekly projections, weekly actuals, league state, trending, schedule. No logic. |
| `season.py` **new** | **pure.** No I/O, no globals, no module-level league state. Weekly scoring, start/sit, marginal value, ROS aggregation, prop conversion, divergence flags. |
| `store.py` **new, small** | the snapshot table. The only stateful module. |
| `cli.py` | `lineup`, `waivers` subcommands. |

`season.py` obeys `value.py`'s rule for the same reason: it is where the logic
worth testing lives, and it must test without a network. If something in
`season.py` wants to fetch, the design is wrong.

**`lineup_value` and `optimal_lineup` are imported, never re-implemented.** The
Phase 3 lesson — a second copy of `FLEX_ELIGIBLE` would have let the roster
panel start a quarterback at FLEX while MARG said otherwise — applies with more
force here, because start/sit *is* the lineup rule.

### Commands

```
.venv/bin/python -m ffhelper.cli lineup  --league <name> [--week N]
.venv/bin/python -m ffhelper.cli waivers --league <name> [--week N] [--limit N]
```

(There is no `ffhelper` console script and this spec does not add one; the
project invokes modules directly, as `run` and `preflight` already do.)

`lineup` prints the optimal starting lineup with each slot named, the bench, and
for every start/sit decision that is CLOSE, both players with their projection,
the market's number where it exists, and their status. **Closeness is what makes
a row worth printing**: a 4-point gap is a decision, a 40-point gap is noise on
the screen. The threshold is a tunable, `close_call_points`, defaulting to
**3.0** — chosen as roughly the weekly standard error implied by §15 rather than
by taste, and expected to move once `backtest_weekly.py` measures it.

`waivers` prints free agents ranked by marginal value over the rest of the
season, with the trending count and a suggested bid. The FAAB budget is READ:
the league's total comes from Sleeper's settings and spend-to-date from
`transactions`, so the remaining budget is derived, not typed. It never claims
anything.

Both degrade per invariant #5: a missing source removes its column, visibly
labelled, and never produces a guessed number.

## Persistence — one table, and why it exists

**The API serves only current state.** No historical projections, no historical
lines. So a decision made on Tuesday cannot be evaluated in December unless the
inputs were recorded on Tuesday.

That is the whole justification, and it is enough:

```sql
CREATE TABLE snapshot (
  league   TEXT, season TEXT, week INTEGER, player_id TEXT,
  taken_at TEXT,                       -- ISO, when we asked
  proj_pts REAL,                       -- Rotowire, this league's scoring
  matchup  REAL,                       -- the adjustment applied, NULL before 4b
  status   TEXT,                       -- injury/practice at decision time
  started  INTEGER,                    -- did the tool advise starting them
  PRIMARY KEY (league, season, week, player_id)
);
```

**Where it lives:** `season.db` at `ROOT`, never relative to cwd — the same
lesson `DRAFT_LOG_DIR` already carries, because the one time the path matters is
the run where you are not thinking about your shell. `*.db` is already
gitignored.

**What this is not.** It is not Phase 2's SQLite draft log — that is cut. It is
not a cache (`.cache/` already does that). It is not a source of truth for
rosters; Sleeper is. It is a record of what each source claimed at the moment a
decision was taken, so the claims can be scored later.

**Six weeks of it makes the ADVICE measurable** — did the lineups this tool
recommended beat the ones actually started, and did the matchup adjustment help
or hurt? Neither question can be answered retroactively, because the inputs are
not re-served. That is the argument for writing it in week 1 rather than
deciding later, and it is also what would let props be evaluated properly if the
October re-test brings them back.

## Yahoo

No API, no reply to the access application as of 2026-09-01. So:

- **The Yahoo roster is hand-entered** as a plain list of names, one per line,
  in `.roster/<league>.txt`, resolved through `transcribe.py`'s EXISTING name
  resolver. Never a second resolver — that is how Bijan and Brian Robinson get
  confused. A file rather than `config.toml` for two reasons: rosters change
  weekly and TOML editing is a worse weekly chore, and the file's mtime is the
  roster's age, which the risk below requires printing. `.roster/` is gitignored
  — it is league state, not source. Ambiguous or unresolved lines abort the read
  and are printed; a silently dropped name is a silently wrong lineup.
- Everything else is platform-independent: projections, scoring, lineup
  optimisation and market data all work.
- **Waivers and trades are Sleeper-only in practice**, because the free-agent
  pool needs every roster and Yahoo will not give them. Say so in the output
  rather than presenting a pool that is silently wrong.

If access arrives, the Yahoo half becomes a loader and nothing above changes.

## Testing

Same discipline as Phase 1, for the same reason: nine defects have been found by
running this code against real data past a fully green suite.

- `season.py` is pure and tests with synthetic players. Fixtures must resemble
  real data — **not round numbers, not four-player pools**, which is the cause
  this project has already traced seven defects to.
- **Every new test verified red before the fix**, via
  `git stash push -u -- ffhelper && pytest -k <name>`. The `-u` is mandatory
  here: `season.py` and `store.py` are NEW files.
- **A mutation in `scripts/mutate.py` alongside each piece of non-trivial
  logic.** Particular candidates: the prop-to-points conversion, the ROS
  horizon boundary (does week N include week N?), the free-agent pool
  subtraction, and the FAAB bid.
- **A weekly backtest, `scripts/backtest_weekly.py`**, is the season-mode
  sibling of `backtest.py`: projected weekly points against actual weekly
  points, per position, over 2025. It answers "how good is the base at all",
  and once the snapshot table has history, "does the market beat it".
  **It must apply the same provenance guard `backtest.py` does** — and there is
  a specific trap: a past week's projection is served in its *last* state, and
  whether that state predates the game has not been verified. Verify before
  scoring anything with it, or the measurement is contaminated in the flattering
  direction.

`preflight` gains a season-mode mode: current week resolves, rosters fetch,
weekly projections join, last week's actuals carry an `opponent`, and the
free-agent pool is non-empty.

## Slices

| slice | contains | done when |
| --- | --- | --- |
| **4a** | weekly projections, player-status fields, `season.py`, `ffhelper.cli lineup` | a correct optimal lineup prints for both leagues in week 1 |
| **4b** | weekly actuals loader, matchup adjustment, `backtest_weekly.py`, snapshot table | the matchup column appears AND has been scored against unadjusted on 2025 |
| **4c** | league state loaders, free-agent pool, ROS horizon, trending, `ffhelper.cli waivers` | ranked waiver targets with a derived FAAB bid |
| **Phase 5** | two-sided search over public rosters | own spec |

**4a is the only slice with a deadline** — week 1 is Sept 9. 4b is second
because matchup is the measured gap in start/sit, which is the feature that runs
every week. Waivers can land mid-season at no cost.

## Risks

- **Every Sleeper endpoint used here is undocumented** (projections, actuals,
  trending) and can change or vanish. Each must degrade to an absent column.
  None may be committed to this public repo — non-negotiable #5.
- **The matchup adjustment is the most dangerous thing in this spec.** It is a
  number the tool invents, applied to every start/sit call, in a project whose
  §15 rule explicitly forbids hand-picked discount factors. Three guards, and
  none is optional: shrink toward the league mean (full shrinkage in week 1),
  show it as its own column, and let it reorder nothing until it beats
  unadjusted projections in `backtest_weekly.py`. **If it fails that test, ship
  it as a display-only column and say so** — that is a legitimate outcome, not a
  failure of the slice.
- **Early-season defensive samples are tiny.** After two games a "matchup" is two
  opponents, and over-reacting to it is the single commonest fantasy error the
  tool could automate.
- **The Yahoo roster is hand-entered and will drift** as the season goes on. A
  stale roster silently produces a wrong lineup, which is the same failure class
  as draft-mode attribution drift. Print the roster's age.
- **Start/sit advice may simply not beat intuition.** §15 measured that within
  the top tier of a position, projection ordering carries very little
  information. The weekly backtest is what turns that from a worry into a
  number, which is why it is in 4c rather than "later".
