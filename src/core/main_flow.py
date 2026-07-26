"""
Pipeline Entry Points

This module acts as the central conductor for the entire transcription and matching pipeline.
It handles audio ingestion (converting everything to standard 16kHz mono), orchestrates 
the FastConformer acoustic engine (Phase 1), and then hands off the results to the 
text-matching SDK (Phase 2).
"""
# Import the time module to measure execution duration.
import time
# Import the subprocess module to run external commands like FFmpeg.
import subprocess
# Import the numpy library for efficient numerical arrays.
import numpy as np

# Import the sdk_adapt module from the local core package.
from src.core import sdk_adapt
# Import the ProfilingData class to store performance metrics.
from src.core.segment_types import ProfilingData
# Import the resolve function from qua_sdk.registry (unused in this specific snippet but imported).
from qua_sdk.registry import resolve

# Import the Phase 1 processing logic from our custom pipeline.
# Import specific functions from the stream module.
from src.phase1_transcribe.stream import (
    # Import the state reset function.
    _reset_request_state,
    # Import the CPU-based ASR execution function.
    run_asr_cpu,
)
# Import the Phase 2 DP matching logic from our custom pipeline.
# Import the post-ASR pipeline execution function.
from src.phase2_matching.matcher import _run_post_asr_pipeline


# Define a function to load audio using FFmpeg directly.
def _load_audio_ffmpeg(file_path, target_sr=16000):
    """
    Loads an audio file directly from disk into a 1D NumPy array of 32-bit floats.
    
    Why FFmpeg instead of librosa?
    Loading massive 2-hour audio files via librosa can easily exhaust 16GB of RAM.
    FFmpeg streams the decoded PCM audio directly into a NumPy buffer, which is 
    orders of magnitude more memory-efficient and much faster.
    """
    # Build the FFmpeg command
    # Define the command arguments as a list of strings.
    command = [
        # The base command to execute FFmpeg.
        'ffmpeg',
        '-v', 'quiet',           # Suppress FFmpeg terminal output
        '-i', file_path,         # The input file path
        '-f', 'f32le',           # Force output format to raw 32-bit little-endian floats
        '-acodec', 'pcm_f32le',  # Use the float32 PCM encoder
        '-ac', '1',              # Mix down to a single Mono channel
        '-ar', str(target_sr),   # Resample to the target sample rate (default 16000Hz)
        'pipe:1'                 # Output the raw audio bytes directly to stdout
    ]
    
    # Execute the FFmpeg command
    # Start the FFmpeg process, capturing stdout and stderr.
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    # Wait for the process to finish and capture the outputs.
    stdout, stderr = process.communicate()
    
    # Check for errors during decoding
    # Check if the process exited with a non-zero status code.
    if process.returncode != 0:
        # Raise a RuntimeError with the decoded stderr message.
        raise RuntimeError(f"FFmpeg failed to load audio: {stderr.decode('utf-8', errors='ignore')}")
        
    # Convert the raw byte stream into a structured NumPy array
    # Parse the stdout byte buffer into a float32 NumPy array and return it with the sample rate.
    return np.frombuffer(stdout, dtype=np.float32), target_sr


# Define a function to resample an in-memory audio array using FFmpeg.
def _resample_audio_ffmpeg(audio_array, orig_sr, target_sr=16000):
    """
    Resamples an existing NumPy audio array in memory using FFmpeg via a stdin pipe.
    
    This is used when an API or UI passes an already-loaded NumPy array, but the 
    sample rate doesn't match the 16kHz required by the acoustic model.
    """
    # Define the FFmpeg command for reading from stdin and writing to stdout.
    command = [
        # Base FFmpeg command.
        'ffmpeg',
        # Suppress standard output logs.
        '-v', 'quiet',
        '-f', 'f32le',          # Tell FFmpeg the incoming data is raw float32
        '-ar', str(orig_sr),    # State the original sample rate
        '-ac', '1',             # State the original channel count (Mono)
        '-i', 'pipe:0',         # Tell FFmpeg to read the input from stdin
        '-f', 'f32le',          # Tell FFmpeg the output should be raw float32
        # Specify the audio codec for the output.
        '-acodec', 'pcm_f32le',
        # Specify the output channel count (Mono).
        '-ac', '1',
        '-ar', str(target_sr),  # The new target sample rate
        'pipe:1'                # Tell FFmpeg to write output to stdout
    ]
    
    # Open the process and pipe our existing NumPy array bytes into stdin
    # Start the FFmpeg process, mapping stdin, stdout, and stderr.
    process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    # Write the numpy array bytes to stdin and capture the output.
    stdout, stderr = process.communicate(input=audio_array.tobytes())
    
    # Handle potential conversion errors
    # Check if the process exited with a non-zero status code.
    if process.returncode != 0:
        # Raise a RuntimeError with the decoded stderr message.
        raise RuntimeError(f"FFmpeg resample failed: {stderr.decode('utf-8', errors='ignore')}")
        
    # Convert back from bytes to a NumPy array
    # Parse the stdout byte buffer into a float32 NumPy array and return it.
    return np.frombuffer(stdout, dtype=np.float32)


# Define the main pipeline processing function.
def process_audio(
    # The audio input data parameter.
    audio_data,
    # The acoustic model name parameter, defaulting to "Base".
    model_name="Base"
):
    """
    The main execution wrapper for the transcription and matching pipeline.
    
    Args:
        audio_data: Either a file path (string) or a tuple containing (sample_rate, numpy_array).
        model_name: The target FastConformer model to use (default: "Base").
        
    Returns:
        JSON structure containing highly precise, Uthmani-aligned Quranic text with timestamps.
    """
    # Clear any residual state from previous requests.
    # Call the reset function to clean up globally cached variables in the module.
    _reset_request_state()

    # Fast-fail if no data was provided.
    # Check if the audio_data parameter is None.
    if audio_data is None:
        # Return an empty list if there's no data.
        return []

    # Print a decorative separator line.
    print(f"\n{'='*60}")
    # Print the processing message.
    print(f"Processing audio with acoustic sliding window")
    # Print the execution settings.
    print(f"Settings: device=CPU")
    # Print a closing decorative separator line.
    print(f"{'='*60}")

    # Initialize a metrics tracker to monitor performance across pipeline stages.
    # Create a new ProfilingData object.
    profiling = ProfilingData()
    # Record the current wall-clock time for the start of the pipeline.
    pipeline_start = time.time()

    # Step 1: Handle Audio Ingestion & Normalization
    # Check if the audio_data provided is a string (a file path).
    if isinstance(audio_data, str):
        # We received a file path. We won't load the file into memory here.
        # Instead, we pass the path directly to `run_asr_cpu` so it can stream it block-by-block.
        # Assign the file path directly to the audio variable.
        audio = audio_data
        # Set the sample rate to the default 16000Hz.
        sample_rate = 16000
        # Print a profiling log indicating disk streaming.
        print(f"[PROFILE] Streaming audio directly from disk via FFmpeg pipe")
    # Execute this block if the audio data is not a string (i.e., it's a tuple).
    else:
        # We received raw audio data in memory (from an API call or another script).
        # Unpack the tuple into sample_rate and audio array.
        sample_rate, audio = audio_data

        # Normalize 16-bit integer PCM to float32 (-1.0 to 1.0)
        # Check if the data type is 16-bit integer.
        if audio.dtype == np.int16:
            # Convert to float32 and divide by the max int16 value.
            audio = audio.astype(np.float32) / 32768.0
        # Normalize 32-bit integer PCM to float32
        # Check if the data type is 32-bit integer.
        elif audio.dtype == np.int32:
            # Convert to float32 and divide by the max int32 value.
            audio = audio.astype(np.float32) / 2147483648.0

        # If the audio is stereo (2 channels) or more, average them down to mono
        # Check if the array has more than one dimension.
        if len(audio.shape) > 1:
            # Calculate the mean across the channel axis to create a mono track.
            audio = audio.mean(axis=1)

        # If the sample rate isn't 16000Hz, we must resample it. FastConformer strictly requires 16kHz.
        # Check if the sample rate differs from 16000Hz.
        if sample_rate != 16000:
            # Record the start time of the resampling process.
            resample_start = time.time()
            # Call the FFmpeg resampler function.
            audio = _resample_audio_ffmpeg(audio, orig_sr=sample_rate, target_sr=16000)
            # Calculate the time taken and store it in the profiling object.
            profiling.resample_time = time.time() - resample_start
            # Print a detailed log of the resampling duration and specs.
            print(f"[PROFILE] Resampling {sample_rate}Hz -> 16000Hz took {profiling.resample_time:.3f}s (audio length: {len(audio)/16000:.1f}s, res_type=FFMPEG_PIPE)")
            # Update the sample rate variable to the new rate.
            sample_rate = 16000

    # Print a status message indicating the start of ASR.
    print("[STAGE] Running Acoustic Transcription...")

    # Step 2: Phase 1 (Acoustic Transcription via VAD)
    # Record the start time of the ASR process.
    asr_start = time.time()
    
    # run_asr_cpu splits the audio into voice segments, transcribes them, and returns raw text blocks.
    # Call the ASR function, unpacking the returned tuple into variables.
    (regions, emissions, stage_metrics, asr_time) = run_asr_cpu(
        # Pass the pre-processed audio, sample rate, and model name.
        audio, sample_rate, model_name
    )
    
    # Calculate the elapsed wall time since the ASR phase started.
    wall_time = time.time() - asr_start

    # Move low-level ASR metrics into our global profiling tracker.
    # Call the sdk_adapt helper to copy metrics.
    sdk_adapt.metrics_to_profiling(stage_metrics, profiling)
    # Print the total wall time taken for ASR prep.
    print(f"[ASR] Pipeline prep completed in {wall_time:.2f}s")

    # Extract clean start/end time intervals from the raw VAD regions.
    # Call the sdk_adapt helper to determine raw speech state (unused variables).
    raw_speech_intervals, raw_is_complete = sdk_adapt.regions_to_state(regions)
    # Call the sdk_adapt helper to get the final cleaned intervals.
    intervals = sdk_adapt.intervals_from_regions(regions)
    
    # If no speech was detected in the entire audio file, return empty.
    # Check if the intervals list is empty.
    if not intervals:
        # Return an empty list to indicate no speech.
        return []

    # Finalize ASR profiling metrics.
    # Store the actual processing time taken by the ASR engine.
    profiling.asr_time = asr_time
    # Print the ASR completion time.
    print(f"[ASR] Transcription completed in {asr_time:.2f}s")

    # Step 3: Phase 2 (Text Matching and Dynamic Programming)
    # The raw ASR text (emissions) and timestamps (regions) are handed off to the sequence matcher.
    # The matcher forces the raw text to perfectly align with the authentic Uthmani Quranic script.
    # Call the post-ASR pipeline and store the result in json_output.
    json_output = _run_post_asr_pipeline(
        # Pass all relevant context, including audio, intervals, metrics, and raw data.
        audio, sample_rate, intervals,
        model_name, profiling, pipeline_start,
        regions=regions,
        emissions=emissions, stage_metrics=stage_metrics
    )

    # Step 4: Return the finalized, fully aligned payload.
    # Return the final JSON structure to the caller.
    return json_output