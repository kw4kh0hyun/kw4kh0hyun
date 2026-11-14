import json

import numpy as np
import pytest

from conftest import sine, stereo, tone_level_db
from edmmix import params as params_mod, pipeline
from edmmix.interaction import masking, mono_bass, phase, sidechain
from edmmix.loader import load_stems

SC = {"enabled": True, "depth_db": 9.0, "attack_ms": 2.0, "hold_ms": 15.0, "release_beats": 0.5, "curve": 2.0}
MB = {"enabled": True, "freq_hz": 120.0, "transition_hz": 60.0, "attenuation_db": 80.0}


def band_level_db(x: np.ndarray, sr: int, lo: float, hi: float) -> float:
    """Level (dB, sine-amplitude scale) of the content between lo and hi Hz."""
    w = np.hanning(x.shape[0])
    spectrum = np.abs(np.fft.rfft(x * w)) * 2 / np.sum(w)
    freqs = np.fft.rfftfreq(x.shape[0], 1 / sr)
    power = np.sum(spectrum[(freqs >= lo) & (freqs <= hi)] ** 2)
    return float(10 * np.log10(max(power, 1e-30)))


# ----------------------------------------------------------------------------- side-chain

def test_ducking_envelope_shape(sr):
    bpm = 120.0                                   # release = 0.5 beat = 250 ms
    onsets = [sr, 2 * sr]
    gain = sidechain.ducking_gain_db(3 * sr, sr, onsets, SC, bpm)
    ms = sr // 1000
    assert gain[sr - 1] == 0.0                                          # nothing before the kick
    assert gain[sr + 2 * ms] == pytest.approx(-9.0, abs=0.2)            # attack done after 2 ms
    assert gain[sr + 10 * ms] == pytest.approx(-9.0, abs=1e-9)          # hold
    assert -9.0 < gain[sr + 100 * ms] < -1.0                            # releasing
    assert gain[sr + 270 * ms] == 0.0                                   # 2 + 15 + 250 ms later: fully released
    assert gain.min() == pytest.approx(-9.0)
    # release follows the tempo
    fast = sidechain.ducking_gain_db(3 * sr, sr, onsets, SC, 180.0)
    assert fast[sr + 190 * ms] == 0.0 and gain[sr + 190 * ms] < -0.1


def test_kick_onsets_match_fixture_grid(stems_dir, sr):
    kick = load_stems(stems_dir).get("kick").audio[:, 0]
    onsets = sidechain.detect_kick_onsets(kick, sr, 128.0)
    beat = 60.0 / 128.0
    expected = np.array([round((16 + i) * beat * sr) for i in range(16)])
    assert len(onsets) == 16
    assert np.max(np.abs(onsets - expected)) <= int(0.003 * sr)


def _level_around(x, center, half):
    seg = x[center - half:center + half]
    return 10 * np.log10(np.mean(seg ** 2) + 1e-30)


def test_sidechain_reduces_sub_and_bass_at_kick_times(mix_out, stems_dir, sr):
    """End to end: compare the mix against the same mix with the side-chain switched off."""
    stem_set = load_stems(stems_dir)
    params = params_mod.load(mix_out / "mix_params.json")
    onsets = params["sidechain"]["onsets_samples"]
    assert len(onsets) == 16 and params["sidechain"]["source_stems"] == ["kick"]
    ducked, _ = pipeline.render_pre_bus(stem_set, params)
    for name in ("sub", "bass"):
        assert params["stems"][name]["sidechain"]["enabled"]
        params["stems"][name]["sidechain"]["enabled"] = False
    plain, _ = pipeline.render_pre_bus(stem_set, params)

    depth = params["stems"]["sub"]["sidechain"]["depth_db"]
    half = int(0.004 * sr)
    on_kick, between = [], []
    for onset in onsets[:-1]:
        hit = onset + int(0.010 * sr)                     # inside the hold phase
        on_kick.append(_level_around(ducked["sub"][:, 0], hit, half) - _level_around(plain["sub"][:, 0], hit, half))
        late = onset + int(0.40 * sr)                     # after the 234 ms release, before the next kick
        between.append(_level_around(ducked["sub"][:, 0], late, half) - _level_around(plain["sub"][:, 0], late, half))
    assert np.mean(on_kick) == pytest.approx(-depth, abs=0.5)
    assert max(on_kick) < -depth + 1.0
    assert np.max(np.abs(between)) < 0.2

    # bass plays on the off-beat: untouched there, but its gain curve still dips at the kick
    report = json.loads((mix_out / "report.json").read_text())
    assert report["render"]["stems"]["bass"]["interaction"]["sidechain"]["max_gain_reduction_db"] == \
        params["stems"]["bass"]["sidechain"]["depth_db"]
    assert report["render"]["stems"]["kick"]["interaction"]["sidechain"]["max_gain_reduction_db"] == 0.0


# ----------------------------------------------------------------------------- bass mono-ing

def test_mono_bass_removes_side_below_120hz(sr):
    t = np.arange(4 * sr) / sr
    mid = 0.3 * np.sin(2 * np.pi * 70 * t) + 0.2 * np.sin(2 * np.pi * 1000 * t)
    side = (0.2 * np.sin(2 * np.pi * 45 * t) + 0.2 * np.sin(2 * np.pi * 90 * t)
            + 0.2 * np.sin(2 * np.pi * 118 * t) + 0.2 * np.sin(2 * np.pi * 3000 * t))
    x = np.stack([mid + side, mid - side], axis=1)
    y = mono_bass.apply(x, sr, MB)
    edge = sr // 2                                       # ignore FIR edge effects at file start/end
    side_in = 0.5 * (x[edge:-edge, 0] - x[edge:-edge, 1])
    side_out = 0.5 * (y[edge:-edge, 0] - y[edge:-edge, 1])
    mid_out = 0.5 * (y[edge:-edge, 0] + y[edge:-edge, 1])
    assert band_level_db(side_out, sr, 20, 120) < -60.0
    assert band_level_db(side_out, sr, 20, 120) - band_level_db(side_in, sr, 20, 120) < -60.0
    # mid is untouched, side above the crossover is untouched (linear phase: sample-accurate)
    assert np.max(np.abs(mid_out - mid[edge:-edge])) < 1e-12
    assert tone_level_db(side_out, 3000.0, sr) == pytest.approx(tone_level_db(side_in, 3000.0, sr), abs=0.01)
    high_err = (side_out - 0.2 * np.sin(2 * np.pi * 3000 * t[edge:-edge]))
    assert band_level_db(high_err, sr, 1000, 10000) < -70.0


def test_mono_bass_passthrough_cases(sr):
    mono = stereo(sine(60.0, 1.0, sr, 0.5))
    assert mono_bass.apply(mono, sr, MB) is mono
    wide = stereo(sine(60.0, 1.0, sr, 0.5), sine(60.0, 1.0, sr, 0.5, phase=1.0))
    assert mono_bass.apply(wide, sr, {**MB, "enabled": False}) is wide


def test_premaster_and_stems_are_mono_below_120hz(mix_out, stems_dir, sr):
    import soundfile as sf

    raw, _ = sf.read(str(stems_dir / "bass.wav"))
    edge = sr // 2
    raw_side = 0.5 * (raw[edge:-edge, 0] - raw[edge:-edge, 1])
    assert band_level_db(raw_side, sr, 20, 120) > -45.0          # the fixture bass really is wide down low
    for path in (mix_out / "premaster.wav", mix_out / "stems_processed" / "bass.wav"):
        x, _ = sf.read(str(path))
        side = 0.5 * (x[edge:-edge, 0] - x[edge:-edge, 1])
        assert band_level_db(side, sr, 20, 120) < -60.0, path.name


# ----------------------------------------------------------------------------- phase

def _bursts(sr, freq=50.0, delay=0, polarity=1.0, seconds=4):
    n = seconds * sr
    x = np.zeros(n)
    onsets = np.arange(sr // 2, n - sr // 2, sr // 2)
    length = int(0.2 * sr)
    t = np.arange(length) / sr
    hit = np.sin(2 * np.pi * freq * t) * np.exp(-t / 0.06)
    for onset in onsets:
        x[onset + delay:onset + delay + length] += polarity * hit
    return x, onsets


def test_phase_aligned_gives_no_suggestion(sr):
    kick, onsets = _bursts(sr)
    result = phase.analyse(kick, kick * 0.7, sr, onsets)
    assert result == {**result, "apply": False, "invert_polarity": False, "delay_samples": 0}
    assert "aligned" in result["reason"]


def test_phase_detects_inverted_polarity(sr):
    kick, onsets = _bursts(sr)
    sub, _ = _bursts(sr, polarity=-1.0)
    result = phase.analyse(kick, sub, sr, onsets)
    assert result["invert_polarity"] is True and result["delay_samples"] == 0
    assert result["apply"] is False and "suggestion" in result["reason"]


def test_phase_detects_delay(sr):
    kick, onsets = _bursts(sr)
    late = int(0.0045 * sr)                          # 4.5 ms late = 81 degrees at 50 Hz
    sub, _ = _bursts(sr, delay=late)
    result = phase.analyse(kick, sub, sr, onsets)
    assert result["invert_polarity"] is False
    assert result["delay_samples"] == pytest.approx(-late, abs=3)      # advance it back


def test_phase_apply(sr):
    x = stereo(np.arange(10, dtype=float))
    assert phase.apply(x, {"apply": False, "invert_polarity": True, "delay_samples": 3}) is x
    y = phase.apply(x, {"apply": True, "invert_polarity": True, "delay_samples": 2})
    assert np.array_equal(y[:, 0], [0, 0, 0, -1, -2, -3, -4, -5, -6, -7])
    z = phase.apply(x, {"apply": True, "invert_polarity": False, "delay_samples": -2})
    assert np.array_equal(z[:, 0], [2, 3, 4, 5, 6, 7, 8, 9, 0, 0])


def test_applying_phase_suggestion_raises_low_end_sum(sr, tmp_path):
    """An inverted sub is flagged by mix; flipping "apply" and re-rendering fixes the kick+sub sum."""
    import soundfile as sf

    kick, onsets = _bursts(sr)
    sub, _ = _bursts(sr, polarity=-1.0)
    stems = tmp_path / "stems"
    stems.mkdir()
    sf.write(str(stems / "kick.wav"), stereo(kick) * 0.5, sr, subtype="PCM_24")
    sf.write(str(stems / "sub.wav"), stereo(sub) * 0.5, sr, subtype="PCM_24")
    stem_set = load_stems(stems)
    params, _ = pipeline.decide(stem_set, bpm_override=120.0)
    suggestion = params["stems"]["sub"]["phase"]
    assert suggestion["invert_polarity"] and not suggestion["apply"]
    for sp in params["stems"].values():
        sp["sidechain"]["enabled"] = False            # isolate the phase effect
    before, _ = pipeline.render_pre_bus(stem_set, params)
    params["stems"]["sub"]["phase"]["apply"] = True
    after, _ = pipeline.render_pre_bus(stem_set, params)
    def rms(d):
        return np.sqrt(np.mean((d["kick"] + d["sub"]) ** 2))
    assert 20 * np.log10(rms(after) / rms(before)) > 6.0


# ----------------------------------------------------------------------------- masking

def test_dynamic_eq_cuts_only_while_source_is_active(sr):
    t = np.arange(3 * sr) / sr
    target = stereo(0.3 * np.sin(2 * np.pi * 1000 * t) + 0.3 * np.sin(2 * np.pi * 6000 * t))
    source = 0.5 * np.sin(2 * np.pi * 1000 * t) * ((t >= 1.0) & (t < 2.0))
    band = {"source": "vox", "freq_hz": 1000.0, "q": 2.0, "max_cut_db": 6.0, "threshold_db": -30.0,
            "range_db": 12.0, "attack_ms": 10.0, "release_ms": 120.0}
    out, info = masking.apply_dynamic_eq(target, source, sr, band)
    active = slice(int(1.3 * sr), int(1.9 * sr))
    idle = slice(int(0.2 * sr), int(0.9 * sr))
    def change(freq, sl):
        return tone_level_db(out[sl, 0], freq, sr) - tone_level_db(target[sl, 0], freq, sr)
    assert change(1000.0, active) == pytest.approx(-6.0, abs=0.3)
    assert abs(change(6000.0, active)) < 0.5                 # 2.6 octaves away: essentially untouched
    assert abs(change(1000.0, idle)) < 0.01
    assert np.array_equal(out[:int(0.9 * sr)], target[:int(0.9 * sr)])    # bit-transparent before the source enters
    assert info["max_cut_db"] == pytest.approx(6.0, abs=0.01)


def _tone_stem(sr, freqs, amp=0.3):
    t = np.arange(4 * sr) / sr
    return stereo(sum(amp * np.sin(2 * np.pi * f * t) for f in freqs))


def test_masking_targets_lower_priority_stem(sr):
    procs = {"vox": _tone_stem(sr, [1000.0]), "pad": _tone_stem(sr, [300.0, 1000.0]),
             "arp": _tone_stem(sr, [1000.0, 5000.0])}
    roles = {"vox": "vocal", "pad": "pad", "arp": "pluck_arp"}
    result = masking.decide(procs, {n: 0.0 for n in procs}, roles, set(), sr)
    assert result["vox"] == []                                   # highest priority is never cut
    for name in ("pad", "arp"):                                  # equal-priority stems don't cut each other
        assert len(result[name]) == 1
        band = result[name][0]
        assert band["source"] == "vox" and band["freq_hz"] == pytest.approx(1000.0, rel=0.02)
        assert 2.0 <= band["max_cut_db"] <= 6.0 and "masking" in band["reason"]


def test_masking_priority_order_and_level_dependence(sr):
    procs = {"kick": _tone_stem(sr, [60.0]), "sub": _tone_stem(sr, [60.0]),
             "vox": _tone_stem(sr, [800.0]), "lead": _tone_stem(sr, [800.0])}
    roles = {"kick": "kick", "sub": "sub", "vox": "vocal", "lead": "lead"}
    gains = {n: 0.0 for n in procs}
    result = masking.decide(procs, gains, roles, set(), sr)
    assert [b["source"] for b in result["sub"]] == ["kick"]       # kick > sub
    assert [b["source"] for b in result["lead"]] == ["vox"]       # vocal > lead
    assert result["kick"] == [] and result["vox"] == []
    # a side-chained sub is already ducked by the kick: no extra dynamic EQ
    assert masking.decide(procs, gains, roles, {"sub"}, sr)["sub"] == []
    # a lead that sits 20 dB under the vocal is not masking it
    quiet = masking.decide(procs, {**gains, "lead": -20.0}, roles, set(), sr)
    assert quiet["lead"] == []


def test_fixture_mix_uses_dynamic_eq_and_buses(mix_out):
    params = json.loads((mix_out / "mix_params.json").read_text())
    assert any(b["source"] == "vocal" for b in params["stems"]["lead"]["dynamic_eq"])
    assert params["stems"]["kick"]["dynamic_eq"] == [] and params["stems"]["vocal"]["dynamic_eq"] == []
    buses = {name: sp["bus"] for name, sp in params["stems"].items()}
    assert buses == {"kick": "drums", "clap": "drums", "hats": "drums", "sub": "bass", "bass": "bass",
                     "lead": "synths", "pad": "synths", "vocal": "vocals", "fx_riser": "fx"}
    assert params["mono_bass"]["enabled"] and params["mono_bass"]["freq_hz"] == 120.0
