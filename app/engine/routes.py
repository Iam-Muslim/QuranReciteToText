"""FastAPI Route Aggregator for Quran Recite Studio.

Defines all HTTP endpoints cleanly separated by domain, maintaining
100% backward compatibility with all frontend calls while adding
QuranCaption-grade desktop capabilities.
"""

from __future__ import annotations

import sys
import time
import json
import asyncio
from pathlib import Path
from typing import Optional, Dict, Any

from fastapi import APIRouter, HTTPException, Request, Response, Query, UploadFile, File
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel

_CURRENT_DIR = Path(__file__).parent.resolve()
_APP_DIR = _CURRENT_DIR.parent.resolve()
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

try:
    from .config import (
        AUDIO_DIR,
        PROJECTS_DIR,
        OUTPUT_DIR,
        PROJECT_ROOT,
        USER_DATA_DIR,
        get_unique_destination,
        sanitize_filename,
    )
    from .media import (
        get_audio_peaks,
        get_exact_media_duration,
        check_audio_timestamp_stretch,
        resolve_media_path,
        make_audio_stream_url,
        stream_media_file_response,
    )
    from .projects import (
        list_projects_service,
        load_project_service,
        save_project_service,
        create_project_service,
        delete_project_service,
        duplicate_project_service,
        prune_orphaned_audio_service,
    )
    from .pipeline import (
        stream_alignment_pipeline,
        scan_directory_for_audio,
        kill_pipeline_process,
    )
    from .quran import get_verse_word_from_location
    from .system import (
        get_storage_diagnostics,
        open_in_explorer,
        native_pick_directory,
    )
except (ImportError, ValueError):
    from engine.config import (
        AUDIO_DIR,
        PROJECTS_DIR,
        OUTPUT_DIR,
        PROJECT_ROOT,
        USER_DATA_DIR,
        get_unique_destination,
        sanitize_filename,
    )
    from engine.media import (
        get_audio_peaks,
        get_exact_media_duration,
        check_audio_timestamp_stretch,
        resolve_media_path,
        make_audio_stream_url,
        stream_media_file_response,
    )
    from engine.projects import (
        list_projects_service,
        load_project_service,
        save_project_service,
        create_project_service,
        delete_project_service,
        duplicate_project_service,
        prune_orphaned_audio_service,
    )
    from engine.pipeline import (
        stream_alignment_pipeline,
        scan_directory_for_audio,
        kill_pipeline_process,
    )
    from engine.quran import get_verse_word_from_location
    from engine.system import (
        get_storage_diagnostics,
        open_in_explorer,
        native_pick_directory,
    )

router = APIRouter()

# In-Memory Cache for latest output
_latest_json_cache: Dict[str, Any] = {"mtime": 0, "content": None}


# ==============================================================================
# 1. System & Storage Diagnostics
# ==============================================================================

@router.get("/status")
@router.get("/health")
@router.get("/ping")
@router.get("/storage_info")
async def get_system_status():
    """Returns engine diagnostics, storage partition paths, and disk metrics."""
    return get_storage_diagnostics()


@router.post("/system/reveal")
async def reveal_file_in_explorer(request: Request):
    """Reveals the given file or folder in native OS File Explorer (QuranCaption design)."""
    body = await request.json()
    raw_path = (body.get("path") or body.get("file_path") or "").strip()
    if not raw_path:
        raise HTTPException(status_code=400, detail="Missing path parameter")

    raw_path = raw_path.strip().strip('"').strip("'")
    base_name = Path(raw_path).name

    if raw_path.lower() in ("projects", "projects_dir"):
        resolved = PROJECTS_DIR
    elif raw_path.lower() in ("audio", "audio_dir"):
        resolved = AUDIO_DIR
    elif (PROJECTS_DIR / raw_path).exists():
        resolved = PROJECTS_DIR / raw_path
    elif (PROJECTS_DIR / base_name).exists():
        resolved = PROJECTS_DIR / base_name
    elif (PROJECT_ROOT / "projects" / base_name).exists():
        resolved = PROJECT_ROOT / "projects" / base_name
    elif (AUDIO_DIR / base_name).exists():
        resolved = AUDIO_DIR / base_name
    elif (PROJECT_ROOT / raw_path).exists():
        resolved = PROJECT_ROOT / raw_path
    else:
        resolved = resolve_media_path(raw_path) or Path(raw_path)

    if not resolved.exists():
        raise HTTPException(status_code=404, detail=f"Path not found: {raw_path}")

    ok = open_in_explorer(resolved)
    return {"success": ok, "path": str(resolved)}


# ==============================================================================
# 2. Audio Streaming & Waveform Peak Extraction
# ==============================================================================

@router.get("/audio")
@router.head("/audio")
@router.get("/audio/stream")
@router.head("/audio/stream")
async def stream_audio(request: Request, path: Optional[str] = None, file: Optional[str] = None):
    """Streams audio with HTTP 206 Partial Content (Range) for instant browser seeking."""
    target_path = resolve_media_path(path) or resolve_media_path(file)
    if not target_path or not target_path.is_file():
        raise HTTPException(status_code=404, detail=f"Audio file not found: {path or file}")
    return stream_media_file_response(request, target_path)


@router.get("/audio/peaks")
async def audio_peaks(path: Optional[str] = None, file: Optional[str] = None, pps: int = 100):
    """Computes downsampled waveform peaks using QuranCaption's FFmpeg pipeline."""
    target_path = resolve_media_path(path) or resolve_media_path(file)
    if not target_path or not target_path.is_file():
        raise HTTPException(status_code=404, detail=f"Audio file not found: {path or file}")

    try:
        peaks, duration = await asyncio.to_thread(get_audio_peaks, target_path, pps)
        return {
            "path": str(target_path).replace("\\", "/"),
            "duration": duration,
            "points_per_second": pps,
            "total_peaks": len(peaks),
            "peaks": peaks,
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Peak extraction error: {exc}")


class AudioLoadRequest(BaseModel):
    path: Optional[str] = None
    file: Optional[str] = None


@router.post("/audio/load")
@router.get("/audio/load")
async def load_audio_endpoint(
    request: Request,
    path: Optional[str] = None,
    file: Optional[str] = None,
    load_req: Optional[AudioLoadRequest] = None,
):
    """Loads audio file metadata, waveform peaks, PTS stretch status, and streaming URL."""
    target_str = None
    if load_req and (load_req.path or load_req.file):
        target_str = load_req.path or load_req.file
    elif path or file:
        target_str = path or file
    elif request.method == "POST":
        try:
            body = await request.json()
            target_str = body.get("path") or body.get("file")
        except Exception:
            pass

    if not target_str:
        raise HTTPException(status_code=400, detail="Missing audio path parameter")

    resolved_path = resolve_media_path(target_str)
    if not resolved_path:
        raise HTTPException(status_code=404, detail=f"Audio file not found: {target_str}")

    peaks, duration = await asyncio.to_thread(get_audio_peaks, resolved_path, 100)
    stretch_ms = check_audio_timestamp_stretch(resolved_path)
    stream_url = make_audio_stream_url(resolved_path)

    return {
        "success": True,
        "filePath": str(resolved_path).replace("\\", "/"),
        "path": str(resolved_path).replace("\\", "/"),
        "fileName": resolved_path.name,
        "filename": resolved_path.name,
        "duration": duration,
        "peaks": peaks,
        "url": stream_url,
        "stretch_ms": stretch_ms,
    }


@router.post("/audio/upload")
@router.post("/upload")
async def upload_audio_endpoint(
    request: Request,
    file: Optional[UploadFile] = File(None),
):
    """
    Saves an uploaded audio file into isolated USER_DATA_DIR / audio using
    collision-free unique destination naming (QuranCaption BatchMediaService approach).
    """
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)

    if file is not None and file.filename:
        orig_name = Path(file.filename).name
        target_path = get_unique_destination(AUDIO_DIR, orig_name)
        content = await file.read()
        with open(target_path, "wb") as f:
            f.write(content)
    else:
        content = await request.body()
        if not content:
            raise HTTPException(status_code=400, detail="Empty audio payload")

        filename_header = request.headers.get("x-filename") or request.headers.get("x-file-name")
        ext = request.headers.get("x-file-ext", "mp3").lstrip(".")
        if filename_header:
            safe_base = sanitize_filename(Path(filename_header).name)
        else:
            safe_base = f"recitation_{int(time.time() * 1000)}.{ext}"

        target_path = get_unique_destination(AUDIO_DIR, safe_base)
        with open(target_path, "wb") as f:
            f.write(content)

    stream_url = make_audio_stream_url(target_path)
    peaks = []
    duration = 0.0
    stretch_ms = 0.0

    # Only extract peaks if explicitly requested (skips 15-20s FFmpeg blocking during alignment upload)
    extract_param = request.query_params.get("extract_peaks", "").lower() in ("1", "true")
    if extract_param:
        peaks, duration = await asyncio.to_thread(get_audio_peaks, target_path, 100)
        stretch_ms = check_audio_timestamp_stretch(target_path)

    return {
        "success": True,
        "filePath": str(target_path).replace("\\", "/"),
        "path": str(target_path).replace("\\", "/"),
        "fileName": target_path.name,
        "duration": duration,
        "peaks": peaks,
        "url": stream_url,
        "stretch_ms": stretch_ms,
    }


@router.get("/cached_audio")
async def list_cached_audio():
    """Returns available audio files in USER_DATA_DIR / audio for quick project restore."""
    try:
        AUDIO_DIR.mkdir(parents=True, exist_ok=True)
        results = []
        for f in AUDIO_DIR.iterdir():
            if f.is_file() and f.suffix.lower() in (".mp3", ".wav", ".m4a", ".ogg", ".flac"):
                results.append({
                    "name": f.name,
                    "path": str(f).replace("\\", "/"),
                    "size_bytes": f.stat().st_size,
                    "url": make_audio_stream_url(f),
                })
        results.sort(key=lambda x: x["name"])
        return {"audio_files": results}
    except Exception:
        return {"audio_files": []}


# ==============================================================================
# 3. Alignment Pipeline & Batch Scanner
# ==============================================================================

@router.post("/system/pick_dir")
@router.get("/system/pick_dir")
async def pick_directory_endpoint(title: Optional[str] = Query("Select Quran Recitations Folder")):
    """Opens native host OS folder picker directly on desktop and automatically scans the selected folder."""
    selected = await asyncio.to_thread(native_pick_directory, title)
    if selected:
        scan_result = scan_directory_for_audio(selected)
        return {
            "success": True,
            "directory": selected,
            "path": selected,
            **scan_result,
        }
    return {
        "success": False,
        "directory": "",
        "path": "",
        "files": [],
        "audio_files": [],
    }


@router.post("/scan_dir")
@router.get("/scan_dir")
async def scan_directory(request: Request, dir_path: Optional[str] = Query(None)):
    """Scans a local directory for audio files for batch alignment."""
    target = dir_path
    if not target and request.method == "POST":
        try:
            body = await request.json()
            target = body.get("dir_path") or body.get("directory")
        except Exception:
            pass
    if not target:
        raise HTTPException(status_code=400, detail="Missing dir_path parameter")
    return scan_directory_for_audio(target)


@router.post("/batch/upload_folder")
async def upload_batch_folder(request: Request, files: list[UploadFile] = File(...)):
    """
    Saves multiple browser-loaded audio files into an isolated batch directory in USER_DATA_DIR.
    Enables native high-speed parallel alignment even for browser-dragged or browser-selected files.
    """
    batch_dir = USER_DATA_DIR / "batch" / f"batch_{int(time.time() * 1000)}"
    batch_dir.mkdir(parents=True, exist_ok=True)
    saved_files = []
    for f in files:
        if not f.filename:
            continue
        safe_name = sanitize_filename(Path(f.filename).name)
        target = batch_dir / safe_name
        content = await f.read()
        target.write_bytes(content)
        saved_files.append({
            "name": safe_name,
            "rel_path": safe_name,
            "path": str(target).replace("\\", "/"),
            "size": len(content),
            "size_bytes": len(content),
        })
    return {
        "success": True,
        "directory": str(batch_dir).replace("\\", "/"),
        "total_files": len(saved_files),
        "files": saved_files,
        "audio_files": saved_files,
    }


@router.post("/align/stop")
@router.get("/align/stop")
@router.post("/align/cancel")
async def stop_alignment_pipeline():
    """Immediately stops and terminates active alignment pipeline subprocess tree, dropping CPU to 0%."""
    killed = kill_pipeline_process()
    return {"success": True, "stopped": killed}



class AlignRequest(BaseModel):
    audio_path: Optional[str] = None
    dir_path: Optional[str] = None
    fast: bool = True
    workers: Optional[int] = None
    threads: Optional[int] = None


@router.post("/align")
@router.get("/align")
async def align_audio_sse(
    request: Request,
    align_req: Optional[AlignRequest] = None,
    audio_path: Optional[str] = Query(None),
    dir_path: Optional[str] = Query(None),
    fast: bool = Query(True),
):
    """Streams real-time alignment progress via Server-Sent Events (SSE)."""
    target_audio = audio_path
    target_dir = dir_path
    fast_mode = fast
    workers = None
    threads = None

    if align_req:
        target_audio = align_req.audio_path or target_audio
        target_dir = align_req.dir_path or target_dir
        fast_mode = align_req.fast
        workers = align_req.workers
        threads = align_req.threads
    elif request.method == "POST":
        try:
            body = await request.json()
            target_audio = body.get("audio_path") or target_audio
            target_dir = body.get("dir_path") or target_dir
            if "fast" in body:
                fast_mode = bool(body["fast"])
            workers = body.get("workers")
            threads = body.get("threads")
        except Exception:
            pass

    return StreamingResponse(
        stream_alignment_pipeline(
            audio_path_str=target_audio,
            dir_path_str=target_dir,
            fast=fast_mode,
            workers=workers,
            threads=threads,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )





@router.get("/load_latest")
async def load_latest_output():
    """Loads latest output.json from the alignment pipeline."""
    output_json = OUTPUT_DIR / "output.json"
    if not output_json.is_file():
        legacy_out = PROJECT_ROOT / "output" / "output.json"
        if legacy_out.is_file():
            output_json = legacy_out
        else:
            raise HTTPException(status_code=404, detail="output/output.json not found")

    stat = output_json.stat()
    if _latest_json_cache["mtime"] != stat.st_mtime or _latest_json_cache["content"] is None:
        with open(output_json, "r", encoding="utf-8") as f:
            _latest_json_cache["content"] = json.load(f)
            _latest_json_cache["mtime"] = stat.st_mtime

    return _latest_json_cache["content"]


# ==============================================================================
# 4. Project Management (.qproj)
# ==============================================================================

@router.get("/projects")
@router.get("/projects/list")
async def list_projects():
    """Lists saved projects from projects/ directory (QuranCaption single-file design)."""
    return list_projects_service()


@router.get("/projects/load")
async def load_project_file(file: str = Query(...)):
    """Loads a project file in-place and automatically resolves audio recitations."""
    return load_project_service(file)


@router.post("/projects/save")
@router.post("/save_project")
async def save_project_state(request: Request):
    """Saves project state atomically using a .part file guard."""
    data = await request.json()
    return save_project_service(data)


@router.post("/projects/create")
async def create_project(request: Request):
    """Creates a new project file directly in projects/."""
    body = await request.json()
    name = body.get("name") or "New Quran Project"
    reciter = body.get("reciter") or ""
    riwayah = body.get("riwayah") or "Hafs 'an 'Asim"
    return create_project_service(name, reciter, riwayah)


@router.post("/projects/delete")
async def delete_project(request: Request):
    """Deletes a project file from projects/."""
    body = await request.json()
    file_name = body.get("file_name") or ""
    if not file_name:
        raise HTTPException(status_code=400, detail="Missing file_name")
    return delete_project_service(file_name)


@router.post("/projects/duplicate")
async def duplicate_project(request: Request):
    """Duplicates a project file cleanly following QuranCaption ProjectService.duplicate."""
    body = await request.json()
    file_name = body.get("file_name") or ""
    if not file_name:
        raise HTTPException(status_code=400, detail="Missing file_name")
    return duplicate_project_service(file_name)


@router.post("/projects/prune_audio")
async def prune_unreferenced_audio():
    """
    Reference-counted garbage collection (adapted directly from QuranCaption's pruneOrphanedQuaCache).
    Removes audio files from audio/ that are no longer referenced by ANY active project.
    """
    return prune_orphaned_audio_service()


# ==============================================================================
# 5. Quran Verse & Word Linguistic Lookup
# ==============================================================================

@router.get("/quran/word")
@router.get("/quran/verse_word")
async def get_quran_verse_word(
    location: Optional[str] = Query(None),
    surah: Optional[int] = Query(None),
    ayah: Optional[int] = Query(None),
    word: Optional[int] = Query(None),
):
    """Looks up specific Arabic word text for verification and correction (Supports location='85:1:1')."""
    if location:
        parts = location.strip().split(":")
        if len(parts) == 3:
            try:
                surah = int(parts[0])
                ayah = int(parts[1])
                word = int(parts[2])
            except ValueError:
                return JSONResponse(status_code=400, content={"success": False, "error": "Invalid location format. Expected 'surah:ayah:word'"})
        else:
            return JSONResponse(status_code=400, content={"success": False, "error": "Invalid location format. Expected 'surah:ayah:word'"})

    if surah is None or ayah is None or word is None:
        return JSONResponse(status_code=400, content={"success": False, "error": "Missing surah, ayah, or word parameters"})

    res = get_verse_word_from_location(surah, ayah, word)
    return JSONResponse(status_code=200, content=res)




