"""Runtime bootstrap and dependency coordinator for QuranReciteToText.

Handles Windows console streams, auto-loads bundled MSVC runtime DLLs (vcruntime140_1.dll),
and automatically installs missing pip packages on first run.
"""

from __future__ import annotations

import os
import sys
import ctypes
import subprocess
import importlib.util
from pathlib import Path

_BIN_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _BIN_DIR.parent.parent


def fix_windows_console() -> None:
    """Ensures console output is visible and UTF-8 encoded on Windows."""
    if sys.platform != "win32":
        return

    # Reattach to parent console if invoked detached or via pythonw
    if sys.stdout is None or sys.stderr is None or "pythonw" in sys.executable.lower():
        try:
            if ctypes.windll.kernel32.AttachConsole(-1) != 0:
                if sys.stdout is None:
                    sys.stdout = open("CONOUT$", "w", encoding="utf-8")
                if sys.stderr is None:
                    sys.stderr = open("CONOUT$", "w", encoding="utf-8")
        except Exception:
            pass

    # Ensure UTF-8 output encoding for Quranic text
    for stream in (sys.stdout, sys.stderr):
        if stream is not None:
            try:
                stream.reconfigure(encoding="utf-8")
            except Exception:
                pass


def ensure_pip_dependencies() -> None:
    """Detects missing dependencies and automatically installs them via pip."""
    required = ("numpy", "onnxruntime", "numba", "miniaudio", "scipy")
    missing = [pkg for pkg in required if importlib.util.find_spec(pkg) is None]

    if not missing:
        return

    print("=" * 60)
    print(f"[*] Missing dependencies detected: {', '.join(missing)}")
    print("[*] Installing requirements via pip. Please wait...")
    print("=" * 60, flush=True)

    req_file = _PROJECT_ROOT / "requirements.txt"
    cmd = [sys.executable, "-m", "pip", "install", "-r", str(req_file)] if req_file.is_file() else [sys.executable, "-m", "pip", "install", *missing]

    try:
        subprocess.check_call(cmd)
        print("[*] All dependencies installed successfully!\n", flush=True)
    except Exception as exc:
        print(f"\n[!] Failed to install dependencies: {exc}", file=sys.stderr)
        print("[!] Please run manually: pip install -r requirements.txt", file=sys.stderr)
        sys.exit(1)


def load_msvc_runtime() -> None:
    """Preloads bundled Visual C++ runtime DLLs so onnxruntime runs without vc_redist."""
    if sys.platform != "win32":
        return

    # Check if system already has vcruntime140_1.dll
    try:
        ctypes.CDLL("vcruntime140_1.dll")
        return
    except OSError:
        pass

    if not _BIN_DIR.is_dir():
        return

    # Add data/bin to Python 3.8+ Windows DLL search path
    if hasattr(os, "add_dll_directory"):
        try:
            os.add_dll_directory(str(_BIN_DIR))
        except Exception:
            pass

    # Preload essential DLLs into process memory
    for dll in ("vcruntime140.dll", "vcruntime140_1.dll", "msvcp140.dll", "vcomp140.dll"):
        dll_path = _BIN_DIR / dll
        if dll_path.is_file():
            try:
                ctypes.CDLL(str(dll_path))
            except Exception:
                pass


def bootstrap() -> None:
    """Executes full environment bootstrap."""
    fix_windows_console()
    ensure_pip_dependencies()
    load_msvc_runtime()


# Execute automatically on import
bootstrap()
