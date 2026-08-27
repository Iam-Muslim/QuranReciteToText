"""Pipeline Entry Points — Orchestrates Phase 1, Phase 2, Phase 3, and Phase 4 processing."""

import time
import subprocess
import numpy as np

from src.core import sdk_adapt
from src.core.segment_types import ProfilingData
from src.phase1_transcribe.stream import run_asr_cpu
from src.phase2_matching.matcher import _run_post_asr_pipeline
from src.phase3_alignment.ctc_align import run_ctc_alignment
from src.phase1_transcribe.zipformer import TOKENS_PATH


def _resample_audio_ffmpeg(audio_array, orig_sr, target_sr=16000):
    """Resamples in-memory NumPy audio array to target sample rate using FFmpeg stdin pipe."""
    command = [
        'ffmpeg', '-v', 'quiet',
        '-f', 'f32le', '-ar', str(orig_sr), '-ac', '1',
        '-i', 'pipe:0',
        '-f', 'f32le', '-acodec', 'pcm_f32le', '-ac', '1', '-ar', str(target_sr),
        'pipe:1'
    ]
    process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    stdout, stderr = process.communicate(input=audio_array.tobytes())

    if process.returncode != 0:
        raise RuntimeError(f"FFmpeg resample failed: {stderr.decode('utf-8', errors='ignore')}")

    return np.frombuffer(stdout, dtype=np.float32)


def process_audio(
    audio_data,
    model_name="Base",
    profile_name="auto",
    return_profiling: bool = False,
    progress_callback=None,
    min_silence_ms: int = 1200,
    pad_ms: int = 600,
):
    """Main execution wrapper for the transcription and Quran alignment pipeline.

    Args:
        audio_data: Input audio file path or (sample_rate, numpy_array).
        model_name: Acoustic model name.
        profile_name: Transcription profile preset ('auto', 'fast', 'noisy', 'clean', 'sliding').
        return_profiling: If True, returns (json_output, profiling).
        progress_callback: Optional callable(pct, msg) for progress tracking.
        min_silence_ms: Requested silence threshold for chunk detection and subtitle splitting.
        pad_ms: Maximum adaptive padding added around speech chunks.
    """
    if audio_data is None:
        return ([], ProfilingData()) if return_profiling else []

    profiling = ProfilingData()
    pipeline_start = time.time()

    if isinstance(audio_data, str):
        audio = audio_data
        sample_rate = 16000
    else:
        sample_rate, audio = audio_data

        if audio.dtype == np.int16:
            audio = audio.astype(np.float32) / 32768.0
        elif audio.dtype == np.int32:
            audio = audio.astype(np.float32) / 2147483648.0

        if len(audio.shape) > 1:
            audio = audio.mean(axis=1)

        if sample_rate != 16000:
            resample_start = time.time()
            audio = _resample_audio_ffmpeg(audio, orig_sr=sample_rate, target_sr=16000)
            profiling.resample_time = time.time() - resample_start
            sample_rate = 16000

    # Phase 1: Continuous ASR Transcription
    try:
        regions, emissions, stage_metrics, asr_time, audio_pcm = run_asr_cpu(
            audio,
            sample_rate,
            model_name=model_name,
            profile_name=profile_name,
            progress_callback=progress_callback,
            min_silence_ms=min_silence_ms,
            pad_ms=pad_ms,
        )
    except Exception as e:
        profiling.total_time = time.time() - pipeline_start
        return ([], profiling) if return_profiling else []

    sdk_adapt.metrics_to_profiling(stage_metrics, profiling)
    intervals = sdk_adapt.intervals_from_regions(regions)

    profiling.audio_duration_s = regions.audio_duration_s

    if not intervals:
        profiling.total_time = time.time() - pipeline_start
        return ([], profiling) if return_profiling else []

    profiling.asr_time = asr_time

    json_output, segments = _run_post_asr_pipeline(
        audio_pcm, sample_rate, intervals,
        model_name, profiling, pipeline_start,
        regions=regions, emissions=emissions, stage_metrics=stage_metrics
    )

    try:
        run_ctc_alignment(
            segments=segments,
            stage_metrics=stage_metrics,
            vocab_path=TOKENS_PATH,
        )
    except Exception as e:
        import traceback
        traceback.print_exc()

    # Phase 4: Canonical 1-Ayah = 1-Segment Aggregation & Formatting
    from src.phase4_splitting.ayah_split import aggregate_by_canonical_ayah, smooth_word_timestamps
    from src.phase4_splitting.missing_words import recompute_missing_words, inject_missing_words

    # 1. Exact 1-Ayah = 1-Segment Canonical Aggregator
    segments = aggregate_by_canonical_ayah(segments)

    # 2. Recompute missing words from canonical Quran coverage
    recompute_missing_words(segments)

    # 3. Optional: extend word end-timestamps into trailing silence
    smooth_word_timestamps(
        segments,
        audio_data=audio,
        sample_rate=sample_rate,
        min_silence_ms=min_silence_ms,
        pad_ms=pad_ms,
        bridge_unsplit_gaps=bool(stage_metrics.get("multi_chapter")),
    )

    # 4. Optional: inject missing (unrecited) words into the words array
    inject_missing_words(segments)

    profiling.total_time = time.time() - pipeline_start

    # Build the core JSON payload (words always included).
    from src.core.segment_types import build_segment_export
    payload = build_segment_export(segments, include_words=True)

    if return_profiling:
        return payload, profiling
    return payload
