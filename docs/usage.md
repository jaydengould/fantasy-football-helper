# Usage reference

The detail behind `README.md`'s quick start: config options, draft-night
mechanics, and what each season command prints and why.

## Configuration

### Choosing the ADP source

```toml
adp_source = "sleeper"   # or "ffc" (the code default)
```

Survival depends almost entirely on the accuracy of the ADP *mean*. Measured
across three 12-team mock drafts (540 picks), Sleeper's ADP predicted the room
roughly twice as well as FFC's, including in Yahoo rooms. FFC's calibration
spanned 24 points and was not monotonic; Sleeper's spanned 47 and rose in every
bucket. That is three drafts of one room type: rerun `scripts/calibrate.py` on
your own league before trusting it.

### A league without a platform API (Yahoo, ESPN, CBS)

Enter the settings by hand. Scoring keys follow Sleeper's stat naming. If the
league later gains API access, the API takes precedence with no config change.

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

For season commands, write one player name per line into `.roster/<league>.txt`
and the lineup is built from that file. `preflight` reports its path, player
count, and age.

### Tunables

```toml
[tunables]
tier_break_sigma = 1.0        # higher = fewer, coarser tiers
divergence_flag_slots = 10    # within-position rank gap that earns a flag
close_call_points = 3.0       # how big a gain must be to print (lineup/waivers/trades)
# playoff_weight = 1.5        # uncomment to weight playoff weeks up instead of down

[tunables.flex_share]         # how flex slots split across positions
RB = 0.5
WR = 0.5
TE = 0.0

[tunables.poll_seconds]       # floored at 1s to avoid API rate limiting
sleeper = 5
yahoo = 12
```

### Secrets

Only credentials belong in `.env` (gitignored). League ids are not secret and
live in `config.toml`.

```
YAHOO_CONSUMER_KEY=...
YAHOO_CONSUMER_SECRET=...
```

## Draft mode

### Web board

`/draft` in the web app. Click a row to mark that player drafted; your own roster
is derived from `draft_slot` and the pick number. On a league with no feed, a
per-row override corrects attribution when entry has drifted. Filter by position
(`FLEX` covers RB/WR/TE), search by name, and read the `TIER` badge, which is
coloured by position. A side panel shows your lineup slot by slot, then your
bench.

**Run one board at a time per league.** Both boards read the same
`.draft/<league>-<date>.jsonl` journal, but the terminal replays it only at
startup, so a terminal board left running beside the web board shows a stale
pool. Stopping one and starting the other loses nothing. Two leagues drafting at
once is fine; give the second web board its own `--port`.

### Manual entry

For a league with no feed, or if a feed dies mid-draft, type into the running
terminal board:

| Input | Effect |
| --- | --- |
| `gibbs` | mark Jahmyr Gibbs drafted by someone |
| `me nacua` | mark Puka Nacua drafted **by you** (counts toward your roster) |
| `-nacua` | take that mark back |
| `2` | choose the 2nd option when a name is ambiguous |
| `u` | undo the last change |
| `nacua, me chase, gibbs` | several at once |

Partial names, accents, and suffixes are handled (`pineiro` finds Eddy Piñeiro,
`harrison` finds Marvin Harrison Jr.). Ambiguous names always prompt: `robinson`
will not silently pick between Bijan and Brian.

Use `me` for your own picks. A plain mark only clears a player off the board;
`me` also feeds your roster, which MARG is measured against. `-` searches only
hand-typed marks, so a feed-reported pick can never be un-drafted. `u` restores
the exact prior state, and a no-op never consumes an undo.

### Crash recovery

Hand-typed marks are journalled to `.draft/<league>-<date>.jsonl` as they happen.
Restart and the board picks up where it left off, undo history included:

```
restored 87 mark(s) from /…/.draft/my-yahoo-league-2026-09-01.jsonl
  -> 87 drafted, 9 yours. Delete that file to start fresh.
```

The filename is dated so a mock never replays into a real draft. If the journal
can't be written the draft carries on without it.

### When the feed disagrees with you

If you claim a player the feed then reports from another seat, the claim is
dropped from your roster:

```
CLAIM OVERRULED: the feed says Puka Nacua was taken from seat 4, not yours --
dropped from your roster. Clear the stale claim with '-<name>'.
```

### Board flags and banners

`FLAGS` carries injury status, bye week, and `MODEL+n` / `MARKET+n` where the
projection and the market disagree by more than `divergence_flag_slots` places
within a position. A bye reads lowercase (`bye8`) until you already roster
someone at that position with the same bye, when it becomes `BYE8 CLASH`.

VONA is rounded to the displayed tenth before sorting and floored at zero, so the
order agrees with the numbers on screen and ties break on value.

Two banners replace the ranking when ranking would mislead:

- **`STARTING LINEUP FULL`**: no available player improves your lineup. The
  remaining order is bench value over replacement, with no model of upside or
  handcuffs.
- **`MANUAL MODE`** / **`FEED STALE 23s`**: no feed, or the feed stopped
  answering. The board keeps rendering the last known state and says so.

## Season mode

### Lineup

Prints your optimal starting lineup for the current week (`--week N` for
another), scored against your league's settings, then your bench.

- A player with no projection is listed separately, not scored as zero.
- A player who **cannot play** (Out, IR, PUP, suspended) is excluded and listed
  under `CANNOT PLAY`. Questionable and Doubtful still start.
- The official Wed–Fri practice report (nflverse) shows as `[Limited]` or
  `[DNP]`. The season's file appears once week 1 has been played.
- Once each defense has played three games, each row carries the opponent's rank in points allowed to that
  position under your scoring (1 = stingiest). It is a rank only: adjusting
  projections by it made them worse on 2024 and 2025.

Real output, week 6 of 2025 replayed:

```
  WR    Puka Nacua               WR  LAR   22.3  vs BAL soft 31/32  [Questionable]
  TE    Trey McBride             TE  ARI   14.8  vs IND tough 11/32
```

Every run for the current week records a snapshot into `season.db` (gitignored):
your roster and every startable player at each position, with what each source
claimed at that moment. The APIs serve current state only, so an unrecorded
week can never be scored later. Re-running replaces that week's snapshot; a run
for a past week writes nothing.

### Waivers

Ranks free agents by the gain to your starting lineup from an add-and-drop, over
this week and the rest of the season, after paying for it with your best cut.
Sleeper only: the pool is every player minus every roster.

A target must clear `close_call_points * sqrt(weeks)` to be listed. On a healthy
roster nothing usually does, and the board says so (real output, week 1):

```
WAIVERS -- bros-fantasy (jaydenpg) -- week 1
  waiver priority 8 of 12 -- a successful claim sends you to 12th

  nothing on the wire beats what you already have.
  (a target must gain more than the weekly projection error to be listed.)
```

Trending adds are shown beside a target when Sleeper has a count. They are
national, not your league.

### Trades

Searches every opponent's roster for the best 1-for-1, 2-for-1, and 2-for-2 that
clears the same floor on **both** sides, and prints the best offer per opponent.
`--player "name"` pins the search to one player and runs much faster. The full
sweep takes a few minutes, so the web page starts it from a button.

It never estimates whether the other manager will accept: that depends on
attention and stubbornness the data cannot see, and the league has no trade
history to learn from. Most pairs of rosters have nothing to trade, and an empty
or one-row board is a real result.

**Grading a received offer** (web `/trades`): pick the players you give and get.
The page answers **Accept**, **Decline**, or **Too close to call** from your
rest-of-season lineup gain, against the finder's floor. It shows any forced drop
and its cost, and when the drop is one of yours, the smaller ask that keeps him.
Offers are entered by hand because Sleeper's public API does not serve pending
offers.
