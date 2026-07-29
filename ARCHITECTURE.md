# QuranReciteToText - Core Architecture & Technical Specification

This document provides the definitive, mathematically accurate specification for the Quran transcription pipeline. It is written for researchers, system architects, and AI agents who need to understand or debug the exact data flow and algorithmic decisions of the engine.

## Acknowledgements & Origins

This system is a lightweight CPU-optimized port of the **Quranic Universal Aligner** originally developed by [hetchyy](https://huggingface.co/spaces/hetchyy/quranic-universal-aligner). While the original system utilized heavy models requiring GPU acceleration on Gradio, this architecture is redesigned for efficiency:
- **Acoustic Model**: Uses a native ONNXRuntime implementation of the FastConformer model based on [Tilawa](https://github.com/yazinsai/tilawa) by [@yazinsai](https://github.com/yazinsai), executing entirely on the CPU.
- **VAD Segmenter**: Utilizes a lightweight Silero Voice Activity Detection engine that runs completely on the CPU.

## 1. System Overview

This pipeline takes a raw audio file of Quranic recitation and generates mathematically precise, word-by-word timestamps aligned exactly to the Uthmani text of the Quran.

The system enforces **100% CPU execution** and is highly optimized for extreme memory constraints. It avoids loading entire audio files into memory by utilizing an FFmpeg process pipe stream paired with **Silero VAD** (Voice Activity Detection) and **Sherpa-ONNX FastConformer**.

Furthermore, the system features **Auto-Environment Bootstrapping**. The `run.py` entrypoint is designed for a zero-configuration plug-and-play experience. When executed, it automatically verifies that all dependencies (including the local SDK wheel) are installed. If missing, it installs them via pip and dynamically restarts the process, requiring no manual setup from the user.

The pipeline operates in three distinct phases:
1. **Phase 1: Acoustic Transcription & VAD Segmentation** (FFmpeg streaming, Silero VAD, Kaldi Mel extraction, ONNXRuntime inference)
2. **Phase 2: Text Matching** (Anchoring and DP alignment to exact Uthmani text via `qua_sdk`)
3. **Phase 3: CTC Forced Alignment** (Viterbi forced alignment via `torchaudio` using FastConformer logprobs to extract frame-perfect timestamps)

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
- **Feeding & Async Parallel Execution Logic**:
  - Small PCM blocks (0.5s) are read sequentially from FFmpeg stdout and fed to `vad.accept_waveform(samples)`.
  - When `vad.is_speech_detected()` triggers, speech segments (`vad.front`) are popped and passed to `extract_speech_segment()`.
  - To maximize CPU utilization, the audio chunks are **asynchronously submitted** to a `ThreadPoolExecutor` (enabled via the `--fast` flag for 4 workers, or scaled higher via the `--workers N` flag). This streams the chunks directly to the ONNX model in real-time, completely parallelizing the transcription workload while the VAD continues detecting future segments.
  - Upon EOF, `vad.flush()` drains any trailing speech segments, and the executor gathers the perfectly chronological sequence of transcribed text via `future.result()`.

### 2.3 Native ONNXRuntime FastConformer Acoustic Engine (`fastconformer.py`)
- **Model**: NVIDIA NeMo FastConformer quantized to int8 (`fastconformer_ar_ctc_q8.onnx`). Auto-downloaded to `data/onnx/fastconformer_ar_ctc_q8.onnx` from the Tilawa GitHub release if missing.
- **Runtime**: `onnxruntime.InferenceSession` locked strictly to CPU (`intra_op_num_threads=2`, `inter_op_num_threads=2`). By dropping standard wrappers, the system gains direct access to the model's unadulterated probability distributions (`logprobs`).
- **Inference & Timestamp Extraction**:
  - Speech samples from each VAD segment are fed into `fc.transcribe(chunk_audio)`.
  - **Audio Preprocessing** (applied before inference):
    1. Safety resample to exactly 16kHz via librosa if sample rate mismatches.
    2. LUFS Loudness Normalization to -23 LUFS (EBU R128) via pyloudnorm — ensures equal recognition weight for quiet and loud passages.
    3. Peak limiting to prevent clipping artifacts.
  - **Feature Extraction**: `kaldi_native_fbank` computes 80-bin Mel Spectrograms (10ms shift, Hann window) exactly matching NeMo defaults. Per-feature Mean/Variance normalization is applied before forwarding to the neural network.
  - **CTC Logprobs Decoding**:
    - The model outputs the raw `logprobs` matrix.
    - Subwords starting with `▁` or space signal new word boundaries (`is_new_word`), and are collapsed into full Arabic words.
    - **Razor-Sharp Timestamping**: To find a word's physical boundary, the system identifies the subword activation peak, then iterates backwards and forwards frame-by-frame (80ms steps) until the CTC blank token (`BLANK_ID=1024`) probability exceeds 90% (`>0.9`). This ensures acoustically precise segmentation.
  - Timestamps are offset by `start_sec` (the VAD segment's start time relative to the full audio file) to establish global absolute time codes.
  - Text is normalized via `normalize_arabic()`.
  - Saves raw chunk transcription data to `raw_transcription.json`.

---

## 3. Phase 2: Dynamic Sequence Matching (`src/phase2_matching/`)

Phase 2 takes the raw, imperfect character strings (emissions) generated by Phase 1 and structurally forces them to align to the absolute truth of the Uthmani Quranic text using Dynamic Programming via the `qua_sdk`.

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

---

## 4. Phase 3: CTC Forced Alignment (`src/phase3_alignment/`)

Phase 3 assigns frame-perfect timestamps to every authenticated Uthmani word by running forced alignment over the acoustic model's probability distribution.

### 4.1 Viterbi CTC Forced Alignment (`ctc_align.py`)
- **Input**: Accepts the `logprobs` matrix generated in Phase 1 and the authenticated text from Phase 2.
- **Tokenization**: The authenticated text is tokenized into FastConformer BPE tokens (`tokens.txt`).
- **Forced Alignment (`torchaudio.functional.forced_align`)**: Uses the Viterbi algorithm to find the single most probable path through the CTC trellis that produces the target tokens.
- **Monotonic Label Parsing & Blank Distribution**: 
  - `torchaudio` returns the optimal target sequence labels frame-by-frame (80ms per frame).
  - Since CTC strongly peaks tokens (emitting them for just 1 frame), the algorithm distributes the surrounding `BLANK` frames intelligently (up to a max expansion bound of 320ms) to generate natural, contiguous spoken word boundaries that perfectly track the reciter's pace without drifting or artificially overlapping.

### 4.2 Boundary Enforcement & Exporting (`fused_split.py`, `export.py`)
- **Ayah Splitting**: After word timings are injected, `_split_fused_segments()` iterates through the data and cleanly cuts massive continuous VAD chunks into separate per-Ayah blocks, accurately tracking repetitions and jumps.
- **Exporting**: The data is exported via `export.py` into a robust JSON schema matching the original QUA specification perfectly, outputting `wrap_word_ranges` and `repeated_ranges` directly for downstream consumers.

---

## 5. Evolution from Original QUA

Unlike the original Quranic Universal Aligner which was designed as an interactive Gradio web app, this fork has been ruthlessly optimized for headless CLI execution:
- **Zero UI Bloat**: Over 700+ lines of interactive manual splitting, manual merging, undo/redo states, and legacy Gradio `gr.State` shapes were purged.
- **Pure CLI Export**: Bypassing UI data structures, the engine produces a clean `output.json` directly upon completion, achieving 1:1 schema parity with the original space.

---

## 6. AI Troubleshooting Guide

If you are an AI agent analyzing this repository to fix a bug, **use this guide**. Do not make assumptions about standard pipelines. Use the exact variables referenced in this document.

### Symptom: Audio streaming fails or ffmpeg process crashes
- **Likely Culprit**: FFmpeg is missing from PATH or input audio format is unreadable.
- **Action**: Check `src/phase1_transcribe/stream.py`. Ensure `ffmpeg` and `ffprobe` are installed and accessible in system PATH. Check stdout pipe reading in `run_asr_cpu()`.

### Symptom: VAD drops initial speech or speech is cut prematurely
- **Likely Culprit**: Silero VAD thresholds in `stream.py` are too aggressive.
- **Action**: Open `src/phase1_transcribe/stream.py`. Inspect `config.silero_vad.min_silence_duration` (default 0.8s), `threshold` (default 0.15), and `min_speech_duration` (default 0.15s). Adjust according to recitation speed and background noise.

### Symptom: Model loading error or blank prediction output
- **Likely Culprit**: Missing `fastconformer_ar_ctc_q8.onnx` file or `tokens.txt` mismatch.
- **Action**: Ensure both the model and the `tokens.txt` vocabulary file are properly downloaded into `data/onnx/`.

### Symptom: The alignment completely fails, returning random characters
- **Likely Culprit**: Character normalization failure between the Acoustic Model and the SDK.
- **Action**: Open `src/phase2_matching/normalize.py`. Ensure the `normalize_arabic` regex is correctly mapping the ASR's output alphabet to the SDK's expected Uthmani alphabet.

### Symptom: Word timestamps drift off the audio or overlap
- **Likely Culprit**: The CTC blank frame distribution algorithm in `src/phase3_alignment/ctc_align.py`.
- **Action**: Check `_frames_to_word_times`. Ensure `torchaudio.functional.forced_align` is returning labels correctly, and that the `MAX_EXPAND` blank distribution logic is cleanly midpoint-splitting the blanks without exceeding `MAX_EXPAND`.

### Symptom: Crash `TypeError: process_audio() got an unexpected keyword argument`
- **Likely Culprit**: Legacy Gradio UI code.
- **Action**: All web logic (`html`, `device`, `is_preset`) was purged. If a script passes these kwargs to `process_audio` in `main_flow.py`, delete them.
