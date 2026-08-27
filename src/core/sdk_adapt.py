"""Adapters between qua_sdk schemas and application data structures."""

from __future__ import annotations
from qua_sdk.schemas import Alignment, Emissions, Regions
from src.core.segment_types import ProfilingData, SegmentInfo, compute_reading_sequence


def alignment_to_segment_infos(
    alignment: Alignment,
    emissions: Emissions,
    regions: Regions,
) -> list[SegmentInfo]:
    """Maps SDK Alignment output onto SegmentInfo list."""
    tokens = emissions.tokens
    segments: list[SegmentInfo] = []

    for seg in alignment.segments:
        if seg.merged_into is not None:
            continue

        matched_ref = seg.matched_ref or ""
        phoneme_text = " ".join(tokens[seg.id]) if seg.id < len(tokens) else ""
        wrap_ranges = seg.wrap_word_ranges
        rep_ranges, rep_text = derive_repetition(matched_ref, wrap_ranges)

        info = SegmentInfo(
            start_time=seg.region.start_s,
            end_time=seg.region.end_s,
            transcribed_text=phoneme_text,
            matched_text=seg.matched_text,
            matched_ref=matched_ref,
            match_score=seg.confidence,
            error=seg.error,
            has_missing_words=False,
            has_repeated_words=bool(wrap_ranges),
            wrap_word_ranges=wrap_ranges,
            repeated_ranges=rep_ranges,
            repeated_text=rep_text,
            _original_alignment_idx=seg.id + 1,
        )
        segments.append(info)

    return segments


def derive_repetition(matched_ref: str, wrap_ranges) -> tuple[list | None, list | None]:
    """Derives reading sequence ranges and repeated texts."""
    if not (wrap_ranges and matched_ref and "-" in matched_ref):
        return None, None
    from src.core.quran_index import get_quran_index

    ref_from, ref_to = matched_ref.split("-", 1)
    rep_ranges = compute_reading_sequence(ref_from, ref_to, wrap_ranges)
    qi = get_quran_index()
    rep_text = []
    for sec_from, sec_to in rep_ranges:
        indices = qi.ref_to_indices(f"{sec_from}-{sec_to}")
        if indices:
            s_i, e_i = indices
            rep_text.append(" ".join(w.text for w in qi.words[s_i:e_i + 1]))
        else:
            rep_text.append("")
    return rep_ranges, rep_text


def intervals_from_regions(regions: Regions) -> list[tuple[float, float]]:
    """Regions -> list of (start_s, end_s) tuples."""
    return [(r.start_s, r.end_s) for r in regions.regions]


def metrics_to_profiling(stages: dict, profiling: ProfilingData) -> None:
    """Populates ProfilingData from per-stage metrics."""
    rec = _metrics(stages.get("recognition"))
    if rec:
        profiling.asr_sorting_time = rec.get("sorting_s", 0.0)
        profiling.asr_batch_build_time = rec.get("batch_build_s", 0.0)
        profiling.asr_model_move_time = rec.get("model_move_s", 0.0)
        profiling.asr_batch_profiling = rec.get("batches") or []

    match = _metrics(stages.get("matching"))
    if match:
        profiling.retry_attempts = match.get("retry_attempts", 0)
        profiling.retry_passed = match.get("retry_passed", 0)
        profiling.retry_segments = match.get("retry_segments", [])
        profiling.consec_reanchors = match.get("consec_reanchors", 0)
        profiling.segments_attempted = match.get("segments_attempted", 0)
        profiling.segments_passed = match.get("segments_passed", 0)
        profiling.special_merges = match.get("special_merges", 0)
        profiling.transition_skips = match.get("transition_skips", 0)
        profiling.phoneme_wraps_detected = match.get("phoneme_wraps_detected", 0)
        wall = _wall_s(stages.get("matching"))
        if wall is not None:
            profiling.phoneme_total_time = wall


def _metrics(stage) -> dict | None:
    if stage is None:
        return None
    return stage.metrics if hasattr(stage, "metrics") else dict(stage)


def _wall_s(stage) -> float | None:
    return getattr(stage, "wall_s", None) if stage is not None else None
