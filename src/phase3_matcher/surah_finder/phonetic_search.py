"""Binary NPY Index loader and high-speed global Quran search engine.

Mirrors Dart lib/phase3_matcher/surah_finder/phonetic_search.dart exactly.
"""

from __future__ import annotations
import os
import re
from pathlib import Path
from typing import Optional, List
import numpy as np

from config import DEFAULT_REF_NORM_PH_PATH, DEFAULT_PH_INDEX_PATH
from src.phase3_matcher.surah_finder.fuzzy_search import find_near_matches, FuzzyMatch
from src.phase3_matcher.surah_finder.models import SurahMatchSpan, SurahSearchResult


class PhoneticSearch:
    """Fast global search over the normalized Quranic phonetic database."""

    _core_chars = "ءبتثجحخدذرزسشصضطظعغفقكلمنهوياۥۦ۾ںـٲ"
    _residual_chars = "َُِڇؙ۪ۜ"

    # Regex matching consecutive core chars plus optional residual
    _core_group = "|".join(f"{c}+" for c in _core_chars)
    _chunk_regex = re.compile(f"((?:{_core_group})[{_residual_chars}]?)")

    def __init__(self):
        self._index_array: Optional[np.ndarray] = None
        self._ref_ph_norm: Optional[str] = None
        self._is_loaded: bool = False

    @property
    def is_loaded(self) -> bool:
        return self._is_loaded

    def load(
        self,
        ref_norm_ph_path: Optional[str] = None,
        ph_index_path: Optional[str] = None,
    ) -> None:
        """Loads the binary index and reference text from file paths."""
        if self._is_loaded:
            return

        ref_path = ref_norm_ph_path or DEFAULT_REF_NORM_PH_PATH
        npy_path = ph_index_path or DEFAULT_PH_INDEX_PATH

        if not os.path.exists(ref_path):
            raise FileNotFoundError(f"Reference normalized phonemes file not found: {ref_path}")
        if not os.path.exists(npy_path):
            raise FileNotFoundError(f"Phonetic index npy file not found: {npy_path}")

        # 1. Load ref_norm_ph.txt
        with open(ref_path, "r", encoding="utf-8") as f:
            self._ref_ph_norm = f.read().strip()

        # 2. Load ph_index.npy
        arr = np.load(npy_path)
        # Ensure array is 2D uint16 array of shape (N, 7)
        if arr.ndim == 1:
            arr = arr.reshape(-1, 7)
        self._index_array = arr.astype(np.uint16)

        self._is_loaded = True

    @classmethod
    def normalize_query(cls, query: str) -> str:
        """Normalizes the query by combining consecutive identical core characters

        into a single character and stripping residuals.
        """
        parts = []
        for match in cls._chunk_regex.finditer(query):
            group = match.group(1)
            if group:
                parts.append(group[0])
        return "".join(parts)

    def _ref_idx_to_span(self, ref_idx: int, is_end: bool = False) -> SurahMatchSpan:
        if self._index_array is None or self._ref_ph_norm is None:
            raise RuntimeError("PhoneticSearch index not loaded")
        if ref_idx < 0 or ref_idx >= len(self._ref_ph_norm):
            raise IndexError(f"Reference index {ref_idx} out of range (0..{len(self._ref_ph_norm)})")

        row = self._index_array[ref_idx]

        return SurahMatchSpan(
            surah_idx=int(row[0]),
            ayah_idx=int(row[1]),
            uthmani_word_idx=int(row[2]),
            uthmani_char_idx=int(row[4] if is_end else row[3]),
            phonemes_idx=int(row[6] if is_end else row[5]),
        )

    def search(self, query: str, error_ratio: float = 0.20) -> List[SurahSearchResult]:
        """Searches for the query across the entire Quran with a max allowed error ratio."""
        if not self._is_loaded or not self._ref_ph_norm:
            return []

        norm_query = self.normalize_query(query)
        if not norm_query:
            return []

        max_edits = int(len(norm_query) * error_ratio)
        outs = find_near_matches(norm_query, self._ref_ph_norm, max_edits)
        if not outs:
            return []

        results: List[SurahSearchResult] = []
        for out in outs:
            results.append(
                SurahSearchResult(
                    start=self._ref_idx_to_span(out.start, is_end=False),
                    end=self._ref_idx_to_span(out.end - 1, is_end=True),
                    mid=self._ref_idx_to_span((out.start + out.end - 1) // 2, is_end=False),
                    distance=out.dist,
                )
            )

        results.sort(key=lambda r: r.distance)
        return results
