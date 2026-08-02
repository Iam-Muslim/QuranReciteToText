"""Segment Deduplication — Eliminate VAD Chunk Overlap/Fragment Artifacts.

Two types of VAD padding artifacts can appear in the output:

1. OVERLAP ARTIFACT (original problem):
   When two adjacent chunks share overlapping audio (padding > gap/2),
   FastConformer transcribes boundary words twice.  The aligner produces a
   "phantom" segment whose absolute time OVERLAPS the preceding segment
   AND whose Quran ref is a strict subset of that segment's ref.
   Detection: nxt.start_time < current.end_time  AND  ref subset.

2. TRAILING FRAGMENT (new, after gap-clamped padding):
   After Fix 1 (gap-clamped padding) the audio no longer overlaps, but the
   VAD silence cut happens at the very end of (or mid-) the last word of
   chunk N.  Chunk N+1 starts at exactly the same sample, so its first
   transcribed word is the tail of the same word already in chunk N.
   This creates an adjacent (not overlapping) segment with 1–2 words whose
   locations are already in the previous segment, and a negligible or zero
   gap between the segments.
   Detection: |nxt.start_time - current.end_time| <= ADJACENT_GAP_THRESH
              AND nxt's ref locations are all already covered by current.

Both artifact types must be removed while preserving GENUINE reciter
repetitions:
  - Real repeats advance forward in time and the SDK sets wrap_word_ranges.
  - The matched_ref of a real repeat starts BEFORE the repeated section, so
    it is NOT a simple suffix/subset of the previous segment's ref.
"""

from __future__ import annotations
from src.core.segment_types import SegmentInfo

# A next segment is "adjacent" (touching, not overlapping) when the gap
# between its start and the current segment's end is within this threshold.
# 50 ms covers timestamp rounding noise while staying well below any real
# silence that would indicate a new sentence.
ADJACENT_GAP_THRESH_S = 0.05  # 50 ms


def _parse_ref(ref: str) -> tuple[str, str] | None:
    """Return (ref_from, ref_to) for 'S:A:W' or 'S:A:W1-S:A:W2'."""
    if not ref or ":" not in ref:
        return None
    parts = ref.split("-", 1)
    return parts[0], parts[-1]


def _loc_tuple(loc: str) -> tuple[int, int, int] | None:
    """Parse 'S:A:W' location into (surah, ayah, word) ints."""
    try:
        s, a, w = loc.split(":")
        return int(s), int(a), int(w)
    except (ValueError, AttributeError):
        return None


def _ref_is_subset_of(inner_ref: str, outer_ref: str) -> bool:
    """True if inner_ref's word range is contained within outer_ref's range."""
    inner = _parse_ref(inner_ref)
    outer = _parse_ref(outer_ref)
    if not inner or not outer:
        return False
    i_from = _loc_tuple(inner[0])
    i_to   = _loc_tuple(inner[1])
    o_from = _loc_tuple(outer[0])
    o_to   = _loc_tuple(outer[1])
    if not all([i_from, i_to, o_from, o_to]):
        return False
    # Must be same surah for this to be a simple padding artifact
    if i_from[0] != o_from[0]:
        return False
    return o_from <= i_from and i_to <= o_to


def _is_genuine_repeat(seg: SegmentInfo) -> bool:
    """A segment is a genuine reciter repetition when the SDK said so."""
    return bool(seg.has_repeated_words or seg.wrap_word_ranges)


def _trailing_fragment(current: SegmentInfo, nxt: SegmentInfo) -> bool:
    """True when nxt is a trailing single-word fragment of current.

    Conditions:
    1. The segments are adjacent or touching (gap <= ADJACENT_GAP_THRESH_S).
    2. nxt contains 1 or 2 words.
    3. ALL of nxt's word locations are already present in current's words.
    4. Neither segment is a genuine reciter repetition.
    """
    gap = nxt.start_time - current.end_time

    # DEBUG: trace any close pair
    if abs(gap) <= 0.1:
        curr_ref = current.matched_ref or ''
        nxt_ref  = nxt.matched_ref or ''
        nxt_words = nxt.words or []
        curr_words = current.words or []
        curr_locs = {w.get("location") for w in curr_words if w.get("location")}
        nxt_locs  = {w.get("location") for w in nxt_words if w.get("location")}
        print(f"[DEDUP-TRACE] gap={gap:.4f} curr={curr_ref!r}({len(curr_words)}w) "
              f"nxt={nxt_ref!r}({len(nxt_words)}w) "
              f"nxt_locs={nxt_locs} subset={nxt_locs <= curr_locs if nxt_locs else 'N/A'} "
              f"curr_genuine={_is_genuine_repeat(current)} nxt_genuine={_is_genuine_repeat(nxt)}")

    if gap > ADJACENT_GAP_THRESH_S or gap < -ADJACENT_GAP_THRESH_S:
        return False  # not adjacent

    if _is_genuine_repeat(current) or _is_genuine_repeat(nxt):
        return False

    nxt_words = nxt.words or []
    # Only handle short fragments (1–2 words)
    if not nxt_words or len(nxt_words) > 2:
        return False

    # Collect all word locations already in current
    curr_locs = {w.get("location") for w in (current.words or []) if w.get("location")}
    nxt_locs  = {w.get("location") for w in nxt_words if w.get("location")}

    if not nxt_locs:
        return False

    # Fragment if ALL of nxt's locations are already in current
    return nxt_locs <= curr_locs


def dedup_vad_overlaps(segments: list[SegmentInfo]) -> list[SegmentInfo]:
    """Remove phantom duplicate/fragment segments from VAD chunk padding.

    Two cases are handled (see module docstring):
    1. Overlap artifacts  — next segment starts before current ends,
                            ref is a subset.
    2. Trailing fragments — next segment touches (gap ≈ 0) with 1–2 words
                            already present in the current segment.

    Genuine reciter repetitions (wrap_word_ranges / has_repeated_words) are
    never removed.

    Returns a deduplicated list with segment end-times extended to cover any
    absorbed fragments.
    """
    if not segments:
        return segments

    try:
        from qua_sdk.domain import SPECIAL_NAMES as _SPECIALS
    except Exception:
        _SPECIALS = set()

    result: list[SegmentInfo] = []
    n_removed = 0
    current = segments[0]

    for nxt in segments[1:]:
        curr_is_special = getattr(current, "matched_ref", None) in _SPECIALS
        nxt_is_special  = getattr(nxt,     "matched_ref", None) in _SPECIALS
        if curr_is_special or nxt_is_special:
            result.append(current)
            current = nxt
            continue

        curr_ref = current.matched_ref or ""
        nxt_ref  = nxt.matched_ref     or ""

        # ── Case 1: Overlap artifact ─────────────────────────────────────
        time_overlaps = nxt.start_time < current.end_time - 0.001  # 1ms tolerance
        if time_overlaps:
            nxt_is_subset  = _ref_is_subset_of(nxt_ref,  curr_ref)
            curr_is_subset = (not nxt_is_subset) and _ref_is_subset_of(curr_ref, nxt_ref)
            curr_genuine   = _is_genuine_repeat(current)
            nxt_genuine    = _is_genuine_repeat(nxt)

            if nxt_is_subset and not nxt_genuine and not curr_genuine:
                new_end = max(current.end_time, nxt.end_time)
                current = _extend_end(current, new_end)
                n_removed += 1
                print(
                    f"[DEDUP] Overlap artifact dropped: ref={nxt_ref!r} "
                    f"⊂ {curr_ref!r}, overlap={current.end_time - nxt.start_time:.3f}s"
                )
                continue

            if curr_is_subset and not curr_genuine and not nxt_genuine:
                n_removed += 1
                print(
                    f"[DEDUP] Overlap artifact dropped (reversed): ref={curr_ref!r} "
                    f"⊂ {nxt_ref!r}"
                )
                current = nxt
                continue

        # ── Case 2: Trailing fragment ────────────────────────────────────
        if _trailing_fragment(current, nxt):
            new_end = max(current.end_time, nxt.end_time)
            current = _extend_end(current, new_end)
            n_removed += 1
            print(
                f"[DEDUP] Trailing fragment dropped: ref={nxt_ref!r} "
                f"(already in {curr_ref!r}), gap={nxt.start_time - (new_end - nxt.end_time + current.end_time):.3f}s"
            )
            continue

        result.append(current)
        current = nxt

    result.append(current)

    if n_removed:
        print(f"[DEDUP] Removed {n_removed} VAD-artifact segment(s).")
    else:
        print("[DEDUP] No VAD-overlap duplicates found.")

    return result


def _extend_end(seg: SegmentInfo, new_end: float) -> SegmentInfo:
    """Return a copy of seg with end_time extended to new_end."""
    return SegmentInfo(
        start_time=seg.start_time,
        end_time=new_end,
        transcribed_text=seg.transcribed_text,
        matched_text=seg.matched_text,
        matched_ref=seg.matched_ref,
        match_score=seg.match_score,
        error=seg.error,
        has_missing_words=seg.has_missing_words,
        has_repeated_words=seg.has_repeated_words,
        wrap_word_ranges=seg.wrap_word_ranges,
        repeated_ranges=seg.repeated_ranges,
        repeated_text=seg.repeated_text,
        words=seg.words,
        _original_alignment_idx=seg._original_alignment_idx,
    )
