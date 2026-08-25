ربنا تقبل منا انك انت السميع العليم
بفضل الله و برحمته الحمد لله رب العالمين

# Quran Recite to Text (Lightweight CPU Edition — Letter & Word Tajweed Timing)

An automated, high-performance, lightweight CPU pipeline for transcribing and forced-aligning Quranic recitations with the exact Medina Mushaf text. It produces **frame-perfect, millisecond-accurate timestamps at the segment, word, and individual letter/Tajweed phoneme level** using the **Zipformer-v3 Arabic Tajweed Phoneme CTC model**.

<img width="1379" height="869" alt="1787559568-409220-image" src="https://github.com/user-attachments/assets/ae615cf9-9d1b-493a-a706-f845c1a2fc56" />

##  Quick Start

### 1. Run Alignment CLI

Place your recitation audio (`audio.mp3`) in the project directory and run:

```bash
# High-speed parallel mode (recommended, defaults to 4 CPU workers)
python run.py --audio audio.mp3 --out output.json --fast

# Scale to more CPU cores for long recitations (e.g. 8 cores)
python run.py --audio audio.mp3 --out output.json --fast --workers 8
```

The resulting `output.json` contains full Ayah segments, word timestamps, and letter-level phoneme breakdowns.

### 2. View in the Modern UI Viewer

Double-click or open ui/viewer.html
1. Load your generated `output.json` (or drag and drop it anywhere).
2. Load your audio file (`audio.mp3` / `.wav`).
3. Enjoy smooth letter-by-letter and word-by-word karaoke synchronization!

---

## 📄 JSON Output Schema

```json
{
  "segments": [
    {
      "segment": 1,
      "time_from": 0.56,
      "time_to": 3.8,
      "ref_from": "46:1:1",
      "ref_to": "46:1:1",
      "matched_text": "حمٓ",
      "confidence": 0.98,
      "has_missing_words": false,
      "has_repeated_words": false,
      "words": [
        {
          "word": "حمٓ",
          "location": "46:1:1",
          "start": 0.0,
          "end": 3.24,
          "phonemes": [
            { "phoneme": "حَ", "start": 0.0, "end": 0.08 },
            { "phoneme": "اا", "start": 0.08, "end": 0.28 },
            { "phoneme": "مِ", "start": 0.28, "end": 1.12 },
            { "phoneme": "ۦۦۦۦۦۦ", "start": 1.12, "end": 2.36 },
            { "phoneme": "م", "start": 2.36, "end": 2.92 }
          ]
        }
      ]
    }
  ]
}
```

---

## Benchmark Performance

| Benchmark Audio | Audio Length | ASR Transcription | Full Alignment | Real-Time Factor |
| :--- | :--- | :--- | :--- | :--- |
| **Surah Al-Ahqaf Sample** | `15.00s` | `0.95s` | `1.45s` | **10.3x Faster** |
| **Surah At-Tawbah (Full)** | `3,042.41s` (~50.7 min) | `81.56s` (~1.3 min) | `161.77s` (~2.6 min) | **37.3x Faster** |

---


* **Original Concept**:  by [Hetchy's Quranic Universal Aligner](https://huggingface.co/spaces/hetchyy/quranic-universal-aligner).
**Model**: [Zipformer Arabic Tajweed Phoneme CTC Model](https://github.com/Iam-Muslim/QuranReciteToText/releases).
* **Silence Segmentation**: [Munajjam PR #65 Adaptive Silence Engine](https://github.com/Itqan-community/Munajjam/pull/65).
