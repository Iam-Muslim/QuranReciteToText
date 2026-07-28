# Multiline string serving as a docstring for the entire script.
"""
Command Line Offline Runner

This script provides the entry point for transcribing and aligning a full audio file 
from the command line. It wraps the audio in the strict CPU-bound overlapping windows
acoustic engine and maps it directly to the Quran text matching SDK.
"""
# Import the os module for interacting with the operating system.
import os
# Import the sys module to interact with Python interpreter variables.
import sys
# Import the Path class from pathlib to handle filesystem paths cleanly.
from pathlib import Path
# Import the argparse module to parse command-line options and arguments.
import argparse
import json
import sys

# Ensure UTF-8 output for stdout so Windows doesn't crash on Arabic paths
if sys.stdout is not None:
    sys.stdout.reconfigure(encoding='utf-8')


# ==============================================================================
# 1. Environment Setup
# ==============================================================================
# Ensure the project root directory is added to sys.path. 
# This allows the script to correctly import local modules (like src.*) 
# regardless of the directory from which the user runs the script.
# Resolve the absolute path of the directory containing this script.
_app_path = Path(__file__).parent.resolve()
# Insert the resolved application path at the beginning of the Python system path.
sys.path.insert(0, str(_app_path))

# Define a function named ensure_dependencies to check for required packages.
def ensure_dependencies():
    """
    Ensure required packages are installed; auto-install if they are missing.
    This provides a 'zero-configuration' plug-and-play experience for users.
    """
    # Import the subprocess module to spawn new processes, like pip.
    import subprocess
    # Start a try block to attempt importing dependencies.
    try:
        # Attempt to import all heavy third-party dependencies required by the pipeline.
        # Import the numpy library for numerical operations.
        import numpy
        # Import the librosa library for audio processing.
        import librosa
        # Import the pyloudnorm library for audio loudness normalization.
        import pyloudnorm
        # Import the sherpa_onnx library for ONNX-based speech recognition.
        import sherpa_onnx
        # Import the qua_sdk library for Quranic text matching.
        import qua_sdk
    # Catch any ImportError that occurs if a dependency is missing.
    except ImportError as e:
        # If any dependency is missing, we trap the error and auto-install.
        # Print a message indicating which dependency is missing and that it's auto-installing.
        print(f"Missing dependency: {e.name}. Auto-installing from requirements.txt...")
        
        # Locate the requirements.txt file in the root directory.
        # Construct the path to the requirements.txt file in the application directory.
        req_path = _app_path / "requirements.txt"
        # Check if the requirements.txt file exists at the constructed path.
        if req_path.exists():
            # Start a nested try block to attempt the installation.
            try:
                # Use subprocess to invoke pip and install the requirements silently.
                # Run the pip install command with the requirements.txt file.
                subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", str(req_path)])
                # Print a success message after the dependencies are installed.
                print("Dependencies installed successfully. Restarting script...")
                
                # os.execv completely replaces the current Python process with a new one.
                # This ensures the newly installed packages are successfully loaded into memory
                # without requiring the user to manually re-run the script.
                # Replace the current process with a new instance of the same script and arguments.
                os.execv(sys.executable, [sys.executable] + sys.argv)
            # Catch any exception that occurs during the pip installation process.
            except Exception as ex:
                # Print an error message if the auto-installation fails.
                print(f"Failed to auto-install dependencies: {ex}")
                # Exit the script with an error code 1 indicating failure.
                sys.exit(1) # Exit with error code if installation fails.
        # Execute this block if the requirements.txt file does not exist.
        else:
            # Print an error message indicating that requirements.txt is missing.
            print("requirements.txt not found! Please install dependencies manually.")
            # Exit the script with an error code 1 indicating failure.
            sys.exit(1)

# Define a function named preload_caches to load necessary data into memory.
def preload_caches():
    """
    Preloads the QPC Hafs references required by the qua_sdk batch_align string matchers.
    Doing this early ensures that text-matching during the pipeline is instantaneous.
    """
    # Print a message indicating that the caches are being preloaded.
    print("Preloading qua_sdk caches for text matching...")
    # Import specific functions from the qua_sdk.domain module for loading indices.
    from qua_sdk.domain import load_chapter_refs, load_ngram_index, load_quran_index, load_sub_costs
    
    # Start a try block to attempt loading the caches.
    try:
        # Load the base Quran text index (the canonical reference).
        # Call the load_quran_index function.
        load_quran_index()
        # Load the N-Gram index (used for fast anchor voting) using the "full" inventory mode.
        # Call the load_ngram_index function with the "full" argument.
        load_ngram_index("full")
        # Load chapter references (Surah and Ayah boundaries).
        # Call the load_chapter_refs function with the "full" argument.
        load_chapter_refs("full")
        # Load the substitution cost table (used by Needleman-Wunsch DP for character matching).
        # Call the load_sub_costs function with the "full" argument.
        load_sub_costs("full")
        
        # Print a success message after all caches are preloaded.
        print("Caches preloaded successfully.")
    # Catch any exception that occurs during the cache preload process.
    except Exception as e:
        # If caching fails, the pipeline will still run, but string matching will be much slower.
        # Print a warning message with the error details.
        print(f"Warning during cache preload (matching may be slower): {e}")

# ==============================================================================
# 2. Main Execution Flow
# ==============================================================================
# Define the main function that serves as the entry point of the script.
def main():
    # Step 1: Ensure all dependencies are present before we execute any heavy logic.
    # Call the ensure_dependencies function to check and install missing packages.
    ensure_dependencies()
    
    # Step 2: Set up the command-line argument parser.
    # Create an ArgumentParser object with a description for the script.
    parser = argparse.ArgumentParser(description="Run Audio through FastConformer")
    
    # Define the --audio argument: mandatory path to the input audio file (.wav, .mp3, etc.)
    # Add an argument for the input audio file, making it a required string.
    parser.add_argument("--audio", type=str, required=True, help="Path to the input audio file (.wav, .mp3)")
    
    # Define the --out argument: optional path to save the generated JSON output.
    # Defaults to 'output.json' if not provided by the user.
    # Add an argument for the output JSON file, providing a default value.
    parser.add_argument("--out", type=str, default="output.json", help="Path to save the JSON output")
    
    # Parse the arguments provided by the user in the terminal.
    # Parse the command-line arguments and store them in the args object.
    args = parser.parse_args()

    # Step 3: Validate that the requested audio file actually exists on the filesystem.
    # Check if the audio file specified in the arguments exists.
    if not os.path.exists(args.audio):
        # Print an error message if the input audio file is not found.
        print(f"Error: Input audio file not found at {args.audio}")
        # Exit the script with an error code 1 indicating failure.
        sys.exit(1)

    # Step 4: Preload all text-matching caches to memory.
    # Call the preload_caches function to prepare text matching data.
    preload_caches()

    # Step 5: Import the core pipeline processor.
    # We delay this import until now to ensure `ensure_dependencies()` has finished checking packages.
    # Import the process_audio function from the src.core.main_flow module.
    from src.core.main_flow import process_audio
    # Print a message indicating which audio file is being processed.
    print(f"\nProcessing audio: {args.audio} on CPU...")
    
    # Step 6: Execute the main transcription and alignment pipeline.
    # We wrap this in a try-except block to gracefully handle and print unexpected errors.
    # Start a try block to process the audio safely.
    try:
        # Call the process_audio function and store the result in json_output.
        json_output = process_audio(
            # Pass the input audio path from the arguments to the function.
            audio_data=args.audio,           # Pass the parsed audio file path.
            # Explicitly specify the model name to use for transcription.
            model_name="Base"                # Explicitly use the "Base" FastConformer model.
        )
    # Catch any general Exception that occurs during audio processing.
    except Exception as e:
        # Import the traceback module to print the stack trace.
        import traceback
        # Print the full stack trace to help with debugging the error.
        traceback.print_exc() # Print the full stack trace for debugging purposes.
        # Print a concise error message indicating the pipeline failed.
        print(f"Pipeline failed: {e}")
        # Exit the script with an error code 1 indicating failure.
        sys.exit(1)
    
    # Step 7: Save the resulting JSON payload to disk.
    # Open the output file specified in the arguments in write mode with UTF-8 encoding.
    with open(args.out, "w", encoding="utf-8") as f:
        # We use indent=2 to ensure the JSON is written in a clean, vertical, human-readable format.
        # ensure_ascii=False ensures Arabic characters are written natively (not as \uXXXX escapes).
        # Write the json_output dictionary to the file with specified formatting options.
        json.dump(json_output, f, ensure_ascii=False, indent=2)
        
    # Print a success message indicating the processing is complete.
    print(f"\nProcessing complete!")
    # Print the path where the JSON output was saved.
    print(f"JSON Output saved to: {args.out}")

# Standard Python idiom to ensure main() is only executed if this script is run directly.
# Check if the script is being run as the main program.
if __name__ == "__main__":
    # Call the main function to start execution.
    main()
