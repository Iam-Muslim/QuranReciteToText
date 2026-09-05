"""Audio loading, decoding, and loudness normalization utilities."""

from __future__ import annotations

import os
import math
import subprocess
import warnings
from typing import Optional
import numpy as np

from config import SAMPLE_RATE


class AudioDecoder:
    """High-speed audio loading via ffmpeg pipe with LUFS/RMS loudness normalization."""
    target_sample_rate: int = SAMPLE_RATE

    @staticmethod
    def calculate_energy_db(
        samples: np.ndarray,
        start_idx: int = 0,
        end_idx: Optional[int] = None
    ) -> float:
        """Calculates RMS energy in decibels (dB) for a slice of Float32 audio samples."""
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
        sample_rate: int = SAMPLE_RATE,
        target_lufs: float = -23.0,
        safe_lufs: bool = True,
    ) -> np.ndarray:
        """Normalizes audio to target LUFS (-23 LUFS) or target RMS with clipping guard."""
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
            try:
                import pyloudnorm as pyln
                meter = pyln.Meter(sample_rate)
                loudness = meter.integrated_loudness(audio_float)
                if np.isfinite(loudness) and loudness < 0.0:
                    gain = float(math.pow(10.0, (target_lufs - loudness) / 20.0))
            except Exception:
                if rms > 0.0:
                    gain = 0.07 / rms
        else:
            if rms > 0.0:
                gain = 0.07 / rms

        # Limit max gain to +15dB (6x) and prevent clipping
        gain = min(6.0, gain)
        if peak * gain > 0.98:
            gain = 0.98 / max(peak, 1e-6)

        if abs(gain - 1.0) < 0.01 and peak <= 1.0:
            return audio_float

        return (audio_float * gain).astype(np.float32)

    @classmethod
    def load_audio_file(
        cls,
        file_path: str,
        sample_rate: int = SAMPLE_RATE,
        normalize: bool = True
    ) -> np.ndarray:
        """Loads an audio file (WAV, MP3, M4A, etc.) as normalized 16kHz mono Float32."""
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Audio file not found: {file_path}")

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
                raise RuntimeError("FFmpeg pipe produced empty output")
        except Exception:
            import librosa
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                audio, _ = librosa.load(file_path, sr=sample_rate, mono=True)
                audio = audio.astype(np.float32)

        if normalize:
            audio = cls.normalize_audio(audio, sample_rate=sample_rate)

        return audio

    @classmethod
    def decode_bytes(
        cls,
        audio_bytes: bytes,
        sample_rate: int = SAMPLE_RATE,
        normalize: bool = True
    ) -> np.ndarray:
        """Decodes raw audio bytes from memory via ffmpeg stdin pipe."""
        cmd = [
            'ffmpeg', '-v', 'quiet', '-y',
            '-i', 'pipe:0',
            '-f', 'f32le', '-ac', '1', '-ar', str(sample_rate),
            '-'
        ]
        try:
            pipe = subprocess.Popen(
                cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL
            )
            raw_audio, _ = pipe.communicate(input=audio_bytes)
            if pipe.returncode == 0 and len(raw_audio) > 0:
                audio = np.frombuffer(raw_audio, dtype=np.float32)
            else:
                raise RuntimeError("FFmpeg decode bytes failed")
        except Exception:
            import io
            import soundfile as sf
            audio, sr = sf.read(io.BytesIO(audio_bytes), dtype='float32')
            if audio.ndim > 1:
                audio = np.mean(audio, axis=1)
            if sr != sample_rate:
                import librosa
                audio = librosa.resample(audio, orig_sr=sr, target_sr=sample_rate)

        if normalize:
            audio = cls.normalize_audio(audio, sample_rate=sample_rate)

        return audio
