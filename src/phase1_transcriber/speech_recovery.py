"""Phase 1.1: Energy-Aware Speech & Repetition Recovery Engine.

Scans the audio timeline for untranscribed speech holes, retranscribes padded
audio slices, and merges recovered phonemes with authentic timestamps.
Faithfully mirrors Dart lib/phase1_transcriber/speech_recovery.dart.
"""

from __future__ import annotations

import time
import math
import logging
from dataclasses import dataclass
from typing import Optional, List, Callable
import numpy as np

from config import (
    FRAME_STEP,
    SPEECH_RECOVERY_ENERGY_THRESHOLD_DB,
    SPEECH_RECOVERY_MIN_HOLE_DURATION_S,
    SPEECH_RECOVERY_PADDING_S,
    SPEECH_RECOVERY_MIN_PHONEMES_IN_GAP,
)
from src.core.models import (
    PhonemeToken,
    RecoveryEvent,
    RecoverySummary,
    SpeechRecoveryResult,
)
from src.core.audio_decoder import AudioDecoder

logger = logging.getLogger(__name__)


@dataclass
class _AudioGap:
    start: float
    end: float
    prev_index: int
    next_index: int

    @property
    def duration(self) -> float:
        return self.end - self.start


class SpeechRecoveryEngine:
    """Scans untranscribed gaps in the audio timeline, checks RMS energy,

    retranscribes audio slices with context padding, and merges recovered phonemes.
    """

    @classmethod
    def recover_speech(
        cls,
        audio_pcm: np.ndarray,
        initial_phonemes: List[PhonemeToken],
        audio_duration: float,
        transcriber,
        energy_threshold_db: float = SPEECH_RECOVERY_ENERGY_THRESHOLD_DB,
        min_hole_duration_s: float = SPEECH_RECOVERY_MIN_HOLE_DURATION_S,
        padding_s: float = SPEECH_RECOVERY_PADDING_S,
        min_phonemes_in_gap: int = SPEECH_RECOVERY_MIN_PHONEMES_IN_GAP,
        sample_rate: int = 16000,
        progress_callback: Optional[Callable[[float, float], None]] = None,
    ) -> SpeechRecoveryResult:
        """Executes energy-aware deletion hole and repetition recovery."""
        start_time = time.time()

        # 1. Identify all candidate gaps across the audio timeline
        candidate_gaps: List[_AudioGap] = []

        if not initial_phonemes:
            if audio_duration >= min_hole_duration_s:
                candidate_gaps.append(
                    _AudioGap(start=0.0, end=audio_duration, prev_index=-1, next_index=-1)
                )
        else:
            # Leading gap before first phoneme
            if initial_phonemes[0].start >= min_hole_duration_s:
                candidate_gaps.append(
                    _AudioGap(start=0.0, end=initial_phonemes[0].start, prev_index=-1, next_index=0)
                )

            # Intermediate gaps between phonemes
            for i in range(len(initial_phonemes) - 1):
                g_start = initial_phonemes[i].end
                g_end = initial_phonemes[i + 1].start
                g_dur = g_end - g_start
                if g_dur >= min_hole_duration_s:
                    candidate_gaps.append(
                        _AudioGap(start=g_start, end=g_end, prev_index=i, next_index=i + 1)
                    )

            # Trailing gap after last phoneme
            if audio_duration - initial_phonemes[-1].end >= min_hole_duration_s:
                candidate_gaps.append(
                    _AudioGap(
                        start=initial_phonemes[-1].end,
                        end=audio_duration,
                        prev_index=len(initial_phonemes) - 1,
                        next_index=-1,
                    )
                )

        total_gaps = len(candidate_gaps)
        speech_holes_detected = 0
        logger.info(f"[Recovery] Scanning {total_gaps} potential gaps for untranscribed speech...")

        recovery_events: List[RecoveryEvent] = []
        new_phonemes_to_insert: List[PhonemeToken] = []

        for g_idx, gap in enumerate(candidate_gaps):
            gap_dur = gap.duration

            # Calculate real RMS energy in dB for the gap
            start_sample = max(0, int(round(gap.start * sample_rate)))
            end_sample = min(len(audio_pcm), int(round(gap.end * sample_rate)))
            energy_db = AudioDecoder.calculate_energy_db(
                audio_pcm, start_idx=start_sample, end_idx=end_sample
            )

            if energy_db >= energy_threshold_db:
                speech_holes_detected += 1

                # Apply symmetric context padding to preserve boundary transitions
                padded_start = max(0.0, gap.start - padding_s)
                padded_end = min(audio_duration, gap.end + padding_s)
                p_start_sample = int(round(padded_start * sample_rate))
                p_end_sample = min(len(audio_pcm), int(round(padded_end * sample_rate)))

                if p_end_sample > p_start_sample:
                    slice_pcm = audio_pcm[p_start_sample:p_end_sample]

                    # Retranscribe slice with short silence padding (24 frames)
                    if hasattr(transcriber, "transcribe_audio"):
                        raw_slice_result = transcriber.transcribe_audio(
                            slice_pcm, sample_rate=sample_rate, silence_pad_frames=24
                        )
                    else:
                        raw_slice_result = transcriber.transcribe(
                            slice_pcm, orig_sr=sample_rate, silence_pad_frames=24
                        )

                    slice_phonemes = raw_slice_result.phonemes if hasattr(raw_slice_result, "phonemes") else []

                    prev_token = (
                        initial_phonemes[gap.prev_index] if gap.prev_index >= 0 else None
                    )
                    next_token = (
                        initial_phonemes[gap.next_index]
                        if (gap.next_index >= 0 and gap.next_index < len(initial_phonemes))
                        else None
                    )

                    gap_recovered: List[PhonemeToken] = []

                    for p in slice_phonemes:
                        abs_start = padded_start + p.start
                        abs_end = padded_start + p.end
                        abs_peak = (
                            (padded_start + p.peak_timestamp)
                            if p.peak_timestamp is not None
                            else None
                        )
                        check_point = abs_peak if abs_peak is not None else ((abs_start + abs_end) / 2.0)

                        # 1. Strict Boundary Containment:
                        # Candidate MUST reside strictly inside the gap window between neighbors
                        if (
                            abs_start < (gap.start - 0.01)
                            or abs_end > (gap.end + 0.01)
                            or check_point < gap.start
                            or check_point > gap.end
                        ):
                            continue

                        # 2. Smart Boundary Echo vs Genuine Repetition Filtering:
                        # Acoustic padding bleed rejection:
                        if prev_token is not None and p.phoneme == prev_token.phoneme:
                            dist_from_prev = abs_start - prev_token.end
                            peak_dist_from_prev = (
                                (abs_peak - prev_token.peak_timestamp)
                                if (abs_peak is not None and prev_token.peak_timestamp is not None)
                                else (abs_start - prev_token.start)
                            )
                            if dist_from_prev < 0.06 and peak_dist_from_prev < 0.12:
                                continue  # Skip padding bleed of prev_token

                        if next_token is not None and p.phoneme == next_token.phoneme:
                            dist_to_next = next_token.start - abs_end
                            peak_dist_to_next = (
                                (next_token.peak_timestamp - abs_peak)
                                if (abs_peak is not None and next_token.peak_timestamp is not None)
                                else (next_token.start - abs_start)
                            )
                            if dist_to_next < 0.06 and peak_dist_to_next < 0.12:
                                continue  # Skip padding bleed of next_token

                        recovered_token = PhonemeToken(
                            phoneme=p.phoneme,
                            start=round(abs_start, 4),
                            end=round(abs_end, 4),
                            confidence=p.confidence,
                            is_recovered=True,
                            start_frame=int(round(abs_start / FRAME_STEP)),
                            end_frame=int(round(abs_end / FRAME_STEP)),
                            peak_frame=(
                                int(round(abs_peak / FRAME_STEP))
                                if abs_peak is not None
                                else None
                            ),
                            peak_timestamp=(
                                round(abs_peak, 4) if abs_peak is not None else None
                            ),
                        )
                        gap_recovered.append(recovered_token)

                    for token in gap_recovered:
                        new_phonemes_to_insert.append(token)

                    if gap_recovered:
                        recovery_events.append(
                            RecoveryEvent(
                                event_id=len(recovery_events) + 1,
                                gap_start=gap.start,
                                gap_end=gap.end,
                                gap_duration=gap_dur,
                                padded_start=padded_start,
                                padded_end=padded_end,
                                energy_db=energy_db,
                                recovered_text="".join(p.phoneme for p in gap_recovered),
                                recovered_phonemes=gap_recovered,
                            )
                        )

            if progress_callback is not None:
                pct = ((g_idx + 1) / total_gaps * 100.0) if total_gaps > 0 else 100.0
                elapsed = time.time() - start_time
                progress_callback(pct, elapsed)

        logger.info(
            f"[Recovery] Finished scanning: {speech_holes_detected} speech holes detected, "
            f"{len(recovery_events)} recovery events, {len(new_phonemes_to_insert)} recovered phonemes"
        )

        # 2. Merge initial and recovered phonemes chronologically
        all_phonemes = list(initial_phonemes) + list(new_phonemes_to_insert)
        all_phonemes.sort(key=lambda p: p.start)

        # 3. Global Sequence Refusal:
        # Any single recovered phoneme (is_recovered == True) that stands alone between
        # original phonemes (or boundaries) with no adjacent recovered phonemes is REFUSED.
        # Only chains of >= 2 consecutive recovered phonemes (words, phrases, repetitions) are kept.
        filtered_phonemes: List[PhonemeToken] = []
        for i in range(len(all_phonemes)):
            current = all_phonemes[i]
            if not current.is_recovered:
                filtered_phonemes.append(current)
            else:
                has_prev_rec = (
                    i > 0
                    and all_phonemes[i - 1].is_recovered
                    and (current.start - all_phonemes[i - 1].end) <= 0.25
                )
                has_next_rec = (
                    i < len(all_phonemes) - 1
                    and all_phonemes[i + 1].is_recovered
                    and (all_phonemes[i + 1].start - current.end) <= 0.25
                )

                if has_prev_rec or has_next_rec:
                    filtered_phonemes.append(current)
                else:
                    # Discard standalone single recovered phoneme
                    continue

        # 4. Deduplicate accidental micro-overlaps (< 80ms) of identical adjacent phonemes
        deduplicated: List[PhonemeToken] = []
        for i in range(len(filtered_phonemes)):
            current = filtered_phonemes[i]
            if deduplicated:
                prev = deduplicated[-1]
                if prev.phoneme == current.phoneme and abs(current.start - prev.start) < 0.08:
                    if current.confidence > prev.confidence:
                        deduplicated[-1] = current
                    continue
            deduplicated.append(current)

        # 5. Ensure sequential start/end monotonicity
        for i in range(len(deduplicated) - 1):
            if deduplicated[i].end > deduplicated[i + 1].start:
                deduplicated[i].end = deduplicated[i + 1].start
            if deduplicated[i].end <= deduplicated[i].start:
                deduplicated[i].end = deduplicated[i].start + FRAME_STEP

        recovery_time = time.time() - start_time
        recovered_count = len(deduplicated) - len(initial_phonemes)

        summary = RecoverySummary(
            recovery_time_seconds=recovery_time,
            scanned_gaps_count=total_gaps,
            speech_holes_detected=speech_holes_detected,
            recovered_events_count=len(recovery_events),
            recovered_phonemes_count=max(0, recovered_count),
            energy_threshold_db=energy_threshold_db,
            min_hole_duration_s=min_hole_duration_s,
        )

        return SpeechRecoveryResult(
            recovered_phonemes=deduplicated,
            recovery_events=recovery_events,
            recovery_summary=summary,
        )
