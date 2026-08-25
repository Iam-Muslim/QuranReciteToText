"""ASR Runtime — Continuous streaming acoustic inference on CPU using Zipformer2 Arabic Phoneme model."""

import time
import subprocess
import json
import numpy as np
import os
import sys
import librosa

os.environ["OMP_NUM_THREADS"] = "2"
os.environ["MKL_NUM_THREADS"] = "2"
os.environ["OPENBLAS_NUM_THREADS"] = "2"

from qua_sdk.schemas import Region, Regions, Emissions
from src.phase1_transcribe.zipformer import ZipformerONNX


def run_asr_cpu(
    audio_input,
    sample_rate: int = 16000,
    model_name: str = "Base",
    profile_name: str = "auto",
    progress_callback=None,
    **kwargs,
):
    """Phase 1 Continuous Acoustic Inference using Zipformer2 Arabic Phoneme model."""
    audio_dur = 0.0

    # Load audio array or handle file path
    if isinstance(audio_input, str):
        probe_cmd = ['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1', audio_input]
        try:
            audio_dur = float(subprocess.check_output(probe_cmd).decode('utf-8').strip())
        except Exception:
            audio_dur = 0.0

        print("[*] Loading audio...")
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            audio_pcm, _ = librosa.load(audio_input, sr=sample_rate, mono=True)
    else:
        audio_pcm = audio_input.astype(np.float32)
        audio_dur = len(audio_pcm) / sample_rate
        print("[*] Loading in-memory audio...")

    if audio_dur == 0.0 and len(audio_pcm) > 0:
        audio_dur = len(audio_pcm) / sample_rate

    model = ZipformerONNX.get_instance(device="cpu")

    print(f"[*] Transcribing continuous audio stream ({audio_dur:.2f}s) with Zipformer-v3...")
    t_asr_start = time.time()

    text, phoneme_timestamps, logprobs = model.transcribe(
        audio_pcm,
        orig_sr=sample_rate,
        safe_lufs=True,
    )

    asr_time = time.time() - t_asr_start
    print(f"[*] ASR completed in {asr_time:.2f}s ({audio_dur / max(0.01, asr_time):.1f}x real-time)")

    if phoneme_timestamps:
        for p in phoneme_timestamps:
            p['word'] = p.get('phoneme', '')

    chunk_phonemes = [p['phoneme'] for p in phoneme_timestamps] if phoneme_timestamps else []

    regions_list = [Region(start_s=0.0, end_s=audio_dur)]
    tokens = [chunk_phonemes]
    asr_words_list = [(phoneme_timestamps, 0.0)]
    logprobs_list = [(logprobs, 0.0)]

    regions = Regions(regions=regions_list, audio_duration_s=audio_dur)
    emissions = Emissions(tokens=tokens)

    raw_transcriptions = [{
        "chunk": 1,
        "chunk_start_time_seconds": 0.0,
        "raw_text": text,
    }]

    with open("raw_transcription.json", "w", encoding="utf-8") as f:
        json.dump({"absolute_raw_transcriptions": raw_transcriptions}, f, ensure_ascii=False, indent=2)

    stage_metrics = {
        "segmentation": {},
        "recognition": {},
        "asr_words": asr_words_list,
        "logprobs": logprobs_list,
        "silence_intervals": [],
    }
    return (regions, emissions, stage_metrics, asr_time)
