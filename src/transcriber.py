"""Zipformer2 Arabic Phoneme CTC Transcriber & Speech Recovery Engine.

Implements pure silence-chunked model feeding with Tajweed-aware acoustic
segmentation, gap-clamped padding, and intra-segment speech recovery.
"""

from __future__ import annotations

import os
import sys
import math
import time
import urllib.request
import logging
from dataclasses import dataclass
from typing import Optional, List, Dict, Tuple, Callable
import numpy as np
import kaldi_native_fbank as knf
import onnxruntime as ort

import config
from config import (
    SAMPLE_RATE,
    BLANK_ID,
    FRAME_STEP,
    DEFAULT_MODEL_PATH,
    DEFAULT_TOKENS_PATH,
    VAD_MIN_PAUSE_S,
    VAD_ONSET_DB,
    VAD_OFFSET_DB,
    VAD_HANGOVER_S,
    VAD_MAX_PAD_S,
    VAD_PREROLL_S,
    VAD_ADAPTIVE,
    FLUSH_PAD_FRAMES,
    RESET_ENCODER_ON_SILENCE,
    ENABLE_SPEECH_RECOVERY,
    SPEECH_RECOVERY_ENERGY_THRESHOLD_DB,
    SPEECH_RECOVERY_MIN_HOLE_DURATION_S,
    SPEECH_RECOVERY_PADDING_S,
    SPEECH_RECOVERY_MIN_PHONEMES_IN_GAP,
)
from src.models import (
    PhonemeToken,
    RawTranscriptionResult,
    RecoveryEvent,
    RecoverySummary,
    SpeechRecoveryResult,
)
from src.audio import AudioDecoder

logger = logging.getLogger(__name__)

FRAME_TIME_STEP = 0.04  # 10ms fbank hop x 4 subsampling = 40ms per encoder frame (25 Hz)
CHUNK_LEN = 48         # decode chunk length in fbank frames (480ms)
T_LEN = 61             # total chunk window including right context in fbank frames (610ms)


@dataclass
class SpeechSegment:
    """Acoustically detected continuous speech segment with safe clamped context."""
    segment_id: int
    raw_start_sec: float
    raw_end_sec: float
    padded_start_sec: float
    padded_end_sec: float
    start_sample: int
    end_sample: int

    @property
    def duration_sec(self) -> float:
        return self.padded_end_sec - self.padded_start_sec


class QuranSilenceSegmenter:
    """Tajweed-aware acoustic silence segmenter.
    
    Features:
    - Dual-threshold Schmitt trigger to prevent fluttering on soft Tajweed letters.
    - Hangover buffer to ensure trailing Madd and Ghunnah are never cut.
    - Rejection of micro-stops (< 500ms) to preserve Qalqalah consonant closures.
    - Gap-clamped padding guaranteeing zero boundary overlap between chunks.
    """

    def __init__(
        self,
        sample_rate: int = SAMPLE_RATE,
        frame_ms: float = 20.0,
        min_pause_s: float = VAD_MIN_PAUSE_S,
        onset_db: float = VAD_ONSET_DB,
        offset_db: float = VAD_OFFSET_DB,
        hangover_s: float = VAD_HANGOVER_S,
        max_pad_s: float = VAD_MAX_PAD_S,
        preroll_s: float = VAD_PREROLL_S,
    ):
        self.sr = sample_rate
        self.frame_samples = int((frame_ms / 1000.0) * sample_rate)
        self.min_pause_s = min_pause_s
        self.hangover_frames = int(hangover_s / (frame_ms / 1000.0))
        self.preroll_frames = int(preroll_s / (frame_ms / 1000.0))
        self.max_pad_s = max_pad_s
        self.onset_db = onset_db
        self.offset_db = offset_db

    def segment_audio(self, audio: np.ndarray) -> List[SpeechSegment]:
        total_samples = len(audio)
        total_duration = total_samples / self.sr
        if total_samples == 0:
            return []

        # 1. Compute frame-level RMS energy in dB
        num_frames = total_samples // self.frame_samples
        if num_frames == 0:
            return [
                SpeechSegment(
                    segment_id=1,
                    raw_start_sec=0.0,
                    raw_end_sec=total_duration,
                    padded_start_sec=0.0,
                    padded_end_sec=total_duration,
                    start_sample=0,
                    end_sample=total_samples,
                )
            ]

        reshaped = audio[:num_frames * self.frame_samples].reshape(num_frames, self.frame_samples)
        rms = np.sqrt(np.mean(np.square(reshaped), axis=1) + 1e-12)
        rms_db = 20.0 * np.log10(np.maximum(rms, 1e-5))

        # Apply a 5-frame (100ms) median filter to remove micro-glitches and breath spikes
        try:
            from scipy.ndimage import median_filter
            energy_curve = median_filter(rms_db, size=5)
        except Exception:
            energy_curve = rms_db

        # Dynamic noise-floor adaptation (calibrates thresholds to audio recording's dynamic range)
        if getattr(config, "VAD_ADAPTIVE", True):
            p15 = float(np.percentile(energy_curve, 15))
            p85 = float(np.percentile(energy_curve, 85))
            dr = max(6.0, p85 - p15)
            onset_th = max(self.onset_db, p15 + 0.38 * dr)
            offset_th = max(self.offset_db, p15 + 0.22 * dr)
        else:
            onset_th = self.onset_db
            offset_th = self.offset_db

        # 2. Dual-threshold state machine with hangover
        is_speech = np.zeros(num_frames, dtype=bool)
        in_speech = False
        silence_count = 0

        for t in range(num_frames):
            e = energy_curve[t]
            if not in_speech:
                if e >= onset_th:
                    in_speech = True
                    is_speech[t] = True
                    silence_count = 0
            else:
                if e >= offset_th:
                    is_speech[t] = True
                    silence_count = 0
                else:
                    silence_count += 1
                    if silence_count <= self.hangover_frames:
                        is_speech[t] = True  # Hangover protection
                    else:
                        in_speech = False

        # 3. Extract continuous speech intervals with pre-roll protection
        raw_intervals: List[Tuple[float, float]] = []
        seg_start = None
        for t in range(num_frames):
            if is_speech[t] and seg_start is None:
                seg_start = max(0, t - self.preroll_frames)
            elif not is_speech[t] and seg_start is not None:
                raw_intervals.append((
                    seg_start * self.frame_samples / self.sr,
                    t * self.frame_samples / self.sr
                ))
                seg_start = None

        if seg_start is not None:
            raw_intervals.append((seg_start * self.frame_samples / self.sr, total_duration))

        if not raw_intervals:
            return [
                SpeechSegment(
                    segment_id=1,
                    raw_start_sec=0.0,
                    raw_end_sec=total_duration,
                    padded_start_sec=0.0,
                    padded_end_sec=total_duration,
                    start_sample=0,
                    end_sample=total_samples,
                )
            ]

        # 4. Merge micro-gaps (< min_pause_s) to preserve Qalqalah stop closures
        merged_intervals: List[Tuple[float, float]] = []
        for s, e in raw_intervals:
            if not merged_intervals:
                merged_intervals.append((s, e))
            else:
                prev_s, prev_e = merged_intervals[-1]
                gap = s - prev_e
                if gap < self.min_pause_s:
                    merged_intervals[-1] = (prev_s, e)
                else:
                    merged_intervals.append((s, e))

        # 5. Apply Gap-Clamped Padding (guarantees zero boundary overlap between chunks)
        segments: List[SpeechSegment] = []
        num_merged = len(merged_intervals)

        for i, (raw_s, raw_e) in enumerate(merged_intervals):
            gap_before = (raw_s - merged_intervals[i - 1][1]) if i > 0 else 10.0
            gap_after = (merged_intervals[i + 1][0] - raw_e) if i < num_merged - 1 else 10.0

            pad_left = min(self.max_pad_s, max(0.0, gap_before / 2.0))
            pad_right = min(self.max_pad_s, max(0.0, gap_after / 2.0))

            padded_s = max(0.0, raw_s - pad_left)
            padded_e = min(total_duration, raw_e + pad_right)

            # Snap to exact 40ms encoder frame boundaries (640 audio samples = 4 fbank frames = 1 encoder frame)
            # This completely eliminates sub-frame phase jitter and time-quantization drift at segment boundaries
            FRAME_SAMPLES = int(round(FRAME_TIME_STEP * self.sr))  # 640 samples (40ms)
            start_sample = int(math.floor((padded_s * self.sr) / FRAME_SAMPLES)) * FRAME_SAMPLES
            end_sample = min(total_samples, int(math.ceil((padded_e * self.sr) / FRAME_SAMPLES)) * FRAME_SAMPLES)

            aligned_padded_s = start_sample / self.sr
            aligned_padded_e = end_sample / self.sr

            segments.append(
                SpeechSegment(
                    segment_id=i + 1,
                    raw_start_sec=round(raw_s, 3),
                    raw_end_sec=round(raw_e, 3),
                    padded_start_sec=round(aligned_padded_s, 4),
                    padded_end_sec=round(aligned_padded_e, 4),
                    start_sample=start_sample,
                    end_sample=end_sample,
                )
            )

        return segments


class ZipformerONNX:
    """Streaming INT8 Zipformer Arabic Phoneme CTC model runner."""
    _instance: Optional[ZipformerONNX] = None

    def __init__(self, device: str = "cpu"):
        self.device = device
        self.session: Optional[ort.InferenceSession] = None
        self.vocab: List[str] = []
        self.id2token: Dict[int, str] = {}
        self.token2id: Dict[str, int] = {}
        self._load_model()

    @classmethod
    def get_instance(cls, device: str = "cpu") -> ZipformerONNX:
        if cls._instance is None:
            cls._instance = ZipformerONNX(device=device)
        return cls._instance

    def _load_model(self):
        if not os.path.exists(DEFAULT_MODEL_PATH):
            os.makedirs(os.path.dirname(DEFAULT_MODEL_PATH), exist_ok=True)
            url = "https://github.com/Iam-Muslim/Natlu/releases/download/models-latest/zipformer_p_arabic_v3.int8.onnx"
            logger.info(f"[*] Downloading Zipformer ONNX model from {url}...")
            urllib.request.urlretrieve(url, DEFAULT_MODEL_PATH)
            logger.info("[*] Zipformer ONNX model downloaded successfully.")

        sess_opts = ort.SessionOptions()
        sess_opts.log_severity_level = 3
        sess_opts.enable_cpu_mem_arena = False
        num_threads = int(os.environ.get("ONNX_NUM_THREADS", "2"))
        sess_opts.intra_op_num_threads = num_threads
        sess_opts.inter_op_num_threads = 2

        opt_model_path = os.path.splitext(DEFAULT_MODEL_PATH)[0] + ".opt.onnx"
        if os.path.exists(opt_model_path):
            sess_opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_DISABLE_ALL
            self.session = ort.InferenceSession(
                opt_model_path,
                sess_opts,
                providers=['CPUExecutionProvider']
            )
        else:
            try:
                sess_opts.optimized_model_filepath = opt_model_path
                self.session = ort.InferenceSession(
                    DEFAULT_MODEL_PATH,
                    sess_opts,
                    providers=['CPUExecutionProvider']
                )
            except Exception:
                sess_opts.optimized_model_filepath = ""
                self.session = ort.InferenceSession(
                    DEFAULT_MODEL_PATH,
                    sess_opts,
                    providers=['CPUExecutionProvider']
                )

        self.vocab = []
        self.id2token = {}
        self.token2id = {}
        if os.path.exists(DEFAULT_TOKENS_PATH):
            with open(DEFAULT_TOKENS_PATH, "r", encoding="utf-8") as f:
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

        # Pre-allocate reusable in-place state buffers to eliminate per-segment heap allocations
        self._input_names = [inp.name for inp in self.session.get_inputs()]
        self._state_names = [name for name in self._input_names if name != 'x']
        self._state_buffers = self._create_initial_states()

    def _create_initial_states(self) -> dict:
        states = {}
        for inp in self.session.get_inputs():
            shape = [1 if dim == 'N' else dim for dim in inp.shape]
            dtype = np.float32 if inp.type == 'tensor(float)' else np.int64
            states[inp.name] = np.zeros(shape, dtype=dtype)
        states['processed_lens'] = np.array([0], dtype=np.int64)
        return states

    def _reset_states(self) -> None:
        """In-place zeroing of recurrent state buffers (zero memory allocation overhead)."""
        for k in self._state_names:
            self._state_buffers[k].fill(0)
        self._state_buffers['processed_lens'].fill(0)

    def _extract_fbank(self, audio: np.ndarray) -> np.ndarray:
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
        if not audio.flags.c_contiguous or audio.dtype != np.float32:
            audio = np.ascontiguousarray(audio, dtype=np.float32)

        # Chunked ingestion avoids buffering entire multi-hour waveforms in C++
        chunk_samples = SAMPLE_RATE * 30
        for pos in range(0, len(audio), chunk_samples):
            fbank.accept_waveform(SAMPLE_RATE, audio[pos:pos + chunk_samples])
        fbank.input_finished()

        num_frames = fbank.num_frames_ready
        if num_frames == 0:
            return np.empty((0, 80), dtype=np.float32)

        feats = np.empty((num_frames, 80), dtype=np.float32)
        for i in range(num_frames):
            feats[i] = fbank.get_frame(i)

        del fbank
        return feats

    def _transcribe_fbank_segment(
        self,
        feats: np.ndarray,
        silence_pad_frames: Optional[int] = None,
        reset_states: bool = True,
    ) -> Tuple[np.ndarray, List[PhonemeToken]]:
        """Core streaming neural chunk loop on a pre-extracted Fbank feature slice."""
        if self.session is None or len(feats) == 0:
            return np.empty((0, len(self.vocab)), dtype=np.float32), []

        # Flush padding: append silence frames (default 96 frames = 960ms) to ensure all
        # internal Zipformer downsampling activations exit through the CTC head.
        flush_frames = FLUSH_PAD_FRAMES if silence_pad_frames is None else silence_pad_frames
        num_chunks = int(math.ceil((len(feats) + flush_frames) / CHUNK_LEN))
        required_len = max(T_LEN, (num_chunks - 1) * CHUNK_LEN + T_LEN)
        pad_len = max(0, required_len - len(feats))
        if pad_len > 0:
            pad = np.zeros((pad_len, 80), dtype=np.float32)
            padded_feats = np.vstack([feats, pad])
        else:
            padded_feats = feats

        # Fast in-place zero state reset only when explicitly requested (e.g. at Waqf boundaries)
        if reset_states:
            self._reset_states()
        num_frames = len(padded_feats)
        chunk_logprobs = []
        pos = 0

        while pos + T_LEN <= num_frames:
            self._state_buffers['x'] = padded_feats[pos:pos + T_LEN][None, :].astype(np.float32)
            outs = self.session.run(None, self._state_buffers)
            for idx in range(1, len(outs)):
                self._state_buffers[self._input_names[idx]] = outs[idx]
            chunk_logprobs.append(outs[0][0])
            pos += CHUNK_LEN

        if not chunk_logprobs:
            return np.empty((0, len(self.vocab)), dtype=np.float32), []

        # Full logprobs without premature truncation, capturing all delayed trailing CTC spikes.
        # Trailing flush frames naturally emit pure CTC blank (BLANK_ID=250), which greedy decoding collapses.
        valid_logprobs = np.concatenate(chunk_logprobs, axis=0)

        # Greedy decoding to extract local phonemes
        pred_idx = np.argmax(valid_logprobs, axis=-1)
        phonemes: List[PhonemeToken] = []

        prev_idx = -1
        current_run_frames = []
        current_tok_idx = -1

        def _flush_run():
            if not current_run_frames or current_tok_idx == BLANK_ID or current_tok_idx == -1:
                return
            start_f = current_run_frames[0]
            end_f = current_run_frames[-1] + 1
            tok_str = self.id2token.get(current_tok_idx, "")
            if tok_str and tok_str != "<blank>":
                # Peak frame within emitted run
                pk_rel = int(np.argmax(valid_logprobs[current_run_frames, current_tok_idx]))
                pk_frame = current_run_frames[pk_rel]

                # Softmax at peak frame to compute true probability margin in [0, 1]
                # (matching decode_with_confidence.py in model/)
                peak_logits = valid_logprobs[pk_frame]
                peak_exp = np.exp(peak_logits - np.max(peak_logits))
                peak_probs = peak_exp / np.sum(peak_exp)
                pk_sorted = np.sort(peak_probs)[::-1]
                margin_pk = float(pk_sorted[0] - pk_sorted[1]) if len(pk_sorted) > 1 else 1.0

                start_sec = round(start_f * FRAME_TIME_STEP, 4)
                end_sec = round(end_f * FRAME_TIME_STEP, 4)
                pk_time = round(pk_frame * FRAME_TIME_STEP, 4)

                token_obj = PhonemeToken(
                    phoneme=tok_str,
                    start=start_sec,
                    end=end_sec,
                    confidence=round(margin_pk, 4),
                    is_recovered=False,
                    start_frame=start_f,
                    end_frame=end_f,
                    peak_frame=pk_frame,
                    peak_timestamp=pk_time,
                )
                phonemes.append(token_obj)

        for f_idx, idx in enumerate(pred_idx):
            if idx == prev_idx:
                if idx != BLANK_ID:
                    current_run_frames.append(f_idx)
                continue
            _flush_run()
            current_run_frames = [] if idx == BLANK_ID else [f_idx]
            current_tok_idx = idx
            prev_idx = idx

        _flush_run()
        return valid_logprobs, phonemes

    def transcribe_segment(
        self,
        segment_pcm: np.ndarray,
        sample_rate: int = SAMPLE_RATE,
        silence_pad_frames: Optional[int] = None,
    ) -> Tuple[np.ndarray, List[PhonemeToken]]:
        """Transcribes a standalone audio slice (used by SpeechRecoveryEngine)."""
        if self.session is None or len(segment_pcm) == 0:
            return np.empty((0, len(self.vocab)), dtype=np.float32), []
        feats = self._extract_fbank(segment_pcm.astype(np.float32))
        if len(feats) == 0:
            return np.empty((0, len(self.vocab)), dtype=np.float32), []
        return self._transcribe_fbank_segment(feats, silence_pad_frames=silence_pad_frames, reset_states=True)

    def transcribe_audio(
        self,
        audio: np.ndarray,
        sample_rate: int = SAMPLE_RATE,
        silence_pad_frames: Optional[int] = None,
        on_progress=None,
        reset_on_silence: Optional[bool] = None,
        min_blank_chunks: Optional[int] = None,
    ) -> RawTranscriptionResult:
        """Transcribes audio using global Fbank caching, Tajweed pause segmentation & zero-drift segment feeding."""
        if self.session is None or len(audio) == 0:
            return RawTranscriptionResult(vocab_size=len(self.vocab))

        audio_pcm = audio.astype(np.float32, copy=False)
        audio_duration = len(audio_pcm) / sample_rate

        # 1. Segment audio on natural Waqf pauses
        segmenter = QuranSilenceSegmenter(sample_rate=sample_rate)
        segments = segmenter.segment_audio(audio_pcm)

        # 2. Extract Mel Filterbank ONCE globally across entire audio (blazing fast in C++)
        global_feats = self._extract_fbank(audio_pcm)
        total_fbank_frames = len(global_feats)
        if total_fbank_frames == 0:
            return RawTranscriptionResult(vocab_size=len(self.vocab))

        del audio_pcm

        total_frames = int(math.ceil(audio_duration / FRAME_TIME_STEP))
        vocab_size = len(self.vocab)

        # 3. Global CTC emission matrix: pre-filled with 100% CTC Blank in pauses
        global_logprobs = np.full((total_frames, vocab_size), -50.0, dtype=np.float32)
        global_logprobs[:, BLANK_ID] = 0.0

        global_phonemes: List[PhonemeToken] = []
        global_raw_tokens: List[str] = []
        global_raw_timestamps: List[float] = []
        pause_timestamps: List[float] = []

        # Reset recurrent state buffers once at the start of the audio file (preserves memory across segments)
        self._reset_states()

        start_time = time.time()
        num_segments = len(segments)
        do_reset_on_silence = getattr(config, "RESET_ENCODER_ON_SILENCE", True) if reset_on_silence is None else reset_on_silence

        for s_idx, seg in enumerate(segments):
            # Zero-copy slice directly from global Fbank matrix (avoids re-running Kaldi Fbank 50+ times)
            s_fb = max(0, int(round(seg.padded_start_sec * 100.0)))
            e_fb = min(total_fbank_frames, int(round(seg.padded_end_sec * 100.0)))
            seg_feats = global_feats[s_fb:e_fb]

            if len(seg_feats) == 0:
                continue

            seg_lp, seg_phonemes = self._transcribe_fbank_segment(
                seg_feats,
                silence_pad_frames=silence_pad_frames,
                reset_states=do_reset_on_silence,
            )

            if len(seg_lp) > 0:
                start_frame = int(round(seg.padded_start_sec / FRAME_TIME_STEP))
                if s_idx < num_segments - 1:
                    next_start_frame = int(round(segments[s_idx + 1].padded_start_sec / FRAME_TIME_STEP))
                    end_frame = min(total_frames, next_start_frame, start_frame + len(seg_lp))
                else:
                    end_frame = min(total_frames, start_frame + len(seg_lp))
                frames_to_copy = end_frame - start_frame

                if frames_to_copy > 0:
                    global_logprobs[start_frame:end_frame] = seg_lp[:frames_to_copy]

                # Map local segment phonemes into global timeline
                for p in seg_phonemes:
                    if p.start > (seg.duration_sec + 0.25):
                        continue

                    g_start = round(seg.padded_start_sec + p.start, 3)
                    g_end = min(round(audio_duration, 3), round(seg.padded_start_sec + p.end, 3))
                    g_pk = round(seg.padded_start_sec + p.peak_timestamp, 3) if p.peak_timestamp else round((g_start + g_end) / 2, 3)
                    g_pk = min(round(audio_duration, 3), g_pk)

                    shifted_token = PhonemeToken(
                        phoneme=p.phoneme,
                        start=g_start,
                        end=g_end,
                        confidence=p.confidence,
                        is_recovered=p.is_recovered,
                        start_frame=start_frame + (p.start_frame or 0),
                        end_frame=start_frame + (p.end_frame or 0),
                        peak_frame=start_frame + (p.peak_frame or 0),
                        peak_timestamp=g_pk,
                    )
                    global_phonemes.append(shifted_token)
                    global_raw_tokens.append(p.phoneme)
                    global_raw_timestamps.append(g_pk)

            # Record pause moments
            if s_idx < num_segments - 1:
                next_seg = segments[s_idx + 1]
                gap = next_seg.raw_start_sec - seg.raw_end_sec
                if gap >= 0.40:
                    pause_timestamps.append(round(seg.raw_end_sec, 2))

            if on_progress is not None:
                pct = min(100.0, ((s_idx + 1) / max(1, num_segments)) * 100.0)
                elp = max(0.001, time.time() - start_time)
                spd = (seg.padded_end_sec) / elp
                on_progress(pct, spd, elp)

        global_phonemes.sort(key=lambda p: p.start)

        return RawTranscriptionResult(
            phonemes=global_phonemes,
            raw_tokens=global_raw_tokens,
            raw_timestamps=global_raw_timestamps,
            logprobs_matrix=global_logprobs,
            num_frames=total_frames,
            vocab_size=vocab_size,
            pause_timestamps=pause_timestamps,
        )


@dataclass
class _AudioGap:
    start: float
    end: float
    prev_index: int
    next_index: int

    @property
    def duration(self) -> float:
        return self.end - self.start


class SpeechRecoveryEngine:
    """Scans untranscribed acoustic gaps inside speech regions and recovers deleted phonemes."""

    @classmethod
    def recover_speech(
        cls,
        audio_pcm: np.ndarray,
        initial_phonemes: List[PhonemeToken],
        audio_duration: float,
        transcriber: ZipformerONNX,
        logprobs_matrix: Optional[np.ndarray] = None,
        energy_threshold_db: float = SPEECH_RECOVERY_ENERGY_THRESHOLD_DB,
        min_hole_duration_s: float = SPEECH_RECOVERY_MIN_HOLE_DURATION_S,
        padding_s: float = SPEECH_RECOVERY_PADDING_S,
        min_phonemes_in_gap: int = SPEECH_RECOVERY_MIN_PHONEMES_IN_GAP,
        sample_rate: int = SAMPLE_RATE,
        on_progress: Optional[Callable[[float, float], None]] = None,
    ) -> SpeechRecoveryResult:
        start_time = time.time()
        candidate_gaps: List[_AudioGap] = []

        if not initial_phonemes:
            if audio_duration >= min_hole_duration_s:
                candidate_gaps.append(_AudioGap(start=0.0, end=audio_duration, prev_index=-1, next_index=-1))
        else:
            if initial_phonemes[0].start >= min_hole_duration_s:
                candidate_gaps.append(_AudioGap(start=0.0, end=initial_phonemes[0].start, prev_index=-1, next_index=0))

            for i in range(len(initial_phonemes) - 1):
                g_start = initial_phonemes[i].end
                g_end = initial_phonemes[i + 1].start
                if g_end - g_start >= min_hole_duration_s:
                    candidate_gaps.append(_AudioGap(start=g_start, end=g_end, prev_index=i, next_index=i + 1))

            if audio_duration - initial_phonemes[-1].end >= min_hole_duration_s:
                candidate_gaps.append(
                    _AudioGap(start=initial_phonemes[-1].end, end=audio_duration, prev_index=len(initial_phonemes) - 1, next_index=-1)
                )

        recovery_events: List[RecoveryEvent] = []
        new_phonemes_to_insert: List[PhonemeToken] = []
        speech_holes_detected = 0

        for g_idx, gap in enumerate(candidate_gaps):
            start_sample = max(0, int(round(gap.start * sample_rate)))
            end_sample = min(len(audio_pcm), int(round(gap.end * sample_rate)))
            energy_db = AudioDecoder.calculate_energy_db(audio_pcm, start_idx=start_sample, end_idx=end_sample)

            if energy_db >= energy_threshold_db:
                speech_holes_detected += 1
                padded_start = max(0.0, gap.start - padding_s)
                padded_end = min(audio_duration, gap.end + padding_s)
                p_start_sample = int(round(padded_start * sample_rate))
                p_end_sample = min(len(audio_pcm), int(round(padded_end * sample_rate)))

                if p_end_sample > p_start_sample:
                    slice_pcm = audio_pcm[p_start_sample:p_end_sample]
                    slice_lp, slice_phonemes = transcriber.transcribe_segment(
                        slice_pcm, sample_rate=sample_rate, silence_pad_frames=24
                    )

                    gap_phonemes: List[PhonemeToken] = []
                    for sp in slice_phonemes:
                        real_start = padded_start + sp.start
                        real_end = padded_start + sp.end
                        real_peak = (padded_start + sp.peak_timestamp) if sp.peak_timestamp else ((real_start + real_end) / 2)

                        if real_start >= gap.start - 0.05 and real_end <= gap.end + 0.05:
                            gap_phonemes.append(
                                PhonemeToken(
                                    phoneme=sp.phoneme,
                                    start=round(real_start, 3),
                                    end=round(real_end, 3),
                                    confidence=sp.confidence,
                                    is_recovered=True,
                                    start_frame=int(round(real_start / FRAME_TIME_STEP)),
                                    end_frame=int(round(real_end / FRAME_TIME_STEP)),
                                    peak_frame=int(round(real_peak / FRAME_TIME_STEP)),
                                    peak_timestamp=round(real_peak, 3),
                                )
                            )

                    if len(gap_phonemes) >= min_phonemes_in_gap:
                        event = RecoveryEvent(
                            event_id=len(recovery_events) + 1,
                            gap_start=gap.start,
                            gap_end=gap.end,
                            gap_duration=gap.duration,
                            padded_start=padded_start,
                            padded_end=padded_end,
                            energy_db=energy_db,
                            recovered_text="".join(p.phoneme for p in gap_phonemes),
                            recovered_phonemes=gap_phonemes,
                        )
                        recovery_events.append(event)
                        new_phonemes_to_insert.extend(gap_phonemes)

                        # Patch the global emission logprobs matrix if provided
                        if logprobs_matrix is not None and len(slice_lp) > 0:
                            s_frame = int(round(padded_start / FRAME_TIME_STEP))
                            e_frame = min(logprobs_matrix.shape[0], s_frame + len(slice_lp))
                            copy_f = e_frame - s_frame
                            if copy_f > 0:
                                logprobs_matrix[s_frame:e_frame] = np.maximum(
                                    logprobs_matrix[s_frame:e_frame],
                                    slice_lp[:copy_f]
                                )

            if on_progress:
                on_progress(((g_idx + 1) / max(1, len(candidate_gaps))) * 100.0, time.time() - start_time)

        # Merge and sort all phonemes chronologically
        all_phonemes = list(initial_phonemes) + new_phonemes_to_insert
        all_phonemes.sort(key=lambda p: p.start)

        summary = RecoverySummary(
            recovery_time_seconds=time.time() - start_time,
            scanned_gaps_count=len(candidate_gaps),
            speech_holes_detected=speech_holes_detected,
            recovered_events_count=len(recovery_events),
            recovered_phonemes_count=len(new_phonemes_to_insert),
            energy_threshold_db=energy_threshold_db,
            min_hole_duration_s=min_hole_duration_s,
        )

        return SpeechRecoveryResult(
            recovered_phonemes=all_phonemes,
            recovery_events=recovery_events,
            recovery_summary=summary,
        )
