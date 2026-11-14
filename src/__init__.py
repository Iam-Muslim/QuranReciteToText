"""QuranReciteToText Package Entry Point & Central Pipeline Coordinator."""

from __future__ import annotations

import sys

# Bootstrap Windows MSVC runtime and console streams before importing C extensions
import data.bin.bootstrap  # noqa: F401

import gc
import json
import time
from pathlib import Path
from collections import defaultdict
from typing import Optional, Callable, Dict, Any, List, Union, Tuple
import numpy as np

import config
from config import (
    SAMPLE_RATE,
    DEFAULT_MODEL_DIR,
    DEFAULT_TOKENS_PATH,
    DEFAULT_EXPECTED_ZFX_PATH,
    DEFAULT_OUTPUT_DIR,
    DEFAULT_QPC_HAFS_PATH,
)
from src.models import (
    PhonemeToken,
    PauseInterval,
    RawTranscriptionResult,
    QuranWord,
    AyahSubSegment,
    QuranSegment,
    PipelineProfiling,
    PipelineResult,
    PipelineStage,
    PipelineProgressEvent,
    RecoveryEvent,
    RecoverySummary,
    SpeechRecoveryResult,
)
from src.audio import AudioDecoder, _resample_audio
from src.transcriber import TajweedFormerEngine, SpeechRecoveryEngine
from src.matching import (
    QuranWordMatcher,
    MatcherConfig,
    warmup_matching,
    QiraatAyahMapper,
    QuranCountingSystem,
)


class AudioPipeline:
    """Central 4-phase audio transcription and Quran alignment coordinator."""

    def __init__(self):
        self.transcriber = None
        self.matcher = QuranWordMatcher()

    def initialize(
        self,
        model_path: str = DEFAULT_MODEL_DIR,
        tokens_path: str = DEFAULT_TOKENS_PATH,
        zfx_path: str = DEFAULT_EXPECTED_ZFX_PATH,
        qpc_path: Optional[str] = None,
        num_threads: int = 0,
    ) -> None:
        if self.transcriber is None:
            self.transcriber = TajweedFormerEngine.get_instance(model_dir=model_path, threads=num_threads)

        if not self.matcher.is_initialized:
            self.matcher.initialize_from_file(
                zfx_path=zfx_path,
                tokens_path=tokens_path,
                qpc_path=qpc_path or DEFAULT_QPC_HAFS_PATH,
            )

        # Warm up Numba JIT kernels so runtime Phase 3 is instant
        try:
            warmup_matching()
        except Exception:
            pass

    def process_audio_file(
        self,
        audio_file_path: str,
        output_dir: str = ".",
        export_json_files: bool = True,
        on_progress_event: Optional[Callable[[PipelineProgressEvent], None]] = None,
        target_surah: Optional[int] = None,
        start_ayah: Optional[int] = None,
        qiraat: str = "hafs",
    ) -> PipelineResult:
        load_start = time.time()
        if on_progress_event:
            on_progress_event(
                PipelineProgressEvent(stage=PipelineStage.loading, percent=0.0, elapsed_seconds=0.0, message="Loading audio...")
            )

        audio_pcm = AudioDecoder.load_audio_file(audio_file_path)
        load_time = time.time() - load_start

        return self.process_pcm(
            audio_pcm=audio_pcm,
            load_time=load_time,
            output_dir=output_dir,
            export_json_files=export_json_files,
            on_progress_event=on_progress_event,
            target_surah=target_surah,
            start_ayah=start_ayah,
            qiraat=qiraat,
        )

    def process_directory(
        self,
        input_dir: str,
        output_dir: str = DEFAULT_OUTPUT_DIR,
        live_profile: bool = False,
        json_progress: bool = False,
        on_progress_event: Optional[Callable[[PipelineProgressEvent], None]] = None,
        qiraat: str = "hafs",
    ) -> Dict[str, Any]:
        """Transcribes all audio files in a directory recursively, preserving folder hierarchy.

        Outputs <audio_stem>.json for each audio, and an ordered all_surahs.json per subfolder.
        """
        input_root = Path(input_dir).resolve()
        out_root = Path(output_dir).resolve()

        audio_files = sorted(
            [p for p in input_root.rglob("*") if p.is_file() and p.suffix.lower() in AudioDecoder.SUPPORTED_EXTENSIONS]
        )

        total_files = len(audio_files)
        if total_files == 0:
            if live_profile:
                print(f"[!] No audio files found in directory: {input_root}", file=sys.stderr)
            elif json_progress:
                print(json.dumps({"stage": "batch_error", "message": f"No audio files found in: {input_root}"}), flush=True)
            return {"total_files": 0, "succeeded": [], "failed": [], "total_time_seconds": 0.0}

        batch_start = time.time()
        if live_profile:
            print("=" * 65)
            print(f"Batch Processing: {total_files} audio file(s) found in '{input_root}'")
            print(f"Output Directory: '{out_root}'")
            print("=" * 65, flush=True)
        elif json_progress:
            print(json.dumps({
                "stage": "batch_start",
                "total_files": total_files,
                "input_dir": str(input_root),
                "output_dir": str(out_root),
            }), flush=True)

        folder_surahs: Dict[Path, Dict[int, Dict[str, Any]]] = defaultdict(dict)
        folder_files_count: Dict[Path, int] = defaultdict(int)
        succeeded: List[str] = []
        failed: List[Tuple[str, str]] = []

        for idx, audio_file in enumerate(audio_files, 1):
            rel_path = audio_file.relative_to(input_root)
            rel_folder = rel_path.parent
            target_dir = out_root / rel_folder
            target_dir.mkdir(parents=True, exist_ok=True)
            target_json = target_dir / f"{audio_file.stem}.json"
            file_start = time.time()

            if live_profile:
                print(f"[{idx}/{total_files}] Processing: {rel_path} ...", flush=True)
            elif json_progress:
                print(json.dumps({
                    "stage": "batch_file_start",
                    "index": idx,
                    "total": total_files,
                    "file": str(rel_path),
                }), flush=True)

            if on_progress_event:
                on_progress_event(
                    PipelineProgressEvent(
                        stage=PipelineStage.loading,
                        percent=round((idx - 1) / max(1, total_files) * 100.0, 1),
                        elapsed_seconds=time.time() - batch_start,
                        message=f"[{idx}/{total_files}] Processing {rel_path}",
                    )
                )

            audio_pcm = None
            try:
                audio_pcm = AudioDecoder.load_audio_file(str(audio_file))
                result = self.process_pcm(
                    audio_pcm=audio_pcm,
                    output_dir=str(target_dir),
                    export_json_files=False,
                    live_profile=live_profile,
                    json_progress=json_progress,
                    on_progress_event=on_progress_event,
                    qiraat=qiraat,
                )
                out_dict = result.to_output_dict()

                with open(target_json, "w", encoding="utf-8") as f:
                    json.dump(out_dict, f, ensure_ascii=False, indent=2)

                for surah_data in out_dict.get("surahs", []):
                    s_num = surah_data.get("surah")
                    if s_num not in folder_surahs[rel_folder]:
                        folder_surahs[rel_folder][s_num] = {
                            "surah": s_num,
                            "ayahs": [],
                        }
                        if surah_data.get("intro"):
                            folder_surahs[rel_folder][s_num]["intro"] = surah_data["intro"]

                    folder_surahs[rel_folder][s_num]["ayahs"].extend(surah_data.get("ayahs", []))
                    if "intro" not in folder_surahs[rel_folder][s_num] and surah_data.get("intro"):
                        folder_surahs[rel_folder][s_num]["intro"] = surah_data["intro"]

                file_elapsed = time.time() - file_start
                succeeded.append(str(rel_path))
                folder_files_count[rel_folder] += 1
                prof = result.profiling

                if live_profile:
                    rtf_str = f", {prof.real_time_factor:.1f}x Real-Time" if prof and prof.real_time_factor > 0 else ""
                    dur_str = f"{prof.audio_duration:.2f}s in " if prof and prof.audio_duration > 0 else ""
                    print(f"[{idx}/{total_files}] -> Saved {target_json.name} ({dur_str}{file_elapsed:.2f}s{rtf_str})", flush=True)
                elif json_progress:
                    print(json.dumps({
                        "stage": "batch_file_done",
                        "index": idx,
                        "total": total_files,
                        "file": str(rel_path),
                        "saved": str(target_json),
                        "elapsed": round(file_elapsed, 2),
                    }), flush=True)

            except Exception as exc:
                failed.append((str(rel_path), str(exc)))
                if live_profile:
                    print(f"[!] Failed to process {rel_path}: {exc}", file=sys.stderr, flush=True)
                elif json_progress:
                    print(json.dumps({
                        "stage": "batch_file_error",
                        "index": idx,
                        "total": total_files,
                        "file": str(rel_path),
                        "error": str(exc),
                    }), flush=True)
            finally:
                if 'result' in locals():
                    del result
                if 'out_dict' in locals():
                    del out_dict
                del audio_pcm
                gc.collect()

        # Write merged all_surahs.json per folder (only when folder has >= 2 files to merge)
        for rel_folder in sorted(folder_surahs.keys()):
            if folder_files_count[rel_folder] <= 1:
                continue

            folder_target_dir = out_root / rel_folder
            folder_target_dir.mkdir(parents=True, exist_ok=True)
            merged_file = folder_target_dir / "all_surahs.json"

            surahs_dict = folder_surahs[rel_folder]
            for s_num, s_obj in surahs_dict.items():
                s_obj["ayahs"].sort(key=lambda a: a.get("ayah", 0))

            sorted_surahs = [surahs_dict[k] for k in sorted(surahs_dict.keys())]
            merged_doc = {
                "total_surahs": len(sorted_surahs),
                "surahs": sorted_surahs,
            }
            with open(merged_file, "w", encoding="utf-8") as f:
                json.dump(merged_doc, f, ensure_ascii=False, indent=2)

        total_time = time.time() - batch_start
        if live_profile:
            print("=" * 65)
            print(f"Batch Complete: {len(succeeded)}/{total_files} succeeded, {len(failed)} failed.")
            print(f"Total Time    : {total_time:.2f}s")
            if failed:
                print("Failed files:")
                for fpath, err in failed:
                    print(f"  - {fpath}: {err}")
            print("=" * 65, flush=True)
        elif json_progress:
            print(json.dumps({
                "stage": "batch_completed",
                "total_files": total_files,
                "succeeded": len(succeeded),
                "failed": len(failed),
                "total_time": round(total_time, 2),
            }), flush=True)

        if on_progress_event:
            on_progress_event(
                PipelineProgressEvent(
                    stage=PipelineStage.completed,
                    percent=100.0,
                    elapsed_seconds=total_time,
                    message=f"Batch complete: {len(succeeded)}/{total_files} succeeded",
                )
            )

        return {
            "total_files": total_files,
            "succeeded": succeeded,
            "failed": failed,
            "total_time_seconds": round(total_time, 2),
        }

    def process_pcm(
        self,
        audio_pcm: np.ndarray,
        load_time: float = 0.0,
        output_dir: str = ".",
        export_json_files: bool = True,
        on_progress_event: Optional[Callable[[PipelineProgressEvent], None]] = None,
        live_profile: bool = False,
        json_progress: bool = False,
        target_surah: Optional[int] = None,
        start_ayah: Optional[int] = None,
        qiraat: str = "hafs",
    ) -> PipelineResult:
        overall_start = time.time()
        audio_duration = len(audio_pcm) / SAMPLE_RATE

        # Phase 1: VAD Silence & Speech Detection
        asr_start = time.time()
        last_progress_time = [0.0]

        def _on_vad_done(vad_seconds: float) -> None:
            if live_profile:
                print(f"Phase 1 VAD         : {vad_seconds:.2f}s", flush=True)
            elif json_progress:
                sys.stdout.write(json.dumps({"stage": "vad", "elapsed": round(vad_seconds, 2)}) + "\n")
                sys.stdout.flush()
            if on_progress_event:
                on_progress_event(
                    PipelineProgressEvent(
                        stage=PipelineStage.vad,
                        percent=100.0,
                        elapsed_seconds=vad_seconds,
                        message=f"VAD completed in {vad_seconds:.2f}s",
                    )
                )

        # Phase 2: Transcribing (TajweedFormer V4 ASR)
        def _on_asr_progress(pct: float, spd: float, elp: float) -> None:
            now = time.time()
            if (now - last_progress_time[0] >= 0.25) or pct >= 100.0:
                last_progress_time[0] = now
                if live_profile:
                    filled = int(20 * pct / 100.0)
                    bar = "=" * filled + " " * (20 - filled)
                    sys.stdout.write(f"\r\033[2KPhase 2 Transcribe  : [{bar}] {pct:3.0f}% ({elp:.1f}s)")
                    sys.stdout.flush()
                elif json_progress:
                    sys.stdout.write(json.dumps({"stage": "transcribing", "percent": round(pct, 1), "elapsed": round(elp, 1), "speed_x": round(spd, 1)}) + "\n")
                    sys.stdout.flush()
                if on_progress_event:
                    on_progress_event(
                        PipelineProgressEvent(
                            stage=PipelineStage.transcribing,
                            percent=pct,
                            elapsed_seconds=elp,
                            speed_x=spd,
                            message=f"Transcribing {pct:.0f}%",
                        )
                    )

        raw_result = self.transcriber.transcribe_audio(
            audio=audio_pcm,
            sample_rate=SAMPLE_RATE,
            on_progress=_on_asr_progress if (live_profile or json_progress or on_progress_event) else None,
            on_vad_done=_on_vad_done if (live_profile or json_progress or on_progress_event) else None,
        )
        phonemes = raw_result.phonemes
        vad_time = getattr(raw_result, "vad_time", 0.0)
        pure_asr_time = max(0.0, (time.time() - asr_start) - vad_time)
        if live_profile:
            sys.stdout.write(f"\r\033[2KPhase 2 Transcribe  : {pure_asr_time:.2f}s\n")
            sys.stdout.flush()

        # Speech Recovery (Optional Second Pass on Audio Gaps)
        recovery_events: List[RecoveryEvent] = []
        recovery_summary = RecoverySummary(0.0, 0, 0, 0, 0)
        recovery_time = 0.0

        if getattr(config, "ENABLE_SPEECH_RECOVERY", True):
            rec_start = time.time()
            rec_res = SpeechRecoveryEngine.recover_speech(
                audio_pcm=audio_pcm,
                initial_phonemes=phonemes,
                audio_duration=audio_duration,
                transcriber=self.transcriber,
                noise_floor_db=getattr(raw_result, "noise_floor_db", None),
            )
            phonemes = rec_res.recovered_phonemes
            recovery_events = rec_res.recovery_events
            recovery_summary = rec_res.recovery_summary
            recovery_time = time.time() - rec_start
            if live_profile:
                print(f"Speech Recovery     : {recovery_time:.2f}s", flush=True)

        audio_pcm = None

        # Phase 3: Matching (Quran Text Matcher & Ayah Alignment)
        match_start = time.time()
        if json_progress:
            print(json.dumps({"stage": "matching", "percent": 0.0, "message": "Matching verses"}), flush=True)
        if on_progress_event:
            on_progress_event(
                PipelineProgressEvent(
                    stage=PipelineStage.matching,
                    percent=0.0,
                    elapsed_seconds=time.time() - overall_start,
                    message="Matching verses to Medina reference...",
                )
            )
        segments = self.matcher.match_segments(
            phonemes=phonemes,
            audio_duration=audio_duration,
            target_surah=target_surah,
            start_ayah=start_ayah,
            pause_timestamps=raw_result.pause_timestamps,
            pause_intervals=raw_result.pause_intervals,
        )

        # Optional Canonical Qira'at Ayah Translation (Zero-overhead bypass for Hafs)
        if qiraat and qiraat.strip().lower() != "hafs":
            mapper = QiraatAyahMapper.load(qiraat)
            segments = mapper.remap_segments(segments)

        for seg in segments:
            if not seg.sub_segments:
                seg.sub_segments = None
            else:
                for idx, sub in enumerate(seg.sub_segments):
                    sub.sub_segment_number = idx + 1

        match_time = time.time() - match_start
        if live_profile:
            print(f"Phase 3 Text Match  : {match_time:.2f}s", flush=True)
        elif json_progress:
            print(json.dumps({"stage": "matching", "percent": 100.0, "elapsed": round(match_time, 2)}), flush=True)
        if on_progress_event:
            on_progress_event(
                PipelineProgressEvent(
                    stage=PipelineStage.matching,
                    percent=100.0,
                    elapsed_seconds=time.time() - overall_start,
                    message="Verses matched successfully",
                )
            )

        # Phase 4: Exporting (JSON Artifact Export)
        export_start = time.time()
        if json_progress:
            sys.stdout.write(json.dumps({"stage": "exporting", "percent": 0.0, "message": "Exporting JSON artifacts..."}) + "\n")
            sys.stdout.flush()
        if on_progress_event:
            on_progress_event(
                PipelineProgressEvent(
                    stage=PipelineStage.exporting,
                    percent=0.0,
                    elapsed_seconds=time.time() - overall_start,
                    message="Building subtitle timeline and exporting JSON...",
                )
            )

        result = PipelineResult(
            audio_duration_seconds=audio_duration,
            phonemes=phonemes,
            segments=segments,
            pause_timestamps=raw_result.pause_timestamps,
            pause_intervals=raw_result.pause_intervals,
            recovery_events=recovery_events,
            recovery_summary=recovery_summary,
        )

        if export_json_files:
            exported_paths = result.export_json(output_dir=output_dir)
            result.exported_files = exported_paths

        export_time = time.time() - export_start
        if live_profile:
            print(f"Phase 4 JSON Export : {export_time:.2f}s", flush=True)
        elif json_progress:
            sys.stdout.write(json.dumps({"stage": "exporting", "percent": 100.0, "elapsed": round(export_time, 2)}) + "\n")
            sys.stdout.flush()
        if on_progress_event:
            on_progress_event(
                PipelineProgressEvent(
                    stage=PipelineStage.exporting,
                    percent=100.0,
                    elapsed_seconds=time.time() - overall_start,
                    message="Export completed",
                )
            )

        total_time = time.time() - overall_start

        profiling = PipelineProfiling(
            audio_duration=audio_duration,
            load_time=load_time,
            vad_time=vad_time,
            asr_time=pure_asr_time,
            recovery_time=recovery_time,
            match_time=match_time,
            export_time=export_time,
            total_time=total_time,
        )
        result.total_processing_time_seconds = total_time
        result.profiling = profiling

        return result


_shared_pipeline: Optional[AudioPipeline] = None


def get_shared_pipeline() -> AudioPipeline:
    global _shared_pipeline
    if _shared_pipeline is None:
        _shared_pipeline = AudioPipeline()
        _shared_pipeline.initialize()
    return _shared_pipeline


def process_audio(
    audio_data: Union[str, np.ndarray, Tuple[int, np.ndarray]],
    output_dir: str = ".",
    export_json_files: bool = False,
    return_profiling: bool = False,
) -> Union[List[Dict[str, Any]], Tuple[List[Dict[str, Any]], PipelineProfiling]]:
    """Functional one-line runner for audio alignment."""
    pipeline = get_shared_pipeline()
    if isinstance(audio_data, str):
        result = pipeline.process_audio_file(
            audio_file_path=audio_data,
            output_dir=output_dir,
            export_json_files=export_json_files,
        )
    elif isinstance(audio_data, tuple):
        orig_sr, pcm = audio_data
        if orig_sr != SAMPLE_RATE:
            pcm = _resample_audio(pcm.astype(np.float32), orig_sr, SAMPLE_RATE)
        result = pipeline.process_pcm(
            audio_pcm=pcm.astype(np.float32),
            output_dir=output_dir,
            export_json_files=export_json_files,
        )
    else:
        result = pipeline.process_pcm(
            audio_pcm=audio_data.astype(np.float32),
            output_dir=output_dir,
            export_json_files=export_json_files,
        )

    segments_dicts = [s.to_dict() for s in result.segments]
    if return_profiling:
        return segments_dicts, result.profiling
    return segments_dicts


__all__ = [
    "AudioPipeline",
    "process_audio",
    "get_shared_pipeline",
    "AudioDecoder",
    "TajweedFormerEngine",
    "SpeechRecoveryEngine",
    "SpeechRecoveryResult",
    "RecoveryEvent",
    "RecoverySummary",
    "QuranWordMatcher",
    "MatcherConfig",
    "QiraatAyahMapper",
    "QuranCountingSystem",
    "PhonemeToken",
    "PauseInterval",
    "QuranWord",
    "QuranSegment",
    "AyahSubSegment",
    "RawTranscriptionResult",
    "PipelineResult",
    "PipelineProfiling",
    "PipelineStage",
    "PipelineProgressEvent",
]
