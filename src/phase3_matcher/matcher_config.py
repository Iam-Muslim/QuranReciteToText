"""Unified configuration for Quran Word Matching, DTW Thresholds, and Repetitions.

Mirrors Dart lib/phase3_matcher/matcher_config.dart exactly.
"""

from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True)
class MatcherConfig:
    """Unified configuration for Quran Word Matching and DTW Thresholds."""
    default_max_path_cost: float = 0.30
    relaxed_max_path_cost: float = 0.36
    short_word_path_cost: float = 0.25
    medium_word_path_cost: float = 0.28
    max_skip_words: int = 2
    acoustic_confusion_cost: float = 0.25
    standard_insertion_cost: float = 0.75
    standard_deletion_cost: float = 1.0
    repetition_penalty: float = 1.2
    max_backtrack_words: int = 30
    auto_detect_surah: bool = True
    multi_surah_mode: bool = True

    # Legacy Aliases (Backwards Compatibility with TrackerConfig)
    @property
    def max_path_cost(self) -> float:
        return self.default_max_path_cost

    @property
    def cost_del(self) -> float:
        return self.standard_deletion_cost

    @property
    def cost_ins(self) -> float:
        return self.standard_insertion_cost

    @classmethod
    def normal(cls) -> MatcherConfig:
        """Standard baseline configuration."""
        return cls()

    @classmethod
    def easy(cls) -> MatcherConfig:
        """Easy mode for beginners, noisy audio, or fast recitation."""
        return cls(
            default_max_path_cost=0.40,
            relaxed_max_path_cost=0.45,
            short_word_path_cost=0.30,
            medium_word_path_cost=0.35,
            max_skip_words=3,
            acoustic_confusion_cost=0.15,
            standard_insertion_cost=0.50,
            standard_deletion_cost=0.80,
        )

    @classmethod
    def strict(cls) -> MatcherConfig:
        """Strict mode for high accuracy validation."""
        return cls(
            default_max_path_cost=0.25,
            relaxed_max_path_cost=0.30,
            short_word_path_cost=0.20,
            medium_word_path_cost=0.23,
            max_skip_words=1,
            acoustic_confusion_cost=0.35,
            standard_insertion_cost=1.0,
            standard_deletion_cost=1.0,
        )


TrackerConfig = MatcherConfig
