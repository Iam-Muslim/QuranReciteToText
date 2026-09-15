"""Global Surah Discovery & Gene Myers' Bit-Parallel Phonetic Search Engine."""

from __future__ import annotations

import os
import logging
from collections import defaultdict
from dataclasses import dataclass
from typing import Optional, List, Tuple
import numpy as np

import config
from config import (
    DEFAULT_REF_NORM_PH_PATH,
    DEFAULT_PH_INDEX_PATH,
)
from src.models import PhonemeToken
from src.matching.phonetics import normalize_phoneme_query
from src.matching.kernels import _bit_parallel_search_fast

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# 1. FUZZY BIT-PARALLEL SUBSTRING MATCHER
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class FuzzyMatch:
    start: int
    end: int
    dist: int


def _filter_overlapping(matches: List[FuzzyMatch]) -> List[FuzzyMatch]:
    if not matches:
        return []
    matches.sort(key=lambda m: (m.start, m.end, m.dist))
    filtered = [matches[0]]
    for nxt in matches[1:]:
        cur = filtered[-1]
        if nxt.start < cur.end:
            if nxt.dist < cur.dist or (nxt.dist == cur.dist and (nxt.end - nxt.start) < (cur.end - cur.start)):
                filtered[-1] = nxt
        else:
            filtered.append(nxt)
    return filtered


def find_near_matches(
    query: str, text: str | np.ndarray, max_dist: int = 0, max_l_dist: Optional[int] = None
) -> List[FuzzyMatch]:
    """Finds near-matches using Gene Myers' 64-bit bit-parallel DP search."""
    effective_dist = max_dist if max_l_dist is None else max_l_dist
    if not query or len(text) == 0 or effective_dist < 0:
        return []
    q_codes = np.array([ord(c) for c in query[:64]], dtype=np.int32)
    t_codes = text if isinstance(text, np.ndarray) else np.array([ord(c) for c in text], dtype=np.int32)
    starts, ends, dists = _bit_parallel_search_fast(q_codes, t_codes, effective_dist)
    return _filter_overlapping([FuzzyMatch(int(s), int(e), int(d)) for s, e, d in zip(starts, ends, dists)])


# ═══════════════════════════════════════════════════════════════════════════════
# 2. PHONETIC SEARCH OVER BINARY NPY INDEX
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class SurahMatchSpan:
    surah_idx: int
    ayah_idx: int


@dataclass
class SurahSearchResult:
    start: SurahMatchSpan
    distance: int

    @property
    def surah_number(self) -> int:
        return self.start.surah_idx

    @property
    def ayah_number(self) -> int:
        return self.start.ayah_idx


@dataclass
class SurahDetectionResult:
    surah: int
    start_ayah: int
    end_ayah: int
    start_time: float = 0.0
    end_time: float = 0.0
    confidence: float = 1.0


class PhoneticSearch:
    """Fast global search over the normalized Quranic binary database."""

    def __init__(self):
        self._index_array: Optional[np.ndarray] = None
        self._ref_ph_norm: Optional[str] = None
        self._ref_codes: Optional[np.ndarray] = None
        self._is_loaded: bool = False

    @property
    def is_loaded(self) -> bool:
        return self._is_loaded

    def load(self, ref_norm_ph_path: Optional[str] = None, ph_index_path: Optional[str] = None) -> None:
        if self._is_loaded:
            return
        ref_path = ref_norm_ph_path or DEFAULT_REF_NORM_PH_PATH
        npy_path = ph_index_path or DEFAULT_PH_INDEX_PATH

        if not os.path.exists(ref_path) or not os.path.exists(npy_path):
            raise FileNotFoundError(f"Missing phonetic reference files: {ref_path} or {npy_path}")

        with open(ref_path, "r", encoding="utf-8") as f:
            self._ref_ph_norm = f.read().strip()
        self._ref_codes = np.array([ord(c) for c in self._ref_ph_norm], dtype=np.int32)

        arr = np.load(npy_path)
        if arr.ndim == 1:
            arr = arr.reshape(-1, 7)
        self._index_array = arr.astype(np.uint16)
        self._is_loaded = True

    @staticmethod
    def normalize_query(query: str) -> str:
        return normalize_phoneme_query(query)

    def _ref_idx_to_span(self, ref_idx: int) -> SurahMatchSpan:
        row = self._index_array[ref_idx]
        return SurahMatchSpan(surah_idx=int(row[0]), ayah_idx=int(row[1]))

    def search(self, query: str, error_ratio: Optional[float] = None) -> List[SurahSearchResult]:
        if not self._is_loaded or not self._ref_ph_norm:
            return []
        norm_query = self.normalize_query(query)
        if not norm_query:
            return []

        ratio = error_ratio if error_ratio is not None else getattr(config, "DETECTOR_ERROR_RATIO", 0.20)
        max_edits = int(min(len(norm_query), 64) * ratio)
        target = self._ref_codes if self._ref_codes is not None else self._ref_ph_norm
        outs = find_near_matches(norm_query, target, max_edits)

        results = [
            SurahSearchResult(
                start=self._ref_idx_to_span(out.start),
                distance=out.dist,
            )
            for out in outs
        ]
        results.sort(key=lambda r: r.distance)
        return results


# ═══════════════════════════════════════════════════════════════════════════════
# 3. SURAH DISCOVERY & TIMELINE DETECTOR
# ═══════════════════════════════════════════════════════════════════════════════

class SurahDetector:
    """Discovers recited Surah and Ayah range in continuous recitation audio."""

    def __init__(self):
        self._phonetic_search = PhoneticSearch()
        self._is_initialized = False

    @property
    def is_initialized(self) -> bool:
        return self._is_initialized

    def initialize(
        self,
        ref_norm_ph_path: Optional[str] = None,
        ph_index_path: Optional[str] = None,
        **kwargs,
    ) -> None:
        if self._is_initialized:
            return
        self._phonetic_search.load(ref_norm_ph_path=ref_norm_ph_path, ph_index_path=ph_index_path)
        self._is_initialized = True

    def detect_single_surah(
        self, aligned_phonemes: List[PhonemeToken], sample_length: int = 35
    ) -> SurahDetectionResult:
        if not aligned_phonemes:
            return SurahDetectionResult(surah=1, start_ayah=1, end_ayah=1)

        total_toks = len(aligned_phonemes)

        # Probe initial offsets across opening window to be immune to preamble, Isti'adha, Basmalah, or noise
        probe_offsets = [0, 8, 16, 24, 32, 48, 64, 80, 100, 120]
        probe_offsets = [off for off in probe_offsets if off + 15 <= total_toks]

        surah_scores: Dict[int, float] = defaultdict(float)
        surah_counts: Dict[int, int] = defaultdict(int)
        surah_candidates: Dict[int, List[Tuple[int, float, int, int]]] = defaultdict(list)

        for offset in probe_offsets:
            slice_tokens = aligned_phonemes[offset:offset + sample_length]
            q = "".join(p.phoneme for p in slice_tokens)
            if len(q) >= 6:
                res = self._phonetic_search.search(q, error_ratio=0.25)
                if res:
                    b = res[0]
                    norm_dist = b.distance / max(1, len(q))
                    w = max(0.01, 1.0 - norm_dist)
                    surah_scores[b.surah_number] += w
                    surah_counts[b.surah_number] += 1
                    surah_candidates[b.surah_number].append((b.distance, norm_dist, b.ayah_number, offset))

        if surah_candidates:
            # If 1:1 (Basmalah) matched but non-1 exists with strong votes, exclude 1:1 if it was just Basmalah
            non_1_surahs = {s: sc for s, sc in surah_scores.items() if s != 1}
            if non_1_surahs and surah_counts[1] <= 2 and all(c[2] == 1 for c in surah_candidates[1]):
                best_surah = max(non_1_surahs.keys(), key=lambda s: (surah_counts[s], surah_scores[s]))
            else:
                best_surah = max(surah_scores.keys(), key=lambda s: (surah_counts[s], surah_scores[s]))

            best_list = surah_candidates[best_surah]
            best_list.sort(key=lambda c: (c[0], c[1]))
            best_dist, best_norm, _, best_offset = best_list[0]

            # Determine start ayah: find the minimum ayah probed for this surah
            min_ayah = min(c[2] for c in best_list)
            start_ayah = max(1, min_ayah - 1) if best_offset > 0 and min_ayah > 1 else min_ayah

            # Determine end ayah: probe near the end of recitation
            end_ayah = start_ayah
            if total_toks > sample_length:
                for end_offset in (total_toks - sample_length, total_toks - sample_length - 20, total_toks - sample_length - 45, total_toks - sample_length - 80):
                    if end_offset > best_offset and end_offset >= 0:
                        slice_tokens = aligned_phonemes[end_offset:end_offset + sample_length]
                        q = "".join(p.phoneme for p in slice_tokens)
                        if len(q) >= 6:
                            res = self._phonetic_search.search(q, error_ratio=0.25)
                            matched_end = False
                            for r in res:
                                if r.surah_number == best_surah:
                                    end_ayah = max(end_ayah, r.ayah_number)
                                    matched_end = True
                                    break
                            if matched_end:
                                break

            return SurahDetectionResult(
                surah=best_surah,
                start_ayah=start_ayah,
                end_ayah=end_ayah,
                start_time=aligned_phonemes[0].start,
                end_time=aligned_phonemes[-1].end,
                confidence=max(0.5, 1.0 - best_norm),
            )

        return SurahDetectionResult(
            surah=1,
            start_ayah=1,
            end_ayah=1,
            start_time=aligned_phonemes[0].start,
            end_time=aligned_phonemes[-1].end,
            confidence=0.5,
        )


# Backward compatibility alias
MultiSurahFinder = SurahDetector
