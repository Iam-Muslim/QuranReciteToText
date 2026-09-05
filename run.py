"""Command Line Offline Runner for QuranReciteToText.

Orchestrates Phase 1 (Zipformer), Phase 1.1 (Recovery), Phase 2 (CTC Aligner),
Phase 3 (Quran Matcher), and Phase 4 (JSON Exporter).
"""

import os
import sys
import time
import argparse
import json
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
    script_start = time.time()

    parser = argparse.ArgumentParser(
        description="Quran Recitation Transcription & Forced-Alignment Pipeline"
    )
    parser.add_argument(
        "--audio", type=str, required=True, help="Path to input audio file"
    )
    parser.add_argument(
        "--out-dir",
        type=str,
        default=".",
        help="Directory to save exported JSON artifacts (default: .)",
    )
    parser.add_argument(
        "--out",
        type=str,
        default="output.json",
        help="Specific path for the main output JSON (default: output.json)",
    )
    parser.add_argument(
        "--export-all",
        action="store_true",
        default=True,
        help="Export all 4 standard JSON artifacts (default: True)",
    )
    parser.add_argument(
        "--no-export-all",
        action="store_false",
        dest="export_all",
        help="Only export the main output.json file",
    )
    parser.add_argument(
        "--threads",
        type=int,
        default=2,
        help="Number of ONNX CPU execution threads (default: 2)",
    )
    parser.add_argument(
        "--recovery",
        action="store_true",
        default=False,
        help="Enable Phase 1.1 Speech & Repetition Recovery",
    )

    args = parser.parse_args()

    os.environ["OMP_NUM_THREADS"] = str(args.threads)
    os.environ["MKL_NUM_THREADS"] = str(args.threads)
    os.environ["OPENBLAS_NUM_THREADS"] = str(args.threads)
    os.environ["ONNX_NUM_THREADS"] = str(args.threads)

    if not os.path.exists(args.audio):
        print(f"[!] Error: Input audio file not found at: {args.audio}", file=sys.stderr)
        sys.exit(1)

    import config
    if args.recovery:
        config.ENABLE_SPEECH_RECOVERY = True

    from src.core.main_flow import AudioPipeline

    pipeline = AudioPipeline()
    pipeline.initialize(num_threads=args.threads)

    os.makedirs(args.out_dir, exist_ok=True)

    print(f"[*] Processing audio: {args.audio}")
    try:
        result = pipeline.process_audio_file(
            audio_file_path=args.audio,
            output_dir=args.out_dir,
            export_json_files=args.export_all,
            on_progress=lambda stage, pct, elp, **kwargs: None,
        )
    except Exception as e:
        import traceback
        traceback.print_exc()
        sys.exit(1)

    # If --out points somewhere other than output_dir/output.json, copy/save there
    out_target = args.out
    if not os.path.isabs(out_target):
        out_target = os.path.join(args.out_dir, out_target) if args.out_dir != "." else out_target

    default_output_path = os.path.join(args.out_dir, "output.json")
    if os.path.abspath(out_target) != os.path.abspath(default_output_path):
        from src.phase4_export.quran_json_exporter import QuranJsonExporter
        with open(out_target, "w", encoding="utf-8") as f:
            by_surah = {}
            for s in result.segments:
                by_surah.setdefault(s.surah_number, []).append(s)
            surahs_json = [
                {
                    "surah_number": k,
                    "total_segments": len(v),
                    "segments": [seg.to_dict() for seg in v],
                }
                for k, v in by_surah.items()
            ]
            json.dump(
                {
                    "total_surahs": len(surahs_json),
                    "total_segments": len(result.segments),
                    "surahs": surahs_json,
                },
                f,
                ensure_ascii=False,
                indent=2,
            )

    total_time = time.time() - script_start
    prof = result.profiling

    print("\n" + "=" * 60)
    print("           QURANRECITE-TO-TEXT PROCESSING COMPLETE")
    print("=" * 60)
    print(f"Audio Duration      : {prof.audio_duration:.2f}s")
    print(f"Decoding / Loading  : {prof.load_time:.2f}s")
    print(f"Phase 1 Transcribe  : {prof.asr_time:.2f}s ({(prof.audio_duration / prof.asr_time if prof.asr_time > 0 else 0):.1f}x)")
    if prof.recovery_time > 0:
        print(f"Phase 1.1 Recovery  : {prof.recovery_time:.2f}s")
    print(f"Phase 2 CTC Align   : {prof.alignment_time:.2f}s")
    print(f"Phase 3 Text Match  : {prof.match_time:.2f}s")
    print(f"Phase 4 JSON Export : {prof.export_time:.2f}s")
    print(f"Total Pipeline Time : {total_time:.2f}s ({prof.real_time_factor:.1f}x Real-Time)")
    print(f"Segments Matched    : {len(result.segments)} Ayah segments")
    print(f"Main Output JSON    : {out_target}")
    if args.export_all:
        print(f"Export Directory    : {os.path.abspath(args.out_dir)}")
        print("Exported Files      :")
        print(f"  - {os.path.join(args.out_dir, 'raw_transcription.json')}")
        print(f"  - {os.path.join(args.out_dir, 'recovered_speech.json')}")
        print(f"  - {os.path.join(args.out_dir, 'ctc_aligned_phonemes.json')}")
        print(f"  - {os.path.join(args.out_dir, 'output.json')}")
    print("=" * 60)


if __name__ == "__main__":
    main()
