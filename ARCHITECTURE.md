# QuranReciteToText - Core Architecture & Technical Specification

This document provides the definitive, mathematically accurate specification for the Quran transcription pipeline. It is written for researchers, system architects, and AI agents who need to understand or debug the exact data flow and algorithmic decisions of the engine.

## Acknowledgements & Origins

This system is a lightweight CPU-optimized port of the **Quranic Universal Aligner** originally developed by [hetchyy](https://huggingface.co/spaces/hetchyy/quranic-universal-aligner). While the original system utilized heavy models requiring GPU acceleration on Gradio, this architecture is redesigned for efficiency:
- **Acoustic Model**: Uses a fast, lightweight Sherpa-ONNX FastConformer model based on [Tilawa](https://github.com/yazinsai/tilawa) by [@yazinsai](https://github.com/yazinsai).
- **VAD Segmenter**: Utilizes a lightweight Silero Voice Activity Detection engine that runs completely on the CPU.

## 1. System Overview

This pipeline takes a raw audio file of Quranic recitation and generates mathematically precise, word-by-word timestamps aligned exactly to the Uthmani text of the Quran.

The system enforces **100% CPU execution** and is highly optimized for extreme memory constraints. It avoids loading entire audio files into memory by utilizing an FFmpeg process pipe stream paired with **Silero VAD** (Voice Activity Detection) and **Sherpa-ONNX FastConformer**.

Furthermore, the system features **Auto-Environment Bootstrapping**. The `run.py` entrypoint is designed for a zero-configuration plug-and-play experience. When executed, it automatically verifies that all dependencies (including the local SDK wheel) are installed. If missing, it installs them via pip and dynamically restarts the process, requiring no manual setup from the user.

The pipeline operates in two distinct phases:
1. **Phase 1: Acoustic Transcription & VAD Segmentation** (FFmpeg streaming, Silero VAD segmentation, Sherpa-ONNX FastConformer inference)
2. **Phase 2: Dynamic Sequence Matching** (Forced alignment to exact Uthmani text via character-level Needleman-Wunsch DP)

---

## 2. Phase 1: Acoustic Transcription (`src/phase1_transcribe/`)

Phase 1 handles audio ingestion, silence/speech segmentation via VAD, and acoustic model inference. It completely replaces legacy overlapping sliding window approaches with dynamic Silero VAD segmentation to skip non-speech silences and eliminate chunk overlap calculation overhead.

### 2.1 Audio Loading & FFmpeg Pipe Streaming (`main_flow.py`, `stream.py`)
To maintain zero-memory footprint on large audio files, audio is ingested directly through an FFmpeg process pipe.
- **Input Ingestion (`main_flow.py`)**: Accepts file paths (`str`) or `(sample_rate, numpy_array)` tuples.
  - For file paths: The file path is passed directly to `run_asr_cpu()` in `stream.py` without loading the full file into Python memory.
  - For numpy arrays: Input is normalized to float32, averaged to mono, and resampled to 16kHz via FFmpeg pipe (`_resample_audio_ffmpeg`) if original rate != 16000Hz.
- **FFmpeg Pipe Stream (`stream.py`)**:
  - `ffprobe` is called first to obtain precise audio duration: `ffprobe -v error -show_entries format=duration ...`.
  - Spawns `ffmpeg -v quiet -i <path> -f f32le -acodec pcm_f32le -ac 1 -ar 16000 pipe:1`.
  - Reads stdout in small blocks of `0.5s` (`8000` samples = `32,000` bytes of float32 PCM data).

### 2.2 Silero VAD Engine & Audio Feeding (`stream.py`)
Voice Activity Detection segments the incoming raw PCM stream into clean, continuous speech segments based on natural pauses (waqf).
- **VAD Model**: `silero_vad.onnx` executed via `sherpa-onnx` (`sherpa_onnx.VoiceActivityDetector`).
  - Auto-downloaded to `data/onnx/silero_vad.onnx` if missing.
- **VAD Tuning Parameters (Ultra-Sensitive for Quran)**:
  - `sample_rate`: 16000 Hz.
  - `min_silence_duration`: 0.8s (prevents splitting mid-Waqf pauses between Ayahs).
  - `threshold`: 0.15 (ultra-sensitive — catches soft Arabic consonants ع,ح,ه,خ and vowel tails).
  - `min_speech_duration`: 0.15s (keeps very short Ayahs like طه, يس).
  - `max_speech_duration`: 30.0s (prevents mega-chunks exhausting model context window).
  - `buffer_size_in_seconds`: 30.0s.
- **Context Padding**: 500ms preroll and 500ms postroll of real audio around each VAD segment, preventing mid-consonant cuts at boundaries.
- **Feeding Logic**:
  - Small PCM blocks (0.5s) are read sequentially from FFmpeg stdout and fed to `vad.accept_waveform(samples)`.
  - When `vad.is_speech_detected()` triggers, speech segments (`vad.front`) are popped and passed to `process_speech_segment()`.
  - Upon EOF, `vad.flush()` drains any trailing speech segments.

### 2.3 Sherpa-ONNX FastConformer Acoustic Engine (`fastconformer.py`)
- **Model**: NVIDIA NeMo FastConformer quantized to int8 (`fastconformer_ar_ctc_q8.onnx`). Auto-downloaded to `data/onnx/fastconformer_ar_ctc_q8.onnx` from the Tilawa GitHub release if missing.
- **Metadata**: Required ONNX metadata (`model_type="nemo_ctc"`, `vocab_size="1024"`, `subsampling_factor="8"`) is injected via `inject_metadata.py`.
- **Runtime**: `sherpa_onnx.OfflineRecognizer.from_nemo_ctc` locked strictly to CPU (`num_threads=2`, `feature_dim=80`, `decoding_method='greedy_search'`).
- **Inference & Timestamp Extraction**:
  - Speech samples from each VAD segment are fed into `fc.transcribe(chunk_audio)`.
  - **Audio Preprocessing** (applied before inference):
    1. Safety resample to exactly 16kHz via librosa if sample rate mismatches.
    2. LUFS Loudness Normalization to -23 LUFS (EBU R128) via pyloudnorm — ensures equal recognition weight for quiet and loud passages.
    3. Peak limiting to prevent clipping artifacts.
  - CTC subword tokens and token-level timestamps are decoded from Sherpa-ONNX stream result.
  - Subwords starting with `▁` or space signal new word boundaries (`is_new_word`).
  - Subwords are merged into full Arabic words with start and end timestamps.
  - Timestamps are offset by `start_sec` (the VAD segment's start time relative to the full audio file) to establish global absolute time codes.
  - Text is normalized via `normalize_arabic()`.
  - Saves raw chunk transcription data to `raw_transcription.json`.

---

## 3. Phase 2: Dynamic Sequence Matching (`src/phase2_matching/`)

Phase 2 takes the raw, imperfect character strings (emissions) generated by Phase 1 and structurally forces them to align to the absolute truth of the Uthmani Quranic text using Dynamic Programming.

### 3.1 Normalization & Tokenization (`normalize.py`)
Before sequence matching can occur, the ASR string outputs must mathematically map to the SDK's expected alphabet.
- **Diacritic Stripping**: `normalize_arabic()` aggressively strips all tashkeel, Quranic punctuation, Ayah markers (۝), Hizb (۞), Sajdah (۩), Tatweel (ـ), and numbers.
- **Alphabet Homogenization**:
  - Normalizes Alef variants (`إأآٱ` -> `ا`).
  - Normalizes Yaa variants (`ىي` -> `ي`).
  - Converts Taa Marbutah to Haa (`ة` -> `ه`), as the acoustic model overwhelmingly emits Haa for terminal Taa Marbutah.
- **Phoneme Sequences**: The cleaned string is passed to `qua_sdk.domain.chapter_refs.RefWord` as an explicit array of individual characters (`phonemes=list(norm_text) + [' ']`). This forces the downstream DP engine to calculate character-level edit distances.

### 3.2 The Needleman-Wunsch DP Matcher (`matcher.py`)
- **The Engine**: The heavy lifting is offloaded to the highly optimized C++ `qua_sdk` engine (`MatchingResources`).
- **N-Gram Anchoring**: The engine utilizes an N-Gram voting system (10-character N-grams) to find "anchors" (highly confident starting points) in the audio emissions (`find_anchor_by_voting`).
- **Dynamic Programming**: Starting from the anchor point, the engine executes a strict Needleman-Wunsch DP alignment matrix (`run_matching_sequence`), resolving exactly where imperfectly spoken words map to the perfect reference text.
- **DP Word Timestamp Interpolation**: `align_words_dp()` aligns recognized ASR words to true Uthmani reference words using Needleman-Wunsch DP to assign precise per-word start and end timestamps.

### 3.3 Boundary Enforcement & Splitting (`split.py`)
- The raw DP matcher outputs continuous segment blocks.
- `_split_fused_segments()` iterates through aligned words and splits them back into per-Ayah bounds whenever a word crosses an Ayah boundary, Surah boundary, or repetition wrap-around.

---

## 4. AI Troubleshooting Guide

If you are an AI agent analyzing this repository to fix a bug, **use this guide**. Do not make assumptions about standard pipelines. Use the exact variables referenced in this document.

### Symptom: Audio streaming fails or ffmpeg process crashes
- **Likely Culprit**: FFmpeg is missing from PATH or input audio format is unreadable.
- **Action**: Check `src/phase1_transcribe/stream.py`. Ensure `ffmpeg` and `ffprobe` are installed and accessible in system PATH. Check stdout pipe reading in `run_asr_cpu()`.

### Symptom: VAD drops initial speech or speech is cut prematurely
- **Likely Culprit**: Silero VAD thresholds in `stream.py` are too aggressive.
- **Action**: Open `src/phase1_transcribe/stream.py`. Inspect `config.silero_vad.min_silence_duration` (default 0.8s), `threshold` (default 0.15), and `min_speech_duration` (default 0.15s). Adjust according to recitation speed and background noise.

### Symptom: Sherpa-ONNX model loading error / Missing metadata
- **Likely Culprit**: `fastconformer_ar_ctc_q8.onnx` is missing required ONNX metadata keys.
- **Action**: Run `python inject_metadata.py` to inject required properties (`model_type="nemo_ctc"`, `vocab_size="1024"`, `subsampling_factor="8"`) into the ONNX binary.

### Symptom: The alignment completely fails, returning random characters
- **Likely Culprit**: Character normalization failure between the Acoustic Model and the SDK.
- **Action**: Open `src/phase2_matching/normalize.py`. Ensure the `normalize_arabic` regex is correctly mapping the ASR's output alphabet to the SDK's expected Uthmani alphabet.

### Symptom: Word timestamps drift off the audio
- **Likely Culprit**: `align_words_dp()` in `matcher.py` or subword token timestamp reconstruction in `fastconformer.py`.
- **Action**: Inspect `FastConformerONNX.transcribe()` in `src/phase1_transcribe/fastconformer.py` for token grouping logic, and `align_words_dp()` in `src/phase2_matching/matcher.py`.

### Symptom: Crash `TypeError: process_audio() got an unexpected keyword argument`
- **Likely Culprit**: Legacy Gradio UI code.
- **Action**: All web logic (`html`, `device`, `is_preset`) was purged. If a script passes these kwargs to `process_audio` in `main_flow.py`, delete them.
