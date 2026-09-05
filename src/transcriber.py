"""Zipformer2 Arabic Phoneme CTC Transcriber & Speech Recovery Engine."""

from __future__ import annotations

import os
import sys
import time
import urllib.request
import logging
from dataclasses import dataclass
from typing import Optional, List, Dict, Callable
import numpy as np
import kaldi_native_fbank as knf
import onnxruntime as ort

from config import (
    SAMPLE_RATE,
    BLANK_ID,
    FRAME_STEP,
    DEFAULT_MODEL_PATH,
    DEFAULT_TOKENS_PATH,
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
        num_threads = int(os.environ.get("ONNX_NUM_THREADS", "2"))
        sess_opts.intra_op_num_threads = num_threads
        sess_opts.inter_op_num_threads = 2

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

    def _create_initial_states(self) -> dict:
        states = {}
        for inp in self.session.get_inputs():
            shape = [1 if dim == 'N' else dim for dim in inp.shape]
            dtype = np.float32 if inp.type == 'tensor(float)' else np.int64
            states[inp.name] = np.zeros(shape, dtype=dtype)
        states['processed_lens'] = np.array([0], dtype=np.int64)
        return states

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
        chunk_samples = 30 * SAMPLE_RATE
        for offset in range(0, len(audio), chunk_samples):
            sub_chunk = audio[offset : offset + chunk_samples]
            fbank.accept_waveform(SAMPLE_RATE, sub_chunk.tolist())
        fbank.input_finished()

        num_frames = fbank.num_frames_ready
        if num_frames == 0:
            return np.empty((0, 80), dtype=np.float32)

        return np.array([fbank.get_frame(i) for i in range(num_frames)], dtype=np.float32)

    def transcribe_audio(
        self,
        audio: np.ndarray,
        sample_rate: int = SAMPLE_RATE,
        silence_pad_frames: int = 105,
        on_progress=None,
    ) -> RawTranscriptionResult:
        """Transcribes audio array into phoneme tokens and valid emission log-probabilities."""
        if self.session is None or len(audio) == 0:
            return RawTranscriptionResult(vocab_size=len(self.vocab))

        feats = self._extract_fbank(audio.astype(np.float32))
        if len(feats) == 0:
            return RawTranscriptionResult(vocab_size=len(self.vocab))

        if silence_pad_frames > 0:
            silence_feats = np.zeros((silence_pad_frames, 80), dtype=np.float32)
            padded_feats = np.vstack([feats, silence_feats])
        else:
            padded_feats = feats

        states = self._create_initial_states()
        num_frames = len(padded_feats)
        all_chunk_logprobs = []
        pos = 0
        input_names = [inp.name for inp in self.session.get_inputs()]
        start_time = time.time()

        while pos + T_LEN <= num_frames:
            chunk = padded_feats[pos:pos + T_LEN][None, :].astype(np.float32)
            states['x'] = chunk
            outputs = self.session.run(None, states)

            chunk_lp = outputs[0][0]  # shape: [12, 251]
            all_chunk_logprobs.append(chunk_lp)

            for out_idx in range(1, len(outputs)):
                states[input_names[out_idx]] = outputs[out_idx]

            pos += CHUNK_LEN

            if on_progress is not None:
                pct = (pos / num_frames) * 100.0
                elp = max(0.001, time.time() - start_time)
                spd = ((pos / num_frames) * (len(audio) / SAMPLE_RATE)) / elp
                on_progress(pct, spd, elp)

        if not all_chunk_logprobs:
            return RawTranscriptionResult(vocab_size=len(self.vocab))

        full_logprobs = np.concatenate(all_chunk_logprobs, axis=0)
        actual_output_frames = max(1, len(feats) // 4)
        total_valid_frames = min(len(full_logprobs), actual_output_frames + 4)
        valid_logprobs = full_logprobs[:total_valid_frames]

        # Greedy CTC decoding
        pred_idx = np.argmax(valid_logprobs, axis=-1)
        phonemes: List[PhonemeToken] = []
        raw_tokens: List[str] = []
        raw_timestamps: List[float] = []

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
                pk_rel = int(np.argmax(run_probs[:, current_tok_idx]))
                pk_frame = current_run_frames[pk_rel]
                pk_sorted = np.sort(valid_logprobs[pk_frame])[::-1]
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
                raw_tokens.append(tok_str)
                raw_timestamps.append(pk_time)

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

        return RawTranscriptionResult(
            phonemes=phonemes,
            raw_tokens=raw_tokens,
            raw_timestamps=raw_timestamps,
            logprobs_matrix=valid_logprobs,
            num_frames=total_valid_frames,
            vocab_size=len(self.vocab),
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
    """Scans untranscribed gaps in the audio timeline and recovers deleted speech."""

    @classmethod
    def recover_speech(
        cls,
        audio_pcm: np.ndarray,
        initial_phonemes: List[PhonemeToken],
        audio_duration: float,
        transcriber: ZipformerONNX,
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
                    raw_slice_result = transcriber.transcribe_audio(
                        slice_pcm, sample_rate=sample_rate, silence_pad_frames=24
                    )
                    slice_phonemes = raw_slice_result.phonemes

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

            if on_progress:
                on_progress(((g_idx + 1) / max(1, len(candidate_gaps))) * 100.0, time.time() - start_time)

        # Merge and sort
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
