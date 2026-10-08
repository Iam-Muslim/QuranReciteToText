<div align="right" dir="rtl">

<sub>ربنا تقبل منا انك انت السميع العليم &bull; الحمد لله رب العالمين &bull; بفضل الله وبرحمته </sub>

</div>
<img width="1200" height="286" alt="New Project (4)" src="https://github.com/user-attachments/assets/596ee40b-9289-429c-9d49-867f48f39b5e" />

<div align="center">

# Quran Recite to Text
### Lightweight CPU Pipeline for Quran Recitation Transcription & Tajweed Alignment

[![Python Version](https://img.shields.io/badge/Python-3.11-3776AB?logo=python&logoColor=white)](https://python.org)
[![Inference Engine](https://img.shields.io/badge/Inference-ONNX%20Runtime%20CPU-005CED?logo=onnx&logoColor=white)](https://onnxruntime.ai)
[![Speed](https://img.shields.io/badge/Speed-20x%20--%2040x%20RTF%20(CPU)-brightgreen)](#benchmarks)

<br/>

<img width="560" alt="QuranReciteToText Preview" src="https://github.com/user-attachments/assets/ae615cf9-9d1b-493a-a706-f845c1a2fc56" />

<br/>
<br/>

<p align="center">
  <a href="#features">Features</a> &bull;
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

- **Neural Zipformer CTC Forced Alignment (Recommended)**: Powered by a 65.5M-parameter Transformer model trained on 59,000+ hours of recitation for fast, sub-frame, highly accurate word and Tajweed phoneme boundaries.
- **Montreal Forced Aligner (MFA) [Experimental / Research Only]**: Optional secondary alignment pass via `--mfa` using pre-trained [Quran Hafs acoustic models](https://huggingface.co/Quran-Lab/mfa-quran-hafs). *Note: MFA is experimental and NOT recommended for general use; stick to the default neural CTC aligner for production alignment.*
- **Word & Letter Timestamps**: Millisecond-accurate start and end boundaries for each word and its individual Tajweed phonemes.
- **Automatic Surah & Ayah Detection**: Identifies recited verses automatically from audio without needing text input or prior labels.
- **Batch Directory Processing**: Recursively processes folders of audio or video recitations, preserving folder trees, exporting per-file `<stem>.json` files, and generating merged `all_surahs.json` sets.
- **Handles Pauses, Restarts & Repetitions**: Sequence matcher natively tracks reciter pauses (*Waqf*), restarts (*Ibtida'*), and repeated verses (*Takrar*) without breaking timeline alignment.
- **Tajweed Acoustic VAD ("Madd Guardian")**: Specialized silence detection protects prolonged vowels (*Madd* 2/4/6 counts) and plosive stop closures (*Qalqalah*).
- **Tajweed Boundary Repair**: Automatically reconciles cross-word assimilations like Idgham (with/without Ghunnah), Iqlab, and Shaddah.
- **Prayer & Taraweeh Compatible**: Handles Istiaadha, Basmalah, and prayer Takbeers (`الله أكبر`) without distorting verse alignment.
- **Fast CPU Inference (20x–40x RTF)**: Runs offline on consumer CPUs using quantized INT8 ONNX models. No GPU or PyTorch required.
- **100% Offline & Private**: Zero external cloud calls, telemetry, or network dependencies.

---

## Quick Start

```bash
git clone https://github.com/Iam-Muslim/QuranReciteToText.git
cd QuranReciteToText

# Process a single audio/video file
python run.py --audio recitation.mp3

# Or process an entire folder recursively
python run.py --dir ./my_recitations
```

> [!NOTE]
> Missing Python packages and the default acoustic model ([Quran-Lab/zipformer_p-arabic-v3](https://huggingface.co/Quran-Lab/zipformer_p-arabic-v3)) are downloaded and configured automatically.

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
Generates 5 files in `./output`:

| File | Description |
| :--- | :--- |
| **`output.json`** | Canonical JSON with Surahs, Ayahs, words, Uthmani text, locations, and phoneme timings. |
| **`ctc_aligned_phonemes.json`** | All recognized Tajweed phonemes aligned to exact audio frame boundaries. |
| **`raw_transcription.json`** | Raw unconstrained phonemes and detected pause timestamps. |
| **`recovered_speech.json`** | Diagnostics of acoustic speech recovery events. |
| **`qurancaption_segments.json`** | Segments format ready for QuranCaption subtitle generators. |

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

1. **Silence & Pause Detection**: Chunks audio at natural breath pauses (*Waqf*) while protecting held vowels (*Madd*) and consonant stop closures (*Qalqalah*).
2. **Phoneme Recognition**: The Zipformer-v3 INT8 model transcribes each chunk into Arabic Tajweed phonemes.
3. **CTC Forced Alignment**: Banded Viterbi alignment calculates exact audio boundaries for each phoneme.
4. **Text Matching**: Matches recognized phonemes against the Quran reference to determine Surah/Ayah and build word boundaries.

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

<div align="center">
<sub><b>Integration</b>: Automatically generates <code>output/qurancaption_segments.json</code> for 1-click use with <a href="https://github.com/zonetecde/QuranCaption">QuranCaption</a></sub>
</div>


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
