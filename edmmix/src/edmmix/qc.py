"""Stage 8: quality control on the rendered premaster. Produces metrics and warnings."""
from __future__ import annotations

import numpy as np

from . import analyze
from .analyze import BROAD_BANDS
from .dsp.util import db10, db20, f64, finite_or_none

MONO_LOSS_WARN_DB = {"sub": 1.5, "low": 1.5, "mid": 4.0, "high_mid": 4.5, "high": 4.5}
DC_WARN = 1e-3                  # -60 dBFS
CLIP_LEVEL = 0.999
TRUE_PEAK_MARGIN_DB = 1.5       # allowed inter-sample overshoot above the sample-peak target
PEAK_TOLERANCE_DB = 0.05
NULL_LIMIT_DB = -90.0
REFERENCE_DEVIATION_WARN_DB = 3.0


def mono_compatibility(x: np.ndarray, sr: int) -> dict[str, float]:
    """Per-band level lost when the mix is summed to mono (dB, positive = loss)."""
    x = f64(x)
    freqs, p_stereo = analyze.psd(x, sr)
    _, p_mono = analyze.psd(x.mean(axis=1), sr)
    out = {}
    for name, lo, hi in BROAD_BANDS:
        stereo_p = analyze.band_power(freqs, p_stereo, lo, hi)
        mono_p = analyze.band_power(freqs, p_mono, lo, hi)
        out[name] = 0.0 if stereo_p <= 1e-20 else round(float(db10(stereo_p) - db10(mono_p)), 2)
    return out


def null_test(premaster_q: np.ndarray, stems_q: dict[str, np.ndarray]) -> dict:
    """Residual of (sum of written stems) - (written premaster), on the 24-bit integer data."""
    total = np.zeros(premaster_q.shape, dtype=np.int64)
    for name in sorted(stems_q):
        total += stems_q[name]
    residual = (total - premaster_q).astype(np.float64) / float(2 ** 23)
    return {"residual_peak_dbfs": round(float(db20(np.max(np.abs(residual)))), 2),
            "residual_rms_dbfs": round(float(db10(np.mean(residual ** 2))), 2)}


def run_qc(premaster: np.ndarray, sr: int, target_peak_dbfs: float,
           stems: dict[str, np.ndarray] | None = None, null: dict | None = None,
           reference_balance: dict[str, float] | None = None) -> dict:
    """``premaster``/``stems`` are the float versions of what was written to disk."""
    x = f64(premaster)
    warnings: list[str] = []
    silent = not np.any(x)

    sample_peak = analyze.sample_peak_db(x)
    true_peak = analyze.true_peak_db(x)
    lufs = analyze.integrated_lufs(x, sr)
    st = analyze.short_term_lufs(x, sr)
    corr = analyze.stereo_correlation(x)
    dc = analyze.dc_offset(x)
    clipped = int(np.count_nonzero(np.abs(x) >= CLIP_LEVEL))
    mono_loss = mono_compatibility(x, sr)
    balance = {k: round(v, 2) for k, v in analyze.broad_band_balance(x, sr).items()} if not silent else {}

    if silent:
        warnings.append("premaster is silent")
    else:
        if abs(sample_peak - target_peak_dbfs) > PEAK_TOLERANCE_DB:
            warnings.append(f"sample peak {sample_peak:.2f} dBFS deviates from the "
                            f"{target_peak_dbfs:.1f} dBFS target (mixbus gain_mode is probably 'fixed')")
        if true_peak > target_peak_dbfs + TRUE_PEAK_MARGIN_DB:
            warnings.append(f"true peak {true_peak:.2f} dBTP is more than {TRUE_PEAK_MARGIN_DB} dB above "
                            "the sample-peak target (strong inter-sample peaks)")
        if clipped:
            warnings.append(f"{clipped} premaster samples at or above {CLIP_LEVEL} full scale (clipping)")
        if corr < 0.0:
            warnings.append(f"overall stereo correlation is negative ({corr:.2f}): mix will thin out in mono")
        elif corr < 0.2:
            warnings.append(f"overall stereo correlation is low ({corr:.2f}): check mono playback")
        for band, loss in mono_loss.items():
            if loss > MONO_LOSS_WARN_DB[band]:
                warnings.append(f"mono compatibility: '{band}' band loses {loss:.1f} dB when summed to mono")
        for ch, value in zip("LR", dc):
            if abs(value) > DC_WARN:
                warnings.append(f"DC offset on {ch} channel: {value:+.5f} ({db20(abs(value)):.1f} dBFS)")
        if reference_balance:
            for band, ref in reference_balance.items():
                dev = balance.get(band, ref) - ref
                if abs(dev) > REFERENCE_DEVIATION_WARN_DB:
                    warnings.append(f"tone balance: '{band}' band is {dev:+.1f} dB vs reference")
        else:
            lows = db10(10 ** (balance["sub"] / 10) + 10 ** (balance["low"] / 10))
            if lows < -12.0:
                warnings.append(f"tone balance: low end (<250 Hz) is only {lows:.1f} dB of the total - thin mix")
            if balance["high"] > -6.0:
                warnings.append(f"tone balance: >6 kHz band is {balance['high']:.1f} dB of the total - harsh/bright mix")

    stem_clips = {}
    for name in sorted(stems or {}):
        count = int(np.count_nonzero(np.abs(stems[name]) >= CLIP_LEVEL))
        if count:
            stem_clips[name] = count
            warnings.append(f"processed stem '{name}' reaches full scale ({count} samples): "
                            "it was clipped on export and the stem sum no longer nulls")
    if null is not None and null["residual_peak_dbfs"] > NULL_LIMIT_DB:
        warnings.append(f"null test failed: stems sum differs from premaster by "
                        f"{null['residual_peak_dbfs']:.1f} dBFS peak (limit {NULL_LIMIT_DB:.0f})")

    return {
        "sample_peak_dbfs": finite_or_none(sample_peak),
        "target_peak_dbfs": target_peak_dbfs,
        "true_peak_dbtp": finite_or_none(true_peak),
        "integrated_lufs": finite_or_none(lufs),
        "short_term_lufs_max": finite_or_none(st.max()) if st.size else None,
        "crest_factor_db": finite_or_none(analyze.crest_factor_db(x, sr)) if not silent else None,
        "stereo_correlation": round(corr, 4),
        "mono_compatibility_loss_db": mono_loss,
        "band_balance_db": balance,
        "reference_band_balance_db": reference_balance,
        "dc_offset": [round(v, 7) for v in dc],
        "clipped_samples": clipped,
        "clipped_stems": stem_clips,
        "null_test": null,
        "warnings": warnings,
        "passed": not warnings,
    }
