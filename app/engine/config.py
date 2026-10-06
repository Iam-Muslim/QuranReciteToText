"""Storage and Path Configuration for Quran Recite Studio.

Implements QuranCaption's exact storage architecture:
1. OS Standard UserData Directory (%APPDATA%/QuranReciteStudio on Windows)
2. Safe Filename Sanitization & Windows MAX_PATH length constraints
3. Non-colliding safe destination resolution
4. Atomic file persistence using .part guards to prevent data corruption
"""

from __future__ import annotations

import os
import sys
import re
import json
from pathlib import Path
from typing import Any

# Base Engine Paths
APP_DIR = Path(__file__).parent.parent.resolve()
PROJECT_ROOT = APP_DIR.parent.resolve()
RUN_PY = PROJECT_ROOT / "run.py"
DATA_DIR = PROJECT_ROOT / "data"

CREATE_NO_WINDOW: int = 0x08000000 if sys.platform == "win32" else 0


def get_app_user_data_dir() -> Path:
    """
    Resolves the canonical User Data Directory following OS standards & QuranCaption design.
    - Environment override: QURAN_STUDIO_USER_DATA or PORTABLE_DATA
    - Local development: if app/userData exists, use it so dev remains self-contained.
    - Production installer mode (.exe / Inno / NSIS / PyInstaller):
      Windows: %APPDATA%/QuranReciteStudio (e.g. C:/Users/<User>/AppData/Roaming/QuranReciteStudio)
      macOS: ~/Library/Application Support/QuranReciteStudio
      Linux: ~/.local/share/QuranReciteStudio
    """
    env_override = os.environ.get("QURAN_STUDIO_USER_DATA") or os.environ.get("PORTABLE_DATA")
    if env_override:
        p = Path(env_override).resolve()
        p.mkdir(parents=True, exist_ok=True)
        return p

    dev_user_data = APP_DIR / "userData"
    if dev_user_data.is_dir():
        return dev_user_data

    if sys.platform == "win32":
        app_data = os.environ.get("APPDATA") or os.environ.get("LOCALAPPDATA")
        if app_data:
            target = Path(app_data) / "QuranReciteStudio"
            target.mkdir(parents=True, exist_ok=True)
            return target
    elif sys.platform == "darwin":
        target = Path.home() / "Library" / "Application Support" / "QuranReciteStudio"
        target.mkdir(parents=True, exist_ok=True)
        return target
    else:
        xdg = os.environ.get("XDG_DATA_HOME")
        if xdg:
            target = Path(xdg) / "QuranReciteStudio"
        else:
            target = Path.home() / ".local" / "share" / "QuranReciteStudio"
        target.mkdir(parents=True, exist_ok=True)
        return target

    dev_user_data.mkdir(parents=True, exist_ok=True)
    return dev_user_data


# Canonical User Storage Partitioning
USER_DATA_DIR = get_app_user_data_dir()
PROJECTS_DIR = USER_DATA_DIR / "projects"
AUDIO_DIR = USER_DATA_DIR / "audio"
EXPORTS_DIR = USER_DATA_DIR / "exports"
CACHE_DIR = USER_DATA_DIR / "cache"
PEAKS_DIR = CACHE_DIR / "peaks"
OUTPUT_DIR = USER_DATA_DIR / "output"

# Auto-initialize directories
for d in (PROJECTS_DIR, AUDIO_DIR, EXPORTS_DIR, CACHE_DIR, PEAKS_DIR, OUTPUT_DIR):
    d.mkdir(parents=True, exist_ok=True)


def sanitize_filename(name: str) -> str:
    """
    Sanitizes filename for cross-platform OS filesystem compatibility (QuranCaption approach).
    Strips illegal Windows characters [/\\:*?\"<>|] while preserving valid Unicode (Arabic, etc.).
    """
    cleaned = re.sub(r'[/\\:*?"<>|]', '_', name).strip().strip('.')
    return cleaned or "unnamed_media"


def constrain_file_path(file_path: Path, max_length: int = 220) -> Path:
    """
    Prevents Windows MAX_PATH (260 char) buffer overflows (QuranCaption ExportService approach).
    Safely shortens filename stem if directory + filename exceeds max_length.
    """
    path_str = str(file_path.resolve())
    if len(path_str) <= max_length:
        return file_path

    parent = file_path.parent
    ext = file_path.suffix
    stem = file_path.stem

    allowed_stem_len = max(16, max_length - len(str(parent)) - len(ext) - 5)
    shortened_stem = stem[:allowed_stem_len].rstrip('._- ')
    return parent / f"{shortened_stem}{ext}"


def get_unique_destination(directory: Path, filename: str) -> Path:
    """
    Generates a unique, non-colliding destination path (QuranCaption BatchMediaService approach).
    Avoids overwriting existing files or active .part temporary writes.
    """
    safe_name = sanitize_filename(filename)
    dest = directory / safe_name
    if not dest.exists() and not (directory / f"{safe_name}.part").exists():
        return dest

    stem = Path(safe_name).stem
    ext = Path(safe_name).suffix
    suffix = 1
    while True:
        candidate_name = f"{stem}_{suffix}{ext}"
        candidate = directory / candidate_name
        if not candidate.exists() and not (directory / f"{candidate_name}.part").exists():
            return candidate
        suffix += 1


def atomic_write_json(file_path: Path, data: Any, indent: int = 2) -> None:
    """
    Atomically writes a JSON document using a .part temporary file (QuranCaption approach).
    Guarantees that a crash or interrupted write never leaves a corrupt 0-byte file.
    """
    file_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = file_path.with_name(f"{file_path.name}.part")
    try:
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=indent)
            f.flush()
            os.fsync(f.fileno())

        if file_path.exists():
            try:
                file_path.unlink()
            except Exception:
                pass
        temp_path.rename(file_path)
    except Exception:
        if temp_path.exists():
            try:
                temp_path.unlink()
            except Exception:
                pass
        raise


if __name__ == "__main__":
    print(f"[*] Engine config ready. UserData: {get_app_user_data_dir()}")
