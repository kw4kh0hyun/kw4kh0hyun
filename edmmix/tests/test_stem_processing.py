import json

import numpy as np
import pytest
from scipy import signal

from conftest import sine, stereo, tone_level_db
from edmmix import stem_processing as sp
from edmmix.dsp import filters
from edmmix.loader import load_stems


def _level(x, freq, sr):
    return tone_level_db(x[sr // 2:, 0], freq, sr)      # skip the filter transient


def test_highpass_attenuates_lows_and_keeps_highs(sr):
    hp = {"enabled": True, "cutoff_hz": 120.0, "order": 2}
    low, high = stereo(sine(30.0, 2.0, sr, 0.5)), stereo(sine(1000.0, 2.0, sr, 0.5))
    assert _level(sp.apply_highpass(low, sr, hp), 30.0, sr) - _level(low, 30.0, sr) == pytest.approx(-24.0, abs=1.0)
    assert _level(sp.apply_highpass(high, sr, hp), 1000.0, sr) - _level(high, 1000.0, sr) == pytest.approx(0.0, abs=0.1)
    assert sp.apply_highpass(low, sr, {"enabled": False}) is low


def test_highpass_decision_by_role(sr):
    kick = stereo(sine(50.0, 2.0, sr, 0.5))
    assert 20.0 <= sp.decide_highpass("kick", kick, sr)["cutoff_hz"] <= 30.0
    assert sp.decide_highpass("sub", kick, sr)["cutoff_hz"] == 20.0
    hats = stereo(np.random.default_rng(0).standard_normal(sr * 2)) * 0.1
    hats = filters.apply_sos(hats, filters.highpass_sos(6000.0, 4, sr))
    assert sp.decide_highpass("hats_perc", hats, sr)["cutoff_hz"] == 300.0
    # a 'lead' whose fundamental sits at 80 Hz must not be thinned out by the 120 Hz default
    low_lead = stereo(sine(80.0, 2.0, sr, 0.5))
    decision = sp.decide_highpass("lead", low_lead, sr)
    assert decision["cutoff_hz"] < 80.0 * 0.75 and "lowered" in decision["reason"]


def _noise_with_resonance(sr, freq=3000.0, gain_db=14.0, q=10.0):
    noise = np.random.default_rng(3).standard_normal(sr * 8) * 0.05
    return stereo(signal.sosfilt(filters.peak_sos(freq, gain_db, q, sr), noise))


def test_resonance_is_detected_and_cut(sr):
    x = _noise_with_resonance(sr)
    peaks, _ = sp.detect_resonances(x, sr)
    assert len(peaks) == 1
    assert peaks[0]["freq_hz"] == pytest.approx(3000.0, rel=0.03)
    assert peaks[0]["excess_db"] == pytest.approx(14.0, abs=3.0)
    bands = sp.decide_eq("lead", x, sr)
    assert len(bands) == 1 and -6.0 <= bands[0]["gain_db"] <= -2.0 and bands[0]["q"] >= 4.0
    after, _ = sp.detect_resonances(sp.apply_eq(x, sr, bands), sr)
    assert not after or after[0]["excess_db"] < peaks[0]["excess_db"] - 4.0


def test_no_resonance_cuts_on_flat_noise_tonal_stems_or_kick(sr, stems_dir):
    flat = stereo(np.random.default_rng(4).standard_normal(sr * 8) * 0.05)
    assert sp.decide_eq("lead", flat, sr) == []
    assert sp.decide_eq("kick", _noise_with_resonance(sr), sr) == []
    stem_set = load_stems(stems_dir)
    for name, role in (("pad", "pad"), ("lead", "lead"), ("vocal", "vocal"), ("bass", "bass")):
        assert sp.decide_eq(role, stem_set.get(name).audio, sr) == [], name


def test_compressor_static_curve():
    levels = np.array([-40.0, -20.0, -8.0, 0.0])
    gr = sp.gain_reduction_db(levels, -20.0, 4.0, 0.0)
    assert gr == pytest.approx([0.0, 0.0, 9.0, 15.0])
    soft = sp.gain_reduction_db(levels, -20.0, 4.0, 6.0)
    assert soft[0] == 0.0 and 0.0 < soft[1] < 1.0 and soft[3] == pytest.approx(15.0)


def test_compressor_steady_state_and_transparency(sr):
    comp = {"enabled": True, "threshold_db": -20.0, "ratio": 4.0, "attack_ms": 5.0, "release_ms": 100.0,
            "knee_db": 0.0, "makeup_db": 0.0, "oversample": 4}
    loud = stereo(sine(1000.0, 2.0, sr, amp=10 ** (-6 / 20)))
    out, info = sp.compress(loud, sr, comp)
    # -6 dBFS in, threshold -20, 4:1 -> -16.5 dBFS at the peaks, slightly less on average (ripple)
    assert _level(out, 1000.0, sr) == pytest.approx(-16.0, abs=1.0)
    assert info["max_gain_reduction_db"] == pytest.approx(10.0, abs=1.0)
    quiet = stereo(sine(1000.0, 2.0, sr, amp=10 ** (-30 / 20)))
    out, info = sp.compress(quiet, sr, comp)
    assert info["max_gain_reduction_db"] == 0.0
    err = out[2000:-2000] - quiet[2000:-2000]
    assert 20 * np.log10(np.max(np.abs(err)) / 10 ** (-30 / 20)) < -60.0
    assert out.shape == quiet.shape


def test_compressor_tames_peaks_and_leaves_quiet_parts(sr):
    x = stereo(sine(220.0, 4.0, sr, 0.1))
    burst = 4000
    for pos in range(sr // 8, x.shape[0] - burst, sr // 2):     # loud burst every 500 ms
        x[pos:pos + burst] += stereo(sine(220.0, burst / sr, sr, 0.7) * np.hanning(burst))
    decision = sp.decide_compressor("vocal", x, sr)
    assert decision["enabled"] and 1.5 <= decision["ratio"] <= 4.0
    out, info = sp.compress(x, sr, decision)
    assert info["max_gain_reduction_db"] > 2.0
    peak_change = 20 * np.log10(np.max(np.abs(out)) / np.max(np.abs(x)))
    assert peak_change < -2.0
    quiet = slice(sr // 8 + burst + sr // 5, sr // 8 + sr // 2 - 500)   # after release, before next burst
    quiet_change = 20 * np.log10(np.max(np.abs(out[quiet])) / np.max(np.abs(x[quiet])))
    assert abs(quiet_change) < 0.5


def test_compressor_decisions_by_role(sr):
    dense = stereo(sine(220.0, 2.0, sr, 0.5))
    assert not sp.decide_compressor("lead", dense, sr)["enabled"]
    assert "never compressed" in sp.decide_compressor("kick", dense, sr)["reason"]
    assert not sp.decide_compressor("pad", np.zeros((sr, 2)), sr)["enabled"]


def _alias_energy(sr, oversample):
    """Fast compression of two HF tones creates intermodulation; products above Nyquist fold back."""
    t = np.arange(sr) / sr
    x = stereo(0.45 * np.sin(2 * np.pi * 17000 * t) + 0.45 * np.sin(2 * np.pi * 19000 * t))
    comp = {"enabled": True, "threshold_db": -30.0, "ratio": 20.0, "attack_ms": 0.0, "release_ms": 0.05,
            "knee_db": 0.0, "makeup_db": 0.0, "oversample": oversample}
    out, _ = sp.compress(x, sr, comp)
    spectrum = np.abs(np.fft.rfft(out[:, 0] * np.hanning(sr)))
    freqs = np.fft.rfftfreq(sr, 1 / sr)
    # genuine intermodulation products sit on the 1 kHz grid; anything else below 14 kHz folded back
    off_grid = (freqs > 500) & (freqs < 14000) & (np.abs((freqs + 500) % 1000 - 500) > 60)
    return float(np.sum(spectrum[off_grid] ** 2))


def test_oversampling_reduces_aliasing(sr):
    assert _alias_energy(sr, 4) < 0.1 * _alias_energy(sr, 1)


def test_mix_params_contain_stem_processing(mix_out):
    params = json.loads((mix_out / "mix_params.json").read_text())
    assert params["stems"]["hats"]["highpass"] == {**params["stems"]["hats"]["highpass"], "enabled": True, "cutoff_hz": 300.0}
    assert params["stems"]["sub"]["highpass"]["cutoff_hz"] == 20.0
    assert params["stems"]["kick"]["compressor"]["enabled"] is False
    assert all(s["compressor"]["oversample"] == 4 for s in params["stems"].values())
    assert all(s["highpass"]["reason"] and s["compressor"]["reason"] for s in params["stems"].values())
