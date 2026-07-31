"""ASR Runtime — Orchestrates acoustic inference on CPU using Silero VAD."""

import time
import subprocess
import json
import numpy as np
import os
import sys
import urllib.request
import concurrent.futures

os.environ["OMP_NUM_THREADS"] = "2"
os.environ["MKL_NUM_THREADS"] = "2"
os.environ["OPENBLAS_NUM_THREADS"] = "2"

from qua_sdk.schemas import Audio, Region, Regions, Emissions
from src.phase2_matching.normalize import normalize_arabic


def _ensure_silero_vad_downloaded(vad_path: str):
    if not os.path.exists(vad_path):
        os.makedirs(os.path.dirname(vad_path), exist_ok=True)
        url = "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/silero_vad.onnx"
        urllib.request.urlretrieve(url, vad_path)


def run_asr_cpu(audio_input, sample_rate, model_name="Base"):
    """VAD-Based Inference with fixed terminal progress bar."""
    audio_dur = 0.0
    from qua_sdk.schemas import Emissions, Region, Regions
    from src.phase1_transcribe.fastconformer import FastConformerONNX, SILERO_VAD_ONNX_PATH
    import sherpa_onnx

    device = "cpu"
    _ensure_silero_vad_downloaded(SILERO_VAD_ONNX_PATH)

    config = sherpa_onnx.VadModelConfig()
    config.silero_vad.model = SILERO_VAD_ONNX_PATH
    config.sample_rate = sample_rate
    config.silero_vad.min_silence_duration = 0.5
    config.silero_vad.threshold = 0.15
    config.silero_vad.min_speech_duration = 0.15
    config.silero_vad.max_speech_duration = 20.0

    vad = sherpa_onnx.VoiceActivityDetector(config, buffer_size_in_seconds=30.0)
    window_size = config.silero_vad.window_size

    fc = FastConformerONNX.get_instance(device=device)

    regions_list = []
    tokens = []
    raw_transcriptions = []
    asr_words_list = []
    logprobs_list = []

    t_asr_start = time.time()
    chunk_idx = 0

    max_workers = int(os.environ.get("ASR_CHUNK_WORKERS", 1))
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=max_workers)
    futures = []

    max_processed_sec = 0.0
    sys.stdout.write("\rTranscribing:   0.0%")
    sys.stdout.flush()

    def _on_chunk_done(fut):
        nonlocal max_processed_sec
        try:
            res = fut.result()
            chunk_end = res[3] + res[6]
            if chunk_end > max_processed_sec:
                max_processed_sec = chunk_end
            pct = min(100.0, (max_processed_sec / audio_dur) * 100.0) if audio_dur > 0 else 100.0
            sys.stdout.write(f"\rTranscribing: {pct:5.1f}%")
            sys.stdout.flush()
        except Exception:
            pass

    def transcribe_chunk_task(chunk_audio, start_sec, actual_preroll_sec, idx, dur):
        text, word_timestamps, logprobs = fc.transcribe(chunk_audio, orig_sr=sample_rate)
        chunk_len_sec = len(chunk_audio) / sample_rate
        return (text, word_timestamps, logprobs, start_sec, actual_preroll_sec, idx, chunk_len_sec)

    def extract_speech_segment(segment, get_real_audio_fn):
        nonlocal chunk_idx
        start_sec = segment.start / sample_rate
        chunk_audio, actual_preroll_sec = get_real_audio_fn(segment.start, len(segment.samples))
        if len(chunk_audio) > 0:
            fut = executor.submit(transcribe_chunk_task, chunk_audio, start_sec, actual_preroll_sec, chunk_idx, audio_dur)
            fut.add_done_callback(_on_chunk_done)
            futures.append(fut)
            chunk_idx += 1

    if isinstance(audio_input, str):
        probe_cmd = ['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1', audio_input]
        try:
            audio_dur = float(subprocess.check_output(probe_cmd).decode('utf-8').strip())
        except Exception:
            audio_dur = 0.0

        command = [
            'ffmpeg', '-v', 'quiet',
            '-i', audio_input,
            '-f', 'f32le', '-acodec', 'pcm_f32le', '-ac', '1', '-ar', str(sample_rate),
            'pipe:1'
        ]
        try:
            process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        except FileNotFoundError:
            raise RuntimeError("ffmpeg not found in system PATH.")

        block_duration = 0.5
        chunk_samples = int(block_duration * sample_rate)
        bytes_per_sample = 4
        chunk_bytes = chunk_samples * bytes_per_sample

        pcm_buffer = np.array([], dtype=np.float32)
        context_buffer = np.array([], dtype=np.float32)
        total_samples_read = 0
        max_context_samples = int(60.0 * sample_rate)

        def get_real_audio_stream(seg_start, seg_length):
            preroll_samples = int(0.5 * sample_rate)
            postroll_samples = int(0.5 * sample_rate)
            target_start = max(0, seg_start - preroll_samples)
            target_end = seg_start + seg_length + postroll_samples

            context_start_idx = max(0, total_samples_read - len(context_buffer))
            idx_start = max(0, target_start - context_start_idx)
            idx_end = max(0, target_end - context_start_idx)

            if idx_end > len(context_buffer):
                idx_end = len(context_buffer)

            real_chunk = context_buffer[idx_start:idx_end]
            actual_preroll_sec = (seg_start - (context_start_idx + idx_start)) / sample_rate
            return real_chunk, actual_preroll_sec

        while True:
            new_bytes = process.stdout.read(chunk_bytes)
            if not new_bytes:
                break

            samples = np.frombuffer(new_bytes, dtype=np.float32)
            pcm_buffer = np.concatenate((pcm_buffer, samples))
            context_buffer = np.concatenate((context_buffer, samples))
            if len(context_buffer) > max_context_samples:
                context_buffer = context_buffer[-max_context_samples:]
            total_samples_read += len(samples)

            while len(pcm_buffer) >= window_size:
                vad.accept_waveform(pcm_buffer[:window_size])
                pcm_buffer = pcm_buffer[window_size:]

                while not vad.empty():
                    extract_speech_segment(vad.front, get_real_audio_stream)
                    vad.pop()

        if len(pcm_buffer) > 0:
            vad.accept_waveform(pcm_buffer)

        vad.flush()
        while not vad.empty():
            extract_speech_segment(vad.front, get_real_audio_stream)
            vad.pop()

        process.stdout.close()
        process.terminate()
        process.wait()

    else:
        audio_dur = len(audio_input) / sample_rate
        window_size = config.silero_vad.window_size
        samples = np.ascontiguousarray(audio_input, dtype=np.float32)

        def get_real_audio_mem(seg_start, seg_length):
            preroll_samples = int(0.5 * sample_rate)
            postroll_samples = int(0.5 * sample_rate)
            idx_start = max(0, seg_start - preroll_samples)
            idx_end = seg_start + seg_length + postroll_samples
            if idx_end > len(audio_input):
                idx_end = len(audio_input)
            real_chunk = audio_input[idx_start:idx_end]
            actual_preroll_sec = (seg_start - idx_start) / sample_rate
            return real_chunk, actual_preroll_sec

        while len(samples) > window_size:
            vad.accept_waveform(samples[:window_size])
            samples = samples[window_size:]
            while not vad.empty():
                extract_speech_segment(vad.front, get_real_audio_mem)
                vad.pop()

        if len(samples) > 0:
            vad.accept_waveform(samples)

        vad.flush()
        while not vad.empty():
            extract_speech_segment(vad.front, get_real_audio_mem)
            vad.pop()

    for fut in futures:
        text, word_timestamps, logprobs, start_sec, actual_preroll_sec, idx, _ = fut.result()
        raw_transcriptions.append({
            "chunk": idx + 1,
            "chunk_start_time_seconds": start_sec,
            "raw_text": text,
        })

        if word_timestamps:
            for w in word_timestamps:
                w['start'] = max(0.0, w['start'] - actual_preroll_sec + start_sec)
                w['end'] = max(0.0, w['end'] - actual_preroll_sec + start_sec)

            if regions_list:
                prev_end = regions_list[-1].end_s
                filtered_words = [w for w in word_timestamps if w['start'] >= prev_end - 0.05]
                if not filtered_words:
                    continue
                word_timestamps = filtered_words

            chunk_text = " ".join([w['word'] for w in word_timestamps])
            abs_start_time = word_timestamps[0]['start']
            abs_end_time = word_timestamps[-1]['end']

            regions_list.append(Region(start_s=abs_start_time, end_s=abs_end_time))
            norm_text = normalize_arabic(chunk_text)
            tokens.append(list(norm_text) + [' '])
            asr_words_list.append((word_timestamps, start_sec))
            logprobs_list.append((logprobs, max(0.0, start_sec - actual_preroll_sec)))

    executor.shutdown(wait=True)
    sys.stdout.write("\rTranscribing: 100.0%\n")
    sys.stdout.flush()

    asr_time = time.time() - t_asr_start
    regions = Regions(regions=regions_list, audio_duration_s=audio_dur)
    emissions = Emissions(tokens=tokens)

    # Debug file dump disabled to avoid triggering dev server reloads
    with open("raw_transcription.json", "w", encoding="utf-8") as f:
        json.dump({"absolute_raw_transcriptions": raw_transcriptions}, f, ensure_ascii=False, indent=2)

    stage_metrics = {
        "segmentation": {},
        "recognition": {},
        "asr_words": asr_words_list,
        "logprobs": logprobs_list
    }
    return (regions, emissions, stage_metrics, asr_time)