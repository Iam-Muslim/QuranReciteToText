"""ASR Runtime — Orchestrates acoustic inference on CPU using Munajjam PR #65 Adaptive Engine."""

import time
import subprocess
import json
import numpy as np
import os
import sys
import librosa
import concurrent.futures

os.environ["OMP_NUM_THREADS"] = "2"
os.environ["MKL_NUM_THREADS"] = "2"
os.environ["OPENBLAS_NUM_THREADS"] = "2"

from qua_sdk.schemas import Audio, Region, Regions, Emissions
from src.phase2_matching.normalize import normalize_arabic
from src.phase1_transcribe.fastconformer import FastConformerONNX
from src.phase1_transcribe.silence import detect_non_silent_chunks


def run_asr_cpu(audio_input, sample_rate: int = 16000, model_name: str = "Base", profile_name: str = "auto"):
    """Phase 1 Acoustic Inference using Munajjam PR #65 Adaptive Silence Detection Engine."""
    audio_dur = 0.0

    # Load audio array or handle file path
    if isinstance(audio_input, str):
        probe_cmd = ['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1', audio_input]
        try:
            audio_dur = float(subprocess.check_output(probe_cmd).decode('utf-8').strip())
        except Exception:
            audio_dur = 0.0

        audio_pcm, _ = librosa.load(audio_input, sr=sample_rate, mono=True)
    else:
        audio_pcm = audio_input.astype(np.float32)
        audio_dur = len(audio_pcm) / sample_rate

    fc = FastConformerONNX.get_instance(device="cpu")

    # Step 1: Detect non-silent speech chunks using Munajjam PR #65 Adaptive Relaxation Engine
    expected_chunks = max(3, int(audio_dur / 8.0))
    chunk_ms_list = detect_non_silent_chunks(
        audio_pcm,
        min_silence_len=300,
        silence_thresh=-30,
        adaptive=True,
        expected_chunks=expected_chunks,
        min_chunks_ratio=0.5,
        sample_rate=sample_rate
    )

    regions_list = []
    tokens = []
    raw_transcriptions = []
    asr_words_list = []
    logprobs_list = []

    t_asr_start = time.time()
    max_workers = int(os.environ.get("ASR_CHUNK_WORKERS", 4))
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=max_workers)
    futures = []

    pad_samples = int(0.20 * sample_rate)  # 200ms preroll/postroll context padding

    sys.stdout.write("\rTranscribing:   0.0%")
    sys.stdout.flush()

    def transcribe_chunk_task(chunk_audio, start_sec, idx):
        text, word_timestamps, logprobs = fc.transcribe(chunk_audio, orig_sr=sample_rate, safe_lufs=True)
        return (text, word_timestamps, logprobs, start_sec, idx)

    for idx, (start_ms, end_ms) in enumerate(chunk_ms_list):
        start_sample = max(0, int((start_ms / 1000.0) * sample_rate) - pad_samples)
        end_sample = min(len(audio_pcm), int((end_ms / 1000.0) * sample_rate) + pad_samples)
        actual_start_sec = start_sample / sample_rate

        chunk_audio = audio_pcm[start_sample:end_sample]
        if len(chunk_audio) > 0:
            fut = executor.submit(transcribe_chunk_task, chunk_audio, actual_start_sec, idx)
            futures.append(fut)

    for i, fut in enumerate(futures):
        text, word_timestamps, logprobs, start_sec, idx = fut.result()

        pct = min(100.0, ((i + 1) / max(1, len(futures))) * 100.0)
        sys.stdout.write(f"\rTranscribing: {pct:5.1f}%")
        sys.stdout.flush()

        raw_transcriptions.append({
            "chunk": idx + 1,
            "chunk_start_time_seconds": start_sec,
            "raw_text": text,
        })

        if word_timestamps:
            for w in word_timestamps:
                w['start'] = max(0.0, w['start'] + start_sec)
                w['end'] = max(0.0, w['end'] + start_sec)

            chunk_text = " ".join([w['word'] for w in word_timestamps])
            abs_start_time = word_timestamps[0]['start']
            abs_end_time = word_timestamps[-1]['end']

            regions_list.append(Region(start_s=abs_start_time, end_s=abs_end_time))
            norm_text = normalize_arabic(chunk_text)
            tokens.append(list(norm_text) + [' '])
            asr_words_list.append((word_timestamps, start_sec))
            logprobs_list.append((logprobs, max(0.0, start_sec)))

    executor.shutdown(wait=True)
    sys.stdout.write("\rTranscribing: 100.0%\n")
    sys.stdout.flush()

    asr_time = time.time() - t_asr_start
    regions = Regions(regions=regions_list, audio_duration_s=audio_dur)
    emissions = Emissions(tokens=tokens)

    with open("raw_transcription.json", "w", encoding="utf-8") as f:
        json.dump({"absolute_raw_transcriptions": raw_transcriptions}, f, ensure_ascii=False, indent=2)

    stage_metrics = {
        "segmentation": {},
        "recognition": {},
        "asr_words": asr_words_list,
        "logprobs": logprobs_list
    }
    return (regions, emissions, stage_metrics, asr_time)