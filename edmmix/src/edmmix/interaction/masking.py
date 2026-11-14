"""Frequency masking between stems, resolved with side-chained dynamic EQ.

Detection: 1/3-octave spectra of every stem at its mix level are compared pairwise. Where
a lower-priority stem is loud in a band that matters to a higher-priority stem, the
lower-priority stem gets a dynamic cut in that band, keyed by the higher-priority stem -
it only ducks while the important stem is actually playing there.

Dynamic EQ: y = x - k(t) * BP(x). BP is a band-pass with unity gain and zero phase at its
centre, so the instantaneous response is a peaking cut of depth (1 - k) at the centre.
"""
from __future__ import annotations

import numpy as np

from .. import analyze
from ..dsp import filters
from ..dsp.envelope import smooth_attack_release
from ..dsp.util import db20, rnd, to_mono
from ..roles import priority

BAND_RANGE_HZ = (40.0, 10000.0)
MASKER_IMPORTANCE_DB = 12.0     # band must be within this of the masker's strongest band
COMPETING_MARGIN_DB = 6.0       # target counts as masking when within this of the masker's level
TARGET_RELEVANCE_DB = 20.0      # ... and the band is not negligible for the target itself
MAX_BANDS_PER_PAIR = 2
MAX_BANDS_PER_STEM = 4
MIN_CUT_DB, MAX_CUT_DB = 2.0, 6.0
DYN_EQ_Q = 2.0
THRESHOLD_BELOW_RMS_DB = 12.0
RANGE_DB = 12.0
ATTACK_MS, RELEASE_MS = 10.0, 120.0


def band_overlap(levels_a: np.ndarray, levels_b: np.ndarray, centers: np.ndarray) -> list[dict]:
    """Bands where stem b (lower priority) masks stem a (higher priority), best first."""
    in_range = (centers >= BAND_RANGE_HZ[0]) & (centers <= BAND_RANGE_HZ[1])
    if not in_range.any() or levels_a.max() < -150.0 or levels_b.max() < -150.0:
        return []
    top_a, top_b = levels_a.max(), levels_b.max()     # importance is judged against the whole spectrum
    hits = []
    for i in np.nonzero(in_range)[0]:
        la, lb = float(levels_a[i]), float(levels_b[i])
        if la >= top_a - MASKER_IMPORTANCE_DB and lb >= la - COMPETING_MARGIN_DB and lb >= top_b - TARGET_RELEVANCE_DB:
            hits.append({"index": int(i), "freq_hz": float(centers[i]),
                         "masker_db": la, "target_db": lb,
                         "score": (lb - la + COMPETING_MARGIN_DB) + 0.5 * (la - top_a + MASKER_IMPORTANCE_DB)})
    hits.sort(key=lambda h: (-h["score"], h["freq_hz"]))
    chosen: list[dict] = []
    for hit in hits:
        if all(abs(hit["index"] - c["index"]) >= 3 for c in chosen):      # at least an octave apart
            chosen.append(hit)
        if len(chosen) == MAX_BANDS_PER_PAIR:
            break
    return chosen


def detector_envelope_db(source_mono: np.ndarray, sr: int, band: dict) -> np.ndarray:
    sos = filters.bandpass_sos(float(band["freq_hz"]), float(band["q"]), sr)
    rectified = np.abs(filters.apply_sos(source_mono, sos))
    return db20(smooth_attack_release(rectified, float(band["attack_ms"]), float(band["release_ms"]), sr))


def cut_curve_db(source_mono: np.ndarray, sr: int, band: dict) -> np.ndarray:
    """Time-varying cut depth in dB (0 .. max_cut_db)."""
    env_db = detector_envelope_db(source_mono, sr, band)
    amount = np.clip((env_db - float(band["threshold_db"])) / max(float(band["range_db"]), 1e-6), 0.0, 1.0)
    return amount * float(band["max_cut_db"])


def apply_dynamic_eq(x: np.ndarray, source_mono: np.ndarray, sr: int, band: dict) -> tuple[np.ndarray, dict]:
    cut_db = cut_curve_db(source_mono, sr, band)
    k = 1.0 - 10.0 ** (-cut_db / 20.0)
    band_signal = filters.apply_sos(x, filters.bandpass_sos(float(band["freq_hz"]), float(band["q"]), sr))
    return x - k[:, None] * band_signal, {"source": band["source"], "freq_hz": band["freq_hz"],
                                          "max_cut_db": round(float(cut_db.max()), 2),
                                          "mean_cut_db": round(float(cut_db.mean()), 2)}


def decide(procs: dict[str, np.ndarray], gains_db: dict[str, float], roles: dict[str, str],
           sidechained: set[str], sr: int) -> dict[str, list[dict]]:
    """Dynamic-EQ bands per target stem. ``procs`` are stems after stem processing (pre-gain)."""
    names = sorted(procs)
    spectra = {}
    centers = analyze.third_octave_centers(sr)
    for name in names:
        _, levels = analyze.third_octave_spectrum(procs[name], sr)
        spectra[name] = levels + gains_db[name]

    found: dict[str, list[dict]] = {name: [] for name in names}
    for masker in names:
        for target in names:
            if priority(roles[masker]) >= priority(roles[target]):
                continue
            if roles[masker] == "kick" and target in sidechained:
                continue        # already handled by the side-chain
            for hit in band_overlap(spectra[masker], spectra[target], centers):
                found[target].append({**hit, "masker": masker})

    out: dict[str, list[dict]] = {name: [] for name in names}
    for target in names:
        hits = sorted(found[target], key=lambda h: (-h["score"], h["freq_hz"], h["masker"]))
        used: list[int] = []
        for hit in hits:
            if len(out[target]) == MAX_BANDS_PER_STEM:
                break
            if any(abs(hit["index"] - u) < 2 for u in used):
                continue        # that region of this stem is already being cut for another masker
            used.append(hit["index"])
            masker = hit["masker"]
            band = {"source": masker, "freq_hz": rnd(hit["freq_hz"], 1), "q": DYN_EQ_Q,
                    "max_cut_db": rnd(np.clip(MIN_CUT_DB + 0.5 * (hit["target_db"] - hit["masker_db"]
                                                                 + COMPETING_MARGIN_DB), MIN_CUT_DB, MAX_CUT_DB), 1),
                    "threshold_db": 0.0, "range_db": RANGE_DB, "attack_ms": ATTACK_MS, "release_ms": RELEASE_MS}
            source_band = filters.apply_sos(to_mono(procs[masker]), filters.bandpass_sos(band["freq_hz"], DYN_EQ_Q, sr))
            band["threshold_db"] = rnd(analyze.active_rms_db(source_band, sr) - THRESHOLD_BELOW_RMS_DB, 1)
            band["reason"] = (
                f"masking: '{target}' ({roles[target]}) is {hit['target_db'] - hit['masker_db']:+.1f} dB relative to "
                f"'{masker}' ({roles[masker]}, higher priority) in the {hit['freq_hz']:.0f} Hz band, which is "
                f"one of {masker}'s main bands; cut only while {masker} is active there")
            out[target].append(band)
        out[target].sort(key=lambda b: (b["freq_hz"], b["source"]))
    return out
