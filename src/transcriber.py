"""TajweedFormer V4 C-Engine Acoustic Transcriber.

Embeds the portable C TajweedFormer inference engine via zf_tajweed.dll.
Provides bit-exact acoustic transcription, 20ms fine timing heads, and
streaming inference with zero external runtime dependencies.
"""

from __future__ import annotations

import os
import time
import math
import queue
import ctypes
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional, List, Dict, Tuple, Callable, Any, Union
from pathlib import Path
import numpy as np

import config
from config import (
    SAMPLE_RATE,
    BLANK_ID,
    FRAME_STEP,
)
from src.models import (
    PhonemeToken,
    RawTranscriptionResult,
    PauseInterval,
    RecoveryEvent,
    RecoverySummary,
    SpeechRecoveryResult,
)
from src.vad import QuranSilenceVAD

logger = logging.getLogger(__name__)

# Head masks from zf_tajweed.h
HEAD_LOG_PROBS = 1 << 0
HEAD_INTER1 = 1 << 1
HEAD_INTER4 = 1 << 2
HEAD_ID = 1 << 3
HEAD_TIMING = 1 << 4
HEAD_GEM = 1 << 5
HEAD_TAFKHEEM = 1 << 6
HEAD_GHUNNA = 1 << 7
HEAD_QALQALAH = 1 << 8
HEAD_FACE = 1 << 9
HEAD_BOUNDARY = 1 << 10
HEAD_CONF = 1 << 11

ACTIVE_HEADS_MASK = (
    HEAD_LOG_PROBS
    | HEAD_TIMING
    | HEAD_CONF
)


# -----------------------------------------------------------------------------
# C-Types Structure Definitions for zf_tajweed.h
# -----------------------------------------------------------------------------

class _ZfTajweedOpenOptions(ctypes.Structure):
    _fields_ = [
        ("struct_size", ctypes.c_size_t),
        ("context", ctypes.c_char_p),
        ("load_engine", ctypes.c_int),
        ("threads", ctypes.c_int),
        ("sample_rate", ctypes.c_int),
        ("batch", ctypes.c_int),
        ("no_pin", ctypes.c_int),
    ]


class _ZfTajweedHeads(ctypes.Structure):
    _fields_ = [
        ("n40", ctypes.c_int),
        ("n20", ctypes.c_int),
        ("vocab", ctypes.c_int),
        ("log_probs", ctypes.POINTER(ctypes.c_float)),
        ("inter1_log_probs", ctypes.POINTER(ctypes.c_float)),
        ("inter4_log_probs", ctypes.POINTER(ctypes.c_float)),
        ("id_log_probs", ctypes.POINTER(ctypes.c_float)),
        ("timing_log_probs", ctypes.POINTER(ctypes.c_float)),
        ("gem", ctypes.POINTER(ctypes.c_float)),
        ("attr_tafkheem", ctypes.POINTER(ctypes.c_float)),
        ("attr_ghunna", ctypes.POINTER(ctypes.c_float)),
        ("attr_qalqalah", ctypes.POINTER(ctypes.c_float)),
        ("attr_face", ctypes.POINTER(ctypes.c_float)),
        ("boundary", ctypes.POINTER(ctypes.c_float)),
        ("conf", ctypes.POINTER(ctypes.c_float)),
    ]


class _ZfTajweedTop2(ctypes.Structure):
    _fields_ = [
        ("token", ctypes.c_int),
        ("runner_up", ctypes.c_int),
        ("log_prob", ctypes.c_float),
        ("runner_up_log_prob", ctypes.c_float),
        ("margin", ctypes.c_float),
    ]


class TajweedFormerEngine:
    """Singleton C-Engine acoustic phoneme transcriber for TajweedFormer V4."""
    _instance: Optional[TajweedFormerEngine] = None

    def __init__(
        self,
        model_dir: Optional[str] = None,
        dll_path: Optional[str] = None,
        context: Optional[str] = None,
        threads: int = 0,
    ):
        self.model_dir = str(Path(model_dir or getattr(config, "DEFAULT_MODEL_DIR", "data/model")).resolve())
        self.dll_path = str(Path(dll_path or getattr(config, "DEFAULT_DLL_PATH", "data/bin/zf_tajweed.dll")).resolve())
        self.context = (context or getattr(config, "TAJWEEDFORMER_CONTEXT", "c24_l256")).encode("utf-8")
        self.threads = threads

        self.dll: Optional[ctypes.CDLL] = None
        self.model: Optional[ctypes.c_void_p] = None
        self.vocab: List[str] = []
        self.id2token: Dict[int, str] = {}
        self.token2id: Dict[str, int] = {}

        self._init_dll()
        self._load_model()

    @classmethod
    def get_instance(cls, **kwargs) -> TajweedFormerEngine:
        if cls._instance is None:
            cls._instance = TajweedFormerEngine(**kwargs)
        return cls._instance

    def _init_dll(self) -> None:
        """Loads and binds the zf_tajweed shared library."""
        cand_paths = [
            self.dll_path,
            str(Path(config.PROJECT_ROOT) / "data" / "bin" / "zf_tajweed.dll"),
            "zf_tajweed.dll",
        ]
        loaded_dll = next((ctypes.CDLL(p) for p in cand_paths if os.path.isfile(p)), None)
        if loaded_dll is None:
            raise FileNotFoundError(f"Could not load zf_tajweed.dll. Looked in: {cand_paths}.")
        self.dll = loaded_dll

        # Declarative C-function signature registration
        sigs = [
            ("zf_tajweed_version", None, ctypes.c_char_p),
            ("zf_tajweed_api_version", None, ctypes.c_int),
            ("zf_tajweed_open_default_options", None, _ZfTajweedOpenOptions),
            ("zf_tajweed_model_open", [ctypes.c_char_p, ctypes.POINTER(_ZfTajweedOpenOptions), ctypes.POINTER(ctypes.c_char_p)], ctypes.c_void_p),
            ("zf_tajweed_model_close", [ctypes.c_void_p], None),
            ("zf_tajweed_model_chunk_ms", [ctypes.c_void_p], ctypes.c_int),
            ("zf_tajweed_token_name", [ctypes.c_void_p, ctypes.c_int], ctypes.c_char_p),
            ("zf_tajweed_stream_create", [ctypes.c_void_p, ctypes.POINTER(ctypes.c_char_p)], ctypes.c_void_p),
            ("zf_tajweed_stream_destroy", [ctypes.c_void_p], None),
            ("zf_tajweed_stream_reset", [ctypes.c_void_p], None),
            ("zf_tajweed_stream_set_heads", [ctypes.c_void_p, ctypes.c_uint], ctypes.c_int),
            ("zf_tajweed_stream_push_audio", [ctypes.c_void_p, ctypes.POINTER(ctypes.c_float), ctypes.c_int], ctypes.c_int),
            ("zf_tajweed_stream_finish", [ctypes.c_void_p], ctypes.c_int),
            ("zf_tajweed_stream_heads", [ctypes.c_void_p, ctypes.POINTER(_ZfTajweedHeads)], ctypes.c_int),
            ("zf_tajweed_stream_top2", [ctypes.c_void_p, ctypes.POINTER(ctypes.POINTER(_ZfTajweedTop2))], ctypes.c_int),
            ("zf_tajweed_stream_greedy", [ctypes.c_void_p, ctypes.POINTER(ctypes.c_int), ctypes.c_int], ctypes.c_int),
            ("zf_tajweed_stream_last_error", [ctypes.c_void_p], ctypes.c_char_p),
        ]
        for name, args, res in sigs:
            fn = getattr(self.dll, name, None)
            if fn:
                if args: fn.argtypes = args
                if res: fn.restype = res

    def _load_model(self) -> None:
        """Opens the TajweedFormer V4 model directory."""
        if not os.path.isdir(self.model_dir):
            raise FileNotFoundError(f"Model directory not found: {self.model_dir}")

        opts = self.dll.zf_tajweed_open_default_options()
        opts.context = self.context
        opts.threads = self.threads
        opts.sample_rate = SAMPLE_RATE
        opts.batch = 1
        opts.no_pin = 1  # Unpinned so concurrent worker streams do not collide on pinned CPU cores

        err = ctypes.c_char_p()
        model_ptr = self.dll.zf_tajweed_model_open(self.model_dir.encode("utf-8"), ctypes.byref(opts), ctypes.byref(err))
        if not model_ptr:
            err_msg = err.value.decode("utf-8") if err.value else "unknown error"
            raise RuntimeError(f"Failed to open TajweedFormer model at {self.model_dir}: {err_msg}")
        self.model = model_ptr

        # Read 38-token vocabulary
        self.vocab, self.id2token, self.token2id = [], {}, {}
        for i in range(38):
            name_p = self.dll.zf_tajweed_token_name(self.model, i)
            tok_name = name_p.decode("utf-8") if name_p else f"<unk_{i}>"
            self.vocab.append(tok_name)
            self.id2token[i] = tok_name
            self.token2id[tok_name] = i

    def create_stream(self) -> ctypes.c_void_p:
        """Creates an independent inference stream handle."""
        err = ctypes.c_char_p()
        s = self.dll.zf_tajweed_stream_create(self.model, ctypes.byref(err))
        if not s:
            err_msg = err.value.decode("utf-8") if err.value else "unknown error"
            raise RuntimeError(f"Failed to create TajweedFormer stream: {err_msg}")
        return s

    def destroy_stream(self, stream: ctypes.c_void_p) -> None:
        """Destroys an inference stream handle."""
        if stream and self.dll:
            self.dll.zf_tajweed_stream_destroy(stream)

    def __del__(self):
        if getattr(self, "model", None) and getattr(self, "dll", None):
            try:
                self.dll.zf_tajweed_model_close(self.model)
                self.model = None
            except Exception:
                pass

    def _decode_heads_to_phonemes(
        self,
        heads: _ZfTajweedHeads,
        top2_ptr: Any,
        n_frames: int,
        time_offset_s: float = 0.0,
        frame_offset: int = 0,
        is_recovered: bool = False,
    ) -> List[PhonemeToken]:
        """Clean 3-head neural decoding using TajweedFormer native layers:
        - Layer 15 (log_probs): Authoritative phoneme classification
        - 20ms H-time Chain (timing_log_probs): Continuous acoustic state chain (attack and held release)
        - 20ms Confidence Head (conf): Frame confidence
        """
        conf_logits = None
        if heads.n20 > 0 and heads.conf:
            conf_logits = np.ctypeslib.as_array(heads.conf, shape=(heads.n20,))

        tlp_arr = None
        if heads.n20 > 0 and heads.timing_log_probs:
            tlp_arr = np.ctypeslib.as_array(heads.timing_log_probs, shape=(heads.n20, heads.vocab))

        # Pre-group continuous acoustic runs from 20ms timing_log_probs (state != 0)
        timing_runs: List[Tuple[int, int, int]] = []
        if tlp_arr is not None:
            curr_r_tok = None
            r_start = 0
            for f in range(heads.n20):
                tok_f = int(np.argmax(tlp_arr[f]))
                if tok_f != curr_r_tok:
                    if curr_r_tok is not None and curr_r_tok != 0 and curr_r_tok in self.id2token:
                        timing_runs.append((curr_r_tok, r_start, f))
                    curr_r_tok = tok_f
                    r_start = f
            if curr_r_tok is not None and curr_r_tok != 0 and curr_r_tok in self.id2token:
                timing_runs.append((curr_r_tok, r_start, heads.n20))

        seg_phonemes: List[PhonemeToken] = []
        t = 0
        prev_end_20 = 0
        tr_cursor = 0

        while t < n_frames:
            curr_token_id = top2_ptr[t].token
            if curr_token_id == BLANK_ID or curr_token_id not in self.id2token:
                t += 1
                continue
            e = t
            while e + 1 < n_frames and top2_ptr[e + 1].token == curr_token_id:
                e += 1
            pk = t
            for k in range(t + 1, e + 1):
                if top2_ptr[k].log_prob > top2_ptr[pk].log_prob:
                    pk = k

            pk_top2 = top2_ptr[pk]

            # 40ms CTC frame span maps to base 20ms frames [2*t, 2*(e+1)]
            base_sf = 2 * t
            base_ef = 2 * (e + 1)

            # Monotonic alignment to physical 20ms H-time acoustic run
            # Find the physical run of curr_token_id that has maximum temporal overlap with CTC emission
            fine_sf = base_sf
            fine_ef = base_ef
            if timing_runs:
                best_idx = None
                best_overlap = -1
                for idx in range(tr_cursor, len(timing_runs)):
                    tr_tok, tr_s, tr_e = timing_runs[idx]
                    if tr_s > base_ef + 10:
                        break
                    if tr_tok == curr_token_id:
                        overlap = max(0, min(tr_e, base_ef) - max(tr_s, base_sf))
                        if overlap > best_overlap:
                            best_overlap = overlap
                            best_idx = idx

                if best_idx is not None and best_overlap > 0:
                    fine_sf = timing_runs[best_idx][1]
                    fine_ef = timing_runs[best_idx][2]
                    tr_cursor = best_idx + 1
                else:
                    # Fallback: closest matching run starting before or at base_ef
                    for idx in range(tr_cursor, len(timing_runs)):
                        tr_tok, tr_s, tr_e = timing_runs[idx]
                        if tr_tok == curr_token_id and tr_s <= base_ef:
                            fine_sf = tr_s
                            fine_ef = tr_e
                            tr_cursor = idx + 1
                            break

            fine_sf = max(prev_end_20, fine_sf)
            fine_ef = max(fine_sf + 1, fine_ef)
            prev_end_20 = fine_ef

            fine_pk = max(fine_sf, min(2 * pk, fine_ef))

            # Neural confidence: mean sigmoid over 20ms span [fine_sf : fine_ef]
            if conf_logits is not None and fine_ef <= len(conf_logits):
                span = conf_logits[fine_sf:fine_ef]
                conf = float(np.mean(1.0 / (1.0 + np.exp(-span))))
            else:
                conf = float(1.0 / (1.0 + math.exp(-pk_top2.margin)))

            seg_phonemes.append(
                PhonemeToken(
                    phoneme=self.id2token[curr_token_id],
                    start=round(time_offset_s + fine_sf * 0.020, 4),
                    end=round(time_offset_s + fine_ef * 0.020, 4),
                    confidence=round(conf, 4),
                    is_recovered=is_recovered,
                    start_frame=frame_offset + fine_sf,
                    end_frame=frame_offset + fine_ef,
                    peak_frame=frame_offset + fine_pk,
                    peak_timestamp=round(time_offset_s + fine_pk * 0.020, 4),
                    token_id=curr_token_id,
                    log_prob=round(float(pk_top2.log_prob), 4),
                    runner_up=int(pk_top2.runner_up),
                    runner_up_log_prob=round(float(pk_top2.runner_up_log_prob), 4),
                    margin=round(float(pk_top2.margin), 4),
                )
            )
            t = e + 1

        return seg_phonemes

    def _infer_stream(
        self,
        st: ctypes.c_void_p,
        pcm: np.ndarray,
        time_offset_s: float = 0.0,
        frame_offset: int = 0,
        is_recovered: bool = False,
        reset_stream: bool = True,
        return_heads: bool = False,
    ) -> Union[List[PhonemeToken], Tuple[List[PhonemeToken], Optional[np.ndarray], Optional[np.ndarray]]]:
        """Core inference worker: pushes PCM and decodes greedy tokens matching author engine tf_decode.c."""
        if len(pcm) == 0:
            return ([], None, None) if return_heads else []

        if not pcm.flags.c_contiguous:
            pcm = np.ascontiguousarray(pcm)

        if reset_stream:
            self.dll.zf_tajweed_stream_reset(st)
        self.dll.zf_tajweed_stream_set_heads(st, ACTIVE_HEADS_MASK)

        ptr = pcm.ctypes.data_as(ctypes.POINTER(ctypes.c_float))
        self.dll.zf_tajweed_stream_push_audio(st, ptr, len(pcm))
        self.dll.zf_tajweed_stream_finish(st)

        heads = _ZfTajweedHeads()
        self.dll.zf_tajweed_stream_heads(st, ctypes.byref(heads))

        top2_ptr = ctypes.POINTER(_ZfTajweedTop2)()
        n_frames = self.dll.zf_tajweed_stream_top2(st, ctypes.byref(top2_ptr))

        seg_phonemes = self._decode_heads_to_phonemes(
            heads=heads,
            top2_ptr=top2_ptr,
            n_frames=n_frames,
            time_offset_s=time_offset_s,
            frame_offset=frame_offset,
            is_recovered=is_recovered,
        )

        if return_heads:
            lp = np.ctypeslib.as_array(heads.log_probs, shape=(heads.n40, heads.vocab)).copy() if heads.n40 > 0 and heads.log_probs else None
            tlp = np.ctypeslib.as_array(heads.timing_log_probs, shape=(heads.n20, heads.vocab)).copy() if heads.n20 > 0 and heads.timing_log_probs else None
            return seg_phonemes, lp, tlp

        return seg_phonemes

    def transcribe_segment(
        self,
        segment_pcm: np.ndarray,
        sample_rate: int = SAMPLE_RATE,
        stream_handle: Optional[Any] = None,
    ) -> List[PhonemeToken]:
        """Transcribes a standalone audio slice (used directly by SpeechRecoveryEngine)."""
        if self.model is None or len(segment_pcm) == 0:
            return []
        own = stream_handle is None
        st = self.create_stream() if own else stream_handle
        try:
            return self._infer_stream(st, segment_pcm, is_recovered=True)
        finally:
            if own:
                self.destroy_stream(st)

    def transcribe_continuous(
        self,
        audio: np.ndarray,
        sample_rate: int = SAMPLE_RATE,
        on_progress: Optional[Callable[[float, float, float], None]] = None,
        return_matrices: Optional[bool] = None,
    ) -> RawTranscriptionResult:
        """Continuous whole-audio transcription matching author SDK / CLI tf_session_push exactly."""
        if self.model is None or len(audio) == 0:
            return RawTranscriptionResult(vocab_size=len(self.vocab))

        audio_pcm = np.ascontiguousarray(audio.astype(np.float32, copy=False))
        audio_dur = len(audio_pcm) / sample_rate
        need_matrices = getattr(config, "COLLECT_ACOUSTIC_MATRICES", False) if return_matrices is None else return_matrices

        t0 = time.time()
        st = self.create_stream()
        try:
            self.dll.zf_tajweed_stream_reset(st)
            self.dll.zf_tajweed_stream_set_heads(st, ACTIVE_HEADS_MASK)

            step = sample_rate // 50  # 20ms pushes matching cli/tajweedformer.c line 185
            n = len(audio_pcm)
            last_rep = 0.0
            for at in range(0, n, step):
                chunk = audio_pcm[at:min(n, at + step)]
                ptr = chunk.ctypes.data_as(ctypes.POINTER(ctypes.c_float))
                self.dll.zf_tajweed_stream_push_audio(st, ptr, len(chunk))
                if on_progress:
                    now = time.time()
                    if now - last_rep >= 0.25 or (at + step >= n):
                        last_rep = now
                        pct = min(100.0, (at / n) * 100.0)
                        elp = max(0.001, now - t0)
                        spd = (at / sample_rate) / elp
                        on_progress(pct, spd, elp)
            self.dll.zf_tajweed_stream_finish(st)

            heads = _ZfTajweedHeads()
            self.dll.zf_tajweed_stream_heads(st, ctypes.byref(heads))

            top2_ptr = ctypes.POINTER(_ZfTajweedTop2)()
            n40 = self.dll.zf_tajweed_stream_top2(st, ctypes.byref(top2_ptr))

            phonemes = self._decode_heads_to_phonemes(
                heads=heads,
                top2_ptr=top2_ptr,
                n_frames=n40,
                time_offset_s=0.0,
                frame_offset=0,
                is_recovered=False,
            )

            lp_mat = None
            tlp_mat = None
            if need_matrices:
                if heads.n40 > 0 and heads.log_probs:
                    lp_mat = np.ctypeslib.as_array(heads.log_probs, shape=(heads.n40, heads.vocab)).copy()
                if heads.n20 > 0 and heads.timing_log_probs:
                    tlp_mat = np.ctypeslib.as_array(heads.timing_log_probs, shape=(heads.n20, heads.vocab)).copy()

            # Direct pause extraction from inter-token silence runs (author waqf / sakt)
            pause_intervals: List[PauseInterval] = []
            pause_timestamps: List[float] = []
            min_pause_s = getattr(config, "VAD_MIN_PAUSE_S", 0.20)
            for i in range(len(phonemes) - 1):
                gap = phonemes[i + 1].start - phonemes[i].end
                if gap >= min_pause_s:
                    mid = round((phonemes[i].end + phonemes[i + 1].start) / 2.0, 3)
                    ptype = "waqf" if gap >= 0.45 else "sakt"
                    pause_intervals.append(
                        PauseInterval(
                            start_sec=round(phonemes[i].end, 3),
                            end_sec=round(phonemes[i + 1].start, 3),
                            duration_sec=round(gap, 3),
                            pause_type=ptype,
                            cut_point=mid,
                        )
                    )
                    pause_timestamps.append(mid)

            return RawTranscriptionResult(
                phonemes=phonemes,
                raw_tokens=[p.phoneme for p in phonemes],
                raw_timestamps=[p.start for p in phonemes],
                logprobs_matrix=lp_mat,
                timing_logprobs_matrix=tlp_mat,
                num_frames=heads.n20,
                vocab_size=len(self.vocab),
                pause_timestamps=pause_timestamps,
                pause_intervals=pause_intervals,
                vad_time=0.0,
            )
        finally:
            self.destroy_stream(st)

    def transcribe_audio(
        self,
        audio: np.ndarray,
        sample_rate: int = SAMPLE_RATE,
        on_progress: Optional[Callable[[float, float, float], None]] = None,
        on_vad_done: Optional[Callable[[float], None]] = None,
        reset_on_silence: Optional[bool] = None,
        return_matrices: Optional[bool] = None,
        stream_mode: bool = False,
    ) -> RawTranscriptionResult:
        """Phase 1: Direct C-Engine TajweedFormer Streaming (or VAD segmented if configured)."""
        if self.model is None or len(audio) == 0:
            return RawTranscriptionResult(vocab_size=len(self.vocab))

        audio_pcm = np.ascontiguousarray(audio.astype(np.float32, copy=False))
        audio_duration = len(audio_pcm) / sample_rate

        # When stream_mode is requested, stream whole audio continuously matching author SDK/CLI
        if stream_mode:
            if on_vad_done:
                on_vad_done(0.0)
            return self.transcribe_continuous(
                audio=audio_pcm,
                sample_rate=sample_rate,
                on_progress=on_progress,
                return_matrices=return_matrices,
            )

        # Phase 1: Unified Tajweed VAD Segmentation (Parallel / Segmented path)
        vad_start = time.time()
        vad = QuranSilenceVAD(sample_rate=sample_rate)
        segments, pause_intervals, pause_timestamps = vad.detect_speech_and_pauses(audio_pcm)
        vad_time = max(0.0, time.time() - vad_start)
        if on_vad_done: on_vad_done(vad_time)

        # Phase 2: TajweedFormer Streaming Transcription
        asr_start = time.time()
        vocab_size = len(self.vocab)
        total_frames = max(1, int(math.ceil(audio_duration / FRAME_STEP)))
        num_segments = len(segments)
        do_reset = getattr(config, "RESET_ENCODER_ON_SILENCE", True) if reset_on_silence is None else reset_on_silence
        need_matrices = getattr(config, "COLLECT_ACOUSTIC_MATRICES", False) if return_matrices is None else return_matrices

        def _worker_task(st, s_idx: int) -> Tuple[int, List[PhonemeToken], Optional[np.ndarray], Optional[np.ndarray]]:
            seg = segments[s_idx]
            s_sm = max(0, int(round(seg.padded_start_sec * sample_rate)))
            e_sm = min(len(audio_pcm), int(round(seg.padded_end_sec * sample_rate)))
            if need_matrices:
                ph, lp, tlp = self._infer_stream(
                    st,
                    audio_pcm[s_sm:e_sm],
                    time_offset_s=seg.padded_start_sec,
                    frame_offset=int(round(seg.padded_start_sec / FRAME_STEP)),
                    reset_stream=do_reset,
                    return_heads=True,
                )
            else:
                ph = self._infer_stream(
                    st,
                    audio_pcm[s_sm:e_sm],
                    time_offset_s=seg.padded_start_sec,
                    frame_offset=int(round(seg.padded_start_sec / FRAME_STEP)),
                    reset_stream=do_reset,
                    return_heads=False,
                )
                lp, tlp = None, None

            if ph and getattr(config, "SNAP_TO_VAD_SEGMENT_BOUNDARIES", True):
                # Lock first phoneme attack to the physical acoustic onset after breath pause (VAD cut)
                ph[0].start = round(seg.raw_start_sec, 4)
                ph[0].start_frame = int(round(seg.raw_start_sec / FRAME_STEP))
                if ph[0].end <= ph[0].start:
                    ph[0].end = round(ph[0].start + FRAME_STEP, 4)
                    ph[0].end_frame = ph[0].start_frame + 1

                # Lock the last phoneme release to the physical acoustic offset (VAD cut)
                ph[-1].end = round(seg.raw_end_sec, 4)
                ph[-1].end_frame = int(round(seg.raw_end_sec / FRAME_STEP))
                if ph[-1].start >= ph[-1].end:
                    ph[-1].start = max(0.0, round(ph[-1].end - FRAME_STEP, 4))
                    ph[-1].start_frame = max(0, ph[-1].end_frame - 1)

            return s_idx, ph, lp, tlp

        results_by_idx = [None] * num_segments

        env_workers = os.environ.get("SEGMENT_WORKERS")
        num_workers = int(env_workers) if env_workers is not None else getattr(config, "NUM_SEGMENT_WORKERS", 1)
        use_parallel = (num_workers > 1) and (num_segments > 2) and do_reset

        if use_parallel:
            pool_size = min(num_workers, num_segments)
            stream_pool: queue.Queue = queue.Queue()
            created_streams = []
            try:
                for _ in range(pool_size):
                    st = self.create_stream()
                    created_streams.append(st)
                    stream_pool.put(st)

                # LPT (Longest Processing Time first) scheduling for optimal worker utilization
                sorted_indices = sorted(range(num_segments), key=lambda idx: segments[idx].duration_sec, reverse=True)

                def _parallel_worker(s_idx: int):
                    st = stream_pool.get()
                    try:
                        return _worker_task(st, s_idx)
                    finally:
                        stream_pool.put(st)

                comp_dur = 0.0
                completed_count = 0
                with ThreadPoolExecutor(max_workers=pool_size) as executor:
                    futures = {executor.submit(_parallel_worker, i): i for i in sorted_indices}
                    for fut in as_completed(futures):
                        res = fut.result()
                        s_idx = res[0]
                        results_by_idx[s_idx] = res
                        completed_count += 1
                        if on_progress:
                            comp_dur += segments[s_idx].duration_sec
                            elp = max(0.001, time.time() - asr_start)
                            on_progress(min(100.0, (completed_count / max(1, num_segments)) * 100.0), comp_dur / elp, elp)
            finally:
                for st in created_streams:
                    try:
                        self.destroy_stream(st)
                    except Exception:
                        pass
        else:
            single_st = self.create_stream()
            try:
                comp_dur = 0.0
                for s_idx in range(num_segments):
                    res = _worker_task(single_st, s_idx)
                    results_by_idx[s_idx] = res
                    if on_progress:
                        comp_dur += segments[s_idx].duration_sec
                        elp = max(0.001, time.time() - asr_start)
                        on_progress(min(100.0, ((s_idx + 1) / max(1, num_segments)) * 100.0), comp_dur / elp, elp)
            finally:
                self.destroy_stream(single_st)

        # 3. Chronological Reassembly
        phonemes: List[PhonemeToken] = []
        assembled_lp = None
        assembled_tlp = None
        if need_matrices:
            total_40 = max(1, int(math.ceil(audio_duration / 0.040)))
            total_20 = total_40 * 2
            assembled_lp = np.full((total_40, vocab_size), -20.0, dtype=np.float32)
            assembled_tlp = np.full((total_20, vocab_size), -20.0, dtype=np.float32)

        for s_idx in range(num_segments):
            if not results_by_idx[s_idx]: continue
            _, seg_ph, lp, tlp = results_by_idx[s_idx]
            phonemes.extend(seg_ph)
            if need_matrices and lp is not None and tlp is not None:
                seg = segments[s_idx]
                f40_start = max(0, int(round(seg.padded_start_sec / 0.040)))
                f40_end = min(len(assembled_lp), f40_start + len(lp))
                assembled_lp[f40_start:f40_end] = lp[:f40_end - f40_start]

                f20_start = f40_start * 2
                f20_end = min(len(assembled_tlp), f20_start + len(tlp))
                assembled_tlp[f20_start:f20_end] = tlp[:f20_end - f20_start]

        phonemes.sort(key=lambda p: p.start)

        return RawTranscriptionResult(
            phonemes=phonemes,
            raw_tokens=[p.phoneme for p in phonemes],
            raw_timestamps=[p.start for p in phonemes],
            logprobs_matrix=assembled_lp,
            timing_logprobs_matrix=assembled_tlp,
            num_frames=total_frames,
            vocab_size=vocab_size,
            pause_timestamps=pause_timestamps,
            pause_intervals=pause_intervals,
            vad_time=vad_time,
        )


class SpeechRecoveryEngine:
    """Scans untranscribed acoustic gaps inside speech regions and recovers deleted phonemes.

    Guarantees:
      1. Boundary phoneme deduplication (prevents duplicating adjacent word edge tokens).
      2. Edge phoneme preservation (pre-roll padding + soft peak inclusion).
      3. Anti-glitch filtering (rejects single-token noise spikes).
      4. Trellis integrity (direct emission logprobs patching inside the gap).
    """

    @classmethod
    def recover_speech(
        cls,
        audio_pcm: np.ndarray,
        initial_phonemes: List[PhonemeToken],
        audio_duration: float,
        transcriber: TajweedFormerEngine,
        min_hole_duration_s: Optional[float] = None,
        sample_rate: int = SAMPLE_RATE,
        on_progress: Optional[Callable[[float, float], None]] = None,
        noise_floor_db: Optional[float] = None,
    ) -> SpeechRecoveryResult:
        start_time = time.time()
        min_hole_dur = min_hole_duration_s if min_hole_duration_s is not None else getattr(config, "SPEECH_RECOVERY_MIN_HOLE_DURATION_S", 1.40)
        pad_pre_s = getattr(config, "SPEECH_RECOVERY_PADDING_PRE_S", 0.16)
        pad_post_s = getattr(config, "SPEECH_RECOVERY_PADDING_POST_S", 0.24)
        min_tokens = getattr(config, "SPEECH_RECOVERY_MIN_PHONEMES_IN_GAP", 2)

        rec_mode = str(getattr(config, "SPEECH_RECOVERY_MODE", "legacy")).strip().lower()
        if not getattr(config, "ENABLE_SPEECH_RECOVERY", True) or rec_mode == "off":
            return SpeechRecoveryResult(
                recovered_phonemes=list(initial_phonemes),
                recovery_events=[],
                recovery_summary=RecoverySummary(0.0, 0, 0, 0, 0, 0.0, min_hole_dur),
            )

        energy_th = -55.0 if rec_mode == "legacy" else (float(noise_floor_db + 4.0) if noise_floor_db is not None else -38.0)
        candidate_gaps: List[Tuple[Optional[PhonemeToken], Optional[PhonemeToken], float, float]] = []

        # Null-safe gap extraction (head, interior, tail)
        if not initial_phonemes:
            if audio_duration >= min_hole_dur:
                candidate_gaps.append((None, None, 0.0, audio_duration))
        else:
            if initial_phonemes[0].start >= min_hole_dur:
                candidate_gaps.append((None, initial_phonemes[0], 0.0, initial_phonemes[0].start))
            for i in range(len(initial_phonemes) - 1):
                p_prev, p_next = initial_phonemes[i], initial_phonemes[i + 1]
                if (p_next.start - p_prev.end) >= min_hole_dur:
                    candidate_gaps.append((p_prev, p_next, p_prev.end, p_next.start))
            if (audio_duration - initial_phonemes[-1].end) >= min_hole_dur:
                candidate_gaps.append((initial_phonemes[-1], None, initial_phonemes[-1].end, audio_duration))

        num_gaps = len(candidate_gaps)
        results_by_idx: List[Optional[Tuple[List[PhonemeToken], float, float, float]]] = [None] * num_gaps

        def _transcribe_single_gap(g_idx: int, st=None):
            prev_tok, next_tok, g_s, g_e = candidate_gaps[g_idx]
            gap_pcm = audio_pcm[max(0, int(round(g_s * sample_rate))):min(len(audio_pcm), int(round(g_e * sample_rate)))]
            if len(gap_pcm) == 0:
                return g_idx, None

            # Skip digital silence / ambient room noise buffers
            rms = np.sqrt(np.mean(gap_pcm**2) + 1e-12)
            edb = float(20.0 * np.log10(max(rms, 1e-5)))
            if edb < energy_th:
                return g_idx, None

            p_start, p_end = max(0.0, g_s - pad_pre_s), min(audio_duration, g_e + pad_post_s)
            slice_pcm = audio_pcm[int(round(p_start * sample_rate)):int(round(p_end * sample_rate))]
            if len(slice_pcm) == 0:
                return g_idx, None

            raw_ph = transcriber.transcribe_segment(slice_pcm, stream_handle=st)
            if not raw_ph:
                return g_idx, None
            return g_idx, (raw_ph, edb, p_start, p_end)

        env_workers = os.environ.get("SEGMENT_WORKERS")
        num_workers = int(env_workers) if env_workers is not None else getattr(config, "NUM_SEGMENT_WORKERS", 1)
        use_parallel = (num_workers > 1) and (num_gaps > 2)

        if use_parallel:
            pool_size = min(num_workers, num_gaps)
            stream_pool: queue.Queue = queue.Queue()
            created_streams = []
            try:
                for _ in range(pool_size):
                    st = transcriber.create_stream()
                    created_streams.append(st)
                    stream_pool.put(st)

                def _parallel_gap_worker(g_idx: int):
                    st = stream_pool.get()
                    try:
                        return _transcribe_single_gap(g_idx, st)
                    finally:
                        stream_pool.put(st)

                completed_gaps = 0
                with ThreadPoolExecutor(max_workers=pool_size) as executor:
                    futures = {executor.submit(_parallel_gap_worker, g): g for g in range(num_gaps)}
                    for fut in as_completed(futures):
                        g_idx, res = fut.result()
                        results_by_idx[g_idx] = res
                        completed_gaps += 1
                        if on_progress:
                            on_progress(min(100.0, (completed_gaps / max(1, num_gaps)) * 100.0), max(0.001, time.time() - start_time))
            finally:
                for st in created_streams:
                    try:
                        transcriber.destroy_stream(st)
                    except Exception:
                        pass
        else:
            single_st = transcriber.create_stream()
            try:
                for g_idx in range(num_gaps):
                    _, res = _transcribe_single_gap(g_idx, single_st)
                    results_by_idx[g_idx] = res
                    if on_progress:
                        on_progress(min(100.0, ((g_idx + 1) / max(1, num_gaps)) * 100.0), max(0.001, time.time() - start_time))
            finally:
                transcriber.destroy_stream(single_st)

        recovery_events: List[RecoveryEvent] = []
        new_phonemes: List[PhonemeToken] = []
        speech_holes_detected = 0

        # Assembly and Monotonic Clamping
        for g_idx in range(num_gaps):
            gap_data = results_by_idx[g_idx]
            if not gap_data: continue

            prev_tok, next_tok, g_s, g_e = candidate_gaps[g_idx]
            raw_ph, edb, p_start, p_end = gap_data

            # Soft peak-based timestamp inclusion
            slice_tokens: List[PhonemeToken] = []
            for sp in raw_ph:
                r_pk = round(p_start + (sp.peak_timestamp or (sp.start + sp.end) / 2), 3)
                if (g_s - 0.08) <= r_pk <= (g_e + 0.08):
                    slice_tokens.append(
                        PhonemeToken(
                            phoneme=sp.phoneme,
                            start=round(p_start + sp.start, 3),
                            end=round(p_start + sp.end, 3),
                            confidence=sp.confidence,
                            is_recovered=True,
                            start_frame=int(round((p_start + sp.start) / FRAME_STEP)),
                            end_frame=int(round((p_start + sp.end) / FRAME_STEP)),
                            peak_frame=int(round(r_pk / FRAME_STEP)),
                            peak_timestamp=r_pk,
                        )
                    )

            if not slice_tokens: continue

            # Strict 1-token seam deduplication
            if prev_tok and slice_tokens and slice_tokens[0].phoneme == prev_tok.phoneme and abs(slice_tokens[0].start - prev_tok.start) < 0.20:
                slice_tokens.pop(0)
            if next_tok and slice_tokens and slice_tokens[-1].phoneme == next_tok.phoneme and abs(slice_tokens[-1].end - next_tok.end) < 0.20:
                slice_tokens.pop(-1)

            if len(slice_tokens) < min_tokens: continue

            speech_holes_detected += 1
            clamped: List[PhonemeToken] = []
            prev_t = prev_tok.end if prev_tok else 0.0

            for k, tok in enumerate(slice_tokens):
                c_start = max(tok.start, prev_t)
                c_end = max(c_start + 0.02, tok.end)
                if next_tok and k == len(slice_tokens) - 1:
                    c_end = min(c_end, next_tok.start)
                    c_start = min(c_start, c_end - 0.02)
                tok.start, tok.end = round(c_start, 3), round(c_end, 3)
                prev_t = tok.end
                clamped.append(tok)

            recovery_events.append(
                RecoveryEvent(
                    event_id=len(recovery_events) + 1,
                    gap_start=g_s,
                    gap_end=g_e,
                    gap_duration=g_e - g_s,
                    padded_start=p_start,
                    padded_end=p_end,
                    energy_db=edb,
                    recovered_text="".join(p.phoneme for p in clamped),
                    recovered_phonemes=clamped,
                )
            )
            new_phonemes.extend(clamped)

        all_phonemes = sorted(list(initial_phonemes) + new_phonemes, key=lambda p: p.start)
        summary = RecoverySummary(
            recovery_time_seconds=time.time() - start_time,
            scanned_gaps_count=len(candidate_gaps),
            speech_holes_detected=speech_holes_detected,
            recovered_events_count=len(recovery_events),
            recovered_phonemes_count=len(new_phonemes),
            energy_threshold_db=round(energy_th, 1),
            min_hole_duration_s=min_hole_dur,
        )

        return SpeechRecoveryResult(
            recovered_phonemes=all_phonemes,
            recovery_events=recovery_events,
            recovery_summary=summary,
        )

