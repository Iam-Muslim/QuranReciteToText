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
    """Domain-agnostic acoustic anchor behavior across CTC neural emission peaks.

    Enables any language or model architecture to declare how phoneme duration
    sits relative to its neural emission spike:
    - SUSTAINED_HOLD: Right-anchored. Blanks before peak are active speech hold (Madd/Ghunnah/long vowels).
    - GEMINATE_CLOSURE: Consonant occlusion before peak, release at/post peak (Shaddah/doubled consonants).
    - BURST_RELEASE: Plosive closure release with acoustic echo tail (Qalqalah/stops).
    - STANDARD_CV: Syllabic unit with onset articulation near peak and vowel decay post-peak.
    """
    SUSTAINED_HOLD = 0
    GEMINATE_CLOSURE = 1
    BURST_RELEASE = 2
    STANDARD_CV = 3


_MIN_PHONEME_DURATION_S = FRAME_STEP
_MIN_PHONEME_DURATION_FRAMES = 1.0

_MADD_GHUNNAH_SUBS = ('اا', 'ۦۦ', 'ۥۥ', 'ممم', 'ننن', 'ںںں', '۾۾۾', 'ييي', 'ووو')
_MADD_GHUNNAH_EXACT = {'ں', '۾', 'ۥ', 'ۦ', 'اااا', 'ااااا', 'اااااا'}


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


_classify_token_str = default_quran_token_classifier


def _trace_speech_onset_backward(
    frame_db: Optional[np.ndarray],
    pk_frame: int,
    earliest_frame: int,
    speech_th_db: float,
    default_frame: int,
) -> int:
    """Traces backwards from an acoustic emission peak to detect true physical speech onset.

    Acoustic Rationale:
    In initial consonants (e.g. 'ل', 'م', 'س', 'ء'), physical articulation begins at
    quiet energy levels (-44 dB to -38 dB) before the loud vowel peak (-20 dB).
    Searching backwards until energy drops into the silence floor captures the full
    consonant onset without premature truncation, while strictly stopping at the pause barrier.
    """
    if frame_db is None or pk_frame <= 0:
        return default_frame

    onset_f = default_frame
    for t in range(min(pk_frame, len(frame_db) - 1), max(0, earliest_frame) - 1, -1):
        if frame_db[t] >= speech_th_db:
            onset_f = t
        else:
            break  # Crossed into silence floor
    return onset_f


def _trace_speech_decay_forward(
    frame_db: Optional[np.ndarray],
    pk_frame: int,
    latest_frame: int,
    speech_th_db: float,
    default_frame: int,
) -> int:
    """Traces forwards from an acoustic emission peak to detect sound decay into pause.

    Acoustic Rationale:
    In verse-final words, reciters sustain final vowels, Tanween, or aspiration ('ه')
    for 200ms to 400ms after the CTC spike. Tracing forwards until energy drops below the
    speech floor captures the full acoustic release without cutting the word prematurely,
    while strictly bounded by the pause cut point (T_cut) so it never bleeds into the next verse.
    """
    if frame_db is None or pk_frame >= len(frame_db) - 1:
        return default_frame

    decay_f = default_frame
    for t in range(pk_frame + 1, min(latest_frame, len(frame_db))):
        if frame_db[t] >= speech_th_db:
            decay_f = t + 1
        else:
            break  # Sound has decayed into background silence
    return decay_f

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
        token_classifier: Optional[Callable[[str], AcousticAnchorType]] = None,
    ) -> List[PhonemeToken]:
        """Performs exact dynamic programming Viterbi forced alignment with Tajweed acoustic modeling.

        Acoustic Pipeline Overview:
        1. Viterbi Trellis DP: Finds globally optimal path through CTC emissions.
        2. Acoustic Energy Tracking: Traces backward/forward RMS contours to capture full
           consonant onsets and post-peak sound decay without premature cutoffs.
        3. Tajweed Articulatory Anchoring: Distinguishes sustained phonemes (Madd/Ghunnah),
           geminate occlusions (Shaddah), and plosive releases (Qalqalah).
        4. Monotonicity & Zero-Overlap Guarantee: Mathematically enforces non-overlapping
           continuous speech during Wasl while respecting clean pause boundaries during Waqf.
        """
        if not target_phonemes:
            return []

        # 0. Blank ID Discovery:
        # Priority: explicit custom_blank_id -> discovered blank token in vocabulary -> class default
        if custom_blank_id is not None:
            b_id = custom_blank_id
        else:
            b_id = token2id.get("<blank>", token2id.get("<blk>", token2id.get("_", cls.default_blank_id)))

        n = len(target_phonemes)

        lp = logprobs_matrix
        if lp is not None and lp.ndim == 2:
            total_frames = lp.shape[0] if num_frames is None else num_frames
        elif lp is not None and lp.ndim == 1:
            total_frames = (len(lp) // cls.vocab_size) if num_frames is None else num_frames
            lp = lp.reshape(-1, cls.vocab_size)
        else:
            total_frames = int(math.ceil(audio_duration * cls.frame_rate)) if num_frames is None else num_frames

        # Temporal Resolution:
        # Derive actual frame step from model emission shape. This guarantees mathematical
        # alignment if the underlying model is replaced (e.g. 40ms Zipformer, 20ms Conformer, 10ms Wav2Vec2).
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
                    else int(round(target_phonemes[k].start / actual_frame_step))
                )
                peak_frames[k] = int(np.clip(fallback_pk, 0, total_frames - 1))
                peak_confidences[k] = float(target_phonemes[k].confidence)
                raw_starts[k] = peak_frames[k]
                raw_ends[k] = peak_frames[k]

        # 6. Token Classification & Acoustic Energy Contour from audio_pcm
        classifier = token_classifier or default_quran_token_classifier
        token_classes = [classifier(target_phonemes[k].phoneme) for k in range(n)]

        frame_db = None
        speech_th_db = -40.0
        if audio_pcm is not None and len(audio_pcm) > 0:
            pcm_len = len(audio_pcm)
            f_len = int(round(actual_frame_step * 16000))
            n_audio_frames = min(total_frames, pcm_len // f_len)
            if n_audio_frames > 0:
                pcm_trunc = audio_pcm[:n_audio_frames * f_len].reshape(n_audio_frames, f_len)
                rms_arr = np.sqrt(np.mean(pcm_trunc ** 2, axis=1))
                frame_db = 20.0 * np.log10(np.maximum(1e-5, rms_arr))
                noise_floor = float(np.percentile(frame_db, 2))
                speech_th_db = min(-36.0, max(noise_floor + 6.0, -44.0))

        min_dur_s = actual_frame_step
        min_dur_f = 1.0

        token_starts = np.zeros(n, dtype=np.float64)
        token_ends = np.zeros(n, dtype=np.float64)

        # 1. Utterance-Initial Onset (Token 0): trace backwards up to 600ms (15 frames)
        token_starts[0] = float(max(0, _trace_speech_onset_backward(
            frame_db=frame_db,
            pk_frame=peak_frames[0],
            earliest_frame=max(0, peak_frames[0] - 15),
            speech_th_db=speech_th_db,
            default_frame=raw_starts[0],
        )))

        # 2. Token-Class-Aware Boundaries across Tokens
        for k in range(1, n):
            gap_start = int(raw_ends[k - 1] + 1)
            gap_end = int(raw_starts[k] - 1)
            gap_s_sec = gap_start * actual_frame_step
            gap_e_sec = (gap_end + 1) * actual_frame_step
            gap_frames = gap_end - gap_start + 1

            # Check confirmed VAD pause interval (Waqf)
            matched_pause = None
            if pause_intervals:
                for p in pause_intervals:
                    p_s = getattr(p, "start_sec", getattr(p, "start", 0.0))
                    p_e = getattr(p, "end_sec", getattr(p, "end", 0.0))
                    p_dur = getattr(p, "duration_sec", getattr(p, "duration", p_e - p_s))
                    if p_s <= gap_e_sec and p_e >= gap_s_sec:
                        overlap = min(gap_e_sec, p_e) - max(gap_s_sec, p_s)
                        if overlap >= 0.06 or p_dur >= 0.15:
                            matched_pause = p
                            break

            c_prev = token_classes[k - 1]
            c_curr = token_classes[k]
            pk_prev = peak_frames[k - 1]
            pk_curr = peak_frames[k]

            # Detect acoustic micro-pause (breath / Sakt with drop below speech threshold)
            is_micro_pause = False
            if matched_pause is None and gap_frames >= 6 and c_curr != AcousticAnchorType.SUSTAINED_HOLD:
                if frame_db is not None and gap_start < len(frame_db) and gap_end < len(frame_db):
                    if float(np.min(frame_db[gap_start:min(len(frame_db), gap_end + 1)])) < speech_th_db:
                        is_micro_pause = True

            if matched_pause is not None or is_micro_pause:
                # ─── PAUSE / BREATH GAP (Waqf / Sakt) ───
                # Determine click-free cut point barrier (T_cut)
                if matched_pause is not None:
                    p_cut = getattr(matched_pause, "optimal_cut_point", getattr(matched_pause, "cut_point", None))
                    if p_cut is None:
                        p_s = getattr(matched_pause, "start_sec", getattr(matched_pause, "start", 0.0))
                        p_e = getattr(matched_pause, "end_sec", getattr(matched_pause, "end", 0.0))
                        p_cut = (p_s + p_e) / 2.0
                    pause_barrier_f = int(round(p_cut / actual_frame_step))
                else:
                    pause_barrier_f = gap_start + max(1, gap_frames // 2)

                # End token k-1: trace forward acoustic energy decay into pause (bounded by T_cut)
                token_ends[k - 1] = float(_trace_speech_decay_forward(
                    frame_db=frame_db,
                    pk_frame=pk_prev,
                    latest_frame=pause_barrier_f,
                    speech_th_db=speech_th_db,
                    default_frame=min(pause_barrier_f, raw_ends[k - 1] + 2),
                ))

                # Start token k: trace backward acoustic speech onset from peak (bounded by T_cut)
                earliest_f = max(int(token_ends[k - 1]), pause_barrier_f)
                token_starts[k] = float(max(
                    token_ends[k - 1],
                    _trace_speech_onset_backward(
                        frame_db=frame_db,
                        pk_frame=pk_curr,
                        earliest_frame=earliest_f,
                        speech_th_db=speech_th_db,
                        default_frame=raw_starts[k],
                    ),
                ))

            else:
                # ─── CONTINUOUS CONNECTED SPEECH (Wasl inside phrase) ───
                if c_curr == AcousticAnchorType.SUSTAINED_HOLD:
                    # Sustained phoneme (Madd / Ghunnah / long vowel): absorbs pre-peak hold
                    token_ends[k - 1] = float(raw_ends[k - 1] + 1)
                    token_starts[k] = token_ends[k - 1]
                elif c_curr == AcousticAnchorType.GEMINATE_CLOSURE:
                    # Geminate closure (Shaddah): consonant occlusion before neural emission peak
                    shaddah_closure_f = max(raw_ends[k - 1] + 1, raw_starts[k] - 3)
                    token_ends[k - 1] = float(shaddah_closure_f)
                    token_starts[k] = float(shaddah_closure_f)
                elif c_curr == AcousticAnchorType.BURST_RELEASE:
                    # Burst release (Qalqalah / plosive stop): occlusion release before burst
                    token_ends[k - 1] = float(max(raw_ends[k - 1] + 1, raw_starts[k] - 2))
                    token_starts[k] = token_ends[k - 1]
                else:
                    # Standard CV: split intermediate blank frames at midpoint
                    if gap_frames > 0:
                        mid_f = int(round((raw_ends[k - 1] + raw_starts[k]) / 2.0))
                        token_ends[k - 1] = float(max(raw_ends[k - 1] + 1, mid_f))
                        token_starts[k] = token_ends[k - 1]
                    else:
                        token_ends[k - 1] = float(raw_ends[k - 1] + 1)
                        token_starts[k] = token_ends[k - 1]

        # 3. Final Token Offset: trace forward acoustic energy decay to sound completion
        token_ends[n - 1] = float(max(
            token_starts[n - 1] + min_dur_f,
            _trace_speech_decay_forward(
                frame_db=frame_db,
                pk_frame=peak_frames[n - 1],
                latest_frame=total_frames,
                speech_th_db=speech_th_db,
                default_frame=min(total_frames, raw_ends[n - 1] + 2),
            ),
        ))

        # 8. Convert frames to seconds using dynamic actual_frame_step
        lookahead = float(getattr(config, "LOOKAHEAD_OFFSET_FRAMES", LOOKAHEAD_OFFSET_FRAMES))

        s_secs = np.maximum(0.0, (token_starts - lookahead) * actual_frame_step)
        e_secs = np.maximum(s_secs + min_dur_s, (token_ends - lookahead) * actual_frame_step)
        pk_secs = np.maximum(0.0, (peak_frames - lookahead) * actual_frame_step)

        # 9. Pause protection: enforce click-free cut point boundary between phrases
        if pause_intervals:
            for p in pause_intervals:
                p_s = getattr(p, "start_sec", getattr(p, "start", 0.0))
                p_e = getattr(p, "end_sec", getattr(p, "end", 0.0))
                p_cut = getattr(p, "optimal_cut_point", getattr(p, "cut_point", (p_s + p_e) / 2.0))
                if p_e <= p_s:
                    continue
                for k in range(n):
                    # Pre-pause token cannot cross past cut point into next phrase
                    if s_secs[k] < p_cut and e_secs[k] > p_cut:
                        e_secs[k] = max(s_secs[k] + min_dur_s, p_cut)
                    # Post-pause token cannot start before cut point
                    elif p_s <= s_secs[k] < p_cut:
                        s_secs[k] = p_cut
                        if e_secs[k] <= s_secs[k]:
                            e_secs[k] = s_secs[k] + min_dur_s

        # 10. Strict Forward & Backward Monotonicity (Zero Overlap Guaranteed!)
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

        # 11. Construct final PhonemeToken outputs with zero overlap and preserved silence gaps
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
                    start_frame=int(round(s_final / actual_frame_step)),
                    end_frame=int(round(e_final / actual_frame_step)),
                    peak_frame=int(peak_frames[i]),
                    peak_timestamp=round(pk_final, 3),
                    raw_start=target_phonemes[i].raw_start if target_phonemes[i].raw_start is not None else target_phonemes[i].start,
                    raw_end=target_phonemes[i].raw_end if target_phonemes[i].raw_end is not None else target_phonemes[i].end,
                )
            )

        return aligned

