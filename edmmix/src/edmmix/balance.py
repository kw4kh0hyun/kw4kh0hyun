"""Stage 6: static balance from genre presets (+ optional reference matching, see reference.py)."""
from __future__ import annotations

from importlib import resources

import numpy as np
import yaml

from .dsp.util import rnd
from .roles import ROLES

ANCHOR_LUFS = -18.0     # internal working level of a role with target 0 LU (the kick)
MAX_GAIN_DB = 24.0


def list_presets() -> list[str]:
    return sorted(p.name[:-5] for p in resources.files("edmmix.presets").iterdir() if p.name.endswith(".yaml"))


def load_preset(genre: str) -> dict:
    if genre not in list_presets():
        raise ValueError(f"unknown genre {genre!r}; available presets: {', '.join(list_presets())}")
    text = resources.files("edmmix.presets").joinpath(f"{genre}.yaml").read_text(encoding="utf-8")
    preset = yaml.safe_load(text)
    missing = [r for r in ROLES if r not in preset.get("targets_lu", {})]
    if missing:
        raise ValueError(f"preset {genre!r} lacks targets_lu for: {', '.join(missing)}")
    return preset


def decide_gains(loudness: dict[str, float | None], roles: dict[str, str], preset: dict) -> dict[str, dict]:
    """Gain per stem so each role's summed loudness lands on its preset target.

    ``loudness`` is the integrated LUFS of each stem after stem processing
    (None for stems too quiet/short to measure).
    """
    counts: dict[str, int] = {}
    for name, role in roles.items():
        if loudness.get(name) is not None:
            counts[role] = counts.get(role, 0) + 1
    out = {}
    for name in sorted(roles):
        role = roles[name]
        measured = loudness.get(name)
        if measured is None:
            out[name] = {"gain_db": 0.0,
                         "reason": "loudness not measurable (silent or shorter than 0.4 s); gain left at 0 dB"}
            continue
        target_lu = float(preset["targets_lu"][role])
        share = 10.0 * np.log10(counts[role])
        gain = ANCHOR_LUFS + target_lu - share - measured
        clipped = float(np.clip(gain, -MAX_GAIN_DB, MAX_GAIN_DB))
        reason = (f"role '{role}' target {target_lu:+.1f} LU vs kick (preset '{preset['name']}'); "
                  f"measured {measured:.1f} LUFS")
        if counts[role] > 1:
            reason += f"; {counts[role]} stems share this role (-{share:.1f} dB each)"
        if clipped != gain:
            reason += f"; clamped from {gain:+.1f} dB"
        out[name] = {"gain_db": rnd(clipped, 2), "reason": reason}
    return out
