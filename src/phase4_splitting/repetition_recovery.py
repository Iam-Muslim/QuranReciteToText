"""Non-Destructive Post-Alignment Repetition Recovery Engine with CTC Trellis Alignment.

Scans unaligned acoustic gaps within aligned Ayah segments and transcribes
only speech-active regions, strictly validating recovered words against the
canonical Ayah text and running CTC Viterbi Trellis Forced Alignment to produce
millisecond-accurate, seamless, non-flickering word and phoneme timestamps.
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from difflib import SequenceMatcher
import numpy as np

from config import (
    ENABLE_GAP_RETRANSCRIPTION,
    GAP_RETRANSCRIPTION_MIN_DURATION_S,
    GAP_RETRANSCRIPTION_ENERGY_THRESHOLD_DB,
    GAP_RETRANSCRIPTION_SPLIT_FALLBACK,
)
from src.core.quran_index import get_quran_index
from src.core.segment_types import SegmentInfo
from src.phase2_matching.normalize import get_arabic_resources
from src.phase1_transcribe.zipformer import TOKENS_PATH
from src.phase3_alignment.ctc_align import (
    _forced_align_chunk,
    _frames_to_word_times,
    _load_vocab_and_mappings,
)

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


def match_gap_phonemes_to_ayah_words(gap_phonemes: list[dict], ayah_words: list) -> list[object]:
    """Matches a sequence of transcribed phonemes in a gap strictly to canonical Ayah words."""
    if not gap_phonemes or not ayah_words:
        return []

    gap_toks = [p['phoneme'] for p in gap_phonemes]
    matched_word_objs = []
    consumed_indices = set()

    for w in ayah_words:
        w_ph = getattr(w, "phonemes", None)
        if not w_ph:
            continue
        w_len = len(w_ph)
        min_match_len = 2 if w_len >= 2 else 1

        best_match = None
        best_score = 0.0

        for start_i in range(len(gap_toks)):
            for end_i in range(start_i + 1, min(len(gap_toks) + 1, start_i + w_len + 3)):
                if any(k in consumed_indices for k in range(start_i, end_i)):
                    continue
                sub_slice = gap_toks[start_i:end_i]
                sm = SequenceMatcher(None, sub_slice, w_ph)
                ratio = sm.ratio()
                match_len = sum(b.size for b in sm.get_matching_blocks())
                if match_len >= min_match_len and ratio >= 0.65:
                    if ratio > best_score or (ratio == best_score and match_len > (best_match[3] if best_match else 0)):
                        best_score = ratio
                        best_match = (start_i, end_i - 1, sub_slice, match_len)

        if best_match is not None:
            s_i, e_i, sub_slice, _ = best_match
            for k in range(s_i, e_i + 1):
                consumed_indices.add(k)
            
            matched_word_objs.append((w, gap_phonemes[s_i]['start']))

    matched_word_objs.sort(key=lambda item: item[1])
    return [item[0] for item in matched_word_objs]


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

    resources = get_arabic_resources()
    from src.phase1_transcribe.zipformer import ZipformerONNX
    model = None
    vocab, token2id = _load_vocab_and_mappings(TOKENS_PATH)
    recovery_audit_records = []

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
        ch_ref = resources.chapter_refs.get(surah)
        if not ch_ref:
            continue
        ayah_words = [w for w in ch_ref.words if w.ayah == ayah]
        if not ayah_words:
            continue

        seg_base = float(seg.start_time or 0.0)

        # Identify physical timeline gaps between recited words
        timed_words = [w for w in seg.words if w.get("start") is not None and w.get("end") is not None]
        if not timed_words:
            continue

        gaps: list[tuple[float, float]] = []
        for i in range(len(timed_words) - 1):
            g_rel_start = float(timed_words[i]["end"])
            g_rel_end = float(timed_words[i + 1]["start"])
            if g_rel_end - g_rel_start >= GAP_RETRANSCRIPTION_MIN_DURATION_S:
                gaps.append((g_rel_start, g_rel_end))

        if not gaps:
            continue

        recovered_words_for_seg = []
        for g_rel_start, g_rel_end in gaps:
            abs_g_start = seg_base + g_rel_start
            abs_g_end = seg_base + g_rel_end

            s_idx = max(0, int(abs_g_start * sample_rate))
            e_idx = min(len(pcm), int(abs_g_end * sample_rate))
            if e_idx <= s_idx:
                continue

            gap_slice = pcm[s_idx:e_idx]
            if len(gap_slice) < int(0.2 * sample_rate):
                continue

            rms = float(np.sqrt(np.mean(np.square(gap_slice))))
            db = 20.0 * np.log10(max(rms, 1e-8))
            if db < GAP_RETRANSCRIPTION_ENERGY_THRESHOLD_DB:
                continue  # Silent breath pause — skip instantly

            if model is None:
                model = ZipformerONNX.get_instance(device="cpu")

            _text, candidate_phonemes, gap_logprobs = model.transcribe(
                gap_slice,
                orig_sr=sample_rate,
                safe_lufs=True,
            )

            if not candidate_phonemes or gap_logprobs is None or len(gap_logprobs) == 0:
                continue

            # Match candidate phonemes strictly against canonical Ayah words
            matched_words = match_gap_phonemes_to_ayah_words(candidate_phonemes, ayah_words)

            if matched_words:
                # ── RUN CTC VITERBI TRELLIS FORCED ALIGNMENT OVER GAP AUDIO ──
                # This guarantees millisecond-accurate, seamless, energy-weighted letter timestamps
                # identical to Phase 3 first-pass alignment (no flickering in UI player).
                token_ids = []
                word_token_counts = []
                for w in matched_words:
                    ids = [token2id[tok] for tok in w.phonemes if tok in token2id]
                    if not ids:
                        ids = [0]
                    token_ids.extend(ids)
                    word_token_counts.append(len(ids))

                try:
                    state_path, scores, chunk_lp, chunk_S = _forced_align_chunk(gap_logprobs, token_ids)
                    word_times = _frames_to_word_times(
                        state_path=state_path,
                        scores=scores,
                        token_ids=token_ids,
                        word_token_counts=word_token_counts,
                        chunk_start_sec=abs_g_start,
                        seg_start_time=seg_base,
                        vocab=vocab,
                        log_probs=chunk_lp,
                    )
                except Exception as e:
                    logger.warning("CTC gap alignment fallback: %s", e)
                    word_times = []

                if not word_times:
                    continue

                audit_entry = {
                    "segment": seg.segment_number,
                    "surah": surah,
                    "ayah": ayah,
                    "gap_absolute_start": round(abs_g_start, 3),
                    "gap_absolute_end": round(abs_g_end, 3),
                    "gap_duration": round(abs_g_end - abs_g_start, 3),
                    "raw_phonemes_in_gap": [p['phoneme'] for p in candidate_phonemes],
                    "recovered_words": []
                }

                for mw, wt in zip(matched_words, word_times):
                    w_start = wt.get("_start")
                    w_end = wt.get("_end")
                    if w_start is None or w_end is None:
                        continue

                    entry: dict = {
                        "word": mw.text,
                        "location": f"{mw.surah}:{mw.ayah}:{mw.word_num}",
                        "start": round(w_start, 4),
                        "end": round(w_end, 4),
                        "confidence": wt.get("_confidence", 0.90),
                        "phonemes": wt.get("_phonemes", []),
                        "is_retranscribed": True,
                        "is_recovered_repetition": True,
                    }
                    recovered_words_for_seg.append(entry)
                    audit_entry["recovered_words"].append({
                        "word": mw.text,
                        "location": f"{mw.surah}:{mw.ayah}:{mw.word_num}",
                        "absolute_start": round(seg_base + w_start, 3),
                        "absolute_end": round(seg_base + w_end, 3),
                    })

                if audit_entry["recovered_words"]:
                    recovery_audit_records.append(audit_entry)

        if recovered_words_for_seg:
            all_words = list(seg.words) + recovered_words_for_seg
            all_words.sort(key=lambda w: (w.get("start") if w.get("start") is not None else 0.0))
            seg.words = all_words
            seg.has_repeated_words = True

    # Save recovery audit records
    if recovery_audit_records:
        with open("recovered_repetitions.json", "w", encoding="utf-8") as f:
            json.dump({
                "total_recovered_gaps": len(recovery_audit_records),
                "recovered_repetition_events": recovery_audit_records
            }, f, ensure_ascii=False, indent=2)
