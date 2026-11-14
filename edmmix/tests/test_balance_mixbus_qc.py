import numpy as np
import pytest

from conftest import sine, stereo
from edmmix import balance, mixbus, qc
from edmmix.audioio import quantize24
from edmmix.roles import ROLES


@pytest.mark.parametrize("genre", ["house", "melodic_techno", "future_bass", "dnb"])
def test_presets_load_and_cover_all_roles(genre):
    preset = balance.load_preset(genre)
    assert set(ROLES) <= set(preset["targets_lu"])
    assert preset["targets_lu"]["kick"] == 0.0
    assert preset["sidechain"]["release_beats"] > 0


def test_gains_hit_role_targets():
    preset = balance.load_preset("house")
    roles = {"k": "kick", "b": "bass", "l1": "lead", "l2": "lead", "quiet": "fx"}
    loud = {"k": -10.0, "b": -30.0, "l1": -20.0, "l2": -20.0, "quiet": None}
    gains = balance.decide_gains(loud, roles, preset)
    level = {n: loud[n] + gains[n]["gain_db"] for n in ("k", "b", "l1", "l2")}
    assert level["b"] - level["k"] == pytest.approx(preset["targets_lu"]["bass"], abs=0.01)
    # two leads share the role: together they reach the target
    lead_sum = 10 * np.log10(2 * 10 ** (level["l1"] / 10))
    assert lead_sum - level["k"] == pytest.approx(preset["targets_lu"]["lead"], abs=0.02)
    assert gains["quiet"]["gain_db"] == 0.0 and "not measurable" in gains["quiet"]["reason"]


def test_mixbus_gain_only(sr):
    x = stereo(sine(100.0, 1.0, sr, amp=0.9))
    gain = mixbus.peak_normalising_gain_db(x, -6.0)
    y = mixbus.apply_gain(x, gain)
    assert 20 * np.log10(np.max(np.abs(y))) == pytest.approx(-6.0, abs=1e-9)
    # pure gain: waveform shape is untouched (no limiter)
    assert np.allclose(y / np.max(np.abs(y)), x / np.max(np.abs(x)), atol=1e-12)
    assert mixbus.peak_normalising_gain_db(np.zeros((10, 2)), -6.0) == 0.0
    assert mixbus.resolve_gain_db(x, {"gain_mode": "fixed", "gain_db": -3.0, "target_peak_dbfs": -6.0}) == -3.0


def _qc(x, sr, **kw):
    return qc.run_qc(x, sr, -6.0, **kw)


def test_qc_clean_signal_passes(sr):
    rng = np.random.default_rng(1)
    noise = rng.standard_normal(sr * 4)
    from scipy import signal
    pink = signal.lfilter([0.05], [1, -0.95], noise)          # low-heavy, music-like tilt
    x = stereo(pink - pink.mean())
    x *= 10 ** (-6 / 20) / np.max(np.abs(x))
    result = _qc(x, sr)
    assert result["passed"], result["warnings"]
    assert result["sample_peak_dbfs"] == pytest.approx(-6.0, abs=0.01)


def test_qc_flags_dc_clipping_and_peak(sr):
    x = stereo(sine(200.0, 2.0, sr, amp=0.5)) + 0.01
    x[100] = 1.0
    warnings = " | ".join(_qc(x, sr)["warnings"])
    assert "DC offset" in warnings and "clipping" in warnings and "deviates" in warnings


def test_qc_mono_compatibility_and_correlation(sr):
    s = sine(80.0, 2.0, sr, amp=0.5)
    result = _qc(stereo(s, -s), sr)
    assert result["stereo_correlation"] == pytest.approx(-1.0)
    assert result["mono_compatibility_loss_db"]["low"] > 40
    warnings = " | ".join(result["warnings"])
    assert "correlation is negative" in warnings and "'low' band loses" in warnings
    assert _qc(stereo(s), sr)["mono_compatibility_loss_db"]["low"] == pytest.approx(0.0, abs=0.01)


def test_qc_true_peak_warning(sr):
    t = np.arange(sr * 2)
    x = stereo(np.sin(2 * np.pi * 0.25 * t + np.pi / 4))      # samples at 0.707 of true peak
    x *= 10 ** (-6 / 20) / np.max(np.abs(x))
    result = _qc(x, sr)
    assert result["true_peak_dbtp"] == pytest.approx(-3.0, abs=0.2)
    assert any("true peak" in w for w in result["warnings"])


def test_null_test_detects_missing_stem(sr):
    a, b = stereo(sine(100.0, 0.5, sr, amp=0.2)), stereo(sine(300.0, 0.5, sr, amp=0.2))
    good = qc.null_test(quantize24(a + b), {"a": quantize24(a), "b": quantize24(b)})
    assert good["residual_peak_dbfs"] < -120
    bad = qc.null_test(quantize24(a + b), {"a": quantize24(a)})
    assert bad["residual_peak_dbfs"] > -20
    result = qc.run_qc(a + b, sr, -6.0, null=bad)
    assert any("null test failed" in w for w in result["warnings"])
