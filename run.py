"""Command Line Offline Runner for QuranReciteToText."""

from __future__ import annotations

import os
import sys
import time
import argparse
from pathlib import Path

if sys.stdout is not None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

_app_path = Path(__file__).parent.resolve()
if str(_app_path) not in sys.path:
    sys.path.insert(0, str(_app_path))


def main():
    start_time = time.time()

    parser = argparse.ArgumentParser(description="Quran Recitation Transcription & Forced Alignment Pipeline")
    parser.add_argument("--audio", type=str, required=True, help="Path to input audio file")
    parser.add_argument("--threads", type=int, default=2, help="ONNX execution threads (default: 2)")
    parser.add_argument("--progress", action="store_true", default=False, help="Emit JSON progress lines for frontend apps")
    args = parser.parse_args()

    if not os.path.exists(args.audio):
        print(f"[!] Error: Audio file not found at: {args.audio}", file=sys.stderr)
        sys.exit(1)

    os.environ["OMP_NUM_THREADS"] = str(args.threads)
    os.environ["ONNX_NUM_THREADS"] = str(args.threads)

    import config

    from src import AudioPipeline
    from src.audio import AudioDecoder

    if not args.progress:
        print("[*] Initializing pipeline and decoding audio...", flush=True)

    pipeline = AudioPipeline()
    pipeline.initialize(num_threads=args.threads)
    audio_pcm = AudioDecoder.load_audio_file(args.audio)

    output_dir = getattr(config, "DEFAULT_OUTPUT_DIR", "output")
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
        export_json_files=getattr(config, "EXPORT_ALL_ARTIFACTS", True),
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
        import json
        print(json.dumps({
            "stage": "completed",
            "audio_duration": round(prof.audio_duration, 2),
            "processing_time": round(prof.total_time, 2),
            "total_time": round(total_time, 2),
            "real_time_factor": round(prof.real_time_factor, 1),
        }), flush=True)


if __name__ == "__main__":
    main()
