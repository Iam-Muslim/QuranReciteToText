"""System & Diagnostics Engine for Quran Recite Studio.

Implements native OS integration inspired by QuranCaption:
1. Reveal files in native OS File Explorer (open_explorer_with_file_selected)
2. Accurate directory size and disk consumption calculations
3. Storage breakdown diagnostics
"""

from __future__ import annotations

import os
import sys
import subprocess
from pathlib import Path
from typing import Dict, Any

_CURRENT_DIR = Path(__file__).parent.resolve()
_APP_DIR = _CURRENT_DIR.parent.resolve()
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

try:
    from .config import (
        USER_DATA_DIR,
        PROJECTS_DIR,
        AUDIO_DIR,
        EXPORTS_DIR,
        CACHE_DIR,
        PEAKS_DIR,
        PROJECT_ROOT,
        RUN_PY,
    )
except (ImportError, ValueError):
    from engine.config import (
        USER_DATA_DIR,
        PROJECTS_DIR,
        AUDIO_DIR,
        EXPORTS_DIR,
        CACHE_DIR,
        PEAKS_DIR,
        PROJECT_ROOT,
        RUN_PY,
    )


def open_in_explorer(file_or_dir: Path) -> bool:
    """
    Reveals the file or folder in native OS File Explorer (QuranCaption media.rs open_explorer_with_file_selected).
    """
    p = file_or_dir.resolve()
    if not p.exists():
        return False

    try:
        if sys.platform == "win32":
            win_path = os.path.normpath(str(p))
            if p.is_file():
                # On Windows, /select, must NOT be inside quotes.
                # Pass command string directly so CreateProcess receives explorer.exe /select,"<path>"
                subprocess.Popen(f'explorer.exe /select,"{win_path}"')
            else:
                if hasattr(os, "startfile"):
                    os.startfile(win_path)
                else:
                    subprocess.Popen(f'explorer.exe "{win_path}"')
            return True
        elif sys.platform == "darwin":
            if p.is_file():
                subprocess.Popen(["open", "-R", str(p)])
            else:
                subprocess.Popen(["open", str(p)])
            return True
        else:
            subprocess.Popen(["xdg-open", str(p.parent if p.is_file() else p)])
            return True
    except Exception:
        try:
            if sys.platform == "win32" and hasattr(os, "startfile"):
                os.startfile(os.path.normpath(str(p.parent if p.is_file() else p)))
                return True
        except Exception:
            pass
        return False


def get_dir_size_bytes(directory: Path) -> int:
    """Calculates recursive directory size in bytes."""
    if not directory.is_dir():
        return 0
    total = 0
    for root, _, files in os.walk(directory):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except Exception:
                pass
    return total


def get_storage_diagnostics() -> Dict[str, Any]:
    """Generates detailed storage metrics and paths for UI status displays."""
    audio_bytes = get_dir_size_bytes(AUDIO_DIR)
    projects_bytes = get_dir_size_bytes(PROJECTS_DIR)
    cache_bytes = get_dir_size_bytes(CACHE_DIR)
    exports_bytes = get_dir_size_bytes(EXPORTS_DIR)
    total_user_bytes = audio_bytes + projects_bytes + cache_bytes + exports_bytes

    return {
        "status": "online",
        "engine_version": "2.0.0",
        "python_executable": sys.executable,
        "engine_script": str(RUN_PY),
        "engine_exists": RUN_PY.is_file(),
        "project_root": str(PROJECT_ROOT),
        "user_data_dir": str(USER_DATA_DIR),
        "paths": {
            "projects": str(PROJECTS_DIR),
            "audio": str(AUDIO_DIR),
            "exports": str(EXPORTS_DIR),
            "cache": str(CACHE_DIR),
            "peaks": str(PEAKS_DIR),
        },
        "disk_usage": {
            "audio_bytes": audio_bytes,
            "audio_mb": round(audio_bytes / (1024 * 1024), 2),
            "projects_bytes": projects_bytes,
            "projects_mb": round(projects_bytes / (1024 * 1024), 2),
            "cache_bytes": cache_bytes,
            "cache_mb": round(cache_bytes / (1024 * 1024), 2),
            "exports_bytes": exports_bytes,
            "exports_mb": round(exports_bytes / (1024 * 1024), 2),
            "total_mb": round(total_user_bytes / (1024 * 1024), 2),
        },
    }
