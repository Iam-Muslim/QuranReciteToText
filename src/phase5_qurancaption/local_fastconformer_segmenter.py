#!/usr/bin/env python3
"""
IPC Bridge: FastConformer -> QuranCaption
This script wraps the FastConformer audio segmentation pipeline 
so it can be executed natively by the QuranCaption desktop app.
"""

import argparse
import json
import os
import sys
import io
import traceback
from pathlib import Path

# Force CPU ONLY execution before anything else is loaded.
os.environ["CUDA_VISIBLE_DEVICES"] = ""

# Instead of hardcoding the D: drive, dynamically resolve the engine folder.
# In QuranCaption, this script lives in src-tauri/python/
# We will store the FastConformer repo inside src-tauri/python/fastconformer_engine/
PROJECT_ROOT = (Path(__file__).parent / "fastconformer_engine").absolute()

# Ensure the folder exists so sys.path doesn't break initially
PROJECT_ROOT.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(PROJECT_ROOT))

# Ensure UTF-8
if sys.platform == "win32":
    if sys.stdout is not None:
        sys.stdout.reconfigure(encoding="utf-8")
    if sys.stderr is not None:
        sys.stderr.reconfigure(encoding="utf-8")

def emit_status_to_stderr(original_stderr_file, step: str, message: str) -> None:
    """Emits progress events to QuranCaption via stderr."""
    try:
        status_json = json.dumps({"step": step, "message": message}, ensure_ascii=False)
        original_stderr_file.write(f"STATUS:{status_json}\n")
        original_stderr_file.flush()
    except Exception:
        pass

class PrintInterceptor:
    """Intercepts print statements and emits them as progress to QuranCaption."""
    def __init__(self, original_stderr):
        self.original_stderr = original_stderr
        self.buffer = ""

    def write(self, text):
        self.buffer += text
        if "\n" in self.buffer:
            lines = self.buffer.split("\n")
            for line in lines[:-1]:
                clean_line = line.strip()
                if clean_line:
                    # Parse specific progress logs formatted as "[PROGRESS] Stage 45.5%"
                    if "[PROGRESS]" in clean_line:
                        import re
                        msg = clean_line.replace("[PROGRESS]", "").strip()
                        pct_match = re.search(r"(\d+(\.\d+)?)%", msg)
                        if pct_match:
                            pct = float(pct_match.group(1))
                            try:
                                status_json = json.dumps({"step": "Processing", "message": msg, "progress": pct}, ensure_ascii=False)
                                self.original_stderr.write(f"STATUS:{status_json}\n")
                                self.original_stderr.flush()
                            except Exception:
                                pass
                        else:
                            emit_status_to_stderr(self.original_stderr, "Processing", clean_line)
                    else:
                        emit_status_to_stderr(self.original_stderr, "Processing", clean_line)
            self.buffer = lines[-1]

    def flush(self):
        pass

def parse_reference(ref_str: str):
    """Parses '2:255:1' -> surah: 2, ayah: 255"""
    if not ref_str or ":" not in ref_str:
        return 1, 1 # fallback
    parts = ref_str.split(":")
    if len(parts) >= 2:
        try:
            return int(parts[0]), int(parts[1])
        except ValueError:
            return 1, 1
    return 1, 1

def adapt_segments_to_qc(fastconformer_segments):
    """Transforms FastConformer output to QuranCaption format."""
    qc_segments = []
    
    for seg in fastconformer_segments:
        surah, ayah = parse_reference(seg.get("ref_from", ""))
        
        words_qc = []
        for w in seg.get("words", []):
            start_val = w.get("start", 0.0)
            end_val = w.get("end", 0.0)
            words_qc.append({
                "word": w.get("word", ""),
                "start": round(start_val, 3) if start_val is not None else 0.0,
                "end": round(end_val, 3) if end_val is not None else 0.0,
            })
            
        qc_segments.append({
            "surahNumber": surah,
            "ayahNumber": ayah,
            "startTime": seg.get("time_from", 0.0),
            "endTime": seg.get("time_to", 0.0),
            "text": seg.get("matched_text", ""),
            "words": words_qc,
        })
        
    return qc_segments

def main() -> int:
    parser = argparse.ArgumentParser(description="FastConformer QuranCaption Bridge")
    # Accept standard QuranCaption arguments
    parser.add_argument("audio_path", help="Path to the audio file")
    parser.add_argument("--device", type=str, default="CPU", choices=["GPU", "CPU", "cpu", "gpu"])
    # Ignore extra args passed by QuranCaption UI
    parser.add_argument("--min-silence-ms", type=int, default=200)
    parser.add_argument("--min-speech-ms", type=int, default=1000)
    parser.add_argument("--pad-ms", type=int, default=100)
    parser.add_argument("--model-name", type=str, default="Base")
    parser.add_argument("--surah", type=int, default=0)
    parser.add_argument("--include-wbw-timestamps", type=str, default="true")
    parser.add_argument("--verbose", action="store_true")
    args, unknown = parser.parse_known_args()

    if not os.path.exists(args.audio_path):
        print(json.dumps({"error": f"Audio file not found: {args.audio_path}"}))
        return 1

    # Force CPU if requested
    if args.device.upper() == "CPU":
        os.environ["CUDA_VISIBLE_DEVICES"] = ""

    # Preserve real stderr for IPC
    original_stderr_fd = os.dup(2)
    original_stderr_file = os.fdopen(original_stderr_fd, "w", encoding="utf-8")
    
    emit_status_to_stderr(original_stderr_file, "Init", "Loading FastConformer pipeline...")
    
    # Run the auto-updater
    try:
        from src.core.updater import check_and_update
        def qc_log(msg):
            emit_status_to_stderr(original_stderr_file, "Init", msg)
        check_and_update(PROJECT_ROOT, log_callback=qc_log)
    except Exception as e:
        emit_status_to_stderr(original_stderr_file, "Init", f"Auto-updater error: {e}")

    # Redirect stdout to avoid polluting the final JSON response
    old_stdout = sys.stdout
    interceptor = PrintInterceptor(original_stderr_file)
    sys.stdout = interceptor

    result = None
    error_result = None
    try:
        from src.core.main_flow import process_audio
        
        # Run pipeline
        fc_payload = process_audio(audio_data=args.audio_path, model_name="Base")
        
        # Transform results
        emit_status_to_stderr(original_stderr_file, "Finalizing", "Formatting for QuranCaption...")
        
        # FastConformer payload is expected to be a dict with a "segments" key
        if isinstance(fc_payload, dict):
            fc_segments = fc_payload.get("segments", [])
        elif isinstance(fc_payload, list):
            fc_segments = fc_payload
        else:
            fc_segments = []
            
        qc_segments = adapt_segments_to_qc(fc_segments)
        
        result = {
            "segments": qc_segments,
            "warning": ""
        }
        
    except Exception as error:
        import traceback
        error_result = {
            "error": str(error),
            "details": traceback.format_exc(),
        }
    finally:
        # Restore stdout
        sys.stdout = old_stdout

    if error_result:
        print(json.dumps(error_result, ensure_ascii=False))
        return 1

    # Output strictly the final JSON
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0

if __name__ == "__main__":
    sys.exit(main())
