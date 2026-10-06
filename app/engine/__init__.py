"""Quran Recite Studio Engine Package.

Modular, high-performance backend architecture mirroring QuranCaption:
- config: OS UserData resolution, paths, MAX_PATH & sanitization
- media: Audio streaming (HTTP 206), FFmpeg peaks, PTS stretch detection
- projects: Atomic (.part) project state management, orphan audio pruning
- pipeline: Subprocess alignment runner with SSE streaming
- quran: Static linguistic data & verse/word lookups
- system: Explorer file revelation & storage diagnostics
- server: FastAPI app factory & static mounts
"""

from __future__ import annotations
import sys
from pathlib import Path

# Ensure app directory is always in sys.path
_CURRENT_DIR = Path(__file__).parent.resolve()
_APP_DIR = _CURRENT_DIR.parent.resolve()
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))
