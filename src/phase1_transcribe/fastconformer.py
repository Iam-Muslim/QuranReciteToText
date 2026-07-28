"""
Acoustic Model Wrapper (ONNXRuntime).

This module runs the quantized FastConformer ONNX inference natively via onnxruntime. 
It uses kaldi_native_fbank for feature extraction to match Sherpa-ONNX's Mel accuracy,
and exposes the raw logprobs for downstream processing.

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
# The index of the blank token used by the CTC model
# Define the integer ID representing the blank token.
BLANK_ID = 1024
# FastConformer effectively processes audio in 80ms chunks (due to 8x subsampling on 10ms Kaldi frames)
# Define the temporal step of the model architecture.
FRAME_TIME_STEP = 0.08

# Define the FastConformerONNX class.
class FastConformerONNX:
    """
    Singleton wrapper for the ONNXRuntime. 
    Loading a neural network into memory takes a few seconds and uses RAM.
    The Singleton pattern ensures we only ever load the model once per session.
    """
    # Initialize the class-level instance variable to None.
    _instance = None

    # Define the constructor method.
    def __init__(self, device='cpu'):
        # Store the requested compute device (e.g., 'cpu' or 'cuda').
        self.device = device
        # Initialize the session attribute to None.
        self.session = None
        # Initialize the vocabulary array to an empty list.
        self.vocab = []
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
        Downloads the FastConformer model if missing, and initializes ONNXRuntime.
        """
        # Import the onnxruntime runtime library.
        import onnxruntime as ort
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
            
        # Print a status message indicating ONNXRuntime initialization.
        print("Loading FastConformer via ONNXRuntime...")
        
        # Initialize ONNXRuntime session
        # Create an instance of the ONNX SessionOptions.
        sess_opts = ort.SessionOptions()
        # Restrict intra-op threads to 2 to prevent CPU lockup during matrix multiplications.
        sess_opts.intra_op_num_threads = 2
        # Restrict inter-op threads to 2 to prevent CPU lockup.
        sess_opts.inter_op_num_threads = 2
        # Instantiate the InferenceSession with the model path and options.
        self.session = ort.InferenceSession(FASTCONFORMER_ONNX_PATH, sess_opts)

        # Load vocabulary so we can manually decode the integer predictions back to Arabic text
        # Open the tokens text file in read mode with UTF-8 encoding.
        with open(FASTCONFORMER_TOKENS_PATH, "r", encoding="utf-8") as f:
            # Each line is format: 'token index' (e.g. 'ة 1'). We rsplit to grab just the token.
            # Parse the lines, split from the right, extract the token, and store in self.vocab.
            self.vocab = [line.strip("\r\n").rsplit(" ", 1)[0] for line in f.readlines() if line.strip("\r\n")]

    # Define the primary inference method.
    def transcribe(self, audio: np.ndarray, orig_sr: int = 16000):
        # A docstring explaining the method.
        """
        The core inference function. Transcribes a single chunk of audio.
        
        Args:
            audio: The NumPy array containing the audio samples.
            orig_sr: The sample rate of the provided audio.
            
        Returns:
            full_text: The raw transcribed string.
            words_timestamps: A list of dicts detailing the start/end time of each word.
            logprobs: The raw log-probabilities matrix from the model.
        """
        # A safety check to ensure the session is loaded and audio is not empty.
        if self.session is None or len(audio) == 0:
            # Return empty defaults if the check fails.
            return "", [], None
            
        # Import the kaldi_native_fbank library for feature extraction.
        import kaldi_native_fbank as knf
        
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
            # If normalization fails (e.g. pure silence), proceed safely.
            pass
        
        # Step 3: Peak limiting to prevent clipping artifacts
        # Ensures no sample exceeds the 1.0/-1.0 float boundary.
        # Calculate the absolute maximum amplitude in the chunk.
        peak = np.max(np.abs(clean_audio))
        # Check if the peak exceeds 1.0.
        if peak > 1.0:
            # Divide the entire array by the peak to compress it to 1.0.
            clean_audio = clean_audio / peak
        
        # =====================================================================
        # FEATURE EXTRACTION (Kaldi Fbank)
        # =====================================================================
        # Configure Kaldi Mel Filterbanks exactly how Sherpa-ONNX does it
        opts = knf.FbankOptions()
        opts.frame_opts.samp_freq = FC_SAMPLE_RATE
        opts.mel_opts.num_bins = 80
        
        # Sherpa-ONNX exact NeMo defaults
        opts.frame_opts.dither = 0.0
        opts.frame_opts.snip_edges = False
        opts.frame_opts.remove_dc_offset = False
        opts.frame_opts.window_type = "hann"
        opts.mel_opts.low_freq = 0.0
        opts.mel_opts.high_freq = 0.0
        opts.frame_opts.preemph_coeff = 0.97
        opts.frame_opts.frame_shift_ms = 10.0
        opts.frame_opts.frame_length_ms = 25.0
        opts.mel_opts.is_librosa = True
        
        fbank = knf.OnlineFbank(opts)
        fbank.accept_waveform(FC_SAMPLE_RATE, clean_audio.tolist())
        fbank.input_finished()
        
        feats = []
        for i in range(fbank.num_frames_ready):
            feats.append(fbank.get_frame(i))
        feats = np.array(feats)
        
        if feats.shape[0] == 0:
            return "", [], None
            
        # NeMo Per-Feature Normalization exactly as implemented in sherpa-onnx/csrc/math.cc
        mean = np.mean(feats, axis=0, keepdims=True)
        mean_sq = np.mean(np.square(feats), axis=0, keepdims=True)
        var = np.maximum(mean_sq - np.square(mean), 0.0)
        inv_std = 1.0 / (np.sqrt(var) + 1e-5)
        feats_norm = (feats - mean) * inv_std
        
        # Transpose for ONNX expected shape: [batch, feature_dim, frames]
        # Transpose the matrix and expand dimensions to add a batch size of 1.
        feats_in = np.expand_dims(feats_norm.T, axis=0)
        # Create a tensor representing the sequence length for the ONNX inputs.
        seq_len = np.array([feats_in.shape[2]], dtype=np.int64)
        
        # =====================================================================
        # INFERENCE
        # =====================================================================
        # Prepare the input dictionary for the ONNX inference session.
        inputs = {
            # Cast the features to float32 and assign to the 'audio_signal' input.
            "audio_signal": feats_in.astype(np.float32),
            # Assign the sequence length to the 'length' input.
            "length": seq_len
        }
        # Execute the model inference and retrieve the 'logprobs' output.
        outputs = self.session.run(["logprobs"], inputs)
        # Extract the log probabilities tensor from the model outputs.
        logprobs = outputs[0]
        
        # =====================================================================
        # CTC DECODING & TIMESTAMPING
        # =====================================================================
        # Grab the highest probability token index for every frame
        # Perform argmax along the vocabulary dimension to get the predicted token indices.
        pred_idx = np.argmax(logprobs[0], axis=-1)
        
        # Initialize an empty list for the predicted subword tokens.
        subword_tokens = []
        # Initialize an empty list for the temporal timestamps of each subword.
        subword_times = []
        
        # Standard CTC reduction: remove blank tokens and collapse consecutive duplicates
        # Initialize a variable to keep track of the previously predicted token.
        prev_idx = -1
        # Iterate over the predicted token indices along with their frame index.
        for frame_idx, idx in enumerate(pred_idx):
            # Check if the token is not a blank and is not a duplicate of the previous token.
            if idx != BLANK_ID and idx != prev_idx:
                # Map the integer index to the actual string token from the vocabulary.
                token = self.vocab[idx]
                # Append the string token to the list.
                subword_tokens.append(token)
                # Calculate and append the absolute timestamp of the token based on the frame index.
                subword_times.append(frame_idx * FRAME_TIME_STEP)
            # Update the previous token index tracker.
            prev_idx = idx

        # Reconstruct full words from subword (BPE) tokens
        # Initialize an empty array for the final reconstructed words.
        words_timestamps = []
        # Initialize an empty array to buffer tokens belonging to the current word.
        current_word_subwords = []
        # Initialize the word start time variable.
        word_start_time = None
        # Initialize the word end time variable.
        word_end_time = None

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
            word_end_time = t + FRAME_TIME_STEP

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
        
        # Return the transcribed string, the array of word dicts, and the raw logprobs.
        return full_text, words_timestamps, logprobs
