import os
import sys
from pathlib import Path
import argparse
import json

# Ensure project root is in sys.path exactly as app.py does
_app_path = Path(__file__).parent.resolve()
sys.path.insert(0, str(_app_path))

def preload_caches():
    """Preloads the QPC Hafs references required by the qua_sdk batch_align string matchers."""
    print("Preloading qua_sdk caches for text matching...")
    from qua_sdk.domain import load_chapter_refs, load_ngram_index, load_quran_index, load_sub_costs
    
    try:
        load_quran_index()
        # "full" is the inventory mode used by the default model configuration
        load_ngram_index("full")
        load_chapter_refs("full")
        load_sub_costs("full")
        print("Caches preloaded successfully.")
    except Exception as e:
        print(f"Warning during cache preload (matching may be slower): {e}")

def main():
    # Instantiate the ArgumentParser to handle command-line arguments.
    parser = argparse.ArgumentParser(description="Run Audio through FastConformer")
    
    # Define the --audio argument: mandatory path to the input audio file (.wav or .mp3).
    parser.add_argument("--audio", type=str, required=True, help="Path to the input audio file (.wav, .mp3)")
    
    # Define the --out argument: optional path to save the generated JSON output (defaults to output.json).
    parser.add_argument("--out", type=str, default="output.json", help="Path to save the JSON output")
    
    # Define the --letters argument: boolean flag to enable extraction of letter-level timestamps.
    parser.add_argument("--letters", action="store_true", help="Include per-letter timestamps in the output")
    
    # Define the --fast argument: boolean flag to enable fast mode (reduces sliding window overlap to 5s instead of 10s).
    parser.add_argument("--fast", action="store_true", help="Enable fast mode (reduced overlap, max CPU threads)")
    
    # Define the --device argument: switch between CPU and CUDA for inference.
    parser.add_argument("--device", type=str, default="cuda", choices=["cpu", "cuda"], help="Device to run inference on")
    
    # Parse the provided command-line arguments.
    args = parser.parse_args()

    if not os.path.exists(args.audio):
        print(f"Error: Input audio file not found at {args.audio}")
        sys.exit(1)

    preload_caches()

    # Import the main pipeline entry function process_audio from the pipeline module.
    from src.pipeline.entries import process_audio
    print(f"\nProcessing audio: {args.audio} on {args.device}...")
    
    # Wrap the pipeline execution in a try-except block to catch and report errors gracefully.
    try:
        # Call process_audio to process the entire audio file using the Sliding Window engine.
        outcome = process_audio(
            audio_data=args.audio,           # Pass the parsed audio file path.
            model_name="Base",               # Use the default "Base" model.
            device=args.device,              # Dynamic device execution as requested.
            is_preset=False,                 # Indicate this is not a preset UI run.
            log_enabled=False,               # Disable detailed internal logging to stdout.
            return_html=False,               # Set to False so outcome.segments returns raw JSON dicts instead of an HTML string.
            include_letters=args.letters,    # Pass the boolean flag controlling letter timestamp generation.
            fast_mode=args.fast              # Pass the boolean flag controlling fast sliding window mode.
        )
        
        # Extract the final JSON dictionary from the pipeline outcome object.
        json_output = outcome.segments
        
        # Extract the directory path where temporary segmented WAV files were saved.
        segment_dir = outcome.segment_dir
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"Pipeline failed: {e}")
        sys.exit(1)
    
    # Save the JSON payload
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(json_output, f, ensure_ascii=False, separators=(',', ':'))
        
    print(f"\nProcessing complete!")
    print(f"JSON Output saved to: {args.out}")
    if segment_dir:
        print(f"Generated Segment WAVs dir: {segment_dir}")

if __name__ == "__main__":
    main()
