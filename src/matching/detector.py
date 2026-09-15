"""Global Surah Discovery & Gene Myers' Bit-Parallel Phonetic Search Engine."""

from __future__ import annotations

import os
import logging
from collections import defaultdict
from dataclasses import dataclass
from typing import Optional, List, Tuple
import numpy as np

import config
from config import DEFAULT_REF_NORM_PH_PATH, DEFAULT_PH_INDEX_PATH
from src.models import PhonemeToken
from src.matching.phonetics import normalize_phoneme_query
from src.matching.kernels import _bit_parallel_search_fast

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# 1. FUZZY BIT-PARALLEL SUBSTRING MATCHER
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass(slots=True)
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
    query: str,
    text: str | np.ndarray,
    max_dist: int = 0,
    max_l_dist: Optional[int] = None,
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

@dataclass(slots=True)
class SurahSearchResult:
    surah_number: int
    ayah_number: int
    distance: int

    # Backward-compatibility properties
    @property
    def start(self) -> SurahSearchResult:
        return self

    @property
    def surah_idx(self) -> int:
        return self.surah_number

    @property
    def ayah_idx(self) -> int:
        return self.ayah_number


SurahMatchSpan = SurahSearchResult  # Backward-compatibility alias


@dataclass(slots=True)
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
        # Store only Surah (col 0) and Ayah (col 1) to conserve RAM
        self._index_array = arr[:, :2].astype(np.uint16)
        self._is_loaded = True

    @staticmethod
    def normalize_query(query: str) -> str:
        return normalize_phoneme_query(query)

    def search(self, query: str, error_ratio: Optional[float] = None) -> List[SurahSearchResult]:
        if not self._is_loaded or self._ref_codes is None or self._index_array is None:
            return []
        norm_query = self.normalize_query(query)
        if not norm_query:
            return []

        ratio = error_ratio if error_ratio is not None else getattr(config, "DETECTOR_ERROR_RATIO", 0.20)
        max_edits = int(min(len(norm_query), 64) * ratio)
        outs = find_near_matches(norm_query, self._ref_codes, max_edits)

        results = []
        for out in outs:
            row = self._index_array[out.start]
            results.append(SurahSearchResult(
                surah_number=int(row[0]),
                ayah_number=int(row[1]),
                distance=out.dist,
            ))
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

        # Probe opening window offsets to be robust to Isti'adha, Basmalah, or intro silence
        probe_offsets = [off for off in (0, 8, 16, 24, 32, 48, 64, 80, 100, 120) if off + 15 <= total_toks]

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
            # If Surah 1:1 (Basmalah) matched but a non-1 Surah exists with strong votes, select non-1
            non_1_surahs = {s: sc for s, sc in surah_scores.items() if s != 1}
            if non_1_surahs and surah_counts[1] <= 2 and all(c[2] == 1 for c in surah_candidates[1]):
                best_surah = max(non_1_surahs.keys(), key=lambda s: (surah_counts[s], surah_scores[s]))
            else:
                best_surah = max(surah_scores.keys(), key=lambda s: (surah_counts[s], surah_scores[s]))

            best_list = surah_candidates[best_surah]
            best_list.sort(key=lambda c: (c[0], c[1]))
            _, best_norm, _, best_offset = best_list[0]

            min_ayah = min(c[2] for c in best_list)
            start_ayah = max(1, min_ayah - 1) if best_offset > 0 and min_ayah > 1 else min_ayah

            # Determine end Ayah by probing near the recitation tail
            end_ayah = start_ayah
            if total_toks > sample_length:
                for end_offset in (
                    total_toks - sample_length,
                    total_toks - sample_length - 20,
                    total_toks - sample_length - 45,
                    total_toks - sample_length - 80,
                ):
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


MultiSurahFinder = SurahDetector  # Backward compatibility alias
