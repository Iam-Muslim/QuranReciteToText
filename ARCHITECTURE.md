# QuranReciteToText - Core Architecture & Technical Specification

This document provides the definitive, mathematically rigorous specification for the Quran transcription and alignment pipeline. It is written for researchers, system architects, and AI agents who need to understand or debug the exact data flow and algorithmic decisions of the engine.

---

## 1. System Overview

The pipeline takes raw Quranic recitation audio and generates mathematically precise, word-by-word and letter-by-letter timestamps aligned exactly to the Medina Mushaf text.

The system enforces **100% CPU execution** and is optimized for minimal memory usage. It streams audio directly through an FFmpeg process pipe paired with **Munajjam PR #65 Adaptive Silence Engine** and the **Zipformer-v3 Tajweed Phoneme CTC model (`zipformer_p_arabic_v3.int8.onnx`)**.

The pipeline operates in four distinct phases:
1. **Phase 1: Acoustic Transcription & Silence Segmentation** (Munajjam PR #65 Engine, Kaldi Povey Fbank extraction, ONNXRuntime Zipformer streaming inference).
2. **Phase 2: Text Matching** (6-Gram phonetic anchoring and Needleman-Wunsch DP alignment via `qua_sdk`).
3. **Phase 3: CTC Forced Alignment & Pure Acoustic Midpoint Timing** (Viterbi state-path trellis evaluation and midpoint boundary assignment over 251 Tajweed phonemes).
4. **Phase 4: Text-Based Ayah Splitting & JSON Export** (Surgical text-based Ayah boundary slicing and recursive phoneme re-offsetting).

---

## 2. Phase 1: Acoustic Transcription (`src/phase1_transcribe/`)

### 2.1 Audio Ingestion & FFmpeg Streaming (`stream.py`)
- Accepts audio file paths or `(sample_rate, numpy_array)` data.
- Spawns an FFmpeg pipe to resample input to 16kHz mono float32 without loading large files into memory:
  ```bash
  ffmpeg -v quiet -i <path> -f f32le -acodec pcm_f32le -ac 1 -ar 16000 pipe:1
  ```
- Reads standard output in sequential 0.5s chunks (`8,000` samples = `32,000` bytes).

### 2.2 Munajjam PR #65 Adaptive Silence Engine
- Segments the incoming stream on natural pauses (Waqf) using RMS peak-relative energy thresholding (`top_db`).
- **4-Level Progressive Relaxation Loop**: If fewer chunks than expected are detected ($\text{expected} \approx \max(3, \text{int}(\text{dur} / 8.0))$), the threshold is automatically relaxed down to 50ms to ensure zero speech is dropped.
- **Audacity-Style Midpoint Cuts**: Chunks include 200ms pre-roll and post-roll context padding, placing the cut dead-center in the silence to avoid clipping consonants.
- **Asynchronous Worker Pool (`ThreadPoolExecutor`)**: Submits chunks in parallel to the Zipformer session (defaults to 4 workers, scalable via `--workers N`).

### 2.3 Native ONNXRuntime Zipformer-v3 Acoustic Engine (`zipformer.py`)
- **Model**: `zipformer_p_arabic_v3.int8.onnx` (quantized INT8, 251 Tajweed phoneme vocabulary in `tokens.txt`).
- **Feature Extraction**: Strict Kaldi Povey Fbank (80 bins, 16kHz, 25.0ms window, 10.0ms shift, DC removal, 0.97 preemphasis).
- **Streaming Step**: 48 frames (480ms step), 61 frames window (610ms), right context 13 frames.
- **Frame Rate**: Emits dense log-probability matrices $[T, 251]$ at **25.0 Hz (40ms per frame)**.
- Blank Token: `BLANK_ID = 250`.

---

## 3. Phase 2: Dynamic Sequence Matching (`src/phase2_matching/`)

### 3.1 Canonical Phoneme Ingestion (`normalize.py`)
- Ingests `data/ordered_quran_phonemes.json` spanning all 6,236 Ayahs and 77,433 words.
- Maps Medina Mushaf orthography to canonical Tajweed phoneme sequences (e.g. `حمٓ` $\to$ `['حَ', 'اا', 'مِ', 'ۦۦۦۦۦۦ', 'م']`).
- Builds a 6-gram phonetic index (`PhonemeNgramIndex`, 283,141 n-grams).

### 3.2 Needleman-Wunsch DP Matcher (`matcher.py`)
- Matches raw acoustic token emissions against the reference database using C++ dynamic programming (`qua_sdk`).
- Resolves multi-chapter transitions, Basmala/Isti'adha templates, and reciter repetitions (wraparound DP tracking).

---

## 4. Phase 3: CTC Forced Alignment & Pure Acoustic Midpoint Timing (`src/phase3_alignment/`)

### 4.1 Viterbi Trellis State Path (`ctc_align.py`)
For a target sequence of $N$ phonemes $c_0, \dots, c_{N-1}$, the Viterbi trellis constructs $L = 2N + 1$ states alternating between `BLANK_ID` and token IDs:
$$S = [\text{BLANK}, c_0, \text{BLANK}, c_1, \dots, \text{BLANK}, c_{N-1}, \text{BLANK}]$$
The dynamic programming recurrence computes:
$$V(t, s) = \log P(S_s \mid t) + \max_{d \in \{0, 1, 2\}} V(t-1, s-d)$$
Backtracking produces the exact state sequence $s_t \in [0, 2N]$ for all frames $t=0 \dots T-1$.

### 4.2 Pure Acoustic Midpoint Boundary Assignment
For each token $k \in [0, N-1]$, its peak acoustic frame in the Viterbi trellis is:
$$\text{peak}(k) = \arg\max_{t \in \{t \mid s_t = 2k+1\}} \log P(c_k \mid t)$$

The transition boundary between token $k$ and token $k+1$ is computed as the exact acoustic midpoint:
$$\text{boundary}(k, k+1) = \frac{\text{peak}(k) + \text{peak}(k+1)}{2}$$

#### Acoustic Guarantees:
1. **Zero Artificial Rules**: Uniform mathematical treatment across Madds, Shaddahs, Ghunnas, vowels, and consonants.
2. **Held Sounds Get Their Full Vocalized Duration**: Elongated vowels (e.g., 6-count Madds) and held consonants (e.g., Noon/Meem Mushaddadah) naturally span their entire acoustic duration ($0.4\text{s} \dots 2.5\text{s}$).
3. **Preservation of Final Letters**: Word-ending consonants (e.g. Waqf Sukoon `م`, `نَ`, `بِ`) receive their genuine acoustic decay ($0.12\text{s} \dots 0.56\text{s}$) rather than being cut off.
4. **Strict Zero-Overlap ($s_{k+1} \equiv e_k$)**: Consecutive phonemes connect continuously with zero gap and zero overlap.

---

## 5. Phase 4: Surgical Ayah Splitting & Export (`src/phase4_splitting/`)

### 5.1 Fused Segment Splitting (`ayah_split.py`, `fused_split.py`)
- Analyzes multi-Ayah VAD segments against canonical verse boundaries.
- Slices segments precisely at the Ayah boundary frames.
- Recursively offsets nested word and phoneme timestamps ($t_{\text{rel}} = t_{\text{abs}} - t_{\text{seg\_start}}$).

### 5.2 Dedup & VAD Fusion (`src/core/dedup_segments.py`)
- Detects false VAD splits in the same Ayah where silence gap is $< 40\text{ms}$.
- Fuses adjacent chunks and recursively offsets nested phoneme arrays, guaranteeing zero cross-segment overlap.

---

## 6. Modern UI Architecture (`ui/viewer.html`)

- **Design Philosophy**: Distraction-free, OLED-dark luxury Quranic reading canvas.
- **Letter & Word Karaoke Synchronization**:
  - Word level: Golden glowing halo on active word.
  - Letter level: Emerald teal active pill highlighting on individual Tajweed sounds.
  - Strict inequality matching ($t \ge p_{\text{start}} \land t < p_{\text{end}}$) guarantees exactly one active sound at any millisecond.
- **Controls**: Floating glassmorphic player capsule, Spacebar shortcut, seekbar with fill animation, playback speed selector ($0.75\times \dots 1.5\times$), automatic centering auto-scroll.
