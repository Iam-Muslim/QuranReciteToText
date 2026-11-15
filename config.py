"""Global Configuration & Tuning Dashboard for QuranReciteToText.

This is the SINGLE FILE to tune matching parameters, edit costs, repetition penalties,
and acoustic silence thresholds across the entire pipeline.
"""

from pathlib import Path

# ==============================================================================
# 1. BASE DIRECTORIES & RESOURCE PATHS
# ==============================================================================
PROJECT_ROOT = Path(__file__).parent.absolute()
DATA_PATH = PROJECT_ROOT / "data"

DEFAULT_MODEL_DIR = str(DATA_PATH / "model")
DEFAULT_DLL_PATH = str(DATA_PATH / "bin" / "zf_tajweed.dll")
DEFAULT_SILERO_PATH = str(DATA_PATH / "onnx" / "silero_vad_half.onnx")
DEFAULT_TOKENS_PATH = str(DATA_PATH / "model" / "tokens.txt")
DEFAULT_EXPECTED_ZFX_PATH = str(DATA_PATH / "model" / "expected_tj3.zfx")
DEFAULT_QPC_HAFS_PATH = str(DATA_PATH / "qpc_hafs.json")
DEFAULT_OUTPUT_DIR = str(PROJECT_ROOT / "output")
EXPORT_ALL_ARTIFACTS: bool = True


# ==============================================================================
# 2. AUDIO & ACOUSTIC SPECIFICATIONS
# ==============================================================================
SAMPLE_RATE: int = 16000
BLANK_ID: int = 0                           # TajweedFormer blank token index (<blk>)
VOCAB_SIZE: int = 38                        # TajweedFormer 38-token vocabulary
TAJWEEDFORMER_CONTEXT: str = "c24_l256"     # Peak accuracy & throughput (480ms chunk, 10.2s context)
FRAME_RATE: float = 50.0                    # 20ms per fine encoder frame (50 Hz)
FRAME_STEP: float = 1.0 / FRAME_RATE        # 0.020s (TajweedFormer V4 fine acoustic timing)
CLIP_AUDIO_PEAKS: bool = True               # Soft guard against clipping > 1.0
NUM_SEGMENT_WORKERS: int = 1                # 1 = sequential 0-overhead stream; >1 = parallel LPT worker streams
RESET_ENCODER_ON_SILENCE: bool = True       # Reset TajweedFormer streaming encoder state at Waqf silence pauses
COLLECT_ACOUSTIC_MATRICES: bool = True      # Collect log_probs (40ms) and timing_log_probs (20ms) matrices

# ==============================================================================
# 3. PHASE 1 UNIFIED TAJWEED ACOUSTIC SILENCE & PAUSE ENGINE (VAD)
# ==============================================================================
VAD_BACKEND: str = "silero_dual_check"      # "energy" or "silero_dual_check"
VAD_SILERO_THRESHOLD: float = 0.45          # Silero speech onset probability threshold
VAD_MADD_PERIODICITY_TH: float = 0.45       # Normalized autocorrelation peak for held Madd ("ييييي")
VAD_MADD_MIN_ENERGY_DB: float = -38.0       # Minimum floor dB for held letter detection
VAD_MIN_PAUSE_S: float = 0.40               # Natural Waqf pause threshold (seconds)
VAD_SAKT_MIN_PAUSE_S: float = 0.16          # Sakt pause detection threshold (seconds)
VAD_CLOSURE_MAX_S: float = 0.14             # Max intra-word stop closure / Qalqalah bridge (seconds)
VAD_ADAPTIVE: bool = True                   # Dynamic noise-floor adaptation
VAD_ONSET_DB: float = -35.0                 # Fallback speech onset energy threshold (dB)
VAD_OFFSET_DB: float = -42.0                # Fallback speech offset energy threshold (dB)
VAD_HANGOVER_S: float = 0.08                # 80ms hangover buffer
VAD_MAX_PAD_S: float = 0.25                 # 250ms clean silence margin on both sides of each segment
VAD_PREROLL_S: float = 0.20                 # 200ms pre-roll margin
SUBSEGMENT_MIN_PAUSE_S: float = 9999.0      # Disabled (9999): Keep 1 unified segment per Ayah for clean UI timeline 
PAUSE_CUT_MARGIN_S: float = 0.08            # Tolerance window (seconds) to anchor acoustic pause cut between words
PAUSE_INTERVAL_OVERLAP_S: float = 0.12      # Maximum pause interval boundary overlap (seconds) with adjacent words
SNAP_TO_VAD_SEGMENT_BOUNDARIES: bool = False # Optional: snap first/last phoneme of segment to VAD raw cuts


# ==============================================================================
# 4. PHASE 2 TAJWEEDFORMER ASR & SPEECH RECOVERY
# ==============================================================================
ENABLE_SPEECH_RECOVERY: bool = False
SPEECH_RECOVERY_MODE: str = "legacy"        # "legacy" or "adaptive"
SPEECH_RECOVERY_MIN_HOLE_DURATION_S: float = 1.40
SPEECH_RECOVERY_PADDING_PRE_S: float = 0.16
SPEECH_RECOVERY_PADDING_POST_S: float = 0.24
SPEECH_RECOVERY_MIN_PHONEMES_IN_GAP: int = 2


# ==============================================================================
# 5. PHASE 3  TEXT MATCHING & WRAPAROUND TUNING
# ==============================================================================
COST_SUBSTITUTION: float = 1.00             # Standard substitution penalty
COST_DELETION: float = 1.00                 # Standard deletion penalty
COST_INSERTION: float = 0.75                # Standard insertion penalty
ACOUSTIC_CONFUSION_COST: float = 0.25       # Cost for acoustically similar pairs (ت/ط, د/ض, Madd vs Harakat)

# Repetition Penalties
WRAP_PENALTY: float = 0.80                  # Regularization penalty to prevent false backward jumps
WRAP_SPAN_WEIGHT: float = 0.05              # Additional cost per word spanned in backward jump

# Word Coverage Filtering (Prevents false words and phantom repetitions from stray phonemes)
MIN_WORD_COVERAGE: float = 0.35             # Minimum fraction of reference phonemes required to accept a word pass


# ==============================================================================
# 5.1 SURAH DISCOVERY & DETECTOR TUNING
# ==============================================================================
DETECTOR_ERROR_RATIO: float = 0.20          # Max Myers bit-parallel error tolerance for global detection
DETECTOR_MIN_PHONEMES: int = 12             # Minimum phonemes required to trigger detection probe


