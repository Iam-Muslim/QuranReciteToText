#!/usr/bin/env python3
"""
Local WordTiming segmenter wrapper for QuranCaption & Quran Recite Studio.

Runs the offline Zipformer-v3 Quran Recitation alignment engine
and outputs normalized JSON with relative word timings and canonical Surahs to stdout.
Pure in-memory streaming over stdout with zero disk search or temporary file hunting.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

SCRIPT_DIR = Path(__file__).parent.absolute()

# Resolve engine root (contains src/, data/, config.py)
candidates = [
    SCRIPT_DIR / "quran_recite_to_text",
    SCRIPT_DIR.parent.parent.parent,
    SCRIPT_DIR.parent.parent,
    Path(os.environ.get("QURAN_PROJECT_ROOT", "")),
]
ENGINE_DIR = SCRIPT_DIR
for c in candidates:
    if c and (c / "src").is_dir():
        ENGINE_DIR = c.resolve()
        break

for p in [str(ENGINE_DIR), str(ENGINE_DIR / "src")]:
    if p not in sys.path:
        sys.path.insert(0, p)


# Bootstrap environment: Windows console and MSVC runtime DLLs
def _bootstrap_environment() -> None:
    """Configure Windows console streams and preload bundled MSVC runtime DLLs."""
    if sys.platform == "win32":
        for stream in (sys.stdout, sys.stderr):
            if stream is not None:
                reconfig = getattr(stream, "reconfigure", None)
                if callable(reconfig):
                    try:
                        reconfig(encoding="utf-8")
                    except Exception:
                        pass

    bin_dirs = [
        ENGINE_DIR / "data" / "bin",
        SCRIPT_DIR.parent / "binaries",
        ENGINE_DIR / "binaries",
    ]
    for bin_dir in bin_dirs:
        if bin_dir.is_dir():
            if hasattr(os, "add_dll_directory"):
                try:
                    os.add_dll_directory(str(bin_dir))
                except Exception:
                    pass
            try:
                import ctypes

                dll_names = (
                    "vcruntime140.dll",
                    "vcruntime140_1.dll",
                    "msvcp140.dll",
                    "msvcp140_1.dll",
                    "msvcp140_2.dll",
                    "msvcp140_codecvt_ids.dll",
                    "vcomp140.dll",
                )
                for name in dll_names:
                    dll_file = bin_dir / name
                    if dll_file.is_file():
                        ctypes.CDLL(str(dll_file))

                import importlib.util
                import shutil

                ort_spec = importlib.util.find_spec("onnxruntime")
                if ort_spec and ort_spec.submodule_search_locations:
                    capi_dir = Path(list(ort_spec.submodule_search_locations)[0]) / "capi"
                    if capi_dir.is_dir():
                        for name in dll_names:
                            src = bin_dir / name
                            dst = capi_dir / name
                            if src.is_file() and not dst.is_file():
                                try:
                                    shutil.copy2(str(src), str(dst))
                                except Exception:
                                    pass
            except Exception:
                pass


_bootstrap_environment()

import numpy as np


def get_hardware_topology() -> Tuple[int, int]:
    """Detects physical and logical CPU cores for optimal parallel execution."""
    try:
        import psutil

        phys = psutil.cpu_count(logical=False) or 4
        log = psutil.cpu_count(logical=True) or 8
    except Exception:
        log = os.cpu_count() or 4
        phys = max(1, log // 2)
    return phys, log


def resolve_concurrency(
    fast: bool,
    user_workers: Optional[int],
    user_threads: Optional[int],
) -> Tuple[int, int]:
    """Resolves optimal (workers, threads) based on hardware topology and CLI flags."""
    phys, log = get_hardware_topology()
    if fast:
        opt_workers = min(max(1, phys), 8)
        opt_threads = 2 if log >= (opt_workers * 2) else (2 if phys <= 4 else 1)
        workers = user_workers if user_workers is not None else opt_workers
        threads = user_threads if user_threads is not None else opt_threads
    else:
        workers = user_workers if user_workers is not None else 1
        threads = user_threads if user_threads is not None else (2 if workers <= 4 else 1)
    return workers, threads


def load_audio_slice(
    file_path: str,
    start_s: float = 0.0,
    duration_s: Optional[float] = None,
    sample_rate: int = 16000,
) -> np.ndarray:
    """Fast-seek audio decoding for timeline slices without decoding entire file."""
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Audio file not found: {file_path}")

    # 1. Primary: Streaming FFmpeg sub-range decode (~0.05s)
    try:
        import subprocess
        from src.audio import _resolve_ffmpeg_bin

        cmd = [_resolve_ffmpeg_bin(), "-hide_banner", "-loglevel", "error"]
        if start_s > 0:
            cmd.extend(["-ss", f"{start_s:.3f}"])
        if duration_s is not None and duration_s > 0:
            cmd.extend(["-t", f"{duration_s:.3f}"])
        cmd.extend([
            "-i", file_path,
            "-vn", "-sn", "-dn",
            "-f", "f32le", "-ac", "1", "-ar", str(sample_rate), "-",
        ])
        popen_kwargs = {}
        if sys.platform == "win32":
            popen_kwargs["creationflags"] = 0x08000000
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, **popen_kwargs)
        out, _ = proc.communicate()
        if proc.returncode == 0 and len(out) > 0:
            return np.frombuffer(out, dtype=np.float32)
    except Exception:
        pass

    # 2. Fallback: In-process full decode with numpy slice
    from src.audio import AudioDecoder

    full_audio = AudioDecoder.load_audio_file(file_path, sample_rate=sample_rate)
    start_sample = max(0, int(round(start_s * sample_rate)))
    if duration_s is not None and duration_s > 0:
        end_sample = min(len(full_audio), start_sample + int(round(duration_s * sample_rate)))
    else:
        end_sample = len(full_audio)
    return full_audio[start_sample:end_sample]


def emit_status_to_stderr(
    original_stderr_file,
    step: str,
    message: str,
    progress: Optional[float | int] = None,
    stage: Optional[str] = None,
    percent: Optional[float] = None,
    speed_x: Optional[float] = None,
    elapsed: Optional[float] = None,
) -> None:
    """Write a structured status update to the original stderr stream.
    Compatible with both QuranCaption ('step', 'progress') and QuranReciteToText ('stage', 'percent').
    """
    try:
        status_payload: Dict[str, Any] = {
            "step": step,
            "stage": stage or step,
            "message": message,
        }
        if progress is not None:
            status_payload["progress"] = progress
        if percent is not None:
            status_payload["percent"] = percent
        if speed_x is not None:
            status_payload["speed_x"] = speed_x
        if elapsed is not None:
            status_payload["elapsed"] = elapsed

        status_json = json.dumps(status_payload, ensure_ascii=False)
        original_stderr_file.write(f"STATUS:{status_json}\n")
        original_stderr_file.flush()
    except Exception:
        pass


def normalize_word_boundaries(words: List[Dict[str, Any]], segment_duration: float) -> List[Dict[str, Any]]:
    """Aligns word ends to next word starts within the segment duration without overlaps."""
    if not words:
        return words

    duration = max(0.0, segment_duration)
    normalized_starts: List[float] = []
    previous_start = 0.0
    for index, word in enumerate(words):
        raw_start = 0.0 if index == 0 else float(word.get("start", 0.0))
        start = max(previous_start, min(duration, raw_start))
        normalized_starts.append(start)
        previous_start = start

    normalized_words: List[Dict[str, Any]] = []
    for index, word in enumerate(words):
        start = normalized_starts[index]
        end = normalized_starts[index + 1] if index < len(words) - 1 else duration
        normalized_words.append(
            {
                **word,
                "start": round(start, 3),
                "end": round(max(start, end), 3),
            }
        )
    return normalized_words


def adapt_pipeline_result_to_qurancaption(
    pipeline_result: Any,
    offset_s: float = 0.0,
    start_segment_idx: int = 1,
) -> List[Dict[str, Any]]:
    """Converts a PipelineResult into QuranCaption's timeline segment list."""
    if hasattr(pipeline_result, "to_qurancaption_response"):
        return pipeline_result.to_qurancaption_response(
            offset_s=offset_s,
            start_segment_idx=start_segment_idx,
        )
    return []


def main() -> int:
    parser = argparse.ArgumentParser(description="Local WordTiming Quran Segmenter & Aligner")
    parser.add_argument("audio_path", nargs="?", default=None, help="Path to the input audio file")
    parser.add_argument("--audio", type=str, default=None, help="Path to input audio file")
    parser.add_argument("--dir", type=str, default=None, help="Path to audio directory for batch processing")
    parser.add_argument("--fast", action="store_true", default=True, help="Auto-configure top-speed parallel workers and threads for this CPU (default: True)")
    parser.add_argument("--no-fast", dest="fast", action="store_false", help="Disable fast parallel mode")
    parser.add_argument("--threads", type=int, default=None, help="ONNX execution threads (default: auto/2)")
    parser.add_argument("--workers", type=int, default=None, help="Parallel CPU workers count (default: auto in fast mode)")
    parser.add_argument("--min-silence-ms", type=int, default=200, help="Minimum silence pause threshold in ms")
    parser.add_argument("--min-speech-ms", type=int, default=1000, help="Minimum speech duration in ms")
    parser.add_argument("--pad-ms", type=int, default=100, help="Padding in ms")
    parser.add_argument("--timeline-clips-json", help="JSON array of timeline audio clips for in-memory slicing")
    parser.add_argument("--audio-regions-ms", help="JSON timeline regions to align independently")
    parser.add_argument("--qiraat", type=str, default="hafs", help="Canonical recitation tradition")
    parser.add_argument("--mfa", action="store_true", default=False)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    effective_audio = args.audio_path or args.audio
    if not effective_audio and not args.dir:
        print(json.dumps({"error": "Either audio file or --dir must be provided."}))
        return 1

    workers, threads = resolve_concurrency(
        fast=args.fast,
        user_workers=args.workers,
        user_threads=args.threads,
    )
    os.environ["ONNX_SEGMENT_WORKERS"] = str(workers)
    os.environ["OMP_NUM_THREADS"] = str(threads)
    os.environ["ONNX_NUM_THREADS"] = str(threads)

    if effective_audio and not os.path.exists(effective_audio):
        print(json.dumps({"error": f"Audio file not found: {effective_audio}"}))
        return 1
    if args.dir and not os.path.isdir(args.dir):
        print(json.dumps({"error": f"Directory not found: {args.dir}"}))
        return 1

    original_stderr_fd = os.dup(2)
    original_stderr_file = os.fdopen(original_stderr_fd, "w", encoding="utf-8")

    result = None
    error_result = None

    try:
        import config

        has_zipformer = any(
            p and os.path.exists(p) and os.path.getsize(p) > 10_000_000
            for p in [
                getattr(config, "DEFAULT_MODEL_PATH", None),
                str(getattr(config, "ONNX_DIR", config.DATA_PATH / "onnx") / "zipformer_p_arabic_v3.int8.onnx"),
                str(config.PROJECT_ROOT / "data" / "onnx" / "zipformer_p_arabic_v3.int8.onnx"),
            ]
        )
        has_silero = any(
            p and os.path.exists(p) and os.path.getsize(p) > 500_000
            for p in [
                getattr(config, "DEFAULT_SILERO_PATH", None),
                str(getattr(config, "ONNX_DIR", config.DATA_PATH / "onnx") / "silero_vad_half.onnx"),
                str(config.PROJECT_ROOT / "data" / "onnx" / "silero_vad_half.onnx"),
            ]
        )
        if not has_zipformer:
            emit_status_to_stderr(
                original_stderr_file, "loading", "Downloading Zipformer ONNX model (~72 MB)...", progress=3, stage="loading"
            )
        elif not has_silero:
            emit_status_to_stderr(
                original_stderr_file, "loading", "Downloading Silero VAD ONNX model (~1.3 MB)...", progress=7, stage="loading"
            )
        else:
            emit_status_to_stderr(
                original_stderr_file, "loading", "Initializing Zipformer engine & models...", progress=10, stage="loading"
            )

        from src import AudioPipeline
        from src.audio import AudioDecoder
        from src.models import PipelineProgressEvent, PipelineStage

        pipeline = AudioPipeline()
        pipeline.initialize(num_threads=threads)

        STAGE_WEIGHTS: Dict[Any, Tuple[float, float]] = {
            PipelineStage.loading: (0.0, 5.0),
            PipelineStage.vad: (5.0, 15.0),
            PipelineStage.transcribing: (15.0, 75.0),
            PipelineStage.recovering: (75.0, 78.0),
            PipelineStage.aligning: (78.0, 88.0),
            PipelineStage.matching: (88.0, 96.0),
            PipelineStage.exporting: (96.0, 98.0),
            PipelineStage.completed: (98.0, 100.0),
        }

        STAGE_TO_STEP: Dict[Any, str] = {
            PipelineStage.loading: "preparing",
            PipelineStage.vad: "segmenting",
            PipelineStage.transcribing: "transcribing",
            PipelineStage.recovering: "transcribing",
            PipelineStage.aligning: "matching",
            PipelineStage.matching: "matching",
            PipelineStage.exporting: "building",
            PipelineStage.completed: "building",
        }

        last_progress = [10]

        def make_progress_cb(clip_idx: int, total_clips: int):
            def on_progress(event: PipelineProgressEvent):
                stage = event.stage
                st_start, st_end = STAGE_WEIGHTS.get(stage, (15.0, 75.0))
                clamped_sub_pct = max(0.0, min(100.0, float(event.percent)))
                stage_pct = st_start + (clamped_sub_pct / 100.0) * (st_end - st_start)

                clip_span = 84.0 / max(1, total_clips)
                clip_base = 10.0 + (clip_idx * clip_span)
                clip_global = clip_base + (stage_pct * clip_span / 100.0)

                overall = int(round(clip_global))
                overall = min(95, max(last_progress[0], overall))
                last_progress[0] = overall

                step = STAGE_TO_STEP.get(stage, "processing")
                stage_val = stage.value if hasattr(stage, "value") else str(stage)
                emit_status_to_stderr(
                    original_stderr_file,
                    step=step,
                    message=event.message or "Transcribing & aligning...",
                    progress=overall,
                    stage=stage_val,
                    percent=round(event.percent, 1),
                    speed_x=round(event.speed_x or 0.0, 1),
                    elapsed=round(event.elapsed_seconds or 0.0, 2),
                )
            return on_progress

        sample_rate = getattr(config, "SAMPLE_RATE", 16000)
        all_segments = []
        all_pipeline_segments = []
        pipeline_res = None

        if args.dir:
            output_dir = getattr(config, "DEFAULT_OUTPUT_DIR", str(ENGINE_DIR / "output"))
            os.makedirs(output_dir, exist_ok=True)
            cb = make_progress_cb(0, 1)
            batch_res = pipeline.process_directory(
                input_dir=args.dir,
                output_dir=output_dir,
                on_progress_event=cb,
                enable_mfa=args.mfa,
                qiraat=args.qiraat,
            )
            result = batch_res
        elif args.timeline_clips_json:
            timeline_clips = json.loads(args.timeline_clips_json)
            total_clips = len(timeline_clips)

            for clip_idx, clip in enumerate(timeline_clips):
                source_start_ms = clip.get("sourceStartMs", clip.get("source_start_ms", 0))
                start_ms = clip.get("startMs", clip.get("start_ms", 0))
                end_ms = clip.get("endMs", clip.get("end_ms", 0))
                duration_ms = end_ms - start_ms

                source_start_s = max(0.0, float(source_start_ms) / 1000.0)
                duration_s = max(0.0, float(duration_ms) / 1000.0)
                timeline_offset_s = max(0.0, float(start_ms) / 1000.0)

                clip_path = clip.get("path") or effective_audio
                emit_status_to_stderr(
                    original_stderr_file,
                    step="preparing",
                    message=f"Decoding audio clip {clip_idx + 1}/{total_clips}...",
                    progress=last_progress[0],
                    stage="vad",
                )
                clip_pcm = load_audio_slice(
                    clip_path,
                    start_s=source_start_s,
                    duration_s=duration_s if duration_s > 0 else None,
                    sample_rate=sample_rate,
                )
                if len(clip_pcm) == 0:
                    continue

                cb = make_progress_cb(clip_idx, total_clips)
                pipeline_res = pipeline.process_pcm(
                    audio_pcm=clip_pcm,
                    export_json_files=False,
                    on_progress_event=cb,
                    enable_mfa=args.mfa,
                    qiraat=args.qiraat,
                )
                if pipeline_res and hasattr(pipeline_res, "segments") and pipeline_res.segments:
                    all_pipeline_segments.extend(pipeline_res.segments)
                clip_segs = adapt_pipeline_result_to_qurancaption(
                    pipeline_res,
                    offset_s=timeline_offset_s,
                    start_segment_idx=len(all_segments) + 1,
                )
                all_segments.extend(clip_segs)
        elif args.audio_regions_ms:
            regions = sorted(json.loads(args.audio_regions_ms), key=lambda region: region[0])
            for region_index, (start_ms, end_ms) in enumerate(regions):
                start_s = max(0.0, float(start_ms) / 1000.0)
                duration_s = max(0.0, float(end_ms - start_ms) / 1000.0)
                if duration_s <= 0:
                    continue
                emit_status_to_stderr(
                    original_stderr_file,
                    step="preparing",
                    message=f"Decoding audio region {region_index + 1}/{len(regions)}...",
                    progress=last_progress[0],
                    stage="vad",
                )
                region_pcm = load_audio_slice(
                    effective_audio,
                    start_s=start_s,
                    duration_s=duration_s,
                    sample_rate=sample_rate,
                )
                if len(region_pcm) == 0:
                    continue
                cb = make_progress_cb(region_index, len(regions))
                pipeline_res = pipeline.process_pcm(
                    audio_pcm=region_pcm,
                    export_json_files=False,
                    on_progress_event=cb,
                    enable_mfa=args.mfa,
                    qiraat=args.qiraat,
                )
                if pipeline_res and hasattr(pipeline_res, "segments") and pipeline_res.segments:
                    all_pipeline_segments.extend(pipeline_res.segments)
                offset_s = start_ms / 1000.0
                region_segs = adapt_pipeline_result_to_qurancaption(
                    pipeline_res,
                    offset_s=offset_s,
                    start_segment_idx=len(all_segments) + 1,
                )
                all_segments.extend(region_segs)
        else:
            emit_status_to_stderr(
                original_stderr_file,
                step="preparing",
                message="Decoding audio...",
                progress=last_progress[0],
                stage="vad",
            )
            audio_pcm = AudioDecoder.load_audio_file(effective_audio, sample_rate=sample_rate)
            cb = make_progress_cb(0, 1)
            pipeline_res = pipeline.process_pcm(
                audio_pcm=audio_pcm,
                export_json_files=False,
                on_progress_event=cb,
                enable_mfa=args.mfa,
                qiraat=args.qiraat,
            )
            if pipeline_res and hasattr(pipeline_res, "segments") and pipeline_res.segments:
                all_pipeline_segments.extend(pipeline_res.segments)
            all_segments = adapt_pipeline_result_to_qurancaption(pipeline_res, offset_s=0.0, start_segment_idx=1)

        if not args.dir:
            emit_status_to_stderr(
                original_stderr_file,
                step="building",
                message="Formatting word timestamps...",
                progress=96,
                stage="matching",
            )
            all_segments.sort(key=lambda s: s["time_from"])
            for i in range(len(all_segments) - 1):
                curr_seg = all_segments[i]
                next_seg = all_segments[i + 1]
                if curr_seg["time_to"] > next_seg["time_from"]:
                    curr_seg["time_to"] = next_seg["time_from"]
                    dur = max(0.0, round(curr_seg["time_to"] - curr_seg["time_from"], 3))
                    if curr_seg.get("words"):
                        curr_seg["words"] = normalize_word_boundaries(curr_seg["words"], dur)
            for idx, seg in enumerate(all_segments, start=1):
                seg["segment"] = idx

            surahs_list = []
            if all_pipeline_segments:
                from collections import defaultdict
                by_surah = defaultdict(list)
                for seg_item in all_pipeline_segments:
                    s_num = getattr(seg_item, "surah_number", 1) or 1
                    a_dict = seg_item.to_dict()
                    a_dict["surah"] = s_num
                    a_dict["surah_number"] = s_num
                    by_surah[s_num].append(a_dict)
                for s_num, ayahs in by_surah.items():
                    s_intro = None
                    for seg_item in all_pipeline_segments:
                        if (getattr(seg_item, "surah_number", 1) or 1) == s_num and getattr(seg_item, "intro", None):
                            s_intro = seg_item.intro
                            break
                    if s_intro is None and getattr(all_pipeline_segments[0], "intro", None):
                        s_intro = all_pipeline_segments[0].intro

                    surah_entry = {
                        "surah": s_num,
                        "surah_number": s_num,
                        "ayahs": ayahs,
                    }
                    if s_intro:
                        surah_entry["intro"] = s_intro
                    surahs_list.append(surah_entry)

            result = {
                "total_surahs": len(surahs_list) if surahs_list else 1,
                "surahs": surahs_list,
                "segments": all_segments,
            }

        emit_status_to_stderr(
            original_stderr_file,
            step="building",
            message="Segmentation complete",
            progress=100,
            stage="completed",
        )

    except Exception as error:
        import traceback
        error_result = {
            "error": str(error),
            "details": traceback.format_exc(),
        }
    finally:
        try:
            original_stderr_file.close()
        except Exception:
            pass

    if error_result:
        sys.stdout.write(json.dumps(error_result) + "\n")
        sys.stdout.flush()
        return 1

    sys.stdout.write(json.dumps(result, ensure_ascii=False) + "\n")
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
