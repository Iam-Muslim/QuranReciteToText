"""Project Management Service for Quran Recite Studio.

Mirrors QuranCaption's ProjectService & QuaAudioCache architecture:
1. Single-file project state management (.qproj)
2. Atomic saving using .part temporary files to prevent corrupted state on crash
3. Fast metadata listing for responsive Projects Hub
4. Reference-counted orphan audio pruning (pruneOrphanedQuaCache design)
"""

from __future__ import annotations

import sys
import time
import json
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

from fastapi import HTTPException

_CURRENT_DIR = Path(__file__).parent.resolve()
_APP_DIR = _CURRENT_DIR.parent.resolve()
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

try:
    from .config import (
        PROJECTS_DIR,
        OUTPUT_DIR,
        AUDIO_DIR,
        PROJECT_ROOT,
        sanitize_filename,
        atomic_write_json,
    )
    from .media import (
        resolve_media_path,
        make_audio_stream_url,
        get_exact_media_duration,
    )
except (ImportError, ValueError):
    from engine.config import (
        PROJECTS_DIR,
        OUTPUT_DIR,
        AUDIO_DIR,
        PROJECT_ROOT,
        sanitize_filename,
        atomic_write_json,
    )
    from engine.media import (
        resolve_media_path,
        make_audio_stream_url,
        get_exact_media_duration,
    )

# In-memory fast project summary cache: filename -> (mtime, size, summary_dict)
_projects_summary_cache: Dict[str, Tuple[float, int, Dict[str, Any]]] = {}


def list_projects_service() -> Dict[str, Any]:
    """Lists saved projects from projects/ directory (QuranCaption single-file design)."""
    PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
    projects_list = []
    seen_files = set()

    search_dirs = [PROJECTS_DIR]
    legacy_dir = PROJECT_ROOT / "projects"
    if legacy_dir.is_dir() and legacy_dir.resolve() != PROJECTS_DIR.resolve():
        search_dirs.append(legacy_dir)

    for p_dir in search_dirs:
        for f in p_dir.glob("*.qproj"):
            if f.name in seen_files:
                continue
            try:
                stat = f.stat()
                seen_files.add(f.name)

                # Instant sub-millisecond cache check
                if f.name in _projects_summary_cache:
                    c_mtime, c_size, c_data = _projects_summary_cache[f.name]
                    if c_mtime == stat.st_mtime and c_size == stat.st_size:
                        projects_list.append(c_data)
                        continue

                with open(f, "r", encoding="utf-8") as fp:
                    data = json.load(fp)
                surahs = data.get("surahs", [])
                total_ayahs = sum(len(s.get("ayahs", [])) for s in surahs)
                total_duration = sum(s.get("audio_duration_seconds", 0) for s in surahs)

                first_surah = surahs[0] if surahs else {}
                status = data.get("status") or (first_surah.get("status") if first_surah else "draft")
                riwayah = data.get("riwayah") or data.get("settings", {}).get("riwayah", "Hafs 'an 'Asim")
                surah_numbers = [s.get("surah_number") for s in surahs if s.get("surah_number")]
                primary_surah = {
                    "surah_number": first_surah.get("surah_number"),
                    "surah_name_arabic": first_surah.get("surah_name_arabic", ""),
                    "surah_name_english": first_surah.get("surah_name_english", ""),
                } if first_surah else None

                summary = {
                    "file_name": f.name,
                    "project_name": data.get("project_name", f.stem),
                    "reciter": data.get("reciter", ""),
                    "riwayah": riwayah,
                    "status": status,
                    "surahs_count": len(surahs),
                    "surah_numbers": surah_numbers,
                    "primary_surah": primary_surah,
                    "total_ayahs": total_ayahs,
                    "total_duration": total_duration,
                    "created_at": data.get("created_at", ""),
                    "updated_at": data.get("updated_at", stat.st_mtime),
                    "size_bytes": stat.st_size,
                }
                _projects_summary_cache[f.name] = (stat.st_mtime, stat.st_size, summary)
                projects_list.append(summary)
            except Exception:
                continue

    projects_list.sort(key=lambda x: str(x.get("updated_at", "")), reverse=True)
    return {"projects": projects_list}


def load_project_service(file_query: str) -> Dict[str, Any]:
    """Loads a project file in-place and automatically resolves audio recitations."""
    safe_name = Path(file_query.strip().strip('"').strip("'")).name
    target = PROJECTS_DIR / safe_name
    if not target.is_file():
        legacy_target = PROJECT_ROOT / "projects" / safe_name
        if legacy_target.is_file():
            target = legacy_target

    if not target.is_file():
        raise HTTPException(status_code=404, detail=f"Project file not found: {file_query}")

    with open(target, "r", encoding="utf-8") as f:
        data = json.load(f)

    data["file_name"] = target.name

    # Auto-resolve audio for every surah so WaveSurfer loads immediately
    for s in data.get("surahs", []):
        raw_audio = s.get("audio_file") or s.get("audio_path")
        resolved = resolve_media_path(raw_audio) if raw_audio else None

        # Auto-match audio if path was missing (QuranCaption resilient loading)
        if not resolved or not resolved.is_file():
            surah_num = s.get("surah_number")
            if surah_num:
                resolved = (
                    resolve_media_path(f"{surah_num:03d}.mp3")
                    or resolve_media_path(f"{surah_num}.mp3")
                    or resolve_media_path(str(surah_num))
                )
            if not resolved and s.get("surah_name_english"):
                resolved = resolve_media_path(s["surah_name_english"])

        if resolved and resolved.is_file():
            s["audio_file"] = str(resolved).replace("\\", "/")
            s["audio_path"] = str(resolved).replace("\\", "/")
            s["audio_url"] = make_audio_stream_url(resolved)
            if not s.get("audio_duration_seconds") or s.get("audio_duration_seconds", 0) <= 0:
                s["audio_duration_seconds"] = get_exact_media_duration(resolved)

    return data


def save_project_service(data: Dict[str, Any]) -> Dict[str, Any]:
    """Saves project state atomically using a .part file guard to prevent file corruption."""
    file_name = data.get("file_name")

    if not file_name:
        project_name = data.get("project_name", "project")
        safe_name = sanitize_filename(project_name) or "project"
        file_name = f"{safe_name}.qproj"
        data["file_name"] = file_name

    PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
    target = PROJECTS_DIR / Path(file_name).name
    data["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    # Atomic write guard (QuranCaption architecture)
    atomic_write_json(target, data, indent=2)

    return {
        "success": True,
        "file_path": str(target).replace("\\", "/"),
        "file_name": target.name,
    }


def create_project_service(name: str, reciter: str, riwayah: str = "Hafs 'an 'Asim") -> Dict[str, Any]:
    """Creates a new project file directly in projects/ (QuranCaption single-file design)."""
    clean_name = (name or "New Quran Project").strip()
    clean_reciter = (reciter or "").strip()
    clean_riwayah = (riwayah or "Hafs 'an 'Asim").strip()

    safe_slug = sanitize_filename(clean_name) or "project"
    file_name = f"{safe_slug}.qproj"
    PROJECTS_DIR.mkdir(parents=True, exist_ok=True)

    counter = 1
    target = PROJECTS_DIR / file_name
    while target.is_file():
        file_name = f"{safe_slug}_{counter}.qproj"
        target = PROJECTS_DIR / file_name
        counter += 1

    new_project = {
        "project_name": clean_name,
        "reciter": clean_reciter,
        "riwayah": clean_riwayah,
        "file_name": file_name,
        "status": "draft",
        "app_version": "2.0.0",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "settings": {
            "riwayah": clean_riwayah,
            "snapping_tolerance_ms": 15,
            "confidence_warning_threshold": 0.85,
            "auto_save_interval_s": 60,
        },
        "surahs": [],
    }

    atomic_write_json(target, new_project, indent=2)

    return {
        "success": True,
        "project": new_project,
        "file_name": file_name,
    }


def delete_project_service(file_name: str) -> Dict[str, Any]:
    """Deletes a project file from projects/."""
    safe_name = Path(file_name.strip()).name
    deleted = False

    target = PROJECTS_DIR / safe_name
    if target.is_file():
        target.unlink()
        deleted = True

    legacy = OUTPUT_DIR / safe_name
    if legacy.is_file():
        legacy.unlink()
        deleted = True

    if deleted:
        return {"success": True, "deleted": safe_name}

    raise HTTPException(status_code=404, detail=f"Project file not found: {safe_name}")


def duplicate_project_service(file_name: str) -> Dict[str, Any]:
    """Duplicates a project file cleanly following QuranCaption's ProjectService.duplicate."""
    safe_name = Path(file_name.strip()).name
    source = PROJECTS_DIR / safe_name
    if not source.is_file():
        legacy_source = PROJECT_ROOT / "projects" / safe_name
        if legacy_source.is_file():
            source = legacy_source
        else:
            raise HTTPException(status_code=404, detail=f"Project not found: {safe_name}")

    stem = source.stem
    new_file_name = f"{stem}_Copy.qproj"
    new_target = PROJECTS_DIR / new_file_name

    counter = 1
    while new_target.is_file():
        new_file_name = f"{stem}_Copy_{counter}.qproj"
        new_target = PROJECTS_DIR / new_file_name
        counter += 1

    with open(source, "r", encoding="utf-8") as f:
        data = json.load(f)

    data["project_name"] = f"{data.get('project_name', stem)} (Copy)"
    data["file_name"] = new_file_name
    data["created_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    data["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    atomic_write_json(new_target, data, indent=2)

    return {
        "success": True,
        "file_name": new_file_name,
        "project": data,
    }


def prune_orphaned_audio_service() -> Dict[str, Any]:
    """
    Reference-counted garbage collection (adapted directly from QuranCaption's pruneOrphanedQuaCache).
    Scans all remaining project JSONs in PROJECTS_DIR.
    Any audio file in AUDIO_DIR that is no longer referenced by ANY active project is deleted.
    Prevents silent accumulation of gigabytes of orphaned audio files.
    """
    if not AUDIO_DIR.is_dir():
        return {"pruned_count": 0, "pruned_files": [], "freed_bytes": 0}

    # 1. Collect all referenced audio files across all projects
    referenced_files = set()
    for f in PROJECTS_DIR.glob("*.qproj"):
        try:
            with open(f, "r", encoding="utf-8") as fp:
                proj = json.load(fp)
            for s in proj.get("surahs", []):
                for key in ("audio_file", "audio_path"):
                    val = s.get(key)
                    if val:
                        referenced_files.add(Path(val).name.lower())
        except Exception:
            continue

    # 2. Identify unreferenced files in AUDIO_DIR
    pruned = []
    freed_bytes = 0
    for aud in AUDIO_DIR.iterdir():
        if not aud.is_file():
            continue
        if aud.name.lower() not in referenced_files:
            try:
                sz = aud.stat().st_size
                aud.unlink()
                pruned.append(aud.name)
                freed_bytes += sz
            except Exception:
                pass

    return {
        "pruned_count": len(pruned),
        "pruned_files": pruned,
        "freed_bytes": freed_bytes,
        "freed_mb": round(freed_bytes / (1024 * 1024), 2),
    }
