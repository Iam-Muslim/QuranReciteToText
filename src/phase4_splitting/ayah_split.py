"""Ayah-Level Splitting via CTC Word Timestamps."""
from __future__ import annotations
from src.core.segment_types import SegmentInfo


def _ayah_key_and_word(location):
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


def split_segments_at_ayah_boundaries(segments):
    """Split every multi-ayah or multi-reading segment into individual per-ayah segments.

    Uses seg.words (populated by CTC alignment) to find ayah boundaries & repeats.
    Special segments or segments without word timestamps pass through.
    """
    from qua_sdk.domain import SPECIAL_NAMES as ALL_SPECIAL_REFS
    result = []
    n_split = 0

    for seg in segments:
        # Pass through specials or segments without words
        if (
            seg.matched_ref in ALL_SPECIAL_REFS
            or not seg.words
        ):
            result.append(seg)
            continue

        # Group words by (surah:ayah) and detect repeated readings (word index reset)
        groups = []
        prev_key = None
        prev_word_num = None

        for w in seg.words:
            key, word_num = _ayah_key_and_word(w.get("location"))

            is_new = False
            if not groups:
                is_new = True
            elif key != prev_key and key is not None:
                is_new = True
            elif word_num is not None and prev_word_num is not None and word_num <= prev_word_num:
                is_new = True  # Repeat detected (e.g. 52:7:4 -> 52:7:1)

            if is_new:
                groups.append([key, [w]])
            else:
                groups[-1][1].append(w)

            if key is not None:
                prev_key = key
            if word_num is not None:
                prev_word_num = word_num

        # Only one ayah group - no split needed
        if len(groups) <= 1:
            result.append(seg)
            continue

        n_split += 1
        seg_start = seg.start_time

        for g_idx, (ayah_key, words) in enumerate(groups):
            is_first = (g_idx == 0)
            is_last  = (g_idx == len(groups) - 1)

            first_rel_start = words[0].get("start")
            last_rel_end    = words[-1].get("end")

            # Compute absolute start
            if is_first:
                abs_start = seg.start_time
            elif first_rel_start is not None:
                abs_start = seg_start + first_rel_start
            else:
                abs_start = result[-1].end_time

            # Compute absolute end
            if last_rel_end is not None:
                abs_end_word = seg_start + last_rel_end
            else:
                abs_end_word = abs_start + 0.04

            if is_last:
                abs_end = seg.end_time
            else:
                next_words = groups[g_idx + 1][1]
                next_rel_start = next_words[0].get("start")
                if next_rel_start is not None:
                    next_abs_start = seg_start + next_rel_start
                    abs_end = (abs_end_word + next_abs_start) / 2.0
                else:
                    abs_end = abs_end_word

            abs_start = round(abs_start, 3)
            abs_end   = round(abs_end,   3)
            if abs_end <= abs_start:
                abs_end = abs_start + 0.04

            # Build matched_ref from word locations
            locs = [w.get("location") for w in words if w.get("location")]
            if locs:
                ref_from = locs[0]
                ref_to   = locs[-1]
                matched_ref = ref_from if ref_from == ref_to else f"{ref_from}-{ref_to}"
            else:
                matched_ref = seg.matched_ref

            matched_text = " ".join(w.get("word", "") for w in words)

            # Rebuild relative word timestamps for this sub-segment
            offset = abs_start - seg_start
            sub_words = []
            for w in words:
                entry = dict(w)
                if entry.get("start") is not None:
                    entry["start"] = round(max(0.0, entry["start"] - offset), 4)
                if entry.get("end") is not None:
                    entry["end"]   = round(max(0.0, entry["end"]   - offset), 4)
                sub_words.append(entry)

            sub_seg = SegmentInfo(
                start_time=abs_start,
                end_time=abs_end,
                transcribed_text=seg.transcribed_text,
                matched_text=matched_text,
                matched_ref=matched_ref,
                match_score=seg.match_score,
                error=seg.error,
                has_missing_words=False,  # recomputed later by recompute_missing_words
                has_repeated_words=False,
                words=sub_words,
                _original_alignment_idx=seg._original_alignment_idx,
            )
            result.append(sub_seg)

        print(f"[AYAH_SPLIT] Segment split into {len(groups)} ayahs ({seg.matched_ref})")

    if n_split:
        print(f"[AYAH_SPLIT] {len(segments)} segments -> {len(result)} segments ({n_split} splits)")
    else:
        print("[AYAH_SPLIT] No multi-ayah segments - no splits needed.")

    return result
