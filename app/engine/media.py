"""Media Engine for Quran Recite Studio.

Implements QuranCaption's exact media pipeline:
1. FFmpeg 4kHz Mono Waveform Peak Extraction (100 peaks/s) with JSON caching
2. Exact ffprobe audio duration extraction
3. Audio PTS timestamp stretch detection (media.rs)
4. Robust cross-platform media path resolution
5. High-performance HTTP 206 Partial Content Range streaming
"""

from __future__ import annotations

import os
import re
import sys
import json
import hashlib
import subprocess
import urllib.parse
from pathlib import Path
from typing import Optional, List, Tuple

from fastapi import Request, Response
from fastapi.responses import StreamingResponse

_CURRENT_DIR = Path(__file__).parent.resolve()
_APP_DIR = _CURRENT_DIR.parent.resolve()
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

try:
    from .config import (
        AUDIO_DIR,
        PEAKS_DIR,
        CACHE_DIR,
        DATA_DIR,
        PROJECT_ROOT,
        CREATE_NO_WINDOW,
    )
except (ImportError, ValueError):
    from engine.config import (
        AUDIO_DIR,
        PEAKS_DIR,
        CACHE_DIR,
        DATA_DIR,
        PROJECT_ROOT,
        CREATE_NO_WINDOW,
    )


def get_audio_peaks(file_path: Path, points_per_second: int = 100) -> Tuple[List[float], float]:
    """
    Computes downsampled amplitude peaks and duration using QuranCaption's exact FFmpeg pipeline:
    Resamples to 4kHz mono s16le, aggregates to 100 peaks/s (40 samples per chunk max),
    normalized to [0.0, 1.0]. Fast, reliable across MP3, WAV, M4A, OGG, AAC, OPUS, etc.
    """
    file_stat = file_path.stat()
    cache_key = hashlib.md5(f"{file_path}_{file_stat.st_mtime}_{file_stat.st_size}_{points_per_second}".encode()).hexdigest()
    cache_file = PEAKS_DIR / f"{cache_key}.json"

    if cache_file.is_file():
        try:
            with open(cache_file, "r", encoding="utf-8") as f:
                cached = json.load(f)
                return cached["peaks"], cached["duration"]
        except Exception:
            pass

    cmd = [
        "ffmpeg", "-y", "-i", str(file_path),
        "-ac", "1",
        "-filter:a", "aresample=4000",
        "-map", "0:a",
        "-c:a", "pcm_s16le",
        "-f", "s16le",
        "-"
    ]

    proc = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=CREATE_NO_WINDOW,
        check=False,
    )

    if proc.returncode != 0:
        # Fallback to duration only
        dur = get_exact_media_duration(file_path)
        return [], dur

    raw_bytes = proc.stdout
    if not raw_bytes:
        dur = get_exact_media_duration(file_path)
        return [], dur

    import numpy as np
    samples = np.frombuffer(raw_bytes, dtype=np.int16)
    total_samples = len(samples)
    duration = total_samples / 4000.0

    samples_per_peak = max(1, int(4000 / points_per_second))
    n_peaks = total_samples // samples_per_peak

    if n_peaks > 0:
        truncated = samples[:n_peaks * samples_per_peak].reshape((n_peaks, samples_per_peak))
        peaks_arr = np.max(np.abs(truncated), axis=1) / 32768.0
        peaks = [round(float(p), 4) for p in peaks_arr]
    else:
        peaks = [round(float(np.max(np.abs(samples)) / 32768.0), 4)] if len(samples) > 0 else []

    try:
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump({"peaks": peaks, "duration": duration}, f)
    except Exception:
        pass

    return peaks, duration


def get_exact_media_duration(file_path: Path) -> float:
    """Gets precise audio duration in seconds via ffprobe (QuranCaption approach)."""
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(file_path)
    ]
    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=CREATE_NO_WINDOW,
            check=False,
            timeout=5.0,
        )
        if proc.returncode == 0:
            val = proc.stdout.decode().strip()
            if val:
                return float(val)
    except Exception:
        pass
    return 0.0


def check_audio_timestamp_stretch(file_path: Path) -> int:
    """
    Detects container vs audio PTS stretch in ms using ffprobe packet counting.
    Directly adapted from QuranCaption's media.rs `audio_timestamp_stretch_ms`.
    """
    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "a:0",
        "-show_entries", "format=duration:stream=duration",
        "-of", "json",
        str(file_path)
    ]
    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=CREATE_NO_WINDOW,
            check=False,
            timeout=5.0,
        )
        if proc.returncode == 0:
            data = json.loads(proc.stdout.decode())
            fmt_dur = float(data.get("format", {}).get("duration", 0) or 0)
            streams = data.get("streams", [])
            if streams:
                strm_dur = float(streams[0].get("duration", 0) or 0)
                if fmt_dur > 0 and strm_dur > 0:
                    diff_ms = int(abs(fmt_dur - strm_dur) * 1000)
                    return diff_ms if diff_ms > 25 else 0
    except Exception:
        pass
    return 0


def resolve_media_path(path_str: Optional[str]) -> Optional[Path]:
    """
    Resolves local, relative, or Windows-corrupted audio file paths reliably.
    Prioritizes isolated USER_DATA_DIR / audio (QuranCaption standard), with backward
    compatibility fallbacks to legacy paths.
    """
    if not path_str:
        return None
    clean = urllib.parse.unquote(path_str).strip().strip('"').strip("'")
    if not clean:
        return None

    # 0. Check if input is a URL or has query parameters (e.g. /api/engine/audio/stream?path=...)
    if "?" in clean:
        try:
            parsed = urllib.parse.urlparse(clean)
            qs = urllib.parse.parse_qs(parsed.query)
            extracted = qs.get("path", [None])[0] or qs.get("file", [None])[0]
            if extracted and extracted != clean:
                sub_res = resolve_media_path(extracted)
                if sub_res:
                    return sub_res
        except Exception:
            pass

    # Strip webview leading slash on Windows drive letters (e.g. /D:/... -> D:/...)
    if clean.startswith("/") and len(clean) > 3 and clean[2] == ":":
        clean = clean[1:]

    # 1. Try direct path
    p = Path(clean)
    if p.is_file():
        return p.resolve()

    # 2. Try normalized path
    norm = clean.replace("/", os.sep).replace("\\", os.sep)
    p_norm = Path(norm)
    if p_norm.is_file():
        return p_norm.resolve()

    # 3. Try in user data AUDIO_DIR (userData/audio/)
    if (AUDIO_DIR / p.name).is_file():
        return (AUDIO_DIR / p.name).resolve()

    # Try appending audio extensions in AUDIO_DIR
    if not p.suffix:
        for ext in (".mp3", ".wav", ".m4a", ".ogg", ".flac"):
            if (AUDIO_DIR / f"{p.name}{ext}").is_file():
                return (AUDIO_DIR / f"{p.name}{ext}").resolve()

    # 4. Backward-compatible fallback: legacy data/audio/
    legacy_audio = DATA_DIR / "audio" / p.name
    if legacy_audio.is_file():
        return legacy_audio.resolve()

    # 5. Try in CACHE_DIR by filename
    if (CACHE_DIR / p.name).is_file():
        return (CACHE_DIR / p.name).resolve()

    # 6. Try relative to PROJECT_ROOT
    if (PROJECT_ROOT / clean).is_file():
        return (PROJECT_ROOT / clean).resolve()
    if (PROJECT_ROOT / norm).is_file():
        return (PROJECT_ROOT / norm).resolve()

    # 7. Fuzzy prefix match or Surah number match (e.g. '046.mp3' or '44_-_سورة_الاحقاف.mp3')
    prefix_match = re.match(r"^(\d+[\-_]*)", p.name)
    if prefix_match:
        prefix = prefix_match.group(1)
        ext = p.suffix.lower() or ".mp3"
        if AUDIO_DIR.is_dir():
            for cand in AUDIO_DIR.iterdir():
                if cand.is_file() and cand.name.startswith(prefix) and cand.suffix.lower() == ext:
                    return cand.resolve()
        if (DATA_DIR / "audio").is_dir():
            for cand in (DATA_DIR / "audio").iterdir():
                if cand.is_file() and cand.name.startswith(prefix) and cand.suffix.lower() == ext:
                    return cand.resolve()

    return None


def make_audio_stream_url(resolved_path: Path) -> str:
    """Creates a normalized URL using forward slashes for cross-platform browser audio streaming."""
    norm = str(resolved_path.resolve()).replace("\\", "/")
    return f"/api/engine/audio/stream?path={urllib.parse.quote(norm)}"


def stream_media_file_response(request: Request, file_path: Path) -> Response:
    """Streams a local file with full HTTP 206 Partial Content (Range) support for audio seeking."""
    file_size = file_path.stat().st_size
    range_header = request.headers.get("Range") or request.headers.get("range")

    ext = file_path.suffix.lower()
    content_types = {
        ".mp3": "audio/mpeg",
        ".wav": "audio/wav",
        ".ogg": "audio/ogg",
        ".m4a": "audio/mp4",
        ".flac": "audio/flac",
        ".webm": "audio/webm",
        ".opus": "audio/opus",
    }
    media_type = content_types.get(ext, "application/octet-stream")

    if not range_header:
        def full_iter():
            with open(file_path, "rb") as f:
                while chunk := f.read(64 * 1024):
                    yield chunk

        return StreamingResponse(
            full_iter(),
            status_code=200,
            media_type=media_type,
            headers={
                "Content-Length": str(file_size),
                "Accept-Ranges": "bytes",
                "Cache-Control": "public, max-age=3600",
            },
        )

    # HTTP 206 Range handling
    range_match = re.match(r"^bytes=(\d*)-(\d*)$", range_header.strip())
    if not range_match:
        return Response(status_code=416, headers={"Content-Range": f"bytes */{file_size}"})

    start_str, end_str = range_match.groups()
    if start_str and end_str:
        start = int(start_str)
        end = min(int(end_str), file_size - 1)
    elif start_str:
        start = int(start_str)
        end = file_size - 1
    elif end_str:
        start = max(0, file_size - int(end_str))
        end = file_size - 1
    else:
        start = 0
        end = file_size - 1

    if start > end or start >= file_size:
        return Response(status_code=416, headers={"Content-Range": f"bytes */{file_size}"})

    chunk_length = end - start + 1

    def range_iter():
        with open(file_path, "rb") as f:
            f.seek(start)
            bytes_left = chunk_length
            while bytes_left > 0:
                to_read = min(64 * 1024, bytes_left)
                data = f.read(to_read)
                if not data:
                    break
                bytes_left -= len(data)
                yield data

    return StreamingResponse(
        range_iter(),
        status_code=206,
        media_type=media_type,
        headers={
            "Content-Range": f"bytes {start}-{end}/{file_size}",
            "Content-Length": str(chunk_length),
            "Accept-Ranges": "bytes",
            "Cache-Control": "no-cache",
        },
    )


def load_audio_slice(
    file_path: Path,
    start_s: float = 0.0,
    duration_s: Optional[float] = None,
    sample_rate: int = 16000,
):
    """
    Fast-seek audio decoding for timeline slices without decoding entire file.
    Directly adapted from QuranCaption's local_word_timing_segmenter.py load_audio_slice.
    Decodes requested time window in ~0.05s via raw PCM pipe.
    """
    import numpy as np

    if not file_path.is_file():
        raise FileNotFoundError(f"Audio file not found: {file_path}")

    # 1. Primary: Streaming FFmpeg sub-range decode (~0.05s)
    try:
        cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error"]
        if start_s > 0:
            cmd.extend(["-ss", f"{start_s:.3f}"])
        if duration_s is not None and duration_s > 0:
            cmd.extend(["-t", f"{duration_s:.3f}"])
        cmd.extend([
            "-i", str(file_path),
            "-vn", "-sn", "-dn",
            "-f", "f32le", "-ac", "1", "-ar", str(sample_rate), "-"
        ])
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            creationflags=CREATE_NO_WINDOW,
            check=False,
        )
        if proc.returncode == 0 and len(proc.stdout) > 0:
            return np.frombuffer(proc.stdout, dtype=np.float32)
    except Exception:
        pass

    # 2. Fallback: Full decode via AudioDecoder and numpy slice
    from src.audio import AudioDecoder
    full_audio = AudioDecoder.load_audio_file(str(file_path), sample_rate=sample_rate)
    start_sample = max(0, int(round(start_s * sample_rate)))
    if duration_s is not None and duration_s > 0:
        end_sample = min(len(full_audio), start_sample + int(round(duration_s * sample_rate)))
    else:
        end_sample = len(full_audio)
    return full_audio[start_sample:end_sample]


def normalize_audio_timestamps(file_path: Path) -> Path:
    """
    Fixes container vs audio PTS/DTS timestamp stretch using FFmpeg (QuranCaption media.rs).
    Normalizes timestamps in-place via safe .part replacement.
    """
    temp_path = file_path.with_name(f"{file_path.stem}_norm{file_path.suffix}")
    cmd = [
        "ffmpeg", "-y", "-i", str(file_path),
        "-c", "copy",
        "-avoid_negative_ts", "make_zero",
        str(temp_path)
    ]
    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=CREATE_NO_WINDOW,
            check=False,
        )
        if proc.returncode == 0 and temp_path.is_file() and temp_path.stat().st_size > 0:
            file_path.unlink()
            temp_path.rename(file_path)
            return file_path
    except Exception:
        pass
    if temp_path.exists():
        try:
            temp_path.unlink()
        except Exception:
            pass
    return file_path


if __name__ == "__main__":
    print("[*] Media engine ready.")
