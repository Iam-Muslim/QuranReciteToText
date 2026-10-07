"""FastAPI Application Server Factory for Quran Recite Studio.

Mirrors QuranCaption's clean architectural lifecycle:
1. Application initialization with CORS
2. Dual-prefix route mounting (/api and /api/engine)
3. Production static asset serving from dist/
4. Native uvicorn runner
"""

from __future__ import annotations

import atexit
import json
import os
import socket
import sys
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

_CURRENT_DIR = Path(__file__).parent.resolve()
_APP_DIR = _CURRENT_DIR.parent.resolve()
for p in (str(_CURRENT_DIR), str(_APP_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

try:
    from engine.config import APP_DIR, USER_DATA_DIR, PROJECT_ROOT
    from engine.routes import router
except (ImportError, ValueError):
    try:
        from config import APP_DIR, USER_DATA_DIR, PROJECT_ROOT
        from routes import router
    except (ImportError, ValueError):
        try:
            from app.engine.config import APP_DIR, USER_DATA_DIR, PROJECT_ROOT
            from app.engine.routes import router
        except (ImportError, ValueError):
            from .config import APP_DIR, USER_DATA_DIR, PROJECT_ROOT
            from .routes import router

for p in (str(PROJECT_ROOT), str(PROJECT_ROOT / "src")):
    if p not in sys.path:
        sys.path.insert(0, p)


def is_port_in_use(port: int, host: str = "127.0.0.1") -> bool:
    """Checks whether a TCP port is currently occupied."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.3)
        return s.connect_ex((host, port)) == 0


def find_available_port(preferred_port: int = 8000, max_attempts: int = 100) -> int:
    """Finds an available TCP port starting from preferred_port.
    
    Prevents crash if another application or zombie process is already using port 8000.
    """
    for port in range(preferred_port, preferred_port + max_attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    # Fallback to ephemeral port assigned by OS
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def write_port_manifest(port: int) -> None:
    """Writes the active engine port to discovery files for Vite & native runners."""
    port_file = APP_DIR / ".engine_port"
    meta_file = USER_DATA_DIR / "engine_port.json"
    
    try:
        USER_DATA_DIR.mkdir(parents=True, exist_ok=True)
        port_file.write_text(str(port), encoding="utf-8")
        meta = {
            "port": port,
            "pid": os.getpid(),
            "url": f"http://127.0.0.1:{port}",
            "host": "127.0.0.1"
        }
        meta_file.write_text(json.dumps(meta, indent=2), encoding="utf-8")
        
        def _cleanup():
            try:
                if port_file.exists():
                    port_file.unlink()
            except Exception:
                pass
        atexit.register(_cleanup)
    except Exception as e:
        print(f"[!] Warning: Could not write port manifest: {e}")


def create_app() -> FastAPI:
    """Creates and configures the production FastAPI instance."""
    app = FastAPI(title="Quran Recite Studio Engine", version="2.0.0")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["Content-Range", "Accept-Ranges", "Content-Length"],
    )

    # Mount routes under both /api and /api/engine for 100% frontend compatibility
    app.include_router(router, prefix="/api")
    app.include_router(router, prefix="/api/engine")

    # Serve production built frontend if available
    dist_dir = APP_DIR / "dist"
    if dist_dir.is_dir():
        app.mount("/", StaticFiles(directory=str(dist_dir), html=True), name="static")

    return app


def run_server(port: int | None = None):
    """Starts the local daemon server via uvicorn with port collision resilience."""
    import uvicorn
    
    if port is None:
        env_port = os.environ.get("PORT")
        if env_port:
            port = int(env_port)
        else:
            port = find_available_port(8000)

    write_port_manifest(port)
    print(f"[*] Starting Quran Recite Studio Engine on http://127.0.0.1:{port} (PID: {os.getpid()})")
    
    app = create_app()
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="info")


if __name__ == "__main__":
    run_server()
