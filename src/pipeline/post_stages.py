"""Post-VAD shared pipeline: ASR → matching → results build → usage logging → render."""
import json
import math
import os
import threading
import time
import uuid

import numpy as np

from config import SEGMENT_AUDIO_DIR
from qua_sdk.components.recognition.spec import RecognitionParams
from qua_sdk.schemas import Region, Regions, Audio
from qua_sdk.components.matching.runtimes.wraparound_params import WraparoundDpParams
from qua_sdk.components.matching.runtimes.sequencer import run_matching_sequence
from qua_sdk.components.matching.runtimes.runtime import find_anchor_by_voting
from src.pipeline.arabic_matching import get_arabic_resources

from src.core import sdk_adapt
from src.core.deploy_select import select_deploy
from src.core.segment_types import segments_to_json
from src.pipeline.fused_split import _split_fused_segments
from src.pipeline.gpu_runtime import run_phoneme_asr_gpu


def _space_profile(model_name):
    """Per-request batch_align profile: app SPACE defaults + the chosen ASR model.

    ``timing`` stays None — word timestamps run via their own UI flow (MFA).
    Segmentation params are irrelevant here (regions are precomputed by the
    lease before matching runs).
    """
    from qua_sdk.profiles.batch_align import BatchAlignProfile
    profile = BatchAlignProfile(name="space")
    profile.timing = None
    profile.recognition = RecognitionParams(model=model_name)
    return profile


def _run_post_vad_pipeline(
    audio, sample_rate, intervals,
    model_name, device, profiling, pipeline_start,
    regions=None,
    emissions=None, stage_metrics=None,
    min_silence_ms=0, min_speech_ms=0, pad_ms=0,
    request=None, log_row=None,
    is_preset=False,
    endpoint="ui",
    log_enabled=True,
    return_html=True,
    estimated_wall_s=None,
    estimate_formula_s=None,
    url_source=None,
    include_letters=False,
):
    """Shared pipeline after segmentation: ASR → matching → results.

    Args:
        audio: Preprocessed float32 mono 16kHz audio array
        sample_rate: Sample rate (16000)
        intervals: List of (start, end) tuples from VAD cleaning
        model_name: ASR model name ("Base" or "Large")
        device: Device string ("gpu" or "cpu")
        profiling: ProfilingData instance to populate
        pipeline_start: time.time() when pipeline started
        regions: Optional qua_sdk Regions matching ``intervals`` (from the
            combined lease). Built from ``intervals`` when absent.
        emissions, stage_metrics: results of a combined GPU lease; when
            ``emissions`` is given, the standalone ASR GPU call is skipped.
        endpoint: pure log label for the usage-log row.
        log_enabled: when False, skip usage logging entirely (synthetic
            re-runs must not pollute the telemetry datasets).
        return_html: True → (rendered cards, List[SegmentInfo]); False →
            API shape ("", JSON dict).

    Returns:
        (html, json_output, segment_dir, log_row) tuple
    """
    if not intervals:
        empty = [] if return_html else {"segments": []}
        return "<div>No speech segments detected in audio</div>", empty, None, None

    if regions is None:
        regions = Regions(
            regions=[Region(start_s=float(s), end_s=float(e)) for s, e in intervals],
            audio_duration_s=len(audio) / sample_rate,
        )

    print(f"[VAD] {len(intervals)} segments")



    if emissions is not None:
        # ASR already ran within the combined GPU lease
        print(f"[PHONEME ASR] {len(emissions)} results (combined lease, gpu {profiling.asr_gpu_time:.2f}s)")
    else:
        # Standalone ASR GPU lease (resegment/retranscribe paths)
        print(f"[STAGE] Running ASR...")

        phoneme_asr_start = time.time()
        emissions, rec_metrics, asr_gpu_time, peak_vram, reserved_vram = run_phoneme_asr_gpu(
            audio, sample_rate, [(float(s), float(e)) for s, e in intervals], model_name, device=device
        )
        phoneme_asr_time = time.time() - phoneme_asr_start
        stage_metrics = {"recognition": rec_metrics}
        sdk_adapt.metrics_to_profiling(stage_metrics, profiling)
        profiling.asr_time = phoneme_asr_time
        profiling.asr_gpu_time = asr_gpu_time
        profiling.gpu_peak_vram_mb = peak_vram
        profiling.gpu_reserved_vram_mb = reserved_vram
        print(f"[PHONEME ASR] {len(emissions)} results in {phoneme_asr_time:.2f}s (gpu {asr_gpu_time:.2f}s)")

    phoneme_texts = emissions.tokens
    asr_batch_profiling = profiling.asr_batch_profiling

    if asr_batch_profiling:
        for b in asr_batch_profiling:
            print(f"  Batch {b['batch_num']:>2}: {b['size']:>3} segs | "
                  f"{b['time']:.3f}s | "
                  f"{b['min_dur']:.2f}-{b['max_dur']:.2f}s "
                  f"(A {b['total_seconds']/b['size']:.2f}s, T {b['total_seconds']:.1f}s, W {b['pad_waste']:.0%}, "
                  f"QK^T {b['qk_mb_per_head']:.1f} MB/head, {b['qk_mb_all_heads']:.0f} MB total)")



    # Matching (specials + anchor + DP alignment, internal to the SDK matcher)
    print(f"[STAGE] Text Matching (Arabic Word Mode)...")

    match_start = time.time()
    try:
        resources = get_arabic_resources()
        params = WraparoundDpParams()
        
        # 1. Global anchor detection via Arabic word n-grams
        start_surah, start_ayah = find_anchor_by_voting(phoneme_texts, resources.ngram_index, params.anchor)
        if start_surah <= 0:
            raise ValueError("Could not anchor to any chapter — no n-gram matches found")
            
        print(f"[ANCHOR] Anchored to Surah {start_surah}:{start_ayah}")
        
        # We need the 0-indexed word pointer for start_ayah.
        chapter_ref = resources.chapter_refs[start_surah]
        start_pointer = 0
        for i, w in enumerate(chapter_ref.words):
            if w.ayah == start_ayah:
                start_pointer = i
                break

        # 2. Sequential Arabic word DP alignment
        sdk_result = run_matching_sequence(
            phoneme_texts=phoneme_texts,
            start_surah=start_surah,
            first_quran_idx=0,
            special_results=[],
            start_pointer=start_pointer,
            params=params,
            resources=resources,
            on_event=None,
        )
    except Exception as e:
        # Keep the legacy contract: anchor/input failures surface as ValueError
        # with the bare message (UI + API handlers match on that).
        user_message = getattr(e, "user_message", None)
        if user_message:
            raise ValueError(user_message) from e
        raise
    match_time = time.time() - match_start
    profiling.match_wall_time = match_time
    print(f"[MATCH] {len(sdk_result.results)} alignments in {match_time:.2f}s")

    # Matching counters + wall breakdown → ProfilingData
    sdk_adapt.metrics_to_profiling({"matching": sdk_result.metrics}, profiling)

    print(f"[STAGE] Building results...")

    # Build SegmentInfo list from run_matching_sequence output
    segments = []
    from src.core.segment_types import SegmentInfo
    from src.pipeline.fastconformer_onnx import FastConformerONNX
    
    fc = FastConformerONNX.get_instance()
    logprobs_entries = stage_metrics.get("logprobs", [])
    
    from src.core.segment_types import compute_reading_sequence

    q_index = None
    ref_to_idx = None

    def _ensure_q_index():
        nonlocal q_index, ref_to_idx
        if q_index is None:
            from src.core.quran_index import get_quran_index
            q_index = get_quran_index()
            ref_to_idx = {f"{w.surah}:{w.ayah}:{w.word}": idx for idx, w in enumerate(q_index.words)}

    for i, res in enumerate(sdk_result.results):
        matched_text, score, matched_ref, wrap_ranges = res
        seg_start = regions.regions[i].start_s
        seg_end = regions.regions[i].end_s
        transcribed_text = " ".join(phoneme_texts[i])
        
        # For repetition segments, rebuild matched_text from the quran index reading sequence
        if wrap_ranges and matched_ref and ":" in matched_ref:
            _ensure_q_index()
            parts = matched_ref.split("-")
            ref_from = parts[0]
            ref_to = parts[1] if len(parts) > 1 else parts[0]
            sections = compute_reading_sequence(ref_from, ref_to, wrap_ranges)
            recited_words = []
            for sec in sections:
                s_ref, e_ref = sec
                if s_ref in ref_to_idx and e_ref in ref_to_idx:
                    for w_i in range(ref_to_idx[s_ref], ref_to_idx[e_ref] + 1):
                        recited_words.append(q_index.words[w_i].text)
            if recited_words:
                matched_text = " ".join(recited_words)
        
        words = None
        if score > 0 and i < len(logprobs_entries) and matched_text:
            lp_entry = logprobs_entries[i]
            if isinstance(lp_entry, tuple):
                logprobs_mat, chunk_origin = lp_entry
            else:
                logprobs_mat, chunk_origin = lp_entry, seg_start

            # CRITICAL: Trim logprobs to only the frames covering this segment's
            # safe-zone [seg_start, seg_end].  Passing the full 30s matrix causes
            # the CTC aligner to absorb all silent/blank frames before the real
            # speech into the first word, producing multi-second-long word0 and
            # wildly compressed remaining words → overlapping timestamps.
            seconds_per_frame = (160 / 16000) * 8  # hop=160, sr=16000, subsampling=8 → 0.08 s/frame
            frame_start = max(0, int((seg_start - chunk_origin) / seconds_per_frame))
            frame_end   = min(logprobs_mat.shape[0], int(math.ceil((seg_end - chunk_origin) / seconds_per_frame)) + 2)
            trimmed_lp  = logprobs_mat[frame_start:frame_end]
            # The trimmed matrix's t=0 corresponds to this absolute time in the audio
            trim_origin = chunk_origin + frame_start * seconds_per_frame

            words = fc.force_align(trimmed_lp, matched_text, include_letters=include_letters)
            for w in words:
                w['start'] += trim_origin
                w['end']   += trim_origin
                if 'letters' in w:
                    for lt in w['letters']:
                        lt['start'] += trim_origin
                        lt['end']   += trim_origin
            # Stamp Quran location refs onto each word using the matched_ref range.
            # This mirrors what the original repo's MFA pipeline does: every word carries
            # location so fused_split and to_json_dict can emit it correctly.
            if matched_ref and ":" in matched_ref and words:
                _ensure_q_index()
                parts = matched_ref.split("-")
                r_from = parts[0]
                r_to = parts[1] if len(parts) > 1 else parts[0]
                sections = compute_reading_sequence(r_from, r_to, wrap_ranges or [])
                # Flatten the reading-order word refs from the quran index
                loc_refs = []
                for sec in sections:
                    s_ref, e_ref = sec
                    if s_ref in ref_to_idx and e_ref in ref_to_idx:
                        for w_i in range(ref_to_idx[s_ref], ref_to_idx[e_ref] + 1):
                            qw = q_index.words[w_i]
                            loc_refs.append(f"{qw.surah}:{qw.ayah}:{qw.word}")
                # Stamp location on each force-aligned word (1:1 mapping)
                for j, w in enumerate(words):
                    if j < len(loc_refs):
                        w['location'] = loc_refs[j]
        
        segments.append(SegmentInfo(
            start_time=seg_start,
            end_time=seg_end,
            transcribed_text=transcribed_text,
            matched_text=matched_text,
            matched_ref=matched_ref,
            match_score=score,
            wrap_word_ranges=wrap_ranges,
            error=f"Low confidence ({score:.0%})" if score < 0.2 and score > 0 else ("Failed" if score == 0 else None),
            has_missing_words=(i in sdk_result.gap_segments),
            has_repeated_words=(i in sdk_result.repetition_segments),
            words=words,
        ))
    result_build_start = time.time()

    audio_encode_time = 0.0

    # Create a per-request directory for segment WAV files
    segment_dir = SEGMENT_AUDIO_DIR / uuid.uuid4().hex
    segment_dir.mkdir(parents=True, exist_ok=True)

    # Post-processing: split combined/fused segments via MFA timestamps
    segments = _split_fused_segments(segments, None, sample_rate)

    # Clamp segment boundaries so no segment's time_to exceeds the next segment's time_from.
    # This eliminates the 0.08s rounding artifacts and larger chunk-boundary overlaps that
    # arise from adjacent safe-zones in the sliding window not perfectly partitioning.
    # Word timestamps inside each segment are untouched — only the envelope metadata changes.
    for i in range(len(segments) - 1):
        if segments[i].end_time > segments[i + 1].start_time:
            segments[i].end_time = segments[i + 1].start_time

    # Recompute stats from final segments list

    _seg_word_counts = []
    _seg_durations = []
    _seg_phoneme_counts = []
    _seg_ayah_spans = []
    for i, seg in enumerate(segments):
        duration = seg.end_time - seg.start_time
        # Simplified stubs since UI was deleted
        word_count = len(seg.matched_ref.split()) if seg.matched_ref else 0
        ayah_span = ""
        _seg_word_counts.append(word_count)
        _seg_durations.append(duration)
        _seg_phoneme_counts.append(0)
        _seg_ayah_spans.append(ayah_span)

    profiling.segments_attempted = len(segments)
    profiling.segments_passed = sum(1 for s in segments if s.match_score > 0.0)

    result_build_total_time = time.time() - result_build_start
    profiling.result_build_time = result_build_total_time
    profiling.result_audio_encode_time = audio_encode_time

    # Print profiling summary
    profiling.total_time = time.time() - pipeline_start
    print(profiling.summary())



    # Segment distribution stats
    matched_words = [w for w in _seg_word_counts if w > 0]
    matched_durs = [d for i, d in enumerate(_seg_durations) if _seg_word_counts[i] > 0]
    matched_phonemes = [p for i, p in enumerate(_seg_phoneme_counts) if _seg_word_counts[i] > 0]
    pauses = [intervals[i + 1][0] - intervals[i][1]
              for i in range(len(intervals) - 1)]
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
        total_phonemes = sum(matched_phonemes)
        wpm = total_words / (total_speech_sec / 60) if total_speech_sec > 0 else 0
        pps = total_phonemes / total_speech_sec if total_speech_sec > 0 else 0
        print(f"\n[SEGMENT STATS] {len(segments)} total segments, {len(matched_words)} matched")
        print(f"  Words/segment : min={min_w}, max={max_w}, avg={avg_w:.1f}\u00b1{std_w:.1f}")
        print(f"  Duration (s)  : min={min_d:.1f}, max={max_d:.1f}, avg={avg_d:.1f}\u00b1{std_d:.1f}")
        if pauses:
            avg_p = sum(pauses) / len(pauses)
            std_p = _std(pauses)
            print(f"  Pause (s)     : min={min(pauses):.1f}, max={max(pauses):.1f}, avg={avg_p:.1f}\u00b1{std_p:.1f}")
        print(f"  Speech pace   : {wpm:.1f} words/min, {pps:.1f} phonemes/sec (speech time only)")
    from qua_sdk.domain import SPECIAL_NAMES as ALL_SPECIAL_REFS
    
    # Usage logging stripped for CPU-only release
    log_row = None

    # Stamp segment_number for BOTH API and UI consumers. Was UI-only before,
    # which left every API response (and the saved session segments.json) with
    # segment=0 for all segments — that cascaded into _build_mfa_refs keying
    # seg_to_result_idx[-1] (overwritten until pointing at the last result),
    # so /timestamps enriched every segment with the LAST segment's word data.
    # Stamp before serializing.
    for i, seg in enumerate(segments):
        seg.segment_number = i + 1

    if not return_html:
        json_output = segments_to_json(segments, include_words=True, include_letters=include_letters)
        return "", json_output, str(segment_dir), log_row

    json_output = segments

    return "", json_output, str(segment_dir), log_row
