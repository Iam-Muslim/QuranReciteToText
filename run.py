"""Command Line Offline Runner for QuranReciteToText."""

from __future__ import annotations

import os
import sys

os.environ["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
os.environ["PYLAUNCH_NO_UPDATE_CHECK"] = "1"
os.environ["OMP_WAIT_POLICY"] = "PASSIVE"
os.environ["KMP_BLOCKTIME"] = "0"

import time
import json
import argparse
from pathlib import Path

_app_path = Path(__file__).parent.resolve()
if str(_app_path) not in sys.path:
    sys.path.insert(0, str(_app_path))

# Bootstrap Windows MSVC runtime, pip dependencies, and console streams
import data.bin.bootstrap


def get_hardware_topology() -> tuple[int, int]:
    """Detects physical and logical CPU cores using standard library."""
    log = os.cpu_count() or 4
    phys = max(1, log // 2)
    return phys, log


def resolve_concurrency(fast: bool, user_workers: int | None, user_threads: int | None) -> tuple[int, int]:
    """Resolves optimal (workers, threads) based on hardware topology and CLI flags."""
    phys, log = get_hardware_topology()
    if fast:
        # Fast mode: scale workers to dedicated physical cores (leave 1 core on multicore systems for OS/I/O)
        opt_workers = max(1, min(phys - 1 if phys > 2 else phys, 7))
        # When running parallel segment workers, each worker uses 1 intra-op thread for zero-barrier locality.
        # This eliminates AVX2 hyperthread contention and mutex stalls, cutting CPU load by >40% with zero speed loss.
        opt_threads = 1 if opt_workers > 1 else (2 if phys >= 2 else 1)
        workers = user_workers if user_workers is not None else opt_workers
        threads = user_threads if user_threads is not None else (1 if workers > 1 else 2)
    else:
        workers = user_workers if user_workers is not None else 1
        threads = user_threads if user_threads is not None else (2 if phys >= 2 else 1)
    return workers, threads


def main():
    start_time = time.time()

    parser = argparse.ArgumentParser(description="Quran Recitation Transcription & Forced Alignment Pipeline")
    parser.add_argument("--audio", type=str, default=None, help="Path to input audio file")
    parser.add_argument("--fast", action="store_true", default=False, help="Auto-configure top-speed parallel workers and threads for this CPU")
    parser.add_argument("--threads", type=int, default=None, help="ONNX execution threads (default: auto/2)")
    parser.add_argument("--workers", type=int, default=None, help="Parallel segment workers (default: 1, or auto in --fast mode)")
    parser.add_argument("--progress", action="store_true", default=False, help="Emit JSON progress lines for frontend apps")
    args = parser.parse_args()

    audio_path = args.audio
    if not audio_path:
        print("=" * 60)
        print("  Quran Recitation Transcription & Forced Alignment Pipeline")
        print("=" * 60)
        print("Usage: python run.py --audio <path_to_audio_file> [--fast]")
        print("-" * 60)
        try:
            prompt_input = input("Enter path to audio file (or press Enter to exit): ").strip().strip('"').strip("'")
            if prompt_input:
                audio_path = prompt_input
            else:
                sys.exit(0)
        except (EOFError, KeyboardInterrupt):
            sys.exit(0)

    if not os.path.exists(audio_path):
        print(f"[!] Error: Audio file not found at: {audio_path}", file=sys.stderr)
        if sys.stdin and sys.stdin.isatty():
            try:
                input("\nPress Enter to exit...")
            except Exception:
                pass
        sys.exit(1)

    workers, threads = resolve_concurrency(fast=args.fast, user_workers=args.workers, user_threads=args.threads)

    os.environ["ONNX_SEGMENT_WORKERS"] = str(workers)
    os.environ["OMP_NUM_THREADS"] = str(threads)
    os.environ["ONNX_NUM_THREADS"] = str(threads)
    os.environ["OMP_WAIT_POLICY"] = "PASSIVE"
    os.environ["KMP_BLOCKTIME"] = "0"

    import config

    from src import AudioPipeline
    from src.audio import AudioDecoder

    if not args.progress:
        print("Initializing pipeline and decoding audio...", flush=True)

    pipeline = AudioPipeline()
    pipeline.initialize(num_threads=threads)
    audio_pcm = AudioDecoder.load_audio_file(audio_path)

    output_dir = config.DEFAULT_OUTPUT_DIR
    os.makedirs(output_dir, exist_ok=True)

    startup_time = max(0.0, time.time() - start_time)
    audio_duration = len(audio_pcm) / config.SAMPLE_RATE

    if not args.progress:
        print("=" * 55)
        print(f"Audio Duration      : {audio_duration:.2f}s", flush=True)
        print(f"Startup & Preload   : {startup_time:.2f}s", flush=True)

    result = pipeline.process_pcm(
        audio_pcm=audio_pcm,
        output_dir=output_dir,
        export_json_files=config.EXPORT_ALL_ARTIFACTS,
        live_profile=not args.progress,
        json_progress=args.progress,
    )

    total_time = time.time() - start_time
    prof = result.profiling

    if not args.progress:
        print(f"Processing Time     : {prof.total_time:.2f}s ({prof.real_time_factor:.1f}x Real-Time)", flush=True)
        print(f"Total Time          : {total_time:.2f}s", flush=True)
        print("=" * 55)
    else:
        print(json.dumps({
            "stage": "completed",
            "audio_duration": round(prof.audio_duration, 2),
            "processing_time": round(prof.total_time, 2),
            "total_time": round(total_time, 2),
            "real_time_factor": round(prof.real_time_factor, 1),
        }), flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"\n[!] Pipeline error: {exc}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        if sys.stdin and sys.stdin.isatty():
            try:
                input("\nPress Enter to exit...")
            except Exception:
                pass
        sys.exit(1)
