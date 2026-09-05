"""Per-Word Semi-Global DTW Matcher (Direct Character-Level Alignment).

Mirrors Dart lib/phase3_matcher/dictation_matcher.dart exactly.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional, List
import numpy as np

from src.phase3_matcher.matcher_config import MatcherConfig
from src.phase3_matcher.phonetic_cost_engine import PhoneticCostEngine


@dataclass
class PhonemeGroupAlignment:
    """Alignment opcode between a reference phoneme index and an ASR phoneme index."""
    op_type: str  # 'match', 'replace', 'delete', 'insert'
    ref_idx: int
    pred_idx: int


@dataclass
class WordMatchResult:
    """Result of aligning ASR characters against a single word's reference."""
    path_cost: float
    tokens_consumed: int
    clean_asr: str
    timestamps: List[float]
    trace: List[PhonemeGroupAlignment]
    start_token_idx: int = 0
    is_partial: bool = False


class QuranDictationMatcher:
    """Single-Pass Semi-Global DTW Matcher operating directly on character strings."""

    def __init__(self):
        self._dp: np.ndarray = np.zeros(2048, dtype=np.float64)
        self._bt: np.ndarray = np.zeros(2048, dtype=np.uint8)

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
        """Aligns asr_text against reference slice [ref_start, ref_end) in full_phonemes.

        Returns the best match or None if no alignment meets the threshold.
        """
        m = len(asr_text)
        n = ref_end - ref_start
        if m == 0 or n <= 0:
            return None

        # 1. BUFFER MANAGEMENT
        stride = n + 1
        cells = (m + 1) * stride
        if len(self._dp) < cells:
            sz = max(cells, len(self._dp) * 2)
            self._dp = np.zeros(sz, dtype=np.float64)
            self._bt = np.zeros(sz, dtype=np.uint8)

        dp = self._dp
        bt = self._bt

        # 2. MATRIX INITIALIZATION
        # Row 0: reference deletions (word phonemes with no ASR)
        dp[0] = 0.0
        bt[0] = 0
        for j in range(1, n + 1):
            del_cost = PhoneticCostEngine.get_deletion_cost(
                full_phonemes,
                ref_start + j - 1,
                config.standard_deletion_cost,
                config.acoustic_confusion_cost,
            )
            dp[j] = dp[j - 1] + del_cost
            bt[j] = 1  # delete

        # Column 0: FREE START (skip leading ASR noise characters at zero cost)
        for i in range(1, m + 1):
            dp[i * stride] = 0.0
            bt[i * stride] = 2  # free insert

        # 3. CORE DP FILL (DYNAMIC TIME WARPING WITH PHONETIC COST MATRIX)
        for i in range(1, m + 1):
            a_code = ord(asr_text[i - 1])
            row = i * stride
            prev = (i - 1) * stride
            ins_cost = PhoneticCostEngine.get_insertion_cost(
                asr_text,
                i - 1,
                config.standard_insertion_cost,
                config.acoustic_confusion_cost,
            )

            for j in range(1, n + 1):
                r_ref = ref_start + j - 1
                r_code = ord(full_phonemes[r_ref])

                sub_cost = PhoneticCostEngine.get_substitution_cost(
                    a_code,
                    r_code,
                    config.acoustic_confusion_cost,
                )
                del_cost = PhoneticCostEngine.get_deletion_cost(
                    full_phonemes,
                    r_ref,
                    config.standard_deletion_cost,
                    config.acoustic_confusion_cost,
                )

                sub = dp[prev + j - 1] + sub_cost
                del_val = dp[row + j - 1] + del_cost
                ins = dp[prev + j] + ins_cost

                # Break ties in favor of deletions to force matching early and deleting late
                if sub < del_val and sub <= ins:
                    dp[row + j] = sub
                    bt[row + j] = 0  # match/sub
                elif del_val <= ins:
                    dp[row + j] = del_val
                    bt[row + j] = 1  # delete
                else:
                    dp[row + j] = ins
                    bt[row + j] = 2  # insert

        # 4. ENDPOINT DETECTION (DYNAMIC THRESHOLD)
        best_i = -1
        best_cost = float("inf")

        eff_n = PhoneticCostEngine.get_effective_length(full_phonemes, ref_start, ref_end)

        threshold = config.default_max_path_cost
        if eff_n <= 3:
            threshold = min(threshold, config.short_word_path_cost)
        elif eff_n <= 7:
            threshold = min(threshold, config.medium_word_path_cost)
        else:
            threshold = min(threshold, config.default_max_path_cost)

        for i in range(1, m + 1):
            norm = dp[i * stride + n] / eff_n
            if norm <= threshold:
                if norm < best_cost:
                    best_i = i
                    best_cost = norm

        # 5. PARTIAL MATCHING LOGIC
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

                if PhoneticCostEngine.is_tashkeel(asr_code) and PhoneticCostEngine.is_tashkeel(ref_code):
                    is_partial = False
                elif PhoneticCostEngine.get_substitution_cost(asr_code, ref_code) > 0.0:
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

        # 6. TRACEBACK & RESULTS
        ci, cj = best_i, n
        raw_trace: List[PhonemeGroupAlignment] = []
        ts: List[float] = []

        while cj > 0:
            if ci == 0:
                raw_trace.append(
                    PhonemeGroupAlignment(
                        op_type="delete",
                        ref_idx=ref_start + cj - 1,
                        pred_idx=-1,
                    )
                )
                cj -= 1
                continue

            op = bt[ci * stride + cj]
            g_ref = ref_start + cj - 1

            if op == 0:
                asr_code = ord(asr_text[ci - 1])
                ref_code = ord(full_phonemes[g_ref])
                is_match = PhoneticCostEngine.get_substitution_cost(asr_code, ref_code) == 0.0
                raw_trace.append(
                    PhonemeGroupAlignment(
                        op_type="match" if is_match else "replace",
                        ref_idx=g_ref,
                        pred_idx=ci - 1,
                    )
                )
                if ci - 1 < len(asr_timestamps):
                    ts.append(asr_timestamps[ci - 1])
                ci -= 1
                cj -= 1
            elif op == 1:
                raw_trace.append(
                    PhonemeGroupAlignment(
                        op_type="delete",
                        ref_idx=g_ref,
                        pred_idx=-1,
                    )
                )
                cj -= 1
            else:
                raw_trace.append(
                    PhonemeGroupAlignment(
                        op_type="insert",
                        ref_idx=g_ref,
                        pred_idx=ci - 1,
                    )
                )
                ci -= 1

        return WordMatchResult(
            path_cost=best_cost,
            tokens_consumed=best_i,
            start_token_idx=ci,
            clean_asr=asr_text[:best_i],
            timestamps=list(reversed(ts)),
            trace=list(reversed(raw_trace)),
        )
