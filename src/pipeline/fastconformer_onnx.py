import os
import numpy as np
import librosa
import onnxruntime as ort
import re
import json
from pathlib import Path

try:
    import sentencepiece as spm
except ImportError:
    spm = None

# Base path for models
MODEL_DIR = Path(__file__).parent.parent.parent / "data" / "onnx-model"
FASTCONFORMER_ONNX_PATH = str(MODEL_DIR / "fastconformer-quran-ar-quantized.onnx")
FASTCONFORMER_TOKENS_PATH = str(MODEL_DIR / "vocab.json")
FASTCONFORMER_SPM_PATH = str(MODEL_DIR / "tokenizer.model")

FC_SAMPLE_RATE = 16000
FC_N_MELS = 80
FC_N_FFT = 400
FC_HOP_LENGTH = 160
FC_WIN_LENGTH = 400
FC_SUBSAMPLING_FACTOR = 8
FC_BLANK_ID = 1024

class FastConformerONNX:
    _instance = None

    def __init__(self, fast_mode=False, device='cpu'):
        self.fast_mode = fast_mode
        self.device = device
        self.session = None
        self.vocab = {}
        self.blank_id = FC_BLANK_ID
        self.spm_processor = None
        self._mel_basis = None  # cached on first use
        self._load_model()
        self._load_vocab()
        if spm is not None and os.path.exists(FASTCONFORMER_SPM_PATH):
            self.spm_processor = spm.SentencePieceProcessor(model_file=FASTCONFORMER_SPM_PATH)

    @classmethod
    def get_instance(cls, fast_mode=False, device='cpu'):
        if cls._instance is None:
            cls._instance = FastConformerONNX(fast_mode=fast_mode, device=device)
        elif cls._instance.fast_mode != fast_mode or getattr(cls._instance, 'device', 'cpu') != device:
            cls._instance = FastConformerONNX(fast_mode=fast_mode, device=device)
        return cls._instance

    def _load_model(self):
        if not os.path.exists(FASTCONFORMER_ONNX_PATH):
            print(f"ONNX model not found at {FASTCONFORMER_ONNX_PATH}")
            return
            
        providers = ['CPUExecutionProvider']
        if self.device == 'cuda':
            print("Loading FastConformer ONNX model with CUDA support...")
            providers = ['CUDAExecutionProvider'] + providers
        else:
            print("Loading FastConformer ONNX model on CPU...")
            
        opts = ort.SessionOptions()
        if self.fast_mode:
            import multiprocessing
            opts.intra_op_num_threads = min(4, multiprocessing.cpu_count())
            opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
            print(f"Fast Mode ONNX Threads: {opts.intra_op_num_threads}")
            
        self.session = ort.InferenceSession(FASTCONFORMER_ONNX_PATH, sess_options=opts, providers=providers)
        print("ONNX model loaded successfully.")

    def _load_vocab(self):
        if not os.path.exists(FASTCONFORMER_TOKENS_PATH):
            print(f"Tokens file not found at {FASTCONFORMER_TOKENS_PATH}")
            return
        with open(FASTCONFORMER_TOKENS_PATH, 'r', encoding='utf-8') as f:
            vocab_dict = json.load(f)
            for k, v in vocab_dict.items():
                self.vocab[int(k)] = v
        if self.blank_id not in self.vocab:
            self.vocab[self.blank_id] = "<blank>"

    def compute_mel_spectrogram(self, audio: np.ndarray) -> np.ndarray:
        dither = 1e-5
        dithered = audio + dither * (np.random.rand(len(audio)) * 2 - 1)
        preemphasis = 0.97
        dithered_pre = np.append(dithered[0], dithered[1:] - preemphasis * dithered[:-1])
        D = librosa.stft(
            dithered_pre,
            n_fft=FC_N_FFT,
            hop_length=FC_HOP_LENGTH,
            win_length=FC_WIN_LENGTH,
            window='hann',
            center=False,
            pad_mode='reflect'
        )
        power_spec = np.abs(D) ** 2
        # Cache mel_basis — it is constant for fixed sr/n_fft/n_mels, recomputing it
        # per-chunk wastes ~10ms × 43 chunks = ~430ms of pure CPU overhead.
        if self._mel_basis is None:
            self._mel_basis = librosa.filters.mel(
                sr=FC_SAMPLE_RATE,
                n_fft=FC_N_FFT,
                n_mels=FC_N_MELS,
                fmin=0.0,
                fmax=8000.0,
                htk=True,
                norm='slaney'
            )
        mel_spec = np.dot(self._mel_basis, power_spec)
        log_mel = np.log(mel_spec + 1e-5)
        mean = np.mean(log_mel, axis=1, keepdims=True)
        std = np.std(log_mel, axis=1, keepdims=True)
        std = np.maximum(std, 1e-10)
        normalized = (log_mel - mean) / std
        return np.expand_dims(normalized, axis=0).astype(np.float32)

    def transcribe_batch(self, audio_chunks: list) -> list:
        """Run ONNX inference on all chunks in ONE batched call.

        Pads every chunk's mel features to the same time dimension, stacks
        them into a single [B, n_mels, T_max] tensor, fires a single
        session.run(), then splits the padded output back per-chunk.
        GPU utilisation goes from ~10% (43 tiny sequential calls) to ~90%
        (one large matrix multiply that fills the compute pipeline).

        Returns a list of (text, word_timestamps, logprobs) tuples,
        one per input chunk, in the same order.
        """
        if self.session is None or not audio_chunks:
            return [("", [], None)] * len(audio_chunks)

        # 1. Compute mel features for every chunk in parallel across CPU cores.
        #    mel computation is pure NumPy — no GIL contention on the heavy math.
        from concurrent.futures import ThreadPoolExecutor
        import multiprocessing
        n_workers = min(len(audio_chunks), multiprocessing.cpu_count())
        with ThreadPoolExecutor(max_workers=n_workers) as pool:
            features_list = list(pool.map(self.compute_mel_spectrogram, audio_chunks))
        # features_list[i] shape: (1, n_mels, T_i)

        T_max = max(f.shape[2] for f in features_list)
        B = len(features_list)

        # 2. Pad to T_max and stack into one batch tensor
        batch = np.zeros((B, FC_N_MELS, T_max), dtype=np.float32)
        lengths = np.zeros(B, dtype=np.int64)
        for i, f in enumerate(features_list):
            t = f.shape[2]
            batch[i, :, :t] = f[0]
            lengths[i] = t

        # 3. Single ONNX inference call for all chunks
        input_names = [inp.name for inp in self.session.get_inputs()]
        ort_inputs = {input_names[0]: batch, input_names[1]: lengths}
        ort_outs = self.session.run(None, ort_inputs)
        # ort_outs[0] shape: (B, T_max_out, vocab) — the subsampled logprobs
        logprobs_batch = ort_outs[0]  # (B, T_out, V)

        # 4. Split and decode each chunk individually
        results = []
        seconds_per_frame = (FC_HOP_LENGTH / FC_SAMPLE_RATE) * FC_SUBSAMPLING_FACTOR
        for i in range(B):
            # Compute the actual output length for chunk i (subsampling factor reduces T)
            t_in  = int(lengths[i])
            t_out = logprobs_batch.shape[1]  # padded output length
            # Estimate valid output frames: proportional to input length vs T_max
            valid_frames = max(1, round(t_out * t_in / T_max))
            lp = logprobs_batch[i, :valid_frames, :]  # trim padding
            text, word_ts = self.decode_ctc(lp, lp.shape[0])
            results.append((text, word_ts, lp))
        return results

    def decode_ctc(self, logprobs: np.ndarray, time_steps: int):
        ids = np.argmax(logprobs, axis=-1)
        seconds_per_frame = (FC_HOP_LENGTH / FC_SAMPLE_RATE) * FC_SUBSAMPLING_FACTOR
        tokens = []
        prev = -1
        current_word_subwords = []
        words_timestamps = []
        word_start_frame = None
        word_end_frame = None

        for t in range(time_steps):
            idx = ids[t]
            if idx != prev and idx != self.blank_id:
                token = self.vocab.get(idx, "")
                is_new_word = token.startswith('▁') or token.startswith(' ')
                if is_new_word and current_word_subwords:
                    full_word = "".join(current_word_subwords).replace('▁', '').replace(' ', '').strip()
                    if full_word:
                        words_timestamps.append({
                            "word": full_word,
                            "start": word_start_frame * seconds_per_frame,
                            "end": word_end_frame * seconds_per_frame
                        })
                    current_word_subwords = []
                    word_start_frame = t
                if not current_word_subwords:
                    word_start_frame = t
                current_word_subwords.append(token)
                word_end_frame = t + 1
                tokens.append(token)
            elif idx == prev and idx != self.blank_id:
                word_end_frame = t + 1
            prev = idx

        if current_word_subwords:
            full_word = "".join(current_word_subwords).replace('▁', '').replace(' ', '').strip()
            if full_word:
                words_timestamps.append({
                    "word": full_word,
                    "start": word_start_frame * seconds_per_frame,
                    "end": word_end_frame * seconds_per_frame
                })

        full_text = "".join(tokens).replace('▁', ' ').replace(' ', ' ').strip()
        full_text = re.sub(r'\s+', ' ', full_text)
        return full_text, words_timestamps

    def transcribe(self, audio: np.ndarray):
        if self.session is None:
            return "", []
        features = self.compute_mel_spectrogram(audio)
        length = np.array([features.shape[2]], dtype=np.int64)
        input_names = [inp.name for inp in self.session.get_inputs()]
        ort_inputs = {
            input_names[0]: features,
            input_names[1]: length
        }
        ort_outs = self.session.run(None, ort_inputs)
        logprobs = ort_outs[0]
        if len(logprobs.shape) == 3:
            logprobs = logprobs[0]
        text, word_timestamps = self.decode_ctc(logprobs, logprobs.shape[0])
        return text, word_timestamps, logprobs

    def force_align(self, logprobs: np.ndarray, reference_text: str, include_letters: bool = False):
        if self.spm_processor is None:
            return []
            
        ref_words = reference_text.split()
        if not ref_words:
            return []
            
        from src.pipeline.arabic_matching import normalize_arabic
        clean_text = normalize_arabic(reference_text)
        
        token_ids = self.spm_processor.encode(clean_text, out_type=int)
        intervals = self._ctc_forced_align(logprobs, token_ids, self.blank_id)
        
        seconds_per_frame = (FC_HOP_LENGTH / FC_SAMPLE_RATE) * FC_SUBSAMPLING_FACTOR
        
        words = []
        word_start_s = None
        word_end_s = None
        word_idx = 0
        
        for tok_id, (start_f, end_f) in zip(token_ids, intervals):
            piece = self.spm_processor.id_to_piece(tok_id)
            start_s = start_f * seconds_per_frame
            end_s = end_f * seconds_per_frame
            
            is_new_word = piece.startswith('▁') or piece.startswith(' ')
            if is_new_word and word_start_s is not None:
                symbol_prefix = ""
                while word_idx < len(ref_words):
                    u_word = ref_words[word_idx]
                    # If the word does not contain any Arabic letters, it's a symbol like ۞
                    if not re.search(r'[\u0621-\u063A\u0641-\u064A\u0671-\u06D3]', u_word):
                        symbol_prefix += u_word + " "
                        word_idx += 1
                    else:
                        break
                        
                u_word = ref_words[word_idx] if word_idx < len(ref_words) else "???"
                if symbol_prefix:
                    u_word = symbol_prefix + u_word
                    
                w_dict = {
                    "word": u_word,
                    "start": word_start_s,
                    "end": word_end_s
                }
                if include_letters and u_word != "???":
                    chars = re.findall(r'.[\u064B-\u065F\u0670\u06D6-\u06DC\u06DF-\u06E8\u06EA-\u06ED\u08F0-\u08FF]*', u_word)
                    dur = (word_end_s - word_start_s) / max(1, len(chars))
                    w_dict["letters"] = [
                        {
                            "letter": ch,
                            "start": word_start_s + i * dur,
                            "end": word_start_s + (i + 1) * dur
                        }
                        for i, ch in enumerate(chars)
                    ]
                words.append(w_dict)
                word_idx += 1
                word_start_s = start_s
            
            if word_start_s is None:
                word_start_s = start_s
            
            word_end_s = end_s
                        
        if word_start_s is not None:
            symbol_prefix = ""
            while word_idx < len(ref_words):
                u_word = ref_words[word_idx]
                if not re.search(r'[\u0621-\u063A\u0641-\u064A\u0671-\u06D3]', u_word):
                    symbol_prefix += u_word + " "
                    word_idx += 1
                else:
                    break

            u_word = ref_words[word_idx] if word_idx < len(ref_words) else "???"
            if symbol_prefix:
                u_word = symbol_prefix + u_word
                
            w_dict = {
                "word": u_word,
                "start": word_start_s,
                "end": word_end_s
            }
            if include_letters and u_word != "???":
                chars = re.findall(r'.[\u064B-\u065F\u0670\u06D6-\u06DC\u06DF-\u06E8\u06EA-\u06ED\u08F0-\u08FF]*', u_word)
                dur = (word_end_s - word_start_s) / max(1, len(chars))
                w_dict["letters"] = [
                    {
                        "letter": ch,
                        "start": word_start_s + i * dur,
                        "end": word_start_s + (i + 1) * dur
                    }
                    for i, ch in enumerate(chars)
                ]
            words.append(w_dict)
            word_idx += 1
                
        while word_idx < len(ref_words):
            u_word = ref_words[word_idx]
            w_dict = {
                "word": u_word,
                "start": word_end_s if word_end_s else 0.0,
                "end": word_end_s if word_end_s else 0.0
            }
            if include_letters:
                chars = re.findall(r'.[\u064B-\u065F\u0670\u06D6-\u06DC\u06DF-\u06E8\u06EA-\u06ED\u08F0-\u08FF]*', u_word)
                w_dict["letters"] = [
                    {
                        "letter": ch,
                        "start": w_dict["start"],
                        "end": w_dict["end"]
                    }
                    for ch in chars
                ]
            words.append(w_dict)
            word_idx += 1
            
        return words

    def _ctc_forced_align(self, logprobs: np.ndarray, token_ids: list, blank_id: int):
        T, _V = logprobs.shape
        seq = [blank_id]
        for t in token_ids:
            seq.append(int(t))
            seq.append(blank_id)
        S = len(seq)
        if T < S // 2:
            # Fallback if audio is too short: return dummy intervals
            return [(0, 0) for _ in token_ids]

        NEG_INF = -1e18
        seq_arr = np.asarray(seq, dtype=np.int64)
        emit = logprobs[:, seq_arr]
        alpha = np.full((T, S), NEG_INF, dtype=np.float64)
        back = np.zeros((T, S), dtype=np.int8)

        alpha[0, 0] = emit[0, 0]
        if S > 1:
            alpha[0, 1] = emit[0, 1]

        skip_ok = np.zeros(S, dtype=bool)
        if S >= 3:
            skip_ok[2:] = (seq_arr[2:] != blank_id) & (seq_arr[2:] != seq_arr[:-2])

        for t in range(1, T):
            prev = alpha[t - 1]
            c0 = prev
            c1 = np.empty(S, dtype=np.float64)
            c1[0] = NEG_INF
            c1[1:] = prev[:-1]
            c2 = np.full(S, NEG_INF, dtype=np.float64)
            if S >= 3:
                c2[2:] = np.where(skip_ok[2:], prev[:-2], NEG_INF)
            
            stacked = np.stack([c0, c1, c2], axis=0)
            best_idx = np.argmax(stacked, axis=0)
            best_val = stacked[best_idx, np.arange(S)]
            alpha[t] = best_val + emit[t]
            back[t] = -best_idx.astype(np.int8)

        end_candidates = [(alpha[T - 1, S - 1], S - 1)]
        if S >= 2:
            end_candidates.append((alpha[T - 1, S - 2], S - 2))
        _best_score, s = max(end_candidates, key=lambda x: x[0])

        path = [s]
        for t in range(T - 1, 0, -1):
            s = s + int(back[t, s])
            path.append(s)
        path.reverse()

        intervals = []
        cur_token_idx = -1
        cur_start = 0
        for t, s in enumerate(path):
            if seq[s] == blank_id:
                continue
            tok_idx = (s - 1) // 2
            if tok_idx != cur_token_idx:
                if cur_token_idx >= 0:
                    intervals.append((cur_start, t))
                cur_token_idx = tok_idx
                cur_start = t
        if cur_token_idx >= 0:
            intervals.append((cur_start, T))
            
        while len(intervals) < len(token_ids):
            last = intervals[-1][1] if intervals else 0
            intervals.append((last, last))
        return intervals[:len(token_ids)]

def transcribe_fastconformer_onnx_with_logprobs(audio: np.ndarray, fast_mode: bool = False, device: str = 'cpu'):
    fc = FastConformerONNX.get_instance(fast_mode=fast_mode, device=device)
    if fc.session is None:
        return "", [], None
    return fc.transcribe(audio)
