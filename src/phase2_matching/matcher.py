"""Post-ASR Matcher (SDK Text Alignment)."""

import time
from qua_sdk.schemas import Region, Regions, Alignment, AlignedSegment
from qua_sdk.components.matching.runtimes.wraparound_params import WraparoundDpParams
from qua_sdk.components.matching.runtimes.sequencer import run_matching_sequence
from qua_sdk.components.matching.runtimes.runtime import find_anchor_by_voting
from src.phase2_matching.normalize import get_arabic_resources
from src.core import sdk_adapt


def _run_post_asr_pipeline(
    audio,
    sample_rate,
    intervals,
    model_name,
    profiling,
    pipeline_start,
    regions=None,
    emissions=None,
    stage_metrics=None
):
    """Main orchestration function for Phase 2 (SDK Text Matching)."""
    if not intervals:
        return {}, []

    if regions is None:
        duration = len(audio) / sample_rate if not isinstance(audio, str) else 0.0
        regions = Regions(
            regions=[Region(start_s=float(s), end_s=float(e)) for s, e in intervals],
            audio_duration_s=duration,
        )

    transcribed_tokens = emissions.tokens
    match_start = time.time()

    try:
        resources = get_arabic_resources()
        params = WraparoundDpParams()
        params.anchor.ngram_size = 5
        params.anchor.segments = 5

        start_surah, start_ayah = find_anchor_by_voting(transcribed_tokens, resources.ngram_index, params.anchor)
        if start_surah <= 0:
            raise ValueError("Could not anchor to any chapter — no n-gram matches found")

        chapter_ref = resources.chapter_refs[start_surah]
        start_pointer = 0
        for i, w in enumerate(chapter_ref.words):
            if w.ayah == start_ayah:
                start_pointer = i
                break

        sdk_result = run_matching_sequence(
            phoneme_texts=transcribed_tokens,
            start_surah=start_surah,
            first_quran_idx=0,
            special_results=[],
            start_pointer=start_pointer,
            params=params,
            resources=resources,
        )

    except Exception as e:
        user_message = getattr(e, "user_message", None)
        if user_message:
            raise ValueError(user_message) from e
        raise

    match_time = time.time() - match_start
    profiling.match_wall_time = match_time
    sdk_adapt.metrics_to_profiling({"matching": sdk_result.metrics}, profiling)

    alignment = Alignment(chapter=start_surah, segments=[])

    for i, res in enumerate(sdk_result.results):
        matched_text, score, matched_ref, wrap_ranges = res

        if wrap_ranges and matched_ref and ":" in matched_ref:
            from src.core.quran_index import get_quran_index
            qi = get_quran_index()

            parts = matched_ref.split("-")
            ref_from = parts[0]
            ref_to = parts[1] if len(parts) > 1 else parts[0]

            sections = []
            if len(wrap_ranges[0]) >= 3:
                sections.append([ref_from, wrap_ranges[0][1]])
                for wr in wrap_ranges:
                    sections.append([wr[0], wr[2]])
            else:
                sections.append([ref_from, wrap_ranges[0][1]])
                for i_wr in range(len(wrap_ranges) - 1):
                    sections.append([wrap_ranges[i_wr][0], wrap_ranges[i_wr + 1][1]])
                sections.append([wrap_ranges[-1][0], ref_to])

            recited_words = []
            for s_ref, e_ref in sections:
                indices = qi.ref_to_indices(f"{s_ref}-{e_ref}")
                if indices:
                    s, e = indices
                    recited_words.extend(qi.words[gi].text for gi in range(s, e + 1))

            if recited_words:
                canon_indices = qi.ref_to_indices(matched_ref)
                if canon_indices:
                    canon_count = canon_indices[1] - canon_indices[0] + 1
                    orig_words = matched_text.split()
                    if len(orig_words) > canon_count:
                        prefix_words = orig_words[:len(orig_words) - canon_count]
                        recited_words = prefix_words + recited_words
                matched_text = " ".join(recited_words)

        # Match reference project: only flag score==0 as low-confidence.
        # Low-but-nonzero scores (< 20%) are accepted silently like the reference.
        seg = AlignedSegment(
            id=i,
            region=regions.regions[i],
            matched_text=matched_text,
            matched_ref=matched_ref,
            confidence=score,
            wrap_word_ranges=wrap_ranges,
            error="Low confidence (0%)" if score == 0 else None,
        )
        alignment.segments.append(seg)

    # alignment_to_segment_infos already sets has_repeated_words from wrap_word_ranges.
    # Do NOT overwrite it — the wrap_ranges are the single source of truth.
    segments = sdk_adapt.alignment_to_segment_infos(alignment, emissions, regions)

    profiling.segments_attempted = len(segments)
    profiling.segments_passed = sum(1 for s in segments if s.match_score > 0.0)
    profiling.total_time = time.time() - pipeline_start

    return None, segments
