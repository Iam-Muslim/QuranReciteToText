"""Pipeline entry points — process / resegment / retranscribe / realign.

Each returns a PipelineOutcome (see outcome.py); the Gradio wiring flattens it
via ``as_outputs()`` and the session API reads fields.
"""
import time

import librosa
import numpy as np

from config import RESAMPLE_TYPE
from src.core import sdk_adapt
from src.core.audio_cache import _load_audio, _store_audio
from src.core.segment_types import ProfilingData
from qua_sdk.registry import resolve

from src.pipeline.gpu_runtime import (
    _reset_request_state,
    run_vad_and_asr_gpu,
)
from src.pipeline.outcome import PipelineOutcome
from src.pipeline.post_stages import _run_post_vad_pipeline


def process_audio(
    audio_data,
    model_name="Base",
    device="GPU",
    is_preset=False,
    request = None,
    endpoint="ui",
    log_enabled=True,
    return_html=True,
    estimated_wall_s=None,
    estimate_formula_s=None,
    url_source=None,
    rate_limit_checked=False,
    include_letters=False,
    fast_mode=False,
):
    """Process uploaded audio and extract segments with automatic verse detection.

    Args:
        audio_data: File path string (from gr.Audio type="filepath") or
                    (sample_rate, numpy_array) tuple (from API's type="numpy").

    Returns:
        PipelineOutcome.
    """
    _reset_request_state()

    if audio_data is None:
        return PipelineOutcome(html="<div>Please upload an audio file</div>")

    # Normalize device label to lowercase for downstream checks
    device = "cpu"

    print(f"\n{'='*60}")
    print(f"Processing audio with acoustic sliding window")
    print(f"Settings: device={device}, fast_mode={fast_mode}")
    print(f"{'='*60}")

    # Initialize profiling data
    profiling = ProfilingData()
    pipeline_start = time.time()

    if isinstance(audio_data, str):
        # File path from gr.Audio(type="filepath")
        load_start = time.time()
        audio, sample_rate = librosa.load(audio_data, sr=16000, mono=True, res_type=RESAMPLE_TYPE)
        profiling.resample_time = time.time() - load_start
        print(f"[PROFILE] Audio loaded and resampled to 16kHz in {profiling.resample_time:.3f}s "
              f"(duration: {len(audio)/16000:.1f}s, res_type={RESAMPLE_TYPE})")
    else:
        # (sample_rate, numpy_array) tuple from gr.Audio(type="numpy") — API path
        sample_rate, audio = audio_data

        # Convert to float32
        if audio.dtype == np.int16:
            audio = audio.astype(np.float32) / 32768.0
        elif audio.dtype == np.int32:
            audio = audio.astype(np.float32) / 2147483648.0

        # Convert stereo to mono
        if len(audio.shape) > 1:
            audio = audio.mean(axis=1)

        # Resample to 16kHz once (both VAD and ASR models require 16kHz)
        if sample_rate != 16000:
            resample_start = time.time()
            audio = librosa.resample(audio, orig_sr=sample_rate, target_sr=16000, res_type=RESAMPLE_TYPE)
            profiling.resample_time = time.time() - resample_start
            print(f"[PROFILE] Resampling {sample_rate}Hz -> 16000Hz took {profiling.resample_time:.3f}s (audio length: {len(audio)/16000:.1f}s, res_type={RESAMPLE_TYPE})")
            sample_rate = 16000

    print("[STAGE] Running VAD + ASR...")

    # Single GPU lease: VAD + ASR
    gpu_start = time.time()
    # Call the GPU runtime to perform the Sliding Window acoustic inference.
    # The VAD parameters have been stripped out; the engine relies purely on fixed sliding chunks.
    (regions, emissions, stage_metrics,
     vad_gpu_time, asr_gpu_time, peak_vram, reserved_vram) = run_vad_and_asr_gpu(
        audio, sample_rate, model_name, fast_mode=fast_mode
    )
    
    # Calculate total wall clock time taken by the GPU runtime.
    wall_time = time.time() - gpu_start
    profiling.gpu_peak_vram_mb = peak_vram
    profiling.gpu_reserved_vram_mb = reserved_vram

    # VAD + ASR breakdowns from the stage metrics; queue wait is attributed to
    # VAD (it happens before VAD runs)
    sdk_adapt.metrics_to_profiling(stage_metrics, profiling)
    profiling.vad_gpu_time = vad_gpu_time
    profiling.vad_wall_time = wall_time - asr_gpu_time
    print(f"[GPU] VAD completed in {profiling.vad_wall_time:.2f}s (gpu {vad_gpu_time:.2f}s)")

    raw_speech_intervals, raw_is_complete = sdk_adapt.regions_to_state(regions)

    intervals = sdk_adapt.intervals_from_regions(regions)
    if not intervals:
        return PipelineOutcome(html="<div>No speech segments detected in audio</div>")

    # ASR profiling: no separate queue (ran within same lease)
    profiling.asr_time = asr_gpu_time
    profiling.asr_gpu_time = asr_gpu_time
    print(f"[GPU] ASR completed in {asr_gpu_time:.2f}s")

    # Pass the regions and emissions from the Sliding Window to the post-processing stages.
    html, json_output, seg_dir, log_row = _run_post_vad_pipeline(
        audio, sample_rate, intervals,
        model_name, device, profiling, pipeline_start,
        regions=regions,
        emissions=emissions, stage_metrics=stage_metrics,
        request=request,
        is_preset=is_preset,
        endpoint=endpoint,
        log_enabled=log_enabled, return_html=return_html,
        estimated_wall_s=estimated_wall_s,
        estimate_formula_s=estimate_formula_s,
        url_source=url_source,
        include_letters=include_letters,
    )

    audio_ref = _store_audio(audio, sample_rate)
    return PipelineOutcome(
        html=html, segments=json_output,
        raw_speech_intervals=raw_speech_intervals, raw_is_complete=raw_is_complete,
        audio_ref=audio_ref, sample_rate=sample_rate, intervals=intervals,
        segment_dir=seg_dir, log_row=log_row,
    )


