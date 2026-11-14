"""Bus grouping: drums / bass / synths / vocals / fx.

Buses carry only linear processing (gain + EQ) so that processed stems still sum exactly
to the premaster; see pipeline.apply_bus.
"""
from __future__ import annotations

import numpy as np

from ..roles import BUSES


def members(params: dict) -> dict[str, list[str]]:
    groups: dict[str, list[str]] = {bus: [] for bus in params["buses"]}
    for name in sorted(params["stems"]):
        groups[params["stems"][name]["bus"]].append(name)
    return groups


def bus_sums(stems: dict[str, np.ndarray], params: dict) -> dict[str, np.ndarray]:
    """Sum of member stems per non-empty bus (fixed order)."""
    out = {}
    for bus, names in members(params).items():
        if names:
            total = np.zeros_like(stems[names[0]])
            for name in names:
                total += stems[name]
            out[bus] = total
    return out


__all__ = ["BUSES", "members", "bus_sums"]
