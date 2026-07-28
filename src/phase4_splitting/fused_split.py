"""MFA-based splitting of combined/fused special segments (Isti\'adha/Basmala)."""
from src.core.segment_types import SegmentInfo


def _split_fused_segments(segments):
    """Post-processing: split combined/fused segments into separate ones via MFA.

    Scans for:
    - Combined "Isti'adha+Basmala" specials → split into Isti'adha + Basmala
    - Fused Basmala+verse → split into Basmala + verse
    - Fused Isti'adha+verse → split into Isti'adha + verse

    Uses MFA word timestamps to find accurate split boundaries.
    On MFA failure: midpoint fallback for combined, keep-as-is for fused.

    Args:
        segments: List of SegmentInfo objects.
        audio_int16: Full recording as int16 numpy array.
        sample_rate: Audio sample rate.

    Returns:
        New list of SegmentInfo objects with splits applied.
    """
    from qua_sdk.domain import SPECIAL_TEXT, SPECIAL_NAMES as ALL_SPECIAL_REFS

    _BASMALA_TEXT = SPECIAL_TEXT["Basmala"]
    _ISTIATHA_TEXT = SPECIAL_TEXT["Isti'adha"]
    _COMBINED_TEXT = _ISTIATHA_TEXT + " ۝ " + _BASMALA_TEXT

    # Number of words in each special
    _ISTIATHA_WORD_COUNT = len(_ISTIATHA_TEXT.split())  # 5
    _BASMALA_WORD_COUNT = len(_BASMALA_TEXT.split())     # 4

    # Identify segments that need splitting
    split_indices = []  # (idx, case, mfa_ref, split_info)
    for idx, seg in enumerate(segments):
        if seg.matched_ref == "Isti'adha+Basmala":
            # Combined special — always split
            split_indices.append((idx, "combined", "Isti'adha+Basmala", None))
        elif seg.matched_ref and seg.matched_ref not in ALL_SPECIAL_REFS and seg.matched_text:
            if seg.matched_text.startswith(_COMBINED_TEXT):
                # Fused Isti'adha+Basmala+verse
                split_indices.append((idx, "fused_combined", f"Isti'adha+Basmala+{seg.matched_ref}", seg.matched_ref))
            elif seg.matched_text.startswith(_ISTIATHA_TEXT):
                # Fused Isti'adha+verse
                split_indices.append((idx, "fused_istiatha", f"Isti'adha+{seg.matched_ref}", seg.matched_ref))
            elif seg.matched_text.startswith(_BASMALA_TEXT):
                # Fused Basmala+verse
                split_indices.append((idx, "fused_basmala", f"Basmala+{seg.matched_ref}", seg.matched_ref))

    if not split_indices:
        return segments

    print(f"[MFA_SPLIT] {len(split_indices)} segments to split: "
          f"{[(i, c) for i, c, _, _ in split_indices]}")

    # In this pipeline, CTC alignment (Phase 3) has already populated seg.words
    # with timestamps, so we don't need to call MFA. We just use seg.words.

    # Build new segment list with splits
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
            # MFA failed — fallback
            if case == "combined":
                # Midpoint fallback for combined
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
                print(f"[MFA_SPLIT] Segment {idx}: combined fallback to midpoint split")
            else:
                # Keep fused as-is when MFA fails
                new_segments.append(seg)
                print(f"[MFA_SPLIT] Segment {idx}: fused fallback, keeping as-is")
            continue

        # Find split boundaries from MFA word timestamps
        seg_start = seg.start_time

        if case == "combined":
            # Split after Isti'adha words (0:0:1..0:0:5), Basmala starts at 0:0:6
            istiatha_end = None
            for w in words:
                loc = w.get("location", "")
                if loc == f"0:0:{_ISTIATHA_WORD_COUNT}":
                    istiatha_end = seg_start + w["end"]
                    break
            if istiatha_end is None:
                # Fallback: midpoint
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
            print(f"[MFA_SPLIT] Segment {idx}: combined split at {istiatha_end:.3f}s")

        elif case == "fused_combined":
            # Isti'adha (0:0:1..5) + Basmala (0:0:6..9) + verse
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

            # Strip prefix text from matched_text to get verse text
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
            print(f"[MFA_SPLIT] Segment {idx}: fused_combined split at "
                  f"{istiatha_end:.3f}s / {basmala_end:.3f}s")

        elif case == "fused_istiatha":
            # Isti'adha (0:0:1..5) + verse
            istiatha_end = None
            for w in words:
                loc = w.get("location", "")
                if loc == f"0:0:{_ISTIATHA_WORD_COUNT}":
                    istiatha_end = seg_start + w["end"]
                    break
            if istiatha_end is None:
                # Keep as-is if we can't find the boundary
                new_segments.append(seg)
                print(f"[MFA_SPLIT] Segment {idx}: fused_istiatha boundary not found, keeping as-is")
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
            print(f"[MFA_SPLIT] Segment {idx}: fused_istiatha split at {istiatha_end:.3f}s")

        elif case == "fused_basmala":
            # Basmala (0:0:1..4) + verse
            basmala_end = None
            for w in words:
                loc = w.get("location", "")
                if loc == f"0:0:{_BASMALA_WORD_COUNT}":
                    basmala_end = seg_start + w["end"]
                    break
            if basmala_end is None:
                new_segments.append(seg)
                print(f"[MFA_SPLIT] Segment {idx}: fused_basmala boundary not found, keeping as-is")
                continue

            verse_text = seg.matched_text
            if verse_text.startswith(_BASMALA_TEXT):
                verse_text = verse_text[len(_BASMALA_TEXT):].lstrip()

            new_segments.append(SegmentInfo(
                start_time=seg.start_time, end_time=basmala_end,
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
            print(f"[MFA_SPLIT] Segment {idx}: fused_basmala split at {basmala_end:.3f}s")

    print(f"[MFA_SPLIT] {len(segments)} segments → {len(new_segments)} segments")
    return new_segments
