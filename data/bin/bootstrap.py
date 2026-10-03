"""Runtime bootstrap and dependency coordinator for QuranReciteToText.

Handles Windows console streams, auto-loads bundled MSVC runtime DLLs (vcruntime140_1.dll),
and automatically installs missing pip packages on first run.
"""

from __future__ import annotations

import os
import sys
import shutil
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
    if sys.platform != "win32" or not _BIN_DIR.is_dir():
        return

    # 1. Add data/bin to Windows DLL search path (Python 3.8+)
    if hasattr(os, "add_dll_directory"):
        try:
            os.add_dll_directory(str(_BIN_DIR))
        except Exception:
            pass

    # 2. Preload essential MSVC runtime DLLs into process memory
    all_dlls = (
        "vcruntime140.dll",
        "vcruntime140_1.dll",
        "msvcp140.dll",
        "msvcp140_1.dll",
        "msvcp140_2.dll",
        "msvcp140_codecvt_ids.dll",
        "vcomp140.dll",
    )
    for dll in all_dlls:
        dll_path = _BIN_DIR / dll
        if dll_path.is_file():
            try:
                ctypes.CDLL(str(dll_path))
            except Exception:
                pass

    # 3. Direct app-local fix: Copy DLLs right next to onnxruntime.dll in site-packages
    try:
        ort_spec = importlib.util.find_spec("onnxruntime")
        if ort_spec and ort_spec.submodule_search_locations:
            capi_dir = Path(list(ort_spec.submodule_search_locations)[0]) / "capi"
            if capi_dir.is_dir():
                for dll in all_dlls:
                    src = _BIN_DIR / dll
                    dst = capi_dir / dll
                    if src.is_file() and not dst.is_file():
                        try:
                            shutil.copy2(str(src), str(dst))
                        except Exception:
                            pass
    except Exception:
        pass


def bootstrap() -> None:
    """Executes full environment bootstrap."""
    fix_windows_console()
    ensure_pip_dependencies()
    load_msvc_runtime()


# Execute automatically on import
bootstrap()
