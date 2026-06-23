"""Adapters between qua_sdk schemas and the app's legacy shapes.

The SDK speaks Audio/Regions/Emissions/Alignment/Timings; the app's UI,
renderer, API responses, saved sessions, and telemetry all speak SegmentInfo,
ProfilingData, and plain gr.State tuples. Everything that crosses that seam
goes through here so the rest of the app stays untouched.

Joins are by ``AlignedSegment.id`` (== input region index, stamped into
``SegmentInfo._original_alignment_idx + 1``), never by list position — merges
keep consumed rows in the Alignment and those are never emitted as cards.
Tahmeed merges are silently absorbed; waqf-sakt merges are surfaced as
"Auto-merged" groups via ``src/core/auto_merge.py``.
"""

from __future__ import annotations

import numpy as np

from qua_sdk.schemas import Alignment, Emissions, Region, Regions, Timings

from src.core.auto_merge import stamp_auto_merge_group, waqf_sakt_consumed_by_target
from src.core.segment_types import ProfilingData, SegmentInfo, compute_reading_sequence

SAMPLE_RATE = 16_000


# ---------------------------------------------------------------------------
# Alignment → SegmentInfo
# ---------------------------------------------------------------------------

def alignment_to_segment_infos(
    alignment: Alignment,
    emissions: Emissions,
    regions: Regions,
) -> list[SegmentInfo]:
    """Map an SDK Alignment onto the legacy SegmentInfo list.

    Mirrors the legacy result builder: consumed (merged) rows are never
    emitted as cards — the SDK already extended the target's region end. A
    waqf-sakt merge target additionally gets an "Auto-merged" group stamped
    (see auto_merge.py) so the user can see and undo the pipeline's merge.
    The non-verse-final penalty and the low-confidence error/blanking are
    applied by the SDK matcher; they are NOT re-applied here.
    """
    tokens = emissions.tokens
    auto_merged = waqf_sakt_consumed_by_target(alignment)
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
            # has_missing_words is derived later by recompute_missing_words
            # (the single coverage-based authority), not from the matcher.
            has_missing_words=False,
            has_repeated_words=bool(wrap_ranges),
            wrap_word_ranges=wrap_ranges,
            repeated_ranges=rep_ranges,
            repeated_text=rep_text,
            # DebugCollector/log rows key per-segment entries by 1-indexed
            # absolute region position (== AlignedSegment.id + 1).
            _original_alignment_idx=seg.id + 1,
        )
        consumed = auto_merged.get(seg.id)
        if consumed is not None:
            stamp_auto_merge_group(info, seg, consumed, regions)
        segments.append(info)

    return segments


def derive_repetition(matched_ref: str, wrap_ranges) -> tuple[list | None, list | None]:
    """Reading-sequence ranges + display texts for a repetition segment.

    Uses the app's quran index (digital-khatt display script) so the rendered
    repeated_text matches what every other card shows.
    """
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
            rep_text.append(" ".join(w.display_text for w in qi.words[s_i:e_i + 1]))
        else:
            rep_text.append("")
    return rep_ranges, rep_text


# ---------------------------------------------------------------------------
# Timings → SegmentInfo.words
# ---------------------------------------------------------------------------

def timings_to_words(timings: Timings, segment_infos: list[SegmentInfo]) -> None:
    """Attach SDK word timings onto ``SegmentInfo.words`` dicts in place.

    Joined by segment id via ``_original_alignment_idx`` (id + 1). Segments
    whose backend run failed (``words=None``) are left untouched.
    """
    by_id = {}
    for seg in segment_infos:
        if seg._original_alignment_idx is not None:
            by_id[seg._original_alignment_idx - 1] = seg

    for st in timings.segments:
        seg = by_id.get(st.segment_id)
        if seg is None or st.words is None:
            continue
        words = []
        for w in st.words:
            entry = {"location": w.location, "start": w.start_s, "end": w.end_s}
            if w.letters:
                entry["letters"] = [
                    {"char": ch, "start": s, "end": e} for ch, s, e in w.letters
                ]
            if w.line_idx is not None:
                entry["line_idx"] = w.line_idx
            words.append(entry)
        seg.words = words


# ---------------------------------------------------------------------------
# Regions ↔ gr.State wire shapes
# ---------------------------------------------------------------------------
# The cached_speech_intervals State slot (and pipeline_state.pkl in saved
# sessions) holds the detector's raw intervals as an int-sample numpy array —
# the exact shape the legacy VAD wrapper produced. Keep that wire shape and
# convert to/from Regions at the SDK boundary.

def regions_to_state(regions: Regions) -> tuple[np.ndarray | None, bool | None]:
    """Regions → (raw sample-int ndarray, is_complete) for the gr.State slots."""
    raw_list = regions.raw if regions.raw is not None else regions.regions
    if not raw_list:
        return None, regions.is_complete
    raw = np.array(
        [[round(r.start_s * SAMPLE_RATE), round(r.end_s * SAMPLE_RATE)] for r in raw_list],
        dtype=np.int64,
    ).reshape(-1, 2)
    return raw, regions.is_complete


def state_to_regions(raw_state, is_complete, audio_duration_s: float | None = None) -> Regions:
    """(raw sample intervals, is_complete) State values → Regions for clean().

    Accepts the legacy shapes: numpy array, torch tensor, or list of pairs,
    all in sample units. ``regions`` is left empty — clean() re-derives it.
    """
    if hasattr(raw_state, "detach"):  # torch tensor from an old session
        raw_state = raw_state.detach().cpu().numpy()
    if isinstance(raw_state, np.ndarray):
        raw_state = raw_state.tolist()
    raw = [
        Region(start_s=float(s) / SAMPLE_RATE, end_s=float(e) / SAMPLE_RATE)
        for s, e in raw_state
    ]
    if hasattr(is_complete, "item"):  # numpy scalar/array
        is_complete = bool(np.asarray(is_complete).all())
    return Regions(
        regions=[],
        is_complete=bool(is_complete) if is_complete is not None else None,
        raw=raw,
        audio_duration_s=audio_duration_s,
    )


def intervals_from_regions(regions: Regions) -> list[tuple[float, float]]:
    """Cleaned Regions → the legacy list of (start_s, end_s) tuples."""
    return [(r.start_s, r.end_s) for r in regions.regions]


# ---------------------------------------------------------------------------
# Stage metrics → ProfilingData
# ---------------------------------------------------------------------------

def metrics_to_profiling(stages: dict, profiling: ProfilingData) -> None:
    """Populate ProfilingData from per-stage SDK metrics, in place.

    ``stages`` maps stage name → StageMeta (or a plain metrics dict). VAD/ASR
    GPU/wall times and VRAM are lease-level concerns stamped by the caller —
    only the per-component breakdowns land here.
    """
    seg = _metrics(stages.get("segmentation"))
    if seg:
        profiling.vad_model_load_time = seg.get("model_load_s", 0.0)
        profiling.vad_model_move_time = seg.get("model_move_s", 0.0)
        profiling.vad_inference_time = seg.get("inference_s", 0.0)

    rec = _metrics(stages.get("recognition"))
    if rec:
        profiling.asr_sorting_time = rec.get("sorting_s", 0.0)
        profiling.asr_batch_build_time = rec.get("batch_build_s", 0.0)
        profiling.asr_model_move_time = rec.get("model_move_s", 0.0)
        profiling.asr_batch_profiling = rec.get("batches") or []

    match = _metrics(stages.get("matching"))
    if match:
        from config import PHONEME_ALIGNMENT_PROFILING
        if PHONEME_ALIGNMENT_PROFILING:
            profiling.phoneme_num_segments = match.get("num_segments", 0)
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


def matching_events_to_collector(stages: dict, dc) -> None:
    """Bridge the matcher's event stream onto the app DebugCollector.

    SDK events are ``{"event": name, **fields}``; the collector (and the v3
    log row's events block) uses ``{"type": name, **fields}``.
    """
    if dc is None:
        return
    match = _metrics(stages.get("matching"))
    for ev in (match or {}).get("events") or []:
        fields = {k: v for k, v in ev.items() if k != "event"}
        dc.add_event(ev.get("event"), **fields)


def _metrics(stage) -> dict | None:
    if stage is None:
        return None
    return stage.metrics if hasattr(stage, "metrics") else dict(stage)


def _wall_s(stage) -> float | None:
    if stage is None:
        return None
    return getattr(stage, "wall_s", None)
