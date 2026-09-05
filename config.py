"""Global Configuration & Path Definitions matching Dart PipelineConfig."""

import os
from pathlib import Path

# Base directories
PROJECT_ROOT = Path(__file__).parent.absolute()
DATA_PATH = PROJECT_ROOT / "data"

# Model and resource paths
ONNX_DIR = DATA_PATH / "onnx"
DEFAULT_MODEL_PATH = str(ONNX_DIR / "zipformer_p_arabic_v3.int8.onnx")
DEFAULT_TOKENS_PATH = str(ONNX_DIR / "tokens.txt")
DEFAULT_QURAN_PHONEMES_PATH = str(DATA_PATH / "ordered_quran_phonemes.json")
DEFAULT_REF_NORM_PH_PATH = str(DATA_PATH / "ref_norm_ph.txt")
DEFAULT_PH_INDEX_PATH = str(DATA_PATH / "ph_index.npy")

# Audio specifications
SAMPLE_RATE = 16000
BLANK_ID = 250
FRAME_RATE = 25.0  # 40ms per encoder frame (25 Hz)
FRAME_STEP = 1.0 / FRAME_RATE  # 0.040s
LOOKAHEAD_OFFSET_FRAMES = 1.5  # -60ms streaming lookahead delay compensation
CTC_BLANK_PENALTY = 1.8  # Trellis blank prior regularization

# Phase 1.1: Energy-Aware Speech & Repetition Recovery Controls
ENABLE_SPEECH_RECOVERY = False
SPEECH_RECOVERY_ENERGY_THRESHOLD_DB = -35.0
SPEECH_RECOVERY_MIN_HOLE_DURATION_S = 0.40
SPEECH_RECOVERY_PADDING_S = 0.20
SPEECH_RECOVERY_MIN_PHONEMES_IN_GAP = 2  # Refuse single-phoneme noise artifacts

# Phase 3: Quran Text Matcher (Pluggable)
ENABLE_MATCHING = True

# Runtime Performance & Profiling
DEFAULT_NUM_THREADS = 2
ENABLE_PROFILING = True


class PipelineConfig:
    """Namespace matching Dart PipelineConfig class."""
    sample_rate: int = SAMPLE_RATE
    blank_id: int = BLANK_ID
    frame_rate: float = FRAME_RATE
    frame_step: float = FRAME_STEP
    lookahead_offset_frames: float = LOOKAHEAD_OFFSET_FRAMES
    ctc_blank_penalty: float = CTC_BLANK_PENALTY

    enable_speech_recovery: bool = ENABLE_SPEECH_RECOVERY
    speech_recovery_energy_threshold_db: float = SPEECH_RECOVERY_ENERGY_THRESHOLD_DB
    speech_recovery_min_hole_duration_s: float = SPEECH_RECOVERY_MIN_HOLE_DURATION_S
    speech_recovery_padding_s: float = SPEECH_RECOVERY_PADDING_S
    speech_recovery_min_phonemes_in_gap: int = SPEECH_RECOVERY_MIN_PHONEMES_IN_GAP

    enable_matching: bool = ENABLE_MATCHING
    default_num_threads: int = DEFAULT_NUM_THREADS
    enable_profiling: bool = ENABLE_PROFILING

    default_model_path: str = DEFAULT_MODEL_PATH
    default_tokens_path: str = DEFAULT_TOKENS_PATH
    default_quran_phonemes_path: str = DEFAULT_QURAN_PHONEMES_PATH
    default_ref_norm_ph_path: str = DEFAULT_REF_NORM_PH_PATH
    default_ph_index_path: str = DEFAULT_PH_INDEX_PATH
