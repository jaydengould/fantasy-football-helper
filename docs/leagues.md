# Leagues — settings, scoring, and what differs between them

Referenced from `CLAUDE.md`. Read this when computing a board, a lineup,
or anything that depends on scoring, roster shape, or replacement level.

| League | Config name | Platform | Draft | Format |
| --- | --- | --- | --- | --- |
| Bros with no hoes (`1395959490938966016`) | `bros-fantasy` | Sleeper | **DRAFTED 2026-09-01** | snake, 12 team, 15 rd, seat 5 |
| Yahoo league (id in `.env`) | `Bush-League` | Yahoo | **DRAFTED 2026-09-01** | snake, **10 team**, seat 2 |
| Sb Fantasy (`1401306086232834048`) | `sb-fantasy` | Sleeper | **DRAFTED 2026-09-06** | snake, **10 team**, 15 rd, seat 4 |

**Config names were changed 2026-09-06** from `sleeper-main` and `yahoo-main`.
The name is a key in three places, not one: `season.db.snapshot` (migrated, 15 and
14 rows), `.roster/<name>.txt` (renamed — it is the Yahoo league's ONLY roster
source), and `scripts/calibrate.py`'s parse of `.draft/` log filenames. Rename in
all four or week-1 history silently orphans.

**All three drafts are done.** Both Sleeper rosters read from the API; the Yahoo
roster has no API and must be hand-entered for season mode. The 2026 season starts
**Sept 9** (`state/nfl`), so week 1 lineups are the first live use of the tool
after the drafts.

Sleeper scoring: full PPR, 0.1/yd rush+rec, 0.04/yd pass, **6-pt passing TDs**
(not Sleeper's default 4). Roster `QB/RB/RB/WR/WR/TE/FLEX/FLEX/K/DEF` + 5 bench.

## Sb Fantasy (`sb-fantasy`) — added 2026-09-06

Settings sync from the Sleeper API, so nothing here is hand-entered. Roster
`QB/RB/RB/WR/WR/TE/FLEX/K/DEF` + 6 bench. Playoffs are 6 of 10 starting week 15.
Only **four** scoring values differ from `bros-fantasy` — everything else, full
PPR and 6-pt passing TDs included, is identical:

```
pass_yd 0.05 (1 per 20, vs 0.04)   pass_int -2 (vs -1)
fgmiss 0 (vs -1)                   xpmiss 0 (vs -1)
```

**Replacement levels:** QB10/RB25/WR25/TE10, at 375.9 / 170.6 / 209.0 / 169.3
points. Generated 2026-09-06 by running `replacement_ranks` against the synced
settings, not by hand.

**The structural difference is 10 teams and ONE flex, against 12 and two.**
Ranking the same player pool under both leagues' settings moves three of four
positions — overall board rank of each positional tier, `sb-fantasy` first:

| | 1st | 3rd | 5th | 8th | |
| --- | --- | --- | --- | --- | --- |
| QB | 17 / 25 | 37 / 55 | 46 / 67 | 62 / 85 | **8–23 earlier** |
| TE | 10 / 17 | 22 / 36 | 39 / 52 | 76 / 79 | **4–14 earlier** |
| WR | 3 / 3 | 13 / 9 | 20 / 16 | 25 / 21 | **4–7 later** |
| RB | 1 / 1 | 5 / 5 | 7 / 7 | 11 / 12 | unchanged |

So QB and TE gains come out of the RECEIVERS, not the backs: the league starts 20
WRs where the other starts 36, and elite RBs are worth the same in both. A second
consequence of ten teams — **K and DEF float up the board**, DEF1 to overall 52 and
K1 to 68 (against 66 and 94 in the 12-teamer). That is a shallow-league VBD
artifact, not a signal; both remain waiver fodder.

**UNCONFIRMED, must be read off Sleeper's own screen** (see `CLAUDE.md`'s first
recurring mistake): the API returns `max_keepers: 1` while league type reads
redraft and the draft ran 15 rounds, and `waiver_type: 0` with `waiver_budget: 100`
— which is rolling waiver priority with a default budget number, not FAAB.

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

