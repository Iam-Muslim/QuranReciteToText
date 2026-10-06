"""1-Click Native Desktop Runner for Quran Recite Studio.

Launches the local FastAPI engine server and opens an ultra-fast, native
desktop window (powered by Windows WebView2) with zero browser chrome or tabs.
"""

from __future__ import annotations

import os
import sys
import time
import socket
import urllib.request
import threading
from pathlib import Path

APP_DIR = Path(__file__).parent.resolve()
PROJECT_ROOT = APP_DIR.parent.resolve()
for p in (str(PROJECT_ROOT), str(APP_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

try:
    from app.engine.server import find_available_port, run_server
except ImportError:
    from engine.server import find_available_port, run_server


def get_active_port_from_file() -> int | None:
    port_file = APP_DIR / ".engine_port"
    if port_file.exists():
        try:
            return int(port_file.read_text(encoding="utf-8").strip())
        except Exception:
            pass
    return None


def is_engine_healthy(port: int) -> bool:
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{port}/api/status", headers={"User-Agent": "StudioRunner"})
        with urllib.request.urlopen(req, timeout=0.8) as resp:
            return resp.status == 200
    except Exception:
        return False


def main():
    # 1. Check if an engine is already running and healthy
    active_port = get_active_port_from_file()
    if active_port and is_engine_healthy(active_port):
        print(f"[*] Connected to existing active Engine on http://127.0.0.1:{active_port}")
    elif is_engine_healthy(8000):
        active_port = 8000
        print(f"[*] Connected to existing active Engine on http://127.0.0.1:8000")
    else:
        # 2. Find an unoccupied port and launch engine
        active_port = find_available_port(8000)
        print(f"[*] Starting local Engine Server on free port {active_port}...")
        
        t = threading.Thread(target=run_server, args=(active_port,), daemon=True)
        t.start()
        
        # Wait up to 5 seconds for server startup
        for _ in range(50):
            time.sleep(0.1)
            if is_engine_healthy(active_port):
                break

    # 3. Launch Native Desktop Window via pywebview
    import webview

    url = f"http://127.0.0.1:{active_port}"
    print(f"[*] Launching Quran Recite Studio Desktop Workstation at {url}...")

    window = webview.create_window(
        title="Quran Recite2Text - Interactive Alignment Workstation",
        url=url,
        width=1380,
        height=860,
        min_size=(1024, 700),
        background_color="#090d16",
        text_select=True,
    )

    webview.start(debug=False)


if __name__ == "__main__":
    main()
