"""Acoustic Model Wrapper for Zipformer2 Arabic Phoneme CTC (ONNXRuntime)."""

import os
import urllib.request
from pathlib import Path
import numpy as np
import librosa
import pyloudnorm as pyln
import onnxruntime as ort
import kaldi_native_fbank as knf

MODEL_DIR = Path(__file__).parent.parent.parent / "data" / "onnx"
ZIPFORMER_ONNX_PATH = str(MODEL_DIR / "zipformer_p_arabic_v3.int8.onnx")
TOKENS_PATH = str(MODEL_DIR / "tokens.txt")

SAMPLE_RATE = 16000
BLANK_ID = 250
FRAME_TIME_STEP = 0.04  # 10ms fbank hop x 4 subsampling = 40ms per encoder frame (25 Hz)
CHUNK_LEN = 48         # decode chunk length in fbank frames (480ms)
T_LEN = 61             # total chunk window including right context in fbank frames (610ms)


class ZipformerONNX:
    """Singleton wrapper for Zipformer2 Arabic Phoneme ONNX model."""
    _instance = None

    def __init__(self, device: str = "cpu"):
        self.device = device
        self.session = None
        self.vocab = []
        self.id2token = {}
        self.token2id = {}
        self._load_model()

    @classmethod
    def get_instance(cls, device: str = "cpu") -> "ZipformerONNX":
        if cls._instance is None:
            cls._instance = ZipformerONNX(device=device)
        return cls._instance

    def _load_model(self):
        if not os.path.exists(ZIPFORMER_ONNX_PATH):
            os.makedirs(os.path.dirname(ZIPFORMER_ONNX_PATH), exist_ok=True)
            url = "https://github.com/Iam-Muslim/Natlu/releases/download/models-latest/zipformer_p_arabic_v3.int8.onnx"
            print(f"[*] Downloading Zipformer ONNX model from {url}...")
            urllib.request.urlretrieve(url, ZIPFORMER_ONNX_PATH)
            print("[*] Zipformer ONNX model downloaded successfully.")

        sess_opts = ort.SessionOptions()
        num_threads = int(os.environ.get("ONNX_NUM_THREADS", "2"))
        sess_opts.intra_op_num_threads = num_threads
        sess_opts.inter_op_num_threads = 2

        self.session = ort.InferenceSession(
            ZIPFORMER_ONNX_PATH,
            sess_opts,
            providers=['CPUExecutionProvider']
        )

        self.vocab = []
        self.id2token = {}
        self.token2id = {}
        if os.path.exists(TOKENS_PATH):
            with open(TOKENS_PATH, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip("\r\n")
                    if not line:
                        continue
                    parts = line.rsplit(" ", 1)
                    if len(parts) == 2:
                        tok, idx = parts[0], int(parts[1])
                        self.id2token[idx] = tok
                        self.token2id[tok] = idx
            max_id = max(self.id2token.keys()) if self.id2token else 250
            self.vocab = [self.id2token.get(i, "<blank>") for i in range(max_id + 1)]

    def _create_initial_states(self) -> dict:
        """Create zero-initialized cache state dict for Zipformer streaming."""
        states = {}
        for inp in self.session.get_inputs():
            shape = [1 if dim == 'N' else dim for dim in inp.shape]
            dtype = np.float32 if inp.type == 'tensor(float)' else np.int64
            states[inp.name] = np.zeros(shape, dtype=dtype)
        states['processed_lens'] = np.array([0], dtype=np.int64)
        return states

    def _extract_fbank(self, audio: np.ndarray) -> np.ndarray:
        """Extract 80-bin Kaldi Fbank features with Povey window."""
        opts = knf.FbankOptions()
        opts.frame_opts.samp_freq = SAMPLE_RATE
        opts.mel_opts.num_bins = 80
        opts.frame_opts.dither = 0.0
        opts.frame_opts.snip_edges = False
        opts.frame_opts.window_type = "povey"
        opts.frame_opts.remove_dc_offset = True
        opts.frame_opts.preemph_coeff = 0.97
        opts.mel_opts.low_freq = 20.0
        opts.mel_opts.high_freq = -400.0
        opts.frame_opts.frame_shift_ms = 10.0
        opts.frame_opts.frame_length_ms = 25.0

        fbank = knf.OnlineFbank(opts)
        fbank.accept_waveform(SAMPLE_RATE, audio.tolist())
        fbank.input_finished()

        num_frames = fbank.num_frames_ready
        if num_frames == 0:
            return np.empty((0, 80), dtype=np.float32)

        feats = np.array([fbank.get_frame(i) for i in range(num_frames)], dtype=np.float32)
        return feats

    def transcribe(
        self,
        audio: np.ndarray,
        orig_sr: int = 16000,
        safe_lufs: bool = True
    ) -> tuple[str, list[dict], np.ndarray]:
        """Transcribe an audio segment to phonemes, per-phoneme timings, and full logprobs matrix."""
        if self.session is None or len(audio) == 0:
            return "", [], np.empty((0, len(self.vocab)), dtype=np.float32)

        clean_audio = audio.astype(np.float32)

        if orig_sr != SAMPLE_RATE:
            clean_audio = librosa.resample(clean_audio, orig_sr=orig_sr, target_sr=SAMPLE_RATE)

        # Check RMS power to prevent amplifying quiet noise floor
        rms = np.sqrt(np.mean(np.square(clean_audio))) if len(clean_audio) > 0 else 0.0
        should_normalize = True
        if safe_lufs and rms < 1e-3:
            should_normalize = False

        import time
        init_start = time.time()
        
        if should_normalize:
            try:
                import warnings
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    meter = pyln.Meter(SAMPLE_RATE)
                    loudness = meter.integrated_loudness(clean_audio)
                    if np.isfinite(loudness) and loudness < 0:
                        clean_audio = pyln.normalize.loudness(clean_audio, loudness, -23.0)
            except Exception:
                pass

        norm_time = time.time()

        peak = np.max(np.abs(clean_audio)) if len(clean_audio) > 0 else 0.0
        if peak > 1.0:
            clean_audio = clean_audio / peak

        feats = self._extract_fbank(clean_audio)
        fbank_time = time.time()

        if len(feats) == 0:
            return "", [], np.empty((0, len(self.vocab)), dtype=np.float32)

        # Append right-context silence frames (~1.05s / 105 frames) so the streaming buffer
        # fully flushes all acoustic information from trailing speech.
        silence_pad_frames = 105
        silence_feats = np.zeros((silence_pad_frames, 80), dtype=np.float32)
        padded_feats = np.vstack([feats, silence_feats])

        states = self._create_initial_states()
        num_frames = len(padded_feats)
        
        all_chunk_logprobs = []
        pos = 0
        input_names = [inp.name for inp in self.session.get_inputs()]
        
        last_print_pos = 0
        import sys
        start_time = time.time()

        while pos + T_LEN <= num_frames:
            chunk = padded_feats[pos:pos + T_LEN][None, :].astype(np.float32)
            states['x'] = chunk
            outputs = self.session.run(None, states)

            chunk_lp = outputs[0][0]  # shape: [12, 251]
            all_chunk_logprobs.append(chunk_lp)

            # Carry state tensors forward
            for out_idx in range(1, len(outputs)):
                name = input_names[out_idx]
                states[name] = outputs[out_idx]

            pos += CHUNK_LEN
            
            # Safe, short progress bar that won't trigger terminal word-wrap flooding
            if pos - last_print_pos >= 2000:
                percent = (pos / num_frames) * 100
                elapsed = max(0.1, time.time() - start_time)
                speed = (pos / 100.0) / elapsed
                msg = f"\rTranscribing ({len(clean_audio)/SAMPLE_RATE:.1f}s)... {percent:.1f}% | Speed: {speed:.1f}x"
                sys.stdout.write(msg.ljust(60))
                sys.stdout.flush()
                last_print_pos = pos

        if not all_chunk_logprobs:
            return "", [], np.empty((0, len(self.vocab)), dtype=np.float32)

        full_logprobs = np.concatenate(all_chunk_logprobs, axis=0)  # shape: [T_total, 251]

        # Calculate the number of output frames corresponding to original non-padded audio
        actual_output_frames = max(1, int(np.ceil(len(feats) / 4.0)))
        total_valid_frames = min(len(full_logprobs), actual_output_frames + 4)
        valid_logprobs = full_logprobs[:total_valid_frames]

        # Greedy CTC decoding
        pred_idx = np.argmax(valid_logprobs, axis=-1)

        phonemes_timestamps = []
        prev_idx = -1
        current_run_frames = []
        current_tok_idx = -1

        def _flush_phoneme_run():
            if not current_run_frames or current_tok_idx == BLANK_ID or current_tok_idx == -1:
                return
            start_f = current_run_frames[0]
            end_f = current_run_frames[-1] + 1
            tok_str = self.id2token.get(current_tok_idx, "")
            if tok_str and tok_str != "<blank>":
                run_probs = valid_logprobs[current_run_frames]
                # Peak probability within run
                pk_rel = int(np.argmax(run_probs[:, current_tok_idx]))
                pk_frame = current_run_frames[pk_rel]
                pk_sorted = np.sort(valid_logprobs[pk_frame])[::-1]
                margin_pk = float(pk_sorted[0] - pk_sorted[1]) if len(pk_sorted) > 1 else 1.0

                phonemes_timestamps.append({
                    "phoneme": tok_str,
                    "word": tok_str,
                    "start": round(start_f * FRAME_TIME_STEP, 4),
                    "end": round(end_f * FRAME_TIME_STEP, 4),
                    "margin_peak": round(margin_pk, 4),
                })

        for f_idx, idx in enumerate(pred_idx):
            if idx == prev_idx:
                if idx != BLANK_ID:
                    current_run_frames.append(f_idx)
                continue
            _flush_phoneme_run()
            current_run_frames = [] if idx == BLANK_ID else [f_idx]
            current_tok_idx = idx
            prev_idx = idx

        _flush_phoneme_run()

        full_text = " ".join([p["phoneme"] for p in phonemes_timestamps])
        return full_text, phonemes_timestamps, valid_logprobs
