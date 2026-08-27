"""Global Configuration & Path Definitions."""

import os
from pathlib import Path

# Base directories
PROJECT_ROOT = Path(__file__).parent.absolute()
DATA_PATH = PROJECT_ROOT / "data"

# Quran Uthmani Script Reference
QURAN_SCRIPT_PATH_COMPUTE = DATA_PATH / "qpc_hafs.json"

# Word Timestamp Tuning Controls
ENABLE_WORD_SMOOTHING = False
WORD_SMOOTHING_MAX_STRETCH_S = 2.0
ENABLE_MISSING_WORD_INJECTION = False

# Gap Retranscription Controls (Missed Words & Repetitions Recovery)
ENABLE_GAP_RETRANSCRIPTION = False
GAP_RETRANSCRIPTION_MIN_DURATION_S = 1.0
GAP_RETRANSCRIPTION_ENERGY_THRESHOLD_DB = -28.0
GAP_RETRANSCRIPTION_SPLIT_FALLBACK = False
