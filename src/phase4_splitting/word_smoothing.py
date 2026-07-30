"""
Word Timestamp Smoothing / Gap Extension.

Extends the end time of each word in a segment by up to max_stretch_s (default 1.0s)
into the silent gap following it.

Rules:
1. Word 'start' times remain 100% pure and untouched (from CTC forced alignment).
2. For word i within a segment, new_end = min(orig_end + max_stretch_s, next_word_start).
   This guarantees zero overlap with the next word's start time.
3. For the LAST word in a segment, it looks ahead to the first word of the NEXT segment:
   next_bound_abs = next_seg.start_time + next_seg.words[0].start
   new_end_rel = min(orig_end + max_stretch_s, next_bound_abs - seg.start_time)
   The segment's end_time (time_to) is updated accordingly so segment boundaries match.
"""
from __future__ import annotations
from src.core.segment_types import SegmentInfo


def smooth_word_timestamps(segments: list[SegmentInfo], max_stretch_s: float | None = None) -> None:
    """
    In-place extension of word 'end' timestamps across all segments.

    Args:
        segments: List of SegmentInfo objects.
        max_stretch_s: Maximum seconds to extend word end into silence (default from config.py).
    """
    if not segments:
        return

    try:
        from config import ENABLE_WORD_SMOOTHING, WORD_SMOOTHING_MAX_STRETCH_S
    except ImportError:
        ENABLE_WORD_SMOOTHING = True
        WORD_SMOOTHING_MAX_STRETCH_S = 1.0

    if not ENABLE_WORD_SMOOTHING:
        print("[WORD_SMOOTH] Word timestamp smoothing is disabled in config.py.")
        return

    if max_stretch_s is None:
        max_stretch_s = WORD_SMOOTHING_MAX_STRETCH_S

    n_words_smoothed = 0
    total_segs = len(segments)

    for seg_idx, seg in enumerate(segments):
        if not seg.words or seg.start_time is None or seg.end_time is None:
            continue

        num_words = len(seg.words)

        for i in range(num_words):
            w = seg.words[i]
            orig_end = w.get("end")
            if orig_end is None:
                continue

            # Determine upper bound for extension
            if i + 1 < num_words:
                # Intra-segment: next word in same segment
                next_start = seg.words[i + 1].get("start")
                if next_start is not None:
                    next_bound_rel = next_start
                else:
                    next_bound_rel = orig_end + max_stretch_s
            else:
                # Inter-segment: last word in segment — look ahead to next segment's first word
                next_bound_rel = orig_end + max_stretch_s  # default if no next segment
                for next_idx in range(seg_idx + 1, total_segs):
                    next_seg = segments[next_idx]
                    if next_seg.words and next_seg.start_time is not None:
                        first_word_start = next_seg.words[0].get("start", 0.0)
                        abs_next_start = next_seg.start_time + first_word_start
                        next_bound_rel = abs_next_start - seg.start_time
                        break

            # Calculate stretched end time (up to +max_stretch_s, capped at next_bound_rel)
            stretched_end = min(orig_end + max_stretch_s, next_bound_rel)
            new_end = max(orig_end, stretched_end)
            w["end"] = round(new_end, 4)
            n_words_smoothed += 1

            # For the last word of the segment, extend segment end_time if word stretched past it
            if i == num_words - 1:
                new_abs_end = round(seg.start_time + new_end, 3)
                if new_abs_end > seg.end_time:
                    seg.end_time = new_abs_end

    print(f"[WORD_SMOOTH] Smoothed timestamps for {n_words_smoothed} words across {total_segs} segments (max_stretch={max_stretch_s}s).")
