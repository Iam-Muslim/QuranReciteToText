"""Tajweed Phonetic Matcher, Gene Myers' 64-bit Bit-Parallel Search & Word Sequencer.

Exact algorithmic parity with original components, consolidated into a single clean module.
"""

from __future__ import annotations

import os
import re
import json
import logging
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any, Tuple
import numpy as np

from config import (
    DEFAULT_QURAN_PHONEMES_PATH,
    DEFAULT_REF_NORM_PH_PATH,
    DEFAULT_PH_INDEX_PATH,
)
from src.models import PhonemeToken, QuranWord, QuranSegment

logger = logging.getLogger(__name__)


try:
    from numba import njit
    HAS_NUMBA = True
except ImportError:
    HAS_NUMBA = False
    def njit(*args, **kwargs):
        def decorator(func):
            return func
        return decorator


# ─── 1. Gene Myers' 64-bit Bit-Parallel Substring Search ───

@dataclass
class FuzzyMatch:
    start: int
    end: int
    dist: int

    def __str__(self) -> str:
        return f"FuzzyMatch(start: {self.start}, end: {self.end}, dist: {self.dist})"


@njit(fastmath=True)
def _bit_parallel_search_fast(query_codes: np.ndarray, text_codes: np.ndarray, max_dist: int):
    n = len(query_codes)
    m = len(text_codes)
    char_mask = np.zeros(2048, dtype=np.uint64)
    for i in range(n):
        c = query_codes[i]
        if c < 2048:
            char_mask[c] |= (np.uint64(1) << np.uint64(i))

    full_mask = (np.uint64(1) << np.uint64(n)) - np.uint64(1)
    top_mask = np.uint64(1) << np.uint64(n - 1)
    vp = full_mask
    vn = np.uint64(0)
    curr_dist = n

    match_starts = []
    match_ends = []
    match_dists = []

    for j in range(m):
        code = text_codes[j]
        pm = char_mask[code] if code < 2048 else np.uint64(0)
        x = pm | vn
        d0 = (((pm & vp) + vp) ^ vp) | x
        hn = vp & d0
        hp = vn | (~(vp | d0) & full_mask)

        if (hp & top_mask) != 0:
            curr_dist += 1
        if (hn & top_mask) != 0:
            curr_dist -= 1

        hp = (hp << 1) & full_mask
        hn = (hn << 1) & full_mask
        vp = (hn | (~(d0 | hp) & full_mask)) & full_mask
        vn = hp & d0

        if curr_dist <= max_dist:
            match_end = j + 1
            estimated_start = max(0, min(match_end, match_end - n - curr_dist))
            match_starts.append(estimated_start)
            match_ends.append(match_end)
            match_dists.append(curr_dist)

    return match_starts, match_ends, match_dists


@njit(fastmath=True)
def _sub_cost_fast(a: int, b: int, confusion_cost: float) -> float:
    if a == 0 or b == 0:
        return 1.0
    if a == b:
        return 0.0
    is_a_hamza = (a == 0x0621 or a == 0x0622 or a == 0x0623 or a == 0x0625 or a == 0x0672)
    is_b_hamza = (b == 0x0621 or b == 0x0622 or b == 0x0623 or b == 0x0625 or b == 0x0672)
    if is_a_hamza and is_b_hamza:
        return 0.0
    if (a == 0x0645 and b == 0x06FE) or (a == 0x06FE and b == 0x0645):
        return 0.0
    if (a == 0x0646 and b == 0x06BA) or (a == 0x06BA and b == 0x0646):
        return 0.0
    if (a == 0x0648 and b == 0x06E5) or (a == 0x06E5 and b == 0x0648):
        return 0.0
    if (a == 0x064A and b == 0x06E6) or (a == 0x06E6 and b == 0x064A):
        return 0.0
    if (a == 0x0629 and b == 0x0647) or (a == 0x0647 and b == 0x0629):
        return 0.0
    if (a == 0x0629 and b == 0x062A) or (a == 0x062A and b == 0x0629):
        return 0.0

    if (a == 0x0627 and b == 0x064E) or (a == 0x064E and b == 0x0627):
        return confusion_cost
    if (a == 0x0648 and b == 0x064F) or (a == 0x064F and b == 0x0648):
        return confusion_cost
    if (a == 0x064F and b == 0x06E5) or (a == 0x06E5 and b == 0x064F):
        return confusion_cost
    if (a == 0x064A and b == 0x0650) or (a == 0x0650 and b == 0x064A):
        return confusion_cost
    if (a == 0x0650 and b == 0x06E6) or (a == 0x06E6 and b == 0x0650):
        return confusion_cost
    if (a == 0x062A and b == 0x0637) or (a == 0x0637 and b == 0x062A):
        return confusion_cost
    if (a == 0x062C and b == 0x0632) or (a == 0x0632 and b == 0x062C):
        return confusion_cost
    if (a == 0x062E and b == 0x0638) or (a == 0x0638 and b == 0x062E):
        return confusion_cost
    if (a == 0x062F and b == 0x0636) or (a == 0x0636 and b == 0x062F):
        return confusion_cost

    return 1.0


@njit(fastmath=True)
def _dtw_fill_fast(
    a_codes: np.ndarray,
    r_codes: np.ndarray,
    ins_costs: np.ndarray,
    del_costs: np.ndarray,
    confusion_cost: float,
    dp: np.ndarray,
    bt: np.ndarray,
    stride: int,
):
    m = len(a_codes)
    n = len(r_codes)
    dp[0] = 0.0
    bt[0] = 0
    for j in range(1, n + 1):
        dp[j] = dp[j - 1] + del_costs[j - 1]
        bt[j] = 1

    for i in range(1, m + 1):
        dp[i * stride] = 0.0
        bt[i * stride] = 2

    for i in range(1, m + 1):
        a_code = a_codes[i - 1]
        row = i * stride
        prev = (i - 1) * stride
        ins_cost = ins_costs[i - 1]

        for j in range(1, n + 1):
            r_code = r_codes[j - 1]
            sub_c = _sub_cost_fast(a_code, r_code, confusion_cost)
            del_c = del_costs[j - 1]

            sub = dp[prev + j - 1] + sub_c
            del_val = dp[row + j - 1] + del_c
            ins = dp[prev + j] + ins_cost

            if sub < del_val and sub <= ins:
                dp[row + j] = sub
                bt[row + j] = 0
            elif del_val <= ins:
                dp[row + j] = del_val
                bt[row + j] = 1
            else:
                dp[row + j] = ins
                bt[row + j] = 2


def warmup_matcher_jit() -> None:
    """Pre-compiles Myers & DTW JIT functions with dummy arrays so first audio run is instant."""
    if not HAS_NUMBA:
        return
    try:
        _bit_parallel_search_fast(np.array([1575], dtype=np.int32), np.array([1575, 1576], dtype=np.int32), 1)
        dp = np.zeros(4, dtype=np.float64)
        bt = np.zeros(4, dtype=np.uint8)
        _dtw_fill_fast(
            np.array([1575], dtype=np.int32),
            np.array([1576], dtype=np.int32),
            np.array([0.75], dtype=np.float64),
            np.array([1.0], dtype=np.float64),
            0.25,
            dp,
            bt,
            2,
        )
    except Exception:
        pass


def find_near_matches(query: str, text: str, max_dist: int) -> List[FuzzyMatch]:
    n = len(query)
    m = len(text)
    if n == 0 or m == 0 or max_dist < 0:
        return []
    if n > 64:
        query = query[:64]
    if HAS_NUMBA:
        q_codes = np.array([ord(c) for c in query], dtype=np.int32)
        t_codes = np.array([ord(c) for c in text], dtype=np.int32)
        starts, ends, dists = _bit_parallel_search_fast(q_codes, t_codes, max_dist)
        return _filter_overlapping([FuzzyMatch(int(s), int(e), int(d)) for s, e, d in zip(starts, ends, dists)])
    return _bit_parallel_search(query, text, max_dist)


def _bit_parallel_search(query: str, text: str, max_dist: int) -> List[FuzzyMatch]:
    n = len(query)
    m = len(text)
    matches: List[FuzzyMatch] = []

    char_mask: Dict[str, int] = {}
    for i, ch in enumerate(query):
        char_mask[ch] = char_mask.get(ch, 0) | (1 << i)

    full_mask = (1 << n) - 1
    top_mask = 1 << (n - 1)
    vp = full_mask
    vn = 0
    curr_dist = n

    for j, ch in enumerate(text):
        pm = char_mask.get(ch, 0)
        x = pm | vn
        d0 = (((pm & vp) + vp) ^ vp) | x
        hn = vp & d0
        hp = vn | (~(vp | d0) & full_mask)

        if (hp & top_mask) != 0:
            curr_dist += 1
        if (hn & top_mask) != 0:
            curr_dist -= 1

        hp = (hp << 1) & full_mask
        hn = (hn << 1) & full_mask
        vp = (hn | (~(d0 | hp) & full_mask)) & full_mask
        vn = hp & d0

        if curr_dist <= max_dist:
            match_end = j + 1
            estimated_start = max(0, min(match_end, match_end - n - curr_dist))
            matches.append(FuzzyMatch(start=estimated_start, end=match_end, dist=curr_dist))

    return _filter_overlapping(matches)



def _filter_overlapping(matches: List[FuzzyMatch]) -> List[FuzzyMatch]:
    if not matches:
        return []
    matches.sort(key=lambda m: (m.start, m.end, m.dist))
    filtered: List[FuzzyMatch] = []
    current = matches[0]

    for i in range(1, len(matches)):
        nxt = matches[i]
        if nxt.start < current.end:
            if nxt.dist < current.dist:
                current = nxt
            elif nxt.dist == current.dist:
                if (nxt.end - nxt.start) < (current.end - current.start):
                    current = nxt
        else:
            filtered.append(current)
            current = nxt

    filtered.append(current)
    return filtered


# ─── 2. Tajweed Phonetic Cost Engine ───

ZERO_COST_MARKERS = {0x0686, 0x0687, 0x06DC, 0x0619, 0x06EA, 0x0640}  # چ, ڇ, ۜ, ؙ, ۪, ـ
HAMZA_VARIANTS = {0x0621, 0x0622, 0x0623, 0x0625, 0x0672}            # ء, آ, أ, إ, ٲ
TASHKEEL = {0x064E, 0x064F, 0x0650}                                    # َ, ُ, ِ

EQUIVALENT_GLYPH_PAIRS = {
    (0x0645, 0x06FE),  # م <-> ۾ (Iqlab)
    (0x0646, 0x06BA),  # ن <-> ں (Ikhfaa)
    (0x0648, 0x06E5),  # و <-> ۥ (Small Waw)
    (0x064A, 0x06E6),  # ي <-> ۦ (Small Yaa)
    (0x0629, 0x0647),  # ة <-> ه (Waqf)
    (0x0629, 0x062A),  # ة <-> ت (Wasl)
}

ACOUSTIC_CONFUSIONS = {
    (ord('ا'), 0x064E),  # ا <-> َ
    (ord('و'), 0x064F),  # و <-> ُ
    (0x064F, 0x06E5),   # ُ <-> ۥ
    (ord('ي'), 0x0650),  # ي <-> ِ
    (0x0650, 0x06E6),   # ِ <-> ۦ
    (ord('ت'), ord('ط')),
    (ord('ج'), ord('ز')),
    (ord('خ'), ord('غ')),
    (ord('د'), ord('ض')),
    (ord('ذ'), ord('ز')),
    (ord('ذ'), ord('ظ')),
    (ord('س'), ord('ص')),
    (ord('ق'), ord('ك')),
}


class PhoneticCostEngine:
    """Evaluates phonetic, acoustic, and Tajweed costs between ASR and Medina text."""

    @staticmethod
    def is_zero_cost_marker(code_unit: int) -> bool:
        return code_unit in ZERO_COST_MARKERS

    @staticmethod
    def is_zero_cost_token(token: str) -> bool:
        return token in ('ـ', 'ــ', 'ۜ', 'ؙ', '۪', 'ڇ', 'چ')

    @classmethod
    def is_equivalent_glyph(cls, a: int, b: int) -> bool:
        if a == b:
            return True
        if a in HAMZA_VARIANTS and b in HAMZA_VARIANTS:
            return True
        return (min(a, b), max(a, b)) in EQUIVALENT_GLYPH_PAIRS

    @staticmethod
    def is_acoustic_confusion(a: int, b: int) -> bool:
        return (min(a, b), max(a, b)) in ACOUSTIC_CONFUSIONS

    @staticmethod
    def is_tashkeel(code: int) -> bool:
        return code in TASHKEEL

    @classmethod
    def get_substitution_cost(cls, asr_code: int, ref_code: int, confusion_cost: float = 0.25) -> float:
        if asr_code == 0 or ref_code == 0:
            return 1.0
        if asr_code == ref_code or cls.is_equivalent_glyph(asr_code, ref_code):
            return 0.0
        if cls.is_acoustic_confusion(asr_code, ref_code):
            return confusion_cost
        if cls.is_tashkeel(asr_code) or cls.is_tashkeel(ref_code):
            return 1.0
        return 1.0

    @classmethod
    def get_deletion_cost(cls, full_phonemes: str, idx: int, standard_cost: float = 1.0, confusion_cost: float = 0.25) -> float:
        if idx < 0 or idx >= len(full_phonemes):
            return standard_cost
        code = ord(full_phonemes[idx])
        if cls.is_zero_cost_marker(code):
            return 0.0
        if code in (ord('ا'), 0x0671):  # Alif / Wasl Alif
            return confusion_cost
        if idx > 0 and ord(full_phonemes[idx - 1]) == code:
            return confusion_cost
        return standard_cost

    @classmethod
    def get_insertion_cost(cls, asr_text: str, idx: int, standard_cost: float = 0.75, confusion_cost: float = 0.25) -> float:
        if idx < 0 or idx >= len(asr_text):
            return standard_cost
        code = ord(asr_text[idx])
        if cls.is_zero_cost_marker(code):
            return 0.0
        if idx > 0 and ord(asr_text[idx - 1]) == code:
            return confusion_cost
        return standard_cost

    @classmethod
    def get_effective_length(cls, full_phonemes: str, start: int, end: int) -> int:
        count = 0
        for i in range(start, end):
            if not cls.is_zero_cost_marker(ord(full_phonemes[i])):
                count += 1
        return max(1, count)


# ─── 3. Phonetic Search Engine (Binary NPY Index) ───

@dataclass
class SurahMatchSpan:
    surah_idx: int
    ayah_idx: int
    uthmani_word_idx: int
    uthmani_char_idx: int
    phonemes_idx: int


@dataclass
class SurahSearchResult:
    start: SurahMatchSpan
    end: SurahMatchSpan
    mid: SurahMatchSpan
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


@dataclass
class SurahAudioBlock:
    block_index: int
    surah_number: int
    surah_name_ar: str
    surah_name_en: str
    start_ayah: int
    end_ayah: int
    start_time_seconds: float
    end_time_seconds: float
    start_phoneme_idx: int
    end_phoneme_idx: int
    confidence: float = 1.0
    phonemes: List[PhonemeToken] = field(default_factory=list)


@dataclass
class _TimelineProbe:
    phoneme_idx: int
    timestamp: float
    surah: int
    ayah: int
    distance: int


class PhoneticSearch:
    """Fast global search over the normalized Quranic binary database."""

    _core_chars = "ءبتثجحخدذرزسشصضطظعغفقكلمنهوياۥۦ۾ںـٲ"
    _residual_chars = "َُِڇؙ۪ۜ"
    _core_group = "|".join(f"{c}+" for c in _core_chars)
    _chunk_regex = re.compile(f"((?:{_core_group})[{_residual_chars}]?)")

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

    @classmethod
    def normalize_query(cls, query: str) -> str:
        parts = []
        for match in cls._chunk_regex.finditer(query):
            group = match.group(1)
            if group:
                parts.append(group[0])
        return "".join(parts)

    def _ref_idx_to_span(self, ref_idx: int, is_end: bool = False) -> SurahMatchSpan:
        row = self._index_array[ref_idx]
        return SurahMatchSpan(
            surah_idx=int(row[0]),
            ayah_idx=int(row[1]),
            uthmani_word_idx=int(row[2]),
            uthmani_char_idx=int(row[4] if is_end else row[3]),
            phonemes_idx=int(row[6] if is_end else row[5]),
        )

    def search(self, query: str, error_ratio: float = 0.20) -> List[SurahSearchResult]:
        if not self._is_loaded or not self._ref_ph_norm:
            return []
        norm_query = self.normalize_query(query)
        if not norm_query:
            return []

        if len(norm_query) > 64:
            norm_query = norm_query[:64]
        max_edits = int(len(norm_query) * error_ratio)

        if self._ref_codes is not None and HAS_NUMBA:
            q_codes = np.array([ord(c) for c in norm_query], dtype=np.int32)
            starts, ends, dists = _bit_parallel_search_fast(q_codes, self._ref_codes, max_edits)
            outs = _filter_overlapping([FuzzyMatch(int(s), int(e), int(d)) for s, e, d in zip(starts, ends, dists)])
        else:
            outs = find_near_matches(norm_query, self._ref_ph_norm, max_edits)

        results = [
            SurahSearchResult(
                start=self._ref_idx_to_span(out.start, is_end=False),
                end=self._ref_idx_to_span(out.end - 1, is_end=True),
                mid=self._ref_idx_to_span((out.start + out.end - 1) // 2, is_end=False),
                distance=out.dist,
            )
            for out in outs
        ]
        results.sort(key=lambda r: r.distance)
        return results


# ─── 4. Semi-Global DTW Matcher ───

@dataclass(frozen=True)
class MatcherConfig:
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


@dataclass
class PhonemeGroupAlignment:
    op_type: str  # 'match', 'replace', 'delete', 'insert'
    ref_idx: int
    pred_idx: int


@dataclass
class WordMatchResult:
    path_cost: float
    tokens_consumed: int
    clean_asr: str
    timestamps: List[float]
    trace: List[PhonemeGroupAlignment]
    start_token_idx: int = 0
    is_partial: bool = False


class QuranDictationMatcher:
    """Semi-Global DTW Matcher operating on character strings with free leading start."""

    def __init__(self):
        self._dp = np.zeros(2048, dtype=np.float64)
        self._bt = np.zeros(2048, dtype=np.uint8)

    def match_word(
        self,
        asr_text: str,
        asr_timestamps: List[float],
        full_phonemes: str,
        ref_start: int,
        ref_end: int,
        config: MatcherConfig = MatcherConfig(),
        is_tajweed: bool = False,
    ) -> Optional[WordMatchResult]:
        m = len(asr_text)
        n = ref_end - ref_start
        if m == 0 or n <= 0:
            return None

        stride = n + 1
        cells = (m + 1) * stride
        if len(self._dp) < cells:
            sz = max(cells, len(self._dp) * 2)
            self._dp = np.zeros(sz, dtype=np.float64)
            self._bt = np.zeros(sz, dtype=np.uint8)

        dp, bt = self._dp, self._bt

        if HAS_NUMBA:
            a_codes = np.array([ord(c) for c in asr_text], dtype=np.int32)
            r_codes = np.array([ord(c) for c in full_phonemes[ref_start:ref_end]], dtype=np.int32)
            ins_costs = np.array([
                PhoneticCostEngine.get_insertion_cost(asr_text, i, config.standard_insertion_cost, config.acoustic_confusion_cost)
                for i in range(m)
            ], dtype=np.float64)
            del_costs = np.array([
                PhoneticCostEngine.get_deletion_cost(full_phonemes, ref_start + j, config.standard_deletion_cost, config.acoustic_confusion_cost)
                for j in range(n)
            ], dtype=np.float64)
            _dtw_fill_fast(a_codes, r_codes, ins_costs, del_costs, config.acoustic_confusion_cost, dp, bt, stride)
        else:
            dp[0] = 0.0
            bt[0] = 0
            for j in range(1, n + 1):
                del_cost = PhoneticCostEngine.get_deletion_cost(full_phonemes, ref_start + j - 1, config.standard_deletion_cost, config.acoustic_confusion_cost)
                dp[j] = dp[j - 1] + del_cost
                bt[j] = 1

            for i in range(1, m + 1):
                dp[i * stride] = 0.0
                bt[i * stride] = 2

            for i in range(1, m + 1):
                a_code = ord(asr_text[i - 1])
                row = i * stride
                prev = (i - 1) * stride
                ins_cost = PhoneticCostEngine.get_insertion_cost(asr_text, i - 1, config.standard_insertion_cost, config.acoustic_confusion_cost)

                for j in range(1, n + 1):
                    r_ref = ref_start + j - 1
                    r_code = ord(full_phonemes[r_ref])
                    sub_cost = PhoneticCostEngine.get_substitution_cost(a_code, r_code, config.acoustic_confusion_cost)
                    del_cost = PhoneticCostEngine.get_deletion_cost(full_phonemes, r_ref, config.standard_deletion_cost, config.acoustic_confusion_cost)

                    sub = dp[prev + j - 1] + sub_cost
                    del_val = dp[row + j - 1] + del_cost
                    ins = dp[prev + j] + ins_cost

                    if sub < del_val and sub <= ins:
                        dp[row + j] = sub
                        bt[row + j] = 0
                    elif del_val <= ins:
                        dp[row + j] = del_val
                        bt[row + j] = 1
                    else:
                        dp[row + j] = ins
                        bt[row + j] = 2

        best_i = -1
        best_cost = float("inf")
        eff_n = PhoneticCostEngine.get_effective_length(full_phonemes, ref_start, ref_end)

        if eff_n <= 3:
            threshold = config.short_word_path_cost
        elif eff_n <= 5:
            threshold = config.medium_word_path_cost
        elif is_tajweed:
            threshold = config.relaxed_max_path_cost
        else:
            threshold = config.default_max_path_cost

        for i in range(1, m + 1):
            norm = dp[i * stride + n] / eff_n
            if norm <= threshold and norm < best_cost:
                best_i = i
                best_cost = norm

        # Partial matching check
        is_partial = False
        if is_tajweed and best_i > 0 and best_i == m:
            cur_j = n
            cur_i = best_i
            has_core_consonant_missing = False
            while cur_j > 0 and cur_i == best_i and bt[cur_i * stride + cur_j] == 1:
                r_code = ord(full_phonemes[ref_start + cur_j - 1])
                is_repeated = cur_j > 1 and r_code == ord(full_phonemes[ref_start + cur_j - 2])
                if (not PhoneticCostEngine.is_tashkeel(r_code) and
                        not PhoneticCostEngine.is_zero_cost_marker(r_code) and
                        not is_repeated):
                    has_core_consonant_missing = True
                    break
                cur_j -= 1

            if has_core_consonant_missing:
                is_partial = True
            elif cur_j > 0 and bt[cur_i * stride + cur_j] == 0:
                asr_code = ord(asr_text[best_i - 1])
                ref_code = ord(full_phonemes[ref_start + cur_j - 1])
                if not (PhoneticCostEngine.is_tashkeel(asr_code) and PhoneticCostEngine.is_tashkeel(ref_code)):
                    if PhoneticCostEngine.get_substitution_cost(asr_code, ref_code) > 0.0:
                        is_partial = True
        elif best_i < 0:
            min_j = 2 if n > 2 else 1
            start_i = max(1, m - 2)
            for i in range(start_i, m + 1):
                for j in range(min_j, n):
                    if dp[i * stride + j] / j <= threshold:
                        is_partial = True
                        break
                if is_partial:
                    break

        if is_partial:
            return WordMatchResult(
                path_cost=0.0,
                tokens_consumed=0,
                clean_asr="",
                timestamps=[],
                trace=[],
                is_partial=True,
            )

        if best_i < 0:
            return None

        # Traceback
        ci, cj = best_i, n
        raw_trace: List[PhonemeGroupAlignment] = []
        ts: List[float] = []

        while cj > 0:
            if ci == 0:
                raw_trace.append(PhonemeGroupAlignment("delete", ref_start + cj - 1, -1))
                cj -= 1
                continue
            op = bt[ci * stride + cj]
            g_ref = ref_start + cj - 1
            if op == 0:
                is_match = PhoneticCostEngine.get_substitution_cost(ord(asr_text[ci - 1]), ord(full_phonemes[g_ref])) == 0.0
                raw_trace.append(PhonemeGroupAlignment("match" if is_match else "replace", g_ref, ci - 1))
                if ci - 1 < len(asr_timestamps):
                    ts.append(asr_timestamps[ci - 1])
                ci -= 1
                cj -= 1
            elif op == 1:
                raw_trace.append(PhonemeGroupAlignment("delete", g_ref, -1))
                cj -= 1
            else:
                raw_trace.append(PhonemeGroupAlignment("insert", g_ref, ci - 1))
                ci -= 1

        raw_trace.reverse()
        ts.reverse()
        clean_asr = asr_text[:best_i]

        first_pred = -1
        for a in raw_trace:
            if a.pred_idx >= 0:
                first_pred = a.pred_idx
                break
        start_token_idx = first_pred if first_pred >= 0 else 0

        return WordMatchResult(
            path_cost=best_cost,
            tokens_consumed=best_i,
            clean_asr=clean_asr,
            timestamps=ts,
            trace=raw_trace,
            start_token_idx=start_token_idx,
        )


# ─── 5. Unified Word Sequencer ───

@dataclass
class RefWord:
    global_index: int
    surah: int
    ayah: int
    word_index_in_ayah: int
    text: str
    ref_phoneme: str
    location: str


class DictationSequencer:
    """Continuous word sequencer with Wasl merging, omissions, and repetitions."""

    def __init__(self):
        self._matcher = QuranDictationMatcher()

    def reset(self) -> None:
        pass

    def sequence_words(
        self,
        asr_text: str,
        asr_start_timestamps: List[float],
        asr_end_timestamps: List[float],
        char_to_tokens: List[PhonemeToken],
        ref_words: List[RefWord],
        config: MatcherConfig = MatcherConfig(),
        default_start_time: float = 0.0,
        ayah_start_indices: Optional[List[int]] = None,
    ) -> Tuple[List[QuranWord], List[Dict[str, Any]], List[str], bool]:
        ayah_start_indices = ayah_start_indices if ayah_start_indices is not None else []
        word_count = len(ref_words)
        if word_count == 0 or not asr_text:
            missing_words = [
                QuranWord(word=w.text, location=w.location, start=round(default_start_time, 2), end=round(default_start_time + 0.05, 2), score=0.0, confidence=0.0)
                for w in ref_words
            ]
            return missing_words, [], [], True

        word_boundaries = [0]
        for w in ref_words:
            word_boundaries.append(word_boundaries[-1] + len(w.ref_phoneme))
        full_phonemes = "".join(w.ref_phoneme for w in ref_words)

        asr_char_anchor = 0
        word_cursor = 0
        last_word_end = default_start_time

        committed_words: Dict[int, QuranWord] = {}
        repeated_ranges: List[Dict[str, Any]] = []
        repeated_text: List[str] = []
        has_missing = False
        highest_word_reached = 0

        rep_start_word: Optional[int] = None
        rep_max_end_word: Optional[int] = None
        rep_start_time: Optional[float] = None
        rep_end_time: Optional[float] = None
        rep_first_start_time: Optional[float] = None
        rep_first_end_time: Optional[float] = None
        rep_first_words: Dict[int, QuranWord] = {}

        def flush_repetition() -> None:
            nonlocal rep_start_word, rep_max_end_word, rep_start_time, rep_end_time
            nonlocal rep_first_start_time, rep_first_end_time
            if rep_start_word is None:
                return

            s_w = rep_start_word
            e_w = min(rep_max_end_word if rep_max_end_word is not None else s_w, word_count - 1)
            rep_txt = " ".join(ref_words[i].text for i in range(s_w, e_w + 1))
            is_intra_ayah = (ref_words[s_w].ayah == ref_words[e_w].ayah)

            rep_words_list: List[QuranWord] = []
            for s in range(s_w, e_w + 1):
                if s in rep_first_words:
                    rep_words_list.append(rep_first_words[s])

            start_ts_val = rep_start_time if rep_start_time is not None else 0.0
            end_ts_val = rep_end_time if rep_end_time is not None else start_ts_val

            rep_entry: Dict[str, Any] = {
                "type": "intra_ayah" if is_intra_ayah else "cross_ayah",
                "from_ref": ref_words[s_w].location,
                "to_ref": ref_words[e_w].location,
                "text": rep_txt,
                "start_time": round(start_ts_val, 2),
                "end_time": round(end_ts_val, 2),
                "repetition_count": 1,
                "words": [w.to_dict() for w in rep_words_list],
            }
            if rep_first_start_time is not None:
                rep_entry["first_start_time"] = round(rep_first_start_time, 2)
            if rep_first_end_time is not None:
                rep_entry["first_end_time"] = round(rep_first_end_time, 2)

            repeated_ranges.append(rep_entry)
            repeated_text.append(rep_txt)
            rep_start_word = None
            rep_max_end_word = None
            rep_start_time = None
            rep_end_time = None
            rep_first_start_time = None
            rep_first_end_time = None
            rep_first_words.clear()

        while asr_char_anchor < len(asr_text) and word_cursor < word_count:
            unconsumed_len = len(asr_text) - asr_char_anchor
            ts_start = min(asr_char_anchor, len(asr_start_timestamps))
            unconsumed_tokens = char_to_tokens[ts_start:]
            unconsumed_start_ts = asr_start_timestamps[ts_start:]
            unconsumed_end_ts = asr_end_timestamps[ts_start:]

            best_result: Optional[WordMatchResult] = None
            best_target_w = -1
            best_merge = 1
            best_score = float("inf")
            waiting_for_partial = False

            def evaluate_candidate(target_w: int, merge: int) -> bool:
                nonlocal best_score, best_result, best_target_w, best_merge, waiting_for_partial
                if target_w < 0:
                    return False
                end_w = target_w + merge - 1
                if end_w >= word_count:
                    return False

                r_start = word_boundaries[target_w]
                r_end = (
                    word_boundaries[end_w + 1]
                    if end_w + 1 < len(word_boundaries)
                    else len(full_phonemes)
                )

                delta = target_w - word_cursor
                if delta != 0 and merge == 1:
                    eff_n = PhoneticCostEngine.get_effective_length(full_phonemes, r_start, r_end)
                    if eff_n < 4:
                        return False

                n = r_end - r_start
                max_win = min(unconsumed_len, max(45, n * 3 + 25))

                res = self._matcher.match_word(
                    asr_text=asr_text[asr_char_anchor:asr_char_anchor + max_win],
                    asr_timestamps=asr_start_timestamps[ts_start:min(len(asr_start_timestamps), ts_start + max_win)],
                    full_phonemes=full_phonemes,
                    ref_start=r_start,
                    ref_end=r_end,
                    config=config,
                    is_tajweed=True,
                )
                if res is None:
                    return False
                if res.is_partial:
                    if unconsumed_len <= max_win:
                        waiting_for_partial = True
                        return True
                    return False
                if res.tokens_consumed == 0:
                    return False

                if merge > 1 and not self._is_valid_merge(
                    res, target_w, end_w, word_boundaries, full_phonemes, asr_text[asr_char_anchor:asr_char_anchor + max_win], config
                ):
                    return False

                transition_penalty = (
                    0.0 if delta == 0 else (0.10 * delta if delta > 0 else (0.25 + 0.04 * abs(delta)))
                )
                onset_penalty = res.start_token_idx * 0.15
                score = res.path_cost + transition_penalty + onset_penalty

                if score < best_score:
                    best_score = score
                    best_result = res
                    best_target_w = target_w
                    best_merge = merge
                return True

            for merge in (1, 2):
                evaluate_candidate(word_cursor, merge)
                if waiting_for_partial:
                    break
            if waiting_for_partial:
                break

            immediate_in_order = (
                best_result is not None
                and best_target_w == word_cursor
                and best_result.start_token_idx <= 2
                and best_result.path_cost <= config.default_max_path_cost
            )

            if not immediate_in_order:
                for s in range(1, config.max_skip_words + 1):
                    if word_cursor + s < word_count:
                        for merge in (1, 2):
                            evaluate_candidate(word_cursor + s, merge)

                current_ayah_start = 0
                for idx in ayah_start_indices:
                    if idx <= word_cursor:
                        current_ayah_start = idx
                lookback_limit = min(word_cursor - current_ayah_start + 1, 15)
                for b in range(1, lookback_limit + 1):
                    target_w = word_cursor - b
                    for merge in (2, 1):
                        evaluate_candidate(target_w, merge)

            if best_result is not None:
                target_w = best_target_w
                merge = best_merge
                result = best_result
                delta = target_w - word_cursor
                end_w = target_w + merge - 1
                chars_consumed = result.tokens_consumed
                w_start = (
                    result.timestamps[0]
                    if result.timestamps
                    else (unconsumed_start_ts[0] if unconsumed_start_ts else last_word_end)
                )
                last_char_idx = min(chars_consumed - 1, len(unconsumed_end_ts) - 1)
                w_end = (
                    max(w_start + 0.05, unconsumed_end_ts[last_char_idx])
                    if last_char_idx >= 0
                    else (w_start + 0.1)
                )
                word_score = max(0.0, min(1.0, 1.0 - result.path_cost))

                # Repetition state machine
                if delta < 0:
                    if rep_start_word is None:
                        rep_start_word = target_w
                        rep_max_end_word = end_w
                        rep_start_time = w_start
                        rep_end_time = w_end
                        rep_first_start_time = (
                            committed_words[target_w].start if target_w in committed_words else None
                        )
                        rep_first_end_time = (
                            committed_words[end_w].end if end_w in committed_words else None
                        )
                        rep_first_words.clear()
                        for s in range(target_w, highest_word_reached + 1):
                            if s in committed_words:
                                rep_first_words[s] = committed_words[s]
                    else:
                        rep_max_end_word = max(rep_max_end_word, end_w)
                        rep_end_time = w_end
                else:
                    if rep_start_word is not None:
                        if target_w <= highest_word_reached:
                            rep_max_end_word = max(rep_max_end_word, end_w)
                            rep_end_time = w_end
                        else:
                            flush_repetition()

                    if delta > 0 and rep_start_word is None:
                        for s in range(word_cursor, target_w):
                            if s not in committed_words:
                                rw = ref_words[s]
                                committed_words[s] = QuranWord(
                                    word=rw.text, location=rw.location, start=round(last_word_end, 2), end=round(last_word_end + 0.05, 2), score=0.0, confidence=0.0
                                )
                                has_missing = True

                self._commit_words_green(
                    committed_words=committed_words,
                    ref_words=ref_words,
                    start_w=target_w,
                    end_w=end_w,
                    merge=merge,
                    chars_consumed=chars_consumed,
                    w_start=w_start,
                    w_end=w_end,
                    word_score=word_score,
                    trace=result.trace,
                    unconsumed_tokens=unconsumed_tokens,
                    unconsumed_start_ts=unconsumed_start_ts,
                    unconsumed_end_ts=unconsumed_end_ts,
                    word_boundaries=word_boundaries,
                )

                if end_w > highest_word_reached:
                    highest_word_reached = end_w

                asr_char_anchor += chars_consumed
                last_word_end = w_end
                word_cursor = end_w + 1
            else:
                break

        if rep_start_word is not None:
            flush_repetition()

        limit = min(word_count, max(word_cursor, highest_word_reached + 1))
        for w in range(limit):
            if w not in committed_words:
                rw = ref_words[w]
                committed_words[w] = QuranWord(
                    word=rw.text, location=rw.location, start=round(last_word_end, 2), end=round(last_word_end + 0.05, 2), score=0.0, confidence=0.0
                )
                has_missing = True

        final_words = [committed_words[w] for w in range(limit)]
        return final_words, repeated_ranges, repeated_text, has_missing

    def _commit_words_green(
        self,
        committed_words: Dict[int, QuranWord],
        ref_words: List[RefWord],
        start_w: int,
        end_w: int,
        merge: int,
        chars_consumed: int,
        w_start: float,
        w_end: float,
        word_score: float,
        trace: List[PhonemeGroupAlignment],
        unconsumed_tokens: List[PhonemeToken],
        unconsumed_start_ts: List[float],
        unconsumed_end_ts: List[float],
        word_boundaries: List[int],
    ) -> None:
        pure_tokens: List[PhonemeToken] = []
        seen = set()
        for align in trace:
            if 0 <= align.pred_idx < len(unconsumed_tokens):
                t = unconsumed_tokens[align.pred_idx]
                t_id = id(t)
                if t_id not in seen:
                    seen.add(t_id)
                    pure_tokens.append(t)

        if not pure_tokens and unconsumed_tokens:
            for c in range(min(chars_consumed, len(unconsumed_tokens))):
                t = unconsumed_tokens[c]
                t_id = id(t)
                if t_id not in seen:
                    seen.add(t_id)
                    pure_tokens.append(t)

        if (
            chars_consumed < len(unconsumed_tokens)
            and pure_tokens
            and pure_tokens[-1] is unconsumed_tokens[chars_consumed]
        ):
            pure_tokens.pop()

        avg_conf = sum(p.confidence for p in pure_tokens) / len(pure_tokens) if pure_tokens else 1.0

        def make_word(idx: int, s: float, e: float, conf: float, toks: List[PhonemeToken]) -> QuranWord:
            rw = ref_words[idx]
            return QuranWord(
                word=rw.text,
                location=rw.location,
                start=round(s, 2),
                end=round(e, 2),
                score=round(word_score, 2),
                confidence=round(conf, 4),
                phonemes=[p.to_dict() for p in toks],
            )

        if merge == 1:
            w_s = pure_tokens[0].start if pure_tokens else w_start
            w_e = pure_tokens[-1].end if pure_tokens else w_end
            committed_words[start_w] = make_word(start_w, w_s, w_e, avg_conf, pure_tokens)
        else:
            boundary = word_boundaries[start_w + 1]
            tokens1: List[PhonemeToken] = []
            tokens2: List[PhonemeToken] = []
            seen1 = set()
            seen2 = set()

            for align in trace:
                if 0 <= align.pred_idx < len(unconsumed_tokens):
                    t = unconsumed_tokens[align.pred_idx]
                    t_id = id(t)
                    if align.ref_idx < boundary:
                        if t_id not in seen1:
                            seen1.add(t_id)
                            tokens1.append(t)
                    else:
                        if t_id not in seen1 and t_id not in seen2:
                            seen2.add(t_id)
                            tokens2.append(t)

            len1 = word_boundaries[start_w + 1] - word_boundaries[start_w]
            len2 = word_boundaries[start_w + 2] - word_boundaries[start_w + 1]
            split_char = max(1, min(chars_consumed - 1, round(chars_consumed * len1 / max(1, len1 + len2))))

            fallback_w1_start = w_start
            fallback_w1_end = (
                max(fallback_w1_start + 0.05, unconsumed_end_ts[split_char - 1])
                if split_char - 1 < len(unconsumed_end_ts)
                else w_end
            )
            fallback_w2_start = (
                max(fallback_w1_end, unconsumed_start_ts[split_char])
                if split_char < len(unconsumed_start_ts)
                else fallback_w1_end
            )
            fallback_w2_end = max(fallback_w2_start + 0.05, w_end)

            w1_s = tokens1[0].start if tokens1 else fallback_w1_start
            w1_e = tokens1[-1].end if tokens1 else fallback_w1_end
            w2_s = tokens2[0].start if tokens2 else fallback_w2_start
            w2_e = tokens2[-1].end if tokens2 else fallback_w2_end

            conf1 = sum(p.confidence for p in tokens1) / len(tokens1) if tokens1 else avg_conf
            conf2 = sum(p.confidence for p in tokens2) / len(tokens2) if tokens2 else avg_conf

            committed_words[start_w] = make_word(start_w, w1_s, w1_e, conf1, tokens1)
            committed_words[start_w + 1] = make_word(start_w + 1, w2_s, w2_e, conf2, tokens2)

    def _is_valid_merge(
        self,
        result: WordMatchResult,
        start_w: int,
        end_w: int,
        word_boundaries: List[int],
        full_phonemes: str,
        asr_text: str,
        config: MatcherConfig,
    ) -> bool:
        if start_w == end_w:
            return True

        for w in range(start_w, end_w + 1):
            ref_start = word_boundaries[w]
            ref_end = (
                word_boundaries[w + 1]
                if w + 1 < len(word_boundaries)
                else len(full_phonemes)
            )
            word_len = ref_end - ref_start
            forgive_start = min(2, word_len // 3) if w > start_w else 0
            forgive_end = min(2, word_len // 3) if w < end_w else 0
            core_start = ref_start + forgive_start
            core_end = ref_end - forgive_end
            core_len = core_end - core_start

            if core_len <= 0:
                continue
            core_cost = 0.0

            for align in result.trace:
                if core_start <= align.ref_idx < core_end:
                    if align.op_type == "delete":
                        core_cost += config.standard_deletion_cost
                    elif align.op_type == "replace":
                        if (
                            align.pred_idx >= 0
                            and align.ref_idx >= 0
                            and align.pred_idx < len(asr_text)
                        ):
                            asr_code = ord(asr_text[align.pred_idx])
                            ref_code = ord(full_phonemes[align.ref_idx])
                            core_cost += PhoneticCostEngine.get_substitution_cost(asr_code, ref_code)
                        else:
                            core_cost += config.standard_insertion_cost

            if (core_cost / core_len) > config.default_max_path_cost:
                return False

        return True


# ─── 6. Multi-Surah Finder & Verse Partitioning ───

class MultiSurahFinder:
    """Detects single or multiple Surah blocks in continuous recitation audio."""

    def __init__(self):
        self._phonetic_search = PhoneticSearch()
        self._verses: Dict[str, Any] = {}
        self._is_initialized = False

    @property
    def is_initialized(self) -> bool:
        return self._is_initialized

    def initialize(
        self,
        quran_json_path: Optional[str] = None,
        ref_norm_ph_path: Optional[str] = None,
        ph_index_path: Optional[str] = None,
    ) -> None:
        if self._is_initialized:
            return
        json_path = quran_json_path or DEFAULT_QURAN_PHONEMES_PATH
        if os.path.exists(json_path):
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                self._verses = data.get("verses", {})

        self._phonetic_search.load(ref_norm_ph_path=ref_norm_ph_path, ph_index_path=ph_index_path)
        self._is_initialized = True

    def _get_surah_metadata(self, surah: int, ayah: int) -> Dict[str, str]:
        key = f"{surah}:{ayah}"
        if key in self._verses:
            v = self._verses[key]
            return {
                "ar": str(v.get("suraname_ar", "")),
                "en": str(v.get("suraname_en", "")),
            }
        return {"ar": "", "en": ""}

    def _probe_offsets(self, tokens: List[PhonemeToken], length: int, exclude_surah_1: bool = False) -> Optional[SurahDetectionResult]:
        for offset in (10, 16, 20, 24, 28, 30, 32, 36):
            if offset < len(tokens):
                post_q = "".join(p.phoneme for p in tokens[offset:offset + length])
                if len(post_q) >= 6:
                    post_res = self._phonetic_search.search(post_q, error_ratio=0.25)
                    if post_res and (not exclude_surah_1 or post_res[0].surah_number != 1):
                        post_best = post_res[0]
                        return SurahDetectionResult(
                            surah=post_best.surah_number,
                            start_ayah=post_best.ayah_number,
                            end_ayah=post_best.ayah_number,
                            start_time=tokens[0].start,
                            end_time=tokens[-1].end,
                            confidence=max(0.5, 1.0 - (post_best.distance / max(1, len(post_q)))),
                        )
        return None

    def detect_single_surah(self, aligned_phonemes: List[PhonemeToken], sample_length: int = 35) -> SurahDetectionResult:
        if not aligned_phonemes:
            return SurahDetectionResult(surah=1, start_ayah=1, end_ayah=1)

        query_text = "".join(p.phoneme for p in aligned_phonemes[:sample_length])
        results = self._phonetic_search.search(query_text, error_ratio=0.25)

        if results:
            best = results[0]
            if best.surah_number == 1 and best.ayah_number == 1 and len(aligned_phonemes) > 20:
                probed = self._probe_offsets(aligned_phonemes, sample_length, exclude_surah_1=True)
                if probed:
                    return probed
            return SurahDetectionResult(
                surah=best.surah_number,
                start_ayah=best.ayah_number,
                end_ayah=best.ayah_number,
                start_time=aligned_phonemes[0].start,
                end_time=aligned_phonemes[-1].end,
                confidence=max(0.5, 1.0 - (best.distance / max(1, len(query_text)))),
            )

        if len(aligned_phonemes) > 15:
            probed = self._probe_offsets(aligned_phonemes, sample_length, exclude_surah_1=False)
            if probed:
                return probed

        return SurahDetectionResult(surah=1, start_ayah=1, end_ayah=1, start_time=aligned_phonemes[0].start, end_time=aligned_phonemes[-1].end, confidence=0.5)

    def detect_multiple_surahs(
        self,
        aligned_phonemes: List[PhonemeToken],
        probe_window_size: int = 35,
        probe_step_size: int = 25,
    ) -> List[SurahAudioBlock]:
        if not aligned_phonemes:
            return []
        total_phonemes = len(aligned_phonemes)
        if total_phonemes < 80:
            single = self.detect_single_surah(aligned_phonemes)
            meta = self._get_surah_metadata(single.surah, single.start_ayah)
            return [
                SurahAudioBlock(
                    block_index=1,
                    surah_number=single.surah,
                    surah_name_ar=meta.get("ar", ""),
                    surah_name_en=meta.get("en", ""),
                    start_ayah=single.start_ayah,
                    end_ayah=single.end_ayah,
                    start_time_seconds=aligned_phonemes[0].start,
                    end_time_seconds=aligned_phonemes[-1].end,
                    start_phoneme_idx=0,
                    end_phoneme_idx=total_phonemes,
                    confidence=single.confidence,
                    phonemes=aligned_phonemes,
                )
            ]

        probes: List[_TimelineProbe] = []
        for idx in range(0, total_phonemes - 10, probe_step_size):
            length = min(probe_window_size, total_phonemes - idx)
            slice_tokens = aligned_phonemes[idx:idx + length]
            query = "".join(p.phoneme for p in slice_tokens)
            results = self._phonetic_search.search(query, error_ratio=0.22)
            if results:
                best = results[0]
                probes.append(
                    _TimelineProbe(
                        phoneme_idx=idx,
                        timestamp=slice_tokens[0].start,
                        surah=best.surah_number,
                        ayah=best.ayah_number,
                        distance=best.distance,
                    )
                )

        if not probes:
            single = self.detect_single_surah(aligned_phonemes)
            meta = self._get_surah_metadata(single.surah, single.start_ayah)
            return [
                SurahAudioBlock(
                    block_index=1,
                    surah_number=single.surah,
                    surah_name_ar=meta.get("ar", ""),
                    surah_name_en=meta.get("en", ""),
                    start_ayah=single.start_ayah,
                    end_ayah=single.end_ayah,
                    start_time_seconds=aligned_phonemes[0].start,
                    end_time_seconds=aligned_phonemes[-1].end,
                    start_phoneme_idx=0,
                    end_phoneme_idx=total_phonemes,
                    phonemes=aligned_phonemes,
                )
            ]

        blocks: List[SurahAudioBlock] = []
        block_idx = 1
        cur_surah = probes[0].surah
        cur_start_ayah = probes[0].ayah
        cur_max_ayah = probes[0].ayah
        cur_start_phoneme_idx = 0
        cur_start_time = aligned_phonemes[0].start

        for i in range(1, len(probes)):
            probe = probes[i]
            if probe.surah != cur_surah:
                confirmed = False
                if i + 1 < len(probes) and probes[i + 1].surah == probe.surah:
                    confirmed = True
                elif i + 1 >= len(probes):
                    confirmed = True

                if confirmed:
                    end_phoneme_idx = probe.phoneme_idx
                    end_time = aligned_phonemes[min(end_phoneme_idx, total_phonemes - 1)].start
                    meta = self._get_surah_metadata(cur_surah, cur_start_ayah)
                    slice_tokens = aligned_phonemes[cur_start_phoneme_idx:end_phoneme_idx]

                    blocks.append(
                        SurahAudioBlock(
                            block_index=block_idx,
                            surah_number=cur_surah,
                            surah_name_ar=meta.get("ar", ""),
                            surah_name_en=meta.get("en", ""),
                            start_ayah=cur_start_ayah,
                            end_ayah=cur_max_ayah,
                            start_time_seconds=cur_start_time,
                            end_time_seconds=end_time,
                            start_phoneme_idx=cur_start_phoneme_idx,
                            end_phoneme_idx=end_phoneme_idx,
                            phonemes=slice_tokens,
                        )
                    )
                    block_idx += 1
                    cur_surah = probe.surah
                    cur_start_ayah = probe.ayah
                    cur_max_ayah = probe.ayah
                    cur_start_phoneme_idx = end_phoneme_idx
                    cur_start_time = end_time
            else:
                if probe.ayah > cur_max_ayah:
                    cur_max_ayah = probe.ayah

        meta = self._get_surah_metadata(cur_surah, cur_start_ayah)
        slice_tokens = aligned_phonemes[cur_start_phoneme_idx:total_phonemes]
        blocks.append(
            SurahAudioBlock(
                block_index=block_idx,
                surah_number=cur_surah,
                surah_name_ar=meta.get("ar", ""),
                surah_name_en=meta.get("en", ""),
                start_ayah=cur_start_ayah,
                end_ayah=cur_max_ayah,
                start_time_seconds=cur_start_time,
                end_time_seconds=aligned_phonemes[-1].end,
                start_phoneme_idx=cur_start_phoneme_idx,
                end_phoneme_idx=total_phonemes,
                phonemes=slice_tokens,
            )
        )
        return blocks


# ─── 7. Unified QuranWordMatcher Entry Point ───

class QuranWordMatcher:
    """Unified Phase 3 Quran Text Matcher and Verse Finder engine."""

    _istiadhah_ph = "ءَعُۥذُبِللَااهِمِنَششَيطَاانِرَّجِۦۦۦۦم"
    _basmalah_ph = "بِسمِللَااهِررَحمَاانِررَحِۦۦۦۦم"

    def __init__(self, config: MatcherConfig = MatcherConfig()):
        self.config = config
        self.surah_finder = MultiSurahFinder()
        self._sequencer = DictationSequencer()
        self._dtw_matcher = QuranDictationMatcher()
        self._verses: Dict[str, Any] = {}
        self._is_initialized = False

    @property
    def is_initialized(self) -> bool:
        return self._is_initialized

    def initialize_from_file(
        self,
        json_file_path: Optional[str] = None,
        ref_norm_ph_path: Optional[str] = None,
        ph_index_path: Optional[str] = None,
    ) -> None:
        path = json_file_path or DEFAULT_QURAN_PHONEMES_PATH
        if not os.path.exists(path):
            raise FileNotFoundError(f"Quran phonemes file not found: {path}")

        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            self._verses = data.get("verses", {})

        self.surah_finder.initialize(
            quran_json_path=path,
            ref_norm_ph_path=ref_norm_ph_path or DEFAULT_REF_NORM_PH_PATH,
            ph_index_path=ph_index_path or DEFAULT_PH_INDEX_PATH,
        )
        self._is_initialized = True

    def _match_preamble(
        self,
        asr_text: str,
        char_start_ts: List[float],
        char_end_ts: List[float],
        ref_ph: str,
        preamble_type: str,
        text: str,
        max_chars: int = 60,
    ) -> Optional[Dict[str, Any]]:
        if len(asr_text) < 15:
            return None
        check_len = min(len(asr_text), max_chars)
        slice_text = asr_text[:check_len]
        slice_ts = char_start_ts[:check_len]

        res = self._dtw_matcher.match_word(
            asr_text=slice_text,
            asr_timestamps=slice_ts,
            full_phonemes=ref_ph,
            ref_start=0,
            ref_end=len(ref_ph),
            config=self.config,
        )
        if res is not None and res.tokens_consumed > 0 and res.path_cost <= 0.25:
            start_time = res.timestamps[0] if res.timestamps else (char_start_ts[0] if char_start_ts else 0.0)
            last_char = min(res.tokens_consumed - 1, len(char_end_ts) - 1)
            end_time = char_end_ts[last_char] if last_char >= 0 else (start_time + 0.5)
            return {
                "type": preamble_type,
                "text": text,
                "start_time": round(start_time, 2),
                "end_time": round(end_time, 2),
                "score": round(max(0.0, min(1.0, 1.0 - res.path_cost)), 2),
                "chars_consumed": res.tokens_consumed,
            }
        return None

    def match_segments(
        self,
        aligned_phonemes: List[PhonemeToken],
        audio_duration: float,
        target_surah: Optional[int] = None,
        start_ayah: Optional[int] = None,
    ) -> List[QuranSegment]:
        if not self._is_initialized:
            self.initialize_from_file()
        if not aligned_phonemes or not self._verses:
            return []

        if target_surah is not None:
            return self._match_surah_span(
                aligned_phonemes=aligned_phonemes,
                surah=target_surah,
                start_ayah=start_ayah or 1,
                start_segment_number=1,
            )

        surah_blocks = self.surah_finder.detect_multiple_surahs(aligned_phonemes)
        all_segments: List[QuranSegment] = []
        cur_seg = 1
        for block in surah_blocks:
            b_segs = self._match_surah_span(
                aligned_phonemes=block.phonemes,
                surah=block.surah_number,
                start_ayah=block.start_ayah,
                start_segment_number=cur_seg,
            )
            all_segments.extend(b_segs)
            cur_seg += len(b_segs)

        return all_segments

    def _match_surah_span(
        self,
        aligned_phonemes: List[PhonemeToken],
        surah: int,
        start_ayah: int,
        start_segment_number: int,
    ) -> List[QuranSegment]:
        if not aligned_phonemes:
            return []

        asr_buffer: List[str] = []
        char_start_ts: List[float] = []
        char_end_ts: List[float] = []
        char_to_tokens: List[PhonemeToken] = []

        for tok in aligned_phonemes:
            for ch in tok.phoneme:
                asr_buffer.append(ch)
                char_start_ts.append(tok.start)
                char_end_ts.append(tok.end)
                char_to_tokens.append(tok)

        full_asr_text = "".join(asr_buffer)
        current_char_idx = 0

        surah_words: List[RefWord] = []
        ayah_start_indices: List[int] = []
        ayah_texts: Dict[int, str] = {}

        a = start_ayah
        while f"{surah}:{a}" in self._verses:
            v_data = self._verses[f"{surah}:{a}"]
            ayah_text = v_data.get("aya_text", "")
            ph_words = v_data.get("aya_phonemes_list", [])
            text_words = [w for w in re.split(r"\s+", ayah_text.strip()) if w]

            if ph_words:
                ayah_start_indices.append(len(surah_words))
                ayah_texts[a] = ayah_text
                for i, ph_w in enumerate(ph_words):
                    txt = text_words[i] if i < len(text_words) else str(ph_w)
                    surah_words.append(
                        RefWord(
                            global_index=len(surah_words),
                            surah=surah,
                            ayah=a,
                            word_index_in_ayah=i + 1,
                            text=txt,
                            ref_phoneme=str(ph_w),
                            location=f"{surah}:{a}:{i + 1}",
                        )
                    )
            a += 1

        if not surah_words:
            return []

        initial_prologue: Optional[Dict[str, Any]] = None

        def apply_prologue(match: Optional[Dict[str, Any]]) -> None:
            nonlocal initial_prologue, current_char_idx
            if match is not None and initial_prologue is None:
                initial_prologue = match
                chars_consumed = match.pop("chars_consumed", 0)
                current_char_idx += chars_consumed

        if surah != 1 and surah != 9:
            apply_prologue(
                self._match_preamble(
                    asr_text=full_asr_text,
                    char_start_ts=char_start_ts,
                    char_end_ts=char_end_ts,
                    ref_ph=f"{self._istiadhah_ph}{self._basmalah_ph}",
                    preamble_type="istiadhah+basmalah",
                    text="أَعُوذُ بِٱللَّهِ مِنَ ٱلشَّيْطَـٰنِ ٱلرَّجِيمِ بِسْمِ ٱللَّهِ ٱلرَّحْمَـٰنِ ٱلرَّحِيمِ",
                    max_chars=120,
                )
            )

        apply_prologue(
            self._match_preamble(
                asr_text=full_asr_text,
                char_start_ts=char_start_ts,
                char_end_ts=char_end_ts,
                ref_ph=self._istiadhah_ph,
                preamble_type="istiadhah",
                text="أَعُوذُ بِٱللَّهِ مِنَ ٱلشَّيْطَـٰنِ ٱلرَّجِيمِ",
                max_chars=60,
            )
        )

        if initial_prologue is None and start_ayah == 1 and surah != 1 and surah != 9:
            apply_prologue(
                self._match_preamble(
                    asr_text=full_asr_text[current_char_idx:],
                    char_start_ts=char_start_ts[current_char_idx:],
                    char_end_ts=char_end_ts[current_char_idx:],
                    ref_ph=self._basmalah_ph,
                    preamble_type="basmalah",
                    text="بِسْمِ ٱللَّهِ ٱلرَّحْمَـٰنِ ٱلرَّحِيمِ",
                    max_chars=60,
                )
            )

        default_start = char_start_ts[current_char_idx] if current_char_idx < len(char_start_ts) else 0.0

        sequenced_words, rep_ranges, rep_texts, has_missing = self._sequencer.sequence_words(
            asr_text=full_asr_text[current_char_idx:],
            asr_start_timestamps=char_start_ts[current_char_idx:],
            asr_end_timestamps=char_end_ts[current_char_idx:],
            char_to_tokens=char_to_tokens[current_char_idx:],
            ref_words=surah_words,
            config=self.config,
            default_start_time=default_start,
            ayah_start_indices=ayah_start_indices,
        )

        words_by_ayah: Dict[int, List[QuranWord]] = {}
        for w in sequenced_words:
            if w.location:
                ay = int(w.location.split(":")[1])
                words_by_ayah.setdefault(ay, []).append(w)

        segments: List[QuranSegment] = []
        seg_num = start_segment_number

        for cur_ayah, a_words in words_by_ayah.items():
            if not a_words:
                continue

            v_key = f"{surah}:{cur_ayah}"
            a_text = ayah_texts.get(cur_ayah, "")

            a_reps = [
                r for r in rep_ranges
                if str(r.get("from_ref", "")).startswith(f"{surah}:{cur_ayah}:")
            ]

            a_start = a_words[0].start if a_words[0].start is not None else default_start
            a_end = a_words[-1].end if a_words[-1].end is not None else (a_start + 0.5)

            for rep in a_reps:
                fst = rep.get("first_start_time")
                if fst is not None and fst < a_start:
                    a_start = fst

            first_idx = -1
            for idx, ts in enumerate(char_start_ts):
                if ts >= a_start:
                    first_idx = idx
                    break

            last_match = -1
            for idx in range(len(char_end_ts) - 1, -1, -1):
                if char_end_ts[idx] <= a_end:
                    last_match = idx
                    break

            last_idx = min(len(full_asr_text), last_match + 1) if last_match >= 0 else len(full_asr_text)
            a_transcribed = full_asr_text[first_idx:last_idx] if (0 <= first_idx < last_idx) else ""
            a_rep_texts = [str(r.get("text", "")) for r in a_reps]

            green_count = sum(1 for w in a_words if (w.score or 0.0) > 0.0)
            score = green_count / max(1, len(a_words))

            seg = QuranSegment(
                segment_number=seg_num,
                surah_number=surah,
                start_time=round(a_start, 2),
                end_time=round(a_end, 2),
                transcribed_text=a_transcribed,
                matched_text=a_text,
                matched_ref=f"{v_key}:1-{v_key}:{len(a_words)}",
                match_score=round(score, 3),
                words=a_words,
                prologue=initial_prologue if cur_ayah == start_ayah else None,
                has_missing_words=any((w.score or 0.0) == 0.0 for w in a_words),
                has_repeated_words=bool(a_reps),
                repeated_ranges=a_reps,
                repeated_text=a_rep_texts,
            )
            segments.append(seg)
            seg_num += 1

        return segments
