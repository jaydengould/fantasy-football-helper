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


@dataclass(frozen=True)
class Tunables:
    tier_break_sigma: float = 1.0
    divergence_flag_slots: int = 25
    flex_share: dict[str, float] = field(
        default_factory=lambda: {"RB": 0.5, "WR": 0.5, "TE": 0.0}
    )
    poll_seconds: dict[str, int] = field(
        default_factory=lambda: {"sleeper": 5, "yahoo": 12}
    )


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
    )
    return leagues, tun


def get_league(leagues: list[League], name: str) -> League:
    for lg in leagues:
        if lg.name == name:
            return lg
    raise KeyError(f"no league named {name!r}; have {[lg.name for lg in leagues]}")
