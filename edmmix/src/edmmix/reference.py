"""Reference-track tone matching (stage 6, optional).

The reference is only *measured* (broad-band balance of its long-term spectrum); it is
never resampled or mixed in. Bus gains and one shared five-band EQ (applied to every bus,
which is equivalent to a mix EQ but keeps stems == premaster) are fitted by bounded least
squares on the bus power spectra, then verified on the real render by QC.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import soundfile as sf
from scipy import optimize

from . import analyze
from .analyze import BROAD_BANDS
from .dsp import filters
from .dsp.util import db10, rnd
from .interaction import buses

MAX_BUS_GAIN_DB = 3.0
MAX_EQ_GAIN_DB = 3.0
REGULARISATION = 0.1            # pulls every correction towards 0 dB
MIN_BAND_LEVEL_DB = -70.0       # bands emptier than this (re total) are not matched

# One band per broad band; identical on every bus.
EQ_TEMPLATE = [
    {"type": "low_shelf", "freq_hz": 60.0, "q": 0.707},
    {"type": "peak", "freq_hz": 120.0, "q": 0.7},
    {"type": "peak", "freq_hz": 700.0, "q": 0.5},
    {"type": "peak", "freq_hz": 3500.0, "q": 0.8},
    {"type": "high_shelf", "freq_hz": 6000.0, "q": 0.707},
]


def load_reference(path: str | Path) -> tuple[np.ndarray, int]:
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"reference file not found: {path}")
    audio, sr = sf.read(str(path), dtype="float64", always_2d=True)
    if not np.any(audio):
        raise ValueError(f"reference file is silent: {path}")
    return audio[:, :2], int(sr)


def _eq_bands(gains_db) -> list[dict]:
    return [{**template, "gain_db": rnd(g, 2)} for template, g in zip(EQ_TEMPLATE, gains_db)]


def _balance(freqs: np.ndarray, p: np.ndarray) -> np.ndarray:
    rel = analyze.relative_balance(analyze.broad_band_levels_from_psd(freqs, p))
    return np.array([rel[name] for name, _, _ in BROAD_BANDS])


def decide(pre_bus_stems: dict[str, np.ndarray], params: dict, sr: int, reference_path: str | Path) -> tuple[dict, dict]:
    """Returns (buses params, report info)."""
    ref_audio, ref_sr = load_reference(reference_path)
    ref_freqs, ref_psd = analyze.psd(ref_audio, ref_sr)
    target = _balance(ref_freqs, ref_psd)

    sums = buses.bus_sums(pre_bus_stems, params)
    bus_names = sorted(sums)
    freqs = None
    psds = []
    for bus in bus_names:
        freqs, p = analyze.psd(sums[bus], sr)
        psds.append(p)
    psds = np.array(psds)
    n_bus = len(bus_names)

    def predicted(x: np.ndarray) -> np.ndarray:
        total = (10.0 ** (x[:n_bus, None] / 10.0) * psds).sum(axis=0)
        response = filters.sos_power_response(filters.eq_sos(
            [{**t, "gain_db": float(g)} for t, g in zip(EQ_TEMPLATE, x[n_bus:])], sr), freqs, sr)
        return _balance(freqs, total * response)

    before = predicted(np.zeros(n_bus + len(EQ_TEMPLATE)))
    usable = (target > MIN_BAND_LEVEL_DB) & (before > MIN_BAND_LEVEL_DB)

    def residuals(x: np.ndarray) -> np.ndarray:
        return np.concatenate([(predicted(x) - target)[usable], REGULARISATION * x])

    bounds = np.array([MAX_BUS_GAIN_DB] * n_bus + [MAX_EQ_GAIN_DB] * len(EQ_TEMPLATE))
    fit = optimize.least_squares(residuals, np.zeros(bounds.shape[0]), bounds=(-bounds, bounds), method="trf")
    x = np.round(fit.x, 2)
    after = predicted(x)

    band_names = [name for name, _, _ in BROAD_BANDS]
    def as_dict(values):
        return {name: round(float(v), 2) for name, v in zip(band_names, values)}

    deviation_before = float(np.sqrt(np.mean((before - target)[usable] ** 2)))
    deviation_after = float(np.sqrt(np.mean((after - target)[usable] ** 2)))
    summary = (f"band balance deviation from reference: {deviation_before:.2f} dB RMS before, "
               f"{deviation_after:.2f} dB RMS predicted after (bus gains within +/-{MAX_BUS_GAIN_DB:g} dB, "
               f"EQ within +/-{MAX_EQ_GAIN_DB:g} dB)")
    eq = _eq_bands(x[n_bus:])
    out = {}
    for bus in params["buses"]:
        if bus in bus_names:
            gain = float(x[bus_names.index(bus)])
            out[bus] = {"gain_db": rnd(gain, 2), "eq": [dict(b) for b in eq],
                        "reason": f"reference match to '{Path(reference_path).name}': {summary}"}
        else:
            out[bus] = {"gain_db": 0.0, "eq": [], "reason": "no stems on this bus"}
    info = {
        "file": str(reference_path),
        "sample_rate": ref_sr,
        "integrated_lufs": round(float(analyze.integrated_lufs(ref_audio, ref_sr)), 2),
        "band_balance_db": as_dict(target),
        "mix_band_balance_before_db": as_dict(before),
        "mix_band_balance_predicted_db": as_dict(after),
        "bands_matched": [n for n, u in zip(band_names, usable) if u],
        "bus_gains_db": {bus: out[bus]["gain_db"] for bus in bus_names},
        "shared_bus_eq": eq,
        "rms_deviation_before_db": round(deviation_before, 3),
        "rms_deviation_predicted_db": round(deviation_after, 3),
        "summary": summary,
    }
    return out, info
