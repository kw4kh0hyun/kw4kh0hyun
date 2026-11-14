import json

import numpy as np
import pytest
import soundfile as sf

from conftest import dir_bytes, read_pcm24
from edmmix import analyze
from edmmix.cli import main
from edmmix.dsp import filters

BANDS = ["sub", "low", "mid", "high_mid", "high"]


@pytest.fixture(scope="module")
def reference_wav(mix_out, tmp_path_factory):
    """The default mix with a tilt (less low end, brighter top), exported at another sample rate tag."""
    x, sr = sf.read(str(mix_out / "premaster.wav"))
    sos = np.vstack([filters.low_shelf_sos(150.0, -3.0, 0.707, sr), filters.high_shelf_sos(3000.0, 4.0, 0.707, sr)])
    path = tmp_path_factory.mktemp("ref") / "reference.wav"
    sf.write(str(path), filters.apply_sos(x, sos), sr, subtype="PCM_24")
    return path


@pytest.fixture(scope="module")
def ref_out(stems_dir, reference_wav, tmp_path_factory):
    out = tmp_path_factory.mktemp("ref_out")
    assert main(["mix", str(stems_dir), "-o", str(out), "--reference", str(reference_wav)]) == 0
    return out


def _deviation(premaster_path, reference_path):
    x, sr = sf.read(str(premaster_path))
    ref, ref_sr = sf.read(str(reference_path))
    a, b = analyze.broad_band_balance(x, sr), analyze.broad_band_balance(ref, ref_sr)
    return np.array([a[k] - b[k] for k in BANDS])


def test_reference_pulls_tone_balance_towards_reference(mix_out, ref_out, reference_wav):
    before = _deviation(mix_out / "premaster.wav", reference_wav)
    after = _deviation(ref_out / "premaster.wav", reference_wav)
    assert np.max(np.abs(before)) > 2.0                                  # the reference really is different
    assert np.sqrt(np.mean(after ** 2)) < 0.5 * np.sqrt(np.mean(before ** 2))
    assert np.max(np.abs(after)) < np.max(np.abs(before))


def test_reference_is_reported_and_bounded(ref_out):
    report = json.loads((ref_out / "report.json").read_text())
    info = report["reference"]
    assert info["rms_deviation_predicted_db"] < info["rms_deviation_before_db"]
    assert report["qc"]["reference_band_balance_db"] == info["band_balance_db"]
    params = json.loads((ref_out / "mix_params.json").read_text())
    used = [b for name, b in params["buses"].items() if b["eq"]]
    assert used and all(abs(b["gain_db"]) <= 3.0 for b in params["buses"].values())
    assert all(abs(band["gain_db"]) <= 3.0 for b in used for band in b["eq"])
    assert any(b["gain_db"] != 0.0 or any(band["gain_db"] for band in b["eq"]) for b in used)
    assert "Reference matching" in (ref_out / "report.md").read_text()


def test_reference_mix_still_nulls_hits_peak_and_reproduces(ref_out, stems_dir, tmp_path):
    premaster = read_pcm24(ref_out / "premaster.wav")
    total = sum(read_pcm24(p) for p in sorted((ref_out / "stems_processed").glob("*.wav")))
    assert 20 * np.log10(max(np.max(np.abs(total - premaster)) / 2 ** 23, 1e-12)) < -90.0
    assert 20 * np.log10(np.max(np.abs(premaster)) / 2 ** 23) == pytest.approx(-6.0, abs=0.01)
    assert main(["render", str(stems_dir), "--params", str(ref_out / "mix_params.json"), "-o", str(tmp_path)]) == 0
    a, b = dir_bytes(ref_out), dir_bytes(tmp_path)
    assert a["premaster.wav"] == b["premaster.wav"] and a["mix_params.json"] == b["mix_params.json"]
    assert all(a[k] == b[k] for k in a if k.startswith("stems_processed/"))


def test_reference_with_different_sample_rate_is_only_measured(stems_dir, tmp_path, sr):
    rng = np.random.default_rng(7)
    ref = np.stack([rng.standard_normal(48000 * 3)] * 2, axis=1) * 0.1
    sf.write(str(tmp_path / "ref48.wav"), ref, 48000, subtype="PCM_16")
    assert main(["mix", str(stems_dir), "-o", str(tmp_path / "out"), "--reference", str(tmp_path / "ref48.wav")]) == 0
    assert sf.info(str(tmp_path / "out" / "premaster.wav")).samplerate == sr


def test_missing_reference_is_an_error(stems_dir, tmp_path, capsys):
    assert main(["mix", str(stems_dir), "-o", str(tmp_path), "--reference", str(tmp_path / "nope.wav")]) == 2
    assert "reference file not found" in capsys.readouterr().err
