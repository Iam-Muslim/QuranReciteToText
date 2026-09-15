"""Unified Quran Recitation Matching Subsystem Package."""

from src.matching.reference import (
    RefWord,
    ContinuousQuranWord,
    SurahReferenceData,
)
from src.matching.phonetics import (
    ZERO_COST_MARKERS,
    HAMZA_VARIANTS,
    MADD_VOWEL_CODES,
    PhoneticCostEngine,
    normalize_phoneme_query,
    get_sub_cost_table,
)
from src.matching.kernels import (
    warmup_matcher_jit,
    warmup_detector_jit,
    warmup_matching_kernels,
)
from src.matching.detector import (
    FuzzyMatch,
    SurahMatchSpan,
    SurahSearchResult,
    SurahDetectionResult,
    PhoneticSearch,
    SurahDetector,
    MultiSurahFinder,
    find_near_matches,
)
from src.matching.matcher import (
    MatcherConfig,
    WraparoundConfig,
    TrackerConfig,
    QuranMatcher,
    QuranWordMatcher,
)

__all__ = [
    "RefWord",
    "ContinuousQuranWord",
    "SurahReferenceData",
    "ZERO_COST_MARKERS",
    "HAMZA_VARIANTS",
    "MADD_VOWEL_CODES",
    "PhoneticCostEngine",
    "normalize_phoneme_query",
    "get_sub_cost_table",
    "warmup_matcher_jit",
    "warmup_detector_jit",
    "warmup_matching_kernels",
    "FuzzyMatch",
    "SurahMatchSpan",
    "SurahSearchResult",
    "SurahDetectionResult",
    "PhoneticSearch",
    "SurahDetector",
    "MultiSurahFinder",
    "find_near_matches",
    "MatcherConfig",
    "WraparoundConfig",
    "TrackerConfig",
    "QuranMatcher",
    "QuranWordMatcher",
]
