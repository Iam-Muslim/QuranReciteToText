<div align="right" dir="rtl">

<sub>ربنا تقبل منا انك انت السميع العليم &bull; الحمد لله رب العالمين &bull; بفضل الله وبرحمته </sub>

</div>
<img width="1200" height="286" alt="New Project (4)" src="https://github.com/user-attachments/assets/596ee40b-9289-429c-9d49-867f48f39b5e" />

<div align="center">

# Quran Recite to Text
### Lightweight CPU Pipeline for Quran Recitation Transcription & Tajweed Alignment

[![Python Version](https://img.shields.io/badge/Python-3.11-3776AB?logo=python&logoColor=white)](https://python.org)
[![Inference Engine](https://img.shields.io/badge/Inference-TajweedFormer%20V4%20C--Engine-005CED?logo=c&logoColor=white)](https://quranlab.ai)
[![Speed](https://img.shields.io/badge/Speed-20x%20--%2040x%20RTF%20(CPU)-brightgreen)](#benchmarks)

<br/>

<img width="560" alt="QuranReciteToText Preview" src="https://github.com/user-attachments/assets/ae615cf9-9d1b-493a-a706-f845c1a2fc56" />

<br/>
<br/>

<p align="center">
  <a href="#features">Features</a> &bull;
  <a href="#model-setup">Model Setup</a> &bull;
  <a href="#quick-start">Quick Start</a> &bull;
  <a href="#cli-usage">CLI Usage</a> &bull;
  <a href="#batch-directory-processing---dir">Batch Processing</a> &bull;
  <a href="#python-api">Python API</a> &bull;
  <a href="#output-files">Output Files</a> &bull;
  <a href="#benchmarks">Benchmarks</a>
</p>

</div>

---

## Features

- **TajweedFormer V4 Native C-Engine**: Powered by the exact TajweedFormer V4 acoustic model and portable C runtime (`zf_tajweed.dll`) for ultra-fast, 20ms fine timing, and sub-frame accurate word and Tajweed phoneme boundaries.
- **Word & Letter Timestamps**: Millisecond-accurate start and end boundaries for each word and its individual Tajweed phonemes.
- **Automatic Surah & Ayah Detection**: Identifies recited verses automatically from audio without needing text input or prior labels.
- **Batch Directory Processing**: Recursively processes folders of audio or video recitations, preserving folder trees, exporting per-file `<stem>.json` files, and generating merged `all_surahs.json` sets.
- **Handles Pauses, Restarts & Repetitions**: Sequence matcher natively tracks reciter pauses (*Waqf*), restarts (*Ibtida'*), and repeated verses (*Takrar*) without breaking timeline alignment.
- **Tajweed Acoustic VAD ("Madd Guardian")**: Specialized silence detection protects prolonged vowels (*Madd* 2/4/6 counts) and plosive stop closures (*Qalqalah*).
- **Tajweed Boundary Repair**: Automatically reconciles cross-word assimilations like Idgham (with/without Ghunnah), Iqlab, and Shaddah.
- **Prayer & Taraweeh Compatible**: Handles Istiaadha, Basmalah, and prayer Takbeers (`الله أكبر`) without distorting verse alignment.
- **Fast CPU Inference (15x–30x RTF)**: Runs offline on consumer CPUs using the exact native C TajweedFormer inference engine. No GPU or PyTorch required.
- **100% Offline & Private**: Zero external cloud calls, telemetry, or network dependencies.

---

## Model Setup (QuranLab TajweedFormer V4)

QuranReciteToText uses the **TajweedFormer V4** neural acoustic model architecture developed by [QuranLab](https://quranlab.ai).

> [!IMPORTANT]
> **No Automated Model Downloads**: To keep this repository lightweight, clean, and 100% offline, TajweedFormer V4 model files are **not bundled in Git** and are **never downloaded automatically** in the background. You must obtain the model files from [quranlab.ai](https://quranlab.ai) and place them in the `data/model/` folder.

### Required Model Directory Structure

Ensure the model files from [quranlab.ai](https://quranlab.ai) are placed in `data/model/` as follows:

```text
QuranReciteToText/
└── data/
    ├── bin/
    │   └── zf_tajweed.dll              # Windows native C inference runtime
    └── model/
        ├── tokens.txt                  # 38-token Tajweed acoustic vocabulary
        ├── expected_tj3.zfx            # Precomputed reference phonemes for all 114 Surahs
        ├── frontend.zfw                # Shared audio front-end filterbank feature weights
        ├── layers.zfw                  # Core TajweedFormer acoustic model weights (~65 MB)
        ├── calibration.json            # Model calibration thresholds & head params
        └── c24_l256/                   # Primary execution context (recommended)
            ├── frames.zfw              # Context frame buffer weights
            ├── model_engine2.onnx      # ONNX execution graph
            ├── model_engine2.onnx.zfg  # Compiled fast execution graph definition
            └── model_engine2.onnx.zfg.bin # Binary graph parameters
```

### Required Files Breakdown

| File / Folder | Purpose & Specification |
| :--- | :--- |
| **`tokens.txt`** | Vocabulary mapping of the 38 acoustic tokens: blank (`<blk>`), word delimiter (`|`), Arabic consonants, short vowels (`a`, `i`, `u`), and long vowels (`aa`, `ii`, `uu`). |
| **`expected_tj3.zfx`** | Compact binary reference containing the canonical expected phoneme sequence for every Ayah across all 114 Surahs. |
| **`frontend.zfw`** | Filterbank and feature extraction neural weights used by the native C-engine. |
| **`layers.zfw`** | Deep acoustic transformer weights common across all context window configurations. |
| **`c24_l256/`** | The recommended inference context (24-frame / 480ms chunk size, 256-frame / 10.2s left context) delivering optimum phoneme accuracy and high RTF speed. |
| **`calibration.json`** | Model calibration parameters for fine confidence thresholds. |
| **`data/bin/zf_tajweed.dll`** | Native C runtime library for Windows (or `libzf_tajweed.so` on Linux) delivering 20ms fine timing without PyTorch or external heavy runtimes. |

*(Note: The lightweight Silero VAD model at `data/onnx/silero_vad_half.onnx` is automatically fetched if not present).*

---

## Quick Start

```bash
git clone https://github.com/Iam-Muslim/QuranReciteToText.git
cd QuranReciteToText

# 1. Place the TajweedFormer V4 model files in data/model/ (see Model Setup above)

# 2. Process a single audio/video file
python run.py --audio recitation.mp3

# 3. Or process an entire folder recursively
python run.py --dir ./my_recitations
```

**Supported Media Formats**:
- **Audio**: `.mp3`, `.wav`, `.m4a`, `.flac`, `.ogg`, `.opus`, `.aac`, `.wma`, `.aiff`
- **Video Containers**: `.webm`, `.mp4`, `.mkv`, `.mov`, `.avi`, `.m4v`, `.flv`

---

## CLI Usage

```bash
# 1. Single file alignment
python run.py --audio recitation.mp3

# 2. Batch directory processing (recursive)
python run.py --dir ./my_recitations

# 3. Maximum CPU throughput (parallel workers)
python run.py --audio recitation.mp3 --fast
python run.py --dir ./my_recitations --fast

# 4. Stream real-time JSON progress for frontends / APIs
python run.py --audio recitation.mp3 --fast --progress
python run.py --dir ./my_recitations --fast --progress

# 5. Canonical qiraat translation (Warsh, Qalun, Al-Duri, etc.)
python run.py --audio recitation_warsh.mp3 --qiraat warsh
python run.py --dir ./warsh_recitations --qiraat warsh --fast

# 6. Interactive prompt (drag & drop file or folder)
python run.py
```

### Options

| Option | Description |
| :--- | :--- |
| `--audio <path>` | Path to a single input recitation file (`.mp3`, `.wav`, `.webm`, etc.). Mutually exclusive with `--dir`. |
| `--dir <folder>` | Path to a directory for recursive batch processing. Preserves subfolders, outputs `<stem>.json` for each file, and creates `all_surahs.json`. |
| `--fast` | Auto-configures parallel workers for maximum CPU throughput. |
| `--qiraat <name>` | Canonical recitation tradition (`hafs` (default), `warsh`, `qaloon`, `duri`, `susi`, `bazzi`, `qunbul`, `shubah`, `hisham`, `ibn_wardan`). Translates verse numbers, verse splits, and merges to the reciter's Mushaf with 0-overhead bypass for Hafs. |
| `--progress` | Streams single-line JSON events to stdout for frontends/UIs/APIs. |

<details>
<summary><small>View sample JSON progress streams (--progress)</small></summary>

**Single-File Mode:**
```json
{"stage": "vad", "elapsed": 0.35}
{"stage": "transcribing", "percent": 50.0, "elapsed": 1.2, "speed_x": 32.0}
{"stage": "transcribing", "percent": 100.0, "elapsed": 2.4, "speed_x": 31.5}
{"stage": "completed", "audio_duration": 112.5, "processing_time": 3.8, "total_time": 4.1, "real_time_factor": 27.4}
```

**Batch Directory Mode:**
```json
{"stage": "batch_start", "total_files": 114}
{"stage": "batch_file_done", "index": 1, "total": 114, "file": "001.mp3", "saved": "output/001.json", "elapsed": 1.25}
{"stage": "batch_file_done", "index": 2, "total": 114, "file": "002.webm", "saved": "output/002.json", "elapsed": 12.40}
{"stage": "batch_completed", "total_files": 114, "succeeded": 114, "failed": 0, "total_time": 128.5}
```

</details>

---

## Batch Directory Processing (`--dir`)

When processing collections of recitations, `--dir` scans the target folder recursively, mirrors the folder hierarchy into `output/`, and creates clean production JSON files.

### Folder Mapping

```text
Input Directory (e.g. ./my_audio):
my_audio/
├── 001.mp3
├── 002.webm
└── reciter_husary/
    ├── 112.m4a
    └── 114.wav

Output Directory (./output):
output/
├── 001.json                 # Aligned Surah 1 (same schema as output.json)
├── 002.json                 # Aligned Surah 2
├── all_surahs.json          # Consolidated & sorted Surahs for root level
└── reciter_husary/
    ├── 112.json             # Aligned Surah 112
    ├── 114.json             # Aligned Surah 114
    └── all_surahs.json      # Consolidated & sorted Surahs for reciter_husary
```

### Batch Output Rules
1. **Stem-Matched JSON**: Every media file outputs an individual JSON named after its filename stem (`1.mp3` $\rightarrow$ `1.json`, `recitation.webm` $\rightarrow$ `recitation.json`). Each file shares the exact canonical schema with `output.json`.
2. **Consolidated `all_surahs.json`**: Generated in each directory folder containing media. All Surahs are sorted numerically ($1 \dots 114$) with Ayahs ordered sequentially, preserving each Surah's `intro` (Basmalah / Isti'adha).
3. **Clean Output**: Debug files (`raw_transcription.json`, `recovered_speech.json`, etc.) are omitted during batch runs to keep directories neat and compact.

### Common Batch Scenarios

#### Scenario 1: Complete Quran / Surah Collection
Transcribe a flat folder of Surahs (`001.mp3` through `114.mp3`):
```bash
python run.py --dir ./quran_audio --fast
```
*Result*: Produces `001.json` ... `114.json` plus a single unified `all_surahs.json` containing the entire aligned Quran.

#### Scenario 2: Multi-Reciter / Subfolder Organization
Organize audio by reciter or qiraat:
```text
audio/
├── mishary/
│   ├── 001.mp3
│   └── 002.mp3
└── minshawi/
    └── 001.mp3
```
```bash
python run.py --dir ./audio --fast
```
*Result*: Output structure perfectly mirrors the input: `output/mishary/all_surahs.json` and `output/minshawi/all_surahs.json`.

#### Scenario 3: Mixed Audio & Video Files
Process mixed folders containing `.mp3`, `.m4a`, and `.webm` video files seamlessly without converting them first:
```bash
python run.py --dir ./recordings
```

---

## Python API

```python
from src import AudioPipeline

# 1. Initialize pipeline
pipeline = AudioPipeline()
pipeline.initialize()

# 2. Option A: Process a single file
result = pipeline.process_audio_file(
    audio_file_path="recitation.mp3",
    output_dir="./output"
)

# Access segments, words, and Tajweed phonemes
for segment in result.segments:
    print(f"\nSurah {segment.surah_number}, Ayah {segment.ayah} [{segment.start_time:.2f}s -> {segment.end_time:.2f}s]")
    for word in segment.words:
        print(f"  {word.word:<12} [{word.start:.2f}s -> {word.end:.2f}s] ({word.location})")
        for ph in (word.phonemes or []):
            print(f"    - {ph['phoneme']:<4} [{ph['start']:.2f}s -> {ph['end']:.2f}s]")

# 2. Option B: Batch process an entire directory
summary = pipeline.process_directory(
    input_dir="./my_recitations",
    output_dir="./output",
    live_profile=True,
)
print(f"Batch complete: {len(summary['succeeded'])}/{summary['total_files']} files processed successfully.")
```

---

## Output Files

Depending on the execution mode, outputs are saved to `./output`:

### Single-File Mode (`--audio`)
Generates production-ready artifacts in `./output`:

| File | Description |
| :--- | :--- |
| **`output.json`** | Canonical JSON with Surahs, Ayahs, words, Uthmani text, locations, and phoneme timings. |
| **`raw_transcription.json`** | Recognized Tajweed phonemes, timestamps, and detected pause intervals. |
| **`recovered_speech.json`** | *(Optional)* Diagnostic telemetry of speech gap recovery (only emitted when enabled in `config.py`). |

### Batch Directory Mode (`--dir`)
Generates clean, production-ready JSON files mirroring the source directory structure:

| File | Description |
| :--- | :--- |
| **`<filename>.json`** | Canonical JSON for each media file (uses the exact same schema as `output.json`). |
| **`all_surahs.json`** | Consolidated and numerically sorted Surahs ($1 \dots 114$) with sequential Ayahs and preserved `intro` for each folder. |

<details>
<summary><b>View sample output.json payload</b></summary>

```json
{
  "total_surahs": 1,
  "surahs": [
    {
      "surah": 1,
      "ayahs": [
        {
          "ayah": 1,
          "start": 0.48,
          "end": 3.92,
          "matched_ref": "1:1:1-1:1:4",
          "segments": [
            {
              "segment": 1,
              "start": 0.48,
              "end": 3.92,
              "words": [
                {
                  "word": "بِسْمِ",
                  "location": "1:1:1",
                  "start": 0.48,
                  "end": 1.12,
                  "score": 0.98,
                  "phonemes": [
                    { "phoneme": "بِ", "start": 0.48, "end": 0.70 },
                    { "phoneme": "سْ", "start": 0.70, "end": 0.94 },
                    { "phoneme": "مِ", "start": 0.94, "end": 1.12 }
                  ]
                }
              ]
            }
          ]
        }
      ]
    }
  ]
}
```

</details>

---

## Benchmarks

Tested on a consumer laptop CPU (AMD Ryzen 7 / Intel Core i7, CPU only):

| Recitation | Audio Duration | Processing Time (`--fast`) | Speed |
| :--- | :---: | :---: | :---: |
| Short (Al-Fatiha) | 42s | ~1.3s | **~32x RTF** |
| Medium (Ar-Rahman) | 14m 20s | ~26s | **~33x RTF** |

---

## How It Works

The entire pipeline executes in 4 sequential phases:

1. **Phase 1: Silence & VAD Detection**: Chunks audio at natural breath pauses (*Waqf*) while protecting held vowels (*Madd*) and consonant stop closures (*Qalqalah*).
2. **Phase 2: Acoustic Phoneme Transcribing**: The native C TajweedFormer V4 engine transcribes each chunk into 38-token Tajweed phonemes with direct 20ms-level timing and neural confidence.
3. **Phase 3:  Text Alignment**: Matches recognized phonemes against the reference  Mushaf using Myers bit-parallel discovery and dynamic sequence alignment to resolve Surah/Ayah and accurate word boundaries.
4. **Phase 4: JSON Artifact Export**: Generates canonical `output.json` and `raw_transcription.json`.

---

<details>
<summary><b>Tuning & Configuration (config.py)</b></summary>

Parameters can be adjusted in [`config.py`](config.py):
- `SAMPLE_RATE`: Audio sample rate (default: `16000`).
- `VAD_MIN_PAUSE_S`: Minimum pause threshold for Waqf splitting (default: `0.20s`).
- `VAD_MADD_PERIODICITY_TH`: Autocorrelation threshold protecting held Madd vowels (default: `0.45`).
- `COST_SUBSTITUTION` / `WRAP_PENALTY`: Dynamic sequence matching costs.
- `DEFAULT_OUTPUT_DIR`: Target export folder (default: `./output`).

</details>

---

## License (لوجه الله تعالى)

### **مَا أَسْأَلُكُمْ عَلَيْهِ مِنْ أَجْرٍ ۖ إِنْ أَجْرِيَ إِلَّا عَلَىٰ رَبِّ الْعَالَمِينَ**

> **THIS PACKAGE AND SOURCE CODE ARE DEDICATED FOR THE SAKE OF ALLAH ALONE.**

Before viewing, using, distributing, or modifying any part of this repository, you explicitly agree to the following covenants:

1. **100% Free to End Users**:
   You may use, study, and redistribute this software or its logic **ONLY** in applications and services that are completely free of charge to all end users forever.
2. **Strict Prohibition on Commercialization & Profit**:
   You are **STRICTLY FORBIDDEN** from selling this application, placing it behind paywalls, subscription models, in-app purchases, charging download fees, monetizing it with advertisements (AdMob, Unity Ads, etc.), or extracting any financial revenue from this codebase, models, or outputs.
3. **Pass-Through**:
   These terms are immutable and strictly pass on to any fork, derivative work, or redistributed component.

---------

**Allah subhanu guided me in this work and it is only his guidance and work from Allah subhanu , Thanks to Allah only <3 , I'm his servant**

[QuranLab models](https://quranlab.ai)

[Qiraat Mapping](https://github.com/Iam-Muslim/ReciteQuran/pull/5)

----------------

**Elhamdule Allah  ,That victory from Allah subhanu alone**

Projects using :

[**QuranCaption**](https://github.com/zonetecde/QuranCaption)

[**Qalun-Timing**](https://github.com/Jawad18750/qalun-timing)
