"""Phase 2: CTC Viterbi Trellis Forced Alignment Engine."""

from __future__ import annotations

import math
import logging
from typing import Optional, List, Dict
import numpy as np

from config import (
    BLANK_ID,
    FRAME_RATE,
    FRAME_STEP,
    CTC_BLANK_PENALTY,
    LOOKAHEAD_OFFSET_FRAMES,
)
from src.models import PhonemeToken

logger = logging.getLogger(__name__)


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
                    end_frame=p.end_frame, peak_frame=p.peak_frame, peak_timestamp=p.peak_timestamp
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

        # 4. Viterbi Trellis with Reachability Bounds & Rolling 2 Rows
        backtrack = np.zeros((total_frames, l), dtype=np.uint8)
        v_prev = np.full(l, -1e30, dtype=np.float32)
        v_curr = np.full(l, -1e30, dtype=np.float32)

        v_prev[0] = lp[0, s_array[0]]
        if l > 1:
            v_prev[1] = lp[0, s_array[1]]

        for t in range(1, total_frames):
            s_min = max(0, l - 2 * (total_frames - t) - 2)
            s_max = min(l, 2 * t + 2)
            v_curr.fill(-1e30)

            span = s_max - s_min
            if span > 0:
                s_range = np.arange(s_min, s_max, dtype=np.int32)
                c0 = v_prev[s_range]

                c1 = np.full(span, -1e30, dtype=np.float32)
                valid_step = s_range > 0
                c1[valid_step] = v_prev[s_range[valid_step] - 1]

                c2 = np.full(span, -1e30, dtype=np.float32)
                valid_skip = (skip_mask[s_range] == 1)
                c2[valid_skip] = v_prev[s_range[valid_skip] - 2]

                max_v = c0.copy()
                best_step = np.zeros(span, dtype=np.uint8)

                step1_better = c1 > max_v
                max_v[step1_better] = c1[step1_better]
                best_step[step1_better] = 1

                step2_better = c2 > max_v
                max_v[step2_better] = c2[step2_better]
                best_step[step2_better] = 2

                backtrack[t, s_min:s_max] = best_step

                reachable = max_v > -1e29
                if np.any(reachable):
                    tok_classes = s_array[s_range[reachable]]
                    emit_logprob = lp[t, tok_classes].copy()
                    is_blank = (tok_classes == b_id)
                    emit_logprob[is_blank] -= CTC_BLANK_PENALTY
                    v_curr[s_range[reachable]] = max_v[reachable] + emit_logprob

            v_prev, v_curr = v_curr, v_prev

        # 5. Backtracking
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
                step = int(backtrack[t, curr_s])
                curr_s = max(0, curr_s - step)

        # 6. Extract Boundaries & Acoustic Confidence
        raw_starts = np.full(n, -1, dtype=np.int32)
        raw_ends = np.full(n, -1, dtype=np.int32)

        for t in range(total_frames):
            s = int(state_path[t])
            if s % 2 == 1:
                k = s // 2
                if k < n:
                    if raw_starts[k] == -1:
                        raw_starts[k] = t
                    raw_ends[k] = t

        peak_frames = np.empty(n, dtype=np.int32)
        peak_confidences = np.empty(n, dtype=np.float32)

        for k in range(n):
            s_f = int(raw_starts[k])
            e_f = int(raw_ends[k])
            tok_id = int(token_ids[k])

            if s_f != -1:
                best_f = s_f
                max_lp = -1e30
                for f in range(s_f, e_f + 1):
                    if state_path[f] == 2 * k + 1:
                        lp_val = float(lp[f, tok_id])
                        if lp_val > max_lp:
                            max_lp = lp_val
                            best_f = f
                peak_frames[k] = best_f

                frame_row = lp[best_f]
                mask = np.ones(cls.vocab_size, dtype=bool)
                mask[tok_id] = False
                runner_up = float(np.max(frame_row[mask])) if cls.vocab_size > 1 else -1e30
                peak_confidences[k] = max(0.1, max_lp - runner_up)
            else:
                fallback_pk = (
                    target_phonemes[k].peak_frame
                    if target_phonemes[k].peak_frame is not None
                    else int(round(target_phonemes[k].start * cls.frame_rate))
                )
                peak_frames[k] = int(np.clip(fallback_pk, 0, total_frames - 1))
                peak_confidences[k] = float(target_phonemes[k].confidence)

        token_starts = np.zeros(n, dtype=np.float64)
        token_ends = np.zeros(n, dtype=np.float64)
        token_starts[0] = 0.0

        for k in range(1, n):
            if raw_starts[k] == -1:
                token_starts[k] = token_ends[k - 1]
                token_ends[k] = token_starts[k]
                continue
            if raw_starts[k - 1] == -1:
                token_starts[k] = token_ends[k - 1]
                continue

            gap_start = int(raw_ends[k - 1] + 1)
            gap_end = int(raw_starts[k] - 1)

            if gap_end < gap_start:
                token_ends[k - 1] = float(raw_starts[k])
                token_starts[k] = float(raw_starts[k])
                continue

            prev_tok = int(token_ids[k - 1])
            curr_tok = int(token_ids[k])
            crossover = gap_start
            for t in range(gap_start, gap_end + 1):
                if lp[t, curr_tok] >= lp[t, prev_tok]:
                    crossover = t
                    break

            token_ends[k - 1] = float(crossover)
            token_starts[k] = float(crossover)

        if n > 0:
            token_ends[n - 1] = float(total_frames)

        lookahead = LOOKAHEAD_OFFSET_FRAMES
        aligned: List[PhonemeToken] = []

        for i in range(n):
            s_frame = max(0.0, token_starts[i] - lookahead)
            e_frame = max(s_frame + 0.5, token_ends[i] - lookahead)

            s_sec = min(audio_duration, s_frame * cls.frame_step)
            e_sec = min(audio_duration, max(s_sec + cls.frame_step, e_frame * cls.frame_step))
            pk_sec = min(audio_duration, float(peak_frames[i]) * cls.frame_step)

            aligned.append(
                PhonemeToken(
                    phoneme=target_phonemes[i].phoneme,
                    start=round(s_sec, 3),
                    end=round(e_sec, 3),
                    confidence=round(float(peak_confidences[i]), 2),
                    is_recovered=target_phonemes[i].is_recovered,
                    start_frame=int(round(s_frame)),
                    end_frame=int(round(e_frame)),
                    peak_frame=int(peak_frames[i]),
                    peak_timestamp=round(pk_sec, 3),
                )
            )

        return aligned
