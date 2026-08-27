"""Canonical 1-Ayah = 1-Segment Aggregator & Timestamp Smoothing.

Transforms raw CTC-aligned word sequences into strict 1-to-1 canonical Ayah segments:
- Every distinct recited (Surah, Ayah) forms exactly 1 segment.
- Cross-chunk and mid-ayah pause fragments are seamlessly assembled into complete verses.
- Intra-verse repetitions (breath repeats) are organized chronologically with repetition metadata.
- Opening specials (Isti'adha, Basmala) are preserved as distinct cards.
- Word timestamps and letter-level phoneme arrays are preserved with microsecond precision.
"""

from __future__ import annotations
import math
from typing import Any
import numpy as np
from src.core.segment_types import SegmentInfo
from src.core.quran_index import get_quran_index, parse_location_key

_SPECIAL_TEXTS = {
    "Isti'adha": "أَعُوذُ بِٱللَّهِ مِنَ ٱلشَّيْطَـٰنِ ٱلرَّجِيمِ",
    "Basmala": "بِسْمِ ٱللَّهِ ٱلرَّحْمَـٰنِ ٱلرَّحِيمِ",
}


def aggregate_by_canonical_ayah(segments: list[SegmentInfo]) -> list[SegmentInfo]:
    """Aggregates all CTC-aligned words into exact 1-to-1 canonical Ayah segments.

    Guarantees:
      1. Exactly 1 segment per distinct recited (Surah, Ayah).
      2. Assembles mid-verse pauses/chunks naturally into complete verses.
      3. Preserves all chronological word timestamps and letter-level phonemes with frame-perfect sync.
      4. Detects within-verse repetitions (breath repeats) and stamps has_repeated_words=True.
      5. Sets matched_text to canonical Medina Mushaf verse text from QuranIndex.
    """
    if not segments:
        return []

    qi = get_quran_index()

    # Step 1: Collect chronological word stream with absolute audio timestamps
    verse_groups: list[dict] = []
    current_group: dict | None = None

    for seg in segments:
        ref = str(seg.matched_ref or "")
        is_special = ref in ("Isti'adha", "Basmala")
        seg_base = seg.start_time if seg.start_time is not None else 0.0

        # Case A: Special segment (Isti'adha or Basmala)
        if is_special and (not seg.words or all(w.get("location", "").startswith("0:0:") for w in seg.words)):
            special_words = []
            for w in seg.words or []:
                w_s = w.get("start")
                w_e = w.get("end")
                special_words.append({
                    **w,
                    "abs_start": round(seg_base + w_s, 4) if w_s is not None else seg_base,
                    "abs_end": round(seg_base + w_e, 4) if w_e is not None else seg_base + 1.0,
                    "abs_phonemes": [
                        {
                            **p,
                            "abs_start": round(seg_base + p.get("start", 0.0), 4) if p.get("start") is not None else seg_base,
                            "abs_end": round(seg_base + p.get("end", 0.0), 4) if p.get("end") is not None else seg_base,
                        }
                        for p in w.get("phonemes", [])
                    ] if w.get("phonemes") else None,
                })
            s_start = min((w["abs_start"] for w in special_words), default=seg_base)
            s_end = max((w["abs_end"] for w in special_words), default=seg.end_time or seg_base + 2.0)
            verse_groups.append({
                "type": "special",
                "special_type": ref,
                "surah": 0,
                "ayah": 0,
                "words": special_words,
                "abs_start": s_start,
                "abs_end": s_end,
                "score": seg.match_score,
                "error": seg.error,
                "has_repetition": False,
                "repeated_ranges": None,
                "repeated_text": None,
            })
            current_group = None
            continue

        if not seg.words:
            continue

        # Case B: Iterate through words in this segment and convert to absolute timeline
        for w in seg.words:
            loc = w.get("location")
            if not loc:
                continue

            # Check if this word is a special (Basmala/Isti'adha)
            if loc.startswith("0:0:"):
                continue

            parts = loc.split(":")
            if len(parts) < 3:
                continue

            try:
                surah, ayah, word_num = int(parts[0]), int(parts[1]), int(parts[2])
            except ValueError:
                continue

            w_s = w.get("start")
            w_e = w.get("end")
            abs_w_start = round(seg_base + w_s, 4) if w_s is not None else seg_base
            abs_w_end = round(seg_base + w_e, 4) if w_e is not None else abs_w_start + 0.3

            abs_ph_list = []
            for p in w.get("phonemes", []):
                p_s = p.get("start")
                p_e = p.get("end")
                abs_ph_list.append({
                    "phoneme": p.get("phoneme", ""),
                    "abs_start": round(seg_base + p_s, 4) if p_s is not None else abs_w_start,
                    "abs_end": round(seg_base + p_e, 4) if p_e is not None else abs_w_end,
                    "confidence": p.get("confidence", 0.99),
                })

            w_entry = {
                "word": w.get("word", ""),
                "location": loc,
                "abs_start": abs_w_start,
                "abs_end": abs_w_end,
                "confidence": w.get("confidence", 0.99),
                "abs_phonemes": abs_ph_list if abs_ph_list else None,
            }

            # Check if we should continue current group or start/resume a group
            if current_group and current_group["type"] == "verse" and current_group["surah"] == surah and current_group["ayah"] == ayah:
                # Check for repetition: if word_num <= last seen word_num
                last_w = current_group["last_word_num"]
                if last_w is not None and word_num <= last_w:
                    current_group["has_repetition"] = True
                    rep_range = (f"{surah}:{ayah}:{word_num}", f"{surah}:{ayah}:{last_w}")
                    if current_group["repeated_ranges"] is None:
                        current_group["repeated_ranges"] = []
                    current_group["repeated_ranges"].append(rep_range)

                current_group["words"].append(w_entry)
                current_group["last_word_num"] = word_num
                current_group["scores"].append(seg.match_score)
                if seg.error:
                    current_group["error"] = seg.error
            else:
                # Check if an earlier group exists for this exact same (surah, ayah)
                existing_group = next(
                    (g for g in verse_groups if g["type"] == "verse" and g["surah"] == surah and g["ayah"] == ayah),
                    None
                )
                if existing_group is not None:
                    # Reciter resumed or repeated this Ayah after a pause or multi-chapter shift
                    last_w = existing_group["last_word_num"]
                    if last_w is not None and word_num <= last_w:
                        existing_group["has_repetition"] = True
                        rep_range = (f"{surah}:{ayah}:{word_num}", f"{surah}:{ayah}:{last_w}")
                        if existing_group["repeated_ranges"] is None:
                            existing_group["repeated_ranges"] = []
                        existing_group["repeated_ranges"].append(rep_range)

                    existing_group["words"].append(w_entry)
                    existing_group["last_word_num"] = word_num
                    existing_group["scores"].append(seg.match_score)
                    if seg.error:
                        existing_group["error"] = seg.error
                    current_group = existing_group
                else:
                    # New Ayah
                    new_grp = {
                        "type": "verse",
                        "special_type": None,
                        "surah": surah,
                        "ayah": ayah,
                        "words": [w_entry],
                        "last_word_num": word_num,
                        "scores": [seg.match_score],
                        "error": seg.error,
                        "has_repetition": False,
                        "repeated_ranges": None,
                        "repeated_text": None,
                    }
                    verse_groups.append(new_grp)
                    current_group = new_grp

    # Step 2: Build SegmentInfo objects from unified verse groups
    final_segments: list[SegmentInfo] = []

    for idx, grp in enumerate(verse_groups, start=1):
        if grp["type"] == "special":
            sp_type = grp["special_type"]
            canonical_text = _SPECIAL_TEXTS.get(sp_type, sp_type)
            s_start = grp["abs_start"]
            s_end = grp["abs_end"]
            
            reletive_special_words = []
            for w in grp["words"]:
                reletive_special_words.append({
                    "word": w.get("word", ""),
                    "location": w.get("location", ""),
                    "start": round(max(0.0, w["abs_start"] - s_start), 4) if "abs_start" in w else 0.0,
                    "end": round(max(0.0, w["abs_end"] - s_start), 4) if "abs_end" in w else 1.0,
                })

            final_segments.append(SegmentInfo(
                segment_number=idx,
                start_time=round(s_start, 3),
                end_time=round(s_end, 3),
                transcribed_text="",
                matched_text=canonical_text,
                matched_ref=sp_type,
                match_score=grp.get("score", 1.0),
                error=grp.get("error"),
                words=reletive_special_words or None,
            ))
            continue

        surah = grp["surah"]
        ayah = grp["ayah"]
        raw_words = grp["words"]

        # Unified Ayah boundaries in absolute audio timeline
        valid_starts = [w["abs_start"] for w in raw_words if w.get("abs_start") is not None]
        valid_ends = [w["abs_end"] for w in raw_words if w.get("abs_end") is not None]
        unified_start = min(valid_starts) if valid_starts else 0.0
        unified_end = max(valid_ends) if valid_ends else unified_start + 1.0

        # Convert words and phonemes back to relative timestamps within this segment
        segment_words = []
        for w in raw_words:
            w_out = {
                "word": w.get("word", ""),
                "location": w.get("location", ""),
                "start": round(max(0.0, w["abs_start"] - unified_start), 4) if w.get("abs_start") is not None else 0.0,
                "end": round(max(0.0, w["abs_end"] - unified_start), 4) if w.get("abs_end") is not None else 0.5,
                "confidence": w.get("confidence", 0.99),
            }
            if w.get("abs_phonemes"):
                w_out["phonemes"] = [
                    {
                        "phoneme": p.get("phoneme", ""),
                        "start": round(max(0.0, p["abs_start"] - unified_start), 4) if p.get("abs_start") is not None else 0.0,
                        "end": round(max(0.0, p["abs_end"] - unified_start), 4) if p.get("abs_end") is not None else 0.0,
                        "confidence": p.get("confidence", 0.99),
                    }
                    for p in w["abs_phonemes"]
                ]
            segment_words.append(w_out)

        # Word range
        word_nums = [parse_location_key(w)[2] for w in raw_words]
        min_wn = min(word_nums) if word_nums else 1
        max_wn = max(word_nums) if word_nums else 1
        matched_ref = f"{surah}:{ayah}:{min_wn}-{surah}:{ayah}:{max_wn}" if min_wn != max_wn else f"{surah}:{ayah}:{min_wn}"

        # Canonical text from Medina QuranIndex
        canonical_text = qi.get_ayah_text(surah, ayah)
        if not canonical_text:
            canonical_text = " ".join(w.get("word", "") for w in raw_words if not w.get("is_missing"))

        # Repetition text derivation
        rep_text_list = None
        if grp["has_repetition"] and grp["repeated_ranges"]:
            rep_text_list = []
            for r_from, r_to in grp["repeated_ranges"]:
                idx_tuple = qi.ref_to_indices(f"{r_from}-{r_to}")
                if idx_tuple:
                    s_i, e_i = idx_tuple
                    rep_text_list.append(" ".join(qi.words[k].text for k in range(s_i, e_i + 1)))
                else:
                    rep_text_list.append("")

        avg_score = float(np.mean(grp["scores"])) if grp["scores"] else 1.0

        final_segments.append(SegmentInfo(
            segment_number=idx,
            start_time=round(unified_start, 3),
            end_time=round(unified_end, 3),
            transcribed_text="",
            matched_text=canonical_text,
            matched_ref=matched_ref,
            match_score=round(avg_score, 3),
            error=grp.get("error"),
            has_repeated_words=grp["has_repetition"],
            repeated_ranges=grp["repeated_ranges"],
            repeated_text=rep_text_list,
            words=segment_words,
        ))

    return final_segments


def _find_sustained_silence(
    audio: np.ndarray,
    sample_rate: int,
    start_s: float,
    end_s: float,
    min_silence_s: float,
    threshold_db: float,
    max_start_s: float | None = None,
) -> tuple[float, float] | None:
    """Returns the longest sustained low-energy interval inside a time range."""
    frame_s = 0.05
    hop_s = 0.01
    frame_samples = max(1, int(frame_s * sample_rate))
    hop_samples = max(1, int(hop_s * sample_rate))
    start_sample = max(0, int(start_s * sample_rate))
    end_sample = min(len(audio), int(end_s * sample_rate))
    chunk = audio[start_sample:end_sample]
    if len(chunk) < frame_samples:
        return None

    quiet = []
    for position in range(0, len(chunk) - frame_samples + 1, hop_samples):
        frame = chunk[position:position + frame_samples]
        rms = float(np.sqrt(np.mean(np.square(frame))))
        quiet.append(20.0 * math.log10(max(rms, 1e-8)) <= threshold_db)

    best = None
    run_start = None
    for index, is_quiet in enumerate(quiet + [False]):
        if is_quiet and run_start is None:
            run_start = index
        elif not is_quiet and run_start is not None:
            silence_start = start_s + run_start * hop_s
            silence_end = start_s + (index - 1) * hop_s + frame_s
            if (
                silence_end - silence_start >= min_silence_s
                and (max_start_s is None or silence_start <= max_start_s)
                and (best is None or silence_end - silence_start > best[1] - best[0])
            ):
                best = (silence_start, silence_end)
            run_start = None
    return best


def smooth_word_timestamps(
    segments: list[SegmentInfo],
    max_stretch_s: float | None = None,
    audio_data=None,
    sample_rate: int = 16000,
    min_silence_ms: int = 200,
    pad_ms: int = 100,
    bridge_unsplit_gaps: bool = False,
) -> None:
    """Extends final word timestamps to acoustic speech boundaries in-place."""
    if not segments:
        return

    try:
        from config import ENABLE_WORD_SMOOTHING, WORD_SMOOTHING_MAX_STRETCH_S
    except ImportError:
        ENABLE_WORD_SMOOTHING = True
        WORD_SMOOTHING_MAX_STRETCH_S = 1.0

    if not ENABLE_WORD_SMOOTHING:
        return

    if max_stretch_s is None:
        max_stretch_s = WORD_SMOOTHING_MAX_STRETCH_S

    if audio_data is not None:
        import librosa

        if isinstance(audio_data, str):
            audio, _ = librosa.load(audio_data, sr=sample_rate, mono=True)
        else:
            audio = np.asarray(audio_data, dtype=np.float32)

        if len(audio) > 0:
            rms = librosa.feature.rms(y=audio, frame_length=1024, hop_length=512)[0]
            rms_db = 20.0 * np.log10(np.maximum(rms, 1e-8))
            silence_threshold_db = float(
                np.clip(np.percentile(rms_db, 75) - 15.0, -45.0, -30.0)
            )
            min_silence_s = min_silence_ms / 1000.0
            boundary_pad_s = max(pad_ms / 1000.0, min(0.2, min_silence_s))
            audio_duration_s = len(audio) / sample_rate
            start_updates: list[float | None] = [None] * len(segments)
            end_updates: list[float | None] = [None] * len(segments)

            for index, seg in enumerate(segments):
                if not seg.words:
                    continue
                last_end = seg.words[-1].get("end")
                if last_end is None:
                    continue
                last_word_end = seg.start_time + last_end

                next_word_start = None
                if index + 1 < len(segments) and segments[index + 1].words:
                    next_seg = segments[index + 1]
                    first_start = next_seg.words[0].get("start")
                    if first_start is not None:
                        next_word_start = next_seg.start_time + first_start

                search_end = min(
                    audio_duration_s,
                    (next_word_start if next_word_start is not None else last_word_end + max_stretch_s)
                    + 0.35,
                )
                silence = _find_sustained_silence(
                    audio,
                    sample_rate,
                    last_word_end,
                    search_end,
                    min_silence_s,
                    silence_threshold_db,
                    max_start_s=(next_word_start + 0.1) if next_word_start is not None else None,
                )
                if silence is None:
                    if (
                        bridge_unsplit_gaps
                        and next_word_start is not None
                        and next_word_start - last_word_end <= 3.0
                    ):
                        end_updates[index] = max(
                            last_word_end,
                            next_word_start - 0.001,
                        )
                    continue

                silence_start, silence_end = silence
                if next_word_start is None:
                    end_updates[index] = min(silence_start + boundary_pad_s, audio_duration_s)
                    continue

                midpoint = (silence_start + silence_end) / 2.0
                end_updates[index] = min(silence_start + boundary_pad_s, midpoint)
                start_updates[index + 1] = max(silence_end - boundary_pad_s, midpoint)

            for index, seg in enumerate(segments):
                if start_updates[index] is not None:
                    seg.start_time = round(start_updates[index], 3)
                if end_updates[index] is not None:
                    seg.end_time = round(end_updates[index], 3)

    for seg in segments:
        if not seg.words or seg.start_time is None or seg.end_time is None:
            continue

        num_words = len(seg.words)

        for i in range(num_words):
            w = seg.words[i]
            orig_end = w.get("end")
            if orig_end is None:
                continue

            if i + 1 < num_words:
                next_start = seg.words[i + 1].get("start")
                next_bound_rel = next_start if next_start is not None else orig_end + max_stretch_s
            else:
                next_bound_rel = max(orig_end, seg.end_time - seg.start_time)

            stretched_end = min(orig_end + max_stretch_s, next_bound_rel)
            new_end = max(orig_end, stretched_end)
            w["end"] = round(new_end, 4)
