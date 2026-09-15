"""Matching Subsystem Package.

Exposes the unified Quran recitation matching, dynamic programming,
linguistic rules, and global detection engines.
"""

from src.matching.phonetics import (
    ZERO_COST_MARKERS,
    HAMZA_VARIANTS,
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
    WraparoundConfig,
    TrackerConfig,
    MatcherConfig,
    QuranMatcher,
    QuranWordMatcher,
)

__all__ = [
    "ZERO_COST_MARKERS",
    "HAMZA_VARIANTS",
    "MADD_VOWEL_CODES",
    "PhoneticCostEngine",
    "normalize_phoneme_query",
    "warmup_matcher_jit",
    "warmup_detector_jit",
    "ContinuousQuranWord",
    "RefWord",
    "SurahReferenceData",
    "FuzzyMatch",
    "SurahMatchSpan",
    "SurahSearchResult",
    "SurahDetectionResult",
    "PhoneticSearch",
    "SurahDetector",
    "MultiSurahFinder",
    "find_near_matches",
    "WraparoundConfig",
    "TrackerConfig",
    "MatcherConfig",
    "QuranMatcher",
    "QuranWordMatcher",
]
