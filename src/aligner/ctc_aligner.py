"""Phase 2: CTC Viterbi Trellis Forced Alignment Engine.

Ultra-fast, high-precision acoustic forced alignment with Zipformer lookahead compensation,
canonical Tajweed sonorant handling, adaptive Viterbi trellising, and JIT-accelerated audio features.
"""

from __future__ import annotations

import math
from enum import IntEnum
from typing import Optional, List, Dict, Tuple, Callable
import numpy as np

import config
from config import (
    BLANK_ID,
    FRAME_RATE,
    FRAME_STEP,
    CTC_BLANK_PENALTY,
    LOOKAHEAD_OFFSET_FRAMES,
)
from src.models import PhonemeToken, PauseInterval


class AcousticAnchorType(IntEnum):
    """Domain-agnostic acoustic anchor behavior across CTC neural emission peaks:
    - SUSTAINED_HOLD: Right-anchored active speech hold (Madd/Ghunnah/long vowels).
    - GEMINATE_CLOSURE: Consonant occlusion before peak, release at/post peak (Shaddah).
    - BURST_RELEASE: Plosive closure release with acoustic echo tail (Qalqalah/stops).
    - STANDARD_CV: Syllabic unit with onset articulation near peak and vowel decay post-peak.
    """
    SUSTAINED_HOLD = 0
    GEMINATE_CLOSURE = 1
    BURST_RELEASE = 2
    STANDARD_CV = 3


_MADD_GHUNNAH_SUBS = ('اا', 'ۦۦ', 'ۥۥ', 'ممم', 'ننن', 'ںںں', '۾۾۾', 'ييي', 'ووو')
_MADD_GHUNNAH_EXACT = {'ں', '۾', 'ۥ', 'ۦ', 'اااا', 'ااااا', 'اااااا'}
_IDGHAM_INTO_NEXT_SUBS = ('ووو', 'ييي')


def default_quran_token_classifier(tok: str) -> AcousticAnchorType:
    """Classifies Quranic/Arabic phoneme tokens into physical acoustic anchor behaviors."""
    if 'ڇ' in tok:
        return AcousticAnchorType.BURST_RELEASE
    if any(m in tok for m in _MADD_GHUNNAH_SUBS) or tok in _MADD_GHUNNAH_EXACT:
        return AcousticAnchorType.SUSTAINED_HOLD
    base = [c for c in tok if c not in ('َ', 'ُ', 'ِ', 'ْ', 'ّ', 'ـ')]
    if len(base) >= 2 and base[0] == base[1]:
        return AcousticAnchorType.GEMINATE_CLOSURE
    return AcousticAnchorType.STANDARD_CV


def _get_pause_span(p: PauseInterval) -> Tuple[float, float, float]:
    """Extracts (start_sec, end_sec, cut_point) from a pause interval."""
    s = float(getattr(p, "start_sec", getattr(p, "start", 0.0)))
    e = float(getattr(p, "end_sec", getattr(p, "end", 0.0)))
    cut = float(getattr(p, "optimal_cut_point", getattr(p, "cut_point", (s + e) * 0.5)))
    return s, e, cut


def _compute_frame_db(audio_pcm: Optional[np.ndarray]) -> Tuple[Optional[np.ndarray], float]:
    """Computes 10ms high-resolution RMS dB envelope and speech threshold from 16kHz PCM."""
    if audio_pcm is None or len(audio_pcm) < 320:
        return None, -38.0
    f_hop, f_len = 160, 320
    n_frames = (len(audio_pcm) - f_len) // f_hop
    if n_frames <= 0:
        return None, -38.0
    strided = np.lib.stride_tricks.sliding_window_view(audio_pcm[:n_frames * f_hop + f_len], f_len)[::f_hop]
    rms_arr = np.sqrt(np.mean(strided ** 2, axis=-1))
    frame_db_10ms = 20.0 * np.log10(np.maximum(1e-5, rms_arr))
    noise_floor = float(np.percentile(frame_db_10ms, 2))
    speech_th_db = min(-26.0, max(noise_floor + 4.0, -46.0))
    return frame_db_10ms, speech_th_db


def _trace_speech_onset_backward(
    frame_db_10ms: Optional[np.ndarray],
    pk_sec: float,
    earliest_sec: float,
    speech_th_db: float,
    default_sec: float,
) -> float:
    """Traces backwards in 10ms steps to detect true physical speech onset."""
    if frame_db_10ms is None or pk_sec <= 0.0:
        return default_sec

    pk_idx = min(int(round(pk_sec / 0.010)), len(frame_db_10ms) - 1)
    earliest_idx = max(0, int(round(earliest_sec / 0.010)))
    if pk_idx <= earliest_idx:
        return default_sec

    onset_idx = pk_idx
    dip_count = 0
    for t in range(pk_idx, earliest_idx - 1, -1):
        if frame_db_10ms[t] >= speech_th_db:
            onset_idx = t
            dip_count = 0
        else:
            dip_count += 1
            if dip_count > 3:
                break
    return float(onset_idx * 0.010)


def _trace_speech_decay_forward(
    frame_db_10ms: Optional[np.ndarray],
    pk_sec: float,
    latest_sec: float,
    speech_th_db: float,
    default_sec: float,
    rel_drop_db: float = 0.0,
) -> float:
    """Traces forwards in 10ms steps to detect sound decay into pause."""
    if frame_db_10ms is None:
        return default_sec

    pk_idx = int(round(pk_sec / 0.010))
    latest_idx = min(int(round(latest_sec / 0.010)), len(frame_db_10ms))
    if pk_idx >= latest_idx:
        return default_sec

    decay_th_db = speech_th_db
    if rel_drop_db > 0.0 and 0 <= pk_idx < len(frame_db_10ms):
        decay_th_db = max(speech_th_db, float(frame_db_10ms[pk_idx]) - rel_drop_db)

    decay_idx = pk_idx
    dip_count = 0
    for t in range(pk_idx + 1, latest_idx):
        if frame_db_10ms[t] >= decay_th_db:
            decay_idx = t + 1
            dip_count = 0
        else:
            dip_count += 1
            if dip_count > 3:
                break
    return float(decay_idx * 0.010)


def _find_closure_onset(
    frame_db_10ms: Optional[np.ndarray],
    earliest_sec: float,
    pk_sec: float,
    drop_db: float = 10.0,
    min_s: float = 0.030,
    max_s: float = 0.400,
) -> Optional[float]:
    """Finds the onset of the last articulatory closure dip before a token's peak."""
    if frame_db_10ms is None:
        return None
    i0 = max(0, int(round(earliest_sec / 0.010)))
    i1 = min(int(round(pk_sec / 0.010)), len(frame_db_10ms) - 1)
    if i1 - i0 < 4:
        return None
    seg = frame_db_10ms[i0:i1 + 1]
    dip_th = float(np.median(seg)) - drop_db
    best = None
    run_start = -1
    for i in range(len(seg)):
        if seg[i] < dip_th:
            if run_start < 0:
                run_start = i
        else:
            if run_start > 0:
                run_len_s = (i - run_start) * 0.010
                if min_s <= run_len_s <= max_s:
                    best = run_start
            run_start = -1
    if best is None:
        return None
    return float((i0 + best) * 0.010 + 0.010)


try:
    from numba import njit
except ImportError:
    def njit(*args, **kwargs):
        def decorator(func):
            return func
        return decorator


@njit(fastmath=True, cache=True)
def _ctc_viterbi_forward(
    lp: np.ndarray,
    s_array: np.ndarray,
    skip_mask: np.ndarray,
    s_base: np.ndarray,
    dur_mu: np.ndarray,
    total_frames: int,
    l: int,
    band_width: int,
    b_id: int,
    blank_penalty: float,
    dur_lambda: float,
) -> Tuple[np.ndarray, np.ndarray]:
    """Unified exact/banded CTC Viterbi Trellis forward pass with duration prior."""
    backtrack = np.zeros((total_frames, band_width), dtype=np.uint8)
    age_prev = np.zeros(l, dtype=np.int32)
    age_curr = np.zeros(l, dtype=np.int32)
    v_prev = np.full(l, -1e30, dtype=np.float32)
    v_curr = np.full(l, -1e30, dtype=np.float32)

    v_prev[0] = lp[0, s_array[0]]
    if l > 1:
        v_prev[1] = lp[0, s_array[1]]
    age_prev[0] = 1
    if l > 1:
        age_prev[1] = 1

    for t in range(1, total_frames):
        base = s_base[t]
        reach_min = max(0, l - 2 * (total_frames - t) - 2)
        reach_max = min(l, 2 * t + 2)
        s_start = max(base, reach_min)
        s_end = min(min(l, base + band_width), reach_max)

        v_curr[max(0, base - 2):min(l, base + band_width + 2)].fill(-1e30)
        age_curr[max(0, base - 2):min(l, base + band_width + 2)].fill(0)

        for s in range(s_start, s_end):
            c0 = v_prev[s]
            c1 = v_prev[s - 1] if s > 0 else -1e30
            c2 = v_prev[s - 2] if (skip_mask[s] == 1 and s >= 2) else -1e30

            max_v = c0
            best_step = 0
            if c1 > max_v:
                max_v = c1
                best_step = 1
            if c2 > max_v:
                max_v = c2
                best_step = 2

            backtrack[t, s - base] = best_step

            if max_v > -1e29:
                tok_class = s_array[s]
                emit = lp[t, tok_class]
                if tok_class == b_id:
                    emit -= blank_penalty
                elif best_step == 0 and s % 2 == 1 and dur_lambda > 0.0:
                    emit -= dur_lambda * (age_prev[s] + 1 - dur_mu[s // 2])
                v_curr[s] = max_v + emit
                age_curr[s] = age_prev[s] + 1 if best_step == 0 else 1

        v_prev, v_curr = v_curr, v_prev
        age_prev, age_curr = age_curr, age_prev

    return backtrack, v_prev


@njit(fastmath=True, cache=True)
def _fast_backtrack_and_extract(
    backtrack: np.ndarray,
    s_base: np.ndarray,
    v_prev: np.ndarray,
    lp: np.ndarray,
    token_ids: np.ndarray,
    total_frames: int,
    l: int,
    band_width: int,
    n: int,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """C-speed backtracking and boundary extraction without array allocations in Python."""
    curr_s = l - 1
    if l > 1 and v_prev[l - 2] > v_prev[l - 1]:
        curr_s = l - 2

    if v_prev[curr_s] <= -1e29:
        max_score = -1e30
        for s in range(l - 1, -1, -1):
            if v_prev[s] > max_score:
                max_score = v_prev[s]
                curr_s = s

    state_path = np.empty(total_frames, dtype=np.int32)
    for t in range(total_frames - 1, -1, -1):
        state_path[t] = curr_s
        if t > 0:
            base = s_base[t]
            col = curr_s - base
            if 0 <= col < band_width:
                step = int(backtrack[t, col])
            elif curr_s > base + band_width - 1:
                step = 1
            else:
                step = 0
            curr_s = max(0, curr_s - step)

    raw_starts = np.full(n, -1, dtype=np.int32)
    raw_ends = np.full(n, -1, dtype=np.int32)
    for t in range(total_frames):
        s = state_path[t]
        if s % 2 == 1:
            k = s // 2
            if k < n:
                if raw_starts[k] == -1:
                    raw_starts[k] = t
                raw_ends[k] = t

    peak_frames = np.empty(n, dtype=np.int32)
    peak_confidences = np.empty(n, dtype=np.float32)
    for k in range(n):
        s_f, e_f = raw_starts[k], raw_ends[k]
        tok_id = token_ids[k]
        if s_f != -1:
            best_f = s_f
            max_lp = -1e30
            for f in range(s_f, e_f + 1):
                if state_path[f] == 2 * k + 1:
                    lp_val = lp[f, tok_id]
                    if lp_val > max_lp:
                        max_lp = lp_val
                        best_f = f
            peak_frames[k] = best_f

            runner_up = -1e30
            for c in range(lp.shape[1]):
                if c != tok_id:
                    v = lp[best_f, c]
                    if v > runner_up:
                        runner_up = v
            diff = max_lp - runner_up
            peak_confidences[k] = diff if diff > 0.1 else 0.1
        else:
            peak_frames[k] = -1
            peak_confidences[k] = 0.5

    return raw_starts, raw_ends, peak_frames, peak_confidences


def warmup_aligner_jit() -> None:
    """Pre-compiles JIT functions with dummy arrays so first audio run is instant."""
    try:
        lp = np.zeros((2, 251), dtype=np.float32)
        s_arr = np.zeros(3, dtype=np.int32)
        sk_m = np.zeros(3, dtype=np.uint8)
        s_b = np.zeros(2, dtype=np.int32)
        d_mu = np.zeros(1, dtype=np.float32)
        bt, vp = _ctc_viterbi_forward(lp, s_arr, sk_m, s_b, d_mu, 2, 3, 3, 250, 0.5, 0.0)
        _fast_backtrack_and_extract(bt, s_b, vp, lp, np.array([1], dtype=np.int32), 2, 3, 3, 1)
    except Exception:
        pass


class CtcViterbiAligner:
    """Exact dynamic programming Viterbi Trellis alignment over acoustic emission logprobs."""
    default_blank_id: int = BLANK_ID  # 250
    frame_rate: float = FRAME_RATE    # 25.0 Hz (40ms per frame)
    frame_step: float = FRAME_STEP    # 0.040s
    vocab_size: int = 251

    @classmethod
    def align_phonemes(
        cls,
        target_phonemes: List[PhonemeToken],
        audio_duration: float,
        token2id: Dict[str, int],
        logprobs_matrix: Optional[np.ndarray],
        num_frames: Optional[int] = None,
        custom_blank_id: Optional[int] = None,
        pause_intervals: Optional[List[PauseInterval]] = None,
        audio_pcm: Optional[np.ndarray] = None,
        token_classifier: Optional[Callable[[str], AcousticAnchorType]] = None,
    ) -> List[PhonemeToken]:
        """Performs exact DP Viterbi forced alignment with Tajweed acoustic modeling."""
        if not target_phonemes:
            return []

        b_id = custom_blank_id if custom_blank_id is not None else token2id.get("<blank>", token2id.get("<blk>", token2id.get("_", cls.default_blank_id)))
        n = len(target_phonemes)

        lp = logprobs_matrix
        if lp is not None and lp.ndim == 2:
            total_frames = lp.shape[0] if num_frames is None else num_frames
        elif lp is not None and lp.ndim == 1:
            total_frames = (len(lp) // cls.vocab_size) if num_frames is None else num_frames
            lp = lp.reshape(-1, cls.vocab_size)
        else:
            total_frames = int(math.ceil(audio_duration * cls.frame_rate)) if num_frames is None else num_frames

        actual_frame_step = (
            float(audio_duration) / float(total_frames)
            if (total_frames > 0 and audio_duration > 0)
            else cls.frame_step
        )

        if lp is None or total_frames <= 0 or lp.shape[0] < total_frames:
            return [
                PhonemeToken(
                    phoneme=p.phoneme, start=p.start, end=p.end, confidence=p.confidence,
                    is_recovered=p.is_recovered, start_frame=p.start_frame,
                    end_frame=p.end_frame, peak_frame=p.peak_frame, peak_timestamp=p.peak_timestamp,
                    raw_start=p.raw_start if p.raw_start is not None else p.start,
                    raw_end=p.raw_end if p.raw_end is not None else p.end,
                )
                for p in target_phonemes
            ]

        # Config pre-fetching (single lookup, zero inner-loop overhead)
        lookahead = float(getattr(config, "LOOKAHEAD_OFFSET_FRAMES", LOOKAHEAD_OFFSET_FRAMES))
        blank_penalty = float(getattr(config, "CTC_BLANK_PENALTY", CTC_BLANK_PENALTY))
        clamp_mode = str(getattr(config, "PAUSE_END_CLAMP_MODE", "cut"))
        micro_pause_gap = float(getattr(config, "MICRO_PAUSE_MIN_GAP_S", 0.28))
        pause_rel_drop = float(getattr(config, "PAUSE_DECAY_REL_DROP_DB", 0.0))
        final_rel_drop = float(getattr(config, "FINAL_DECAY_REL_DROP_DB", 14.0))
        final_trace_max_s = float(getattr(config, "FINAL_DECAY_TRACE_MAX_S", 0.800))
        w_switch, w_onset, w_prior = getattr(config, "INTERIOR_BOUNDARY_WEIGHTS", (0.55, 0.25, 0.20))

        # Vectorized CTC state arrays
        token_ids = np.array([token2id.get(p.phoneme, b_id) for p in target_phonemes], dtype=np.int32)
        l = 2 * n + 1
        s_array = np.full(l, b_id, dtype=np.int32)
        s_array[1::2] = token_ids
        skip_mask = np.zeros(l, dtype=np.uint8)
        if n > 1:
            skip_mask[3::2] = (token_ids[1:] != token_ids[:-1]).astype(np.uint8)

        # Adaptive Trellis Banding
        if l > 512:
            band_width = 512
            pk_frames, pk_states = [], []
            last_pk = -1
            for k in range(n):
                pk = target_phonemes[k].peak_frame
                if pk is not None and pk > last_pk:
                    pk_frames.append(pk)
                    pk_states.append(2 * k + 1)
                    last_pk = pk

            if len(pk_frames) < 2:
                s_guide = np.linspace(0, l - 1, total_frames, dtype=np.int32)
            else:
                s_guide = np.interp(
                    np.arange(total_frames, dtype=np.float64),
                    np.array(pk_frames, dtype=np.float64),
                    np.array(pk_states, dtype=np.float64),
                ).astype(np.int32)
            s_base = np.clip(s_guide - (band_width // 2), 0, max(0, l - band_width)).astype(np.int32)
        else:
            band_width = l
            s_base = np.zeros(total_frames, dtype=np.int32)

        # Token classification & duration prior
        classifier = token_classifier or default_quran_token_classifier
        token_classes = [classifier(target_phonemes[k].phoneme) for k in range(n)]

        dur_lambda = float(getattr(config, "CTC_DURATION_PRIOR_LAMBDA", 0.0)) if getattr(config, "CTC_DURATION_PRIOR_ENABLED", True) else 0.0
        dur_mu = np.zeros(n, dtype=np.float32)
        if dur_lambda > 0.0:
            mu_defaults = getattr(config, "CTC_DURATION_PRIOR_MU_FRAMES", (10.0, 2.0, 2.0, 3.0))
            for i, c in enumerate(token_classes):
                dur_mu[i] = float(mu_defaults[c])

        # Forward Trellis DP
        backtrack, v_prev = _ctc_viterbi_forward(
            lp=lp, s_array=s_array, skip_mask=skip_mask, s_base=s_base,
            dur_mu=dur_mu, total_frames=total_frames, l=l, band_width=band_width,
            b_id=b_id, blank_penalty=blank_penalty, dur_lambda=dur_lambda,
        )

        # Backtracking & Boundary Extraction
        raw_starts, raw_ends, peak_frames, peak_confidences = _fast_backtrack_and_extract(
            backtrack=backtrack, s_base=s_base, v_prev=v_prev, lp=lp,
            token_ids=token_ids, total_frames=total_frames, l=l, band_width=band_width, n=n,
        )

        for k in range(n):
            if raw_starts[k] == -1:
                pk_val = target_phonemes[k].peak_frame
                fb = pk_val if pk_val is not None else int(round(target_phonemes[k].start / actual_frame_step))
                peak_frames[k] = int(np.clip(fb, 0, total_frames - 1))
                peak_confidences[k] = float(target_phonemes[k].confidence)
                raw_starts[k] = raw_ends[k] = peak_frames[k]

        # Parabolic Sub-Frame Peak Fitting
        cont_peak_frames = peak_frames.astype(np.float64).copy()
        if lp is not None and lp.ndim == 2:
            for k in range(n):
                pk, tok = peak_frames[k], token_ids[k]
                if 0 < pk < total_frames - 1 and tok < lp.shape[1]:
                    y0, y1, y2 = float(lp[pk - 1, tok]), float(lp[pk, tok]), float(lp[pk + 1, tok])
                    denom = 2.0 * (y0 - 2.0 * y1 + y2)
                    if y1 > y0 and y1 > y2 and denom < -1e-6:
                        cont_peak_frames[k] = pk + float(np.clip((y0 - y2) / denom, -0.5, 0.5))

        # Sub-Frame Emission-Crossing Refinement
        refined_switch_s = None
        if lp is not None and lp.ndim == 2 and getattr(config, "EMISSION_CROSSING_REFINEMENT", True):
            refined_switch_s = np.full(n, np.nan, dtype=np.float64)
            for k in range(1, n):
                tk, tp = int(token_ids[k]), int(token_ids[k - 1])
                if tk == tp or tk >= lp.shape[1] or tp >= lp.shape[1]:
                    continue
                t0 = int(raw_starts[k])
                if t0 < 0:
                    continue
                lo, hi = max(0, t0 - 2), min(total_frames - 1, t0 + 1)
                d = lp[lo:hi + 1, tk] - lp[lo:hi + 1, tp]
                for i in range(len(d) - 1):
                    a, b = float(d[i]), float(d[i + 1])
                    if a < 0.0 <= b:
                        frac = (-a / (b - a)) if (b - a) > 1e-9 else 0.5
                        refined_switch_s[k] = (float(lo + i) + float(np.clip(frac, 0.0, 1.0)) - lookahead) * actual_frame_step
                        break

        # High-Resolution Acoustic Energy Contour
        frame_db_10ms, speech_th_db = _compute_frame_db(audio_pcm)
        min_dur_s = actual_frame_step

        s_secs = np.maximum(0.0, (raw_starts - lookahead) * actual_frame_step)
        e_secs = np.maximum(s_secs + min_dur_s, (raw_ends - lookahead) * actual_frame_step)
        pk_secs = np.maximum(0.0, (cont_peak_frames - lookahead) * actual_frame_step)

        # Token 0 onset
        s_secs[0] = max(0.0, _trace_speech_onset_backward(
            frame_db_10ms=frame_db_10ms,
            pk_sec=pk_secs[0],
            earliest_sec=max(0.0, pk_secs[0] - 0.600),
            speech_th_db=speech_th_db,
            default_sec=s_secs[0],
        ))

        # Token Boundaries across Sequence (Waqf vs Wasl)
        for k in range(1, n):
            gap_s_sec, gap_e_sec = e_secs[k - 1], s_secs[k]
            gap_dur = gap_e_sec - gap_s_sec

            matched_pause = None
            if pause_intervals:
                for p in pause_intervals:
                    p_s, p_e, _ = _get_pause_span(p)
                    if p_s <= gap_e_sec and p_e >= gap_s_sec:
                        overlap = min(gap_e_sec, p_e) - max(gap_s_sec, p_s)
                        if overlap >= 0.06 or (p_e - p_s) >= 0.15:
                            matched_pause = p
                            break

            c_prev, c_curr = token_classes[k - 1], token_classes[k]

            is_micro_pause = False
            if (
                matched_pause is None
                and gap_dur >= micro_pause_gap
                and c_curr not in (AcousticAnchorType.SUSTAINED_HOLD, AcousticAnchorType.GEMINATE_CLOSURE, AcousticAnchorType.BURST_RELEASE)
                and frame_db_10ms is not None
            ):
                g_idx_s, g_idx_e = int(round(gap_s_sec / 0.010)), int(round(gap_e_sec / 0.010))
                if 0 <= g_idx_s < len(frame_db_10ms) and 0 <= g_idx_e < len(frame_db_10ms) and g_idx_s < g_idx_e:
                    if float(np.min(frame_db_10ms[g_idx_s:g_idx_e + 1])) < speech_th_db:
                        is_micro_pause = True

            if matched_pause is not None or is_micro_pause:
                # ─── WAQF / SAKT PAUSE GAP ───
                if matched_pause is not None:
                    p_s, _, p_cut = _get_pause_span(matched_pause)
                    p_end_lim = p_s if clamp_mode != "cut" else p_cut
                    p_min_db = getattr(matched_pause, "min_energy_db", None)
                    local_th = speech_th_db if (p_min_db is None or math.isnan(p_min_db)) else min(speech_th_db, max(p_min_db + 4.0, -45.0))
                else:
                    p_cut = (gap_s_sec + gap_e_sec) * 0.5
                    p_end_lim = p_cut
                    local_th = speech_th_db

                e_secs[k - 1] = max(
                    s_secs[k - 1] + min_dur_s,
                    _trace_speech_decay_forward(
                        frame_db_10ms=frame_db_10ms,
                        pk_sec=pk_secs[k - 1],
                        latest_sec=p_end_lim,
                        speech_th_db=speech_th_db,
                        default_sec=min(p_end_lim, e_secs[k - 1] + 2 * actual_frame_step),
                        rel_drop_db=pause_rel_drop,
                    ),
                )
                earliest_s = max(e_secs[k - 1], p_cut)
                s_onset = _trace_speech_onset_backward(
                    frame_db_10ms=frame_db_10ms,
                    pk_sec=pk_secs[k],
                    earliest_sec=earliest_s,
                    speech_th_db=local_th,
                    default_sec=s_secs[k],
                )
                s_secs[k] = max(earliest_s, s_onset)
            else:
                # ─── WASL CONNECTED SPEECH ───
                lead = (3 if c_curr == AcousticAnchorType.GEMINATE_CLOSURE else 2) * actual_frame_step
                min_boundary = max(s_secs[k - 1] + min_dur_s, pk_secs[k - 1] + min_dur_s * 0.5)
                target_boundary = pk_secs[k] - lead

                if (c_prev == AcousticAnchorType.SUSTAINED_HOLD or
                        c_curr in (AcousticAnchorType.GEMINATE_CLOSURE, AcousticAnchorType.BURST_RELEASE)):
                    boundary = max(min_boundary, min(e_secs[k - 1], target_boundary))
                elif c_curr == AcousticAnchorType.SUSTAINED_HOLD and not any(
                    m in target_phonemes[k].phoneme for m in _IDGHAM_INTO_NEXT_SUBS
                ):
                    boundary = max(min_boundary, min(e_secs[k - 1] + actual_frame_step, target_boundary))
                else:
                    # Voiced-voiced interior transition fusion
                    gap = s_secs[k] - e_secs[k - 1]
                    ref_s = (e_secs[k - 1] + s_secs[k]) * 0.5 if gap > 0 else e_secs[k - 1]
                    prior_sec = max(min_boundary, min(ref_s, target_boundary))

                    switch_sec = s_secs[k]
                    if refined_switch_s is not None:
                        _rs = float(refined_switch_s[k])
                        if not math.isnan(_rs):
                            switch_sec = _rs

                    if frame_db_10ms is not None:
                        onset_sec = _trace_speech_onset_backward(
                            frame_db_10ms=frame_db_10ms,
                            pk_sec=pk_secs[k],
                            earliest_sec=max(s_secs[k] - 0.300, min_boundary),
                            speech_th_db=speech_th_db,
                            default_sec=switch_sec,
                        )
                        boundary = w_switch * switch_sec + w_onset * onset_sec + w_prior * prior_sec
                    else:
                        boundary = w_switch * switch_sec + w_prior * prior_sec
                    boundary = max(min_boundary, min(boundary, target_boundary))

                if c_curr != AcousticAnchorType.SUSTAINED_HOLD:
                    closure_sec = _find_closure_onset(
                        frame_db_10ms=frame_db_10ms,
                        earliest_sec=pk_secs[k - 1] + min_dur_s * 0.5,
                        pk_sec=pk_secs[k],
                    )
                    if closure_sec is not None:
                        boundary = max(min_boundary, min(boundary, closure_sec))

                # Hard invariant: retain at least 0.5 frame before emission peak
                boundary = min(boundary, max(min_boundary, pk_secs[k] - actual_frame_step * 0.5))
                e_secs[k - 1] = boundary
                s_secs[k] = boundary

        # Final Token Offset Decay
        e_secs[n - 1] = max(
            s_secs[n - 1] + min_dur_s,
            _trace_speech_decay_forward(
                frame_db_10ms=frame_db_10ms,
                pk_sec=pk_secs[n - 1],
                latest_sec=min(audio_duration, pk_secs[n - 1] + final_trace_max_s),
                speech_th_db=speech_th_db,
                default_sec=min(audio_duration, e_secs[n - 1] + 2 * actual_frame_step),
                rel_drop_db=final_rel_drop,
            ),
        )

        # Pause protection: enforce click-free cut point boundary between phrases
        if pause_intervals:
            for p in pause_intervals:
                p_s, p_e, p_cut = _get_pause_span(p)
                if p_e <= p_s:
                    continue
                pre_pause_clamp = p_s if clamp_mode == "start" else p_cut
                for k in range(n):
                    if s_secs[k] < p_cut < e_secs[k]:
                        e_secs[k] = max(s_secs[k] + min_dur_s, pre_pause_clamp)
                    elif p_s <= s_secs[k] < p_cut:
                        s_secs[k] = p_cut
                        if e_secs[k] <= s_secs[k]:
                            e_secs[k] = s_secs[k] + min_dur_s

        # Strict forward and backward monotonicity (Zero Overlap Guaranteed!)
        for k in range(1, n):
            if s_secs[k] < e_secs[k - 1]:
                s_secs[k] = e_secs[k - 1]
            if e_secs[k] < s_secs[k] + min_dur_s:
                e_secs[k] = s_secs[k] + min_dur_s

        for k in range(n - 2, -1, -1):
            if e_secs[k] > s_secs[k + 1]:
                e_secs[k] = s_secs[k + 1]
            if s_secs[k] > e_secs[k] - min_dur_s:
                s_secs[k] = max(0.0, e_secs[k] - min_dur_s)

        # Output PhonemeToken construction
        aligned: List[PhonemeToken] = []
        for i in range(n):
            s_final = float(min(audio_duration, max(0.0, s_secs[i])))
            e_final = float(min(audio_duration, max(s_final + min_dur_s, e_secs[i])))
            pk_final = float(min(audio_duration, max(s_final, min(e_final, pk_secs[i]))))
            p_orig = target_phonemes[i]

            aligned.append(
                PhonemeToken(
                    phoneme=p_orig.phoneme,
                    start=round(s_final, 3),
                    end=round(e_final, 3),
                    confidence=round(float(peak_confidences[i]), 2),
                    is_recovered=p_orig.is_recovered,
                    start_frame=int(round(s_final / actual_frame_step)),
                    end_frame=int(round(e_final / actual_frame_step)),
                    peak_frame=int(peak_frames[i]),
                    peak_timestamp=round(pk_final, 3),
                    raw_start=p_orig.raw_start if p_orig.raw_start is not None else p_orig.start,
                    raw_end=p_orig.raw_end if p_orig.raw_end is not None else p_orig.end,
                )
            )

        return aligned
