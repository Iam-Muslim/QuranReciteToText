"""Phase 3 Matcher: 3D Wraparound Dynamic Programming Quran Recitation Aligner.

Orchestrates forward Quran recitation matching, multi-pass repetition tracking,
and canonical Ayah segment construction. All tunable parameters are read from config.py.
"""

from __future__ import annotations

import os
import json
import logging
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any, Tuple
from collections import defaultdict
import numpy as np

import config
from config import (
    DEFAULT_QURAN_PHONEMES_PATH,
    DEFAULT_REF_NORM_PH_PATH,
    DEFAULT_PH_INDEX_PATH,
)
from src.models import (
    PhonemeToken,
    QuranWord,
    QuranSegment,
    AyahSubSegment,
)
from src.matching.phonetics import PhoneticCostEngine, get_sub_cost_table
from src.matching.kernels import _dp_wraparound_fast, warmup_matcher_jit
from src.matching.reference import (
    ContinuousQuranWord,
    SurahReferenceData,
    compute_reading_sequence,
)
from src.matching.detector import (
    MultiSurahFinder,
    SurahDetectionResult,
    find_near_matches,
    warmup_detector_jit,
)

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# 1. WRAPAROUND CONFIGURATION (DEFAULTS CONSUMED FROM CONFIG.PY)
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class WraparoundConfig:
    """Hyperparameter configuration for 3D Wraparound DP alignment."""
    # Edit Costs
    cost_substitution: float = getattr(config, "COST_SUBSTITUTION", 1.00)
    cost_deletion: float = getattr(config, "COST_DELETION", 1.00)
    cost_insertion: float = getattr(config, "COST_INSERTION", 0.75)
    acoustic_confusion_cost: float = getattr(config, "ACOUSTIC_CONFUSION_COST", 0.25)

    # Wraparound & Repetition Parameters
    max_wraps: int = getattr(config, "MAX_WRAPS", 3)
    wrap_penalty: float = getattr(config, "WRAP_PENALTY", 0.80)
    wrap_span_weight: float = getattr(config, "WRAP_SPAN_WEIGHT", 0.05)
    start_prior_weight: float = getattr(config, "START_PRIOR_WEIGHT", 0.02)

    # Window & Search Slicing
    lookback_words: int = getattr(config, "LOOKBACK_WORDS", 4)
    lookahead_words: int = getattr(config, "LOOKAHEAD_WORDS", 25)
    max_edit_distance: float = getattr(config, "MAX_EDIT_DISTANCE", 0.35)


# Aliases for backward compatibility
TrackerConfig = WraparoundConfig
MatcherConfig = WraparoundConfig


# ═══════════════════════════════════════════════════════════════════════════════
# 2. ALIGNMENT RESULT
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class AlignmentResult:
    """Result of aligning a speech segment against the Quran reference."""
    start_word_idx: int
    end_word_idx: int
    edit_cost: float
    confidence: float
    j_start: int
    best_j: int
    consumed_chars: int = 0
    word_instances: List[Tuple[int, int, int]] = field(default_factory=list)
    n_wraps: int = 0
    max_j_reached: int = 0
    wrap_word_ranges: list = field(default_factory=list)
    reading_sequence: list = field(default_factory=list)


# ═══════════════════════════════════════════════════════════════════════════════
# 3. 3D WRAPAROUND WINDOW MATCHER
# ═══════════════════════════════════════════════════════════════════════════════

class WraparoundDpMatcher:
    """Matches continuous ASR speech phonemes against the Quran using 3D Wraparound DP."""

    def __init__(self, config: Optional[WraparoundConfig] = None):
        self.config = config or WraparoundConfig()

    def align_window(
        self,
        asr_phonemes_str: str,
        ref_data: SurahReferenceData,
        pointer: int,
        config: Optional[WraparoundConfig] = None,
    ) -> Optional[AlignmentResult]:
        cfg = config or self.config
        m = len(asr_phonemes_str)
        if m == 0 or ref_data.num_words == 0:
            return None

        # 1. Estimate word span and slice reference window around pointer
        est_words = max(1, int(round(m / ref_data.avg_phones_per_word)))
        win_start = max(0, pointer - cfg.lookback_words)
        win_end = min(ref_data.num_words, pointer + est_words + cfg.lookahead_words)

        if win_start >= ref_data.num_words:
            return None

        p_start = ref_data.word_boundaries[win_start]
        p_end = ref_data.word_boundaries[win_end]

        sub_r_str = ref_data.full_phonemes[p_start:p_end]
        n = len(sub_r_str)
        if n == 0:
            return None

        sub_phone_to_word = ref_data.flat_phone_to_word[p_start:p_end]

        p_codes = np.array([ord(c) for c in asr_phonemes_str], dtype=np.int32)
        r_codes = np.array([ord(c) for c in sub_r_str], dtype=np.int32)

        # 2. Build word boundary masks
        word_starts_mask = np.zeros(n + 1, dtype=np.bool_)
        word_ends_mask = np.zeros(n + 1, dtype=np.bool_)

        for j in range(n + 1):
            if j == 0 or (j < n and sub_phone_to_word[j] != sub_phone_to_word[j - 1]):
                word_starts_mask[j] = True
            if j == n or (j > 0 and j < n and sub_phone_to_word[j] != sub_phone_to_word[j - 1]):
                word_ends_mask[j] = True

        ins_costs = np.array(
            [PhoneticCostEngine.get_insertion_cost(asr_phonemes_str, i, cfg.cost_insertion, cfg.acoustic_confusion_cost) for i in range(m)],
            dtype=np.float64,
        )
        del_costs = np.array(
            [PhoneticCostEngine.get_deletion_cost(sub_r_str, j, cfg.cost_deletion, cfg.acoustic_confusion_cost) for j in range(n)],
            dtype=np.float64,
        )

        # 3. Execute 3D Wraparound DP with exact Viterbi backtracking
        (
            best_i,
            best_k,
            best_j,
            best_cost,
            norm_dist,
            j_start,
            max_j_reached,
            char_word_map,
            char_pass_map,
        ) = _dp_wraparound_fast(
            p_codes=p_codes,
            r_codes=r_codes,
            r_phone_to_word=sub_phone_to_word,
            word_starts_mask=word_starts_mask,
            word_ends_mask=word_ends_mask,
            del_costs=del_costs,
            ins_costs=ins_costs,
            sub_table=get_sub_cost_table(cfg.acoustic_confusion_cost),
            max_wraps=cfg.max_wraps,
            cost_sub=cfg.cost_substitution,
            cost_del=cfg.cost_deletion,
            cost_ins=cfg.cost_insertion,
            wrap_penalty=cfg.wrap_penalty,
            wrap_span_weight=cfg.wrap_span_weight,
            confusion_cost=cfg.acoustic_confusion_cost,
            prior_weight=cfg.start_prior_weight,
            expected_word=pointer,
        )

        if best_j < 0 or norm_dist > cfg.max_edit_distance:
            return None

        # Map to global word indices
        start_word_idx = sub_phone_to_word[j_start]
        end_word_idx = sub_phone_to_word[best_j - 1]

        if best_k > 0 and max_j_reached > best_j:
            end_word_idx = sub_phone_to_word[max_j_reached - 1]

        confidence = max(0.0, min(1.0, 1.0 - norm_dist))

        # Extract strictly partitioned word instances from Viterbi character maps
        word_instances: List[Tuple[int, int, int]] = []
        curr_w = -1
        curr_k = -1
        span_s = -1

        for ci in range(int(best_i)):
            w = int(char_word_map[ci])
            k = int(char_pass_map[ci])
            if w != curr_w or k != curr_k:
                if curr_w >= 0 and span_s >= 0:
                    word_instances.append((curr_w, span_s, ci))
                curr_w = w
                curr_k = k
                span_s = ci if w >= 0 else -1

        if curr_w >= 0 and span_s >= 0:
            word_instances.append((curr_w, span_s, int(best_i)))

        # Wrap word ranges
        wrap_word_ranges = []
        if best_k > 0:
            jump_to = ref_data.words[start_word_idx].location
            jump_from = ref_data.words[end_word_idx].location
            repeat_end = ref_data.words[sub_phone_to_word[best_j - 1]].location
            wrap_word_ranges.append((jump_to, jump_from, repeat_end))

        ref_from = ref_data.words[start_word_idx].location
        ref_to = ref_data.words[end_word_idx].location
        reading_seq = compute_reading_sequence(ref_from, ref_to, wrap_word_ranges)

        return AlignmentResult(
            start_word_idx=start_word_idx,
            end_word_idx=end_word_idx,
            edit_cost=best_cost,
            confidence=confidence,
            j_start=j_start,
            best_j=best_j,
            consumed_chars=int(best_i),
            word_instances=word_instances,
            n_wraps=best_k,
            max_j_reached=max_j_reached,
            wrap_word_ranges=wrap_word_ranges,
            reading_sequence=reading_seq,
        )


# ═══════════════════════════════════════════════════════════════════════════════
# 4. SEQUENTIAL PASS & SEGMENT BUILDER
# ═══════════════════════════════════════════════════════════════════════════════

def _align_and_package_ayahs(
    aligned_tokens: List[PhonemeToken],
    ref_data: SurahReferenceData,
    start_word_index: int = 0,
    target_end_ayah: Optional[int] = None,
    config: Optional[WraparoundConfig] = None,
) -> List[QuranSegment]:
    """Aligns speech tokens against Surah reference using Global Graph DP."""
    if not aligned_tokens or ref_data.num_words == 0:
        return []

    cfg = config or WraparoundConfig()

    total_tokens = len(aligned_tokens)
    asr_str = "".join(t.phoneme for t in aligned_tokens)

    # Build exact char-to-token index lookup table
    char_to_tok: List[int] = []
    for tok_idx, t in enumerate(aligned_tokens):
        for _ in t.phoneme:
            char_to_tok.append(tok_idx)
    char_to_tok.append(total_tokens)

    word_count = ref_data.num_words
    win_start = max(0, start_word_index - 50)  # Safe 50 words lookback for repetitions
    
    if target_end_ayah is not None and target_end_ayah in ref_data.ayah_to_words:
        # Generous safe buffer of 15 Ayahs beyond the detected end
        max_ay = min(max(ref_data.ayah_to_words.keys()), target_end_ayah + 15)
        win_end = min(word_count, ref_data.ayah_to_words[max_ay][-1].global_index + 1)
    else:
        # Fallback word estimation: average phonemes per word is ~8, use safe 4.0 ratio + 150 buffer
        est_words = int(len(asr_str) / 4.0) + 150
        win_end = min(word_count, start_word_index + est_words)
    
    p_start = ref_data.word_boundaries[win_start]
    p_end = ref_data.word_boundaries[win_end] if win_end < word_count else len(ref_data.full_phonemes)
    
    sub_r_str = ref_data.full_phonemes[p_start:p_end]
    n = len(sub_r_str)
    if n == 0:
        return []

    sub_phone_to_word = ref_data.flat_phone_to_word[p_start:p_end]

    p_codes = np.array([ord(c) for c in asr_str], dtype=np.int32)
    r_codes = np.array([ord(c) for c in sub_r_str], dtype=np.int32)

    word_starts_mask = np.zeros(n + 1, dtype=np.bool_)
    word_ends_mask = np.zeros(n + 1, dtype=np.bool_)

    for j in range(n + 1):
        if j == 0 or (j < n and sub_phone_to_word[j] != sub_phone_to_word[j - 1]):
            word_starts_mask[j] = True
        if j == n or (j > 0 and j < n and sub_phone_to_word[j] != sub_phone_to_word[j - 1]):
            word_ends_mask[j] = True

    m = len(asr_str)
    ins_costs = np.array(
        [PhoneticCostEngine.get_insertion_cost(asr_str, i, cfg.cost_insertion, cfg.acoustic_confusion_cost) for i in range(m)],
        dtype=np.float64,
    )
    del_costs = np.array(
        [PhoneticCostEngine.get_deletion_cost(sub_r_str, j, cfg.cost_deletion, cfg.acoustic_confusion_cost) for j in range(n)],
        dtype=np.float64,
    )

    from src.matching.kernels import _global_viterbi_fast
    sub_table = get_sub_cost_table(cfg.acoustic_confusion_cost)
    
    _, _, _, char_word_map, char_j_map = _global_viterbi_fast(
        p_codes=p_codes,
        r_codes=r_codes,
        r_phone_to_word=sub_phone_to_word,
        word_starts_mask=word_starts_mask,
        word_ends_mask=word_ends_mask,
        del_costs=del_costs,
        ins_costs=ins_costs,
        sub_table=sub_table,
        cost_sub=cfg.cost_substitution,
        cost_del=cfg.cost_deletion,
        cost_ins=cfg.cost_insertion,
        wrap_penalty=cfg.wrap_penalty,
        wrap_span_weight=cfg.wrap_span_weight,
        confusion_cost=cfg.acoustic_confusion_cost,
    )


    matched_word_tokens: Dict[int, List[List[PhonemeToken]]] = defaultdict(list)
    matched_word_scores: Dict[int, float] = {}

    word_passes = []
    curr_w = -1
    span_s = -1

    for i in range(m):
        w = int(char_word_map[i])
        
        is_jump = False
        if i > 0 and char_j_map[i] >= 0 and char_j_map[i-1] >= 0:
            if char_j_map[i] < char_j_map[i-1]:
                is_jump = True
                
        if w != curr_w or is_jump:
            if curr_w >= 0 and span_s >= 0:
                word_passes.append((curr_w, span_s, i))
            curr_w = w
            span_s = i if w >= 0 else -1
            
    if curr_w >= 0 and span_s >= 0:
        word_passes.append((curr_w, span_s, m))

    for w, s_char, e_char in word_passes:
        if e_char > s_char:
            t_s = char_to_tok[s_char]
            t_e = char_to_tok[e_char]
            if t_e > t_s:
                w_toks = aligned_tokens[t_s:t_e]
                matched_word_tokens[w].append(w_toks)
                w_conf = sum(t.confidence for t in w_toks) / len(w_toks)
                matched_word_scores[w] = round(min(1.0, w_conf), 2)

    # Build canonical Ayah segments
    min_w = min(matched_word_tokens.keys()) if matched_word_tokens else 0
    max_w = max(matched_word_tokens.keys()) if matched_word_tokens else (word_count - 1)

    start_ay = ref_data.words[min_w].ayah if min_w < word_count else 1
    end_ay = ref_data.words[max_w].ayah if max_w < word_count else ref_data.words[-1].ayah

    segments: List[QuranSegment] = []
    seg_number = 1

    for ay in range(start_ay, end_ay + 1):
        ay_words = ref_data.ayah_to_words.get(ay, [])
        if not ay_words:
            continue

        qwords: List[QuranWord] = []
        has_missing = False
        has_repeated = False

        for rw in ay_words:
            w_idx = rw.global_index
            if w_idx in matched_word_tokens and matched_word_tokens[w_idx]:
                passes = matched_word_tokens[w_idx]
                if len(passes) > 1:
                    has_repeated = True

                # Use the canonical final recitation pass
                chosen_pass = passes[-1]
                w_start = chosen_pass[0].start
                w_end = chosen_pass[-1].end
                avg_conf = sum(t.confidence for t in chosen_pass) / len(chosen_pass)
                ph_dicts = [t.to_dict() for t in chosen_pass]
                score = matched_word_scores.get(w_idx, 1.0)

                qwords.append(QuranWord(
                    word=rw.uthmani,
                    location=rw.location,
                    ref=rw.phoneme,
                    start=round(w_start, 2),
                    end=round(w_end, 2),
                    score=round(score, 2),
                    confidence=round(avg_conf, 2),
                    phonemes=ph_dicts,
                ))
            else:
                has_missing = True
                qwords.append(QuranWord(
                    word=rw.uthmani,
                    location=rw.location,
                    ref=rw.phoneme,
                    start=None,
                    end=None,
                    score=0.0,
                    confidence=0.0,
                    phonemes=[],
                ))

        # Build sub_segments and repetition details if the verse was recited multiple times
        sub_segments: Optional[List[AyahSubSegment]] = None
        repeated_ranges: Optional[List[str]] = None
        repeated_text: Optional[List[str]] = None

        if has_repeated:
            all_word_instances = []
            for rw in ay_words:
                w_idx = rw.global_index
                for p in matched_word_tokens.get(w_idx, []):
                    if p:
                        avg_c = sum(t.confidence for t in p) / len(p)
                        score = matched_word_scores.get(w_idx, 1.0)
                        q_inst = QuranWord(
                            word=rw.uthmani,
                            location=rw.location,
                            ref=rw.phoneme,
                            start=round(p[0].start, 2),
                            end=round(p[-1].end, 2),
                            score=round(score, 2),
                            confidence=round(avg_c, 2),
                            phonemes=[t.to_dict() for t in p],
                        )
                        all_word_instances.append((w_idx, rw, q_inst))

            all_word_instances.sort(key=lambda x: x[2].start)

            sub_segs_list: List[AyahSubSegment] = []
            current_pass: List[QuranWord] = []
            prev_w_idx = -1

            for w_idx, rw, q_inst in all_word_instances:
                if current_pass and w_idx <= prev_w_idx:
                    p_st = current_pass[0].start or 0.0
                    p_et = current_pass[-1].end or 0.0
                    p_txt = " ".join(w.word for w in current_pass)
                    p_range = f"{current_pass[0].location}-{current_pass[-1].location}"
                    sub_segs_list.append(AyahSubSegment(
                        sub_segment_number=len(sub_segs_list) + 1,
                        start_time=p_st,
                        end_time=p_et,
                        text=p_txt,
                        words_range=p_range,
                        is_repetition=(len(sub_segs_list) > 0),
                        words=current_pass,
                    ))
                    current_pass = []

                current_pass.append(q_inst)
                prev_w_idx = w_idx

            if current_pass:
                p_st = current_pass[0].start or 0.0
                p_et = current_pass[-1].end or 0.0
                p_txt = " ".join(w.word for w in current_pass)
                p_range = f"{current_pass[0].location}-{current_pass[-1].location}"
                sub_segs_list.append(AyahSubSegment(
                    sub_segment_number=len(sub_segs_list) + 1,
                    start_time=p_st,
                    end_time=p_et,
                    text=p_txt,
                    words_range=p_range,
                    is_repetition=(len(sub_segs_list) > 0),
                    words=current_pass,
                ))

            if sub_segs_list:
                sub_segments = sub_segs_list
                repeated_ranges = [s.words_range for s in sub_segments if s.is_repetition]
                repeated_text = [s.text for s in sub_segments if s.is_repetition]

        # The Ayah segment spans from the start of the first matched pass to the end of the last matched pass
        all_ay_passes = [p for rw in ay_words for p in matched_word_tokens.get(rw.global_index, []) if p]
        if all_ay_passes:
            seg_start = min(p[0].start for p in all_ay_passes)
            seg_end = max(p[-1].end for p in all_ay_passes)
        else:
            seg_start = 0.0
            seg_end = 0.0

        ayah_text = ref_data.ayah_texts.get(ay, " ".join(w.uthmani for w in ay_words))
        matched_ref_str = f"{ref_data.surah}:{ay}:1-{ref_data.surah}:{ay}:{len(ay_words)}"

        segments.append(QuranSegment(
            segment_number=seg_number,
            surah_number=ref_data.surah,
            start_time=round(seg_start, 2),
            end_time=round(seg_end, 2),
            transcribed_text=ayah_text,
            matched_text=ayah_text,
            matched_ref=matched_ref_str,
            match_score=1.0 if not has_missing else 0.85,
            words=qwords,
            has_missing_words=has_missing,
            has_repeated_words=has_repeated,
            repeated_ranges=repeated_ranges,
            repeated_text=repeated_text,
            sub_segments=sub_segments,
        ))
        seg_number += 1

    return segments


# ═══════════════════════════════════════════════════════════════════════════════
# 5. PREAMBLE EXTRACTION & CANONICAL MATCHING FACADE
# ═══════════════════════════════════════════════════════════════════════════════

ISTIAADHA_TEXT = "أَعُوذُ بِٱللَّهِ مِنَ ٱلشَّيْطَـٰنِ ٱلرَّجِيمِ"
ISTIAADHA_PH = "ءَعُۥۥذُبِللَااهِمِنَششَيطَاانِررَجِۦۦۦۦم"


def _slice_preamble_match(
    pattern: str, tokens: List[PhonemeToken], max_error_ratio: float = 0.28
) -> Tuple[Optional[Tuple[float, float, List[PhonemeToken]]], List[PhonemeToken]]:
    """Fast bit-parallel slice for opening preamble using Gene Myers' kernel."""
    if not tokens:
        return None, tokens

    head_len = min(len(tokens), len(pattern) + 30)
    head_str = "".join(t.phoneme for t in tokens[:head_len])
    max_dist = max(3, int(len(pattern) * max_error_ratio))

    matches = find_near_matches(pattern, head_str, max_l_dist=max_dist)
    if matches and matches[0].start <= 6:
        m = matches[0]
        consumed, k = 0, len(tokens)
        start_t, end_t = None, None
        for idx, tok in enumerate(tokens):
            consumed += len(tok.phoneme)
            if start_t is None and consumed > m.start:
                start_t = tok.start
            if consumed >= m.end:
                end_t = tok.end
                k = idx + 1
                break
        matched_toks = tokens[:k]
        st = start_t if start_t is not None else matched_toks[0].start
        et = end_t if end_t is not None else matched_toks[-1].end
        return (st, et, matched_toks), tokens[k:]

    return None, tokens


def _extract_opening_preamble(
    aligned_tokens: List[PhonemeToken],
    surah: int,
    start_ayah: int,
    ref_surah_1: SurahReferenceData,
) -> Tuple[Optional[Dict[str, Any]], List[PhonemeToken]]:
    """Detects and isolates recited Isti'adha and/or pre-verse Basmalah before Ayah 1."""
    if not aligned_tokens:
        return None, aligned_tokens

    curr = aligned_tokens
    preamble: Dict[str, Any] = {}

    # 1. Isti'adha (can precede any recitation)
    ist_res, curr = _slice_preamble_match(ISTIAADHA_PH, curr)
    if ist_res:
        st, et, _ = ist_res
        preamble["istiaatha"] = {
            "text": ISTIAADHA_TEXT,
            "start": round(st, 2),
            "end": round(et, 2),
        }

    # 2. Basmalah (Surahs 2-114 except 9, only before Ayah 1)
    if start_ayah == 1 and surah not in (1, 9):
        basmalah_ph = "".join(w.phoneme for w in ref_surah_1.ayah_to_words[1])
        bas_res, curr = _slice_preamble_match(basmalah_ph, curr)
        if bas_res:
            st, et, bas_toks = bas_res
            bas_segs = _align_and_package_ayahs(
                aligned_tokens=bas_toks,
                ref_data=ref_surah_1,
                start_word_index=0,
                target_end_ayah=1,
            )
            words = [w.to_dict() for w in bas_segs[0].words] if bas_segs else []
            preamble["basmalah"] = {
                "text": ref_surah_1.ayah_texts.get(1, "بِسْمِ ٱللَّهِ ٱلرَّحْمَـٰنِ ٱلرَّحِيمِ"),
                "start": round(st, 2),
                "end": round(et, 2),
                "words": words,
            }

    return (preamble or None), curr


class QuranMatcher:
    """Consolidated Quran Recitation Alignment Engine."""

    def __init__(self, config: Optional[WraparoundConfig] = None):
        self.config = config or WraparoundConfig()
        self.detector = MultiSurahFinder()
        self.window_matcher = WraparoundDpMatcher(self.config)
        self._verses: Dict[str, Any] = {}
        self._surah_refs: Dict[int, SurahReferenceData] = {}
        self._is_initialized = False

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
            self._verses = data.get("verses", data)

        self.detector.initialize(
            quran_json_path=path,
            ref_norm_ph_path=ref_norm_ph_path,
            ph_index_path=ph_index_path,
        )
        self._is_initialized = True

    def _get_surah_ref(self, surah: int) -> SurahReferenceData:
        if surah not in self._surah_refs:
            self._surah_refs[surah] = SurahReferenceData(surah, self._verses)
        return self._surah_refs[surah]

    def match_segments(
        self,
        aligned_phonemes: List[PhonemeToken],
        audio_duration: float = 0.0,
        target_surah: Optional[int] = None,
        start_ayah: Optional[int] = None,
    ) -> List[QuranSegment]:
        if not self._is_initialized:
            self.initialize_from_file()
        if not aligned_phonemes or not self._verses:
            return []

        # 1. Single Surah & Start Ayah Detection
        detected_surah = target_surah
        detected_start_ayah = start_ayah
        detected_end_ayah = None

        if detected_surah is None:
            det_res = self.detector.detect_single_surah(aligned_phonemes)
            if det_res is not None:
                detected_surah = det_res.surah
                detected_start_ayah = det_res.start_ayah
                detected_end_ayah = det_res.end_ayah
                logger.info(
                    "Detected Surah %d starting at Ayah %d (confidence=%.2f)",
                    detected_surah,
                    detected_start_ayah,
                    det_res.confidence,
                )
            else:
                detected_surah = 1
                detected_start_ayah = 1

        # 2. Opening Preamble Extraction (Isti'adha & pre-verse Basmalah)
        prologue, remaining_tokens = _extract_opening_preamble(
            aligned_phonemes, detected_surah, detected_start_ayah or 1, self._get_surah_ref(1)
        )

        ref_data = self._get_surah_ref(detected_surah)
        start_word_idx = ref_data.ayah_start_word_index.get(detected_start_ayah or 1, 0)

        # 3. 3D Wraparound Alignment & Segment Construction
        segments = _align_and_package_ayahs(
            aligned_tokens=remaining_tokens,
            ref_data=ref_data,
            start_word_index=start_word_idx,
            target_end_ayah=detected_end_ayah,
            config=self.config,
        )

        if prologue and segments:
            segments[0].prologue = prologue
            p_starts = [
                v["start"] for v in prologue.values()
                if isinstance(v, dict) and "start" in v
            ]
            if p_starts:
                segments[0].start_time = min(segments[0].start_time, min(p_starts))

        return segments



QuranWordMatcher = QuranMatcher
