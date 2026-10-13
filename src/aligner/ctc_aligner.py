"""Phase 2: CTC Viterbi Trellis Forced Alignment Engine.

Ultra-fast, high-precision acoustic forced alignment with Zipformer lookahead compensation,
canonical Tajweed sonorant handling, adaptive Viterbi trellising, and JIT-accelerated audio features.
"""

from __future__ import annotations

import math
from typing import Optional, List, Dict, Tuple
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


_MIN_PHONEME_DURATION_S = FRAME_STEP
_MIN_PHONEME_DURATION_FRAMES = 1.0

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
    total_frames: int,
    l: int,
    band_width: int,
    b_id: int,
    blank_penalty: float,
) -> Tuple[np.ndarray, np.ndarray]:
    """Unified exact/banded CTC Viterbi Trellis forward pass."""
    backtrack = np.zeros((total_frames, band_width), dtype=np.uint8)
    v_prev = np.full(l, -1e30, dtype=np.float32)
    v_curr = np.full(l, -1e30, dtype=np.float32)

    v_prev[0] = lp[0, s_array[0]]
    if l > 1:
        v_prev[1] = lp[0, s_array[1]]

    for t in range(1, total_frames):
        base = s_base[t]
        reach_min = max(0, l - 2 * (total_frames - t) - 2)
        reach_max = min(l, 2 * t + 2)
        s_start = max(base, reach_min)
        s_end = min(min(l, base + band_width), reach_max)

        v_curr[max(0, base - 2):min(l, base + band_width + 2)].fill(-1e30)

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
                v_curr[s] = max_v + emit

        v_prev, v_curr = v_curr, v_prev

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
        s_f = raw_starts[k]
        e_f = raw_ends[k]
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
    """Pre-compiles all JIT functions with dummy arrays so first audio run is instant."""
    try:
        lp = np.zeros((2, 251), dtype=np.float32)
        s_arr = np.zeros(3, dtype=np.int32)
        sk_m = np.zeros(3, dtype=np.uint8)
        s_b = np.zeros(2, dtype=np.int32)
        bt, vp = _ctc_viterbi_forward(lp, s_arr, sk_m, s_b, 2, 3, 3, 250, 0.5)
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
    ) -> List[PhonemeToken]:
        if not target_phonemes:
            return []

        b_id = custom_blank_id if custom_blank_id is not None else cls.default_blank_id
        n = len(target_phonemes)

        lp = logprobs_matrix
        if lp is not None and lp.ndim == 2:
            total_frames = lp.shape[0] if num_frames is None else num_frames
        elif lp is not None and lp.ndim == 1:
            total_frames = (len(lp) // cls.vocab_size) if num_frames is None else num_frames
            lp = lp.reshape(-1, cls.vocab_size)
        else:
            total_frames = int(math.ceil(audio_duration * cls.frame_rate)) if num_frames is None else num_frames

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

        # 1. Map target phonemes to token IDs
        token_ids = np.empty(n, dtype=np.int32)
        for i in range(n):
            token_ids[i] = token2id.get(target_phonemes[i].phoneme, b_id)

        # 2. Interleaved CTC state sequence: [blank, tok_0, blank, tok_1, ..., blank]
        l = 2 * n + 1
        s_array = np.empty(l, dtype=np.int32)
        for i in range(l):
            s_array[i] = b_id if (i % 2 == 0) else token_ids[i // 2]

        # 3. Skip mask: allow direct s-2 -> s when s is odd and S[s] != S[s-2]
        skip_mask = np.zeros(l, dtype=np.uint8)
        for s in range(3, l, 2):
            if s_array[s] != s_array[s - 2]:
                skip_mask[s] = 1

        # 4. Adaptive Banded Trellis (Expanded band_width for zero-trapping)
        # Use full exact trellis for l <= 512; generous 512 band when l > 512
        if l > 512:
            band_width = 512
            pk_frames = []
            pk_states = []
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
                pk_frames_arr = np.array(pk_frames, dtype=np.float64)
                pk_states_arr = np.array(pk_states, dtype=np.float64)
                all_frames = np.arange(total_frames, dtype=np.float64)
                s_guide = np.interp(all_frames, pk_frames_arr, pk_states_arr).astype(np.int32)

            s_base = np.clip(s_guide - (band_width // 2), 0, max(0, l - band_width)).astype(np.int32)
        else:
            band_width = l
            s_base = np.zeros(total_frames, dtype=np.int32)

        # Forward Trellis
        backtrack, v_prev = _ctc_viterbi_forward(
            lp=lp,
            s_array=s_array,
            skip_mask=skip_mask,
            s_base=s_base,
            total_frames=total_frames,
            l=l,
            band_width=band_width,
            b_id=b_id,
            blank_penalty=float(getattr(config, "CTC_BLANK_PENALTY", CTC_BLANK_PENALTY)),
        )

        # 5. Fast Backtracking & Boundary Extraction in Numba (Sub-millisecond)
        raw_starts, raw_ends, peak_frames, peak_confidences = _fast_backtrack_and_extract(
            backtrack=backtrack,
            s_base=s_base,
            v_prev=v_prev,
            lp=lp,
            token_ids=token_ids,
            total_frames=total_frames,
            l=l,
            band_width=band_width,
            n=n,
        )

        # Handle fallbacks if any state was unreached
        for k in range(n):
            if raw_starts[k] == -1:
                fallback_pk = (
                    target_phonemes[k].peak_frame
                    if target_phonemes[k].peak_frame is not None
                    else int(round(target_phonemes[k].start * cls.frame_rate))
                )
                peak_frames[k] = int(np.clip(fallback_pk, 0, total_frames - 1))
                peak_confidences[k] = float(target_phonemes[k].confidence)
                raw_starts[k] = peak_frames[k]
                raw_ends[k] = peak_frames[k]

        # 6. Direct Viterbi Path Extraction with Acoustic Grounding
        min_dur_s = _MIN_PHONEME_DURATION_S
        min_dur_f = _MIN_PHONEME_DURATION_FRAMES

        token_starts = np.zeros(n, dtype=np.float64)
        token_ends = np.zeros(n, dtype=np.float64)

        # First token onset: anchor to exact acoustic speech onset from Viterbi path
        token_starts[0] = float(max(0, raw_starts[0]))

        # 7. Exact Acoustic Boundaries across Tokens
        for k in range(1, n):
            gap_start = int(raw_ends[k - 1] + 1)
            gap_end = int(raw_starts[k] - 1)
            gap_s_sec = gap_start * cls.frame_step
            gap_e_sec = (gap_end + 1) * cls.frame_step

            # Check: confirmed VAD pause overlap (Waqf)
            matched_pause = None
            if pause_intervals:
                for p in pause_intervals:
                    if p.start_sec <= gap_e_sec and p.end_sec >= gap_s_sec:
                        overlap = min(gap_e_sec, p.end_sec) - max(gap_s_sec, p.start_sec)
                        if overlap >= 0.06 or p.duration_sec >= 0.15:
                            matched_pause = p
                            break

            if matched_pause is not None:
                p_start_f = int(round(matched_pause.start_sec / cls.frame_step))
                p_end_f = int(round(matched_pause.end_sec / cls.frame_step))
                end_f = float(max(raw_ends[k - 1] + 1, p_start_f))
                pk_f = float(peak_frames[k - 1])
                # Consonant release protection: if pause onset triggered prematurely during an occlusion dip
                # (less than 5 frames / 200ms after the acoustic peak), allow the stop consonant to complete
                # its natural physical release burst into the pause (up to 7 frames / 280ms or optimal cut point).
                if (end_f - pk_f) < 5:
                    opt_cut_f = int(round(matched_pause.optimal_cut_point / cls.frame_step))
                    release_f = min(pk_f + 7, float(opt_cut_f), float(p_end_f))
                    if release_f > end_f:
                        end_f = release_f
                token_ends[k - 1] = end_f
                token_starts[k] = float(min(raw_starts[k], max(p_end_f, raw_ends[k - 1] + 1)))
            else:
                # Continuous connected speech: token k begins immediately upon completion of token k-1 release
                token_ends[k - 1] = float(raw_ends[k - 1] + 1)
                token_starts[k] = token_ends[k - 1]

        # Final token offset from Viterbi path (guarantee release window if audio permits)
        last_pk_f = float(peak_frames[n - 1])
        last_e = float(min(total_frames, raw_ends[n - 1] + 1))
        if (last_e - last_pk_f) < 5:
            last_e = float(min(total_frames, last_pk_f + 7))
        token_ends[n - 1] = max(token_starts[n - 1] + min_dur_f, last_e)

        # 8. Convert frames to seconds
        lookahead = float(getattr(config, "LOOKAHEAD_OFFSET_FRAMES", LOOKAHEAD_OFFSET_FRAMES))

        s_secs = np.maximum(0.0, (token_starts - lookahead) * cls.frame_step)
        e_secs = np.maximum(s_secs + min_dur_s, (token_ends - lookahead) * cls.frame_step)
        pk_secs = np.maximum(0.0, (peak_frames - lookahead) * cls.frame_step)

        # 9. Clean Monotonicity (preserving true acoustic silence gaps)
        for k in range(1, n):
            if s_secs[k] < e_secs[k - 1]:
                s_secs[k] = e_secs[k - 1]
            if e_secs[k] < s_secs[k] + min_dur_s:
                e_secs[k] = s_secs[k] + min_dur_s

        # Pause protection for confirmed VAD pauses
        if pause_intervals:
            for p in pause_intervals:
                p_s = p.start_sec
                p_e = p.end_sec
                if p_e <= p_s:
                    continue
                cut = getattr(p, "optimal_cut_point", p_s)
                for k in range(n):
                    if p_s <= s_secs[k] < p_e:
                        s_secs[k] = p_e
                        if e_secs[k] <= s_secs[k]:
                            e_secs[k] = s_secs[k] + min_dur_s
                    elif p_s < e_secs[k] <= p_e:
                        # Allow natural stop consonant release burst into the pause (up to 280ms post-peak or optimal cut point)
                        max_allowed = max(p_s, min(cut, pk_secs[k] + 0.28))
                        if e_secs[k] > max_allowed:
                            e_secs[k] = max(s_secs[k] + min_dur_s, max_allowed)

        # 10. Construct final PhonemeToken outputs with zero overlap and preserved silence gaps
        aligned: List[PhonemeToken] = []
        for i in range(n):
            s_final = float(min(audio_duration, max(0.0, s_secs[i])))
            e_final = float(min(audio_duration, max(s_final + min_dur_s, e_secs[i])))
            pk_final = float(min(audio_duration, max(s_final, min(e_final, pk_secs[i]))))

            aligned.append(
                PhonemeToken(
                    phoneme=target_phonemes[i].phoneme,
                    start=round(s_final, 3),
                    end=round(e_final, 3),
                    confidence=round(float(peak_confidences[i]), 2),
                    is_recovered=target_phonemes[i].is_recovered,
                    start_frame=int(round(s_final / cls.frame_step)),
                    end_frame=int(round(e_final / cls.frame_step)),
                    peak_frame=int(peak_frames[i]),
                    peak_timestamp=round(pk_final, 3),
                    raw_start=target_phonemes[i].raw_start if target_phonemes[i].raw_start is not None else target_phonemes[i].start,
                    raw_end=target_phonemes[i].raw_end if target_phonemes[i].raw_end is not None else target_phonemes[i].end,
                )
            )

        return aligned
