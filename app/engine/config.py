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

def normalize_cli_path(p: Path | str) -> str:
    """Strips Windows extended prefix \\\\?\\ which causes Python CLI/argparse open errors."""
    s = str(p)
    if s.startswith("\\\\?\\"):
        s = s[4:]
    return s


def resolve_project_root() -> Path:
    """
    Finds the root directory containing run.py, data/, and src/.
    Works seamlessly in both local development and production bundled desktop app.
    """
    # 1. Explicit environment variable passed by Rust engine manager
    env_root = os.environ.get("QURAN_PROJECT_ROOT") or os.environ.get("PROJECT_ROOT")
    if env_root:
        p = Path(normalize_cli_path(env_root)).resolve()
        if (p / "run.py").is_file() or (p / "src").is_dir():
            return p

    engine_dir = Path(__file__).parent.resolve()

    # 2. Production bundled Tauri mode: <resource_dir>/engine -> <resource_dir>
    # In bundled mode, run.py and src/ are placed directly in the resource root (engine_dir.parent)
    cand_prod = engine_dir.parent.resolve()
    if (cand_prod / "run.py").is_file():
        return cand_prod

    # 3. Development workspace mode: <repo_root>/app/engine -> <repo_root>
    cand_dev = engine_dir.parent.parent.resolve()
    if (cand_dev / "run.py").is_file():
        return cand_dev

    # 4. Check CWD (process working directory, which Rust sets to project_root)
    cwd = Path.cwd().resolve()
    if (cwd / "run.py").is_file():
        return cwd

    # 5. Check upwards from engine_dir
    curr = engine_dir
    for _ in range(5):
        if (curr / "run.py").is_file():
            return curr
        curr = curr.parent

    return cand_prod if (cand_prod / "src").is_dir() else cand_dev


# Base Engine Paths
PROJECT_ROOT = resolve_project_root()
APP_DIR = (PROJECT_ROOT / "app") if (PROJECT_ROOT / "app").is_dir() else PROJECT_ROOT
RUN_PY = PROJECT_ROOT / "run.py"
DATA_DIR = PROJECT_ROOT / "data"

# Ensure PROJECT_ROOT and its src folder are on sys.path for direct module imports
for extra_p in (str(PROJECT_ROOT), str(PROJECT_ROOT / "src")):
    if extra_p not in sys.path:
        sys.path.insert(0, extra_p)

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
