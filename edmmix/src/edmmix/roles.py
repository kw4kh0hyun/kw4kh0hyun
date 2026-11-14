"""Role vocabulary, bus grouping and masking priority."""
from __future__ import annotations

ROLES = ["kick", "snare_clap", "hats_perc", "sub", "bass", "lead", "pad", "pluck_arp", "vocal", "fx"]

BUSES = ["drums", "bass", "synths", "vocals", "fx"]

ROLE_TO_BUS = {
    "kick": "drums", "snare_clap": "drums", "hats_perc": "drums",
    "sub": "bass", "bass": "bass",
    "lead": "synths", "pad": "synths", "pluck_arp": "synths",
    "vocal": "vocals",
    "fx": "fx",
}

# Lower number = higher priority when two stems fight for the same band.
MASKING_PRIORITY = {"kick": 0, "sub": 1, "vocal": 2, "lead": 3}
LOWEST_PRIORITY = 4


def priority(role: str) -> int:
    return MASKING_PRIORITY.get(role, LOWEST_PRIORITY)
