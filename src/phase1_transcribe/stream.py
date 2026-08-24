"""ASR Runtime — Orchestrates acoustic inference on CPU using Zipformer2 Arabic Phoneme model."""

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

from qua_sdk.schemas import Region, Regions, Emissions
from src.phase1_transcribe.zipformer import ZipformerONNX
from src.phase1_transcribe.silence import detect_acoustic_silences, detect_non_silent_chunks


def run_asr_cpu(
    audio_input,
    sample_rate: int = 16000,
    model_name: str = "Base",
    profile_name: str = "auto",
    progress_callback=None,
    min_silence_ms: int = 1200,
    pad_ms: int = 600,
):
    """Phase 1 Acoustic Inference using Zipformer2 Arabic Phoneme model & Munajjam PR #65 silence engine."""
    audio_dur = 0.0

    # Load audio array or handle file path
    if isinstance(audio_input, str):
        probe_cmd = ['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1', audio_input]
        try:
            audio_dur = float(subprocess.check_output(probe_cmd).decode('utf-8').strip())
        except Exception:
            audio_dur = 0.0

        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            audio_pcm, _ = librosa.load(audio_input, sr=sample_rate, mono=True)
    else:
        audio_pcm = audio_input.astype(np.float32)
        audio_dur = len(audio_pcm) / sample_rate

    model = ZipformerONNX.get_instance(device="cpu")

    # Step 1: Detect non-silent speech chunks using non-neural gentle engine
    expected_chunks = max(1, int(audio_dur / 25.0))
    chunk_ms_list = detect_non_silent_chunks(
        audio_pcm,
        min_silence_len=min_silence_ms,
        silence_thresh=-45,
        adaptive=False,
        expected_chunks=expected_chunks,
        sample_rate=sample_rate
    )
    silence_intervals = detect_acoustic_silences(
        audio_pcm,
        min_silence_len_ms=min_silence_ms,
        sample_rate=sample_rate,
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

    # --- Gap-clamped adaptive padding ---
    MAX_PAD_MS = pad_ms
    n_chunks = len(chunk_ms_list)

    preroll_samples_list = []
    postroll_samples_list = []
    for idx, (start_ms, end_ms) in enumerate(chunk_ms_list):
        if idx > 0:
            prev_end_ms = chunk_ms_list[idx - 1][1]
            gap_before_ms = start_ms - prev_end_ms
        else:
            gap_before_ms = MAX_PAD_MS * 2

        if idx < n_chunks - 1:
            next_start_ms = chunk_ms_list[idx + 1][0]
            gap_after_ms = next_start_ms - end_ms
        else:
            gap_after_ms = MAX_PAD_MS * 2

        preroll_ms = min(MAX_PAD_MS, gap_before_ms // 2)
        postroll_ms = min(MAX_PAD_MS, gap_after_ms // 2)
        preroll_samples_list.append(int((preroll_ms / 1000.0) * sample_rate))
        postroll_samples_list.append(int((postroll_ms / 1000.0) * sample_rate))

    sys.stdout.write("\rTranscribing:   0.0%")
    sys.stdout.flush()

    def transcribe_chunk_task(chunk_audio, start_sec, idx):
        text, phoneme_timestamps, logprobs = model.transcribe(chunk_audio, orig_sr=sample_rate, safe_lufs=True)
        return (text, phoneme_timestamps, logprobs, start_sec, idx)

    for idx, (start_ms, end_ms) in enumerate(chunk_ms_list):
        preroll = preroll_samples_list[idx]
        postroll = postroll_samples_list[idx]
        start_sample = max(0, int((start_ms / 1000.0) * sample_rate) - preroll)
        end_sample = min(len(audio_pcm), int((end_ms / 1000.0) * sample_rate) + postroll)
        actual_start_sec = start_sample / sample_rate

        chunk_audio = audio_pcm[start_sample:end_sample]

        # Intro split fix: For the first chunk, scan the first 10 seconds to find pause dip
        if start_sample == 0 and len(chunk_audio) > 0:
            scan_end = min(len(chunk_audio), int(10.0 * sample_rate))
            frame_hop = int(0.05 * sample_rate)
            min_rms = float('inf')
            split_sample = -1
            for f_start in range(int(1.0 * sample_rate), scan_end - frame_hop, frame_hop):
                frame = chunk_audio[f_start:f_start + frame_hop]
                rms = float(np.sqrt(np.mean(np.square(frame))))
                if rms < min_rms:
                    min_rms = rms
                    split_sample = f_start
            chunk_mean_rms = float(np.sqrt(np.mean(np.square(chunk_audio[:scan_end]))))
            if split_sample > 0 and min_rms < chunk_mean_rms * 0.10:
                intro_audio = chunk_audio[:split_sample]
                if len(intro_audio) > 0:
                    fut_intro = executor.submit(transcribe_chunk_task, intro_audio, actual_start_sec, idx)
                    futures.append(fut_intro)
                recite_start_sec = split_sample / sample_rate
                chunk_audio = chunk_audio[split_sample:]
                actual_start_sec = recite_start_sec

        if len(chunk_audio) > 0:
            fut = executor.submit(transcribe_chunk_task, chunk_audio, actual_start_sec, idx)
            futures.append(fut)

    for i, fut in enumerate(futures):
        text, phoneme_timestamps, logprobs, start_sec, idx = fut.result()

        pct = min(100.0, ((i + 1) / max(1, len(futures))) * 100.0)
        sys.stdout.write(f"\rTranscribing: {pct:5.1f}%")
        sys.stdout.flush()
        if progress_callback:
            try:
                progress_callback(pct, f"Transcribing audio: {pct:.1f}%")
            except Exception:
                pass

        raw_transcriptions.append({
            "chunk": idx + 1,
            "chunk_start_time_seconds": start_sec,
            "raw_text": text,
        })

        if phoneme_timestamps:
            for p in phoneme_timestamps:
                p['start'] = max(0.0, p['start'] + start_sec)
                p['end'] = max(0.0, p['end'] + start_sec)
                p['word'] = p.get('phoneme', '')

            abs_start_time = phoneme_timestamps[0]['start']
            abs_end_time = phoneme_timestamps[-1]['end']

            regions_list.append(Region(start_s=abs_start_time, end_s=abs_end_time))
            chunk_phonemes = [p['phoneme'] for p in phoneme_timestamps]
            tokens.append(chunk_phonemes)
            asr_words_list.append((phoneme_timestamps, start_sec))
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
        "logprobs": logprobs_list,
        "silence_intervals": silence_intervals,
    }
    return (regions, emissions, stage_metrics, asr_time)
