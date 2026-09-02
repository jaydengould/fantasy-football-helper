# Phase 4c — waivers

Written 2026-09-02, after `phase-4b-snapshot` merged. Supersedes the waiver
half of `2026-09-01-phase-4-season-mode-design.md`, whose FAAB premise was
wrong; that spec's correction appendix records why.

**One command.** `ffhelper.cli waivers` answers: *what does the wire owe me,
this week and for the rest of the season, and what would it cost to take it?*

## The premise that was wrong, and what it changes

The Phase 4 spec's 4c row promised "ranked waiver targets with a derived FAAB
bid". **The league does not use FAAB.** It runs rolling waiver priority —
confirmed by the user against Sleeper's UI on 2026-09-02, after the live
settings contradicted the docs: `waiver_type: 0`, and all twelve rosters carry
a distinct `waiver_position` (1-12) with `waiver_budget_used: 0`.

The bad claim rested entirely on `waiver_budget: 100` in the settings payload —
**a field Sleeper returns by default whether or not bidding is on.** Same shape
as the Yahoo one-RB-slot error: a league rule inferred from an API default
rather than read off the platform's own screen.

So there is no bid to derive. Priority is a consumable *ordering*, not a
currency, and the output says where you sit and what spending it costs.

**Unaffected:** the waiver notify-bot stays cut. That rests on claims resolving
in a scheduled batch (`waiver_clear_days: 2`, `waiver_day_of_week: 2`), which
is still true.

## What the data says before anything is built

Measured 2026-09-02 against the real `sleeper-main` roster and pool, in scratch,
before a line of this was designed. **It argues against the obvious version of
the feature.**

With a healthy 15-man roster the wire has essentially nothing:

| best available upgrade, week 1 | +1.2 pts (a streaming DEF) |
| best available upgrade, rest of season | **+8.3 pts over 18 weeks** |
| base lineup, same horizon | 2399.0 pts |
| so, per week | **0.46 pts** |
| measured TE weekly MAE (`backtest_weekly.py`, 2025) | **3.23** |

**The best thing on the wire is inside the noise by a factor of seven.** A
ranked list of 355 free agents separated by tenths of a point is precisely the
over-reaction this project has now cut twice — the matchup adjustment and its
tercile label both died on the same standard.

What the wire IS worth is measured by opening a hole. Dropping each starter and
re-ranking:

| hole | best free-agent replacement | ROS gain | per week |
| --- | --- | --- | --- |
| **Jake Ferguson (only TE)** | Dalton Schultz | **+163.9** | 9.1 |
| Jason Myers (K) | Tyler Loop | +128.7 | 7.2 |
| Denver Broncos (DEF) | New England | +123.7 | 6.9 |
| Chris Olave (WR) | Schultz | +19.5 | 1.1 |
| Josh Allen (QB) | Jordan Love | +37.7 | 2.1 |
| D'Andre Swift (RB) | Schultz | +9.8 | 0.5 |

**The signal is positional depth, not marginal ranking.** Ferguson is worth
+163.9 because he is the only tight end on the roster and the slot cannot
otherwise be filled. Allen is worth only +37.7 despite being the best player on
the team, because Kyler Murray already backs him up. That asymmetry is the
whole product.

## The significance floor

**A candidate prints only if it clears the noise on the horizon it is ranked
on.** One tunable, `close_call_points` (3.0), applied at the right scale:

| section | threshold |
| --- | --- |
| THIS WEEK | gain > `close_call_points` |
| REST OF SEASON | gain > `close_call_points` × √(weeks remaining) |

**The √ is not decoration and the flat version was wrong.** `close_call_points`
is calibrated to a SINGLE week's projection error (TE weekly MAE 3.23, measured
by `backtest_weekly.py` on 2025). The error on a fourteen-week total is not
fourteen times that — independent weekly errors partially cancel, so the
standard error of the sum grows as √n, not n. Requiring 3.0 points per week
across a season demands the season-long edge clear the single-week noise bar,
which is roughly four times too strict and silences real upgrades.

`close_call_points` is reused rather than given a sibling because it is already
the project's answer to "how big must a projected gap be before it is a
decision", already defaulted from measured error, and already expected to move
when `backtest_weekly.py` refines that error. A second threshold measuring the
same quantity would drift from it.

**Validated against the measured cases above before being written**, which is
the standard `CLAUDE.md` demands of any factor the tool applies. At 18 weeks
remaining the ROS bar is 12.7 points; at 14 weeks it is 11.2:

| case | ROS gain | bar | prints? | right? |
| --- | --- | --- | --- | --- |
| today's healthy board | +8.3 | 12.7 | **no** | yes — it is 0.46/wk of noise |
| lose Ferguson (only TE) | +163.9 | 12.7 | yes | yes |
| lose K | +128.7 | 12.7 | yes | yes |
| lose DEF | +123.7 | 12.7 | yes | yes |
| lose Allen (Murray backs him up) | +37.7 | 12.7 | yes | yes — 37.7 pts is a real gain |
| lose Olave | +19.5 | 12.7 | yes | marginal, and correctly marginal |
| lose Swift (three RBs behind him) | +9.8 | 12.7 | **no** | yes |

**The healthy-roster board is empty and that is the headline result.** An empty
board must be printed as a result, in a sentence, not as a blank.

## Output

```
waiver priority 8 of 12 -- a successful claim sends you to 12th

THIS WEEK -- upgrade to your week 5 lineup
  RB  Tyjae Spears        +6.2   would start at FLEX over Mason
                                 add, drop Jalen Coker (bench, 0 ROS starts)

REST OF SEASON -- upgrade over weeks 5-18
  RB  Bucky Irving       +31.7   add, drop Tyler Allgeier (bench, 0 starts)
  TE  Cade Otton         +12.9   add, drop Mike Gesicki (bench, 0 starts)

  next-best RB if you keep priority: Tyjae Spears +11.4
  spending 8th costs you 20.3 pts of RB upgrade this season

  the drop is by PROJECTION ONLY -- it does not know about handcuffs,
  upside, or your bye weeks. read it, do not follow it.
  trending: Irving +279k adds NATIONALLY -- not a signal about your league.
```

Both sections rank by **true marginal value**, not by raw points: the best
lineup with the candidate in and your most expendable player out, minus your
lineup as it stands. The roster is 15/15, so every add really is an
add-and-drop, and an add-only number overstates every candidate by the value of
whoever you would have cut.

## The drop

**Chosen on the ROS horizon only, never on one week.** The week-1 probe proved
why: a one-week horizon happily offers to cut your backup QB for 1.2 points of
streaming defense. The arithmetic is right and the advice is ruinous.

**Ties are real and must not be broken silently.** For Dalton Schultz the top
two drops are Shakir (+8.3) and Addison (+7.8) — and in the week-1 run five
players tied *exactly*, so the code named an arbitrary one. Printing an
arbitrary member of a tie as "the drop" is fabrication in this project's sense:
a name presented as computed when it was positional.

The rule, stated in the source and on screen: **among drops within 0.5 points
of the best, take the lowest ROS points.** Deterministic, and the caveat line
says the choice is by projection only.

**Naming a drop is the first output where being wrong is permanent.** A bad
start/sit call costs one week; a claimed drop does not come back. It remains
advice rather than action, so non-negotiable #6 is intact — but the caveat is
not decoration.

## Architecture

| file | change |
| --- | --- |
| `data.py` | `load_trending(kind, ...)`. One loader, same `fetch_json` shape as every sibling. |
| `season.py` | **pure.** `free_agent_pool`, `waiver_targets` → ranked `WaiverTarget(player, gain, drop, weeks_started)`. |
| `cli.py` | the `waivers` subcommand, and one extraction (below). |

**`_resolve_my_roster` is extracted from `_lineup`, and it is required rather
than opportunistic.** `_lineup` holds ~90 lines resolving whose roster this is
— the hand-set override, then derivation through the draft feed, then the
degraded path — plus the cache-age and owner notes. `waivers` needs it
identically. A second copy is the `FLEX_ELIGIBLE` mistake with higher stakes:
two commands disagreeing about whose team they are advising.

`lineup_value` and `optimal_lineup` are **imported, never re-implemented**, for
the reason the Phase 4 spec already gives.

### Cost, measured not estimated

| | |
| --- | --- |
| candidates (free agents with a projection in the horizon) | 355 |
| lineup evaluations, full ROS add-and-drop | 355 × 15 drops × 18 weeks |
| wall clock, warm cache | **3.2s** |
| network, cold cache | ~108 requests (6 positions × remaining weeks) |
| network, warm | 0.3s |

Compute is a non-issue. The cold fetch is the real cost and it is once an hour
(`load_weekly_projections` caches at `ttl_seconds=3600`).

## Degradation — invariant #5, unchanged

| source down | result |
| --- | --- |
| trending | the trending line is absent. Never a zero. |
| a roster with no `waiver_position` | the priority line is absent; the board still ranks. |
| a week's projections | that week drops out of the ROS sum **and the printed week count says so** — see below. |
| rosters | no pool can be computed; the command says so and stops. |
| **Yahoo** | refuses, labelled. The free-agent pool needs every roster and Yahoo has no API. |

**A bye is an ABSENT ROW, not a zero** — verified: Gibbs has no week-6 row,
Allen no week-7, Nacua no week-11. So is an injured player, and so is a player
nobody projects. Summing "the weeks that answered" silently loses the 4a
distinction between a measured 0.0 and no number at all, over fourteen weeks
instead of one. **Every ROS total prints the count of weeks that contributed**
(`starts 9 of 14 remaining weeks`), which is the only thing that makes the
total readable.

## Known limits, stated rather than fixed

- **TE dominates the raw ranking.** Nine of the top twelve ROS candidates are
  tight ends, because TE has the shallowest replacement level of any position —
  `TODO.md` §14, observed live in the draft and now again here. The floor
  suppresses most of it; what survives is genuine. Fixing it needs an upside
  model the projections do not carry.
- **Trending is national.** 279k adds is the whole Sleeper userbase across
  millions of leagues; it says nothing about whether your eleven opponents want
  the player. It is printed as description and explicitly labelled, never used
  to predict whether a claim wins. Using it that way would be the matchup
  adjustment's error by a new route.
- **The ROS sum inherits flat preseason projections.** Until usage data
  accumulates, Rotowire's weekly numbers barely move (Nacua reads 20.4-21.0
  across all 18 weeks), so a September ROS ranking is close to a restatement of
  season-long consensus. This is an argument for the floor, not against the
  feature: the floor is what keeps it quiet until the projections have
  something to say.

## Testing

Same discipline as 4a and 4b, for the same reason.

- `season.py` stays pure and tests with realistic fixtures — **not round
  numbers, not four-player pools**, the cause this project has traced seven
  defects to.
- **Every new test verified red before the fix**, via
  `git stash push -u -- ffhelper && pytest -k <name>`.
- **Mutations on the four places a silent wrong answer would look healthy:**
  the free-agent pool subtraction, the ROS horizon boundary (does week N
  include week N?), the floor comparison, and the drop tie-break.
- `scripts/mutate.py` is run in the FOREGROUND, ALONE — no subagent may run its
  own concurrently.
- **The command is run against the real league before it is called done**, and
  the healthy-roster case must print an empty board. A board with rows on a
  healthy 15-man roster in week 1 is the defect, not the success.

## Out of scope

- **Writing waiver candidates to the snapshot table.** Its primary key is
  rostered players, and scoring advice-not-taken is a different question with
  its own design. Reopen if the empty-board rule ever needs auditing.
- **A Dash page.** CLI first, as with `lineup`.
- **Yahoo waivers.** No API, no pool. If access ever arrives it is a loader and
  nothing here changes.

## Amendment 2026-09-02, during planning — `load_league_transactions` is cut

The Architecture table originally carried it. **It has no consumer.** Under FAAB
it supplied spend-to-date; under priority, your position comes from the
`rosters` payload (`settings.waiver_position`) and the cost-of-spending line is
arithmetic on two already-computed targets. The one option that would have read
it — league-local add/drop activity — was offered and not chosen. Cut rather
than built unused.

**And the two sections are one code path.** The floor is
`close_call_points × √weeks`, and √1 = 1, so THIS WEEK is the rest-of-season
function called with a single-week horizon. No branch, no second threshold.
