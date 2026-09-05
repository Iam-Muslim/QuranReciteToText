"""Unified Character-Level Word Sequencer: In-order progression, Wasl merging,
lookahead omissions, and generalized backward lookback across continuous word streams.

Mirrors Dart lib/phase3_matcher/dictation_sequencer.dart exactly.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any

from src.core.models import PhonemeToken, QuranWord
from src.phase3_matcher.dictation_matcher import QuranDictationMatcher, WordMatchResult, PhonemeGroupAlignment
from src.phase3_matcher.matcher_config import MatcherConfig
from src.phase3_matcher.phonetic_cost_engine import PhoneticCostEngine


@dataclass
class RefWord:
    """Represents a reference word in the continuous Quranic stream."""
    global_index: int
    surah: int
    ayah: int
    word_index_in_ayah: int
    text: str
    ref_phoneme: str
    location: str


@dataclass
class SequencedWord:
    """Represents a classified word during sequential alignment."""
    surah: int
    ayah: int
    word_index_in_ayah: int
    text: str
    ref_phoneme: str
    location: str
    is_green: bool
    is_red: bool
    score: float
    start: float
    end: float
    confidence: float
    matched_tokens: List[PhonemeToken] = field(default_factory=list)

    @classmethod
    def missing(cls, ref: RefWord, timestamp: float) -> SequencedWord:
        return cls(
            surah=ref.surah,
            ayah=ref.ayah,
            word_index_in_ayah=ref.word_index_in_ayah,
            text=ref.text,
            ref_phoneme=ref.ref_phoneme,
            location=ref.location,
            is_green=False,
            is_red=True,
            score=0.0,
            start=timestamp,
            end=timestamp + 0.05,
            confidence=0.0,
            matched_tokens=[],
        )

    @classmethod
    def matched(
        cls,
        ref: RefWord,
        start: float,
        end: float,
        score: float,
        tokens: List[PhonemeToken],
    ) -> SequencedWord:
        avg_conf = (
            sum(p.confidence for p in tokens) / len(tokens)
            if tokens else 1.0
        )
        return cls(
            surah=ref.surah,
            ayah=ref.ayah,
            word_index_in_ayah=ref.word_index_in_ayah,
            text=ref.text,
            ref_phoneme=ref.ref_phoneme,
            location=ref.location,
            is_green=True,
            is_red=False,
            score=score,
            start=start,
            end=end,
            confidence=avg_conf,
            matched_tokens=tokens,
        )

    def to_quran_word(self) -> QuranWord:
        return QuranWord(
            word=self.text,
            location=self.location,
            start=round(self.start, 2),
            end=round(self.end, 2),
            score=round(self.score, 2),
            confidence=round(self.confidence, 4),
            phonemes=[p.to_dict() for p in self.matched_tokens],
        )


@dataclass
class AyahSequenceResult:
    """Result of sequencing words against the ASR phoneme stream."""
    chars_consumed: int
    words: List[SequencedWord]
    has_missing_words: bool
    repeated_ranges: List[Dict[str, Any]] = field(default_factory=list)
    repeated_text: List[str] = field(default_factory=list)


class DictationSequencer:
    """Unified Sequencer matching continuous word streams with lookahead omissions,
    Wasl merging, and backward repetitions.
    """

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
    ) -> AyahSequenceResult:
        """Unified tracking over a continuous word stream."""
        ayah_start_indices = ayah_start_indices if ayah_start_indices is not None else []
        word_count = len(ref_words)
        if word_count == 0 or not asr_text:
            return AyahSequenceResult(
                chars_consumed=0,
                words=[SequencedWord.missing(ref_words[i], default_start_time) for i in range(word_count)],
                has_missing_words=True,
            )

        word_boundaries: List[int] = [0]
        for w in ref_words:
            word_boundaries.append(word_boundaries[-1] + len(w.ref_phoneme))
        full_phonemes = "".join(w.ref_phoneme for w in ref_words)

        asr_char_anchor = 0
        word_cursor = 0
        last_word_end = default_start_time

        committed_words: Dict[int, SequencedWord] = {}
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
        rep_first_words: Dict[int, SequencedWord] = {}

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
                    rep_words_list.append(rep_first_words[s].to_quran_word())

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
                "words": rep_words_list,
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

        # ── Unified Continuous Tracking Loop ──
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

            # Evaluates a candidate (target_w, merge) using the unified objective function
            def evaluate_candidate(target_w: int, merge: int) -> bool:
                nonlocal best_score, best_result, best_target_w, best_merge, waiting_for_partial
                if target_w < 0:
                    return False
                end_w = target_w + merge - 1
                if end_w >= word_count:
                    return False

                ref_start = word_boundaries[target_w]
                ref_end = (
                    word_boundaries[end_w + 1]
                    if end_w + 1 < len(word_boundaries)
                    else len(full_phonemes)
                )

                # Disambiguation Guard: Reject isolated short particles on any non-local jump (skip or backtrack)
                delta = target_w - word_cursor
                if delta != 0 and merge == 1:
                    eff_n = PhoneticCostEngine.get_effective_length(
                        full_phonemes, ref_start, ref_end
                    )
                    if eff_n < 4:
                        return False

                n = ref_end - ref_start
                max_win = min(unconsumed_len, max(45, n * 3 + 25))

                res = self._matcher.match_word(
                    asr_text=asr_text[asr_char_anchor:asr_char_anchor + max_win],
                    asr_timestamps=asr_start_timestamps[ts_start:min(len(asr_start_timestamps), ts_start + max_win)],
                    full_phonemes=full_phonemes,
                    ref_start=ref_start,
                    ref_end=ref_end,
                    config=config,
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
                    res,
                    target_w,
                    end_w,
                    word_boundaries,
                    full_phonemes,
                    asr_text[asr_char_anchor:asr_char_anchor + max_win],
                    config,
                ):
                    return False

                transition_penalty = (
                    0.0
                    if delta == 0
                    else (0.10 * delta if delta > 0 else (0.25 + 0.04 * abs(delta)))
                )
                onset_penalty = res.start_token_idx * 0.15
                score = res.path_cost + transition_penalty + onset_penalty

                if score < best_score:
                    best_score = score
                    best_result = res
                    best_target_w = target_w
                    best_merge = merge
                return True

            # Step 1: Evaluate Expected Word (delta == 0)
            for merge in (1, 2):
                evaluate_candidate(word_cursor, merge)
                if waiting_for_partial:
                    break

            if waiting_for_partial:
                break

            # Fast-Path: If expected word matched at microphone onset (start_token_idx <= 2)
            # with good acoustic confidence, accept it immediately!
            immediate_in_order = (
                best_result is not None
                and best_target_w == word_cursor
                and best_result.start_token_idx <= 2
                and best_result.path_cost <= config.default_max_path_cost
            )

            # Step 2: If expected word failed or skipped leading speech, search alternatives!
            if not immediate_in_order:
                # Forward skips (omissions)
                for s in range(1, config.max_skip_words + 1):
                    if word_cursor + s < word_count:
                        for merge in (1, 2):
                            evaluate_candidate(word_cursor + s, merge)

                # Backward lookbacks (repetitions within current Ayah)
                current_ayah_start = 0
                for idx in ayah_start_indices:
                    if idx <= word_cursor:
                        current_ayah_start = idx
                lookback_limit = min(word_cursor - current_ayah_start + 1, 15)
                for b in range(1, lookback_limit + 1):
                    target_w = word_cursor - b
                    for merge in (2, 1):
                        evaluate_candidate(target_w, merge)

            # ── Process Match or Terminate ──
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

                # ── Repetition State Machine Tracking ──
                if delta < 0:
                    # Backward Jump: Begin or extend repetition span
                    if rep_start_word is None:
                        rep_start_word = target_w
                        rep_max_end_word = end_w
                        rep_start_time = w_start
                        rep_end_time = w_end
                        rep_first_start_time = (
                            committed_words[target_w].start
                            if target_w in committed_words
                            else None
                        )
                        rep_first_end_time = (
                            committed_words[end_w].end
                            if end_w in committed_words
                            else None
                        )
                        rep_first_words.clear()
                        for s in range(target_w, highest_word_reached + 1):
                            if s in committed_words:
                                rep_first_words[s] = committed_words[s]
                    else:
                        rep_max_end_word = max(rep_max_end_word, end_w)
                        rep_end_time = w_end
                else:
                    # In-order forward progression (delta >= 0)
                    if rep_start_word is not None:
                        if target_w <= highest_word_reached:
                            # Still reciting repeated words forward!
                            rep_max_end_word = max(rep_max_end_word, end_w)
                            rep_end_time = w_end
                        else:
                            # Reciter passed previous frontier: Repetition finished!
                            flush_repetition()

                    if delta > 0 and rep_start_word is None:
                        # Forward Jump: Mark skipped words RED
                        for s in range(word_cursor, target_w):
                            if s not in committed_words:
                                committed_words[s] = SequencedWord.missing(ref_words[s], last_word_end)
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
                break  # Strictly terminate if no candidate matched

        if rep_start_word is not None:
            flush_repetition()

        # ── Mark remaining uncommitted words within reached passage as RED ──
        limit = min(word_count, max(word_cursor, highest_word_reached + 1))
        for w in range(limit):
            if w not in committed_words:
                committed_words[w] = SequencedWord.missing(ref_words[w], last_word_end)
                has_missing = True

        return AyahSequenceResult(
            chars_consumed=asr_char_anchor,
            words=[committed_words[w] for w in range(limit)],
            has_missing_words=has_missing,
            repeated_ranges=repeated_ranges,
            repeated_text=repeated_text,
        )

    def _commit_words_green(
        self,
        committed_words: Dict[int, SequencedWord],
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
        # Extract tokens mapped strictly via Viterbi alignment trace
        pure_tokens: List[PhonemeToken] = []
        seen = set()
        for align in trace:
            if 0 <= align.pred_idx < len(unconsumed_tokens):
                t = unconsumed_tokens[align.pred_idx]
                t_id = id(t)
                if t_id not in seen:
                    seen.add(t_id)
                    pure_tokens.append(t)

        # Fallback if trace has no matched tokens
        if not pure_tokens and unconsumed_tokens:
            for c in range(min(chars_consumed, len(unconsumed_tokens))):
                t = unconsumed_tokens[c]
                t_id = id(t)
                if t_id not in seen:
                    seen.add(t_id)
                    pure_tokens.append(t)

        # If word ended in the middle of a multi-char token, that token belongs to the next word
        if (
            chars_consumed < len(unconsumed_tokens)
            and pure_tokens
            and pure_tokens[-1] is unconsumed_tokens[chars_consumed]
        ):
            pure_tokens.pop()

        if merge == 1:
            word_start = pure_tokens[0].start if pure_tokens else w_start
            word_end = pure_tokens[-1].end if pure_tokens else w_end

            committed_words[start_w] = SequencedWord.matched(
                ref=ref_words[start_w],
                start=word_start,
                end=word_end,
                score=word_score,
                tokens=pure_tokens,
            )
        else:
            # Split tokens strictly by alignment reference boundaries
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

            committed_words[start_w] = SequencedWord.matched(
                ref=ref_words[start_w],
                start=w1_s,
                end=w1_e,
                score=word_score,
                tokens=tokens1,
            )

            committed_words[start_w + 1] = SequencedWord.matched(
                ref=ref_words[start_w + 1],
                start=w2_s,
                end=w2_e,
                score=word_score,
                tokens=tokens2,
            )

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
                            core_cost += PhoneticCostEngine.get_substitution_cost(
                                asr_code, ref_code
                            )
                        else:
                            core_cost += config.standard_insertion_cost

            if (core_cost / core_len) > config.default_max_path_cost:
                return False

        return True
