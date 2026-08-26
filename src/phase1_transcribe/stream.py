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

# In Classical Arabic / Tajweed, every utterance MUST begin with a voweled
# consonant (متحرك).  Madd, Ghunnah, Sukoon, bare vowels, and bare consonants
# can NEVER start an utterance.  Splitting is only allowed before one of these.
_SINGLE_VOWELED = {
    'ءَ', 'ءُ', 'ءِ', 'بَ', 'بُ', 'بِ', 'تَ', 'تُ', 'تِ', 'ثَ', 'ثُ', 'ثِ',
    'جَ', 'جُ', 'جِ', 'حَ', 'حُ', 'حِ', 'خَ', 'خُ', 'خِ', 'دَ', 'دُ', 'دِ',
    'ذَ', 'ذُ', 'ذِ', 'رَ', 'رُ', 'رِ', 'زَ', 'زُ', 'زِ', 'سَ', 'سُ', 'سِ',
    'شَ', 'شُ', 'شِ', 'صَ', 'صُ', 'صِ', 'ضَ', 'ضُ', 'ضِ', 'طَ', 'طُ', 'طِ',
    'ظَ', 'ظُ', 'ظِ', 'عَ', 'عُ', 'عِ', 'غَ', 'غُ', 'غِ', 'فَ', 'فُ', 'فِ',
    'قَ', 'قُ', 'قِ', 'كَ', 'كُ', 'كِ', 'لَ', 'لُ', 'لِ', 'مَ', 'مُ', 'مِ',
    'نَ', 'نُ', 'نِ', 'هَ', 'هُ', 'هِ', 'وَ', 'وُ', 'وِ', 'يَ', 'يُ', 'يِ',
}

# Solar-letter doubled onsets (after Al-Wasl: الرحمن -> ررَ, الصراط -> صصِ)
_SOLAR_VOWELED = {
    'تتَ', 'تتُ', 'تتِ', 'ثثَ', 'ثثُ', 'ثثِ', 'ددَ', 'ددُ', 'ددِ',
    'ذذَ', 'ذذُ', 'ذذِ', 'ررَ', 'ررُ', 'ررِ', 'ززَ', 'ززُ', 'ززِ',
    'سسَ', 'سسُ', 'سسِ', 'ششَ', 'ششُ', 'ششِ', 'صصَ', 'صصُ', 'صصِ',
    'ضضَ', 'ضضُ', 'ضضِ', 'ططَ', 'ططُ', 'ططِ', 'ظظَ', 'ظظُ', 'ظظِ',
    'للَ', 'للُ', 'للِ', 'ننَ', 'ننُ', 'ننِ',
}

_VALID_STARTERS = _SINGLE_VOWELED | _SOLAR_VOWELED


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

    # ── Segment the continuous phoneme stream at natural breath pauses ──
    # A split is allowed ONLY when:
    #   1. The acoustic gap between consecutive phonemes >= 2.0 seconds
    #   2. The NEXT phoneme is a valid Arabic word-starter (voweled consonant)
    # This is linguistically guaranteed to never cut a word mid-syllable.
    min_pause_s = 2.0

    if phoneme_timestamps and len(phoneme_timestamps) > 1:
        splits = [0]
        for i in range(len(phoneme_timestamps) - 1):
            gap = phoneme_timestamps[i + 1]["start"] - phoneme_timestamps[i]["end"]
            if gap >= min_pause_s:
                next_phoneme = phoneme_timestamps[i + 1]["phoneme"]
                if next_phoneme in _VALID_STARTERS:
                    splits.append(i + 1)
        if splits[-1] != len(phoneme_timestamps):
            splits.append(len(phoneme_timestamps))

        regions_list = []
        tokens = []
        asr_words_list = []
        logprobs_list = []
        raw_transcriptions = []

        for s_i, e_i in zip(splits[:-1], splits[1:]):
            sub_pts = phoneme_timestamps[s_i:e_i]
            sub_toks = [p["phoneme"] for p in sub_pts]
            u_start = float(sub_pts[0]["start"])
            u_end = float(sub_pts[-1]["end"])

            regions_list.append(Region(start_s=round(u_start, 3), end_s=round(u_end, 3)))
            tokens.append(sub_toks)
            asr_words_list.append((sub_pts, u_start))
            
            raw_transcriptions.append({
                "chunk": len(raw_transcriptions) + 1,
                "chunk_start_time_seconds": round(u_start, 3),
                "chunk_end_time_seconds": round(u_end, 3),
                "raw_text": "".join(sub_toks)
            })

            if logprobs is not None and len(logprobs) > 0:
                frame_start = max(0, int(u_start * 25.0) - 2)
                frame_end = min(len(logprobs), int(np.ceil(u_end * 25.0)) + 3)
                logprobs_list.append((logprobs[frame_start:frame_end], frame_start * 0.04))
            else:
                logprobs_list.append((None, u_start))
    else:
        chunk_phonemes = [p['phoneme'] for p in phoneme_timestamps] if phoneme_timestamps else []
        regions_list = [Region(start_s=0.0, end_s=audio_dur)]
        tokens = [chunk_phonemes]
        asr_words_list = [(phoneme_timestamps, 0.0)]
        logprobs_list = [(logprobs, 0.0)]
        raw_transcriptions = [{
            "chunk": 1,
            "chunk_start_time_seconds": 0.0,
            "chunk_end_time_seconds": audio_dur,
            "raw_text": "".join(chunk_phonemes)
        }]

    regions = Regions(regions=regions_list, audio_duration_s=audio_dur)
    emissions = Emissions(tokens=tokens)

    # Write raw transcription for audit
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
