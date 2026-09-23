# Yahoo roster editor on /lineup

Written 2026-09-23. Brainstormed with the user the same day; the user waived
spec review and asked for the build to follow directly.

**Authority:** `CLAUDE.md` wins where this disagrees with it.

## What this is for

Yahoo has no API access (Phase 0, blocked since 2026-08-24), so
`.roster/<league>.txt` IS the Yahoo roster. Every add/drop in Yahoo means
opening that file by hand. This lets the user mirror a Yahoo add/drop from the
Lineup page instead. The transaction still happens in Yahoo first; this app
never writes to Yahoo.

The optimizer is unchanged. The file is an unordered roster; `optimal_lineup()`
decides who starts. The user adds players to the *roster*, never to a slot --
a user-chosen slot would be a second lineup rule able to disagree with the
first.

## Settled facts

- **Bush-League has no IR** (read off Yahoo's settings by the user,
  2026-09-23). Capacity is `sum(roster_slots) + bench` = 9 + 5 = **14**.
- **Name round-trip fails for real players.** Measured 2026-09-23 over the full
  pool (3,232 players, every one, not a sample): writing a player's full name
  and re-reading it through `find_players` fails for 37 names, 5 of them on an
  NFL team today -- Ian Thomas (LV, also matches Brian Thomas), Josh Johnson
  (CIN), Nick Williams (DEN), David Moore (CAR), Frank Gore (BUF). A name-only
  writer would make those five un-addable. This is why the writer writes IDs.

## Design

### File format (`cli.py`)

- A line whose first token is a pool key (Sleeper `player_id`) resolves **by
  ID**; the rest of the line is a human label and is ignored. Any other line is
  a name and resolves as before. Existing hand-written files keep working.
- `add_to_roster_file(path, player)` appends `<id>  <name>`. Refuses a player
  already on the roster.
- `remove_from_roster_file(path, player_id, pool)` rewrites the file without
  every line resolving to that player -- by ID or by unique name, since today's
  file is all names. Comments and all other lines are kept verbatim.
- Both write a temp file and `os.replace` it: a crash mid-write cannot leave a
  half-roster.

### UI (`app.py`, `/lineup`, only when `platform != "sleeper"`)

The same branch `cli._resolve_my_roster` uses to read the file.

- Every player row in Starters, Bench, No projection and Cannot play gets a
  **Drop** button -> `dcc.ConfirmDialog` ("Drop X from <league>?") -> write ->
  page reload, so the lineup recomputes from the new roster.
- When the roster has fewer than 14 entries, an **Add player** card appears: a
  searchable `dcc.Dropdown` ("Name (POS TEAM)") of pool players on an NFL team
  and not already rostered, plus an Add button -> write -> reload.
- **Capacity counts entries in the file, not resolved players.** An ambiguous
  hand-typed line is still a player the user really rosters; counting only
  resolved players would open the search and permit a 15th. Unresolved lines
  stay as notes, with no Drop button; the user fixes them by hand.
- A reload re-renders `/lineup`, which re-records the week's snapshot
  (`INSERT OR REPLACE`). That is the snapshot's meaning -- the last look before
  kickoff -- so a mid-week roster change correctly replaces the row.

### Errors

A failed write is shown on the page and logged; the app never dies.

### Testing

- ID line resolves Ian Thomas where his name is ambiguous (the measured
  failure, reproduced in the fixture).
- Remove drops ID and legacy name lines, keeps comments.
- Add refuses a duplicate.
- Capacity counts entries.
- Drop/Add are absent for a Sleeper league, present for Yahoo.
- The add list excludes the user's roster and teamless players.
- Each shown failing first via `git stash push -u -- ffhelper`; mutations added
  to `scripts/mutate.py` for the ID branch and the capacity check. Tests point
  `ROSTER_DIR` at `tmp_path`, as the existing ones do.

## Out of scope

Slot choice, IR, Yahoo sync, a "remove this unresolved line" button.
