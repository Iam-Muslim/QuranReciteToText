"""Phase 3 Matcher: 3D JumpDTW Dynamic Programming Quran Recitation Aligner.

Orchestrates forward recitation matching, repetition tracking,
and canonical Ayah segment construction from  Mushaf reference.
"""

from __future__ import annotations

import os
import bisect
import logging
from dataclasses import dataclass
from typing import Optional, List, Dict, Any, Tuple
from collections import defaultdict
import numpy as np

import config
from config import (
    DEFAULT_EXPECTED_ZFX_PATH,
    DEFAULT_TOKENS_PATH,
    PAUSE_CUT_MARGIN_S,
    PAUSE_INTERVAL_OVERLAP_S,
)
from src.models import (
    PhonemeToken,
    PauseInterval,
    QuranWord,
    QuranSegment,
    AyahSubSegment,
)
from src.matching.phonetics import (
    get_sub_cost_table,
    _compute_insertion_costs_fast,
    _compute_deletion_costs_fast,
    ISTIAADHA_PH,
    TAKBEER_PH,
    TASMEE_PH,
    PRAYER_EXCLUDED_VERSES,
)
from src.matching.kernels import _global_viterbi_fast
from src.matching.reference import RefWord, SurahReferenceData, ZfxReader
from src.matching.detector import SurahDetector, SurahDetectionResult, find_near_matches

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# 1. MATCHER CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True, slots=True)
class MatcherConfig:
    """Hyperparameter configuration for recitation alignment."""
    cost_substitution: float = getattr(config, "COST_SUBSTITUTION", 1.00)
    cost_deletion: float = getattr(config, "COST_DELETION", 1.00)
    cost_insertion: float = getattr(config, "COST_INSERTION", 0.75)
    acoustic_confusion_cost: float = getattr(config, "ACOUSTIC_CONFUSION_COST", 0.25)
    wrap_penalty: float = getattr(config, "WRAP_PENALTY", 0.80)
    wrap_span_weight: float = getattr(config, "WRAP_SPAN_WEIGHT", 0.05)
    min_word_coverage: float = getattr(config, "MIN_WORD_COVERAGE", 0.35)


# ═══════════════════════════════════════════════════════════════════════════════
# 2. WORD & SEGMENT BUILDERS
# ═══════════════════════════════════════════════════════════════════════════════

def _build_qword(rw: RefWord, tokens: List[PhonemeToken], score: float) -> QuranWord:
    """Creates a unified QuranWord instance with phoneme breakdown and acoustic bounds."""
    w_start = round(tokens[0].start, 3)
    w_end = round(tokens[-1].end, 3)
    return QuranWord(
        word=rw.uthmani,
        location=rw.location,
        ref=rw.phoneme,
        start=w_start,
        end=w_end,
        score=round(score, 2),
        phonemes=[t.to_dict() for t in tokens],
        raw_start=w_start,
        raw_end=w_end,
    )



def _align_and_package_ayahs(
    tokens: List[PhonemeToken],
    ref_data: SurahReferenceData,
    start_word_index: int = 0,
    target_end_ayah: Optional[int] = None,
    matcher_cfg: Optional[MatcherConfig] = None,
    pause_timestamps: Optional[List[float]] = None,
    pause_intervals: Optional[List[PauseInterval]] = None,
) -> List[QuranSegment]:
    """Aligns speech tokens against Surah reference using JumpDTW Dynamic Programming."""
    if not tokens or ref_data.num_words == 0:
        return []

    cfg = matcher_cfg or MatcherConfig()
    total_tokens = len(tokens)
    asr_str = "".join(t.phoneme for t in tokens)

    # Fast char-to-token index lookup
    char_to_tok: List[int] = []
    for tok_idx, t in enumerate(tokens):
        char_to_tok.extend([tok_idx] * len(t.phoneme))
    char_to_tok.append(total_tokens)

    word_count = ref_data.num_words
    win_start = max(0, start_word_index - 2)

    # Robust window bounds: never truncate below acoustic length estimate
    est_words = int(len(asr_str) / 4.0) + 150
    min_required_end = start_word_index + est_words

    if target_end_ayah is not None and target_end_ayah in ref_data.ayah_to_words:
        target_end_word = ref_data.ayah_to_words[target_end_ayah][-1].global_index + 1
        win_end = min(word_count, max(min_required_end, target_end_word + 30))
    else:
        win_end = min(word_count, min_required_end)

    p_start = ref_data.word_boundaries[win_start]
    p_end = ref_data.word_boundaries[win_end] if win_end < word_count else len(ref_data.full_phonemes)

    sub_r_str = ref_data.full_phonemes[p_start:p_end]
    n = len(sub_r_str)
    if n == 0:
        return []

    sub_phone_to_word = ref_data.flat_phone_to_word[p_start:p_end]
    p_codes = np.array([ord(c) for c in asr_str], dtype=np.int32)
    r_codes = np.array([ord(c) for c in sub_r_str], dtype=np.int32)

    diff = sub_phone_to_word[1:] != sub_phone_to_word[:-1]
    word_starts_mask = np.empty(n + 1, dtype=np.bool_)
    word_ends_mask = np.empty(n + 1, dtype=np.bool_)
    word_starts_mask[0] = True
    word_starts_mask[1:n] = diff
    word_starts_mask[n] = False
    word_ends_mask[0] = False
    word_ends_mask[1:n] = diff
    word_ends_mask[n] = True

    # Fast JIT-vectorized edit costs
    ins_costs = _compute_insertion_costs_fast(p_codes, cfg.cost_insertion, cfg.acoustic_confusion_cost)
    del_costs = _compute_deletion_costs_fast(r_codes, cfg.cost_deletion, cfg.acoustic_confusion_cost)
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
        wrap_penalty=cfg.wrap_penalty,
        wrap_span_weight=cfg.wrap_span_weight,
    )

    matched_word_tokens: Dict[int, List[List[PhonemeToken]]] = defaultdict(list)
    matched_word_scores: Dict[int, float] = {}

    word_passes: List[Tuple[int, int, int]] = []
    curr_w = -1
    span_s = -1
    m = len(asr_str)

    for i in range(m):
        w = int(char_word_map[i])
        is_jump = (i > 0 and char_j_map[i] >= 0 and char_j_map[i - 1] >= 0 and char_j_map[i] < char_j_map[i - 1])
        if w != curr_w or is_jump:
            if curr_w >= 0 and span_s >= 0:
                word_passes.append((curr_w, span_s, i))
            curr_w = w
            span_s = i if w >= 0 else -1

    if curr_w >= 0 and span_s >= 0:
        word_passes.append((curr_w, span_s, m))

    min_cov = getattr(cfg, "min_word_coverage", getattr(config, "MIN_WORD_COVERAGE", 0.35))
    intervals = pause_intervals or []
    interval_starts = [p.start_sec for p in intervals] if intervals else []
    pause_pts = sorted(pause_timestamps) if pause_timestamps else []
    min_pause_s = getattr(config, "VAD_SAKT_MIN_PAUSE_S", 0.16)

    def _is_pause_between(t1: PhonemeToken, t2: PhonemeToken) -> bool:
        if (t2.start - t1.end) >= min_pause_s:
            return True
        if intervals:
            idx = bisect.bisect_right(interval_starts, t1.end - 0.020)
            if idx < len(intervals):
                p = intervals[idx]
                if p.start_sec < t2.start + 0.020 and p.end_sec > t1.end - 0.020:
                    if p.duration_sec >= min_pause_s:
                        return True
        return False

    for w, s_char, e_char in word_passes:
        if e_char > s_char:
            t_s = char_to_tok[s_char]
            t_e = char_to_tok[e_char]
            if t_e > t_s and 0 <= w < word_count:
                rw = ref_data.words[w]
                ref_len = len(rw.phoneme)

                # Reference boundary for word w within the current sub_r_str window
                w_j_start = ref_data.word_boundaries[w] - p_start
                w_j_end = ref_data.word_boundaries[w + 1] - p_start

                # Acoustic Pause Barrier: Words do not straddle breath pauses (>= min_pause_s).
                # If a physical pause occurs inside tokens[t_s:t_e], partition into continuous sub-slices.
                sub_slices: List[Tuple[int, int]] = []
                c_s = t_s
                for k in range(t_s, t_e - 1):
                    if _is_pause_between(tokens[k], tokens[k + 1]):
                        sub_slices.append((c_s, k + 1))
                        c_s = k + 1
                sub_slices.append((c_s, t_e))

                # Determine which continuous sub-slice has maximum reference coverage for word w
                best_slice = sub_slices[0]
                best_cov = -1
                best_idx = 0
                for s_idx, (sl_s, sl_e) in enumerate(sub_slices):
                    sl_covered = set()
                    for i in range(s_char, e_char):
                        tok_idx = char_to_tok[i]
                        if sl_s <= tok_idx < sl_e:
                            j = int(char_j_map[i])
                            if w_j_start <= j < w_j_end:
                                sl_covered.add(j)
                    if len(sl_covered) > best_cov:
                        best_cov = len(sl_covered)
                        best_slice = (sl_s, sl_e)
                        best_idx = s_idx

                ref_covered = max(0, best_cov)
                coverage = ref_covered / max(1, ref_len)

                # Pure coverage guard (no confidence check, robust to noisy/fast ASR):
                # 1. Short words (<= 2 chars like "وَ", "فَ") require at least 1 covered char.
                # 2. Longer words (>= 3 chars) require at least 2 covered chars AND coverage >= min_cov.
                if ref_len <= 2:
                    if ref_covered < 1:
                        continue
                else:
                    if ref_covered < 2 or coverage < min_cov:
                        continue

                # Handle orphaned sub-slices separated by pauses
                # If an orphaned sub-slice precedes best_slice across a pause, attach it to w - 1
                if best_idx > 0:
                    for sl_s, sl_e in sub_slices[:best_idx]:
                        orphaned_toks = tokens[sl_s:sl_e]
                        if orphaned_toks and (w - 1) in matched_word_tokens:
                            matched_word_tokens[w - 1][-1].extend(orphaned_toks)

                w_toks = tokens[best_slice[0]:best_slice[1]]
                matched_word_tokens[w].append(w_toks)
                w_conf = sum(t.confidence for t in w_toks) / len(w_toks)
                matched_word_scores[w] = round(min(1.0, w_conf), 2)

    if not matched_word_tokens:
        return []

    # Build canonical Ayah segments
    min_w = min(matched_word_tokens.keys())
    max_w = max(matched_word_tokens.keys())
    start_ay = ref_data.words[min_w].ayah if min_w < word_count else 1
    end_ay = ref_data.words[max_w].ayah if max_w < word_count else ref_data.words[-1].ayah

    def _find_pause_cut(w_prev: QuranWord, w_curr: QuranWord) -> Optional[Tuple[float, float]]:
        w_prev_e = w_prev.end or 0.0
        w_curr_s = w_curr.start or 0.0

        if w_curr_s <= w_prev_e:
            return None

        mid_prev = ((w_prev.start or 0.0) + w_prev_e) / 2.0
        mid_curr = (w_curr_s + (w_curr.end or 0.0)) / 2.0

        if intervals:
            idx = bisect.bisect_right(interval_starts, w_curr_s + 0.50)
            for i in range(idx - 1, -1, -1):
                p = intervals[i]
                if p.start_sec < w_prev_e - 1.0:
                    break
                if p.duration_sec < min_pause_s:
                    continue
                # Reject shallow consonant closures (e.g. labial dips > -30 dB) that are not true breath pauses
                if p.duration_sec < 0.35 and getattr(p, "min_energy_db", None) is not None and p.min_energy_db > -30.0:
                    continue
                cut = p.optimal_cut_point

                # Acoustic cut sits naturally between previous word end and current word start
                if (w_prev_e - PAUSE_CUT_MARGIN_S) <= cut <= (w_curr_s + PAUSE_CUT_MARGIN_S) and (mid_prev < cut < mid_curr):
                    return (cut, p.end_sec)
                if (p.start_sec >= w_prev_e - PAUSE_INTERVAL_OVERLAP_S) and (p.end_sec <= w_curr_s + PAUSE_INTERVAL_OVERLAP_S):
                    if mid_prev < cut < mid_curr:
                        return (cut, p.end_sec)
        elif pause_pts:
            idx = bisect.bisect_right(pause_pts, w_curr_s + 0.50)
            for i in range(idx - 1, -1, -1):
                pt = pause_pts[i]
                if pt < w_prev_e - 1.0:
                    break
                if (w_prev_e - PAUSE_CUT_MARGIN_S) <= pt <= (w_curr_s + PAUSE_CUT_MARGIN_S) and (mid_prev < pt < mid_curr):
                    return (pt, pt + 0.10)

        return None

    segments: List[QuranSegment] = []
    seg_number = 1

    for ay in range(start_ay, end_ay + 1):
        ay_words = ref_data.ayah_to_words.get(ay, [])
        if not ay_words:
            continue

        qwords: List[QuranWord] = []
        has_repeated = False

        for rw in ay_words:
            w_idx = rw.global_index
            passes = matched_word_tokens.get(w_idx)
            if passes:
                if len(passes) > 1:
                    has_repeated = True
                chosen_pass = passes[-1]
                score = matched_word_scores.get(w_idx, 1.0)
                qwords.append(_build_qword(rw, chosen_pass, score))

        if not qwords:
            continue

        if has_repeated and len(qwords) > 1:
            chosen_tokens = []
            next_start = float('inf')
            for rw in reversed(ay_words):
                w_idx = rw.global_index
                passes = matched_word_tokens.get(w_idx, [])
                if not passes:
                    continue
                valid = [p for p in passes if p and (p[-1].end <= next_start + 0.05)]
                chosen = valid[-1] if valid else passes[0]
                chosen_tokens.append((rw, chosen))
                if chosen:
                    next_start = chosen[0].start

            chosen_tokens.reverse()
            qwords = [
                _build_qword(rw, p, matched_word_scores.get(rw.global_index, 1.0))
                for rw, p in chosen_tokens
            ]

        sub_segments: Optional[List[AyahSubSegment]] = None
        repeated_ranges: Optional[List[str]] = None
        repeated_text: Optional[List[str]] = None

        # Tier 1: Group word instances into passes (repetition tracking)
        passes: List[Tuple[List[QuranWord], bool]] = []

        if has_repeated:
            all_word_instances = []
            for rw in ay_words:
                w_idx = rw.global_index
                for p in matched_word_tokens.get(w_idx, []):
                    if p:
                        score = matched_word_scores.get(w_idx, 1.0)
                        all_word_instances.append((w_idx, _build_qword(rw, p, score)))

            all_word_instances.sort(key=lambda x: x[1].start or 0.0)

            current_pass: List[QuranWord] = []
            prev_w_idx = -1

            for w_idx, q_inst in all_word_instances:
                if current_pass and w_idx <= prev_w_idx:
                    passes.append((current_pass, len(passes) > 0))
                    current_pass = []
                current_pass.append(q_inst)
                prev_w_idx = w_idx

            if current_pass:
                passes.append((current_pass, len(passes) > 0))
        else:
            passes = [(qwords, False)]


        # Tier 2: Split passes on Phase 1 pauses with 'Never Cut Word' geometric validation
        sub_segs_list: List[AyahSubSegment] = []

        def _build_sub(pass_words: List[QuranWord], is_rep: bool) -> AyahSubSegment:
            sub_asr = "".join("".join(p.get("phoneme", "") for p in (w.phonemes or [])) for w in pass_words if w.phonemes)
            return AyahSubSegment(
                sub_segment_number=len(sub_segs_list) + 1,
                start_time=pass_words[0].start or 0.0,
                end_time=pass_words[-1].end or 0.0,
                text=sub_asr,
                words_range=f"{pass_words[0].location}-{pass_words[-1].location}",
                is_repetition=is_rep,
                words=pass_words,
            )

        seen_locations: set[str] = set()

        def _append_chunk(chunk: List[QuranWord]) -> None:
            if not chunk:
                return

            # A subsegment is marked as a repetition if it contains ANY word that has already been recited earlier in this Ayah
            is_rep_chunk = (
                has_repeated
                and bool(chunk)
                and any((w.location in seen_locations) for w in chunk if w.location)
            )
            # Mark repetition flag on each individual word
            for w in chunk:
                if has_repeated and w.location and (w.location in seen_locations):
                    w.is_repetition = True
                else:
                    w.is_repetition = False
                if w.location:
                    seen_locations.add(w.location)

            sub_segs_list.append(_build_sub(chunk, is_rep_chunk))

        for p_idx, (pass_words, _) in enumerate(passes):
            current_chunk: List[QuranWord] = []
            for w in pass_words:
                if current_chunk:
                    prev_w = current_chunk[-1]
                    p_bounds = _find_pause_cut(prev_w, w)
                    if p_bounds is not None:
                        _append_chunk(current_chunk)
                        current_chunk = []

                current_chunk.append(w)

            if current_chunk:
                _append_chunk(current_chunk)

        ui_sub_pause = getattr(config, "SUBSEGMENT_MIN_PAUSE_S", 9999.0)
        allow_ui_subsegments = (ui_sub_pause < 9000.0)
        if (len(sub_segs_list) > 1 and allow_ui_subsegments) or has_repeated:
            sub_segments = sub_segs_list
            repeated_ranges = [s.words_range for s in sub_segments if s.is_repetition] or None
            repeated_text = [s.text for s in sub_segments if s.is_repetition] or None

        if sub_segments:
            seg_start = sub_segments[0].start_time
            seg_end = sub_segments[-1].end_time
        elif qwords:
            seg_start = qwords[0].start or 0.0
            seg_end = qwords[-1].end or 0.0
        else:
            all_ay_passes = [p for rw in ay_words for p in matched_word_tokens.get(rw.global_index, []) if p]
            seg_start = min(p[0].start for p in all_ay_passes) if all_ay_passes else 0.0
            seg_end = max(p[-1].end for p in all_ay_passes) if all_ay_passes else 0.0
        matched_ref_str = f"{ref_data.surah}:{ay}:1-{ref_data.surah}:{ay}:{len(ay_words)}"

        segments.append(QuranSegment(
            segment_number=seg_number,
            ayah=ay,
            surah_number=ref_data.surah,
            start_time=round(seg_start, 3),
            end_time=round(seg_end, 3),
            matched_ref=matched_ref_str,
            words=qwords,
            repeated_ranges=repeated_ranges,
            repeated_text=repeated_text,
            sub_segments=sub_segments,
        ))
        seg_number += 1

    return segments


# ═══════════════════════════════════════════════════════════════════════════════
# 3. OPENING PREAMBLE EXTRACTION
# ═══════════════════════════════════════════════════════════════════════════════

ISTIAADHA_REF_DATA = SurahReferenceData(
    0,
    ayah_words={1: ["ءaعuuذu", "بiلaaهi", "مiنa", "شaيطaaنi", "رaجiiم"]},
    uthmani_words={1: ["أَعُوذُ", "بِٱللَّهِ", "مِنَ", "ٱلشَّيْطَـٰنِ", "ٱلرَّجِيمِ"]},
)

TAKBEER_REF_DATA = SurahReferenceData(
    0,
    ayah_words={2: ["ءaلaaهu", "ءaكبaر"]},
    uthmani_words={2: ["اللَّهُ", "أَكْبَرُ"]},
)

TASMEE_REF_DATA = SurahReferenceData(
    0,
    ayah_words={3: ["سaمiعa", "لaaهu", "لiمaن", "حaمiدaه"]},
    uthmani_words={3: ["سَمِعَ", "اللَّهُ", "لِمَنْ", "حَمِدَهُ"]},
)


def _slice_preamble_match(
    pattern: str,
    tokens: List[PhonemeToken],
    max_dist: Optional[int] = None,
    max_error_ratio: float = 0.28,
) -> Tuple[Optional[Tuple[float, float, List[PhonemeToken]]], List[PhonemeToken]]:
    """Fast bit-parallel slice for opening preamble using Gene Myers' kernel."""
    if not tokens:
        return None, tokens

    head_len = min(len(tokens), len(pattern) + 30)
    head_str = "".join(t.phoneme for t in tokens[:head_len])
    if max_dist is None:
        max_dist = max(2, int(len(pattern) * max_error_ratio))

    matches = find_near_matches(pattern, head_str, max_l_dist=max_dist)
    if matches and matches[0].start <= 14:
        m = matches[0]
        consumed = 0
        start_tok_idx = 0
        start_t, end_t = None, None
        k = len(tokens)
        for idx, tok in enumerate(tokens):
            consumed += len(tok.phoneme)
            if start_t is None and consumed > m.start:
                start_t = tok.start
                start_tok_idx = idx
            if consumed >= m.end:
                end_t = tok.end
                k = idx + 1
                break
        matched_toks = tokens[start_tok_idx:k]
        st = start_t if start_t is not None else (matched_toks[0].start if matched_toks else tokens[0].start)
        et = end_t if end_t is not None else (matched_toks[-1].end if matched_toks else tokens[-1].end)
        return (st, et, matched_toks), tokens[k:]

    return None, tokens


def _extract_opening_preamble(
    tokens: List[PhonemeToken],
    surah: int,
    start_ayah: int,
    ref_surah_1: SurahReferenceData,
) -> Tuple[Optional[Dict[str, Any]], List[PhonemeToken]]:
    """Detects and isolates prayer transition phrases (Takbeer/Tasmee'), Isti'adha, and/or Basmalah before Ayah 1."""
    if not tokens:
        return None, tokens

    curr = tokens
    intro_words: List[Dict[str, Any]] = []
    intro_texts: List[str] = []
    intro_starts: List[float] = []
    intro_ends: List[float] = []

    def _match_and_align(pattern: str, ref: SurahReferenceData, max_dist: Optional[int] = None) -> None:
        nonlocal curr
        res, curr = _slice_preamble_match(pattern, curr, max_dist=max_dist)
        if res:
            st, et, toks = res
            intro_starts.append(st)
            intro_ends.append(et)
            segs = _align_and_package_ayahs(
                tokens=toks,
                ref_data=ref,
                start_word_index=0,
                target_end_ayah=None,
            )
            if segs:
                if segs[0].sub_segments:
                    for sub in segs[0].sub_segments:
                        intro_texts.append(sub.text)
                        for w in sub.words:
                            intro_words.append(w.to_dict())
                elif segs[0].words:
                    intro_texts.append("".join("".join(p.get("phoneme", "") for p in (w.phonemes or [])) for w in segs[0].words if w.phonemes))
                    for w in segs[0].words:
                        intro_words.append(w.to_dict())

    # 1. Prayer transition phrases (Takbeer and/or Tasmee' in arbitrary prayer sequences)
    # Strictly excluded on Quranic verses containing or resembling Allahu Akbar / Tasmee' to avoid false matching
    if (surah, start_ayah) not in PRAYER_EXCLUDED_VERSES:
        for _ in range(6):
            prev_len = len(curr)
            # Try Takbeer
            _match_and_align(TAKBEER_PH, TAKBEER_REF_DATA, max_dist=3)
            if len(curr) < prev_len:
                continue
            # Try Tasmee'
            _match_and_align(TASMEE_PH, TASMEE_REF_DATA, max_dist=5)
            if len(curr) < prev_len:
                continue
            break

    # 3. Isti'adha (can precede any recitation)
    _match_and_align(ISTIAADHA_PH, ISTIAADHA_REF_DATA)

    # 4. Basmalah (Surahs 2-114 except 9)
    if surah not in (1, 9):
        basmalah_ph = "".join(w.phoneme for w in ref_surah_1.ayah_to_words[1])
        _match_and_align(basmalah_ph, ref_surah_1)

    if intro_texts:
        return {
            "start": round(min(intro_starts), 3),
            "end": round(max(intro_ends), 3),
            "transcribed_text": "".join(intro_texts),
            "words": intro_words,
        }, curr

    return None, curr


# ═══════════════════════════════════════════════════════════════════════════════
# 4. CONSOLIDATED QURAN RECITATION MATCHER FACADE
# ═══════════════════════════════════════════════════════════════════════════════

class QuranMatcher:
    """Unified Quran Recitation Alignment Engine."""

    def __init__(self, config: Optional[MatcherConfig] = None):
        self.config = config or MatcherConfig()
        self.detector = SurahDetector()
        self._zfx_reader: Optional[ZfxReader] = None
        self._surah_refs: Dict[int, SurahReferenceData] = {}
        self._is_initialized = False

    @property
    def is_initialized(self) -> bool:
        return self._is_initialized

    def initialize_from_file(
        self,
        zfx_path: Optional[str] = None,
        tokens_path: Optional[str] = None,
        qpc_path: Optional[str] = None,
    ) -> None:
        target_zfx = zfx_path or DEFAULT_EXPECTED_ZFX_PATH
        target_tokens = tokens_path or DEFAULT_TOKENS_PATH
        target_qpc = qpc_path or getattr(config, "DEFAULT_QPC_HAFS_PATH", None)

        if not os.path.exists(target_zfx):
            raise FileNotFoundError(f"Missing ZFX reference file: {target_zfx}")
        if not os.path.exists(target_tokens):
            raise FileNotFoundError(f"Missing tokens file: {target_tokens}")

        self._zfx_reader = ZfxReader(target_zfx, target_tokens, qpc_path=target_qpc)

        self.detector.initialize(
            zfx_reader=self._zfx_reader,
            zfx_path=target_zfx,
            tokens_path=target_tokens,
        )
        self._is_initialized = True

    def _get_surah_ref(self, surah: int) -> SurahReferenceData:
        if surah not in self._surah_refs:
            if self._zfx_reader is None:
                raise RuntimeError("QuranMatcher is not initialized with ZFX reference.")
            w_dict, u_dict = self._zfx_reader.get_surah_data(surah)
            self._surah_refs[surah] = SurahReferenceData(surah, ayah_words=w_dict, uthmani_words=u_dict)
        return self._surah_refs[surah]

    def match_segments(
        self,
        phonemes: List[PhonemeToken],
        audio_duration: float = 0.0,
        target_surah: Optional[int] = None,
        start_ayah: Optional[int] = None,
        pause_timestamps: Optional[List[float]] = None,
        pause_intervals: Optional[List[PauseInterval]] = None,
    ) -> List[QuranSegment]:
        if not self._is_initialized:
            self.initialize_from_file()
        if not phonemes or self._zfx_reader is None:
            return []

        # 1. Automatic Multi-Surah / Single-Surah Detection
        if target_surah is not None:
            detected_surah = target_surah
            detected_start_ayah = start_ayah
            detected_end_ayah: Optional[int] = None
            sections = [
                SurahDetectionResult(
                    surah=detected_surah,
                    start_ayah=detected_start_ayah or 1,
                    end_ayah=detected_end_ayah,
                    token_start_idx=0,
                    token_end_idx=len(phonemes),
                )
            ]
        else:
            sections = self.detector.detect_multi_surah(
                phonemes,
                pause_timestamps=pause_timestamps,
                pause_intervals=pause_intervals,
            )

        if not sections:
            sections = [SurahDetectionResult(surah=1, start_ayah=1, token_start_idx=0, token_end_idx=len(phonemes))]

        if len(sections) == 1:
            det_res = sections[0]
            detected_surah = det_res.surah
            detected_start_ayah = det_res.start_ayah
            detected_end_ayah = None
            if det_res.end_ayah is not None and det_res.end_ayah > det_res.start_ayah:
                detected_end_ayah = det_res.end_ayah
            logger.info(
                "Detected Surah %d starting at Ayah %d (confidence=%.2f)",
                detected_surah,
                detected_start_ayah,
                det_res.confidence,
            )
            return self._align_surah_section(
                tokens=phonemes,
                surah=detected_surah,
                start_ayah=detected_start_ayah or 1,
                end_ayah=detected_end_ayah,
                pause_timestamps=pause_timestamps,
                pause_intervals=pause_intervals,
            )

        # Multi-Surah Recitation Sequential Alignment
        logger.info("Multi-Surah recitation detected: %d distinct Surah sections found", len(sections))
        all_segments: List[QuranSegment] = []
        global_seg_idx = 1

        for sec in sections:
            sec_tokens = phonemes[sec.token_start_idx : sec.token_end_idx]
            if not sec_tokens:
                continue

            sec_surah = sec.surah
            sec_start_ay = sec.start_ayah or 1
            sec_end_ay = sec.end_ayah if (sec.end_ayah is not None and sec.end_ayah > sec_start_ay) else None

            logger.info(
                "Aligning section Surah %d (Ayah %d to %s, confidence=%.2f, tokens=[%d:%d])",
                sec_surah,
                sec_start_ay,
                str(sec_end_ay or "end"),
                sec.confidence,
                sec.token_start_idx,
                sec.token_end_idx,
            )

            segs = self._align_surah_section(
                tokens=sec_tokens,
                surah=sec_surah,
                start_ayah=sec_start_ay,
                end_ayah=sec_end_ay,
                pause_timestamps=pause_timestamps,
                pause_intervals=pause_intervals,
            )

            for seg in segs:
                seg.segment_number = global_seg_idx
                global_seg_idx += 1
                all_segments.append(seg)

        return all_segments

    def _align_surah_section(
        self,
        tokens: List[PhonemeToken],
        surah: int,
        start_ayah: int,
        end_ayah: Optional[int],
        pause_timestamps: Optional[List[float]],
        pause_intervals: Optional[List[PauseInterval]],
    ) -> List[QuranSegment]:
        """Aligns a continuous section against a specific Surah reference with preamble extraction."""
        intro_dict, remaining_tokens = _extract_opening_preamble(
            tokens=tokens,
            surah=surah,
            start_ayah=start_ayah,
            ref_surah_1=self._get_surah_ref(1),
        )

        ref_data = self._get_surah_ref(surah)
        effective_start_ayah = start_ayah
        if intro_dict and any(w.get("location", "").startswith("1:1:") for w in intro_dict.get("words", [])):
            effective_start_ayah = 1
        start_word_idx = ref_data.ayah_start_word_index.get(effective_start_ayah, 0)

        segs = _align_and_package_ayahs(
            tokens=remaining_tokens,
            ref_data=ref_data,
            start_word_index=start_word_idx,
            target_end_ayah=end_ayah,
            matcher_cfg=self.config,
            pause_timestamps=pause_timestamps,
            pause_intervals=pause_intervals,
        )

        if intro_dict and segs:
            segs[0].intro = intro_dict

        return segs


# Backward compatibility alias
QuranWordMatcher = QuranMatcher
