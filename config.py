"""Global Configuration & Tuning Dashboard for QuranReciteToText.

This is the SINGLE FILE to tune matching parameters, edit costs, repetition penalties,
CTC alignment blank weights, and acoustic silence thresholds across the entire pipeline.
"""

import os
from pathlib import Path

# ==============================================================================
# 1. BASE DIRECTORIES & RESOURCE PATHS
# ==============================================================================
PROJECT_ROOT = Path(__file__).parent.absolute()
DATA_PATH = PROJECT_ROOT / "data"

ONNX_DIR = DATA_PATH / "onnx"
MODEL_DIR = Path(os.environ.get("QC_WORD_TIMING_MODEL_DIR", ONNX_DIR))
DEFAULT_MODEL_PATH = str(MODEL_DIR / "zipformer_p_arabic_v3.int8.onnx")
DEFAULT_SILERO_PATH = str(MODEL_DIR / "silero_vad_half.onnx")
DEFAULT_TOKENS_PATH = str(ONNX_DIR / "tokens.txt")
DEFAULT_QURAN_PHONEMES_PATH = str(DATA_PATH / "ordered_quran_phonemes.json")
DEFAULT_REF_NORM_PH_PATH = str(DATA_PATH / "ref_norm_ph.txt")
DEFAULT_PH_INDEX_PATH = str(DATA_PATH / "ph_index.npy")
DEFAULT_OUTPUT_DIR = str(PROJECT_ROOT / "output")
EXPORT_ALL_ARTIFACTS: bool = True


# ==============================================================================
# 2. AUDIO & ACOUSTIC SPECIFICATIONS
# ==============================================================================
SAMPLE_RATE: int = 16000
BLANK_ID: int = 250
FRAME_RATE: float = 25.0                    # 40ms per encoder frame (25 Hz)
FRAME_STEP: float = 1.0 / FRAME_RATE        # 0.040s
CLIP_AUDIO_PEAKS: bool = True               # Soft guard against clipping > 1.0

# Memory & Performance Optimization (On = New Way, Off = Old Way)
OPTIMIZED_FBANK: bool = True                # True (on): Memory-efficient batched Fbank extraction; False (off): Legacy unchunked mode
FBANK_BATCH_FRAMES: int = 4096              # Frame batch size for optimized Fbank



# ==============================================================================
# 3. PHASE 3 MATCHING & WRAPAROUND TUNING (TWEAK MATCHING HERE)
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
# 4. PHASE 3A SURAH DISCOVERY & DETECTOR TUNING
# ==============================================================================
DETECTOR_ERROR_RATIO: float = 0.20          # Max Myers bit-parallel error tolerance for global detection
DETECTOR_MIN_PHONEMES: int = 12             # Minimum phonemes required to trigger detection probe


# ==============================================================================
# 5. PHASE 2 CTC FORCED ALIGNMENT TUNING
# ==============================================================================
CTC_BLANK_PENALTY: float = 1.8              # Trellis blank prior regularization
LOOKAHEAD_OFFSET_FRAMES: float = 4.0        # Zipformer causal lookahead compensation (4.0 frames = 160ms)

# Interior word-boundary fusion (Wasl connected speech, voiced transitions).
# How much each signal contributes to the boundary between two adjacent tokens:
#   1st = trellis path-switch frame  (model's own acoustic decision point)
#   2nd = measured 10ms onset from the RMS energy envelope (traced back from the peak)
#   3rd = legacy heuristic (emission peak - lead time) kept for stability
# Weights must sum to 1.0. Set all three to e.g. (0.0, 0.0, 1.0) to restore pure legacy behavior.
# Tuned by A/B benchmark on surah 50 (373 words vs QUD GT): (0.45,0.30,0.25) beat legacy
# start MAE 86.0->81.8ms, start p95 213->175ms, end median 60->55ms.
INTERIOR_BOUNDARY_WEIGHTS: tuple = (0.45, 0.30, 0.25)

# Per-position word-timing calibration (seconds ADDED to word start/end after matching).
# Positive = later, negative = earlier. Measured by calibration sweep on the surah-50
# benchmark vs QUD GT. Keyed by word position inside the ayah.
# Applied in Phase 3.5 (pipeline post-match); never inside the matcher itself.
# Set {"ayah_initial": {"start":0,"end":0}, "interior": {"start":0,"end":0}, "ayah_final": {"start":0,"end":0}}
# to disable.
WORD_TIMING_CALIBRATION_S: dict = {
    "ayah_initial": {"start": 0.070, "end": 0.030},
    "interior":     {"start": 0.030, "end": 0.010},
    "ayah_final":   {"start": 0.030, "end": 0.100},
}

# Duration prior in the CTC trellis (Phase 2 only; does not affect matching).
# While a token state "stays" the path pays LAMBDA*(age - MU) per stay frame, where MU is
# the expected occupancy in 40ms frames for that Tajweed class. Blank/waqf states exempt.
# Order of MU tuple: (SUSTAINED_HOLD, GEMINATE_CLOSURE, BURST_RELEASE, STANDARD_CV).
# Set LAMBDA = 0.0 (or ENABLED = False) to restore the legacy no-prior trellis.
CTC_DURATION_PRIOR_ENABLED: bool = True
CTC_DURATION_PRIOR_LAMBDA: float = 0.0   # 0.15-0.40 tested: neutral on surah-50 bench; raise to activate
CTC_DURATION_PRIOR_MU_FRAMES: tuple = (15.0, 2.0, 2.0, 3.0)

# Sub-frame emission-crossing refinement (Phase 2): interpolate the logprob crossing
# between adjacent phonemes inside their shared 40ms switch frame, when both tokens
# differ. Bypassing raw_starts frame-quantization; the fuser still blends with the
# energy onset trace and the legacy anchor, so a poor crossing cannot dominate.
EMISSION_CROSSING_REFINEMENT: bool = True

# Minimum raw-boundary gap (seconds) treated as an acoustic micro-pause (Sakt/breath)
# inside connected phrases. Legacy behavior: 0.28. Lowering to the Sakt threshold
# (0.16) lets the energy-traced split handle shorter dips inside phrases instead of
# falling back to the fused heuristic boundary.
MICRO_PAUSE_MIN_GAP_S: float = 0.28   # 0.16 tested: neutral (no raw gaps land in this band)

# Final-token (ayah-end) decay trace: stop when envelope falls REL_DROP_DB below the
# word's own peak energy instead of riding absolute silence (fixes +400-750ms end tails),
# and hard-cap the trace window (was a fixed 0.800s).
FINAL_DECAY_REL_DROP_DB: float = 14.0
FINAL_DECAY_TRACE_MAX_S: float = 0.40

# Where a word's end is clamped when it straddles a VAD Waqf pause
# (aligner-side only). "cut" = legacy pause midpoint; "start" = physical silence onset,
# recommended: stops ayah-final words riding deep into the pause.
PAUSE_END_CLAMP_MODE: str = "start"
CTC_BLANK_PENALTY: float = 1.8              # Trellis blank prior regularization (1.0 tested, regressed end MAE)
LOOKAHEAD_OFFSET_FRAMES: float = 4.0        # Zipformer causal lookahead compensation (4.0 = 160ms; 2.0 tested, worse)


# ==============================================================================
# 6. UNIFIED TAJWEED ACOUSTIC SILENCE & PAUSE ENGINE (VAD)
# ==============================================================================
VAD_BACKEND: str = "silero_dual_check"      # "energy" or "silero_dual_check"
VAD_SILERO_THRESHOLD: float = 0.45          # Silero speech onset probability threshold
VAD_MADD_PERIODICITY_TH: float = 0.45       # Normalized autocorrelation peak for held Madd ("ييييي")
VAD_MADD_MIN_ENERGY_DB: float = -38.0       # Minimum floor dB for held letter detection
VAD_MIN_PAUSE_S: float = 0.20               # Natural Waqf pause threshold (seconds)
VAD_SAKT_MIN_PAUSE_S: float = 0.16          # Sakt pause detection threshold (seconds)
VAD_CLOSURE_MAX_S: float = 0.14             # Max intra-word stop closure / Qalqalah bridge (seconds)
VAD_ADAPTIVE: bool = True                   # Dynamic noise-floor adaptation
VAD_ONSET_DB: float = -35.0                 # Fallback speech onset energy threshold (dB)
VAD_OFFSET_DB: float = -42.0                # Fallback speech offset energy threshold (dB)
VAD_HANGOVER_S: float = 0.08                # 80ms hangover buffer
VAD_MAX_PAD_S: float = 0.25                 # 250ms clean silence margin on both sides of each segment
VAD_PREROLL_S: float = 0.20                 # 200ms pre-roll margin
FLUSH_PAD_FRAMES: int = 36                  # 360ms tail flush padding

RESET_ENCODER_ON_SILENCE: bool = True       # Encoder state reset at Waqf boundaries
SUBSEGMENT_MIN_PAUSE_S: float = 0.25        # Minimum pause duration (seconds) to split Ayah into Subsegment


# ==============================================================================
# 7. SPEECH RECOVERY CONTROLS (INTRA-SEGMENT HOLE RE-TRANSCRIPTION)
# ==============================================================================
ENABLE_SPEECH_RECOVERY: bool = True          # Targeted re-transcription of severe deletion holes
SPEECH_RECOVERY_MODE: str = "legacy"             # "legacy" (default, exact original -55dB brute-force), "adaptive" (VAD noise floor), or "off"
SPEECH_RECOVERY_MIN_HOLE_DURATION_S: float = 1.40  # Minimum gap duration to inspect
SPEECH_RECOVERY_PADDING_PRE_S: float = 0.16        # 160ms pre-roll for causal conv states ramp-up
SPEECH_RECOVERY_PADDING_POST_S: float = 0.24       # 240ms flush padding for trailing vowels
SPEECH_RECOVERY_MIN_PHONEMES_IN_GAP: int = 2       # Minimum tokens to accept recovered speech


# ==============================================================================
# 8. RUNTIME CONCURRENCY
# ==============================================================================
NUM_SEGMENT_WORKERS: int = 1


# ==============================================================================
# 9. MONTREAL FORCED ALIGNER (MFA) SECONDARY REFINEMENT (OPTIONAL --mfa)
# ==============================================================================
DEFAULT_MFA_DIR = DATA_PATH / "mfa"
DEFAULT_MFA_ACOUSTIC_PATH = str(DEFAULT_MFA_DIR / "quran_hafs_acoustic.zip")
DEFAULT_MFA_DICT_PATH = str(DEFAULT_MFA_DIR / "quran_hafs.dict")
DEFAULT_MFA_RULES_PATH = str(DEFAULT_MFA_DIR / "rule_index.jsonl")
CLEANUP_MFA_WORKSPACE: bool = True           # Discard temporary sliced WAVs/TextGrids after JSON export
MFA_BEAM: int = 40                           # MFA search beam width (tuned for recitation madd vowels)
MFA_RETRY_BEAM: int = 160                    # MFA retry beam width on difficult elongations
MFA_NUM_JOBS: int = 2                        # Parallel acoustic alignment worker threads


