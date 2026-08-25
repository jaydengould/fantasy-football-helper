# fantasy-football-helper

A live draft assistant that answers the question a printed cheat sheet cannot:
**what will not survive until my next pick?**

Most draft tools rank players by value. This one ranks by *cost of waiting*. If
three running backs of equal tier will still be available 19 picks from now and
only one tight end will be, the board says take the tight end — even though the
running backs score higher.

## Status

Draft mode is complete and tested against live data. Season mode and a web UI are
planned but not built.

| Capability | State |
| --- | --- |
| Projections scored against your league's real rules | working |
| VBD, tiers, survival probability, VONA | working |
| Optimal-lineup marginal value | working |
| Live Sleeper draft feed | working |
| Manual pick entry (any platform, no feed needed) | working |
| Terminal board with auto-refresh | working |
| Yahoo API feed | blocked on Yahoo developer approval |
| Web dashboard, season mode, trade finder | planned |

## Requirements

Python 3.12+. Two runtime dependencies: `requests` and `yfpy`.

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

## Configuration

Everything lives in `config.toml`. Copy the example league blocks and edit.

### A league with a platform API (Sleeper)

Settings sync automatically — scoring, roster slots, team count, and draft id are
read from the platform.

```toml
[[league]]
name = "my-sleeper-league"
platform = "sleeper"
league_id = "1234567890"      # the number in your league URL
draft_slot = 3                 # your draft position, 1-indexed
```

`draft_slot` is deliberately manual. Draft order is often not final until the
draft starts, and a wrong slot silently corrupts every survival number — so the
tool never guesses it.

### A league without a platform API (Yahoo, ESPN, CBS, anywhere)

Enter the settings by hand. **This is a first-class path, not a workaround** —
Yahoo requires per-developer API approval that can be denied, ESPN has no official
API, and most people will use the tool this way.

```toml
[[league]]
name = "my-yahoo-league"
platform = "yahoo"
league_id = "123456"
draft_slot = 4

  [league.settings]
  num_teams = 10
  bench = 5
  roster_slots = { QB = 1, RB = 2, WR = 2, TE = 1, FLEX = 2, K = 1, DEF = 1 }

  [league.settings.scoring]
  pass_cmp = 0.25
  pass_yd  = 0.04
  pass_td  = 6
  pass_int = -2
  rush_yd  = 0.1
  rush_td  = 6
  rec      = 0.5
  rec_yd   = 0.1
  rec_td   = 6
  fum_lost = -2
```

Scoring keys follow Sleeper's stat naming. A platform API, where one exists, takes
precedence over this block — so a league that later gains API access starts
syncing with no config change.

### Tunables

```toml
[tunables]
tier_break_sigma = 1.0        # higher = fewer, coarser tiers
divergence_flag_slots = 25    # flag when model and market disagree by this much

[tunables.flex_share]         # how flex slots split across positions
RB = 0.5
WR = 0.5
TE = 0.0

[tunables.poll_seconds]       # floored at 1s to avoid API rate limiting
sleeper = 5
yahoo = 12
```

### Secrets

Only credentials belong in `.env` — league ids are not secret and live in
`config.toml`.

```
YAHOO_CONSUMER_KEY=...
YAHOO_CONSUMER_SECRET=...
```

`.env` is gitignored. Do not commit it.

## Usage

### Before the draft

```bash
.venv/bin/python -m ffhelper.cli preflight --league my-sleeper-league
```

Fetches every source, validates all joins, reports unmatched players, confirms the
feed is reachable, and warns if `draft_slot` is unset. **Run this the morning of
your draft**, not five minutes before.

### During the draft

```bash
.venv/bin/python -m ffhelper.cli run --league my-sleeper-league
```

The board refreshes automatically. If the feed drops, it keeps rendering the last
known state behind a `FEED STALE` banner rather than dying.

### Manual entry

For a league with no feed — or if a feed dies mid-draft — type into the running
board:

| Input | Effect |
| --- | --- |
| `gibbs` | mark Jahmyr Gibbs drafted by someone |
| `me nacua` | mark Puka Nacua drafted **by you** (counts toward your roster) |
| `2` | choose the 2nd option when a name is ambiguous |
| `u` | undo the last mark |

Partial names work, accents and suffixes are handled (`pineiro` finds Eddy
Piñeiro, `harrison` finds Marvin Harrison Jr.). **Ambiguous names always prompt** —
typing `robinson` will not silently pick between Bijan and Brian.

## Reading the board

```
#   PLAYER              POS     VONA     VBD    MARG TIER   SURV   DIV  FLAGS
1   Brock Bowers        TE      36.9    91.0   253.5    1     7%    -2  bye13
12  D'Andre Swift       RB       1.0   124.2   208.0    1    48%   +17  bye10
```

| Column | Meaning |
| --- | --- |
| **VONA** | What you lose by waiting. **The board sorts by this.** Negative means waiting is strictly better. |
| **VBD** | Points above a replacement-level player at that position |
| **MARG** | How much this player improves your *starting lineup* — a third RB is worth less than a first |
| **TIER** | Players in a tier are roughly interchangeable |
| **SURV** | Probability of still being available at your next pick |
| **DIV** | Projection rank minus market rank. A flag, never blended into the score. |

Swift above is the whole point: the highest VBD on screen, but VONA of 1.0 — he
has a 48% chance of lasting to your next pick, so spending this pick on him costs
you the tight end you cannot get back.

## Data sources

- **Sleeper API** — player database, projections, ADP, live draft picks. Free, no
  auth. Projection data is provided by Rotowire via Sleeper; it is fetched at
  runtime and never redistributed with this repository.
- **FantasyFootballCalculator ADP** — per-player ADP standard deviation, which no
  other free source publishes and which the survival math depends on.
  *ADP data courtesy of [Fantasy Football Calculator](https://fantasyfootballcalculator.com).*
- **DynastyProcess player IDs** — cross-platform ID crosswalk. Required because
  Sleeper's own `yahoo_id` is unpopulated for every rookie and most second-year
  players.

## Design notes

**Player identity joins on integer IDs, never names.** Bijan Robinson and Brian
Robinson are both running backs on Atlanta; a name join silently merges them and
every downstream number becomes quietly wrong. FFC is the one source with no
cross-platform id, so it is confined to a final, non-load-bearing enrichment step
that reports unmatched and ambiguous names instead of guessing.

**Projection rank and market rank are never averaged.** A board that tracks
consensus produces consensus results. The disagreement is surfaced as a flag for
you to judge.

**Degrade, never fabricate.** Unknown draft slot, unreachable feed, ambiguous
name, missing settings — each produces a visible, labelled degradation rather than
a plausible guess.

## Development

```bash
.venv/bin/pytest          # 144 tests, no network, runs in ~0.15s
```

`ffhelper/value.py` is pure — no I/O, no network, no module state — so the entire
ranking engine tests without a network.

## License and attribution

Personal project. ADP data courtesy of
[Fantasy Football Calculator](https://fantasyfootballcalculator.com). Projections
via Sleeper (Rotowire). Player ID crosswalk from
[DynastyProcess](https://github.com/dynastyprocess/data).
