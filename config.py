"""Global Configuration & Audio/Model Specifications."""

import sys
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

# Speech Recovery Controls (Fallback)
ENABLE_SPEECH_RECOVERY: bool = False
SPEECH_RECOVERY_ENERGY_THRESHOLD_DB: float = -35.0
SPEECH_RECOVERY_MIN_HOLE_DURATION_S: float = 0.40
SPEECH_RECOVERY_PADDING_S: float = 0.20
SPEECH_RECOVERY_MIN_PHONEMES_IN_GAP: int = 2

# Streaming Zipformer State Reset on Silence
# Resets internal recurrent states when silence is detected between Ayahs / Waqf pauses.
# Default is True. Set to False to disable state reset.
RESET_ENCODER_ON_SILENCE: bool = True
SILENCE_RESET_CONSECUTIVE_BLANK_CHUNKS: int = 2  # 2 chunks = 2 * 0.48s = 0.96s of silence

# Runtime Performance & Profiling
DEFAULT_NUM_THREADS = 2
ENABLE_PROFILING = True

# Backwards compatibility alias for PipelineConfig namespace
PipelineConfig = sys.modules[__name__]
