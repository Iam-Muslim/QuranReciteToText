"""Matching Subsystem Package.

Exposes the unified Quran recitation matching, dynamic programming,
linguistic rules, and global detection engines.
"""

from src.matching.phonetics import (
    ZERO_COST_MARKERS,
    HAMZA_VARIANTS,
    TASHKEEL_CODES,
    MADD_VOWEL_CODES,
    PhoneticCostEngine,
    normalize_phoneme_query,
)
from src.matching.kernels import (
    warmup_matcher_jit,
    warmup_detector_jit,
)
from src.matching.reference import (
    ContinuousQuranWord,
    RefWord,
    SurahReferenceData,
    compute_reading_sequence,
)
from src.matching.detector import (
    FuzzyMatch,
    SurahMatchSpan,
    SurahSearchResult,
    SurahDetectionResult,
    SurahAudioBlock,
    PhoneticSearch,
    MultiSurahFinder,
    find_near_matches,
)
from src.matching.matcher import (
    WraparoundConfig,
    TrackerConfig,
    MatcherConfig,
    AlignmentResult,
    WraparoundDpMatcher,
    QuranMatcher,
    QuranWordMatcher,
)

__all__ = [
    "ZERO_COST_MARKERS",
    "HAMZA_VARIANTS",
    "TASHKEEL_CODES",
    "MADD_VOWEL_CODES",
    "PhoneticCostEngine",
    "normalize_phoneme_query",
    "warmup_matcher_jit",
    "warmup_detector_jit",
    "ContinuousQuranWord",
    "RefWord",
    "SurahReferenceData",
    "compute_reading_sequence",
    "FuzzyMatch",
    "SurahMatchSpan",
    "SurahSearchResult",
    "SurahDetectionResult",
    "SurahAudioBlock",
    "PhoneticSearch",
    "MultiSurahFinder",
    "find_near_matches",
    "WraparoundConfig",
    "TrackerConfig",
    "MatcherConfig",
    "AlignmentResult",
    "WraparoundDpMatcher",
    "QuranMatcher",
    "QuranWordMatcher",
]
