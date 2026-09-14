ربنا تقبل منا انك انت السميع العليم
بفضل الله و برحمته الحمد لله رب العالمين

# Quran Recite to Text (Lightweight CPU Edition — Letter & Word Tajweed Timing)

An automated, high-performance, lightweight CPU pipeline for transcribing and forced-aligning Quranic recitations with the exact Medina Mushaf text. It produces **frame-perfect, millisecond-accurate timestamps at the segment, word, and individual letter/Tajweed phoneme level** using the **Zipformer-v3 Arabic Tajweed Phoneme CTC model**.

<img width="1379" height="869" alt="1787559568-409220-image" src="https://github.com/user-attachments/assets/ae615cf9-9d1b-493a-a706-f845c1a2fc56" />

##  Quick Start

### 1. Run Alignment CLI

Place your recitation audio (`audio.mp3`) in the project directory and run:

```bash
# High-speed parallel mode (defaults to 4 workers)
python run.py --audio audio.mp3 --workers 4

```

The resulting `output.json` contains full Ayah segments, word timestamps, and letter-level phoneme breakdowns.

### 2. View in the Modern UI Viewer

Double-click or open `output/ui.html`
1. Load your generated `output.json` (or drag and drop it anywhere).
2. Load your audio file (`audio.mp3` / `.wav`).
3. Enjoy smooth letter-by-letter and word-by-word  synchronization!

---



* **Original Concept**:  by [Hetchy's Quranic Universal Aligner](https://huggingface.co/spaces/hetchyy/quranic-universal-aligner).
**Model**: [Zipformer Arabic Tajweed Phoneme CTC Model](https://github.com/Iam-Muslim/QuranReciteToText/releases).
