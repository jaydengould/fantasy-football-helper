"""Config loading. No league state lives at module level anywhere in this package."""
import tomllib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class League:
    name: str
    platform: str          # "sleeper" | "yahoo"
    league_id: str
    draft_slot: int | None = None    # 1-indexed; None means read from platform
    adp_format: str | None = None    # None means derive from league scoring
    adp_teams: int | None = None     # None means derive from league size
    settings: dict | None = None     # hand-entered [league.settings]; first-class, not a fallback
    # Manual override for the Sleeper roster_id the `lineup` command reads.
    # Mirrors draft_slot -- "must be a config override, never trusted from the
    # API" -- for the same reason: derivation (roster_id_for_slot, keyed off
    # draft_slot) depends on a draft that may be a mock, may have aged out of
    # the feed, or may not exist at all for a league joined mid-season. When
    # set, `_lineup` prefers it over derivation and says so on screen, because
    # a hand-set roster id that is wrong must not be silent.
    roster_id: int | None = None
    # Point the pick feed at a different draft than the one the league reports,
    # keeping that league's synced scoring and roster. This is what makes a
    # Sleeper MOCK draft usable as a rehearsal: a mock has a draft_id but no
    # league of its own, so its settings cannot be fetched -- borrow the real
    # league's and override only where the picks come from.
    draft_id: str | None = None
    # Which ADP the survival model believes: "ffc" (default) or "sleeper".
    #
    # This is the single biggest lever on survival accuracy. Measured against
    # the Task 13 mock, FFC ADP gave near-flat calibration (says 0-20% ->
    # 74% actually survived, says 80-100% -> 94%) while Sleeper ADP gave
    # 4/17/52/91/100 -- nearly perfect. That test is circular, since the mock's
    # CPU drafters pick off Sleeper's list, but it does establish that the model
    # FORM is sound and that only the ADP mean was wrong.
    #
    # There is no universally right answer, which is why this is a knob:
    #   - FFC's sample is exactly 12-team PPR 15-round on a rolling 7-day window,
    #     matching this league's shape.
    #   - Sleeper's `adp_ppr` is what leaguemates see in the app while drafting,
    #     but folds in TE-premium leagues (TEs run ~20 picks earlier).
    # QB and RB are near-identical between them; the disagreement is TE and WR.
    #
    # "yahoo" is NOT implemented: Yahoo's API exposes ADP via draft_analysis
    # (average_pick, average_round, average_cost, percent_drafted) and is the
    # right source for a Yahoo league once access is granted -- but access has
    # not arrived, so it cannot be built or tested. See TODO.
    adp_source: str = "ffc"


@dataclass(frozen=True)
class Tunables:
    tier_break_sigma: float = 1.0
    # Within-position rank gap that earns a MODEL+/MARKET+ flag. Was 25, tuned
    # for the old GLOBAL ranking whose kicker artifacts reached +399. Within
    # position the same real board tops out at +20, so 25 could never fire.
    # Measured over 300 top-20 rows of the Task 13 mock: 8 fires on 9% of rows,
    # 10 on 6%, 12 on 3%. 10 is about one flag per screenful. One draft's
    # evidence -- turn it if it feels noisy or silent.
    divergence_flag_slots: int = 10
    flex_share: dict[str, float] = field(
        default_factory=lambda: {"RB": 0.5, "WR": 0.5, "TE": 0.0}
    )
    poll_seconds: dict[str, int] = field(
        default_factory=lambda: {"sleeper": 5, "yahoo": 12}
    )
    # How close two players must be for a start/sit call to be worth printing.
    # A 30-point gap is not a decision and printing it buries the 1.5-point one
    # that is. 3.0 is a starting value, NOT a measured one -- it is expected to
    # move once backtest_weekly.py measures the real weekly projection error.
    close_call_points: float = 3.0


def load_config(path: Path) -> tuple[list[League], Tunables]:
    raw = tomllib.loads(Path(path).read_text())
    leagues = [League(**entry) for entry in raw.get("league", [])]
    tun_raw = raw.get("tunables", {})
    defaults = Tunables()
    # Scalar tunables: whole-value fallback (existing correct behavior).
    # Dict-valued tunables: per-key merge so partial edits inherit unspecified keys.
    flex_share_raw = tun_raw.get("flex_share", {})
    flex_share_merged = {**defaults.flex_share, **flex_share_raw}
    poll_seconds_raw = tun_raw.get("poll_seconds", {})
    poll_seconds_merged = {**defaults.poll_seconds, **poll_seconds_raw}
    tun = Tunables(
        tier_break_sigma=tun_raw.get("tier_break_sigma", defaults.tier_break_sigma),
        divergence_flag_slots=tun_raw.get("divergence_flag_slots", defaults.divergence_flag_slots),
        flex_share=flex_share_merged,
        poll_seconds=poll_seconds_merged,
        close_call_points=tun_raw.get("close_call_points", defaults.close_call_points),
    )
    return leagues, tun


def get_league(leagues: list[League], name: str) -> League:
    for lg in leagues:
        if lg.name == name:
            return lg
    raise KeyError(f"no league named {name!r}; have {[lg.name for lg in leagues]}")
