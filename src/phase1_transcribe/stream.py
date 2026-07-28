"""
ASR Runtime — Orchestrates acoustic inference on CPU using Silero VAD,
streaming audio efficiently via FFmpeg pipes to prevent high RAM usage.

This module splits long audio files into short, speech-only chunks using 
Voice Activity Detection (VAD). This completely eliminates the memory overhead 
of traditional overlapping-window approaches, and allows hours of audio to be 
processed on a standard CPU.
"""
# Import time for performance benchmarking.
import time
# Import subprocess to invoke the FFmpeg executable.
import subprocess
# Import json for saving debugging files.
import json
# Import numpy for array manipulation.
import numpy as np
# Import os to manage environment variables.
import os
# Import urllib.request to download missing models.
import urllib.request

# ==============================================================================
# 1. CPU Thread Throttling
# ==============================================================================
# FastConformer relies on massive matrix multiplications under the hood (via PyTorch/ONNX).
# If left unchecked, these libraries will aggressively spin up threads for EVERY CPU core,
# causing 100% CPU lockup and thermal throttling. We strictly limit them to 2 threads.
# Restrict OpenMP threads to 2.
os.environ["OMP_NUM_THREADS"] = "2"
# Restrict Intel MKL threads to 2.
os.environ["MKL_NUM_THREADS"] = "2"
# Restrict OpenBLAS threads to 2.
os.environ["OPENBLAS_NUM_THREADS"] = "2"

# Import specific schemas from the qua_sdk library.
from qua_sdk.schemas import Audio, Region, Regions, Emissions
# Import the text normalization function.
from src.phase2_matching.normalize import normalize_arabic


# Define a placeholder function for resetting state.
def _reset_request_state():
    # A docstring explaining the placeholder.
    """Placeholder for any state reset required between API calls."""
    # Do nothing.
    pass


# Define a function to ensure the VAD model exists.
def _ensure_silero_vad_downloaded(vad_path: str):
    """
    Auto-downloads the Silero VAD model if it doesn't exist locally.
    This ensures the pipeline remains plug-and-play.
    """
    # Check if the file doesn't exist at the given path.
    if not os.path.exists(vad_path):
        # Print a message indicating the download has started.
        print(f"Downloading silero_vad.onnx to {vad_path}...")
        # Create the necessary parent directories if they don't exist.
        os.makedirs(os.path.dirname(vad_path), exist_ok=True)
        # Define the direct URL to the model on GitHub.
        url = "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/silero_vad.onnx"
        # Download the file using urllib.
        urllib.request.urlretrieve(url, vad_path)
        # Print a success message.
        print("Download complete.")


# ==============================================================================
# 2. Main Transcription Loop
# ==============================================================================
# Define the core transcription engine function.
def run_asr_cpu(audio_input, sample_rate, model_name="Base"):
    """
    VAD-Based Inference (Forced CPU Mode).
    
    1. Reads audio (either via FFmpeg pipe from disk, or from RAM).
    2. Feeds the audio block-by-block into the Silero VAD engine.
    3. When VAD detects a complete spoken phrase, it sends that exact audio chunk 
       to FastConformer for transcription.
    4. Aggregates the text and timestamps.
    """
    audio_dur = 0.0
    # Import schemas locally to avoid circular dependencies if any exist.
    from qua_sdk.schemas import Emissions, Region, Regions
    # Import the FastConformer singleton and model paths.
    from src.phase1_transcribe.fastconformer import FastConformerONNX, SILERO_VAD_ONNX_PATH
    # Import sherpa_onnx for the VAD engine.
    import sherpa_onnx
    
    # Force the device parameter to CPU to ensure no rogue CUDA allocations occur.
    device = "cpu"  
    # Record the starting timestamp for the lease processing time.
    t_lease_start = time.time()
    
    # Step 1: Ensure VAD model is present.
    # Call the helper function to download the model if missing.
    _ensure_silero_vad_downloaded(SILERO_VAD_ONNX_PATH)
    
    # Step 2: Configure the Silero VAD engine.
    # Instantiate an empty VadModelConfig object.
    config = sherpa_onnx.VadModelConfig()
    # Set the path to the VAD model file.
    config.silero_vad.model = SILERO_VAD_ONNX_PATH
    # Set the expected sample rate (must match audio input).
    config.sample_rate = sample_rate
    
    # Quran-specific VAD tuning — ultra-sensitive to catch soft Arabic endings (ع,ح,ه,خ)
    # and extended vowels (مد). Optimized for maximum word/letter accuracy.
    # Set the minimum silence duration to 0.8 seconds to avoid splitting mid-breath.
    config.silero_vad.min_silence_duration = 0.8   # 0.8s — don't split mid-Waqf pauses
    # Set the activation threshold to a low 0.15 to catch quiet tails.
    config.silero_vad.threshold = 0.15             # 0.15 — catch soft consonants & vowel tails
    # Set the minimum speech duration to 0.15 seconds to allow very short words.
    config.silero_vad.min_speech_duration = 0.15   # 0.15 — keep very short Ayahs (طه, يس)
    # Set the maximum speech duration to 30.0 seconds to prevent massive chunks.
    config.silero_vad.max_speech_duration = 30.0   # 30s — prevent mega-chunks exhausting model context
    
    # Initialize the VAD engine with a 30-second context buffer.
    # Instantiate the VoiceActivityDetector using the constructed config.
    vad = sherpa_onnx.VoiceActivityDetector(config, buffer_size_in_seconds=30.0)
    # Extract the block window size required by the VAD model (usually 512 samples).
    window_size = config.silero_vad.window_size
    
    # Initialize the FastConformer acoustic model singleton.
    # Retrieve the loaded instance of the FastConformer engine.
    fc = FastConformerONNX.get_instance(device=device)

    # Master arrays to hold the final results.
    # Initialize an empty list for Region objects.
    regions_list = []
    # Initialize an empty list for token arrays.
    tokens = []
    # Initialize an empty list for raw debugging text.
    raw_transcriptions = []
    # Initialize an empty list for word timing dictionaries.
    asr_words_list = []
    # Initialize an empty list for the raw logprobs from the acoustic model.
    logprobs_list = []
    
    # Record the timestamp when the actual transcription loop starts.
    t_asr_start = time.time()
    # Initialize the chunk index counter to 0.
    chunk_idx = 0

    # Define an inner callback function to process individual speech segments.
    def process_speech_segment(segment, get_real_audio_fn):
        """
        Inner callback: Executed every time VAD spits out a valid speech segment.
        Extracts the audio, passes it to FastConformer, and records the text/timings.
        """
        nonlocal chunk_idx
        start_sec = segment.start / sample_rate
        
        # Calculate and emit progress (0-100)
        if audio_dur > 0:
            pct = min(100.0, ((start_sec + len(segment.samples)/sample_rate) / audio_dur) * 100.0)
            print(f"[PROGRESS] Transcribing {pct:.1f}%")

        # We fetch the *actual* audio for this segment, plus a tiny bit of pre-roll 
        # (context) so the model doesn't clip the first syllable.
        # Call the injected function to pull the audio array from memory/disk buffers.
        chunk_audio, actual_preroll_sec = get_real_audio_fn(segment.start, len(segment.samples))
        
        # Guard clause: check if the returned audio is empty.
        if len(chunk_audio) == 0:
            # Abort processing if empty.
            return

        # Perform the actual heavy-lifting transcription.
        # Pass the extracted audio to the FastConformer engine.
        text, word_timestamps, logprobs = fc.transcribe(chunk_audio, orig_sr=sample_rate)
        
        # Append the raw text to the debugging list.
        raw_transcriptions.append({
            # Store the current 1-based chunk number.
            "chunk": chunk_idx + 1,
            # Store the absolute start time of the chunk.
            "chunk_start_time_seconds": start_sec,
            # Store the raw text output.
            "raw_text": text,
        })
        
        # Check if the transcription returned any actual words.
        if word_timestamps:
            # The ASR model returns timestamps relative to the start of the tiny chunk.
            # We must mathematically adjust them to be absolute times in the full audio file.
            # Iterate through each word dictionary in the list.
            for w in word_timestamps:
                # Subtract the pre-roll, add the segment's absolute start time.
                # Calculate the absolute start time, clamping at 0.0 to avoid negatives.
                w['start'] = max(0.0, w['start'] - actual_preroll_sec + start_sec)
                # Calculate the absolute end time, clamping at 0.0.
                w['end']   = max(0.0, w['end'] - actual_preroll_sec + start_sec)
                
            # Filter out overlapping words caught in the preroll audio
            if regions_list:
                prev_end = regions_list[-1].end_s
                filtered_words = [w for w in word_timestamps if w['start'] >= prev_end - 0.05]
                if not filtered_words:
                    chunk_idx += 1
                    return
                word_timestamps = filtered_words

            # Reconstruct the sentence by joining the word strings.
            chunk_text = " ".join([w['word'] for w in word_timestamps])
            # Determine the absolute start time of the first word.
            abs_start_time = word_timestamps[0]['start']
            # Determine the absolute end time of the last word.
            abs_end_time   = word_timestamps[-1]['end']

            # Record the absolute boundary of this spoken phrase.
            # Append a new Region object to the master list.
            regions_list.append(Region(start_s=abs_start_time, end_s=abs_end_time))
            
            # Normalize the Arabic text (remove diacritics) for the DP matcher.
            # Call the normalizer on the raw text.
            norm_text = normalize_arabic(chunk_text)
            # Append the characters as a list, plus a space to denote word boundaries, to the tokens array.
            tokens.append(list(norm_text) + [' '])
            
            # Append the word timestamps and start offset to the ASR words list.
            asr_words_list.append((word_timestamps, start_sec))
            
            # Append the logprobs matrix and its actual start offset.
            # The logprobs correspond to the chunk_audio which includes actual_preroll_sec,
            # so its true start time is start_sec - actual_preroll_sec.
            actual_logprobs_start = max(0.0, start_sec - actual_preroll_sec)
            logprobs_list.append((logprobs, actual_logprobs_start))
            
        # Increment the global chunk counter.
        chunk_idx += 1


    # ==============================================================================
    # 3. Execution Branches (Disk Stream vs. Memory Buffer)
    # ==============================================================================
    # Check if the provided audio input is a file path string.
    if isinstance(audio_input, str):
        # Branch A: We were given a file path. Use FFmpeg to stream it directly 
        # from disk to save RAM.
        
        # Probe the audio duration first.
        # Build the ffprobe command to extract the total duration in seconds.
        probe_cmd = ['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1', audio_input]
        # Start a try block to catch execution errors.
        try:
            # Execute ffprobe, capture stdout, decode it, and cast to float.
            audio_dur = float(subprocess.check_output(probe_cmd).decode('utf-8').strip())
        # Catch FileNotFoundError if ffprobe is missing from the system.
        except FileNotFoundError:
            # Raise a critical runtime error instructing the user to install FFmpeg.
            raise RuntimeError("ffprobe not found. Please install FFmpeg and ensure it is in your system PATH.")
        # Catch any other exception (e.g. malformed audio file).
        except Exception:
            # Fallback to a duration of 0.0.
            audio_dur = 0.0

        # Start the streaming pipe.
        # Define the FFmpeg command to decode audio and write raw floats to stdout.
        command = [
            'ffmpeg', '-v', 'quiet',
            '-i', audio_input,
            '-f', 'f32le', '-acodec', 'pcm_f32le', '-ac', '1', '-ar', str(sample_rate),
            'pipe:1'
        ]
        # Start a try block for the subprocess creation.
        try:
            # Spawn the FFmpeg process, redirecting stdout to a pipe and trashing stderr.
            process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        # Catch FileNotFoundError if ffmpeg is missing.
        except FileNotFoundError:
            # Raise a critical runtime error.
            raise RuntimeError("ffmpeg not found. Please install FFmpeg and ensure it is in your system PATH.")
        
        # Define the amount of audio to read per iteration (0.5 seconds).
        block_duration = 0.5
        # Calculate the number of samples in that block.
        chunk_samples = int(block_duration * sample_rate)
        # Define the size of a single 32-bit float in bytes (4).
        bytes_per_sample = 4
        # Calculate the total number of bytes to read per iteration.
        chunk_bytes = chunk_samples * bytes_per_sample
        
        # Print a status message showing the total duration.
        print(f"\nTranscribing [{audio_dur / 60:.2f} Minutes] Audio via VAD")
        
        # Initialize an empty numpy array to buffer the incoming stream.
        pcm_buffer = np.array([], dtype=np.float32)
        
        # A rolling buffer to keep the last 60 seconds of audio in memory, 
        # so when VAD triggers, we can easily grab the chunk plus pre-roll context.
        # Initialize an empty numpy array for the context history.
        context_buffer = np.array([], dtype=np.float32)
        # Initialize a counter for the total number of samples processed.
        total_samples_read = 0
        # Calculate the absolute maximum size of the context buffer (60 seconds).
        max_context_samples = int(60.0 * sample_rate)
        
        # Define a function to extract audio specifically from the rolling context buffer.
        def get_real_audio_stream(seg_start, seg_length):
            # A docstring explaining the function.
            """Extracts audio from the rolling stream buffer."""
            # Define the amount of pre-roll context (0.5 seconds).
            preroll_samples = int(0.5 * sample_rate)   # 500ms context before speech
            # Define the amount of post-roll context (0.5 seconds).
            postroll_samples = int(0.5 * sample_rate)  # 500ms context after speech
            
            # Calculate the desired start sample, clamping at 0.
            target_start = max(0, seg_start - preroll_samples)
            # Calculate the desired end sample.
            target_end = seg_start + seg_length + postroll_samples
            
            # Determine the absolute sample index of the oldest sample in the buffer.
            context_start_idx = max(0, total_samples_read - len(context_buffer))
            
            # Calculate the relative start index within the buffer array.
            idx_start = max(0, target_start - context_start_idx)
            # Calculate the relative end index within the buffer array.
            idx_end = max(0, target_end - context_start_idx)
            
            # If the calculated end index exceeds the buffer size.
            if idx_end > len(context_buffer):
                # Clamp it to the maximum available length.
                idx_end = len(context_buffer)
                
            # Slice the numpy array to extract the requested audio.
            real_chunk = context_buffer[idx_start:idx_end]
            # Calculate the exact number of preroll samples successfully extracted.
            actual_preroll_samples = seg_start - (context_start_idx + idx_start)
            # Convert that to seconds.
            actual_preroll_sec = actual_preroll_samples / sample_rate
            
            # Return the extracted audio and the actual preroll offset.
            return real_chunk, actual_preroll_sec
        
        # Main FFmpeg read loop
        # Loop indefinitely until the pipe closes.
        while True:
            # Read a tiny chunk from the pipe
            # Read exactly chunk_bytes from the stdout pipe.
            new_bytes = process.stdout.read(chunk_bytes)
            # If the pipe returns empty bytes (EOF).
            if not new_bytes:
                # Break out of the loop.
                break
                
            # Convert the raw bytes into a float32 numpy array.
            samples = np.frombuffer(new_bytes, dtype=np.float32)
            # Append the new samples to the main VAD buffer.
            pcm_buffer = np.concatenate((pcm_buffer, samples))
            
            # Maintain the 60-second rolling buffer
            # Append the new samples to the history buffer.
            context_buffer = np.concatenate((context_buffer, samples))
            # Check if the history buffer exceeds the 60-second limit.
            if len(context_buffer) > max_context_samples:
                # Truncate the buffer to keep only the most recent samples.
                context_buffer = context_buffer[-max_context_samples:]
            # Increment the global sample counter.
            total_samples_read += len(samples)
            
            # Feed data to VAD in exact window sizes
            # Loop while the buffer contains enough data for at least one VAD frame.
            while len(pcm_buffer) >= window_size:
                # Push exactly one window of samples into the VAD engine.
                vad.accept_waveform(pcm_buffer[:window_size])
                # Remove those processed samples from the buffer.
                pcm_buffer = pcm_buffer[window_size:]
                
                # If VAD detected a segment, process it immediately!
                # This prevents memory leaks.
                # Loop while the VAD engine has detected completed speech segments in its queue.
                while not vad.empty():
                    # Process the front-most segment using our callback.
                    process_speech_segment(vad.front, get_real_audio_stream)
                    # Pop the segment off the queue.
                    vad.pop()
                        
        # After EOF, check if there are any remaining samples in the buffer.
        if len(pcm_buffer) > 0:
            # Force the VAD to process the final uneven chunk.
            vad.accept_waveform(pcm_buffer)
            
        # Drain any remaining speech after EOF
        # Command the VAD to conclude all processing and close any open segments.
        vad.flush()
        # Loop while there are remaining segments in the queue.
        while not vad.empty():
            # Process the front-most segment.
            process_speech_segment(vad.front, get_real_audio_stream)
            # Pop the segment off the queue.
            vad.pop()
            
        # Close the stdout pipe.
        process.stdout.close()
        # Send a terminate signal to FFmpeg just in case.
        process.terminate()
        # Wait for the process to exit cleanly.
        process.wait()

    # Execute this block if the input is a raw numpy array instead of a file path.
    else:
        # Branch B: The entire audio array is already in RAM.
        # Calculate the duration by dividing length by sample rate.
        audio_dur = len(audio_input) / sample_rate
        # Print a status message.
        print(f"\nTranscribing [{audio_dur / 60:.2f} Minutes] Audio via VAD")
        
        # Extract the VAD window size.
        window_size = config.silero_vad.window_size
        # Ensure the array is contiguous in memory to prevent C++ binding errors.
        samples = np.ascontiguousarray(audio_input, dtype=np.float32)
        
        # Define a function to extract audio specifically from the in-memory array.
        def get_real_audio_mem(seg_start, seg_length):
            # A docstring explaining the function.
            """Extracts audio directly from the full RAM array."""
            # Define the amount of pre-roll context (0.5 seconds).
            preroll_samples = int(0.5 * sample_rate)   # 500ms context before speech
            # Define the amount of post-roll context (0.5 seconds).
            postroll_samples = int(0.5 * sample_rate)  # 500ms context after speech
            
            # Calculate the start index, clamping to 0.
            idx_start = max(0, seg_start - preroll_samples)
            # Calculate the end index.
            idx_end = seg_start + seg_length + postroll_samples
            
            # Clamp the end index to the array length.
            if idx_end > len(audio_input):
                # Restrict to array boundary.
                idx_end = len(audio_input)
                
            # Slice the array directly to extract the chunk.
            real_chunk = audio_input[idx_start:idx_end]
            # Calculate the exact preroll samples extracted.
            actual_preroll_samples = seg_start - idx_start
            # Convert preroll samples to seconds.
            actual_preroll_sec = actual_preroll_samples / sample_rate
            # Return the chunk and the preroll time.
            return real_chunk, actual_preroll_sec
        
        # Feed the entire array into VAD block-by-block.
        # Loop while there is enough data for at least one frame.
        while len(samples) > window_size:
            # Pass exactly one window to the VAD.
            vad.accept_waveform(samples[:window_size])
            # Slice the array to remove the processed window.
            samples = samples[window_size:]
            
            # Drain any completed segments.
            while not vad.empty():
                # Process the segment.
                process_speech_segment(vad.front, get_real_audio_mem)
                # Pop the segment.
                vad.pop()
                    
        # Process the final uneven chunk if any remains.
        if len(samples) > 0:
            # Pass remaining samples.
            vad.accept_waveform(samples)
            
        # Flush the VAD to force closure of open segments.
        vad.flush()
        # Drain any final segments.
        while not vad.empty():
            # Process the segment.
            process_speech_segment(vad.front, get_real_audio_mem)
            # Pop the segment.
            vad.pop()

    # Calculate the total elapsed wall-clock time for the ASR phase.
    asr_time = time.time() - t_asr_start
    # Print the total time taken.
    print(f"Transcribing Took [{asr_time / 60:.2f} Minutes]")
    
    # Construct the final SDK structures
    # Create the Regions container using the collected region list.
    regions = Regions(regions=regions_list, audio_duration_s=audio_dur)
    # Create the Emissions container using the collected tokens.
    emissions = Emissions(tokens=tokens)

    # Save a debug log of the raw ASR text before DP alignment
    # Open the raw_transcription.json file in write mode.
    with open("raw_transcription.json", "w", encoding="utf-8") as f:
        # Dump the debugging list into the file, preserving Arabic characters and formatting.
        json.dump({"absolute_raw_transcriptions": raw_transcriptions}, f, ensure_ascii=False, indent=2)

    # Compile the stage metrics dictionary required by the pipeline.
    stage_metrics = {
        "segmentation": {}, 
        "recognition": {}, 
        "asr_words": asr_words_list,
        "logprobs": logprobs_list
    }
    # Return the 4-tuple of regions, emissions, metrics, and wall time.
    return (regions, emissions, stage_metrics, asr_time)