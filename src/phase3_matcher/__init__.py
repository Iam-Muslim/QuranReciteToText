"""Phase 3: Quran Text Matcher, Phonetic Cost Engine, and Verse Finder."""

from src.phase3_matcher.matcher_config import MatcherConfig, TrackerConfig
from src.phase3_matcher.phonetic_cost_engine import PhoneticCostEngine
from src.phase3_matcher.dictation_matcher import (
    QuranDictationMatcher,
    WordMatchResult,
    PhonemeGroupAlignment,
)
from src.phase3_matcher.dictation_sequencer import (
    DictationSequencer,
    RefWord,
    SequencedWord,
    AyahSequenceResult,
)
from src.phase3_matcher.quran_word_matcher import (
    QuranWordMatcher,
    BaseQuranMatcher,
    MatchedAyah,
)
from src.phase3_matcher.surah_finder import (
    SurahMatchSpan,
    SurahSearchResult,
    SurahDetectionResult,
    SurahAudioBlock,
    PhoneticSearch,
    MultiSurahFinder,
)

__all__ = [
    "MatcherConfig",
    "TrackerConfig",
    "PhoneticCostEngine",
    "QuranDictationMatcher",
    "WordMatchResult",
    "PhonemeGroupAlignment",
    "DictationSequencer",
    "RefWord",
    "SequencedWord",
    "AyahSequenceResult",
    "QuranWordMatcher",
    "BaseQuranMatcher",
    "MatchedAyah",
    "SurahMatchSpan",
    "SurahSearchResult",
    "SurahDetectionResult",
    "SurahAudioBlock",
    "PhoneticSearch",
    "MultiSurahFinder",
]
