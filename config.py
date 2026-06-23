import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.absolute()
DATA_PATH = PROJECT_ROOT / "data"

# Quran script paths
QURAN_SCRIPT_PATH_COMPUTE = DATA_PATH / "qpc_hafs.json"
QURAN_SCRIPT_PATH_DISPLAY = DATA_PATH / "digital_khatt_v2_script.json"

# Audio & Alignment Settings
RESAMPLE_TYPE = "soxr_lq"
SEGMENT_AUDIO_DIR = Path("/tmp/segments")

# Auto-merge
AUTO_MERGE_GROUP_PREFIX = "merge-auto-"

# CPU / GPU execution configs
CPU_DTYPE = os.environ.get("CPU_DTYPE", "bfloat16").lower()
AUDIO_CACHE_MAX_ENTRIES = int(os.environ.get("AUDIO_CACHE_MAX_ENTRIES", "32"))
PHONEME_ALIGNMENT_PROFILING = True
ZEROGPU_MAX_DURATION = 120

def get_vad_duration(minutes):
    """GPU seconds needed for VAD based on audio minutes."""
    VAD_LEASE_BUFFER = 5
    return max(3, 0.28 * minutes + 1.66 + VAD_LEASE_BUFFER)

def get_asr_duration(minutes, model_name="Base"):
    """GPU seconds needed for ASR, scales linearly with audio duration."""
    if model_name == "Large":
        ASR_LEASE_BUFFER = 6.54
        return max(3, 0.0579 * minutes + 1.72 + ASR_LEASE_BUFFER)
    ASR_LEASE_BUFFER = 4.5
    return max(3, 0.0198 * minutes + 0.32 + ASR_LEASE_BUFFER)
