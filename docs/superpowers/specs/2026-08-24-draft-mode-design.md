# Fantasy Football Helper — Draft Mode Design

**Date:** 2026-08-24
**Status:** Approved
**Scope:** Phases 0–3 (draft mode). Season mode (Phase 4) and the trade finder (Phase 5) get their own spec cycles.

## Goal

A personal tool for live fantasy football drafts that recommends picks using
projections scored against the user's actual league settings, combined with
draft-pick survival probability. Two leagues on two platforms this season:

| League | Platform | Draft | Format |
| --- | --- | --- | --- |
| Bros with no hoes (`1395959490938966016`) | Sleeper | **Sept 6, 7:00 PM** | snake, 12 team, 15 rd, 120s clock |
| Yahoo league (id, size, and scoring not yet known — resolved in Phase 0) | Yahoo | **Sept 1** | snake |

The Yahoo draft is first and Yahoo is the harder integration. Build order is
driven by that fact.

## Verified league settings (Sleeper, pulled 2026-08-24)

Roster: `QB / RB / RB / WR / WR / TE / FLEX / FLEX / K / DEF` + 5 bench (15 total).

Scoring is full PPR (`rec: 1.0`), 0.1/yd rush and receive, 0.04/yd passing, and
**6-point passing TDs** — not Sleeper's default of 4.

Waivers run in scheduled batches (`waiver_clear_days: 2`). Claims resolve
simultaneously regardless of submission time, so a same-day waiver alert provides
**no timing edge**. The waiver notify-bot is cut from season mode.

**CORRECTED 2026-09-02:** this paragraph said "Waivers are FAAB
(`waiver_budget: 100`)". They are not — the league runs **rolling waiver
priority**, confirmed by the user against Sleeper's UI (`waiver_type: 0`, twelve
distinct `waiver_position` values). `waiver_budget` is a field Sleeper returns by
default whether or not bidding is on, so the whole claim rested on an API
default. The notify-bot cut is unaffected: it turns on batch processing, not on
the payment mechanism. See the correction appended to the Phase 4 season-mode
spec.

`draft_order` currently holds 11 of 12 slots, so the user's draft position is not
final. Draft slot must be a config override, not trusted from the API.

## Data sources

| Source | Auth | Provides | Join key |
| --- | --- | --- | --- |
| Sleeper `/v1/players/nfl` | none | player DB, injury status (14.6MB) | `sleeper_id` |
| Sleeper `/projections/nfl/{season}` | none | Rotowire projections, raw stat lines, ADP | `sleeper_id` (native) |
| DynastyProcess `db_playerids.csv` | none | `sleeper_id` ↔ `yahoo_id` crosswalk | `sleeper_id` |
| FantasyFootballCalculator ADP | none | **`stdev`**, `high`, `low`, `bye` | name (fuzzy) |
| Sleeper / Yahoo league endpoints | Yahoo: OAuth2 | scoring settings, roster slots, picks | — |

Ruled out: FantasyPros (paid, and their ToU bars reproducing site content).
`nfl_data_py` is deprecated by nflverse in favour of `nflreadpy`; season mode
only, not used in draft mode.

### Sleeper's `yahoo_id` is unusable — crosswalk is mandatory

Sleeper stopped populating `yahoo_id` around 2021:

| years_exp | with `yahoo_id` |
| --- | --- |
| 0 (rookies) | 0 / 302 |
| 1 | 13 / 692 |
| 2 | 113 / 325 |
| 6+ | ~99% |

Jahmyr Gibbs (consensus RB1) has `yahoo_id: None`. Every rookie and sophomore is
missing — exactly the population whose draft value is most contested. Building
the Yahoo path on Sleeper's crosswalk would fail silently on the players that
matter most.

DynastyProcess `db_playerids.csv` covers it: `yahoo_id` 12,470/12,480 (99.9%),
`sleeper_id` 100%. Gibbs resolves `sleeper_id 9221 ↔ yahoo_id 40059`. This is a
**Phase 1 draft-mode dependency**, not a season-mode one.

### Sleeper is two separate things

Sleeper is the **data backbone for both leagues** (projections, player DB, ADP)
*and* one of two **pick feeds**. Yahoo replaces only the feed. The engine never
knows which platform it is serving.

### FFC is an optional, non-load-bearing enrichment layer

FFC is the only source carrying draft-pick variance, and that variance cannot be
synthesized. Fitting `stdev` as a function of ADP alone:

```
stdev = 0.287 × adp^0.809      R² = 0.574
```

42.6% of the variance is irreducible per-player information. The failures are
severe and land exactly where survival matters most:

| Player | ADP | actual stdev | curve |
| --- | --- | --- | --- |
| Keon Coleman | 96.2 | 47.7 | 11.6 |
| Isaac TeSlaa | 167.7 | 40.2 | 18.2 |
| Kaden Wetjen | 172.3 | 3.9 | 18.6 |

FFC therefore stays. To contain its fuzzy-join risk:

> **FFC is left-joined onto an already-complete Sleeper-ID board and supplies
> `adp_stdev` (and `bye`) only.** On a match failure the player keeps Sleeper's
> ADP and falls back to the fitted curve above.

Blast radius of a join failure is one column for one player. It can never
corrupt a projection, drop a player, or merge two players. Unmatched players are
printed at load, never silently dropped.

Match key is (normalized full name, position, team). Last name plus position
plus team is **not** sufficient — Bijan Robinson and Brian Robinson are both RBs
on ATL.

## Recommendation engine

Selected approach: **VBD + survival-weighted VONA**. Rejected: a static VBD board
(a printed cheatsheet that never answers the question at the clock) and a
Monte-Carlo lineup optimizer (needs an opponent model there is no data to fit, too
slow for a 120s clock, and fails silently — a bad simulation still returns a
confident number).

Pipeline, all inside a pure `value.py`:

1. **Custom scoring** — dot product of each player's raw stat line against the
   league's `scoring_settings`.
2. **VBD** — projected points minus the replacement-level player at that
   position. Replacement rank is
   `num_teams × (starters_at_pos + flex_share_of_pos × flex_slots)`. Flex share
   defaults to RB 0.5 / WR 0.5 / TE 0.0 and is config-overridable. For this
   league that gives QB12, TE12, RB30, WR36.
3. **Tiers** — walking sorted VBD, break when the gap to the next player exceeds
   `tier_break_sigma` × the standard deviation of gaps within that position.
   Default 1.0, tunable in config; the right value is an empirical judgement and
   needs a knob rather than a constant.
4. **Survival** — `statistics.NormalDist(adp, stdev).cdf(next_pick_no)`.
5. **VONA** — `proj(p) − E[best available at p.position at my next pick]`.
6. **Marginal lineup fit** — `lineup_value(roster + p) − lineup_value(roster)`.
7. **Run detection** — position distribution over the last 8 picks.
8. **ADP divergence flag** — `projection_rank − adp_rank`, surfaced when the gap
   exceeds `divergence_flag_slots` (default 25).

### ADP divergence is a flag, never a blend

ADP already is a crowd consensus — FFC aggregates thousands of real drafts — and
consensus and point projections systematically disagree because they measure
different things. A ranking absorbs injury risk, role security, and offensive
continuity that a pure projection undersells.

Surfacing the gap is free and needs no new source: a player Rotowire ranks 40
slots above the market is either the edge or the error, and either way is the row
to examine.

**The two ranks must never be averaged into one number.** Blending pulls the
board toward the field, and a board that tracks consensus produces consensus
results — which destroys the reason the tool exists. The flag preserves the edge
while catching outliers; a blend quietly removes it.

### Custom scoring is correct but marginal — do not oversell it

The 6-point passing TD moves raw totals a great deal (Allen 361.5 → 415.5, Burrow
+66.0), but VBD is a *difference* and a near-uniform shift cancels at replacement
level. Actual board effect: Allen's VBD moves 65.8 → 68.0; Jackson and Maye rise
about three overall slots. Worth building — roughly ten lines, and simply correct
— but VONA and survival carry the real edge.

### `lineup_value()` is a first-class function

`lineup_value(roster, projections, slots) -> float` returns what a set of players
scores as an optimal starting lineup. Phase 1 needs it for starter-slot awareness
(a third RB is worth a fraction of the first). Phase 5's trade finder needs the
identical function. It is built standalone and pure, never inlined into the board.

## Architecture

```
data.py     fetch + disk cache: players, crosswalk, projections, FFC ADP,
              league settings  → list[Player], ids resolved
value.py    PURE. scoring → VBD → tiers → survival → VONA → lineup_value.
              no I/O, no network
feeds.py    Protocol: get_picks() -> list[Pick]  |  SleeperFeed, YahooFeed
cli.py      poll → recompute → render text table → log
app.py      Dash (Phase 3), calls the same value.py
```

`value.py` holding all logic and zero I/O is the point: it is the part worth
testing, and it tests without a network.

**Dependencies: `requests`, `yfpy`, `dash`.** No pandas — the relevant pool is
about 560 skill players plus K/DEF, which is a list of dicts, and that is what
Dash's DataTable wants anyway. No scipy — survival is `statistics.NormalDist`
from the stdlib. No PyYAML — config is `config.toml`, read with stdlib `tomllib`
(Python 3.12).

### Multi-league support

The user has two leagues on two platforms, so this is a requirement, not
speculation — and it is cheap now and a rewrite later.

- `config.toml` holds a list of leagues (platform + id + optional overrides).
- Every function takes league context. **No module-level "current league" global.**
- Disk cache is keyed by league.
- SQLite log carries a `league_id` column.
- `cli.py` takes `--league`; Dash gets a dropdown.

### Settings auto-sync

Settings sync is independent of FFC. Sleeper `/league/{id}` returns
`scoring_settings`, `roster_positions`, and `num_teams`; Yahoo's settings
endpoint returns stat modifiers and roster slots. FFC's `teams` and `format`
parameters are *derived* from those (`num_teams: 12` + `rec: 1.0` →
`teams=12&format=ppr`).

Zero manual configuration by default, with a `config.toml` override for anything
the API gets wrong or the user wants to experiment with. Draft slot is always an
override (see `draft_order` above).

## Data flow

**Cold start** (once daily, cached to disk): fetch player DB, projections,
crosswalk, FFC ADP, and league settings. Three of the four join on integer IDs;
FFC is the only fuzzy join and is applied last as enrichment.

Output is one `list[Player]`: ids, name, pos, team, bye, `proj_pts` (already
scored against the league's settings), `adp`, `adp_stdev`, `injury_status`.

**Live loop** — the pick feed is the only network call inside it:

```python
picks = feed.get_picks()               # only network call in the loop
board = value.rank(pool - drafted, my_roster, pick_no, my_slot, settings)
render(board); log(board); sleep(interval)
```

Poll interval: 5s for Sleeper, **10–15s for Yahoo**. Yahoo's rate limits are
undocumented and enforced per registered app ID; with a 60–120s pick clock, 5s
polling buys nothing and risks a mid-draft block.

## Injury status

Among active skill players: 162 Questionable, 39 IR, 7 PUP, 2 DNR. Rotowire's
season-long projections do not reliably zero out a shelved player, so a player
projected for 250 points who is on PUP is a trap the board would otherwise
recommend. The field is present in both the player DB and the projections
payload. Phase 1, as a display flag.

## Draft-night failure handling

This decides whether the tool is useful at 7:04 PM on Sept 6.

1. **The loop never dies.** Poll wrapped, exception logged, `continue`.
2. **5-second timeout on every request.** A hung API must not freeze the render.
3. **Feed failure degrades, does not stop.** The board keeps rendering off the
   last known picks with a `⚠ FEED STALE 45s` banner. Stale advice you know is
   stale beats a traceback.
4. **Manual mark-drafted mode.** `--manual`, or available at any time: type a
   name and the player leaves the pool. This is what makes the degraded path
   operable rather than merely non-crashing, and it is the universal fallback —
   it covers the Yahoo adapter not being ready by Sept 1, any feed dying
   mid-draft, and platforms with no integration at all. Honest limit: nobody
   types all 180 picks while drafting, but only players near the top of the board
   matter, which is 20–30 entries over three hours.
5. **SQLite log every iteration** → restart resumes mid-draft.
6. **`preflight` command.** Fetches everything, validates all joins, prints
   unmatched FFC players, confirms auth, confirms the `draft_id` is reachable and
   roster settings parse. Run the morning of each draft. Highest-value
   operational feature in the build.

### SQLite draft log

Written from Phase 2, not deferred. Three payoffs: crash recovery mid-draft;
post-draft analysis of whether the tool's advice beat actual picks; and it *is*
the persistence layer season mode already requires — arriving already exercised
against real draft data rather than designed cold in October.

## Testing

`value.py` being pure makes this cheap — all logic tests with zero network.

**Bulk fixtures are not committed.** An earlier draft of this spec said to commit
captured live data, which directly contradicts the rule against committing
Rotowire projections to a public repo. Resolution:

- `value.py` tests use **synthetic players**. The engine is pure arithmetic and
  does not care whether the numbers are real.
- Two tests hardcode a **single real record inline** where realism is the point:
  Josh Allen's stat line for the scoring golden value, and the Bijan/Brian
  Robinson pair for the join regression. Two records is de minimis, not a
  redistribution of the dataset.
- Validation against the full live dataset happens in `preflight`, which runs
  against the network on purpose.

- **Bijan/Brian regression** — the join must not merge them. A real bug hit
  during design, not a hypothetical.
- **Custom scoring golden value** — Allen = 415.5 under 6-pt passing TDs.
- **Replacement level** — 12 teams × (2 RB + flex share) lands RB replacement
  where expected.
- **Survival monotonicity** — P(available) strictly decreases as pick number rises.
- **`lineup_value`** — the third RB adds less than the first.
- **Degenerate inputs** — empty pool, everyone drafted, missing `stdev`, null
  projections.

Integration test: a free Sleeper mock draft gives a real `draft_id` with live
moving picks, days before either real draft.

**Yahoo cannot be integration-tested before Sept 1.** Mock-lobby drafts are not
real leagues and do not expose a `league_key`. The only pre-draft Yahoo test is a
settings read plus an empty `draft_results` against the real league. This is why
Phase 2 targets Aug 29–30 with a deliberate buffer day.

### The Yahoo risk is confined to draft day

The risk is not that Yahoo is hard — it is that a draft is unrepeatable. In-season
Yahoo has none of those properties: weekly cadence rather than a 120-second clock,
a break on Tuesday fixed on Wednesday, and continuous testing against live data
with no deadline. Yahoo in-season is *lower* risk than Sleeper draft mode.

Two consequences. **Phase 0 is never wasted work** — the OAuth handshake is a
season-mode prerequisite regardless of what happens on Sept 1, and doing it now
means it is thoroughly exercised by the time season mode depends on it. And
**the tool is useful for the Yahoo draft even with no Yahoo feed**: projections,
custom scoring, VBD, tiers, ADP, and survival are all platform-independent. The
feed supplies only *who is already gone*, which manual mark-drafted mode covers.
The floor for Sept 1 is therefore a working board, not nothing.

One test file (`test_value.py`) plus `preflight`. No mocking of the network — the
pure core does not need it.

## Yahoo OAuth

Yahoo has no password flow. Setup is a one-time app registration at
`developer.yahoo.com/apps/create` (free, instant, no review, private) yielding a
Client ID and Secret, followed by a browser consent handshake.

| Field | Value |
| --- | --- |
| Application Name | `ff-helper` |
| Application Type | Installed Application |
| Redirect URI | `https://localhost:8080` |
| API Permissions | Fantasy Sports → Read |

The localhost redirect throws a certificate warning; that is expected. Access
tokens expire hourly, refresh tokens are long-lived, so the browser step happens
once.

Secrets live in `.env`, gitignored, never committed. The README documents
creating your own Yahoo app — the repo is public and tied to a job search.

Relatedly: Sleeper's projections endpoint is undocumented and the data is
Rotowire's. Fetch at runtime; **do not commit cached projections** to the public
repo. Same reasoning that ruled out FantasyPros.

## Phasing

| Phase | What | By |
| --- | --- | --- |
| **0** | Yahoo OAuth handshake; confirm league access, size, and settings | Aug 25 |
| **1** | `data.py` (disk cache, injury flags) + `value.py` (incl. `lineup_value`, ADP divergence flag) + `cli.py` (incl. manual mark-drafted), Sleeper feed, multi-league config | Aug 28 |
| **2** | Yahoo feed adapter (backoff, 10–15s poll) + SQLite draft log | **Aug 29–30** |
| **3** | Dash UI | Sept 5 |
| **3.5** | Opponent roster needs, bye clustering, on-the-clock notification, manual player overrides | Sept 5 |
| **4** | Season mode (`nflreadpy`) — *without* the waiver notify-bot | after |
| **5** | Trade finder — own spec | in-season |

Phase 1 builds against the Sleeper feed because it needs no auth and Sleeper mock
drafts are free — it is the test harness that de-risks the Yahoo adapter.

## Deferred, with reasons

- **Adding a second projection source.** ESPN does expose undocumented
  projection endpoints and `espn-api` exists, so this is real rather than
  impossible. Deferred for two reasons: fantasy projections correlate heavily
  (all built from pace, target share, and historical usage), so the ensemble gain
  is far smaller than in genuinely independent forecasting; and each source adds
  another entity-resolution surface. The ADP divergence flag captures most of the
  benefit at zero integration cost. FantasyPros stays out on price and ToU.
- **Playoff strength of schedule.** Weak predictive power in August.
- **Auto-pick.** Advice only. No tool drafts on the user's behalf.
- **Waiver notify-bot.** Dead on arrival given FAAB with scheduled processing.
- **Monte-Carlo draft simulation.** See "Recommendation engine" above.

## Phase 5 preview — trade finder

Recorded here so Phase 1 builds `lineup_value()` correctly; full design comes in
its own spec.

Verified available: `/league/{id}/rosters` (12 rosters with `players`,
`starters`, `reserve`); weekly projections for every week, so rest-of-season
value is a sum over remaining weeks (preseason projections are the wrong basis
for a week-9 trade); and `/league/{id}/transactions/{week}`.

Evaluation is `Δ(my ROS lineup_value)` and `Δ(their ROS lineup_value)`. Mutually
beneficial trades exist because lineup constraints create surplus, not because
someone is being fleeced. Search is brute force — 1-for-1 plus 2-for-1 across 11
opponents is roughly 17,000 combinations, milliseconds. No optimizer, no ML.

**"Likely to be accepted" will not be modelled as a probability.** Acceptance
depends on attention, name-brand bias, and stubbornness; a confident-looking
percentage would be dressing up a guess. Output is *"this improves both starting
lineups, and here is the argument."* Proposals are ranked by a data-backed prior
from transaction history — does this manager trade at all, how often, do they take
2-for-1s, are they still active — rather than by a fabricated acceptance score.

Neither platform's API allows submitting the offer. Proposals are sent by hand.
