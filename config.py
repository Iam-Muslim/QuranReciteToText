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

# Speech Recovery Controls
ENABLE_SPEECH_RECOVERY = False
SPEECH_RECOVERY_ENERGY_THRESHOLD_DB = -35.0
SPEECH_RECOVERY_MIN_HOLE_DURATION_S = 0.40
SPEECH_RECOVERY_PADDING_S = 0.20
SPEECH_RECOVERY_MIN_PHONEMES_IN_GAP = 2

# Runtime Performance & Profiling
DEFAULT_NUM_THREADS = 2
ENABLE_PROFILING = True

# Backwards compatibility alias for PipelineConfig namespace
PipelineConfig = sys.modules[__name__]
