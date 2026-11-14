import numpy as np
import pytest

from conftest import sine, stereo
from edmmix import analyze
from edmmix.classify import HeuristicClassifier, classify_stems, load_roles_file
from edmmix.dsp.onsets import detect_onsets
from edmmix.loader import load_stems


def test_integrated_lufs_of_reference_sine(sr):
    # BS.1770: a 997 Hz stereo sine at -18 dBFS peak reads about -18 LUFS.
    x = stereo(sine(997.0, 5.0, sr, amp=10 ** (-18 / 20)))
    assert analyze.integrated_lufs(x, sr) == pytest.approx(-18.0, abs=0.3)
    st = analyze.short_term_lufs(x, sr)
    assert st.size == 3 and st.max() == pytest.approx(-18.0, abs=0.3)


def test_silence_is_minus_inf(sr):
    assert analyze.integrated_lufs(np.zeros((sr * 2, 2)), sr) == float("-inf")


def test_peaks_and_crest(sr):
    x = stereo(sine(1000.0, 2.0, sr, amp=0.5))
    assert analyze.sample_peak_db(x) == pytest.approx(-6.02, abs=0.05)
    assert analyze.crest_factor_db(x, sr) == pytest.approx(3.01, abs=0.1)
    # sr/4 sine sampled at 45 degrees: samples reach only 0.707 of the true peak
    t = np.arange(sr)
    y = stereo(np.sin(2 * np.pi * 0.25 * t + np.pi / 4))
    assert analyze.sample_peak_db(y) == pytest.approx(-3.01, abs=0.05)
    assert analyze.true_peak_db(y) == pytest.approx(0.0, abs=0.2)


def test_stereo_correlation(sr):
    s = sine(440.0, 1.0, sr)
    assert analyze.stereo_correlation(stereo(s, s)) == pytest.approx(1.0)
    assert analyze.stereo_correlation(stereo(s, -s)) == pytest.approx(-1.0)
    assert abs(analyze.stereo_correlation(stereo(s, sine(440.0, 1.0, sr, phase=np.pi / 2)))) < 0.01


def test_third_octave_peak_band(sr):
    centers, levels = analyze.third_octave_spectrum(stereo(sine(1000.0, 2.0, sr)), sr)
    assert centers[np.argmax(levels)] == pytest.approx(1000.0, rel=0.01)
    assert levels.max() == pytest.approx(-3.0, abs=0.5)  # power of a unit sine = 0.5


def test_onset_detection_on_kick_grid(sr):
    x = np.zeros(sr * 4)
    expected = np.arange(8) * int(0.46875 * sr) + 1000
    n = int(0.25 * sr)
    t = np.arange(n) / sr
    hit = np.sin(2 * np.pi * 55 * t) * np.exp(-t / 0.08)
    for pos in expected:
        x[pos:pos + n] += hit
    onsets = detect_onsets(x, sr)
    assert len(onsets) == len(expected)
    assert np.max(np.abs(onsets - expected)) <= int(0.004 * sr)


def test_bpm_key_sections_on_fixture(stems_dir):
    stem_set = load_stems(stems_dir)
    mix = sum(s.audio.astype(np.float64) for s in stem_set.stems)
    tonal = stem_set.get("pad").audio.astype(np.float64)
    result = analyze.analyze_global(mix, tonal, stem_set.sample_rate)
    assert result["tempo"]["bpm"] == pytest.approx(128.0, abs=1.0)
    assert result["key"]["key"] in ("A minor", "C major")
    labels = [s["label"] for s in result["sections"]]
    assert labels[-1] == "drop" and labels[0] == "intro"
    drop = result["sections"][-1]
    assert drop["start_bar"] == 4 and drop["end_bar"] == 8


def test_analyze_audio_is_json_serialisable(stems_dir):
    import json

    stem = load_stems(stems_dir).get("kick")
    json.dumps(analyze.analyze_audio(stem.audio, stem.sample_rate))
    json.dumps(analyze.analyze_audio(np.zeros((44100, 2)), 44100))


def test_filename_classification(stems_dir):
    roles = {k: v.role for k, v in classify_stems(load_stems(stems_dir)).items()}
    assert roles == {"kick": "kick", "sub": "sub", "bass": "bass", "hats": "hats_perc",
                     "clap": "snare_clap", "lead": "lead", "pad": "pad", "vocal": "vocal",
                     "fx_riser": "fx"}


@pytest.mark.parametrize("name,role", [
    ("01_Sub Bass", "sub"), ("Vocal Chop 2", "vocal"), ("BD_main", "kick"), ("Open HH", "hats_perc"),
    ("Reese_Bass", "bass"), ("Supersaw Lead", "lead"), ("ARP 1", "pluck_arp"), ("Strings", "pad"),
])
def test_filename_keywords(name, role, sr):
    assert HeuristicClassifier().classify(name, np.zeros((sr, 2)), sr).role == role


def test_spectral_fallback(stems_dir):
    stem_set = load_stems(stems_dir)
    clf = HeuristicClassifier()
    spectral = {n: clf.classify_spectral(stem_set.get(n).audio, stem_set.sample_rate).role
                for n in ("kick", "sub", "hats")}
    assert spectral == {"kick": "kick", "sub": "sub", "hats": "hats_perc"}


def test_manual_roles_take_priority(stems_dir, tmp_path):
    path = tmp_path / "roles.json"
    path.write_text('{"lead.wav": "pluck_arp"}')
    guesses = classify_stems(load_stems(stems_dir), load_roles_file(path))
    assert guesses["lead"].role == "pluck_arp" and guesses["lead"].source == "manual"
    path.write_text('{"lead": "banana"}')
    with pytest.raises(ValueError, match="unknown role"):
        load_roles_file(path)
