"""Pipeline Runner for Quran Recite Studio.

Executes the offline alignment engine asynchronously and streams real-time
progress updates to the frontend via Server-Sent Events (SSE).
Guarantees clean Windows subprocess execution with CREATE_NO_WINDOW.
"""

from __future__ import annotations

import os
import sys
import json
import asyncio
import urllib.parse
from pathlib import Path
from typing import AsyncGenerator, Dict, Any, Optional

from fastapi import HTTPException

_CURRENT_DIR = Path(__file__).parent.resolve()
_APP_DIR = _CURRENT_DIR.parent.resolve()
_PROJECT_ROOT = _APP_DIR.parent.resolve()
for p in (str(_PROJECT_ROOT), str(_APP_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

try:
    from app.engine.config import (
        RUN_PY,
        PROJECT_ROOT,
        OUTPUT_DIR,
        CREATE_NO_WINDOW,
    )
    from app.engine.media import resolve_media_path
except ImportError:
    try:
        from .config import (
            RUN_PY,
            PROJECT_ROOT,
            OUTPUT_DIR,
            CREATE_NO_WINDOW,
        )
        from .media import resolve_media_path
    except (ImportError, ValueError):
        from engine.config import (
            RUN_PY,
            PROJECT_ROOT,
            OUTPUT_DIR,
            CREATE_NO_WINDOW,
        )
        from engine.media import resolve_media_path


async def stream_alignment_pipeline(
    audio_path_str: Optional[str] = None,
    dir_path_str: Optional[str] = None,
    fast: bool = True,
    workers: Optional[int] = None,
    threads: Optional[int] = None,
) -> AsyncGenerator[str, None]:
    """
    Spawns run.py pipeline and yields SSE formatted progress messages.
    Uses CREATE_NO_WINDOW to eliminate flashing terminal windows in desktop builds.
    Supports top-speed multi-core acceleration via --fast.
    """
    python_exe = sys.executable
    is_batch_dir = False
    display_target = ""
    target_path_str = ""

    if dir_path_str:
        dir_p = Path(dir_path_str)
        if not dir_p.is_dir():
            yield f"data: {json.dumps({'type': 'stderr', 'text': f'Directory does not exist: {dir_path_str}'})}\n\n"
            return
        cmd = [python_exe, str(RUN_PY), "--dir", str(dir_p), "--progress"]
        display_target = f"Directory: {dir_p.name}"
        is_batch_dir = True
        target_path_str = str(dir_p)
    else:
        if not audio_path_str:
            yield f"data: {json.dumps({'type': 'stderr', 'text': 'Missing audio_path parameter'})}\n\n"
            return
        audio_path = resolve_media_path(audio_path_str)
        if not audio_path or not audio_path.is_file():
            yield f"data: {json.dumps({'type': 'stderr', 'text': f'Audio file not found: {audio_path_str}'})}\n\n"
            return
        cmd = [python_exe, str(RUN_PY), "--audio", str(audio_path), "--progress"]
        display_target = f"{audio_path.name}"
        target_path_str = str(audio_path)

    if fast:
        cmd.append("--fast")
    if workers is not None:
        cmd.extend(["--workers", str(workers)])
    if threads is not None:
        cmd.extend(["--threads", str(threads)])

    yield f"data: {json.dumps({'type': 'start', 'audio': display_target, 'command': ' '.join(cmd)})}\n\n"

    # Async process execution with CREATE_NO_WINDOW
    kwargs: Dict[str, Any] = {
        "cwd": str(PROJECT_ROOT),
        "stdout": asyncio.subprocess.PIPE,
        "stderr": asyncio.subprocess.PIPE,
        "env": {**os.environ, "PYTHONUNBUFFERED": "1"},
    }
    if sys.platform == "win32":
        kwargs["creationflags"] = CREATE_NO_WINDOW

    proc = await asyncio.create_subprocess_exec(*cmd, **kwargs)

    try:
        while True:
            line = await proc.stdout.readline()
            if not line:
                break
            decoded = line.decode("utf-8", errors="replace").strip()
            if not decoded:
                continue
            try:
                parsed = json.loads(decoded)
                yield f"data: {json.dumps({'type': 'progress', 'data': parsed})}\n\n"
            except json.JSONDecodeError:
                yield f"data: {json.dumps({'type': 'stdout', 'text': decoded})}\n\n"

        stderr_out = await proc.stderr.read()
        if stderr_out:
            stderr_text = stderr_out.decode("utf-8", errors="replace").strip()
            if stderr_text:
                yield f"data: {json.dumps({'type': 'stderr', 'text': stderr_text})}\n\n"

        code = await proc.wait()
        if code == 0:
            stem = Path(target_path_str).stem if target_path_str else ""
            candidate_files = [
                PROJECT_ROOT / "output" / "all_surahs.json",
                OUTPUT_DIR / "all_surahs.json",
                PROJECT_ROOT / "output" / f"{stem}.json" if stem else None,
                OUTPUT_DIR / f"{stem}.json" if stem else None,
                PROJECT_ROOT / "output" / "output.json",
                OUTPUT_DIR / "output.json",
            ]

            result_data = None
            for cand in candidate_files:
                if cand and cand.is_file():
                    try:
                        with open(cand, "r", encoding="utf-8") as f:
                            d = json.load(f)
                        if d and "surahs" in d and len(d["surahs"]) > 0:
                            result_data = d
                            break
                        elif d and not result_data:
                            result_data = d
                    except Exception:
                        pass

            # If directory batch and no single merged file was found, merge all generated JSONs
            if is_batch_dir and (not result_data or not result_data.get("surahs")):
                all_surahs_map = {}
                search_dirs = [OUTPUT_DIR, PROJECT_ROOT / "output"]
                for sdir in search_dirs:
                    if not sdir.is_dir():
                        continue
                    for jf in sdir.rglob("*.json"):
                        if jf.name in {
                            "raw_transcription.json",
                            "recovered_speech.json",
                            "ctc_aligned_phonemes.json",
                            "qurancaption_segments.json",
                        }:
                            continue
                        try:
                            with open(jf, "r", encoding="utf-8") as f:
                                d = json.load(f)
                            for s in d.get("surahs", []):
                                s_num = s.get("surah")
                                if s_num:
                                    all_surahs_map[s_num] = s
                        except Exception:
                            pass
                if all_surahs_map:
                    result_data = {
                        "total_surahs": len(all_surahs_map),
                        "surahs": [all_surahs_map[k] for k in sorted(all_surahs_map.keys())],
                    }

            audio_url = f"/api/engine/audio/stream?path={urllib.parse.quote(target_path_str.replace(chr(92), '/'))}" if not is_batch_dir else None
            yield f"data: {json.dumps({'type': 'complete', 'code': code, 'audio_url': audio_url, 'audio_path': target_path_str, 'is_batch': is_batch_dir, 'result': result_data})}\n\n"
        else:
            yield f"data: {json.dumps({'type': 'error', 'code': code, 'message': f'Pipeline exited with error code {code}'})}\n\n"

    except Exception as exc:
        yield f"data: {json.dumps({'type': 'error', 'message': str(exc)})}\n\n"


def scan_directory_for_audio(dir_path_str: str) -> Dict[str, Any]:
    """Scans a local directory for supported audio files for batch alignment."""
    p = Path(dir_path_str.strip().strip('"').strip("'"))
    if not p.is_dir():
        raise HTTPException(status_code=400, detail=f"Directory does not exist: {dir_path_str}")

    audio_extensions = {".mp3", ".wav", ".m4a", ".ogg", ".flac", ".aac", ".opus"}
    files = []
    for f in p.iterdir():
        if f.is_file() and f.suffix.lower() in audio_extensions:
            files.append({
                "name": f.name,
                "path": str(f.resolve()).replace("\\", "/"),
                "size_bytes": f.stat().st_size,
            })

    files.sort(key=lambda x: x["name"])
    return {"directory": str(p.resolve()).replace("\\", "/"), "total_files": len(files), "audio_files": files}


if __name__ == "__main__":
    print(f"[*] Pipeline runner ready. Subprocess target: {RUN_PY}")
