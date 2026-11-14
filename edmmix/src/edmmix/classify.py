"""Stage 2: stem role classification.

``Classifier`` is the seam for swapping in an ML model later: anything with a
``classify(name, audio, sr) -> RoleGuess`` method works. Manual assignments from
roles.json always win over the classifier.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import numpy as np

from .analyze import crest_factor_db, spectral_features
from .roles import ROLES


@dataclass
class RoleGuess:
    role: str
    confidence: float      # 0..1
    reason: str
    source: str            # "manual" | "filename" | "spectral"


class Classifier(Protocol):
    def classify(self, name: str, audio: np.ndarray, sr: int) -> RoleGuess: ...


# Checked in order; the first role with a matching keyword wins. Short keywords
# (<= 3 chars) must match a whole token, longer ones may match as a substring.
_KEYWORDS: list[tuple[str, list[str]]] = [
    ("kick", ["kick", "kik", "bd", "bassdrum", "bass drum"]),
    ("vocal", ["vocal", "vox", "voc", "voice", "adlib", "acapella", "choir", "chant"]),
    ("sub", ["sub"]),
    ("bass", ["bass", "808", "reese", "bs"]),
    ("snare_clap", ["snare", "clap", "snr", "sd", "rim", "snap"]),
    ("hats_perc", ["hat", "hats", "hihat", "hh", "ohh", "chh", "perc", "ride", "shaker", "cymbal",
                   "tops", "top", "tom", "conga", "bongo", "tamb"]),
    ("fx", ["fx", "sfx", "riser", "rise", "sweep", "impact", "downlifter", "uplifter", "whoosh",
            "noise", "crash", "atmos", "ambience", "foley"]),
    ("pluck_arp", ["pluck", "arp", "seq", "stab", "keys", "piano", "bell", "mallet", "chop"]),
    ("pad", ["pad", "string", "strings", "chord", "chords", "drone", "organ"]),
    ("lead", ["lead", "synth", "saw", "melody", "hook", "supersaw", "guitar"]),
]


def _match_filename(name: str) -> tuple[str, str] | None:
    lowered = name.lower()
    tokens = [t for t in re.split(r"[^a-z0-9]+", lowered) if t]
    # also split trailing digits: "kick01" -> "kick"
    tokens += [re.sub(r"\d+$", "", t) for t in tokens if re.search(r"[a-z]\d+$", t)]
    spaced = " ".join(tokens)
    for role, words in _KEYWORDS:
        for word in words:
            if len(word) <= 3:
                hit = word in tokens
            else:
                hit = word in lowered or word in spaced
            if hit:
                return role, word
    return None


class HeuristicClassifier:
    """File-name keywords first, spectral heuristics as fallback."""

    def classify(self, name: str, audio: np.ndarray, sr: int) -> RoleGuess:
        hit = _match_filename(name)
        if hit:
            return RoleGuess(hit[0], 0.9, f"file name contains '{hit[1]}'", "filename")
        return self.classify_spectral(audio, sr)

    def classify_spectral(self, audio: np.ndarray, sr: int) -> RoleGuess:
        feats = spectral_features(audio, sr)
        if feats["centroid_hz"] == 0.0:
            return RoleGuess("fx", 0.1, "silent stem; defaulting to fx", "spectral")
        crest = crest_factor_db(audio, sr)
        centroid, low, density, flat = (feats["centroid_hz"], feats["low_ratio"],
                                        feats["transient_density"], feats["flatness"])
        desc = (f"centroid {centroid:.0f} Hz, <120 Hz ratio {low:.2f}, "
                f"{density:.1f} transients/s, crest {crest:.1f} dB")
        if low > 0.5 and density >= 0.8 and crest > 9.0:
            role, conf = "kick", 0.6
        elif low > 0.8:
            role, conf = "sub", 0.6
        elif low > 0.3:
            role, conf = "bass", 0.5
        elif centroid > 5000.0 and density >= 1.5:
            role, conf = "hats_perc", 0.55
        elif density >= 0.8 and crest > 12.0 and flat > 0.05:
            role, conf = "snare_clap", 0.45
        elif centroid > 5000.0 and flat > 0.2:
            role, conf = "fx", 0.4
        elif density >= 3.0:
            role, conf = "pluck_arp", 0.4
        elif centroid < 1200.0 and density < 1.0:
            role, conf = "pad", 0.4
        else:
            role, conf = "lead", 0.35
        return RoleGuess(role, conf, f"spectral heuristic ({desc})", "spectral")


def load_roles_file(path: str | Path) -> dict[str, str]:
    """roles.json: {"<stem name or file name>": "<role>", ...}."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected a JSON object mapping stem names to roles")
    out = {}
    for key, role in data.items():
        if role not in ROLES:
            raise ValueError(f"{path}: unknown role {role!r} for {key!r}; valid roles: {', '.join(ROLES)}")
        out[Path(key).stem if key.lower().endswith(".wav") else key] = role
    return out


def classify_stems(stem_set, manual: dict[str, str] | None = None,
                   classifier: Classifier | None = None) -> dict[str, RoleGuess]:
    classifier = classifier or HeuristicClassifier()
    manual = manual or {}
    unknown = sorted(set(manual) - set(stem_set.names))
    if unknown:
        raise ValueError(f"roles.json refers to stems that are not in the folder: {', '.join(unknown)}")
    result = {}
    for stem in stem_set.stems:
        if stem.name in manual:
            result[stem.name] = RoleGuess(manual[stem.name], 1.0, "assigned in roles.json", "manual")
        else:
            result[stem.name] = classifier.classify(stem.name, stem.audio, stem.sample_rate)
    return result
