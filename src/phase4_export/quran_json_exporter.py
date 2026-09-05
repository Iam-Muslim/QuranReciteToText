"""Phase 4 Exporter: Formats matched Quran data, computes pauses, builds subsegments, and exports JSON outputs.

Mirrors Dart lib/phase4_export/quran_json_exporter.dart exactly.
"""

from __future__ import annotations
import json
import os
import re
from pathlib import Path
from typing import List, Dict, Optional, Any, TYPE_CHECKING

from src.core.models import (
    PhonemeToken,
    RecoveryEvent,
    RecoverySummary,
    QuranWord,
    AyahSubSegment,
    QuranSegment,
)

if TYPE_CHECKING:
    from src.phase3_matcher.quran_word_matcher import MatchedAyah


class QuranJsonExporter:
    """Converts raw matched Ayahs from Phase 3 into formatted QuranSegments
    with calculated breath pauses, sub-segments, and rounded timestamps,
    and exports JSON artifacts.
    """

    @classmethod
    def build_segments(cls, ayahs: List["MatchedAyah"]) -> List[QuranSegment]:
        """Converts raw matched Ayahs into formatted QuranSegments."""
        segments: List[QuranSegment] = []

        current_surah = -1
        surah_segment_number = 1

        for a in ayahs:
            try:
                surah_num = int(a.v_key.split(":")[0])
            except Exception:
                surah_num = 1

            if surah_num != current_surah:
                current_surah = surah_num
                surah_segment_number = 1  # Resets back to 1 for each new Surah

            text_words = [w for w in re.split(r"\s+", a.ayah_text.strip()) if w]
            words_result = [sw.to_quran_word() for sw in a.words]

            # 1. Calculate inter-word pauses (> 1.0 second)
            cls.calculate_pauses(words_result, pause_threshold=1.0)

            # 2. Build breath phrase sub-segments
            sub_segments = cls.build_sub_segments(
                words_result,
                text_words,
                a.v_key,
                a.default_ayah_start,
                repeated_ranges=a.repeated_ranges,
                waqf_pause_threshold=1.0,
            )

            # 3. Compute Ayah boundaries
            ayah_start = (
                words_result[0].start
                if words_result and words_result[0].start is not None
                else a.default_ayah_start
            )
            ayah_end = (
                max(ayah_start + 0.1, words_result[-1].end)
                if words_result and words_result[-1].end is not None
                else (ayah_start + 0.1)
            )

            green_count = sum(1 for w in words_result if (w.score or 0.0) > 0.0)
            match_score = green_count / max(1, len(a.words))

            segments.append(
                QuranSegment(
                    segment_number=surah_segment_number,
                    surah_number=surah_num,
                    start_time=round(ayah_start, 2),
                    end_time=round(ayah_end, 2),
                    transcribed_text=a.transcribed_text,
                    matched_text=a.ayah_text,
                    matched_ref=f"{a.v_key}:1-{a.v_key}:{len(words_result)}",
                    match_score=round(match_score, 3),
                    words=words_result,
                    prologue=a.prologue,
                    sub_segments=sub_segments,
                    has_missing_words=a.has_missing_words,
                    has_repeated_words=bool(a.repeated_ranges),
                    repeated_ranges=a.repeated_ranges,
                    repeated_text=a.repeated_text,
                )
            )
            surah_segment_number += 1

        return segments

    @staticmethod
    def calculate_pauses(words: List[QuranWord], pause_threshold: float = 1.0) -> None:
        """Computes silence gaps (pauses) between consecutive words (> 1.0 second)."""
        for w in range(len(words) - 1):
            cur = words[w]
            nxt = words[w + 1]
            if cur.end is not None and nxt.start is not None:
                gap = nxt.start - cur.end
                if gap > pause_threshold:
                    words[w].pause_after_seconds = round(gap, 2)

    @staticmethod
    def build_sub_segments(
        words: List[QuranWord],
        text_words: List[str],
        v_key: str,
        default_start: float,
        repeated_ranges: Optional[List[Any]] = None,
        waqf_pause_threshold: float = 1.0,
    ) -> Optional[List[AyahSubSegment]]:
        """Builds breath phrases based on pauses > waqf_pause_threshold (default > 1.0s)
        and isolates repetition phrases as sub-segments.
        """
        if not words:
            return None

        sub_segments: List[AyahSubSegment] = []

        # Map repetitions by their starting word index
        reps_by_start_word: Dict[int, List[Dict[str, Any]]] = {}
        if repeated_ranges:
            for r in repeated_ranges:
                if isinstance(r, dict):
                    from_ref = str(r.get("from_ref", ""))
                    to_ref = str(r.get("to_ref", ""))
                    if from_ref.startswith(f"{v_key}:") and to_ref.startswith(f"{v_key}:"):
                        try:
                            from_w = int(from_ref.split(":")[2]) - 1
                            to_w = int(to_ref.split(":")[2]) - 1
                        except Exception:
                            continue

                        if 0 <= from_w <= to_w < len(words):
                            entry = {
                                "from_w": from_w,
                                "to_w": to_w,
                                "text": r.get("text", ""),
                                "first_start_time": r.get("first_start_time"),
                                "first_end_time": r.get("first_end_time"),
                            }
                            if "words" in r:
                                entry["words"] = r["words"]
                            reps_by_start_word.setdefault(from_w, []).append(entry)

        sub_seg_num = 1
        p_start_w = 0

        for w in range(len(words)):
            # 1. If this word begins a repetition, emit the attempt connected to whatever preceded it
            if w in reps_by_start_word:
                for rep in reps_by_start_word[w]:
                    r_from = rep["from_w"]
                    r_to = rep["to_w"]

                    if p_start_w < r_from and words[p_start_w].start is not None:
                        r_start = words[p_start_w].start
                    else:
                        r_start = rep.get("first_start_time")
                        if r_start is None:
                            r_start = words[r_from].start if words[r_from].start is not None else default_start

                    r_end = rep.get("first_end_time")
                    if r_end is None:
                        r_end = words[r_to].end if words[r_to].end is not None else (r_start + 0.1)

                    p_text = " ".join(text_words[min(p_start_w, len(text_words)):min(r_to + 1, len(text_words))])

                    rep_words = rep.get("words", words[r_from:r_to + 1])
                    sub_words: List[QuranWord] = []
                    if p_start_w < r_from:
                        sub_words.extend(words[p_start_w:r_from])
                    sub_words.extend(rep_words)

                    is_middle_rep = (p_start_w >= r_from)

                    sub_segments.append(
                        AyahSubSegment(
                            sub_segment_number=sub_seg_num,
                            start_time=round(r_start, 2),
                            end_time=round(r_end, 2),
                            text=p_text,
                            words_range=f"{v_key}:{p_start_w + 1}-{v_key}:{r_to + 1}",
                            is_repetition=is_middle_rep,
                            words=sub_words,
                        )
                    )
                    sub_seg_num += 1

                    # Resumed reading starts at r_from:
                    p_start_w = r_from

            # 2. Check if continuous phrase should cut at w (Waqf pause > 1.0s or Ayah end)
            is_last = (w == len(words) - 1)
            has_waqf_pause = False
            if not is_last:
                if (w + 1) in reps_by_start_word:
                    first_rep = reps_by_start_word[w + 1][0]
                    rep_first_start = first_rep.get("first_start_time", words[w + 1].start or 0.0)
                    cur_end = words[w].end if words[w].end is not None else rep_first_start
                    has_waqf_pause = (rep_first_start - cur_end) > waqf_pause_threshold
                else:
                    has_waqf_pause = (
                        words[w].pause_after_seconds is not None
                        and words[w].pause_after_seconds > waqf_pause_threshold
                    )

            if is_last or has_waqf_pause:
                if p_start_w <= w:
                    p_start = words[p_start_w].start if words[p_start_w].start is not None else default_start
                    p_end = words[w].end if words[w].end is not None else (p_start + 0.1)
                    p_text = " ".join(text_words[min(p_start_w, len(text_words)):min(w + 1, len(text_words))])
                    p_words = words[p_start_w:w + 1]

                    sub_segments.append(
                        AyahSubSegment(
                            sub_segment_number=sub_seg_num,
                            start_time=round(p_start, 2),
                            end_time=round(p_end, 2),
                            text=p_text,
                            words_range=f"{v_key}:{p_start_w + 1}-{v_key}:{w + 1}",
                            words=p_words,
                        )
                    )
                    sub_seg_num += 1
                    p_start_w = w + 1

        return sub_segments if sub_segments else None

    @classmethod
    def export_output_json(cls, output_dir: str, segments: List[QuranSegment]) -> str:
        """Exports output.json format with segments grouped into their respective surah blocks."""
        os.makedirs(output_dir, exist_ok=True)

        by_surah: Dict[int, List[QuranSegment]] = {}
        for s in segments:
            by_surah.setdefault(s.surah_number, []).append(s)

        surahs_json = []
        for surah_num, segs in by_surah.items():
            surahs_json.append({
                "surah_number": surah_num,
                "total_segments": len(segs),
                "segments": [s.to_dict() for s in segs],
            })

        output_dict = {
            "total_surahs": len(surahs_json),
            "total_segments": len(segments),
            "surahs": surahs_json,
        }

        output_path = os.path.join(output_dir, "output.json")
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(output_dict, f, ensure_ascii=False, indent=2)

        return output_path

    @classmethod
    def export_all(
        cls,
        output_dir: str,
        audio_duration: float,
        raw_phonemes: List[PhonemeToken],
        recovery_summary: RecoverySummary,
        recovery_events: List[RecoveryEvent],
        aligned_phonemes: List[PhonemeToken],
        segments: List[QuranSegment],
    ) -> Dict[str, str]:
        """Exports all standard pipeline JSON artifacts (raw_transcription, recovered_speech, ctc_aligned, output.json)."""
        os.makedirs(output_dir, exist_ok=True)

        # 1. raw_transcription.json
        raw_sherpa_output = []
        for p in raw_phonemes:
            raw_sherpa_output.append({
                "token": p.phoneme,
                "start": round(p.start, 3),
                "end": round(p.end, 3),
                "start_timestamp": round(p.peak_timestamp if p.peak_timestamp is not None else p.start, 3),
            })

        raw_transcription_dict = {
            "total_audio_duration_seconds": round(audio_duration, 3),
            "total_phonemes": len(raw_phonemes),
            "raw_text": "".join(p.phoneme for p in raw_phonemes),
            "phonemes": [p.to_raw_dict(i + 1) for i, p in enumerate(raw_phonemes)],
            "sherpa_raw_output": raw_sherpa_output,
        }
        raw_path = os.path.join(output_dir, "raw_transcription.json")
        with open(raw_path, "w", encoding="utf-8") as f:
            json.dump(raw_transcription_dict, f, ensure_ascii=False, indent=2)

        # 2. recovered_speech.json
        recovered_speech_dict = {
            "summary": recovery_summary.to_dict(),
            "recovery_events": [e.to_dict() for e in recovery_events],
        }
        rec_path = os.path.join(output_dir, "recovered_speech.json")
        with open(rec_path, "w", encoding="utf-8") as f:
            json.dump(recovered_speech_dict, f, ensure_ascii=False, indent=2)

        # 3. ctc_aligned_phonemes.json
        ctc_aligned_dict = {
            "audio_duration_seconds": round(audio_duration, 3),
            "total_phonemes": len(aligned_phonemes),
            "raw_text": "".join(p.phoneme for p in aligned_phonemes),
            "aligned_phonemes": [p.to_aligned_dict(i + 1) for i, p in enumerate(aligned_phonemes)],
        }
        align_path = os.path.join(output_dir, "ctc_aligned_phonemes.json")
        with open(align_path, "w", encoding="utf-8") as f:
            json.dump(ctc_aligned_dict, f, ensure_ascii=False, indent=2)

        # 4. output.json
        out_path = cls.export_output_json(output_dir=output_dir, segments=segments)

        return {
            "raw_transcription": raw_path,
            "recovered_speech": rec_path,
            "ctc_aligned_phonemes": align_path,
            "output": out_path,
        }
