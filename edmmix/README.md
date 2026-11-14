# edmmix — EDM 스템 자동 믹싱 엔진 (MVP)

스템(악기별 WAV) 폴더를 받아 마스터링에 넘길 수 있는 **프리마스터**를 만드는 Python CLI입니다.

- 신경망이 오디오를 만들거나 바꾸지 않습니다. **분석 → 파라미터 결정 → DSP 적용**만 합니다.
- **결정론적**입니다. 같은 입력과 같은 설정이면 출력 파일이 비트 단위로 같습니다.
- 모든 처리 파라미터는 `mix_params.json`에 저장되고, 수정한 JSON으로 다시 렌더링할 수 있습니다.
- 내부 처리는 float64, 원본 샘플레이트 그대로입니다(리샘플링 없음).
- 믹스 버스에는 게인만 있습니다. 리미터·맥시마이저·클리퍼는 없습니다.

## 설치

```bash
cd edmmix
pip install -e ".[dev]"     # Python 3.11+
pytest                      # 약 1~2분
```

## 사용법

```bash
edmmix analyze <stems_dir> [-o <dir>]            # 분석만. <dir>/report.json (기본: 현재 디렉터리)
edmmix mix <stems_dir> -o <out_dir> [--reference ref.wav] [--genre house]
edmmix render <stems_dir> --params mix_params.json -o <out_dir>
```

공통 옵션(`analyze`, `mix`):

| 옵션 | 설명 |
|---|---|
| `--roles roles.json` | 역할 수동 지정. 생략하면 `<stems_dir>/roles.json`이 있을 때 자동으로 읽습니다. |
| `--bpm 128` | 템포 검출 대신 이 값을 사용합니다. |
| `--genre` | `house`(기본), `melodic_techno`, `future_bass`, `dnb` |
| `--reference` | 레퍼런스 트랙. 대역별 톤 밸런스만 측정해 버스 게인/EQ를 맞춥니다. |

입력 조건: 폴더 최상위의 `.wav` 파일 전부가 스템입니다. 모두 **같은 샘플레이트, 같은 길이**여야 하고(다르면 파일별 값을 보여주는 에러로 중단), 모노 또는 스테레오여야 합니다. 모노는 스테레오로 복제됩니다.

`roles.json` 예시 (키는 파일명 또는 확장자를 뺀 이름):

```json
{ "Serum_01.wav": "lead", "LOOP_A": "hats_perc" }
```

역할: `kick, snare_clap, hats_perc, sub, bass, lead, pad, pluck_arp, vocal, fx`

테스트용 합성 스템으로 바로 실행해 볼 수 있습니다.

```bash
python tests/fixtures/make_stems.py /tmp/stems
edmmix mix /tmp/stems -o /tmp/out
```

### 워크플로: 자동 믹스 후 손으로 고치기

1. `edmmix mix stems -o out` 실행 후 `out/report.md`에서 각 결정과 이유, QC 경고를 확인합니다.
2. `out/mix_params.json`을 고칩니다. 예: 스템 `gain_db` 변경, `sidechain.depth_db` 조정, 위상 제안 `"apply": true`.
3. `edmmix render stems --params out/mix_params.json -o out_v2`

수정하지 않은 `mix_params.json`으로 `render`하면 `mix` 결과와 바이트 단위로 같은 오디오가 나옵니다.

## 출력물

| 파일 | 내용 |
|---|---|
| `premaster.wav` | 24-bit PCM(디더 없음), 원본 샘플레이트, 샘플 피크 -6 dBFS |
| `stems_processed/` | 처리된 개별 스템. 전부 더하면 `premaster.wav`와 일치합니다(오차 약 -129 dBFS, 24-bit 반올림 수준). |
| `mix_params.json` | 스템별/버스별 전체 파라미터 |
| `report.json`, `report.md` | 분석 결과, 각 결정과 이유, QC 결과와 경고 |

## 파이프라인

| 단계 | 모듈 | 하는 일 |
|---|---|---|
| 1 | `loader` | WAV 로드, 샘플레이트/길이/채널 검증, 스테레오 통일 |
| 2 | `classify` | 역할 분류. 우선순위: `roles.json` > 파일명 키워드 > 스펙트럼 휴리스틱(센트로이드, 120 Hz 이하 에너지 비율, 트랜지언트 밀도, 크레스트). `Classifier` 프로토콜만 구현하면 ML 모델로 교체할 수 있습니다. |
| 3 | `analyze` | 통합/단기 LUFS, 트루 피크, 크레스트 팩터, 1/3옥타브 스펙트럼, 스테레오 상관도, BPM, 키, 구간(intro/buildup/drop/breakdown) |
| 4 | `stem_processing` | 역할별 하이패스 → 공진 컷 EQ → 컴프레서(4x 오버샘플링) |
| 5 | `interaction` | 킥 사이드체인, 마스킹 다이내믹 EQ, 120 Hz 이하 모노화, 킥/서브 위상 검사, 버스 그룹핑 |
| 6 | `balance`, `reference` | 장르 프리셋의 역할별 목표 레벨로 게인 설정, 레퍼런스 톤 매칭 |
| 7 | `mixbus` | 합산 후 샘플 피크가 -6 dBFS가 되도록 게인만 조정 |
| 8 | `qc` | 검증 리포트와 경고 |

스템 하나의 신호 경로:

```
[위상 보정(선택)] → 하이패스 → 공진 EQ → 컴프레서
  → 킥 사이드체인 → 다이내믹 EQ → 120 Hz 모노화
  → 밸런스 게인 → 버스 EQ/게인 → 믹스버스 게인
```

### 주요 설계

- **decide / render 분리.** `mix`는 파라미터를 결정한 뒤, 저장될 JSON을 그대로 다시 읽어 `render`와 같은 코드로 렌더링합니다.
- **사이드체인.** 킥 오디오로 컴프레서를 누르는 대신, 킥 트랜지언트 위치를 검출해 각 위치에 어택 → 홀드 → 릴리즈 엔벨로프를 합성합니다. 릴리즈는 박자 단위(`release_beats`)라 BPM에 동기화됩니다. 검출된 위치는 `sidechain.onsets_samples`에 저장되어 직접 고칠 수 있습니다.
- **마스킹.** 믹스 레벨에서의 스템별 1/3옥타브 스펙트럼을 쌍으로 비교합니다. 우선순위(kick > sub > vocal > lead > 나머지)가 높은 스템의 주요 대역에서 낮은 쪽이 6 dB 이내로 경쟁하면, 낮은 쪽에 높은 쪽 신호로 구동되는 다이내믹 EQ(최대 6 dB 컷)를 겁니다. 우선순위가 같은 스템끼리는 서로 깎지 않고, 킥 사이드체인이 이미 걸린 스템은 킥 기준 다이내믹 EQ를 생략합니다.
- **모노화.** 사이드 신호를 선형위상 FIR(120 Hz까지 통과, 180 Hz에서 -80 dB)로 나눠 저역 사이드만 제거합니다. 지연을 보상하므로 미드 신호와 크로스오버 위 대역은 샘플 단위로 그대로입니다.
- **위상 검사.** 킥 직후 150 ms 구간의 150 Hz 이하 대역에서, sub/bass의 극성 반전이나 ±5 ms 이내 지연이 킥과의 합을 1 dB 이상 키우는지 계산합니다. 결과는 **제안만** 하고(`"apply": false`) 자동 적용하지 않습니다.
- **버스는 선형 처리만.** 버스 EQ/게인을 스템마다 적용해도 버스 합에 적용한 것과 같으므로, 처리된 스템의 합이 프리마스터와 일치합니다. 같은 이유로 버스 컴프레션은 없습니다.
- **레퍼런스 매칭.** 5개 대역(20–60, 60–250, 250–2k, 2k–6k, 6k–20k Hz) 밸런스 차이를 버스 게인(±3 dB)과 모든 버스에 공통인 5밴드 EQ(±3 dB)로 최소제곱 근사합니다. 레퍼런스는 측정만 하므로 샘플레이트가 달라도 됩니다.

### QC 항목

샘플 피크(목표 대비), 트루 피크, 통합/단기 LUFS, 스테레오 상관도, 대역별 모노 합산 손실, 대역별 밸런스(레퍼런스가 있으면 편차), DC 오프셋, 클리핑(프리마스터와 스템), 널 테스트(스템 합 − 프리마스터). 기준을 벗어난 항목은 `report.md`와 CLI 출력에 경고로 표시됩니다.

## 장르 프리셋

`src/edmmix/presets/*.yaml`에 있습니다. 파일을 추가하면 `--genre <파일명>`으로 쓸 수 있습니다.

```yaml
name: house
default_bpm: 124            # 템포 검출 실패 시 사용
targets_lu:                 # 킥 대비 역할별 목표 통합 라우드니스(LU). 10개 역할 모두 필요
  kick: 0.0
  bass: -5.0
  # ...
sidechain:
  attack_ms: 2.0
  hold_ms: 15.0
  release_beats: 0.5        # 4분음표 단위
  curve: 2.0
  depth_db:                 # 역할별 최대 감쇠량. 없는 역할은 덕킹하지 않음
    sub: 9.0
    bass: 7.0
highpass_hz:                # (선택) 역할별 하이패스 기본값 덮어쓰기
  pad: 150.0
```

같은 역할의 스템이 여러 개면 그 역할의 합이 목표에 오도록 각 스템을 `10·log10(n)` dB 낮춥니다.

## `mix_params.json` 스키마 (schema_version 1)

`reason`, `*_reason` 키는 사람이 읽기 위한 설명이며 렌더러는 무시합니다.

```jsonc
{
  "schema_version": 1,
  "edmmix_version": "0.1.0",
  "sample_rate": 44100,            // 스템과 다르면 render가 거부
  "genre": "house",                // 정보용
  "bpm": 128.0,                    // 사이드체인 릴리즈 길이에 사용
  "stems": {
    "<스템 이름 = 확장자 뺀 파일명>": {
      "file": "bass.wav",
      "role": "bass",              // 10개 역할 중 하나
      "bus": "bass",               // drums | bass | synths | vocals | fx
      "phase": {                   // 킥 대비 위상 제안. apply=true여야 적용
        "apply": false, "invert_polarity": false, "delay_samples": 0   // 음수 = 앞당김
      },
      "highpass": { "enabled": true, "cutoff_hz": 30.0, "order": 2 },  // Butterworth, 6·order dB/oct
      "eq": [                      // 정적 EQ. type: peak | low_shelf | high_shelf
        { "type": "peak", "freq_hz": 3000.0, "gain_db": -4.0, "q": 8.0 }
      ],
      "compressor": {
        "enabled": true, "threshold_db": -12.4, "ratio": 2.8,
        "attack_ms": 15.0, "release_ms": 120.0, "knee_db": 6.0,
        "makeup_db": 0.0, "oversample": 4          // 1 | 2 | 4 | 8
      },
      "sidechain": {               // 킥 덕킹
        "enabled": true, "depth_db": 7.0, "attack_ms": 2.0, "hold_ms": 15.0,
        "release_beats": 0.5, "curve": 2.0         // curve: 릴리즈 곡선 지수
      },
      "dynamic_eq": [              // source 스템이 해당 대역에서 울릴 때만 컷
        { "source": "vocal", "freq_hz": 1587.4, "q": 2.0, "max_cut_db": 4.3,
          "threshold_db": -41.2, "range_db": 12.0,  // threshold에서 시작, +range에서 최대 컷
          "attack_ms": 10.0, "release_ms": 120.0 }
      ],
      "gain_db": -2.1              // 밸런스 게인
    }
  },
  "sidechain": {
    "source_stems": ["kick"],      // 정보용
    "onsets_samples": [330750, 351422]   // 덕킹이 시작되는 샘플 위치
  },
  "mono_bass": { "enabled": true, "freq_hz": 120.0, "transition_hz": 60.0, "attenuation_db": 80.0 },
  "buses": {
    "drums": { "gain_db": 0.0, "eq": [] }          // eq 형식은 스템 eq와 동일
    // bass, synths, vocals, fx
  },
  "mixbus": {
    "target_peak_dbfs": -6.0,
    "gain_mode": "auto",           // auto: 렌더할 때마다 목표 피크에 맞춤 / fixed: gain_db를 그대로 사용
    "gain_db": -6.39               // auto일 때는 실제 적용된 값의 기록
  }
}
```

`render`는 폴더의 스템 이름 집합이 `stems`의 키와 정확히 같아야 실행됩니다. 스템 처리 순서와 합산 순서는 이름순으로 고정됩니다.

## 테스트

`pytest`로 77개 테스트를 실행합니다.

| 요구 사항 | 테스트 |
|---|---|
| DSP 단위 테스트(사인, 킥, 노이즈) | `test_analyze.py`, `test_stem_processing.py`, `test_interaction.py`, `test_balance_mixbus_qc.py` |
| 결정론 | `test_pipeline.py::test_deterministic_two_runs_identical` |
| 널 테스트(-90 dB 이하) | `test_pipeline.py::test_null_processed_stems_sum_to_premaster` |
| 재현(mix → render) | `test_pipeline.py::test_render_reproduces_mix` |
| 사이드체인 게인 리덕션 | `test_interaction.py::test_sidechain_reduces_sub_and_bass_at_kick_times` |
| 120 Hz 이하 사이드 -60 dB 이하 | `test_interaction.py::test_mono_bass_removes_side_below_120hz`, `test_premaster_and_stems_are_mono_below_120hz` |
| 합성 스템 생성 스크립트 | `tests/fixtures/make_stems.py` (8마디, 128 BPM, 9개 스템) |

## 알려진 한계

- **pedalboard는 의존성에만 있고 렌더 경로에서는 쓰지 않습니다.** 외부 사이드체인 입력과 비트 단위 결정론을 위해 DSP를 numpy/scipy/numba로 직접 구현했습니다.
- **결정론의 범위.** 같은 머신과 같은 라이브러리 버전에서 비트 단위로 같습니다. 다른 CPU나 numpy/scipy 버전에서는 FFT·BLAS 구현 차이로 마지막 비트가 달라질 수 있습니다.
- **메모리.** 모든 스템을 메모리에 올려 float64로 처리합니다. 스테레오 5분 스템 하나가 단계마다 약 200 MB를 쓰므로, 스템이 많은 긴 곡은 수 GB가 필요합니다. 스트리밍 처리는 없습니다.
- **역할 분류.** 파일명 키워드가 없으면 스펙트럼 휴리스틱으로 추정하는데 lead/pad/pluck_arp/vocal 구분은 신뢰도가 낮습니다. `report.md`의 분류 근거를 확인하고 틀리면 `roles.json`으로 지정하세요.
- **밸런스는 LUFS 기준입니다.** K-가중은 저역을 낮게 평가하므로 프리셋의 sub/kick 목표값은 경험적인 값입니다. 프리셋 수치는 출발점이며 장르별 검증 데이터로 튜닝한 것이 아닙니다.
- **공진 검출은 보수적입니다.** 장기 평균 스펙트럼에서 고립된 좁은 피크만 잡고(스템당 최대 2개, 최대 6 dB 컷), 피크가 3개 이상이거나 20 dB를 넘으면 음정 성분으로 보고 건드리지 않습니다. 그래도 한 음만 길게 유지되는 소리의 배음을 공진으로 오인할 수 있습니다.
- **컴프레서**는 스테레오 링크 피크 검출 방식 하나뿐이고 메이크업 게인은 0입니다(레벨은 밸런스 단계가 맞춥니다). 새추레이션, 멀티밴드, 병렬 컴프레션, 리버브/딜레이 같은 공간계 처리는 없습니다.
- **다이내믹 EQ와 사이드체인은 오버샘플링하지 않습니다.** 게인 변화가 느려 앨리어싱이 문제되지 않는다고 보았습니다. 4x 오버샘플링은 컴프레서에만 적용됩니다.
- **킥 검출**은 레벨 기반입니다. 킥 스템에 다른 타악기가 섞여 있거나 고스트 노트가 많으면 원치 않는 덕킹이 생길 수 있습니다. `sidechain.onsets_samples`를 고쳐서 바로잡을 수 있습니다. 킥 역할 스템이 없으면 사이드체인과 위상 검사를 건너뜁니다.
- **템포는 곡 전체에서 하나로 가정합니다.** 템포 변화나 스윙이 큰 곡은 `--bpm`으로 지정하세요. 키 추정은 리포트용이며 처리에 쓰이지 않습니다.
- **구간 검출**은 마디 단위 에너지 기반 추정으로 리포트에만 쓰입니다. 구간별로 다른 처리(오토메이션)는 하지 않으며, 모든 파라미터는 곡 전체에 고정입니다.
- **레퍼런스 매칭**은 5개 대역의 장기 평균 밸런스만 맞춥니다. 라우드니스, 다이내믹, 스테레오 폭은 맞추지 않고, EQ는 모든 버스에 같은 값이 들어갑니다.
- **마스킹 검출**은 장기 평균 스펙트럼 기반이라 서로 다른 구간에서만 울리는 스템 쌍도 겹침으로 잡힐 수 있습니다. 다만 다이내믹 EQ는 소스가 실제로 울릴 때만 동작합니다.
- **모노화 FIR**은 파일 맨 앞과 맨 끝 약 40 ms 구간에서 경계 효과가 있습니다.
- 프리마스터는 **샘플 피크** 기준 -6 dBFS입니다. 트루 피크는 QC에서 따로 보고하며 1.5 dB 이상 높으면 경고합니다.
- 처리된 스템이 0 dBFS를 넘으면 24-bit 저장 시 잘리고 널 테스트가 깨집니다. 이 경우 QC가 경고합니다.
- 입력은 WAV만 지원합니다(레퍼런스는 libsndfile이 읽는 형식이면 됩니다). 출력 비트 심도는 24-bit 고정입니다.
