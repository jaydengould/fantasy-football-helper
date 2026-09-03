# Phase 5 — trade finder

Written 2026-09-02, after `phase-4c-waivers` merged. Supersedes the "Phase 5
preview" in `2026-08-24-draft-mode-design.md`, whose ranking mechanism does not
exist; the correction is below.

**One command, two modes.** `ffhelper.cli trades` answers: *which two-sided swap
improves my starting lineup and my counterparty's, over the weeks that still
count?* — either scanning the whole league, or pivoted on one named player.

**Authority:** `CLAUDE.md` holds the standing decisions and non-negotiables.
Where this spec and that file disagree, that file wins and this one is wrong.

## The premise that was wrong, and what it changes

The Phase 1 preview promised proposals "ranked by a data-backed prior from
transaction history — does this manager trade at all, how often, do they take
2-for-1s, are they still active."

**That prior has no data.** Measured against the live league on 2026-09-02:

| | |
| --- | --- |
| transactions all season | **3**, all free-agent moves |
| trades, ever | **0** |
| `previous_league_id` | **None** — the league has no prior season at all |

So the ranking mechanism the preview named cannot be built, and **nothing is
substituted for it.** Fitting a manager model to an empty sample is the FAAB
bid again — a confident number derived from what an API happens to return
rather than from an observation. Proposals rank by my own gain, and the board
states that it cannot tell you whether anyone will accept.

**Unaffected:** the preview's refusal to output an acceptance *probability*
stands, and now rests on a measurement rather than a judgement.

**Reopen condition:** revisit in November if the league has by then generated
actual trades. `load_league_transactions` — cut in 4c for having no consumer —
is what it would need, and it stays cut until then.

## What the data says before anything is built

Measured against the real `sleeper-main` roster and all eleven opponent rosters,
in scratch, before a line of this was designed.

**1-for-1, the shape everyone imagines, is empty.** All 11 opponents, 2475
pairs, 3.1s:

| | |
| --- | --- |
| pairs where BOTH teams gain anything at all | **11 of 2475** (0.4%) |
| best of them | +9.3 me / +2.6 them, over 18 weeks |
| the significance floor at this horizon | **12.7** |
| pairs clearing it | **0** |

**2-for-2 is where the surplus lives.** 33,075 combinations across three
opponents, 41s: **49 proposals clear the floor on both sides**, best +34.3 me /
+13.7 them. That is the lineup-constraint surplus the Phase 1 preview predicted,
and it only appears once roster spots are consolidated — a 1-for-1 cannot
express it, because it cannot change how many bodies each side carries at a
position.

**The full board is one row.** All eleven opponents, all three shapes, 330s:

```
TRADES -- sleeper-main (jaydenpg) -- week 1, 18 weeks left
  both sides must gain more than 12.7 pts; 1 of 11 teams qualify

  leaguemate       you + 34.3   them + 13.7   [2-for-2]
                   give Khalil Shakir (WR) + Christian Watson (WR)
                   get  George Pickens (WR) + Los Angeles Chargers (DEF)
```

The 49 hits above were concentrated almost entirely in one opponent. **Best-per-
opponent is therefore not a display convenience — it is what turns ~180 near-
duplicate proposals into a call list**, and it collapses to one row because only
one manager in the league holds a surplus that pairs with mine.

**Provenance of that board, because it is not what the shipped default will
print.** Every number above was measured with a FLAT weight vector over weeks
1–18, i.e. before the calendar fix and the week weights below. Ending the
horizon at week 17 and down-weighting the playoff weeks both shrink every total
and shift the floor, so the shipped board may differ. It is quoted here as
evidence about the SHAPE of the result — 1-for-1 empty, 2-for-2 productive, one
opponent qualifying — not as the expected output. Re-measuring it under the
shipped defaults is an acceptance step, not a formality.

## The evaluation model

A trade is `roster_upgrade` run twice. There is no new ranking engine, and if
this spec ever seems to need one the design is wrong.

```
gain_me   = horizon_total(mine   - give + get,  weights) - horizon_total(mine,   weights)
gain_them = horizon_total(theirs - get + give,  weights) - horizon_total(theirs, weights)
```

Both sides scored over the same weeks under **this league's own rules** — one
league, one rulebook. A trade is worth making because lineup constraints create
surplus on both rosters, not because someone is being fleeced.

### Both sides must clear `close_call_points × √weeks`

Not merely be positive. The floor and the √ are 4c's, reused for 4c's reasons:
the tunable is calibrated to a SINGLE week's projection error (TE weekly MAE
3.23, measured by `backtest_weekly.py` on 2025), and independent weekly errors
partially cancel, so the standard error of a sum grows as √n.

**Applying it to THEIR side is the load-bearing decision.** The output is an
argument you send to another human. "+2.6 points for you across eighteen weeks"
is smaller than the error on the number that produced it, and a proposal built
on it cannot be defended when the counterparty asks why. Measured, this single
choice is the difference between 11 rows of noise and the 1 real row above.

**Under weights, the floor is `close_call_points × √(Σ weights)`, not
`√(week count)`.** A week counted at 0.33 contributes a third of a week's worth
of independent error, so the effective sample size is the sum of the weights.
With flat weights Σ = n and this reduces to 4c's rule exactly, which is why one
expression serves both and no second threshold appears.

### Roster legality is modelled, not ignored

| shape | my roster after | theirs after | consequence |
| --- | --- | --- | --- |
| 1-for-1 | 15 | 15 | neutral, nothing to resolve |
| 2-for-2 | 15 | 15 | neutral, nothing to resolve |
| **2-for-1** | **14 — legal** | **16 — illegal** | they must cut one, and the cut is SEARCHED |

**My fourteenth spot is deliberately not re-filled from the wire.** The first
probe did exactly that and it inflated my gain by whatever the free-agent pool
happens to be worth, conflating a trade with a waiver add. `waivers` already
answers that question, separately, and entangling the two makes neither number
mean anything. It also cost 403s for three opponents, against 41s without.

A 14-man roster still fills every starting slot, so `horizon_total` on it is
well defined and needs no invention. A 16-man one is not legal, so their forced
cut is real and is computed the way `roster_upgrade` computes a drop.

### No prefilter, and this was tested rather than asserted

An obvious prune: drop incoming players who could never crack my lineup. It is
sound for 1-for-1 and **unsound for everything else** — giving away two players
opens a slot the pruned player then fills.

Measured: it kept 121 of 165 opponent players, ran 1.7× faster, and **silently
dropped 22 of 49 real trades** (27 found against 49). It is not in the design.

Recorded because the argument for it felt like a proof, and this project's rule
is that eliminating one suspect is not a verdict. The check cost one probe.

## The calendar — three facts read from the payload, not assumed

All three come from the league settings endpoint already fetched.

| setting | value | consequence |
| --- | --- | --- |
| `trade_deadline` | **11** | after week 11 the command refuses, labelled. Printing proposals you are not allowed to make is worse than printing none. |
| `playoff_week_start` | **15** | the fantasy season ends week **17**, not 18 |
| `playoff_teams` | **6** | 3 rounds (`ceil(log2(6))`), so 15 → 17 |

**`season.LAST_REGULAR_WEEK = 18` is wrong for this league and it is already
shipped.** `waivers` sums rest-of-season value through week 18, but with
playoffs starting week 15 and a three-round bracket, week 18 is played by nobody
and contributes to no fantasy outcome. It is ~5% of the horizon, and it is the
same shape as the one-RB-slot and FAAB errors: a league rule assumed rather than
read. **Phase 5 fixes it for both commands**, which means `waivers` output moves
slightly and must be re-run and re-checked as part of this work.

**Guard:** the round arithmetic assumes `playoff_round_type: 0` (one week per
round), which is what this league serves. Any other value falls back to the
current constant and says so on screen, rather than computing a confident wrong
last week.

## Week weights — the seam, and a defensible default

`horizon_total` gains a per-week weight vector. It is computed ONCE before the
search and never inside it, so the search cost is unchanged no matter how smart
the weights later become.

**The default is derived, not picked.** A point scored in a week you do not play
is worth nothing, so the weight is the probability you play that week under the
league's own bracket and a uniform prior over seeds:

| weeks | who plays | weight |
| --- | --- | --- |
| 1–14 | everyone | 1.0 |
| 15 | 4 of 12 (top two seeds have byes) | 0.33 |
| 16 | 4 of 12 | 0.33 |
| 17 | 2 of 12 | 0.17 |

**This weights playoff weeks DOWN, which is the opposite of the literature**,
and the disagreement is honest rather than accidental. The arXiv playoff-biasing
work weights weeks 15–17 up because championships are decided there; that is a
statement about *conditional* value, and it is only reachable through a matchup
win-probability model nobody here has validated. The derivation above answers
the question this tool can actually answer — expected points that count — and it
says you may not be there at all, and you only get there by winning weeks 1–14.

**Both readings are available to the user.** `tunables.playoff_weight`, when
set, replaces the derived playoff-week weights with that constant; unset, the
derivation stands. The knob exists precisely because the direction is contested,
and the spec refuses to smuggle a preference in as a default.

**To justify weighting playoff weeks up, bring a backtest showing it picks
better trades** — the same bar the matchup adjustment failed on.

## Output

**Mode 1 — the board.** `trades --league sleeper-main`. Best proposal per
opponent, ranked by my gain, at most 11 rows and realistically 1–3. An empty
board is a stated result, in a sentence, exactly as in `waivers`.

**Mode 2 — the pinned search.** `trades --player "smith-njigba"`. The player is
resolved through the existing partial-name matcher with the same disambiguation
rules as manual mark-drafted — the Bijan/Brian problem is unchanged here, and a
wrong resolution silently answers a question nobody asked.

| the named player is | the question | ranked by |
| --- | --- | --- |
| on my roster | what is the best return for him? | my gain |
| on someone else's | what would it take to get him? | **their** gain |

The second ranking is deliberate: when I am the one asking for a player, the
constraint is what makes the other manager say yes, so the board should lead
with the packages that pay him most while still clearing my own floor.

Every row states both packages, both gains, the shape, and — for a 2-for-1 —
the player the counterparty would have to cut, because that cut is part of the
offer and they will notice it before you do.

## Ranking and what the board refuses to claim

Ranked by my gain. Nothing models acceptance, per the section above, and the
board says so in a line rather than leaving it to be inferred.

Ties break on player id, matching `roster_upgrade`'s rule and for its reason: a
board that renames a package when nothing changed is one nobody can trust. This
is also why the search is **exhaustive rather than heuristic** — see below.

## Architecture

| file | change |
| --- | --- |
| `trade.py` | **new, pure.** `Proposal`, `trade_options`, the three shapes, the pin. |
| `season.py` | `horizon_total(..., weights)`; `week_weights`; `last_scoring_week`. |
| `cli.py` | the `trades` subcommand and `render_trades`, mirroring `_waivers`. |
| `config.toml` | `tunables.playoff_weight`, optional. |

```python
@dataclass(frozen=True)
class Proposal:
    opponent: int                 # roster_id
    give: tuple[Player, ...]
    get: tuple[Player, ...]
    gain_me: float
    gain_them: float
    their_drop: Player | None     # 2-for-1 only; None means roster-neutral

def trade_options(mine, theirs, opponent, slots, weekly_by_week,
                  floor, weights, pin=None) -> list[Proposal]
```

**One opponent per call.** It keeps the module single-subject, tests without a
network, and leaves the eleven-way loop and best-of-each in `cli` where the
league context already lives.

**A new module rather than growing `season.py`**, which is 526 lines and reasons
about one roster at a time. A trade is a two-roster operation, which is a
different subject; the split follows the existing `value.py` / `season.py` line,
which is drawn by what a module reasons about rather than by which phase built
it. `lineup_value`, `optimal_lineup`, `horizon_total` and `with_weekly_points`
are **imported, never re-implemented.**

**`_resolve_my_roster` and `_resolve_week` are reused as-is.** They were
extracted in 4c for exactly this; a second answer to "whose roster is this"
would be the `FLEX_ELIGIBLE` mistake with higher stakes.

### Cost, measured not estimated

| shape | combinations | wall clock, warm |
| --- | --- | --- |
| 1-for-1 | 2,475 | 3.1s |
| 2-for-1 (their forced cut searched) | 17,325 × 16 evaluations | ~194s |
| 2-for-2 | 121,275 | ~151s |
| **full board, all shapes, 11 opponents** | | **330s** |
| pinned mode | ~1/15th of the above | ~20s |

**5.5 minutes is accepted, and no optimisation ships with it.** A weekly one-shot
command may be slow; a fast one that silently drops real trades may not, and the
prefilter section is what that judgement rests on. A progress line prints so it
does not look hung. Marked with a `ponytail:` comment naming the ceiling.

**A genetic algorithm is rejected on the same ground.** The arXiv work uses one
to avoid exhaustive enumeration across millions of leagues; we enumerate one
team's options in 330s, and a GA would trade exactness for speed we do not need
while returning **different answers on different runs** — which this project
already ruled out when it made `roster_upgrade`'s tie-break deterministic.

## Where this sits against how the industry does it

Researched 2026-09-02, and it changed nothing in the core design — recorded so
the question is not reopened as a fresh opinion.

**The dominant commercial approach is a single trade-value number per player**
(FantasyPros from consensus expert rankings, dynasty charts from analyst
consensus, simpler tools from VORP over ROS projections); you sum each side and
compare. **This project cannot use it and should not want to**: a consensus
ranking is *price*, and non-negotiable #2 forbids folding price into the value
axis. It is the same reason §18 closed ECR.

**The better tier of tools does what `lineup_value` already does** — the sources
describe personalising value by "roster depth at a position, slot count, and
position importance." Where they apply a positional *adjustment*, this computes
the actual lineup effect over the real horizon. That is strictly more precise,
and it is why the search surfaced a proposal built around a bench defense, which
no value chart can represent.

**ESPN's published system applies an explicit diversity constraint** to avoid
proposing many variants of one trade. That is independent confirmation of the
near-duplicate problem measured above; best-per-opponent is this tool's version
of it.

## Degradation — invariant #5, unchanged

| source down | result |
| --- | --- |
| league settings | the calendar falls back to `LAST_REGULAR_WEEK` and the deadline check is skipped, both stated on screen |
| a week's projections | that week leaves the horizon **and the printed week count says so** |
| rosters | no opponents, so nothing can be searched; the command says so and stops |
| league users | proposals render with `team <roster_id>` instead of a display name |
| **Yahoo** | refuses, labelled, exit 1 — it needs every roster and Yahoo serves none |
| **past the trade deadline** | refuses, labelled, exit 0 — a legal state, not an error |

A bye remains an ABSENT ROW, not a zero, and every horizon total prints the
count of weeks that contributed. Both inherited unchanged from 4c.

## Known limits, stated rather than fixed

- **Their gain assumes they set an optimal lineup every week.** They may not.
  The assumption is applied to their baseline and their post-trade roster
  equally, so it partially cancels, but the number is an upper bound on a
  manager who benches the wrong player.
- **No injury or depth model.** A 2-for-1 leaves me at 14 and thinner
  somewhere; `horizon_total` assumes everyone plays their projection. This is
  the same gap `waivers` has, and closing it needs a variance estimate this
  project has never made.
- **Preseason projections are flat** (Nacua reads 20.4–21.0 across all 18
  weeks), so a September board is close to a restatement of season-long
  consensus. The floor is what keeps it quiet until the projections have
  something to say. Stated on screen in week 1.
- **Neither platform's API accepts a submitted offer.** Proposals are sent by
  hand. Non-negotiable #6 intact.
- **The uniform-seed prior in the default weights is an assumption**, and it is
  the one the deferred leverage slice replaces with real standings.

## Testing

Same discipline as 4a, 4b and 4c, for the same reasons.

- `trade.py` stays pure and tests with realistic fixtures — **not round numbers,
  not four-player rosters**, the cause this project has traced seven defects to.
- **Every new test verified red before the fix**, via
  `git stash push -u -- ffhelper && pytest -k <name>`. The `-u` is not optional:
  `trade.py` is a NEW file, and plain `git stash push` leaves it on disk.
- **Mutations on the five places a silent wrong answer would look healthy:** the
  forced cut on a 2-for-1 is actually applied; the floor is checked on BOTH
  sides; no re-fill happens on my 14-man side; `pin` selects the give or get
  side by roster membership; and the tie-break is deterministic.
- `scripts/mutate.py` runs in the FOREGROUND, ALONE — no subagent may run its
  own concurrently, and the suite must be GREEN before the run is believed.
- **Run against the real league before it is called done.** The board must
  reproduce the single one-row board, and `waivers` must be re-run and its
  changed horizon checked, since this phase alters it.

## Out of scope, and the two deferred slices

- **Leverage weighting.** Weight weeks by how much they actually move your
  playoff odds — heavier late-regular-season weeks when you are on the bubble.
  Requested by the user and it is the correct form of the idea. **Deferred, not
  rejected**, for three reasons: it is completely inert today (every team is
  0-0, so it computes a uniform vector); it is a different subject, being a
  playoff-odds simulation over the remaining schedule; and it needs a per-team
  score variance this project has never estimated. **The data supports it** —
  probed 2026-09-02: the full schedule is served in advance (11 distinct
  pairings across weeks 1–14) and rosters carry `wins` / `losses` / `fpts`. It
  plugs into the weights seam with no change to the search. Live window is
  roughly weeks 8–11, between a real bubble and the week-11 deadline.
- **Win-probability lineups.** Start high-floor players when heavily favoured,
  high-ceiling when an underdog; FantasyPros applies the same framing to trades
  by scoring post-trade *record*. It needs the same missing ingredient —
  per-player variance — so the two slices share a prerequisite and should be
  built in that order. It is testable: `backtest_weekly.py` is one arm away from
  asking whether it wins more head-to-head matchups than expected-points
  selection on 2024 and 2025. **A real gate, and it must pass it.**
- **Writing proposals to the snapshot table.** Scoring advice-not-taken is a
  different question with its own design.
- **A Dash page.** CLI first, as with `lineup` and `waivers`.
- **Yahoo.** No API, no opponent rosters. If access arrives it is a loader and
  nothing here changes.
- **3-for-2 and larger.** No evidence any of it adds what 2-for-2 does not, and
  the combinatorics grow faster than the honesty of the projections behind them.
