import numpy as np
import pytest
import soundfile as sf

from edmmix.loader import StemLoadError, load_stems


def _write(path, n, sr=44100, channels=2):
    sf.write(str(path), np.zeros((n, channels)) + 0.1, sr, subtype="PCM_24")


def test_loads_fixture_set(stems_dir, sr):
    stem_set = load_stems(stems_dir)
    assert stem_set.sample_rate == sr
    assert len(stem_set.stems) == 9
    assert all(s.audio.shape == (stem_set.n_samples, 2) for s in stem_set.stems)
    assert stem_set.names == sorted(stem_set.names)


def test_mono_is_expanded_to_stereo(tmp_path):
    _write(tmp_path / "a.wav", 1000, channels=1)
    _write(tmp_path / "b.wav", 1000, channels=2)
    stem_set = load_stems(tmp_path)
    a = stem_set.get("a")
    assert a.audio.shape == (1000, 2) and a.source_channels == 1
    assert np.array_equal(a.audio[:, 0], a.audio[:, 1])


def test_sample_rate_mismatch(tmp_path):
    _write(tmp_path / "a.wav", 1000, sr=44100)
    _write(tmp_path / "b.wav", 1000, sr=48000)
    with pytest.raises(StemLoadError, match="sample rate mismatch"):
        load_stems(tmp_path)


def test_length_mismatch(tmp_path):
    _write(tmp_path / "a.wav", 1000)
    _write(tmp_path / "b.wav", 1001)
    with pytest.raises(StemLoadError, match="length mismatch"):
        load_stems(tmp_path)


def test_empty_dir_and_missing_dir(tmp_path):
    with pytest.raises(StemLoadError, match="no .wav files"):
        load_stems(tmp_path)
    with pytest.raises(StemLoadError, match="not found"):
        load_stems(tmp_path / "nope")


def test_too_many_channels(tmp_path):
    _write(tmp_path / "a.wav", 1000, channels=4)
    with pytest.raises(StemLoadError, match="channels"):
        load_stems(tmp_path)
