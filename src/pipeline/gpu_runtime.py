"""GPU lease runtime — lease-decorated SDK stage calls, duration estimators,
per-request state reset, and the startup AOTI compilation probe."""
import time

from config import get_vad_duration, get_asr_duration, ZEROGPU_MAX_DURATION
from qua_sdk.schemas import Audio, Region, Regions
from src.pipeline.fastconformer_onnx import transcribe_fastconformer_onnx_with_logprobs
from src.pipeline.arabic_matching import normalize_arabic

def _reset_request_state():
    pass

def _capture_vram_safely():
    return 0.0, 0.0


def run_vad_and_asr_gpu(audio, sample_rate, model_name="Base", fast_mode=False, device="cpu"):
    """Single CPU run: Custom overlap inference + FastConformer recognition.
    
    Bypasses VAD entirely to process audio continuously in 30-second
    overlapping chunks, eliminating mid-word cuts and lost silences.
    """
    from qua_sdk.schemas import Emissions, Region, Regions
    
    t_lease_start = time.time()
    
    chunk_dur = 30.0
    step_dur = 25.0 if fast_mode else 20.0
    overlap = chunk_dur - step_dur
    cut_margin = overlap / 2.0
    
    audio_dur = len(audio) / sample_rate
    
    # Build all chunk start times up-front
    chunk_starts = []
    t = 0.0
    while t < audio_dur:
        chunk_starts.append(t)
        t += step_dur
    
    t_asr_start = time.time()
    
    fc = transcribe_fastconformer_onnx_with_logprobs.__self__ if hasattr(
        transcribe_fastconformer_onnx_with_logprobs, '__self__') else None

    # Instantiate once (avoids repeated model loads)
    from src.pipeline.fastconformer_onnx import FastConformerONNX
    fc = FastConformerONNX.get_instance(fast_mode=fast_mode, device=device)

    # ── Phase 1: slice all audio chunks ──────────────────────────────────────
    audio_chunks = []
    valid_chunk_starts = []
    for start_s in chunk_starts:
        end_s = min(start_s + chunk_dur, audio_dur)
        start_idx = int(start_s * sample_rate)
        end_idx   = int(end_s   * sample_rate)
        audio_chunks.append(audio[start_idx:end_idx])
        valid_chunk_starts.append(start_s)

    # ── Phase 2: ONE batched ONNX forward pass for ALL chunks ─────────────────
    # Instead of 43 sequential session.run() calls (each with GPU round-trip
    # overhead), stack all mel features into [B, 80, T_max] and run once.
    # Expected speedup: 3-5× for a 14-minute audio on DML/CUDA.
    batch_results = fc.transcribe_batch(audio_chunks)
    # batch_results[i] = (text, word_timestamps_relative, logprobs)

    # ── Phase 3: safe-zone filtering + absolute time conversion ──────────────
    regions_list     = []
    tokens           = []
    raw_transcriptions = []
    logprobs_list    = []

    for i, (start_s, (text, word_timestamps, logprobs)) in enumerate(
            zip(valid_chunk_starts, batch_results)):

        filtered_words = []
        for w in word_timestamps:
            rel_start = w['start']
            if i == 0:
                keep = (rel_start < chunk_dur - cut_margin)
            elif i == len(valid_chunk_starts) - 1:
                keep = (rel_start >= cut_margin)
            else:
                keep = (cut_margin <= rel_start < chunk_dur - cut_margin)
            if keep:
                filtered_words.append(w)

        if not filtered_words:
            continue

        chunk_text = " ".join([w['word'] for w in filtered_words])
        abs_start_time = start_s + filtered_words[0]['start']
        abs_end_time   = start_s + filtered_words[-1]['end']

        regions_list.append(Region(start_s=abs_start_time, end_s=abs_end_time))

        abs_words = [
            {"word": w["word"], "start": start_s + w["start"], "end": start_s + w["end"]}
            for w in filtered_words
        ]
        raw_transcriptions.append({
            "segment":    len(raw_transcriptions) + 1,
            "start_time": abs_start_time,
            "end_time":   abs_end_time,
            "text":       chunk_text,
            "words":      abs_words,
        })

        norm_text = normalize_arabic(chunk_text)
        tokens.append(list(norm_text) + [' '])
        logprobs_list.append((logprobs, start_s))

    regions  = Regions(regions=regions_list, audio_duration_s=audio_dur)
    emissions = Emissions(tokens=tokens)

    import json
    with open("raw_transcription.json", "w", encoding="utf-8") as f:
        json.dump({"transcriptions": raw_transcriptions}, f, ensure_ascii=False, indent=2)

    vad_gpu_time = 0.0
    asr_gpu_time = time.time() - t_asr_start

    stage_metrics = {"segmentation": {}, "recognition": {}, "logprobs": logprobs_list}
    return (regions, emissions, stage_metrics,
            vad_gpu_time, asr_gpu_time, 0.0, 0.0)


def run_phoneme_asr_gpu(audio, sample_rate, intervals, model_name="Base", device="cpu"):
    """Standalone recognition CPU.

    Returns (emissions, rec_metrics, asr_gpu_time, peak_vram, reserved_vram).
    """
    audio_obj = Audio.from_array(audio, sample_rate)
    regions = Regions(
        regions=[Region(start_s=float(s), end_s=float(e)) for s, e in intervals],
        audio_duration_s=len(audio) / sample_rate,
    )

    t_asr_start = time.time()
    from qua_sdk.schemas import Emissions
    tokens = []
    raw_transcriptions = []
    
    # Process each segmented region using FastConformer
    for reg in regions.regions:
        start_idx = int(reg.start_s * sample_rate)
        end_idx = int(reg.end_s * sample_rate)
        seg_audio = audio[start_idx:end_idx]
        
        text, word_timestamps, logprobs = transcribe_fastconformer_onnx_with_logprobs(seg_audio, device=device)
        abs_words = []
        for w in word_timestamps:
            abs_words.append({
                "word": w["word"],
                "start": reg.start_s + w["start"],
                "end": reg.start_s + w["end"]
            })
            
        raw_transcriptions.append({
            "segment": len(raw_transcriptions) + 1,
            "start_time": reg.start_s,
            "end_time": reg.end_s,
            "text": text,
            "words": abs_words
        })
        text = normalize_arabic(text)
        tokens.append(list(text) + [' '])
        
    import json
    with open("raw_transcription.json", "w", encoding="utf-8") as f:
        json.dump({"transcriptions": raw_transcriptions}, f, ensure_ascii=False, indent=2)
        
    emissions = Emissions(tokens=tokens)
    asr_gpu_time = time.time() - t_asr_start
    rec_metrics = {}

    peak_vram, reserved_vram = _capture_vram_safely()

    return emissions, rec_metrics, asr_gpu_time, peak_vram, reserved_vram

