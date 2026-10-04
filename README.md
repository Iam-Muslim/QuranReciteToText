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
  <a href="#python-api">Python API</a> &bull;
  <a href="#output-files">Output Files</a> &bull;
  <a href="#optional-montreal-forced-aligner---mfa">MFA (Optional)</a> &bull;
  <a href="#benchmarks">Benchmarks</a>
</p>

</div>

---

## Features

- **Optional Montreal Forced Aligner (MFA)**: Built-in support for secondary 10ms phone-level refinement via `--mfa` using pre-trained [Quran Hafs acoustic models](https://huggingface.co/Quran-Lab/mfa-quran-hafs), alongside the default fast Zipformer CTC aligner.
- **Word & Letter Timestamps**: Millisecond-accurate start and end boundaries for each word and its individual Tajweed phonemes.
- **Automatic Surah & Ayah Detection**: Identifies recited verses automatically from audio without needing text input or prior labels.
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

# Run alignment (dependencies and default models auto-setup on first run)
python run.py --audio recitation.mp3
```

> [!NOTE]
> Missing Python packages and the default acoustic model ([Quran-Lab/zipformer_p-arabic-v3](https://huggingface.co/Quran-Lab/zipformer_p-arabic-v3)) are downloaded and configured automatically.

Supported audio formats: `.mp3`, `.wav`, `.m4a`, `.ogg`, `.flac`.

---

## CLI Usage

```bash
# Default mode: built-in CTC aligner (no external tools required)
python run.py --audio recitation.mp3

# Fast parallel mode: utilizes all physical CPU cores
python run.py --audio recitation.mp3 --fast

# Progress mode: streams single-line JSON events to stdout for frontends/APIs
python run.py --audio recitation.mp3 --fast --progress
```

### Options

| Option | Description |
| :--- | :--- |
| `--audio <path>` | Path to input recitation audio file (`.mp3`, `.wav`, `.m4a`, etc.). |
| `--fast` | Auto-configures parallel workers for maximum CPU throughput. |
| `--progress` | Emits single-line JSON progress events to `stdout`. |
| `--workers <n>` | Explicit number of worker processes. |
| `--threads <n>` | ONNX execution threads per worker. |
| `--mfa` | Optional secondary alignment using Montreal Forced Aligner. |

<details>
<summary><small>View sample JSON progress stream (--progress)</small></summary>

```json
{"stage": "vad", "elapsed": 0.35}
{"stage": "transcribing", "percent": 50.0, "elapsed": 1.2, "speed_x": 32.0}
{"stage": "transcribing", "percent": 100.0, "elapsed": 2.4, "speed_x": 31.5}
{"stage": "completed", "audio_duration": 112.5, "processing_time": 3.8, "total_time": 4.1, "real_time_factor": 27.4}
```

</details>

---

## Python API

```python
from src import AudioPipeline

# 1. Initialize pipeline
pipeline = AudioPipeline()
pipeline.initialize()

# 2. Process recitation audio file
result = pipeline.process_audio_file(
    audio_file_path="recitation.mp3",
    output_dir="./output"
)

# 3. Read aligned verses, words, and letter phonemes
for segment in result.segments:
    print(f"\nSurah {segment.surah_number}, Ayah {segment.ayah} [{segment.start_time:.2f}s -> {segment.end_time:.2f}s]")
    for word in segment.words:
        print(f"  {word.word:<12} [{word.start:.2f}s -> {word.end:.2f}s] ({word.location})")
        for ph in (word.phonemes or []):
            print(f"    - {ph['phoneme']:<4} [{ph['start']:.2f}s -> {ph['end']:.2f}s]")
```

---

## Output Files

All output files are saved to `./output`:

| File | Description |
| :--- | :--- |
| **`output.json`** | Canonical JSON with Ayahs, words, Uthmani text, locations, and phoneme timings. |
| **`ctc_aligned_phonemes.json`** | All recognized Tajweed phonemes aligned to exact audio frame boundaries. |
| **`raw_transcription.json`** | Raw unconstrained phonemes and detected pause timestamps. |
| **`recovered_speech.json`** | Diagnostics of acoustic speech recovery events. |

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
| Full Juz' (Juz' Amma) | 1h 05m | ~2m 10s | **~30x RTF** |

---

## How It Works

1. **Silence & Pause Detection**: Chunks audio at natural breath pauses (*Waqf*) while protecting held vowels (*Madd*) and consonant stop closures (*Qalqalah*).
2. **Phoneme Recognition**: The Zipformer-v3 INT8 model transcribes each chunk into Arabic Tajweed phonemes.
3. **CTC Forced Alignment**: Banded Viterbi alignment calculates exact audio boundaries for each phoneme.
4. **Text Matching**: Matches recognized phonemes against the Quran reference to determine Surah/Ayah and build word boundaries.

---

## Optional: Montreal Forced Aligner (`--mfa`)

The default built-in CTC aligner handles alignment out-of-the-box without MFA.

If you want an additional 10ms phone refinement pass using Montreal Forced Aligner:

1. Download [`quran_hafs_acoustic.zip`](https://huggingface.co/Quran-Lab/mfa-quran-hafs) from Hugging Face.
2. Place `quran_hafs_acoustic.zip` into the `data/mfa/` directory.
3. Run with the `--mfa` flag:
   ```bash
   python run.py --audio recitation.mp3 --mfa
   ```

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
