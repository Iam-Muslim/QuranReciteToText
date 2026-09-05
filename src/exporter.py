"""Phase 4 Exporter: Pause calculation, Waqf sub-segmentation, and JSON export."""

from __future__ import annotations

import os
import json
import re
from typing import List, Dict, Optional, Any
from src.models import (
    PhonemeToken,
    RecoveryEvent,
    RecoverySummary,
    QuranWord,
    AyahSubSegment,
    QuranSegment,
)


class QuranJsonExporter:
    """Computes pauses, breath sub-segments, and exports the 4 canonical JSON artifacts."""

    @staticmethod
    def calculate_pauses(words: List[QuranWord], pause_threshold: float = 1.0) -> None:
        """Computes silence gaps between consecutive words (> 1.0 second)."""
        for w in range(len(words) - 1):
            cur = words[w]
            nxt = words[w + 1]
            if cur.end is not None and nxt.start is not None:
                gap = nxt.start - cur.end
                if gap > pause_threshold:
                    words[w].pause_after_seconds = round(gap, 2)

    @classmethod
    def process_segments(cls, segments: List[QuranSegment]) -> List[QuranSegment]:
        """Calculates inter-word pauses and builds Waqf breath sub-segments."""
        for seg in segments:
            cls.calculate_pauses(seg.words, pause_threshold=1.0)

            # Build Waqf breath sub-segments
            sub_segments: List[AyahSubSegment] = []
            curr_words: List[QuranWord] = []
            sub_num = 1

            for w in seg.words:
                curr_words.append(w)
                if w.pause_after_seconds is not None or w == seg.words[-1]:
                    if curr_words:
                        s_time = curr_words[0].start or seg.start_time
                        e_time = curr_words[-1].end or seg.end_time
                        s_loc = curr_words[0].location or ""
                        e_loc = curr_words[-1].location or ""
                        w_range = f"{s_loc}-{e_loc}" if s_loc != e_loc else s_loc
                        phrase_text = " ".join(cw.word for cw in curr_words)

                        sub_segments.append(
                            AyahSubSegment(
                                sub_segment_number=sub_num,
                                start_time=round(s_time, 2),
                                end_time=round(e_time, 2),
                                text=phrase_text,
                                words_range=w_range,
                                words=list(curr_words),
                            )
                        )
                        sub_num += 1
                        curr_words = []

            if sub_segments:
                seg.sub_segments = sub_segments

        return segments

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
    ) -> None:
        """Exports all 4 canonical JSON files."""
        os.makedirs(output_dir, exist_ok=True)

        # 1. raw_transcription.json
        with open(os.path.join(output_dir, "raw_transcription.json"), "w", encoding="utf-8") as f:
            json.dump({
                "audio_duration_seconds": round(audio_duration, 3),
                "total_tokens": len(raw_phonemes),
                "raw_text": "".join(p.phoneme for p in raw_phonemes),
                "phoneme_tokens": [p.to_raw_dict(i + 1) for i, p in enumerate(raw_phonemes)],
            }, f, ensure_ascii=False, indent=2)

        # 2. recovered_speech.json
        with open(os.path.join(output_dir, "recovered_speech.json"), "w", encoding="utf-8") as f:
            json.dump({
                "audio_duration_seconds": round(audio_duration, 3),
                "recovery_summary": recovery_summary.to_dict(),
                "recovery_events": [e.to_dict() for e in recovery_events],
            }, f, ensure_ascii=False, indent=2)

        # 3. ctc_aligned_phonemes.json
        with open(os.path.join(output_dir, "ctc_aligned_phonemes.json"), "w", encoding="utf-8") as f:
            json.dump({
                "audio_duration_seconds": round(audio_duration, 3),
                "total_phonemes": len(aligned_phonemes),
                "raw_text": "".join(p.phoneme for p in aligned_phonemes),
                "aligned_phonemes": [p.to_aligned_dict(i + 1) for i, p in enumerate(aligned_phonemes)],
            }, f, ensure_ascii=False, indent=2)

        # 4. output.json
        by_surah: Dict[int, List[QuranSegment]] = {}
        for s in segments:
            by_surah.setdefault(s.surah_number, []).append(s)

        surahs_json = [
            {
                "surah_number": k,
                "total_segments": len(v),
                "segments": [seg.to_dict() for seg in v],
            }
            for k, v in by_surah.items()
        ]

        with open(os.path.join(output_dir, "output.json"), "w", encoding="utf-8") as f:
            json.dump({
                "total_surahs": len(surahs_json),
                "total_segments": len(segments),
                "surahs": surahs_json,
            }, f, ensure_ascii=False, indent=2)
