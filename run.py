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
    parser.add_argument("--out-dir", type=str, default=".", help="Output directory for JSON files (default: .)")
    parser.add_argument("--out", type=str, default="output.json", help="Path for main output JSON (default: output.json)")
    parser.add_argument("--threads", type=int, default=2, help="ONNX execution threads (default: 2)")
    parser.add_argument("--recovery", action="store_true", default=False, help="Enable Phase 1.1 Speech Recovery")
    parser.add_argument("--export-all", action="store_true", default=True, help="Export all 4 JSON artifacts")
    args = parser.parse_args()

    if not os.path.exists(args.audio):
        print(f"[!] Error: Audio file not found at: {args.audio}", file=sys.stderr)
        sys.exit(1)

    os.environ["OMP_NUM_THREADS"] = str(args.threads)
    os.environ["ONNX_NUM_THREADS"] = str(args.threads)

    import config
    if args.recovery:
        config.ENABLE_SPEECH_RECOVERY = True

    from src import AudioPipeline

    pipeline = AudioPipeline()
    pipeline.initialize(num_threads=args.threads)

    os.makedirs(args.out_dir, exist_ok=True)
    print(f"[*] Processing audio: {args.audio}")

    result = pipeline.process_audio_file(
        audio_file_path=args.audio,
        output_dir=args.out_dir,
        export_json_files=args.export_all,
    )

    total_time = time.time() - start_time
    prof = result.profiling

    print("\n" + "=" * 55)
    print(f"Audio Duration      : {prof.audio_duration:.2f}s")
    print(f"Phase 1 Transcribe  : {prof.asr_time:.2f}s")
    if prof.recovery_time > 0:
        print(f"Phase 1.1 Recovery  : {prof.recovery_time:.2f}s")
    print(f"Phase 2 CTC Align   : {prof.alignment_time:.2f}s")
    print(f"Phase 3 Text Match  : {prof.match_time:.2f}s")
    print(f"Phase 4 JSON Export : {prof.export_time:.2f}s")
    print(f"Total Time          : {total_time:.2f}s ({prof.real_time_factor:.1f}x Real-Time)")
    print(f"Segments Matched    : {len(result.segments)} Ayah segments")
    print(f"Output Directory    : {os.path.abspath(args.out_dir)}")
    print("=" * 55)


if __name__ == "__main__":
    main()
