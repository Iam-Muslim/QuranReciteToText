"""Tajweed Phonetic Matcher, Gene Myers' 64-bit Bit-Parallel Search & Word Sequencer."""

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


# ─── 1. Gene Myers' 64-bit Bit-Parallel Substring Search ───

@dataclass
class FuzzyMatch:
    start: int
    end: int
    dist: int


def find_near_matches(query: str, text: str, max_dist: int) -> List[FuzzyMatch]:
    n = len(query)
    m = len(text)
    if n == 0 or m == 0 or max_dist < 0:
        return []
    if n <= 64:
        return _bit_parallel_search(query, text, max_dist)
    return _dp_search(query, text, max_dist)


def _bit_parallel_search(query: str, text: str, max_dist: int) -> List[FuzzyMatch]:
    n = len(query)
    m = len(text)
    matches: List[FuzzyMatch] = []

    char_mask: Dict[int, int] = {}
    for i, ch in enumerate(query):
        code = ord(ch)
        char_mask[code] = char_mask.get(code, 0) | (1 << i)

    full_mask = (1 << n) - 1
    top_mask = 1 << (n - 1)
    vp = full_mask
    vn = 0
    curr_dist = n

    for j, ch in enumerate(text):
        pm = char_mask.get(ord(ch), 0)
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


def _dp_search(query: str, text: str, max_dist: int) -> List[FuzzyMatch]:
    matches: List[FuzzyMatch] = []
    n = len(query)
    m = len(text)

    prev_dist = list(range(n + 1))
    prev_start = [0] * (n + 1)
    curr_dist = [0] * (n + 1)
    curr_start = [0] * (n + 1)

    query_units = [ord(c) for c in query]
    text_units = [ord(c) for c in text]

    for j in range(1, m + 1):
        curr_dist[0] = 0
        curr_start[0] = j
        text_char = text_units[j - 1]

        for i in range(1, n + 1):
            cost = 0 if query_units[i - 1] == text_char else 1
            replace_dist = prev_dist[i - 1] + cost
            replace_start = prev_start[i - 1]

            delete_query_dist = prev_dist[i] + 1
            delete_query_start = prev_start[i]

            insert_query_dist = curr_dist[i - 1] + 1
            insert_query_start = curr_start[i - 1]

            min_dist = replace_dist
            best_start = replace_start

            if (delete_query_dist < min_dist or
                    (delete_query_dist == min_dist and delete_query_start > best_start)):
                min_dist = delete_query_dist
                best_start = delete_query_start

            if (insert_query_dist < min_dist or
                    (insert_query_dist == min_dist and insert_query_start > best_start)):
                min_dist = insert_query_dist
                best_start = insert_query_start

            curr_dist[i] = min_dist
            curr_start[i] = best_start

        if curr_dist[n] <= max_dist:
            matches.append(FuzzyMatch(start=curr_start[n], end=j, dist=curr_dist[n]))

        prev_dist, curr_dist = curr_dist, prev_dist
        prev_start, curr_start = curr_start, prev_start

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

# Equivalent glyphs: (min_code, max_code)
EQUIVALENT_GLYPH_PAIRS = {
    (0x0645, 0x06FE),  # م <-> ۾ (Iqlab)
    (0x0646, 0x06BA),  # ن <-> ں (Ikhfaa)
    (0x0648, 0x06E5),  # و <-> ۥ (Small Waw)
    (0x064A, 0x06E6),  # ي <-> ۦ (Small Yaa)
    (0x0629, 0x0647),  # ة <-> ه (Waqf)
    (0x0629, 0x062A),  # ة <-> ت (Wasl)
}

# Acoustic confusion pairs: (min_code, max_code) -> 0.25 cost
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


class PhoneticSearch:
    """Fast global search over the normalized Quranic binary database."""

    _core_chars = "ءبتثجحخدذرزسشصضطظعغفقكلمنهوياۥۦ۾ںـٲ"
    _residual_chars = "َُِڇؙ۪ۜ"
    _core_group = "|".join(f"{c}+" for c in _core_chars)
    _chunk_regex = re.compile(f"((?:{_core_group})[{_residual_chars}]?)")

    def __init__(self):
        self._index_array: Optional[np.ndarray] = None
        self._ref_ph_norm: Optional[str] = None
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

        max_edits = int(len(norm_query) * error_ratio)
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

        return WordMatchResult(
            path_cost=best_cost,
            tokens_consumed=best_i,
            clean_asr=clean_asr,
            timestamps=ts,
            trace=raw_trace,
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
        committed_words: Dict[int, QuranWord] = {}
        repeated_ranges: List[Dict[str, Any]] = []
        repeated_text: List[str] = []
        has_missing = False

        while asr_char_anchor < len(asr_text) and word_cursor < word_count:
            ts_start = min(asr_char_anchor, len(asr_start_timestamps))
            unconsumed_text = asr_text[asr_char_anchor:]
            unconsumed_start_ts = asr_start_timestamps[ts_start:]
            unconsumed_tokens = char_to_tokens[ts_start:]

            best_result: Optional[WordMatchResult] = None
            best_target_w = -1
            best_merge = 1
            best_score = float("inf")

            def evaluate_candidate(target_w: int, merge: int) -> bool:
                nonlocal best_score, best_result, best_target_w, best_merge
                if target_w < 0 or target_w + merge - 1 >= word_count:
                    return False
                r_start = word_boundaries[target_w]
                r_end = word_boundaries[target_w + merge]

                res = self._matcher.match_word(
                    asr_text=unconsumed_text,
                    asr_timestamps=unconsumed_start_ts,
                    full_phonemes=full_phonemes,
                    ref_start=r_start,
                    ref_end=r_end,
                    config=config,
                    is_tajweed=True,
                )
                if res is None:
                    return False

                eff_n = PhoneticCostEngine.get_effective_length(full_phonemes, r_start, r_end)
                cost = res.path_cost
                if cost < best_score:
                    best_score = cost
                    best_result = res
                    best_target_w = target_w
                    best_merge = merge
                return True

            # 1. Forward candidates (Local + Lookahead)
            for m in (1, 2, 3):
                evaluate_candidate(word_cursor, m)

            for skip in range(1, config.max_skip_words + 1):
                evaluate_candidate(word_cursor + skip, 1)

            # 2. Backward repetitions
            if best_result is None or best_score > 0.20:
                back_limit = max(0, word_cursor - config.max_backtrack_words)
                for b_w in range(word_cursor - 1, back_limit - 1, -1):
                    evaluate_candidate(b_w, 1)

            if best_result is not None and best_result.tokens_consumed > 0:
                s_tok = unconsumed_tokens[0] if unconsumed_tokens else None
                e_idx = min(best_result.tokens_consumed - 1, len(unconsumed_tokens) - 1)
                e_tok = unconsumed_tokens[e_idx] if e_idx >= 0 else s_tok

                w_start = s_tok.start if s_tok else 0.0
                w_end = e_tok.end if e_tok else (w_start + 0.5)
                matched_tokens = unconsumed_tokens[:best_result.tokens_consumed]
                avg_conf = sum(p.confidence for p in matched_tokens) / len(matched_tokens) if matched_tokens else 1.0
                word_score = max(0.0, min(1.0, 1.0 - best_result.path_cost))

                # Mark skipped words as missing (red)
                if best_target_w > word_cursor:
                    has_missing = True
                    for missing_w in range(word_cursor, best_target_w):
                        rw = ref_words[missing_w]
                        committed_words[missing_w] = QuranWord(
                            word=rw.text, location=rw.location, start=round(w_start, 2), end=round(w_start + 0.05, 2), score=0.0, confidence=0.0
                        )

                # Commit matched word(s)
                for offset in range(best_merge):
                    cur_w_idx = best_target_w + offset
                    if cur_w_idx < word_count:
                        rw = ref_words[cur_w_idx]
                        committed_words[cur_w_idx] = QuranWord(
                            word=rw.text,
                            location=rw.location,
                            start=round(w_start, 2),
                            end=round(w_end, 2),
                            score=round(word_score, 2),
                            confidence=round(avg_conf, 4),
                            phonemes=[p.to_dict() for p in matched_tokens],
                        )

                asr_char_anchor += best_result.tokens_consumed
                word_cursor = max(word_cursor, best_target_w + best_merge)
            else:
                asr_char_anchor += 1  # Skip 1 noise character

        # Fill remaining words as missing
        for i in range(word_count):
            if i not in committed_words:
                has_missing = True
                rw = ref_words[i]
                committed_words[i] = QuranWord(
                    word=rw.text, location=rw.location, start=round(default_start_time, 2), end=round(default_start_time + 0.05, 2), score=0.0, confidence=0.0
                )

        final_words = [committed_words[i] for i in range(word_count)]
        return final_words, repeated_ranges, repeated_text, has_missing


# ─── 6. Multi-Surah Finder & Verse Partitioning ───

class MultiSurahFinder:
    """Detects single or multiple Surah blocks in continuous recitation audio."""

    def __init__(self):
        self._phonetic_search = PhoneticSearch()
        self._verses: Dict[str, Any] = {}
        self._surah_metadata: Dict[int, Dict[str, str]] = {}
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

    def detect_single_surah(self, aligned_phonemes: List[PhonemeToken], sample_length: int = 35) -> SurahDetectionResult:
        if not aligned_phonemes:
            return SurahDetectionResult(surah=1, start_ayah=1, end_ayah=1)

        query_text = "".join(p.phoneme for p in aligned_phonemes[:sample_length])
        results = self._phonetic_search.search(query_text, error_ratio=0.25)

        # Skip prologue offsets if Basmalah detected
        offsets = (0, 10, 16, 20, 24, 28, 32, 36)
        for off in offsets:
            if off < len(aligned_phonemes):
                q = "".join(p.phoneme for p in aligned_phonemes[off:off + sample_length])
                if len(q) >= 6:
                    res = self._phonetic_search.search(q, error_ratio=0.25)
                    if res and (off == 0 or res[0].surah_number != 1):
                        best = res[0]
                        return SurahDetectionResult(
                            surah=best.surah_number,
                            start_ayah=best.ayah_number,
                            end_ayah=best.ayah_number,
                            start_time=aligned_phonemes[0].start,
                            end_time=aligned_phonemes[-1].end,
                            confidence=max(0.5, 1.0 - (best.distance / max(1, len(q)))),
                        )

        return SurahDetectionResult(surah=1, start_ayah=1, end_ayah=1)

    def detect_multiple_surahs(self, aligned_phonemes: List[PhonemeToken]) -> List[SurahAudioBlock]:
        if not aligned_phonemes:
            return []
        single = self.detect_single_surah(aligned_phonemes)
        return [
            SurahAudioBlock(
                block_index=1,
                surah_number=single.surah,
                surah_name_ar="",
                surah_name_en="",
                start_ayah=single.start_ayah,
                end_ayah=single.end_ayah,
                start_time_seconds=aligned_phonemes[0].start,
                end_time_seconds=aligned_phonemes[-1].end,
                start_phoneme_idx=0,
                end_phoneme_idx=len(aligned_phonemes),
                phonemes=aligned_phonemes,
            )
        ]


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

        surah = target_surah
        s_ayah = start_ayah or 1
        if surah is None:
            detected = self.surah_finder.detect_single_surah(aligned_phonemes)
            surah = detected.surah
            s_ayah = detected.start_ayah

        # 1. Expand continuous characters
        asr_buffer = []
        char_start_ts = []
        char_end_ts = []
        char_to_tokens = []
        for tok in aligned_phonemes:
            for ch in tok.phoneme:
                asr_buffer.append(ch)
                char_start_ts.append(tok.start)
                char_end_ts.append(tok.end)
                char_to_tokens.append(tok)
        full_asr_text = "".join(asr_buffer)

        # 2. Build Surah RefWords
        surah_words: List[RefWord] = []
        ayah_texts: Dict[int, str] = {}
        a = s_ayah
        while f"{surah}:{a}" in self._verses:
            v_data = self._verses[f"{surah}:{a}"]
            a_text = v_data.get("aya_text", "")
            ph_words = v_data.get("aya_phonemes_list", [])
            text_words = [w for w in re.split(r"\s+", a_text.strip()) if w]
            ayah_texts[a] = a_text

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

        # 3. Prologue check (Isti'adhah / Basmalah)
        prologue: Optional[Dict[str, Any]] = None
        current_char_idx = 0
        if surah != 1 and surah != 9 and len(full_asr_text) >= 15:
            # Check Isti'adhah + Basmalah
            check_slice = full_asr_text[:120]
            res = self._dtw_matcher.match_word(
                asr_text=check_slice,
                asr_timestamps=char_start_ts[:120],
                full_phonemes=f"{self._istiadhah_ph}{self._basmalah_ph}",
                ref_start=0,
                ref_end=len(f"{self._istiadhah_ph}{self._basmalah_ph}"),
                config=self.config,
            )
            if res and res.tokens_consumed > 0 and res.path_cost <= 0.25:
                prologue = {
                    "type": "istiadhah+basmalah",
                    "text": "أَعُوذُ بِٱللَّهِ مِنَ ٱلشَّيْطَـٰنِ ٱلرَّجِيمِ بِسْمِ ٱللَّهِ ٱلرَّحْمَـٰنِ ٱلرَّحِيمِ",
                    "start_time": round(char_start_ts[0], 2),
                    "end_time": round(char_end_ts[min(res.tokens_consumed - 1, len(char_end_ts) - 1)], 2),
                    "score": round(1.0 - res.path_cost, 2),
                }
                current_char_idx = res.tokens_consumed

        # 4. Sequence words
        default_start = char_start_ts[current_char_idx] if current_char_idx < len(char_start_ts) else 0.0
        sequenced_words, rep_ranges, rep_texts, has_missing = self._sequencer.sequence_words(
            asr_text=full_asr_text[current_char_idx:],
            asr_start_timestamps=char_start_ts[current_char_idx:],
            asr_end_timestamps=char_end_ts[current_char_idx:],
            char_to_tokens=char_to_tokens[current_char_idx:],
            ref_words=surah_words,
            config=self.config,
            default_start_time=default_start,
        )

        # 5. Partition by Ayah into QuranSegments
        segments: List[QuranSegment] = []
        words_by_ayah: Dict[int, List[QuranWord]] = {}
        for w in sequenced_words:
            if w.location:
                ay = int(w.location.split(":")[1])
                words_by_ayah.setdefault(ay, []).append(w)

        seg_num = 1
        for ay_num, a_words in words_by_ayah.items():
            if not a_words:
                continue
            a_start = a_words[0].start if a_words[0].start is not None else default_start
            a_end = a_words[-1].end if a_words[-1].end is not None else (a_start + 0.5)
            a_text = ayah_texts.get(ay_num, "")
            green_count = sum(1 for w in a_words if (w.score or 0.0) > 0.0)
            score = green_count / max(1, len(a_words))

            seg = QuranSegment(
                segment_number=seg_num,
                surah_number=surah,
                start_time=round(a_start, 2),
                end_time=round(a_end, 2),
                matched_text=a_text,
                matched_ref=f"{surah}:{ay_num}:1-{surah}:{ay_num}:{len(a_words)}",
                match_score=round(score, 3),
                words=a_words,
                prologue=prologue if ay_num == s_ayah else None,
                has_missing_words=any((w.score or 0.0) == 0.0 for w in a_words),
            )
            segments.append(seg)
            seg_num += 1

        return segments
