"""Surface the SDK's waqf-sakt auto-merge as an app merge group.

The qua_sdk matcher heals a verse the VAD split at an obligatory sakt point
(75:27 / 83:14, see qua_sdk.domain.sakt): the earlier segment becomes the
merge target (combined ref, region extended, confidence 1.0) and the consumed
row stays in the Alignment with ``merged_into`` + ``merge_reason="waqf_sakt"``,
keeping its own pre-merge match. This module reconstructs the two pre-merge
halves and stamps the merged SegmentInfo with the same ``merge_group_id`` +
``merge_members`` machinery user merges use (src/ui/segment_splitter.py), so
the card renders as an "Auto-merged" group and "Undo merge" restores the
halves. Tahmeed merges (``merge_reason="tahmeed"``) stay silently absorbed.
Wired in by ``src/core/sdk_adapt.alignment_to_segment_infos``.
"""

from __future__ import annotations

import uuid

from qua_sdk.schemas import AlignedSegment, Alignment, Regions

from config import AUTO_MERGE_GROUP_PREFIX
from src.core.segment_types import SegmentInfo


def waqf_sakt_consumed_by_target(alignment: Alignment) -> dict[int, AlignedSegment]:
    """Map target segment id → its waqf-sakt consumed row.

    ``getattr`` guards against older qua_sdk wheels whose AlignedSegment has no
    ``merge_reason`` — there every merge is tahmeed and nothing is surfaced.
    """
    out: dict[int, AlignedSegment] = {}
    for seg in alignment.segments:
        if seg.merged_into is None:
            continue
        if getattr(seg, "merge_reason", None) == "waqf_sakt":
            out[seg.merged_into] = seg
    return out


def stamp_auto_merge_group(info: SegmentInfo, target: AlignedSegment,
                           consumed: AlignedSegment, regions: Regions) -> None:
    """Stamp the merged card with an auto merge group, in place.

    ``info`` is the SegmentInfo built from the (already-merged) ``target`` row.
    Members are the two reconstructed pre-merge halves as to_json_dict dicts —
    the exact shape undo_merge_group restores from. If the halves cannot be
    reconstructed (malformed refs), the card is left as a plain merged segment.
    """
    member_a = _target_half(info, target, consumed, regions)
    if member_a is None:
        return
    member_b = _consumed_half(consumed)
    info.merge_group_id = f"{AUTO_MERGE_GROUP_PREFIX}{uuid.uuid4().hex[:8]}"
    info.merge_members = [member_a.to_json_dict(), member_b.to_json_dict()]


def _target_half(info: SegmentInfo, target: AlignedSegment,
                 consumed: AlignedSegment, regions: Regions) -> SegmentInfo | None:
    """Reconstruct the pre-merge first half from the mutated target row.

    Its ref runs from the combined ref's start to the word before the consumed
    ref's start (the sakt point sits inside one verse, so same surah:ayah).
    Its region end is the target's INPUT region end — the merge extended the
    target's region over the consumed one. The target's pre-merge confidence is
    not recoverable, so the merged 1.0 is kept.
    """
    a_ref = _ref_before_consumed(target.matched_ref or "", consumed.matched_ref or "")
    if a_ref is None:
        return None

    if target.id < len(regions.regions):
        end_s = regions.regions[target.id].end_s
    else:
        end_s = consumed.region.start_s

    return SegmentInfo(
        start_time=target.region.start_s,
        end_time=end_s,
        transcribed_text="",
        matched_text=_text_without_consumed_suffix(
            info.matched_text or "", consumed.matched_text or "", a_ref),
        matched_ref=a_ref,
        match_score=info.match_score,
    )


def _consumed_half(consumed: AlignedSegment) -> SegmentInfo:
    """Build the second half straight from the consumed row — it kept everything."""
    from src.core.sdk_adapt import derive_repetition

    ref = consumed.matched_ref or ""
    wrap_ranges = consumed.wrap_word_ranges
    rep_ranges, rep_text = derive_repetition(ref, wrap_ranges)
    return SegmentInfo(
        start_time=consumed.region.start_s,
        end_time=consumed.region.end_s,
        transcribed_text="",
        matched_text=consumed.matched_text,
        matched_ref=ref,
        match_score=consumed.confidence,
        has_repeated_words=bool(wrap_ranges),
        wrap_word_ranges=wrap_ranges,
        repeated_ranges=rep_ranges,
        repeated_text=rep_text,
    )


def _ref_before_consumed(target_ref: str, consumed_ref: str) -> str | None:
    """First-half ref: target span start .. word before the consumed span start."""
    start = target_ref.split("-")[0]
    consumed_start = consumed_ref.split("-")[0]
    parts = consumed_start.split(":")
    if not start or len(parts) != 3:
        return None
    try:
        surah, ayah, word = (int(p) for p in parts)
    except ValueError:
        return None
    if word < 2:
        return None
    prev_loc = f"{surah}:{ayah}:{word - 1}"
    return prev_loc if start == prev_loc else f"{start}-{prev_loc}"


def _text_without_consumed_suffix(merged_text: str, consumed_text: str,
                                  a_ref: str) -> str:
    """First-half display text: strip the consumed half off the merged concat.

    Falls back to rebuilding from the quran index when the concat doesn't end
    with the consumed text verbatim.
    """
    if consumed_text and merged_text.endswith(consumed_text):
        return merged_text[: len(merged_text) - len(consumed_text)].rstrip()

    from src.core.quran_index import get_quran_index
    qi = get_quran_index()
    indices = qi.ref_to_indices(a_ref)
    if not indices:
        return merged_text
    s_i, e_i = indices
    return " ".join(w.display_text for w in qi.words[s_i:e_i + 1])
