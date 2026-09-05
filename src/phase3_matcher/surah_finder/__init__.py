"""Surah Finder subpackage for global Quran search and multi-Surah timeline partitioning."""

from src.phase3_matcher.surah_finder.models import (
    SurahMatchSpan,
    SurahSearchResult,
    SurahDetectionResult,
    SurahAudioBlock,
)
from src.phase3_matcher.surah_finder.fuzzy_search import FuzzyMatch, find_near_matches
from src.phase3_matcher.surah_finder.phonetic_search import PhoneticSearch
from src.phase3_matcher.surah_finder.multi_surah_finder import MultiSurahFinder

__all__ = [
    "SurahMatchSpan",
    "SurahSearchResult",
    "SurahDetectionResult",
    "SurahAudioBlock",
    "FuzzyMatch",
    "find_near_matches",
    "PhoneticSearch",
    "MultiSurahFinder",
]
