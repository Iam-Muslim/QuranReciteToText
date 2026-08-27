"""Phase 3: CTC Forced Alignment — Per-Word and Per-Phoneme Timestamp Extraction."""

from __future__ import annotations
import re
from typing import Optional
from functools import lru_cache
import numpy as np

from src.phase2_matching.normalize import tokenize_phoneme_string, get_phoneme_vocab_set, get_arabic_resources

BLANK_ID = 250
FRAME_RATE = 25.0  # 40ms per frame
FRAME_STEP = 1.0 / FRAME_RATE


@lru_cache(maxsize=1)
def get_loc_to_refword() -> dict[str, object]:
    """Pre-indexes all 77,430+ Quranic words by their location 'surah:ayah:word_num'."""
    resources = get_arabic_resources()
    return {
        f"{w.surah}:{w.ayah}:{w.word_num}": w
        for s, ch in resources.chapter_refs.items()
        for w in ch.words
    }


def _find_unmatched_affixes(transcribed_text: str, matched_text: str) -> tuple[list[str], list[str]]:
    """Finds prefix and suffix words from transcribed_text not aligned to matched_text."""
    if not transcribed_text or not matched_text:
        return [], []

    t_words = transcribed_text.split()
    m_words = matched_text.split()

    from src.phase2_matching.normalize import normalize_arabic
    t_norm = [normalize_arabic(w) for w in t_words]
    m_norm = [normalize_arabic(w) for w in m_words]

    import difflib
    sm = difflib.SequenceMatcher(None, t_norm, m_norm)
    opcodes = sm.get_opcodes()

    prefix, suffix = [], []
    if opcodes:
        tag, i1, i2, j1, j2 = opcodes[0]
        if tag == 'delete' and j1 == 0 and j2 == 0:
            prefix = t_words[i1:i2]

        tag, i1, i2, j1, j2 = opcodes[-1]
        if tag == 'delete' and j1 == len(m_norm) and j2 == len(m_norm):
            suffix = t_words[i1:i2]

    return prefix, suffix


def _load_vocab_and_mappings(tokens_path: str) -> tuple[list[str], dict[str, int]]:
    """Loads vocabulary and token-to-id mapping from tokens.txt."""
    id2token = {}
    token2id = {}
    with open(tokens_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.rsplit(" ", 1)
            if len(parts) == 2:
                tok, idx = parts[0], int(parts[1])
                id2token[idx] = tok
                token2id[tok] = idx
    max_id = max(id2token.keys()) if id2token else 250
    vocab = [id2token.get(i, "<blank>") for i in range(max_id + 1)]
    return vocab, token2id


def _tokenize_word(word: str, vocab_set: set[str], token2id: dict[str, int]) -> list[int]:
    """Tokenize a phoneme or text word into Zipformer token IDs."""
    ph_tokens = tokenize_phoneme_string(word, vocab_set)
    ids = [token2id[tok] for tok in ph_tokens if tok in token2id]
    return ids if ids else [0]


def _forced_align_chunk(log_probs_np: np.ndarray, token_ids: list[int]) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Runs Viterbi dynamic programming trellis forced alignment over logprobs.

    Returns (state_path, scores, log_probs, S) where:
      - state_path: per-frame best state index in the interleaved sequence
      - scores: per-frame log-prob of the chosen state
      - log_probs: the full (T, V) log-probability matrix
      - S: the interleaved state label array (blank, tok0, blank, tok1, ...)
    """
    lp = np.array(log_probs_np, dtype=np.float32)
    if lp.ndim == 3:
        lp = lp[0]
    T, V = lp.shape
    N = len(token_ids)

    if N == 0 or T < N:
        empty_S = np.full(1, BLANK_ID, dtype=np.int64)
        return np.zeros(T, dtype=np.int64), np.zeros(T, dtype=np.float32), lp, empty_S

    L = 2 * N + 1
    S = np.full(L, BLANK_ID, dtype=np.int64)
    S[1::2] = token_ids

    skip_mask = np.zeros(L, dtype=bool)
    for s in range(2, L):
        if S[s] != BLANK_ID and S[s] != S[s - 2]:
            skip_mask[s] = True

    V_trellis = np.full((T, L), -np.inf, dtype=np.float32)
    B = np.zeros((T, L), dtype=np.int32)

    V_trellis[0, 0] = lp[0, BLANK_ID]
    if L > 1:
        V_trellis[0, 1] = lp[0, S[1]]

    for t in range(1, T):
        prev = V_trellis[t - 1]
        v0 = prev
        v1 = np.empty_like(prev)
        v1[0] = -np.inf
        v1[1:] = prev[:-1]

        v2 = np.empty_like(prev)
        v2[:2] = -np.inf
        v2[2:] = prev[:-2]
        v2 = np.where(skip_mask, v2, -np.inf)

        stacked = np.stack([v0, v1, v2], axis=0)
        max_v = np.max(stacked, axis=0)
        idx_max = np.argmax(stacked, axis=0)

        B[t] = idx_max
        V_trellis[t] = max_v + lp[t, S]

    curr_s = L - 1 if V_trellis[T - 1, L - 1] > V_trellis[T - 1, L - 2] else L - 2
    state_path = np.zeros(T, dtype=np.int64)
    scores = np.zeros(T, dtype=np.float32)

    for t in range(T - 1, -1, -1):
        state_path[t] = curr_s
        scores[t] = lp[t, S[curr_s]]
        curr_s = curr_s - B[t, curr_s]

    return state_path, scores, lp, S


def _frames_to_word_times(
    state_path: np.ndarray,
    scores: np.ndarray,
    token_ids: list[int],
    word_token_counts: list[int],
    chunk_start_sec: float,
    seg_start_time: float,
    vocab: list[str] | None = None,
    log_probs: np.ndarray | None = None,
) -> list[dict]:
    """Converts CTC state trellis alignments into exact, non-overlapping word and phoneme spans.

    Uses Viterbi state-duration tracking with energy-weighted blank distribution
    and the model author's margin_peak confidence metric for stability across runtimes.
    Applies a -1.5 frame lookahead compensation to correct for streaming emission delay.
    """
    T = len(state_path)
    N = len(token_ids)

    # ── Streaming Lookahead Compensation ──
    # Zipformer2 streaming uses 130ms right-context (≈3.25 fbank frames → ~1.5 encoder
    # frames at 4× subsampling). CTC emission peaks are inherently delayed by this
    # lookahead. Shifting boundaries back by 1.5 frames (60ms) aligns the timestamps
    # with the physical acoustic onset in the waveform.
    LOOKAHEAD_OFFSET_FRAMES = 1.5

    active_frames = {}
    for k in range(N):
        target_state = 2 * k + 1
        active_frames[k] = np.where(state_path == target_state)[0]

    # Find raw activation bounds for each phoneme token
    raw_starts = np.full(N, -1, dtype=int)
    raw_ends = np.full(N, -1, dtype=int)

    for k in range(N):
        active = active_frames[k]
        if len(active) > 0:
            raw_starts[k] = active[0]
            raw_ends[k] = active[-1]

    # ── Energy-Weighted Blank Distribution ──
    # Instead of splitting blanks 50/50 between adjacent phonemes, we weight
    # the split proportionally to each phoneme's acoustic energy (number of
    # active non-blank frames). A long madd with 10 active frames gets more
    # of the trailing blanks than a short fatha with 1 frame.
    token_starts_f = np.zeros(N, dtype=float)
    token_ends_f = np.zeros(N, dtype=float)

    for k in range(N):
        if raw_starts[k] == -1:
            # Token had no active frames in the Viterbi path
            if k == 0:
                token_starts_f[k] = 0.0
                token_ends_f[k] = 0.0
            else:
                token_starts_f[k] = token_ends_f[k - 1]
                token_ends_f[k] = token_ends_f[k - 1]
            continue

        if k == 0:
            # First token absorbs all preceding blanks
            token_starts_f[k] = 0.0
        else:
            if raw_starts[k - 1] == -1:
                token_starts_f[k] = token_ends_f[k - 1]
            else:
                # Distribute intermediate blanks proportionally to active frame counts
                blank_start = raw_ends[k - 1] + 1
                blank_end = raw_starts[k] - 1
                if blank_end >= blank_start:
                    n_blanks = blank_end - blank_start + 1
                    dur_prev = len(active_frames[k - 1])
                    dur_curr = len(active_frames[k])
                    total_dur = dur_prev + dur_curr
                    if total_dur > 0:
                        # Heavier phoneme claims more of the blank gap
                        prev_share = dur_prev / total_dur
                    else:
                        prev_share = 0.5
                    split_point = blank_start + n_blanks * prev_share
                    token_starts_f[k] = float(split_point)
                else:
                    token_starts_f[k] = float(raw_starts[k])

    # Set end frames: each token ends where the next begins
    for k in range(N):
        if k == N - 1:
            # Last token absorbs all trailing blanks
            token_ends_f[k] = float(T)
        else:
            if raw_starts[k] != -1:
                token_ends_f[k] = token_starts_f[k + 1]

    # ── Apply Lookahead Offset ──
    # Shift all boundaries back to compensate for streaming emission delay.
    # Clamp to [0, T] to prevent negative or out-of-bounds timestamps.
    for k in range(N):
        token_starts_f[k] = max(0.0, token_starts_f[k] - LOOKAHEAD_OFFSET_FRAMES)
        token_ends_f[k] = max(0.0, token_ends_f[k] - LOOKAHEAD_OFFSET_FRAMES)

    # ── Build Word & Phoneme Output ──
    word_times: list[dict] = []
    tok_offset = 0

    for count in word_token_counts:
        if tok_offset >= N:
            break
        ws_f = token_starts_f[tok_offset]
        we_f = token_ends_f[tok_offset + count - 1]

        abs_ws = (ws_f * FRAME_STEP) + chunk_start_sec
        abs_we = (we_f * FRAME_STEP) + chunk_start_sec
        if abs_we < abs_ws:
            abs_ws, abs_we = abs_we, abs_ws

        rel_ws = max(0.0, abs_ws - seg_start_time)
        rel_we = max(0.0, abs_we - seg_start_time)

        phonemes_list = []
        token_confs = []
        for k in range(tok_offset, tok_offset + count):
            ps_f = token_starts_f[k]
            pe_f = token_ends_f[k]
            p_abs_ws = (ps_f * FRAME_STEP) + chunk_start_sec
            p_abs_we = (pe_f * FRAME_STEP) + chunk_start_sec
            if p_abs_we < p_abs_ws:
                p_abs_ws, p_abs_we = p_abs_we, p_abs_ws
            p_rel_ws = max(0.0, p_abs_ws - seg_start_time)
            p_rel_we = max(0.0, p_abs_we - seg_start_time)
            tok_id = token_ids[k]
            tok_str = vocab[tok_id] if vocab and tok_id < len(vocab) else ""

            # ── margin_peak Confidence ──
            act_f = active_frames[k]
            if len(act_f) > 0 and log_probs is not None:
                pk_rel = int(np.argmax(log_probs[act_f, tok_id]))
                pk_frame = act_f[pk_rel]
                p_conf_peak = float(np.exp(log_probs[pk_frame, tok_id]))
                p_conf = float(np.clip(p_conf_peak, 0.05, 0.99))
            elif len(act_f) > 0:
                p_logp = float(np.mean(scores[act_f]))
                p_conf = float(np.clip(np.exp(p_logp), 0.05, 0.99))
            else:
                p_conf = 0.50
            # Ensure strict non-overlapping sequential phonemes
            if len(phonemes_list) > 0 and p_rel_ws < phonemes_list[-1]["end"]:
                phonemes_list[-1]["end"] = round(p_rel_ws, 4)

            phonemes_list.append({
                "phoneme": tok_str,
                "start": round(p_rel_ws, 4),
                "end": round(p_rel_we, 4),
                "confidence": round(p_conf, 2),
            })

        w_conf = float(np.mean(token_confs)) if token_confs else 0.80
        word_times.append({
            "_start": rel_ws,
            "_end": rel_we,
            "_confidence": round(w_conf, 2),
            "_phonemes": phonemes_list,
        })
        tok_offset += count

    return word_times



def run_ctc_alignment(
    segments: list,
    stage_metrics: dict,
    vocab_path: str,
) -> None:
    """Fills seg.words for every segment using CTC forced alignment with Zipformer Tajweed phonemes."""
    _vocab, token2id = _load_vocab_and_mappings(vocab_path)
    vocab_set = get_phoneme_vocab_set()
    loc_to_refword = get_loc_to_refword()

    logprobs_list = stage_metrics.get("logprobs", [])
    asr_words_list = stage_metrics.get("asr_words", [])
    silence_intervals = stage_metrics.get("silence_intervals", [])

    if not logprobs_list:
        return

    for seg in segments:
        matched_text = seg.matched_text or ""
        transcribed_text = seg.transcribed_text or ""
        if not matched_text.strip():
            continue

        # Find the best matching chunk from logprobs_list based on start time
        best_idx = 0
        min_dist = float("inf")
        for i, lp_entry in enumerate(logprobs_list):
            chunk_start = lp_entry[1] if isinstance(lp_entry, tuple) else 0.0
            dist = abs(chunk_start - seg.start_time)
            if dist < min_dist:
                min_dist = dist
                best_idx = i
        idx = best_idx

        logprobs_entry = logprobs_list[idx]
        if isinstance(logprobs_entry, tuple):
            logprobs_np, chunk_start_sec = logprobs_entry
        else:
            logprobs_np, chunk_start_sec = logprobs_entry, seg.start_time

        if logprobs_np is None or len(logprobs_np) == 0:
            continue

        prefix_words, suffix_words = _find_unmatched_affixes(transcribed_text, matched_text)
        ref_words = matched_text.split()

        # ----------------------------------------------------------------
        # 1. Resolve exact locations for each ref_word
        # ----------------------------------------------------------------
        existing_locs: list[Optional[str]] = [w.get("location") for w in seg.words] if seg.words else []

        if not any(existing_locs):
            from qua_sdk.domain import SPECIAL_NAMES as ALL_SPECIAL_REFS
            if seg.matched_ref in ALL_SPECIAL_REFS:
                existing_locs = [f"0:0:{k+1}" for k in range(len(ref_words))]

        if not any(existing_locs) and seg.matched_ref and ":" in seg.matched_ref and "+" not in seg.matched_ref:
            from src.core.quran_index import get_quran_index
            from qua_sdk.domain import SPECIAL_TEXT, SPECIAL_NAMES as ALL_SPECIAL_REFS
            qi = get_quran_index()

            prefix_locs = []
            if seg.matched_ref not in ALL_SPECIAL_REFS and seg.matched_text:
                _BASMALA_TEXT = SPECIAL_TEXT.get("Basmala", "بسم الله الرحمن الرحيم")
                _ISTIATHA_TEXT = SPECIAL_TEXT.get("Isti'adha", "اعوذ بالله من الشيطان الرجيم")
                _COMBINED_TEXT = _ISTIATHA_TEXT + " ۝ " + _BASMALA_TEXT
                if seg.matched_text.startswith(_COMBINED_TEXT):
                    prefix_locs = [f"0:0:{k+1}" for k in range(len(_COMBINED_TEXT.split()))]
                elif seg.matched_text.startswith(_ISTIATHA_TEXT):
                    prefix_locs = [f"0:0:{k+1}" for k in range(len(_ISTIATHA_TEXT.split()))]
                elif seg.matched_text.startswith(_BASMALA_TEXT):
                    prefix_locs = [f"0:0:{k+1}" for k in range(len(_BASMALA_TEXT.split()))]

            def _get_locs(ref_from, ref_to):
                indices = qi.ref_to_indices(f"{ref_from}-{ref_to}")
                if not indices:
                    return []
                s, e = indices
                return [f"{qi.words[gi].surah}:{qi.words[gi].ayah}:{qi.words[gi].word}" for gi in range(s, e + 1)]

            if seg.wrap_word_ranges:
                parts = seg.matched_ref.split("-")
                ref_from, ref_to = parts[0], parts[1] if len(parts) > 1 else parts[0]
                sections = []
                if len(seg.wrap_word_ranges[0]) >= 3:
                    sections.append([ref_from, seg.wrap_word_ranges[0][1]])
                    for wr in seg.wrap_word_ranges:
                        sections.append([wr[0], wr[2]])
                else:
                    sections.append([ref_from, seg.wrap_word_ranges[0][1]])
                    for i_wr in range(len(seg.wrap_word_ranges) - 1):
                        sections.append([seg.wrap_word_ranges[i_wr][0], seg.wrap_word_ranges[i_wr + 1][1]])
                    sections.append([seg.wrap_word_ranges[-1][0], ref_to])

                seq_locs = []
                for s_ref, e_ref in sections:
                    seq_locs.extend(_get_locs(s_ref, e_ref))

                q_idx = 0
                aligned_locs = list(prefix_locs)
                for w in ref_words[len(prefix_locs):]:
                    if w in ["۞", "۩"] or w.startswith("۞") or w.startswith("۩"):
                        aligned_locs.append(None)
                    elif q_idx < len(seq_locs):
                        aligned_locs.append(seq_locs[q_idx])
                        q_idx += 1
                    else:
                        aligned_locs.append(None)
                existing_locs = aligned_locs
            else:
                indices = qi.ref_to_indices(seg.matched_ref)
                if indices:
                    s, e = indices
                    seq_locs = [f"{qi.words[gi].surah}:{qi.words[gi].ayah}:{qi.words[gi].word}" for gi in range(s, e + 1)]
                    q_idx = 0
                    aligned_locs = list(prefix_locs)
                    for w in ref_words[len(prefix_locs):]:
                        if w in ["۞", "۩"] or w.startswith("۞") or w.startswith("۩"):
                            aligned_locs.append(None)
                        elif q_idx < len(seq_locs):
                            aligned_locs.append(seq_locs[q_idx])
                            q_idx += 1
                        else:
                            aligned_locs.append(None)
                    existing_locs = aligned_locs

        while len(existing_locs) < len(ref_words):
            existing_locs.append(None)

        # ----------------------------------------------------------------
        # 2. Extract canonical phoneme token IDs using loc_to_refword
        # ----------------------------------------------------------------
        ref_word_token_ids = []
        ref_token_counts = []

        for w_idx, w_text in enumerate(ref_words):
            loc = existing_locs[w_idx] if w_idx < len(existing_locs) else None
            ref_word_obj = loc_to_refword.get(loc) if loc else None

            if ref_word_obj and hasattr(ref_word_obj, "phonemes") and ref_word_obj.phonemes:
                ph_tokens = ref_word_obj.phonemes
            else:
                ph_tokens = tokenize_phoneme_string(w_text, vocab_set)

            ids = [token2id[tok] for tok in ph_tokens if tok in token2id]
            if not ids:
                ids = [0]
            ref_word_token_ids.extend(ids)
            ref_token_counts.append(len(ids))

        prefix_token_ids = []
        prefix_token_counts = []
        for pw in prefix_words:
            ids = _tokenize_word(pw, vocab_set, token2id)
            prefix_token_ids.extend(ids)
            prefix_token_counts.append(len(ids))

        suffix_token_ids = []
        suffix_token_counts = []
        for sw in suffix_words:
            ids = _tokenize_word(sw, vocab_set, token2id)
            suffix_token_ids.extend(ids)
            suffix_token_counts.append(len(ids))

        full_token_ids = prefix_token_ids + ref_word_token_ids + suffix_token_ids
        full_word_token_counts = prefix_token_counts + ref_token_counts + suffix_token_counts

        if not full_token_ids:
            continue

        try:
            alignments, scores, chunk_lp, chunk_S = _forced_align_chunk(logprobs_np, full_token_ids)
        except Exception:
            continue

        full_word_times = _frames_to_word_times(
            alignments, scores, full_token_ids, full_word_token_counts,
            chunk_start_sec, seg.start_time, vocab=_vocab, log_probs=chunk_lp
        )
        start_idx = len(prefix_words)
        end_idx = len(prefix_words) + len(ref_words)

        word_times = full_word_times[start_idx:end_idx]
        while len(word_times) < len(ref_words):
            word_times.append({"_start": None, "_end": None})

        new_words = []
        for j, (word, wt) in enumerate(zip(ref_words, word_times)):
            if word in ["۞", "۩"] or word.startswith("۞") or word.startswith("۩"):
                continue
            entry: dict = {"word": word}
            loc = existing_locs[j] if j < len(existing_locs) else None
            if loc:
                entry["location"] = loc
            s, e = wt.get("_start"), wt.get("_end")
            entry["start"] = round(s, 4) if s is not None else None
            entry["end"] = round(e, 4) if e is not None else None
            conf = wt.get("_confidence")
            if conf is not None:
                entry["confidence"] = round(conf, 2)
            ph = wt.get("_phonemes")
            if ph:
                entry["phonemes"] = ph
            new_words.append(entry)


        seg.words = new_words
