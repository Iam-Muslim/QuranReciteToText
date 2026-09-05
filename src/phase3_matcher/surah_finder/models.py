"""Data models for Surah and Ayah detection, spans, and multi-Surah audio partitioning.

Mirrors Dart lib/phase3_matcher/surah_finder/models.dart exactly.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from src.core.models import PhonemeToken


@dataclass
class SurahMatchSpan:
    """Represents a match span from the global phonetic binary index."""
    surah_idx: int  # 1-indexed (1 to 114)
    ayah_idx: int   # 1-indexed
    uthmani_word_idx: int
    uthmani_char_idx: int
    phonemes_idx: int

    @property
    def surah_number(self) -> int:
        return self.surah_idx

    def __str__(self) -> str:
        return (
            f"SurahMatchSpan(surah: {self.surah_number}, ayah: {self.ayah_idx}, "
            f"word: {self.uthmani_word_idx}, char: {self.uthmani_char_idx}, ph: {self.phonemes_idx})"
        )


@dataclass
class SurahSearchResult:
    """Represents the raw result of a global fuzzy search query."""
    start: SurahMatchSpan
    end: SurahMatchSpan
    mid: SurahMatchSpan
    distance: int

    @property
    def surah_number(self) -> int:
        return self.mid.surah_number

    @property
    def ayah_number(self) -> int:
        return self.mid.ayah_idx

    def __str__(self) -> str:
        return f"SurahSearchResult(surah: {self.surah_number}, ayah: {self.ayah_number}, distance: {self.distance})"


@dataclass
class SurahDetectionResult:
    """High-level single detection result."""
    surah: int
    start_ayah: int
    end_ayah: int
    confidence: float = 1.0
    start_phoneme_idx: int = 0
    end_phoneme_idx: int = 0
    start_time: float = 0.0
    end_time: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "surah": self.surah,
            "start_ayah": self.start_ayah,
            "end_ayah": self.end_ayah,
            "confidence": round(self.confidence, 3),
            "start_time": round(self.start_time, 3),
            "end_time": round(self.end_time, 3),
        }


@dataclass
class SurahAudioBlock:
    """Represents a distinct Surah section / block identified within a continuous audio recording."""
    block_index: int
    surah_number: int
    start_ayah: int
    end_ayah: int
    start_time_seconds: float
    end_time_seconds: float
    start_phoneme_idx: int
    end_phoneme_idx: int
    surah_name_ar: str = ""
    surah_name_en: str = ""
    confidence: float = 1.0
    phonemes: List[PhonemeToken] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "block_index": self.block_index,
            "surah_number": self.surah_number,
            "surah_name_ar": self.surah_name_ar,
            "surah_name_en": self.surah_name_en,
            "start_ayah": self.start_ayah,
            "end_ayah": self.end_ayah,
            "start_time_seconds": round(self.start_time_seconds, 3),
            "end_time_seconds": round(self.end_time_seconds, 3),
            "total_phonemes": len(self.phonemes),
            "confidence": round(self.confidence, 3),
        }

    def __str__(self) -> str:
        return (
            f"SurahAudioBlock #{self.block_index}: Surah {self.surah_number} "
            f"({self.surah_name_ar} - {self.surah_name_en}), Ayahs {self.start_ayah}..{self.end_ayah}, "
            f"Time: {self.start_time_seconds:.2f}s - {self.end_time_seconds:.2f}s ({len(self.phonemes)} phonemes)"
        )
