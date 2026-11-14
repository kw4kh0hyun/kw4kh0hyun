import json

import numpy as np
import pytest
import soundfile as sf

from conftest import dir_bytes, read_pcm24
from edmmix import params as params_mod
from edmmix.cli import main

AUDIO_AND_PARAMS = ("premaster.wav", "mix_params.json", "stems_processed/")


def _comparable(files: dict) -> dict:
    return {k: v for k, v in files.items() if k.startswith(AUDIO_AND_PARAMS)}


def test_outputs_exist_and_format(mix_out, stems_dir, sr):
    for name in ("premaster.wav", "mix_params.json", "report.json", "report.md"):
        assert (mix_out / name).is_file()
    info = sf.info(str(mix_out / "premaster.wav"))
    assert (info.samplerate, info.channels, info.subtype) == (sr, 2, "PCM_24")
    originals = sorted(p.name for p in stems_dir.glob("*.wav"))
    assert sorted(p.name for p in (mix_out / "stems_processed").glob("*.wav")) == originals
    assert info.frames == sf.info(str(stems_dir / originals[0])).frames


def test_premaster_peak_is_minus_6_dbfs(mix_out):
    peak = np.max(np.abs(read_pcm24(mix_out / "premaster.wav"))) / 2 ** 23
    assert 20 * np.log10(peak) == pytest.approx(-6.0, abs=0.01)


def test_null_processed_stems_sum_to_premaster(mix_out):
    premaster = read_pcm24(mix_out / "premaster.wav")
    total = sum(read_pcm24(p) for p in sorted((mix_out / "stems_processed").glob("*.wav")))
    residual = np.max(np.abs(total - premaster)) / 2 ** 23
    assert 20 * np.log10(max(residual, 1e-12)) < -90.0


def test_deterministic_two_runs_identical(mix_out, stems_dir, tmp_path):
    assert main(["mix", str(stems_dir), "-o", str(tmp_path)]) == 0
    first, second = _comparable(dir_bytes(mix_out)), _comparable(dir_bytes(tmp_path))
    assert first.keys() == second.keys()
    assert all(first[k] == second[k] for k in first), "mix output differs between runs"


def test_render_reproduces_mix(mix_out, stems_dir, tmp_path):
    assert main(["render", str(stems_dir), "--params", str(mix_out / "mix_params.json"),
                 "-o", str(tmp_path)]) == 0
    first, second = _comparable(dir_bytes(mix_out)), _comparable(dir_bytes(tmp_path))
    assert first.keys() == second.keys()
    assert all(first[k] == second[k] for k in first), "render(params) differs from mix"


def test_edited_params_change_the_render(mix_out, stems_dir, tmp_path):
    params = json.loads((mix_out / "mix_params.json").read_text())
    params["stems"]["lead"]["gain_db"] -= 60.0
    edited = tmp_path / "edited.json"
    edited.write_text(json.dumps(params))
    assert main(["render", str(stems_dir), "--params", str(edited), "-o", str(tmp_path / "out")]) == 0
    lead = read_pcm24(tmp_path / "out" / "stems_processed" / "lead.wav")
    original = read_pcm24(mix_out / "stems_processed" / "lead.wav")
    assert np.max(np.abs(lead)) < 0.01 * np.max(np.abs(original))
    peak = np.max(np.abs(read_pcm24(tmp_path / "out" / "premaster.wav"))) / 2 ** 23
    assert 20 * np.log10(peak) == pytest.approx(-6.0, abs=0.01)  # auto mix-bus gain still hits the target


def test_report_contents(mix_out):
    report = json.loads((mix_out / "report.json").read_text())
    assert report["qc"]["null_test"]["residual_peak_dbfs"] < -90
    assert report["qc"]["sample_peak_dbfs"] == pytest.approx(-6.0, abs=0.01)
    assert report["global"]["tempo"]["bpm"] == 128.0
    assert all(d["reason"] for d in report["decisions"] if d["stage"] in ("classify", "balance"))
    assert "## QC" in (mix_out / "report.md").read_text()


def test_params_file_is_valid_and_complete(mix_out, stems_dir):
    params = params_mod.load(mix_out / "mix_params.json")
    assert set(params["stems"]) == {p.stem for p in stems_dir.glob("*.wav")}
    assert params["mixbus"]["target_peak_dbfs"] == -6.0 and params["sample_rate"] == 44100


def test_render_rejects_mismatched_stems(mix_out, stems_dir, tmp_path, capsys):
    params = json.loads((mix_out / "mix_params.json").read_text())
    del params["stems"]["pad"]
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(params))
    assert main(["render", str(stems_dir), "--params", str(bad), "-o", str(tmp_path / "o")]) == 2
    assert "not in params: pad" in capsys.readouterr().err


def test_analyze_command(stems_dir, tmp_path):
    assert main(["analyze", str(stems_dir), "-o", str(tmp_path)]) == 0
    report = json.loads((tmp_path / "report.json").read_text())
    assert report["stems"]["kick"]["role"] == "kick"
    assert len(report["stems"]["kick"]["analysis"]["third_octave"]["levels_db"]) == 29  # 25 Hz .. 16 kHz at 44.1 kHz


def test_unknown_genre_is_an_error(stems_dir, tmp_path, capsys):
    assert main(["mix", str(stems_dir), "-o", str(tmp_path), "--genre", "polka"]) == 2
    assert "unknown genre" in capsys.readouterr().err
