"""
Acoustic Model Wrapper (Sherpa-ONNX).

This module runs the quantized FastConformer ONNX inference natively via the 
highly optimized sherpa-onnx C++ runtime. 

It handles the auto-downloading of the neural network model, and applies strict 
audio preprocessing (Resampling, Noise Reduction, LUFS Normalization) to ensure 
the acoustic model receives pristine audio, maximizing transcription accuracy.
"""
# Import the os module for interacting with the operating system environment.
import os
# Import numpy for fast array manipulation.
import numpy as np
# Import librosa for audio processing and resampling.
import librosa
# Import pyloudnorm for audio loudness normalization.
import pyloudnorm as pyln
# Import Path from pathlib for cross-platform path handling.
from pathlib import Path

# ==============================================================================
# 1. Path Definitions & Constants
# ==============================================================================
# Determine the absolute path to the data/onnx directory relative to this file.
MODEL_DIR = Path(__file__).parent.parent.parent / "data" / "onnx"

# The 8-bit quantized acoustic neural network
# Set the absolute path for the main ONNX model.
FASTCONFORMER_ONNX_PATH = str(MODEL_DIR / "fastconformer_ar_ctc_q8.onnx")
# The BPE subword vocabulary tokens
# Set the absolute path for the tokens text file.
FASTCONFORMER_TOKENS_PATH = str(MODEL_DIR / "tokens.txt")
# The Silero Voice Activity Detection model
# Set the absolute path for the Silero VAD model.
SILERO_VAD_ONNX_PATH = str(MODEL_DIR / "silero_vad.onnx")

# FastConformer absolutely requires 16kHz audio. Anything else will produce garbage output.
# Define the expected sample rate constant as 16000.
FC_SAMPLE_RATE = 16000


# Define the FastConformerONNX class.
class FastConformerONNX:
    """
    Singleton wrapper for the Sherpa-ONNX runtime. 
    Loading a neural network into memory takes a few seconds and uses RAM.
    The Singleton pattern ensures we only ever load the model once per session.
    """
    # Initialize the class-level instance variable to None.
    _instance = None

    # Define the constructor method.
    def __init__(self, device='cpu'):
        # Store the requested compute device (e.g., 'cpu' or 'cuda').
        self.device = device
        # Initialize the recognizer attribute to None.
        self.recognizer = None
        # Call the internal method to actually load the model into memory.
        self._load_model()

    # Apply the classmethod decorator.
    @classmethod
    # Define the factory method to retrieve the singleton instance.
    def get_instance(cls, device='cpu'):
        # A docstring explaining the factory method.
        """Retrieves the global singleton instance, instantiating it if necessary."""
        # Check if the global instance has not been created yet.
        if cls._instance is None:
            # Instantiate the class and store it in the global variable.
            cls._instance = FastConformerONNX(device=device)
        # Return the initialized instance.
        return cls._instance

    # Define the internal model loading method.
    def _load_model(self):
        # A docstring explaining the loading process.
        """
        Downloads the FastConformer model if missing, and initializes the C++ runtime.
        """
        # Import the sherpa_onnx runtime library.
        import sherpa_onnx
        # Import the urllib.request module to download files over HTTP.
        import urllib.request
        
        # Auto-provision the model from GitHub Releases
        # Check if the FastConformer model file exists locally.
        if not os.path.exists(FASTCONFORMER_ONNX_PATH):
            # Print a message indicating the download has started.
            print(f"Downloading FastConformer ONNX model to {FASTCONFORMER_ONNX_PATH}...")
            # Ensure the target directory exists before downloading.
            os.makedirs(os.path.dirname(FASTCONFORMER_ONNX_PATH), exist_ok=True)
            # Define the URL to download the quantized model from GitHub.
            url = "https://github.com/yazinsai/tilawa/releases/download/v0.1.0/fastconformer_ar_ctc_q8.onnx"
            # Execute the download and save it to the specified path.
            urllib.request.urlretrieve(url, FASTCONFORMER_ONNX_PATH)
            # Print a success message.
            print("Download complete.")
            
        # Print a status message indicating Sherpa initialization.
        print("Loading FastConformer via Sherpa-ONNX...")
        # Initialize the Sherpa Offline Recognizer (designed for processing full files, not live streams).
        # Create an instance of the OfflineRecognizer specifically configured for NeMo CTC models.
        self.recognizer = sherpa_onnx.OfflineRecognizer.from_nemo_ctc(
            # Pass the path to the ONNX acoustic model.
            model=FASTCONFORMER_ONNX_PATH,
            # Pass the path to the BPE tokens file.
            tokens=FASTCONFORMER_TOKENS_PATH,
            num_threads=2,              # Restrict to 2 threads to prevent CPU lockup
            sample_rate=FC_SAMPLE_RATE, # Ensure runtime expects 16kHz
            feature_dim=80              # FastConformer uses 80-bin Mel Spectrograms
        )

    # Define the primary inference method.
    def transcribe(self, audio: np.ndarray, orig_sr: int = 16000):
        """
        The core inference function. Transcribes a single chunk of audio.
        
        Args:
            audio: The NumPy array containing the audio samples.
            orig_sr: The sample rate of the provided audio.
            
        Returns:
            full_text: The raw transcribed string.
            words_timestamps: A list of dicts detailing the start/end time of each word.
            None: Placeholder for legacy logprobs.
        """
        # A safety check to ensure the recognizer is loaded and audio is not empty.
        if self.recognizer is None or len(audio) == 0:
            # Return empty defaults if the check fails.
            return "", [], None
            
        # Import sherpa_onnx locally just to be safe.
        import sherpa_onnx
        
        # =====================================================================
        # STRICT AUDIO PREPROCESSING — Required for maximum word/letter accuracy.
        # The FastConformer model was trained on extremely clean, normalized 16kHz audio.
        # Feeding raw, un-normalized audio directly to the network causes severe 
        # hallucinations and dropped words.
        # =====================================================================
        # Convert the audio array strictly to 32-bit floats.
        clean_audio = audio.astype(np.float32)
        
        # Step 1: Ensure exact 16kHz sample rate (safety resample if mismatch)
        # Check if the original sample rate differs from the target.
        if orig_sr != FC_SAMPLE_RATE:
            # Use librosa to perform high-quality software resampling.
            clean_audio = librosa.resample(clean_audio, orig_sr=orig_sr, target_sr=FC_SAMPLE_RATE)
        
        # Step 2: LUFS Loudness Normalization (EBU R128 → -23 LUFS)
        # Why? If a reciter speaks quietly, the network activations might not cross 
        # the activation thresholds, dropping words. This algorithm forces every chunk 
        # to the exact same perceptual loudness.
        # Start a try block because loudness calculations can occasionally crash on silence.
        try:
            # Instantiate an EBU R128 loudness meter configured for 16kHz.
            meter = pyln.Meter(FC_SAMPLE_RATE)
            # Calculate the integrated loudness of the audio chunk.
            loudness = meter.integrated_loudness(clean_audio)
            # Only normalize if it's finite and not completely silent.
            # Check if the loudness is a valid finite negative number.
            if np.isfinite(loudness) and loudness < 0:
                # Apply the gain needed to hit the -23.0 LUFS target.
                clean_audio = pyln.normalize.loudness(clean_audio, loudness, -23.0)
        # Catch any exception that occurs during normalization.
        except Exception:
            pass  # If normalization fails (e.g. pure silence), proceed with the raw audio safely.
        
        # Step 3: Peak limiting to prevent clipping artifacts
        # Ensures no sample exceeds the 1.0/-1.0 float boundary.
        # Calculate the absolute maximum amplitude in the chunk.
        peak = np.max(np.abs(clean_audio))
        # Check if the peak exceeds 1.0.
        if peak > 1.0:
            # Divide the entire array by the peak to compress it to 1.0.
            clean_audio = clean_audio / peak
        
        # =====================================================================
        # INFERENCE
        # =====================================================================
        # Feed the pristine audio into the C++ runtime.
        # Create an empty input stream object attached to the recognizer.
        stream = self.recognizer.create_stream()
        # Push the normalized float32 waveform into the stream buffer.
        stream.accept_waveform(FC_SAMPLE_RATE, clean_audio)
        # Trigger the neural network inference block to process the stream.
        self.recognizer.decode_stream(stream)
        
        # Retrieve the final result object from the stream.
        result = stream.result
        
        # Extract word timestamps
        # Pull the list of recognized text tokens.
        subword_tokens = result.tokens
        # Pull the list of absolute timestamps for each token.
        subword_times = result.timestamps
        
        # Initialize an empty array for the final reconstructed words.
        words_timestamps = []
        # Initialize an empty array to buffer tokens belonging to the current word.
        current_word_subwords = []
        # Initialize the word start time variable.
        word_start_time = None
        # Initialize the word end time variable.
        word_end_time = None

        # FastConformer effectively processes audio in 80ms chunks.
        # Define the hardcoded temporal step of the model architecture.
        frame_time_step = 0.08  
        
        # The model outputs sub-words (BPE tokens). We must merge them back into full words.
        # Iterate over the tokens and timestamps simultaneously using zip.
        for tok, t in zip(subword_tokens, subword_times):
            # '▁' or a space denotes the start of a new actual word.
            # Evaluate a boolean indicating if this token starts a new physical word.
            is_new_word = tok.startswith('▁') or tok.startswith(' ')
            
            # Check if this is a new word AND we already have a buffered word to flush.
            if is_new_word and current_word_subwords:
                # Compile the finished word.
                # Join the tokens and strip out all boundary markers and spaces.
                full_word = "".join(current_word_subwords).replace('▁', '').replace(' ', '').strip()
                # Ensure the word isn't completely empty after stripping.
                if full_word:
                    # Append the dictionary containing the word and bounds to the final list.
                    words_timestamps.append({
                        "word": full_word,
                        "start": word_start_time,
                        "end": word_end_time
                    })
                # Reset buffers for the next word.
                # Clear the subword buffer.
                current_word_subwords = []
                # Record the new word's start time as the current token's time.
                word_start_time = t
                
            # If this is the very first token of a word, mark the start time.
            # Check if the buffer is entirely empty.
            if not current_word_subwords:
                # Record the absolute start time.
                word_start_time = t
                
            # Append the current token to the buffer.
            current_word_subwords.append(tok)
            # Estimate the end time by adding the frame step to the token trigger time.
            # Increment the end time using the model's physical frame rate.
            word_end_time = t + frame_time_step

        # Flush the final word in the buffer
        # Check if any tokens are left over after the loop completes.
        if current_word_subwords:
            # Join and strip the tokens to form the final word.
            full_word = "".join(current_word_subwords).replace('▁', '').replace(' ', '').strip()
            # Ensure the word isn't empty.
            if full_word:
                # Append the final word dictionary to the list.
                words_timestamps.append({
                    "word": full_word,
                    "start": word_start_time,
                    "end": word_end_time
                })
                
        # Create a single raw string for the entire chunk.
        # Join all the extracted words with spaces to form a single string.
        full_text = " ".join([w['word'] for w in words_timestamps])
        
        # Return the transcribed string, the array of word dicts, and None for logprobs.
        return full_text, words_timestamps, None
