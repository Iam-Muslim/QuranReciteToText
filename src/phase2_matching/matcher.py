"""
Post-ASR Matcher (SDK Text Alignment Only).

This module executes Phase 2 of the pipeline. It takes the raw, imperfect text
transcribed by FastConformer and aligns it against the perfect Uthmani script
using the qua_sdk Dynamic Programming (DP) engine.

Word-level timestamps are NO LONGER produced here. They are produced in Phase 3
(CTC Forced Alignment) which uses the raw logprobs matrix from FastConformer.
This module only returns SegmentInfo objects with words=None.
"""
# Import time for performance profiling and benchmarking.
import time

# Import specific domain schemas from the DP SDK.
from qua_sdk.schemas import Region, Regions
# Import the parameters structure used to configure the DP engine.
from qua_sdk.components.matching.runtimes.wraparound_params import WraparoundDpParams
# Import the primary DP execution function.
from qua_sdk.components.matching.runtimes.sequencer import run_matching_sequence
# Import the N-Gram anchoring logic.
from qua_sdk.components.matching.runtimes.runtime import find_anchor_by_voting
# Import our custom Arabic normalization rules.
from src.phase2_matching.normalize import get_arabic_resources

# Import our custom SDK adapter utilities.
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
    """
    Main orchestration function for Phase 2 (SDK Text Matching Only).

    Args:
        audio: The preprocessed float32 mono 16kHz audio array.
        sample_rate: The sample rate (always 16000).
        intervals: List of (start_s, end_s) tuples defining each speech chunk.
        model_name: The name of the acoustic model used.
        profiling: The ProfilingData instance used to track execution speeds.
        pipeline_start: The Unix timestamp when the user first launched the script.
        regions: SDK Region objects containing absolute start/end times.
        emissions: The raw transcribed text tokens from FastConformer.
        stage_metrics: Metrics passed down from the FastConformer inference stage.

    Returns:
        A tuple: (json_output_dict, segments_list)
        json_output_dict: The final JSON payload with words=None (Phase 3 fills words).
        segments_list: The list of SegmentInfo objects for Phase 3 to consume.
    """
    if not intervals:
        return {}, []

    if regions is None:
        duration = len(audio) / sample_rate if not isinstance(audio, str) else 0.0
        regions = Regions(
            regions=[Region(start_s=float(s), end_s=float(e)) for s, e in intervals],
            audio_duration_s=duration,
        )

    print(f"[Sliding Window] {len(intervals)} chunks")
    print(f"[ASR] {len(emissions.tokens)} results")

    transcribed_tokens = emissions.tokens
    asr_batch_profiling = profiling.asr_batch_profiling

    if asr_batch_profiling:
        for b in asr_batch_profiling:
            print(f"  Batch {b['batch_num']:>2}: {b['size']:>3} segs | "
                  f"{b['time']:.3f}s | "
                  f"{b['min_dur']:.2f}-{b['max_dur']:.2f}s "
                  f"(A {b['total_seconds']/b['size']:.2f}s, T {b['total_seconds']:.1f}s, W {b['pad_waste']:.0%}, "
                  f"QK^T {b['qk_mb_per_head']:.1f} MB/head, {b['qk_mb_all_heads']:.0f} MB total)")

    # =====================================================================
    # DP MATCHING STAGE
    # =====================================================================
    print(f"[STAGE] Text Matching (Arabic Word Mode)...")

    match_start = time.time()
    try:
        resources = get_arabic_resources()
        params = WraparoundDpParams()

        params.anchor.ngram_size = 5
        params.anchor.segments = 5

        # PHASE 2.1: GLOBAL ANCHOR DETECTION (N-Gram Matching)
        start_surah, start_ayah = find_anchor_by_voting(transcribed_tokens, resources.ngram_index, params.anchor)

        if start_surah <= 0:
            raise ValueError("Could not anchor to any chapter — no n-gram matches found")

        print(f"[ANCHOR] Anchored to Surah {start_surah}:{start_ayah}")

        chapter_ref = resources.chapter_refs[start_surah]
        start_pointer = 0
        for i, w in enumerate(chapter_ref.words):
            if w.ayah == start_ayah:
                start_pointer = i
                break

        def _on_match_event(evt):
            if isinstance(evt, dict) and "progress" in evt:
                pct = float(evt["progress"]) * 100.0
                print(f"[PROGRESS] Matching {pct:.1f}%")

        # PHASE 2.2: SEQUENTIAL DYNAMIC PROGRAMMING (DP) ALIGNMENT
        sdk_result = run_matching_sequence(
            phoneme_texts=transcribed_tokens,
            start_surah=start_surah,
            first_quran_idx=0,
            special_results=[],
            start_pointer=start_pointer,
            params=params,
            resources=resources,
            on_event=_on_match_event,
        )

    except Exception as e:
        user_message = getattr(e, "user_message", None)
        if user_message:
            raise ValueError(user_message) from e
        raise

    match_time = time.time() - match_start
    profiling.match_wall_time = match_time
    print(f"[MATCH] {len(sdk_result.results)} alignments in {match_time:.2f}s")

    sdk_adapt.metrics_to_profiling({"matching": sdk_result.metrics}, profiling)

    # =====================================================================
    # RESULTS BUILDING STAGE (1:1 Clone of QUA SDK Handling)
    # =====================================================================
    print(f"[STAGE] Building results...")

    from qua_sdk.schemas import Alignment, AlignedSegment

    # The official app uses batch_align which returns an Alignment object.
    # Since we use sequential DP here, we bridge the gap by constructing an
    # Alignment object so we can pipe it through the official sdk_adapt layer 1:1.
    alignment = Alignment(
        chapter=start_surah,
        segments=[],
    )

    for i, res in enumerate(sdk_result.results):
        matched_text, score, matched_ref, wrap_ranges = res
        
        # For repetition segments, rebuild matched_text in chronological reading order.
        # This is critical for CTC alignment, as it needs the exact spoken sequence.
        if wrap_ranges and matched_ref and ":" in matched_ref:
            from src.core.quran_index import get_quran_index
            qi = get_quran_index()
            
            parts = matched_ref.split("-")
            ref_from = parts[0]
            ref_to = parts[1] if len(parts) > 1 else parts[0]
            
            # Use the same logic we put in ctc_align to get the sections
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
                    for gi in range(s, e + 1):
                        recited_words.append(qi.words[gi].text)
            
            if recited_words:
                # Keep any prefix specials (like Basmala) that were in the original matched_text
                # Find the canonical text words
                canon_indices = qi.ref_to_indices(matched_ref)
                if canon_indices:
                    canon_count = canon_indices[1] - canon_indices[0] + 1
                    orig_words = matched_text.split()
                    if len(orig_words) > canon_count:
                        prefix_words = orig_words[:len(orig_words) - canon_count]
                        recited_words = prefix_words + recited_words
                matched_text = " ".join(recited_words)

        # Build the exact AlignedSegment schema expected by sdk_adapt
        seg = AlignedSegment(
            id=i,
            region=regions.regions[i],
            matched_text=matched_text,
            matched_ref=matched_ref,
            confidence=score,
            wrap_word_ranges=wrap_ranges,
            error=f"Low confidence ({score:.0%})" if score < 0.2 and score > 0 else ("Failed" if score == 0 else None),
        )
        alignment.segments.append(seg)

    # Use the official adapter exactly like the reference app
    segments = sdk_adapt.alignment_to_segment_infos(alignment, emissions, regions)
    
    # Restore the repetition flags that were computed sequentially
    for i, seg in enumerate(segments):
        seg.has_repeated_words = (i in getattr(sdk_result, "repetition_segments", set()))

    # =====================================================================
    # POST-PROCESSING: Split fused segments at Ayah boundaries
    # =====================================================================
    result_build_start = time.time()
    # (Moved to main_flow.py AFTER Phase 3 CTC alignment)

    # =====================================================================
    # FINAL METRICS & SUMMARY
    # =====================================================================
    _seg_word_counts = []
    _seg_durations = []
    _seg_char_counts = []

    for seg in segments:
        if seg.end_time is not None and seg.start_time is not None:
            duration = seg.end_time - seg.start_time
        else:
            duration = 0.0
        word_count = len(seg.matched_ref.split()) if seg.matched_ref else 0
        _seg_word_counts.append(word_count)
        _seg_durations.append(duration)
        _seg_char_counts.append(0)

    profiling.segments_attempted = len(segments)
    profiling.segments_passed = sum(1 for s in segments if s.match_score > 0.0)

    result_build_total_time = time.time() - result_build_start
    profiling.result_build_time = result_build_total_time
    profiling.result_audio_encode_time = 0.0
    profiling.total_time = time.time() - pipeline_start
    print(profiling.summary())

    matched_words = [w for w in _seg_word_counts if w > 0]
    matched_durs = [d for i, d in enumerate(_seg_durations) if _seg_word_counts[i] > 0]
    pauses = [intervals[i + 1][0] - intervals[i][1] for i in range(len(intervals) - 1)]
    pauses = [p for p in pauses if p > 0]

    if matched_words:
        def _std(vals):
            n = len(vals)
            if n < 2:
                return 0.0
            mean = sum(vals) / n
            return (sum((v - mean) ** 2 for v in vals) / n) ** 0.5

        avg_w = sum(matched_words) / len(matched_words)
        std_w = _std(matched_words)
        min_w, max_w = min(matched_words), max(matched_words)
        avg_d = sum(matched_durs) / len(matched_durs)
        std_d = _std(matched_durs)
        min_d, max_d = min(matched_durs), max(matched_durs)
        total_speech_sec = sum(matched_durs)
        total_words = sum(matched_words)
        wpm = total_words / (total_speech_sec / 60) if total_speech_sec > 0 else 0

        print(f"\n[SEGMENT STATS] {len(segments)} total segments, {len(matched_words)} matched")
        print(f"  Words/segment : min={min_w}, max={max_w}, avg={avg_w:.1f}\u00b1{std_w:.1f}")
        print(f"  Duration (s)  : min={min_d:.1f}, max={max_d:.1f}, avg={avg_d:.1f}\u00b1{std_d:.1f}")
        if pauses:
            avg_p = sum(pauses) / len(pauses)
            std_p = _std(pauses)
            print(f"  Pause (s)     : min={min(pauses):.1f}, max={max(pauses):.1f}, avg={avg_p:.1f}\u00b1{std_p:.1f}")
        print(f"  Speech pace   : {wpm:.1f} words/min")

    for i, seg in enumerate(segments):
        seg.segment_number = i + 1

    # Return BOTH the JSON dict (None placeholder) and the segments list.
    # The segments list is needed by Phase 3 to fill in word timestamps via CTC alignment.
    return None, segments
