"""Audio loading, decoding, and normalization utilities.

Mirrors Dart lib/core/audio_decoder.dart exactly.
"""

from __future__ import annotations

import os
import math
import subprocess
import warnings
from typing import Optional
import numpy as np

from config import SAMPLE_RATE


class AudioDecoder:
    target_sample_rate: int = SAMPLE_RATE

    @staticmethod
    def calculate_energy_db(
        samples: np.ndarray,
        start_idx: int = 0,
        end_idx: Optional[int] = None
    ) -> float:
        """Calculates RMS energy in decibels (dB) for a slice of Float32 audio samples.

        Formula mirrors Dart AudioDecoder.calculateEnergyDb:
            RMS = sqrt(mean(samples^2))
            dB = 20 * log10(max(RMS, 1e-8))
        """
        end = len(samples) if end_idx is None else end_idx
        length = end - start_idx
        if length <= 0 or len(samples) == 0:
            return -100.0

        sub = samples[start_idx:end]
        mean_sq = float(np.mean(np.square(sub)))
        rms = math.sqrt(max(0.0, mean_sq))
        return float(20.0 * math.log10(max(rms, 1e-8)))

    @staticmethod
    def normalize_audio(
        audio: np.ndarray,
        sample_rate: int = 16000,
        target_lufs: float = -23.0,
        safe_lufs: bool = True,
    ) -> np.ndarray:
        """Normalizes audio using single-pass RMS / LUFS scaling.

        Matches Dart AudioDecoder.normalizeAudio logic.
        """
        if len(audio) == 0:
            return audio

        audio_float = audio.astype(np.float32)
        length = len(audio_float)

        peak = float(np.max(np.abs(audio_float))) if length > 0 else 0.0
        sum_sq = float(np.sum(np.square(audio_float)))
        rms = math.sqrt(sum_sq / length)

        if safe_lufs and rms < 1e-4:
            return audio_float

        gain = 1.0
        if length <= 30 * sample_rate:
            # Short audio: attempt precise integrated loudness measurement
            try:
                import pyloudnorm as pyln
                meter = pyln.Meter(sample_rate)
                loudness = meter.integrated_loudness(audio_float)
                if np.isfinite(loudness) and loudness < 0.0:
                    gain = float(math.pow(10.0, (target_lufs - loudness) / 20.0))
            except Exception:
                target_rms = 0.07
                if rms > 0.0:
                    gain = target_rms / rms
        else:
            # Long audio: target RMS equivalent to -23 LUFS (target RMS ~ 0.07)
            target_rms = 0.07
            if rms > 0.0:
                gain = target_rms / rms

        # Prevent excessive amplification (max 6x / +15dB)
        if gain > 6.0:
            gain = 6.0

        # Guard against clipping
        if peak * gain > 0.98:
            gain = 0.98 / max(peak, 1e-6)

        # If gain is virtually 1.0, return unchanged
        if abs(gain - 1.0) < 0.01 and peak <= 1.0:
            return audio_float

        return (audio_float * gain).astype(np.float32)

    @classmethod
    def load_audio_file(
        cls,
        file_path: str,
        sample_rate: int = 16000,
        normalize: bool = True
    ) -> np.ndarray:
        """Loads an audio file (WAV, MP3, M4A, etc.) and returns normalized 16kHz mono Float32 array."""
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Audio file not found: {file_path}")

        # Fast loading via ffmpeg stdout pipe
        cmd = [
            'ffmpeg', '-v', 'quiet', '-y',
            '-i', file_path,
            '-f', 'f32le', '-ac', '1', '-ar', str(sample_rate),
            '-'
        ]
        try:
            pipe = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            raw_audio, _ = pipe.communicate()
            if pipe.returncode == 0 and len(raw_audio) > 0:
                audio = np.frombuffer(raw_audio, dtype=np.float32)
            else:
                raise RuntimeError("FFmpeg pipe produced empty or failed output")
        except Exception:
            import librosa
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                audio, _ = librosa.load(file_path, sr=sample_rate, mono=True)
                audio = audio.astype(np.float32)

        if normalize:
            audio = cls.normalize_audio(audio, sample_rate=sample_rate)

        return audio
