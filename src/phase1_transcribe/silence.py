"""Phase 1 Silence Detection — Munajjam PR #65 Adaptive Silence Engine.

Provides peak-relative Librosa RMS energy splitting (`top_db`) and 4-Level Progressive
Threshold Relaxation for continuous reciters (Hadr style) and noisy recordings.

Source: https://github.com/Itqan-community/Munajjam/pull/65
Author: ahmed-alramah
"""

import numpy as np
import librosa
from pathlib import Path
from typing import List, Tuple, Optional


def _detect_non_silent_fast(
    audio_data: np.ndarray | str | Path,
    min_silence_len_ms: int = 300,
    silence_thresh_db: int = -30,
    sample_rate: int = 16000,
) -> List[Tuple[int, int]]:
    """Librosa Fast Engine: Peak-relative top_db RMS non-silent interval detection."""
    if isinstance(audio_data, (str, Path)):
        y, sr = librosa.load(str(audio_data), sr=sample_rate, mono=True)
    else:
        y, sr = audio_data, sample_rate

    if len(y) == 0:
        return []

    top_db = abs(silence_thresh_db)
    frame_length = 2048
    hop_length = 512

    intervals = librosa.effects.split(
        y,
        top_db=top_db,
        frame_length=frame_length,
        hop_length=hop_length
    )

    chunks = []
    min_silence_samples = int((min_silence_len_ms / 1000.0) * sr)

    for start_sample, end_sample in intervals:
        start_ms = int((start_sample / sr) * 1000)
        end_ms = int((end_sample / sr) * 1000)

        if not chunks:
            chunks.append((start_ms, end_ms))
        else:
            prev_start_ms, prev_end_ms = chunks[-1]
            gap_samples = start_sample - int((prev_end_ms / 1000.0) * sr)

            if gap_samples < min_silence_samples:
                chunks[-1] = (prev_start_ms, end_ms)
            else:
                chunks.append((start_ms, end_ms))

    return chunks


def _detect_non_silent_chunks_raw(
    audio_data: np.ndarray | str | Path,
    min_silence_len: int = 300,
    silence_thresh: int = -30,
    use_fast: bool = True,
    sample_rate: int = 16000,
) -> List[Tuple[int, int]]:
    """Internal helper: detect non-silent chunks with fixed thresholds."""
    return _detect_non_silent_fast(audio_data, min_silence_len, silence_thresh, sample_rate=sample_rate)


def detect_non_silent_chunks(
    audio_data: np.ndarray | str | Path,
    min_silence_len: int = 300,
    silence_thresh: int = -30,
    use_fast: bool = True,
    adaptive: bool = False,
    expected_chunks: Optional[int] = None,
    min_chunks_ratio: float = 0.5,
    sample_rate: int = 16000,
) -> List[Tuple[int, int]]:
    """Detects non-silent speech portions in audio using Munajjam PR #65 Adaptive Relaxation.

    Args:
        audio_data: Audio file path or PCM numpy array
        min_silence_len: Minimum silence duration in milliseconds (default 300ms)
        silence_thresh: Silence threshold in dB (default -30 dB)
        use_fast: Use fast librosa-based detection
        adaptive: Enable 4-level progressive threshold relaxation when too few chunks found
        expected_chunks: Expected number of non-silent chunks (e.g. ayah count)
        min_chunks_ratio: Fraction of expected_chunks required before stopping retry
        sample_rate: Audio sampling rate (default 16000 Hz)

    Returns:
        List of (start_ms, end_ms) tuples for non-silent speech portions.
    """
    # Step 1: Initial raw detection pass
    chunks = _detect_non_silent_chunks_raw(audio_data, min_silence_len, silence_thresh, use_fast, sample_rate)

    if not adaptive or expected_chunks is None or expected_chunks <= 0:
        return chunks

    if min_chunks_ratio <= 0:
        raise ValueError("min_chunks_ratio must be > 0 when adaptive=True")

    # Step 2: 4-Level Progressive Retry Relaxation Table
    retry_levels = [
        (+5, 0.75),   # Level 1: slightly more sensitive (+5 dB, 75% min silence)
        (+10, 0.50),  # Level 2: moderately more sensitive
        (+15, 0.35),  # Level 3: quite sensitive
        (+20, 0.25),  # Level 4: very sensitive (last resort)
    ]

    min_required = max(1, int(min_chunks_ratio * expected_chunks))
    best_chunks = chunks

    # Step 3: Progressive Relaxation Retry Loop
    for thresh_delta, len_factor in retry_levels:
        if len(best_chunks) >= min_required:
            break

        relaxed_thresh = min(silence_thresh + thresh_delta, -10)
        relaxed_len = max(50, int(min_silence_len * len_factor))

        chunks = _detect_non_silent_chunks_raw(
            audio_data, relaxed_len, relaxed_thresh, use_fast, sample_rate
        )
        if len(chunks) > len(best_chunks):
            best_chunks = chunks

    return best_chunks
