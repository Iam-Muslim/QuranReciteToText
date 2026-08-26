"""Ayah-Level Splitting via CTC Word Timestamps.

Splits multi-ayah SDK segments into per-ayah segments at word boundaries,
preserving ALL metadata (repetitions, wrap ranges, error, etc.) from the
parent segment.

Repetition handling:
- A chunk that contains a repetition (wrap_word_ranges set) is split normally
  at ayah boundaries. The sub-segment that contains the repeated section
  inherits has_repeated_words=True and the relevant wrap/repeated fields.
- Repetitions spanning two ayahs (rare) are kept on the first sub-segment.
"""

from __future__ import annotations
import math
from typing import Any
import numpy as np
from src.core.segment_types import SegmentInfo


WAQF_MARKS = frozenset("ۖۗۘۚۛۜ")


def _ayah_key_and_word(location: str | None):
    if not location:
        return None, None
    parts = location.split(":")
    if len(parts) >= 3:
        try:
            return f"{parts[0]}:{parts[1]}", int(parts[2])
        except ValueError:
            return f"{parts[0]}:{parts[1]}", None
    elif len(parts) >= 2:
        return f"{parts[0]}:{parts[1]}", None
    return None, None


def _wrap_ranges_for_group(wrap_word_ranges: Any, group_locs: set[str]):
    """Filter wrap_word_ranges to those whose jump_to falls in this group's locs."""
    if not wrap_word_ranges:
        return None
    result = []
    for wr in wrap_word_ranges:
        # wr is (jump_to, jump_from, repeat_end) or (jump_to, jump_from)
        jump_to = wr[0] if wr else None
        if jump_to and jump_to in group_locs:
            result.append(wr)
    return result if result else None


# A group is a plain dict with keys: key (str), reason (str), words (list[dict])
# Using dicts avoids all tuple-unpacking type checker complaints and allows
# in-place mutation of the words list.
def _new_group(key: str | None, reason: str, first_word: dict) -> dict:
    return {"key": key, "reason": reason, "words": [first_word]}


def split_segments_at_ayah_boundaries(
    segments: list[SegmentInfo],
    min_word_gap_s: float = 0.5,
    split_all_ayahs: bool = False,
) -> list[SegmentInfo]:
    """Splits segments at ayah, repetition, and meaningful intra-ayah pause boundaries.

    Ayah boundaries require a small meaningful silence gap, repetition boundaries
    are always retained, and pauses within one ayah use ``min_word_gap_s``.

    Preserves all metadata from the parent segment including:
    - has_repeated_words / wrap_word_ranges / repeated_ranges / repeated_text
    - error, match_score, _original_alignment_idx
    - has_missing_words (will be recomputed by recompute_missing_words later)
    """
    # Minimum silence gap (seconds) between the end of the last word of one
    # ayah group and the start of the first word of the next to justify a split.
    # Below this threshold the groups are merged back (reciter read continuously).
    # CTC timestamp jitter is typically < 40ms, so 40ms is a safe floor.
    MIN_SPLIT_GAP_S = 0.04

    from qua_sdk.domain import SPECIAL_NAMES as ALL_SPECIAL_REFS
    result: list[SegmentInfo] = []

    for seg in segments:
        # Skip specials and segments with no word timestamps
        if seg.matched_ref in ALL_SPECIAL_REFS or not seg.words:
            result.append(seg)
            continue

        # ----------------------------------------------------------------
        # Step 1: Group words by (surah:ayah) key.
        # A new group is opened when:
        #   a) the ayah key changes            → reason "ayah_boundary"
        #   b) the word index goes backward    → reason "repetition"
        #   c) two words in one ayah have a meaningful pause → reason "word_gap"
        #   d) a waqf mark is followed by a clear ASR gap   → reason "waqf"
        # ----------------------------------------------------------------
        groups: list[dict] = []
        prev_key: str | None = None
        prev_word_num: int | None = None

        for word_index, w in enumerate(seg.words):
            loc: str | None = w.get("location")
            if not loc or loc.startswith("0:0:"):
                # Special-segment words (location 0:0:N) — attach to current group
                if groups:
                    groups[-1]["words"].append(w)
                else:
                    groups.append(_new_group("special", "first", w))
                continue

            key, word_num = _ayah_key_and_word(loc)
            acoustic_gap = (
                seg._acoustic_word_gaps[word_index]
                if seg._acoustic_word_gaps
                and word_index < len(seg._acoustic_word_gaps)
                else None
            )
            asr_gap = (
                seg._asr_word_gaps[word_index]
                if seg._asr_word_gaps and word_index < len(seg._asr_word_gaps)
                else None
            )

            if not groups:
                groups.append(_new_group(key, "first", w))
            elif key != prev_key and key is not None:
                groups.append(_new_group(key, "ayah_boundary", w))
            elif (
                word_num is not None
                and prev_word_num is not None
                and word_num <= prev_word_num
            ):
                # Backward word index within the same ayah = repetition boundary
                groups.append(_new_group(key, "repetition", w))
            elif key == prev_key:
                previous_word = groups[-1]["words"][-1]
                previous_end = previous_word.get("end")
                current_start = w.get("start")
                ctc_gap = (
                    current_start - previous_end
                    if previous_end is not None and current_start is not None
                    else None
                )
                has_waqf = any(mark in previous_word.get("word", "") for mark in WAQF_MARKS)
                waqf_gap = asr_gap if asr_gap is not None else ctc_gap
                if acoustic_gap is not None and acoustic_gap >= min_word_gap_s:
                    groups.append(_new_group(key, "word_gap", w))
                elif (
                    has_waqf
                    and waqf_gap is not None
                    and waqf_gap >= max(0.24, min_word_gap_s * 0.5)
                ):
                    # Zipformer encoder frames advance in 40ms steps (25 Hz),
                    # so 240ms (6 frames) reliably captures natural Waqf pauses.
                    groups.append(_new_group(key, "waqf", w))

                else:
                    groups[-1]["words"].append(w)
            else:
                groups[-1]["words"].append(w)

            if key is not None:
                prev_key = key
            if word_num is not None:
                prev_word_num = word_num

        # No split needed
        if len(groups) <= 1:
            result.append(seg)
            continue

        # ----------------------------------------------------------------
        # Step 2: Merge back adjacent ayah-boundary groups that have no
        # meaningful silence gap (the reciter read continuously).
        # Repetition and intra-ayah pause boundaries are ALWAYS kept.
        # ----------------------------------------------------------------
        merged: list[dict] = [groups[0]]
        for grp in groups[1:]:
            if grp["reason"] == "ayah_boundary":
                if split_all_ayahs:
                    merged.append(grp)
                    continue
                prev_words = merged[-1]["words"]
                last_end = prev_words[-1].get("end")
                next_start = grp["words"][0].get("start")
                gap = (
                    (next_start - last_end)
                    if last_end is not None and next_start is not None
                    else None
                )
                if gap is None or gap < MIN_SPLIT_GAP_S:
                    # No real pause — merge into previous group
                    merged[-1]["words"].extend(grp["words"])
                    continue
            merged.append(grp)

        # Still no split needed after gap filtering
        if len(merged) <= 1:
            result.append(seg)
            continue

        # ----------------------------------------------------------------
        # Step 3: Emit one SegmentInfo per group.
        # ----------------------------------------------------------------
        seg_start = seg.start_time
        parent_has_rep = seg.has_repeated_words
        parent_wraps = seg.wrap_word_ranges

        for g_idx, grp in enumerate(merged):
            words = grp["words"]
            is_first = (g_idx == 0)
            is_last  = (g_idx == len(merged) - 1)

            first_rel_start = words[0].get("start")
            last_rel_end    = words[-1].get("end")

            if is_first:
                abs_start = seg.start_time
            elif first_rel_start is not None:
                abs_start = seg_start + first_rel_start
            else:
                abs_start = result[-1].end_time if result else seg.start_time

            abs_end_word = (
                seg_start + last_rel_end if last_rel_end is not None else abs_start + 0.04
            )

            if is_last:
                abs_end = seg.end_time
            else:
                next_words     = merged[g_idx + 1]["words"]
                next_rel_start = next_words[0].get("start")
                abs_end = (
                    (abs_end_word + seg_start + next_rel_start) / 2.0
                    if next_rel_start is not None
                    else abs_end_word
                )

            abs_start = round(abs_start, 3)
            abs_end   = round(abs_end,   3)
            if abs_end <= abs_start:
                abs_end = abs_start + 0.04

            # Build ref from word locations
            locs = [
                w.get("location")
                for w in words
                if w.get("location") and not w.get("location", "").startswith("0:0:")
            ]
            if locs:
                ref_from  = locs[0]
                ref_to    = locs[-1]
                matched_ref = ref_from if ref_from == ref_to else f"{ref_from}-{ref_to}"
            else:
                matched_ref = seg.matched_ref

            matched_text = " ".join(
                w.get("word", "") for w in words if not w.get("is_missing")
            )

            # Re-offset word timestamps to be relative to sub-segment start
            offset = abs_start - seg_start
            sub_words: list[dict] = []
            for w in words:
                entry = dict(w)
                if entry.get("start") is not None:
                    entry["start"] = round(max(0.0, entry["start"] - offset), 4)
                if entry.get("end") is not None:
                    entry["end"]   = round(max(0.0, entry["end"]   - offset), 4)
                if "phonemes" in entry:
                    entry["phonemes"] = [
                        {
                            **p,
                            "start": round(max(0.0, p["start"] - offset), 4) if p.get("start") is not None else None,
                            "end": round(max(0.0, p["end"] - offset), 4) if p.get("end") is not None else None,
                        }
                        for p in entry["phonemes"]
                    ]
                sub_words.append(entry)

            # Determine if this sub-segment owns a repetition group.
            # The jump_to location decides which sub-segment inherits the wrap.
            group_locs = {w.get("location") for w in words if w.get("location")}
            sub_wraps  = _wrap_ranges_for_group(parent_wraps, group_locs) if parent_has_rep else None
            sub_has_rep = bool(sub_wraps)

            # Recompute repeated_ranges and repeated_text for the sub-segment
            sub_rep_ranges = None
            sub_rep_text   = None
            if sub_has_rep and sub_wraps and matched_ref and "-" in matched_ref:
                try:
                    from src.core.sdk_adapt import derive_repetition
                    sub_rep_ranges, sub_rep_text = derive_repetition(matched_ref, sub_wraps)
                except Exception:
                    pass

            sub_seg = SegmentInfo(
                start_time=abs_start,
                end_time=abs_end,
                transcribed_text=seg.transcribed_text,
                matched_text=matched_text,
                matched_ref=matched_ref,
                match_score=seg.match_score,
                error=seg.error,
                has_missing_words=False,    # recomputed by recompute_missing_words
                has_repeated_words=sub_has_rep,
                wrap_word_ranges=sub_wraps,
                repeated_ranges=sub_rep_ranges,
                repeated_text=sub_rep_text,
                words=sub_words,
                _original_alignment_idx=seg._original_alignment_idx,
                _preserve_split_before=(
                    not is_first and grp["reason"] in {"word_gap", "repetition", "waqf"}
                ),
            )
            result.append(sub_seg)

    return result


def split_fused_segments(segments: list[SegmentInfo]) -> list[SegmentInfo]:
    """Splits combined or fused special segments (Isti'adha/Basmala) using word timestamps."""
    from qua_sdk.domain import SPECIAL_TEXT, SPECIAL_NAMES as ALL_SPECIAL_REFS

    _BASMALA_TEXT = SPECIAL_TEXT["Basmala"]
    _ISTIATHA_TEXT = SPECIAL_TEXT["Isti'adha"]
    _COMBINED_TEXT = _ISTIATHA_TEXT + " ۝ " + _BASMALA_TEXT

    _ISTIATHA_WORD_COUNT = len(_ISTIATHA_TEXT.split())
    _BASMALA_WORD_COUNT = len(_BASMALA_TEXT.split())

    split_indices = []
    for idx, seg in enumerate(segments):
        if seg.matched_ref == "Isti'adha+Basmala":
            split_indices.append((idx, "combined", "Isti'adha+Basmala", None))
        elif seg.matched_ref and seg.matched_ref not in ALL_SPECIAL_REFS and seg.matched_text:
            if seg.matched_text.startswith(_COMBINED_TEXT):
                split_indices.append((idx, "fused_combined", f"Isti'adha+Basmala+{seg.matched_ref}", seg.matched_ref))
            elif seg.matched_text.startswith(_ISTIATHA_TEXT):
                split_indices.append((idx, "fused_istiatha", f"Isti'adha+{seg.matched_ref}", seg.matched_ref))
            elif seg.matched_text.startswith(_BASMALA_TEXT):
                split_indices.append((idx, "fused_basmala", f"Basmala+{seg.matched_ref}", seg.matched_ref))

    if not split_indices:
        return segments

    new_segments = []
    split_set = {idx for idx, _, _, _ in split_indices}
    split_map = {idx: (i, case, mfa_ref, verse_ref) for i, (idx, case, mfa_ref, verse_ref) in enumerate(split_indices)}

    for idx, seg in enumerate(segments):
        if idx not in split_set:
            new_segments.append(seg)
            continue

        batch_i, case, mfa_ref, verse_ref = split_map[idx]
        words = seg.words

        if words is None:
            if case == "combined":
                mid_time = (seg.start_time + seg.end_time) / 2.0
                new_segments.append(SegmentInfo(
                    start_time=seg.start_time, end_time=mid_time,
                    transcribed_text="", matched_text=_ISTIATHA_TEXT,
                    matched_ref="Isti'adha", match_score=seg.match_score,
                ))
                new_segments.append(SegmentInfo(
                    start_time=mid_time, end_time=seg.end_time,
                    transcribed_text="", matched_text=_BASMALA_TEXT,
                    matched_ref="Basmala", match_score=seg.match_score,
                ))
            else:
                new_segments.append(seg)
            continue

        seg_start = seg.start_time

        if case == "combined":
            istiatha_end = None
            for w in words:
                if w.get("location", "") == f"0:0:{_ISTIATHA_WORD_COUNT}":
                    istiatha_end = seg_start + w["end"]
                    break
            if istiatha_end is None:
                istiatha_end = (seg.start_time + seg.end_time) / 2.0

            new_segments.append(SegmentInfo(
                start_time=seg.start_time, end_time=istiatha_end,
                transcribed_text="", matched_text=_ISTIATHA_TEXT,
                matched_ref="Isti'adha", match_score=seg.match_score,
            ))
            new_segments.append(SegmentInfo(
                start_time=istiatha_end, end_time=seg.end_time,
                transcribed_text="", matched_text=_BASMALA_TEXT,
                matched_ref="Basmala", match_score=seg.match_score,
            ))

        elif case == "fused_combined":
            istiatha_end = None
            basmala_end = None
            basmala_last_loc = f"0:0:{_ISTIATHA_WORD_COUNT + _BASMALA_WORD_COUNT}"

            for w in words:
                loc = w.get("location", "")
                if loc == f"0:0:{_ISTIATHA_WORD_COUNT}":
                    istiatha_end = seg_start + w["end"]
                if loc == basmala_last_loc:
                    basmala_end = seg_start + w["end"]

            if istiatha_end is None:
                istiatha_end = seg.start_time + (seg.end_time - seg.start_time) / 3.0
            if basmala_end is None:
                basmala_end = seg.start_time + 2 * (seg.end_time - seg.start_time) / 3.0

            verse_text = seg.matched_text
            if verse_text.startswith(_COMBINED_TEXT):
                verse_text = verse_text[len(_COMBINED_TEXT):].lstrip()

            new_segments.append(SegmentInfo(
                start_time=seg.start_time, end_time=istiatha_end,
                transcribed_text="", matched_text=_ISTIATHA_TEXT,
                matched_ref="Isti'adha", match_score=seg.match_score,
            ))
            new_segments.append(SegmentInfo(
                start_time=istiatha_end, end_time=basmala_end,
                transcribed_text="", matched_text=_BASMALA_TEXT,
                matched_ref="Basmala", match_score=seg.match_score,
            ))
            new_segments.append(SegmentInfo(
                start_time=basmala_end, end_time=seg.end_time,
                transcribed_text=seg.transcribed_text, matched_text=verse_text,
                matched_ref=verse_ref, match_score=seg.match_score,
                error=seg.error, has_missing_words=seg.has_missing_words,
                _original_alignment_idx=seg._original_alignment_idx,
            ))

        elif case == "fused_istiatha":
            istiatha_end = None
            for w in words:
                if w.get("location", "") == f"0:0:{_ISTIATHA_WORD_COUNT}":
                    istiatha_end = seg_start + w["end"]
                    break
            if istiatha_end is None:
                new_segments.append(seg)
                continue

            verse_text = seg.matched_text
            if verse_text.startswith(_ISTIATHA_TEXT):
                verse_text = verse_text[len(_ISTIATHA_TEXT):].lstrip()

            new_segments.append(SegmentInfo(
                start_time=seg.start_time, end_time=istiatha_end,
                transcribed_text="", matched_text=_ISTIATHA_TEXT,
                matched_ref="Isti'adha", match_score=seg.match_score,
            ))
            new_segments.append(SegmentInfo(
                start_time=istiatha_end, end_time=seg.end_time,
                transcribed_text=seg.transcribed_text, matched_text=verse_text,
                matched_ref=verse_ref, match_score=seg.match_score,
                error=seg.error, has_missing_words=seg.has_missing_words,
                _original_alignment_idx=seg._original_alignment_idx,
            ))

        elif case == "fused_basmala":
            basmala_end = None
            for w in words:
                if w.get("location", "") == f"0:0:{_BASMALA_WORD_COUNT}":
                    basmala_end = seg_start + w["end"]
                    break
            if basmala_end is None:
                new_segments.append(seg)
                continue

            verse_text = seg.matched_text
            if verse_text.startswith(_BASMALA_TEXT):
                verse_text = verse_text[len(_BASMALA_TEXT):].lstrip()

            verse_words, basmala_words = None, None
            verse_asr_gaps, verse_acoustic_gaps = None, None
            verse_start = basmala_end
            if seg.words:
                split_rel = basmala_end - seg.start_time
                b_list, v_list = [], []
                v_asr_gaps, v_acoustic_gaps = [], []
                for word_index, w in enumerate(seg.words):
                    w_copy = dict(w)
                    loc = w_copy.get("location", "")
                    if loc.startswith("0:0:"):
                        b_list.append(w_copy)
                    else:
                        if w_copy.get("start") is not None:
                            w_copy["start"] = max(0.0, round(w_copy["start"] - split_rel, 4))
                        if w_copy.get("end") is not None:
                            w_copy["end"] = max(0.0, round(w_copy["end"] - split_rel, 4))
                        if "phonemes" in w_copy:
                            w_copy["phonemes"] = [
                                {
                                    **p,
                                    "start": max(0.0, round(p["start"] - split_rel, 4)) if p.get("start") is not None else None,
                                    "end": max(0.0, round(p["end"] - split_rel, 4)) if p.get("end") is not None else None,
                                }
                                for p in w_copy["phonemes"]
                            ]
                        v_list.append(w_copy)
                        v_asr_gaps.append(
                            seg._asr_word_gaps[word_index]
                            if seg._asr_word_gaps and word_index < len(seg._asr_word_gaps)
                            else None
                        )
                        v_acoustic_gaps.append(
                            seg._acoustic_word_gaps[word_index]
                            if seg._acoustic_word_gaps
                            and word_index < len(seg._acoustic_word_gaps)
                            else None
                        )

                verse_offset = v_list[0].get("start") if v_list else None
                if verse_offset is not None and verse_offset > 0:
                    verse_start += verse_offset
                    for word in v_list:
                        if word.get("start") is not None:
                            word["start"] = max(0.0, round(word["start"] - verse_offset, 4))
                        if word.get("end") is not None:
                            word["end"] = max(0.0, round(word["end"] - verse_offset, 4))
                basmala_words = b_list or None
                verse_words = v_list or None
                verse_asr_gaps = ([None] + v_asr_gaps[1:]) if v_asr_gaps else None
                verse_acoustic_gaps = (
                    [None] + v_acoustic_gaps[1:] if v_acoustic_gaps else None
                )

            new_segments.append(SegmentInfo(
                start_time=seg.start_time, end_time=basmala_end,
                transcribed_text="", matched_text=_BASMALA_TEXT,
                matched_ref="Basmala", match_score=seg.match_score,
                words=basmala_words,
            ))
            new_segments.append(SegmentInfo(
                start_time=verse_start, end_time=seg.end_time,
                transcribed_text=seg.transcribed_text, matched_text=verse_text,
                matched_ref=verse_ref, match_score=seg.match_score,
                error=seg.error, has_missing_words=seg.has_missing_words,
                words=verse_words,
                _original_alignment_idx=seg._original_alignment_idx,
                _asr_word_gaps=verse_asr_gaps,
                _acoustic_word_gaps=verse_acoustic_gaps,
            ))

    return new_segments


def _find_sustained_silence(
    audio: np.ndarray,
    sample_rate: int,
    start_s: float,
    end_s: float,
    min_silence_s: float,
    threshold_db: float,
    max_start_s: float | None = None,
) -> tuple[float, float] | None:
    """Returns the longest sustained low-energy interval inside a time range."""
    frame_s = 0.05
    hop_s = 0.01
    frame_samples = max(1, int(frame_s * sample_rate))
    hop_samples = max(1, int(hop_s * sample_rate))
    start_sample = max(0, int(start_s * sample_rate))
    end_sample = min(len(audio), int(end_s * sample_rate))
    chunk = audio[start_sample:end_sample]
    if len(chunk) < frame_samples:
        return None

    quiet = []
    for position in range(0, len(chunk) - frame_samples + 1, hop_samples):
        frame = chunk[position:position + frame_samples]
        rms = float(np.sqrt(np.mean(np.square(frame))))
        quiet.append(20.0 * math.log10(max(rms, 1e-8)) <= threshold_db)

    best = None
    run_start = None
    for index, is_quiet in enumerate(quiet + [False]):
        if is_quiet and run_start is None:
            run_start = index
        elif not is_quiet and run_start is not None:
            silence_start = start_s + run_start * hop_s
            silence_end = start_s + (index - 1) * hop_s + frame_s
            if (
                silence_end - silence_start >= min_silence_s
                and (max_start_s is None or silence_start <= max_start_s)
                and (best is None or silence_end - silence_start > best[1] - best[0])
            ):
                best = (silence_start, silence_end)
            run_start = None
    return best


def smooth_word_timestamps(
    segments: list[SegmentInfo],
    max_stretch_s: float | None = None,
    audio_data=None,
    sample_rate: int = 16000,
    min_silence_ms: int = 200,
    pad_ms: int = 100,
    bridge_unsplit_gaps: bool = False,
) -> None:
    """Extends final word timestamps to acoustic speech boundaries in-place."""
    if not segments:
        return

    try:
        from config import ENABLE_WORD_SMOOTHING, WORD_SMOOTHING_MAX_STRETCH_S
    except ImportError:
        ENABLE_WORD_SMOOTHING = True
        WORD_SMOOTHING_MAX_STRETCH_S = 1.0

    if not ENABLE_WORD_SMOOTHING:
        return

    if max_stretch_s is None:
        max_stretch_s = WORD_SMOOTHING_MAX_STRETCH_S

    if audio_data is not None:
        import librosa

        if isinstance(audio_data, str):
            audio, _ = librosa.load(audio_data, sr=sample_rate, mono=True)
        else:
            audio = np.asarray(audio_data, dtype=np.float32)

        if len(audio) > 0:
            rms = librosa.feature.rms(y=audio, frame_length=1024, hop_length=512)[0]
            rms_db = 20.0 * np.log10(np.maximum(rms, 1e-8))
            silence_threshold_db = float(
                np.clip(np.percentile(rms_db, 75) - 15.0, -45.0, -30.0)
            )
            min_silence_s = min_silence_ms / 1000.0
            boundary_pad_s = max(pad_ms / 1000.0, min(0.2, min_silence_s))
            audio_duration_s = len(audio) / sample_rate
            start_updates: list[float | None] = [None] * len(segments)
            end_updates: list[float | None] = [None] * len(segments)

            for index, seg in enumerate(segments):
                if not seg.words:
                    continue
                last_end = seg.words[-1].get("end")
                if last_end is None:
                    continue
                last_word_end = seg.start_time + last_end

                next_word_start = None
                if index + 1 < len(segments) and segments[index + 1].words:
                    next_seg = segments[index + 1]
                    first_start = next_seg.words[0].get("start")
                    if first_start is not None:
                        next_word_start = next_seg.start_time + first_start

                search_end = min(
                    audio_duration_s,
                    (next_word_start if next_word_start is not None else last_word_end + max_stretch_s)
                    + 0.35,
                )
                silence = _find_sustained_silence(
                    audio,
                    sample_rate,
                    last_word_end,
                    search_end,
                    min_silence_s,
                    silence_threshold_db,
                    max_start_s=(next_word_start + 0.1) if next_word_start is not None else None,
                )
                if silence is None:
                    if (
                        bridge_unsplit_gaps
                        and next_word_start is not None
                        and next_word_start - last_word_end <= 3.0
                    ):
                        end_updates[index] = max(
                            last_word_end,
                            next_word_start - 0.001,
                        )
                    continue

                silence_start, silence_end = silence
                if next_word_start is None:
                    end_updates[index] = min(silence_start + boundary_pad_s, audio_duration_s)
                    continue

                midpoint = (silence_start + silence_end) / 2.0
                end_updates[index] = min(silence_start + boundary_pad_s, midpoint)
                start_updates[index + 1] = max(silence_end - boundary_pad_s, midpoint)

            for index, seg in enumerate(segments):
                if start_updates[index] is not None:
                    seg.start_time = round(start_updates[index], 3)
                if end_updates[index] is not None:
                    seg.end_time = round(end_updates[index], 3)

    for seg in segments:
        if not seg.words or seg.start_time is None or seg.end_time is None:
            continue

        num_words = len(seg.words)

        for i in range(num_words):
            w = seg.words[i]
            orig_end = w.get("end")
            if orig_end is None:
                continue

            if i + 1 < num_words:
                next_start = seg.words[i + 1].get("start")
                next_bound_rel = next_start if next_start is not None else orig_end + max_stretch_s
            else:
                next_bound_rel = max(orig_end, seg.end_time - seg.start_time)

            stretched_end = min(orig_end + max_stretch_s, next_bound_rel)
            new_end = max(orig_end, stretched_end)
            w["end"] = round(new_end, 4)


