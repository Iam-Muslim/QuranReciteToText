"""Quran Recite Studio - High-Performance Engine Server.

Production daemon powered by the modular `engine` package, mirroring QuranCaption:
1. Direct OS Audio Streaming with HTTP 206 Partial Content (Range Support)
2. Sub-second Audio Waveform Peak Extraction (QuranCaption FFmpeg pipeline)
3. Real-Time Alignment Pipeline Runner with Server-Sent Events (SSE)
4. Atomic Project State Management (.qproj with .part corruption guard)
5. Native OS UserData Partitioning (Isolated from Program Files & git repo)
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure app directory is in sys.path
APP_DIR = Path(__file__).parent.resolve()
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from engine.server import create_app, run_server
from engine.config import (
    USER_DATA_DIR,
    PROJECTS_DIR,
    AUDIO_DIR,
    EXPORTS_DIR,
    CACHE_DIR,
    PEAKS_DIR,
    OUTPUT_DIR,
    PROJECT_ROOT,
)

# Canonical FastAPI application instance
app = create_app()

if __name__ == "__main__":
    run_server()
