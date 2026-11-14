"""Stage 4: per-stem corrective processing (high-pass, resonance cuts, compression).

``decide_*`` functions choose parameters from measurements; ``apply`` runs the chain
from a parameter dict. Order: high-pass -> EQ -> compressor.
"""
from __future__ import annotations

import numpy as np
from scipy import signal

from . import analyze
from .dsp import filters
from .dsp.envelope import smooth_attack_release
from .dsp.oversample import downsample, upsample
from .dsp.util import db10, db20, f64, from_db, rnd

# Default high-pass corner per role (Hz). Kick/sub only lose infrasonics and DC.
ROLE_HIGHPASS_HZ = {
    "kick": 25.0, "sub": 20.0, "bass": 30.0, "snare_clap": 100.0, "hats_perc": 300.0,
    "lead": 120.0, "pad": 120.0, "pluck_arp": 150.0, "vocal": 90.0, "fx": 80.0,
}
MIN_HIGHPASS_HZ = 20.0

# role -> (crest factor above which we compress, attack ms, release ms). None = never compress.
ROLE_COMPRESSION = {
    "kick": None, "sub": None, "fx": None,
    "snare_clap": (16.0, 8.0, 80.0),
    "hats_perc": (18.0, 5.0, 60.0),
    "bass": (10.0, 15.0, 120.0),
    "lead": (10.0, 10.0, 150.0),
    "pad": (10.0, 30.0, 250.0),
    "pluck_arp": (14.0, 10.0, 120.0),
    "vocal": (9.0, 5.0, 120.0),
}
MAX_PEAK_REDUCTION_DB = 6.0

RESONANCE_RANGE_HZ = (250.0, 10000.0)
RESONANCE_MIN_EXCESS_DB = 8.0
RESONANCE_MAX_EXCESS_DB = 20.0     # anything taller is a pure tone, i.e. a note
RESONANCE_MAX_CUTS = 2
RESONANCE_MAX_CUT_DB = 6.0
NO_RESONANCE_ROLES = {"kick", "sub"}


# ----------------------------------------------------------------------------- high-pass

def decide_highpass(role: str, x: np.ndarray, sr: int, preset: dict | None = None) -> dict:
    default = float((preset or {}).get("highpass_hz", {}).get(role, ROLE_HIGHPASS_HZ[role]))
    centers, levels = analyze.third_octave_spectrum(x, sr)
    reason = f"role default for '{role}'"
    cutoff = default
    if np.max(levels) > -200.0:
        significant = centers[levels >= np.max(levels) - 30.0]
        lowest = float(significant[0])
        if 0.7 * lowest < default:
            cutoff = max(MIN_HIGHPASS_HZ, 0.7 * lowest)
            reason = (f"role default {default:g} Hz lowered: stem has significant energy down to the "
                      f"{lowest:.0f} Hz band, corner kept 30 % below it")
        else:
            reason += f"; lowest significant band is {lowest:.0f} Hz so nothing musical is removed"
    return {"enabled": True, "cutoff_hz": rnd(cutoff, 1), "order": 2, "reason": reason}


def apply_highpass(x: np.ndarray, sr: int, hp: dict) -> np.ndarray:
    if not hp.get("enabled"):
        return x
    return filters.apply_sos(x, filters.highpass_sos(float(hp["cutoff_hz"]), int(hp.get("order", 2)), sr))


# ----------------------------------------------------------------------------- resonance EQ

def _log_spectrum(x: np.ndarray, sr: int, f_lo: float, f_hi: float, per_octave: int = 48):
    """PSD averaged into 1/48-octave cells (dB), so narrow peaks are neither missed nor aliased."""
    freqs, p = analyze.psd(x, sr, nperseg=32768)
    df = freqs[1] - freqs[0]
    n_cells = int(np.floor(np.log2(f_hi / f_lo) * per_octave))
    edges = f_lo * 2.0 ** (np.arange(n_cells + 1) / per_octave)
    cumulative = np.concatenate([[0.0], np.cumsum(p)]) * df
    at_edges = np.interp(edges, np.concatenate([[0.0], freqs + 0.5 * df]), cumulative)
    density = np.diff(at_edges) / np.diff(edges)
    return np.sqrt(edges[:-1] * edges[1:]), db10(density), df


def detect_resonances(x: np.ndarray, sr: int) -> tuple[list[dict], str]:
    """Find narrow, isolated spectral bumps that stand out from a one-octave median baseline.

    Returns (peaks, note). Deliberately conservative: peaks taller than
    RESONANCE_MAX_EXCESS_DB are spectral lines (steady partials) and are ignored, and if the
    spectrum has more than RESONANCE_MAX_CUTS narrow peaks it is treated as a harmonic comb -
    those are notes, not resonances - and nothing is reported.
    """
    f_lo = RESONANCE_RANGE_HZ[0] / 2.0
    f_hi = min(RESONANCE_RANGE_HZ[1] * 2.0, 0.45 * sr)
    centers, spec, df = _log_spectrum(x, sr, f_lo, f_hi)
    if spec.max() < -200.0:
        return [], "silent stem"
    spec = np.convolve(np.pad(spec, 1, mode="edge"), np.ones(3) / 3.0, mode="valid")
    baseline = signal.medfilt(np.pad(spec, 24, mode="edge"), 49)[24:-24]
    excess = spec - baseline
    idx, _ = signal.find_peaks(excess, height=RESONANCE_MIN_EXCESS_DB, distance=16)
    widths = signal.peak_widths(excess, idx, rel_height=0.5)[0] if len(idx) else np.zeros(0)
    in_range = []
    narrow_peaks = 0
    for i in idx:
        if spec[i] < spec.max() - 40.0:
            continue                                    # too quiet to matter
        narrow_peaks += 1
        freq = float(centers[i])
        if excess[i] > RESONANCE_MAX_EXCESS_DB:
            continue                                    # a spectral line (steady partial), not a resonance
        if RESONANCE_RANGE_HZ[0] <= freq <= min(RESONANCE_RANGE_HZ[1], 0.4 * sr):
            in_range.append(i)
    if narrow_peaks > RESONANCE_MAX_CUTS:
        return [], (f"{narrow_peaks} narrow peaks found: spectrum is a harmonic comb "
                    "(notes, not resonances); no cuts")
    widths = signal.peak_widths(excess, in_range, rel_height=0.5)[0] if in_range else []
    candidates = []
    for i, width_cells in zip(in_range, widths):
        freq = float(centers[i])
        bandwidth_hz = freq * (2.0 ** (width_cells / 96.0) - 2.0 ** (-width_cells / 96.0))
        candidates.append({"freq_hz": freq, "excess_db": float(excess[i]),
                           "q": float(np.clip(freq / max(bandwidth_hz, 1e-9), 4.0, 12.0))})
    candidates.sort(key=lambda c: (-c["excess_db"], c["freq_hz"]))
    return candidates[:RESONANCE_MAX_CUTS], ""


def decide_eq(role: str, x: np.ndarray, sr: int) -> list[dict]:
    if role in NO_RESONANCE_ROLES:
        return []
    peaks, _ = detect_resonances(x, sr)
    bands = []
    for peak in sorted(peaks, key=lambda c: c["freq_hz"]):
        cut = float(np.clip(peak["excess_db"] - 4.0, 2.0, RESONANCE_MAX_CUT_DB))
        bands.append({
            "type": "peak", "freq_hz": rnd(peak["freq_hz"], 1), "gain_db": rnd(-cut, 1), "q": rnd(peak["q"], 1),
            "reason": (f"resonance: {peak['excess_db']:.1f} dB above the one-octave median spectrum at "
                       f"{peak['freq_hz']:.0f} Hz; narrow cut, capped at {RESONANCE_MAX_CUT_DB:g} dB"),
        })
    return bands


def apply_eq(x: np.ndarray, sr: int, bands: list[dict]) -> np.ndarray:
    return filters.apply_sos(x, filters.eq_sos(bands, sr))


# ----------------------------------------------------------------------------- compressor

def decide_compressor(role: str, x: np.ndarray, sr: int) -> dict:
    base = {"enabled": False, "threshold_db": 0.0, "ratio": 1.0, "attack_ms": 10.0, "release_ms": 100.0,
            "knee_db": 6.0, "makeup_db": 0.0, "oversample": 4}
    settings = ROLE_COMPRESSION[role]
    if settings is None:
        return {**base, "reason": f"role '{role}' is never compressed (dynamics are part of the sound)"}
    crest_limit, attack, release = settings
    base.update(attack_ms=attack, release_ms=release)
    peak = analyze.sample_peak_db(x)
    if peak < -120.0:
        return {**base, "reason": "silent stem"}
    rms = analyze.active_rms_db(x, sr)
    crest = peak - rms
    if crest <= crest_limit:
        return {**base, "reason": (f"crest factor {crest:.1f} dB is within the {crest_limit:g} dB limit "
                                   f"for '{role}': already controlled")}
    excess = crest - crest_limit
    ratio = float(np.clip(1.5 + excess / 4.0, 1.5, 4.0))
    reduction = min(excess, MAX_PEAK_REDUCTION_DB)
    threshold = max(peak - reduction / (1.0 - 1.0 / ratio), rms)
    base.update(enabled=True, threshold_db=rnd(threshold, 1), ratio=rnd(ratio, 1))
    return {**base, "reason": (f"crest factor {crest:.1f} dB exceeds the {crest_limit:g} dB limit for '{role}' "
                               f"by {excess:.1f} dB: aiming for about {reduction:.1f} dB reduction on peaks "
                               f"(peak {peak:.1f} dBFS, active RMS {rms:.1f} dBFS)")}


def gain_reduction_db(level_db: np.ndarray, threshold_db: float, ratio: float, knee_db: float) -> np.ndarray:
    """Static soft-knee compressor curve: positive dB of reduction for each input level."""
    slope = 1.0 - 1.0 / ratio
    over = level_db - threshold_db
    hard = slope * np.maximum(over, 0.0)
    if knee_db <= 0.0:
        return hard
    in_knee = np.abs(2.0 * over) <= knee_db
    soft = slope * (over + knee_db / 2.0) ** 2 / (2.0 * knee_db)
    return np.where(in_knee, soft, hard)


def compress(x: np.ndarray, sr: int, comp: dict) -> tuple[np.ndarray, dict]:
    """Feed-forward, stereo-linked peak compressor. The gain computer and the gain
    multiplication run at ``oversample`` x the sample rate to keep aliasing out of band."""
    if not comp.get("enabled"):
        return x, {"max_gain_reduction_db": 0.0}
    factor = int(comp.get("oversample", 4))
    n = x.shape[0]
    up = upsample(x, factor)
    level_db = db20(np.max(np.abs(up), axis=1))
    static = gain_reduction_db(level_db, float(comp["threshold_db"]), float(comp["ratio"]),
                               float(comp.get("knee_db", 6.0)))
    reduction = smooth_attack_release(static, float(comp["attack_ms"]), float(comp["release_ms"]), sr * factor)
    out = downsample(up * from_db(-reduction)[:, None], factor, n)
    out = out * float(from_db(comp.get("makeup_db", 0.0)))
    return out, {"max_gain_reduction_db": round(float(reduction.max()), 2)}


# ----------------------------------------------------------------------------- chain

def apply(x: np.ndarray, sr: int, sp: dict) -> tuple[np.ndarray, dict]:
    y = apply_highpass(f64(x), sr, sp["highpass"])
    y = apply_eq(y, sr, sp["eq"])
    return compress(y, sr, sp["compressor"])


def decide(role: str, x: np.ndarray, sr: int, preset: dict | None = None) -> dict:
    """Choose high-pass, EQ and compressor settings; each is decided on the output of the previous one."""
    x = f64(x)
    highpass = decide_highpass(role, x, sr, preset)
    y = apply_highpass(x, sr, highpass)
    eq = decide_eq(role, y, sr)
    y = apply_eq(y, sr, eq)
    return {"highpass": highpass, "eq": eq, "compressor": decide_compressor(role, y, sr)}
