# QuranReciteToText Architecture & Pipeline Guide

`QuranReciteToText` is an offline, high-precision Quran recitation transcription and forced-alignment engine (100% pure Python / Dart parity). It takes an audio recitation file and generates frame-accurate word-level and letter-level timestamps aligned to the Medina Mushaf (Hafs 'an 'Asim).

---

## 1. Directory Structure

The repository mirrors the modern Flutter/Dart engine (`ReciteQuran`) structure 1-to-1:

```
QuranReciteToText/
├── config.py                       # Global paths, audio specs, and PipelineConfig
├── run.py                          # CLI runner
├── requirements.txt                # Pure Python dependencies (no C++ wheels, no qua_sdk)
├── data/
│   ├── onnx/                       # Zipformer INT8 acoustic models & tokens.txt
│   ├── ordered_quran_phonemes.json # Medina Mushaf phoneme sequence reference
│   ├── ref_norm_ph.txt             # 311k normalized Medina phoneme reference text
│   └── ph_index.npy                # (311886, 7) uint16 binary Quran index
└── src/
    ├── core/                       # Core shared models, decoding & orchestration
    │   ├── audio_decoder.py        # Audio loading, decoding & loudness normalization
    │   ├── main_flow.py            # Central 4-phase coordinator (AudioPipeline & process_audio)
    │   └── models.py               # Unified data models matching Dart models.dart
    ├── phase1_transcriber/         # Phase 1: Pure ONNX CTC Transcription & Speech Recovery
    │   ├── transcriber.py          # ZipformerONNX / OfflineTranscriber
    │   └── speech_recovery.py      # Energy-aware speech & repetition hole recovery
    ├── phase2_aligner/             # Phase 2: CTC Viterbi Trellis Forced Alignment
    │   └── ctc_aligner.py          # Dynamic programming Viterbi trellis & acoustic crossover
    ├── phase3_matcher/             # Phase 3: Tajweed Phonetic Matcher & Ayah Sequencer
    │   ├── matcher_config.py       # Scoring thresholds & presets (normal, easy, strict)
    │   ├── phonetic_cost_engine.py # Tajweed & acoustic confusion cost engine
    │   ├── dictation_matcher.py    # Semi-global DTW with free lead-in noise skipping
    │   ├── dictation_sequencer.py  # Continuous word stream sequencer & repetition state machine
    │   ├── quran_word_matcher.py   # Preamble detection, Ayah partitioning & BaseQuranMatcher
    │   └── surah_finder/           # Global fast Quran search
    │       ├── fuzzy_search.py     # Gene Myers' 64-bit Bit-Parallel Substring Search
    │       ├── phonetic_search.py  # Binary NPY index search engine
    │       ├── multi_surah_finder.py# Single/multi-Surah timeline clustering
    │       └── models.py           # SurahMatchSpan, SurahAudioBlock, etc.
    └── phase4_export/              # Phase 4: Post-Processing, Sub-Segmentation & JSON Export
        └── quran_json_exporter.py  # Pause calculation, Waqf sub-segments & 4 JSON exports
```

---

## 2. Four-Phase Pipeline Flow

```
[Input Audio 16kHz PCM]
       │
       ▼
[AudioDecoder] (src/core/audio_decoder.py)
       │ Decodes & normalizes audio (-23 LUFS / RMS target)
       ▼
[Phase 1: Pure ONNX Zipformer CTC Transcription] (src/phase1_transcriber/transcriber.py)
       │ Outputs raw_phonemes + logprobs_matrix (T x 251)
       ▼
[Phase 1.1: Authentic Speech & Repetition Recovery] (src/phase1_transcriber/speech_recovery.py)
       │ Slices audio gaps (energy > -35dB, duration >= 0.40s), re-transcribes with context padding
       │ Outputs effective_phonemes + recovery_events + recovery_summary
       ▼
[Phase 2: CTC Viterbi Trellis Forced Alignment] (src/phase2_aligner/ctc_aligner.py)
       │ 6-stage DP Trellis forward/backtrack + acoustic crossover + -60ms lookahead delay
       │ Outputs aligned_phonemes (frame-accurate acoustic bounds)
       ▼
[Phase 3: Tajweed Quran Text Matcher & Sequencer] (src/phase3_matcher/quran_word_matcher.py)
       │ MultiSurahFinder & PhoneticSearch (Myers 64-bit Bit-Parallel search on binary NPY index)
       │ PhoneticCostEngine (Tajweed acoustic substitution, insertion, deletion matrix)
       │ QuranDictationMatcher (Semi-Global DTW with free lead-in noise skipping)
       │ DictationSequencer (In-order tracking, Wasl merging, omissions, backward repetitions)
       │ Outputs matched Ayahs, Words, Prologues (Isti'adhah/Basmalah) & Repetitions
       ▼
[Phase 4: Post-Processing, Sub-Segmentation & JSON Export] (src/phase4_export/quran_json_exporter.py)
       │ Inter-word pause calculation (> 1.0s)
       │ Waqf breath-phrase sub-segmentation & repetition isolation
       │ Exports 4 canonical JSON files:
       │   1. raw_transcription.json
       │   2. recovered_speech.json
       │   3. ctc_aligned_phonemes.json
       │   4. output.json
```

---

## 3. Key Data Contracts

* **`PhonemeToken`**: Individual acoustic token with frame bounds and peak confidence:
  `{ "phoneme": "بِ", "start": 0.12, "end": 0.32, "confidence": 0.95 }`
* **`QuranWord`**: Aligned Medina Mushaf word:
  `{ "word": "بِسْمِ", "location": "1:1:1", "start": 0.12, "end": 0.68, "score": 1.0 }`
* **`AyahSubSegment`**: Natural breath-phrase inside an Ayah:
  `{ "sub_segment": 1, "start_time": 0.12, "end_time": 3.54, "text": "بِسْمِ ٱللَّهِ ٱلرَّحْمَـٰنِ ٱلرَّحِيمِ", "words_range": "1:1:1-1:1:4" }`
* **`QuranSegment`**: Canonical 1-Ayah segment containing metadata, words, sub-segments, repetitions, and prologue.
