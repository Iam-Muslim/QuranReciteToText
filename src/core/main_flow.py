"""Pipeline Entry Points — Orchestrates Phase 1, Phase 2, Phase 3, and Phase 4 processing."""

import time
import subprocess
import numpy as np

from src.core import sdk_adapt
from src.core.segment_types import ProfilingData
from src.phase1_transcribe.stream import run_asr_cpu
from src.phase2_matching.matcher import _run_post_asr_pipeline
from src.phase3_alignment.ctc_align import run_ctc_alignment
from src.phase1_transcribe.fastconformer import FASTCONFORMER_TOKENS_PATH


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


def process_audio(audio_data, model_name="Base", return_profiling: bool = False):
    """Main execution wrapper for the transcription and Quran alignment pipeline.

    Args:
        audio_data: Input audio file path or (sample_rate, numpy_array).
        model_name: Acoustic model name.
        return_profiling: If True, returns (json_output, profiling).
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

    (regions, emissions, stage_metrics, asr_time) = run_asr_cpu(audio, sample_rate, model_name)
    sdk_adapt.metrics_to_profiling(stage_metrics, profiling)
    intervals = sdk_adapt.intervals_from_regions(regions)

    profiling.audio_duration_s = regions.audio_duration_s

    if not intervals:
        profiling.total_time = time.time() - pipeline_start
        return ([], profiling) if return_profiling else []

    profiling.asr_time = asr_time

    json_output, segments = _run_post_asr_pipeline(
        audio, sample_rate, intervals,
        model_name, profiling, pipeline_start,
        regions=regions, emissions=emissions, stage_metrics=stage_metrics
    )

    try:
        run_ctc_alignment(
            segments=segments,
            stage_metrics=stage_metrics,
            vocab_path=FASTCONFORMER_TOKENS_PATH,
        )
    except Exception as e:
        import traceback
        traceback.print_exc()

    from src.phase4_splitting.fused_split import _split_fused_segments
    segments = _split_fused_segments(segments)

    from src.phase4_splitting.ayah_split import split_segments_at_ayah_boundaries
    segments = split_segments_at_ayah_boundaries(segments)

    from src.core.auto_merge import fuse_adjacent_same_ayah_segments
    segments = fuse_adjacent_same_ayah_segments(segments)

    for i, seg in enumerate(segments):
        seg.segment_number = i + 1

    from src.core.missing_words import recompute_missing_words, inject_missing_words
    recompute_missing_words(segments)
    inject_missing_words(segments)

    from src.phase4_splitting.word_smoothing import smooth_word_timestamps
    smooth_word_timestamps(segments)

    profiling.total_time = time.time() - pipeline_start

    from src.phase4_splitting.export import build_segment_export
    payload = build_segment_export(segments, include_words=True)

    if return_profiling:
        return payload, profiling
    return payload