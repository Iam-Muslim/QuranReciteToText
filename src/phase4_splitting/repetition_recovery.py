"""Non-Destructive Post-Alignment Repetition Recovery Engine.

Scans unaligned acoustic gaps within aligned Ayah segments and transcribes
only speech-active regions, strictly validating recovered words against the
canonical Ayah text before non-destructively inserting them into the segment.
"""

from __future__ import annotations

import logging
from collections import defaultdict
import numpy as np

from config import (
    ENABLE_GAP_RETRANSCRIPTION,
    GAP_RETRANSCRIPTION_MIN_DURATION_S,
    GAP_RETRANSCRIPTION_ENERGY_THRESHOLD_DB,
    GAP_RETRANSCRIPTION_SPLIT_FALLBACK,
)
from src.core.quran_index import get_quran_index
from src.core.segment_types import SegmentInfo
from src.phase2_matching.normalize import normalize_arabic

logger = logging.getLogger(__name__)


def _find_silence_dip(audio_slice: np.ndarray, sample_rate: int = 16000) -> int:
    """Finds the sample index of the local acoustic energy minimum (silence dip)."""
    win = int(0.1 * sample_rate)
    if len(audio_slice) < 3 * win:
        return len(audio_slice) // 2
    energies = [
        float(np.sum(np.square(audio_slice[i : i + win])))
        for i in range(win, len(audio_slice) - 2 * win, win // 2)
    ]
    if not energies:
        return len(audio_slice) // 2
    min_idx = int(np.argmin(energies))
    return win + min_idx * (win // 2) + (win // 2)


def recover_unaligned_repetitions(
    segments: list[SegmentInfo],
    audio_pcm: np.ndarray | str | None,
    sample_rate: int = 16000,
) -> None:
    """Safely recovers repeated or missed words from speech gaps without altering baseline alignment."""
    if not ENABLE_GAP_RETRANSCRIPTION or not segments:
        return

    pcm = None
    if isinstance(audio_pcm, str):
        try:
            import librosa
            pcm, _ = librosa.load(audio_pcm, sr=sample_rate, mono=True)
        except Exception as e:
            logger.warning("Failed to load audio for repetition recovery: %s", e)
            return
    elif audio_pcm is not None:
        pcm = np.asarray(audio_pcm, dtype=np.float32)

    if pcm is None or len(pcm) == 0:
        return

    qi = get_quran_index()
    from src.phase1_transcribe.zipformer import ZipformerONNX
    model = None

    for seg in segments:
        ref = seg.matched_ref
        if not seg.words or not ref or ":" not in ref:
            continue

        try:
            parts = ref.split("-")[0].split(":")
            surah, ayah = int(parts[0]), int(parts[1])
        except (ValueError, IndexError):
            continue

        # Get canonical reference words for this specific Ayah
        canonical_raw = qi.get_ayah_text(surah, ayah)
        if not canonical_raw:
            continue
        canonical_words_list = canonical_raw.split()
        canonical_normalized_map: dict[str, list[tuple[str, str]]] = defaultdict(list)
        for w_idx, c_word in enumerate(canonical_words_list, 1):
            norm = normalize_arabic(c_word).strip()
            loc = f"{surah}:{ayah}:{w_idx}"
            canonical_normalized_map[norm].append((c_word, loc))

        # Identify physical timeline gaps between recited words
        timed_words = [w for w in seg.words if w.get("start") is not None and w.get("end") is not None]
        if not timed_words:
            continue

        gaps: list[tuple[float, float]] = []
        for i in range(len(timed_words) - 1):
            g_start = float(timed_words[i]["end"])
            g_end = float(timed_words[i + 1]["start"])
            if g_end - g_start >= GAP_RETRANSCRIPTION_MIN_DURATION_S:
                gaps.append((g_start, g_end))

        if not gaps:
            continue

        recovered_words_for_seg = []
        for g_start, g_end in gaps:
            s_idx = max(0, int(g_start * sample_rate))
            e_idx = min(len(pcm), int(g_end * sample_rate))
            if e_idx <= s_idx:
                continue

            gap_slice = pcm[s_idx:e_idx]
            if len(gap_slice) < int(0.2 * sample_rate):
                continue

            rms = float(np.sqrt(np.mean(np.square(gap_slice))))
            db = 20.0 * np.log10(max(rms, 1e-8))
            if db < GAP_RETRANSCRIPTION_ENERGY_THRESHOLD_DB:
                continue  # Silent breath pause — skip instantly without model inference

            if model is None:
                model = ZipformerONNX.get_instance(device="cpu")

            _text, candidate_words, _logprobs = model.transcribe(
                gap_slice,
                orig_sr=sample_rate,
                safe_lufs=True,
            )

            if not candidate_words and GAP_RETRANSCRIPTION_SPLIT_FALLBACK and len(gap_slice) >= int(2.0 * sample_rate):
                dip_idx = _find_silence_dip(gap_slice, sample_rate)
                sub1 = gap_slice[:dip_idx]
                sub2 = gap_slice[dip_idx:]
                _t1, w1, _ = model.transcribe(sub1, orig_sr=sample_rate, safe_lufs=True)
                _t2, w2, _ = model.transcribe(sub2, orig_sr=sample_rate, safe_lufs=True)
                combined = []
                for w in (w1 or []):
                    w["start"] += 0.0
                    w["end"] += 0.0
                    combined.append(w)
                for w in (w2 or []):
                    w["start"] += dip_idx / sample_rate
                    w["end"] += dip_idx / sample_rate
                    combined.append(w)
                candidate_words = combined

            if not candidate_words:
                continue

            # Contextually match candidate words strictly to canonical Ayah vocabulary
            for cand in candidate_words:
                cand_text = cand.get("word", cand.get("phoneme", "")).strip()
                cand_norm = normalize_arabic(cand_text).strip()
                if cand_norm in canonical_normalized_map:
                    exact_text, loc = canonical_normalized_map[cand_norm][0]
                    entry: dict = {
                        "word": exact_text,
                        "location": loc,
                        "start": round(g_start + float(cand["start"]), 4),
                        "end": round(g_start + float(cand["end"]), 4),
                        "is_retranscribed": True,
                    }
                    if "confidence" in cand:
                        entry["confidence"] = round(float(cand["confidence"]), 2)
                    if "phonemes" in cand:
                        entry["phonemes"] = [
                            {
                                "phoneme": p.get("phoneme", ""),
                                "start": round(g_start + float(p["start"]), 4),
                                "end": round(g_start + float(p["end"]), 4),
                            }
                            for p in cand["phonemes"]
                        ]
                    recovered_words_for_seg.append(entry)

        if recovered_words_for_seg:
            all_words = list(seg.words) + recovered_words_for_seg
            all_words.sort(key=lambda w: (w.get("start") if w.get("start") is not None else 0.0))
            seg.words = all_words
            seg.has_repeated_words = True
