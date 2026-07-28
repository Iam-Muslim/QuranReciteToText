"""
Phase 3: CTC Forced Alignment — Per-Word Timestamp Extraction.

This module uses the raw log-probability matrix (logprobs) produced by the
FastConformer ONNX model (shape: (1, T_enc, 1025)) to compute exact per-word
timestamps via CTC forced alignment (Viterbi).

Why this is correct:
- FastConformer encoder outputs 1 frame per 80ms (16000 / 160 / 8 = 12.5 fps).
- The logprobs matrix has T_enc frames, each representing exactly 80ms of audio.
- torchaudio.functional.forced_align runs the Viterbi algorithm on the logprobs,
  forcing the optimal frame-to-token assignment given the reference word sequence.
- This gives EXACT start/end frame indices per token → per word timestamps.

Why Phase 1 timestamps were wrong:
- Phase 1 did CTC argmax (greedy decode) frame-by-frame and recorded the first
  frame a token appeared. It set end = start + 80ms. This is wrong because:
  * A word can span many frames (multiple 80ms chunks).
  * Forced alignment uses Viterbi to assign ALL frames to tokens optimally.
  * Forced alignment respects the actual text reference, not the greedy path.

Input (from stage_metrics["logprobs"]):
    List of (logprobs_np, chunk_start_sec) tuples.
    - logprobs_np: np.ndarray shape (1, T_enc, 1025) from ONNX run
    - chunk_start_sec: absolute start time of this chunk in the full audio

Input (from segments):
    List of SegmentInfo objects (with words=None, matched_text set by Phase 2).

Output:
    Fills seg.words for each segment with per-word dicts:
    {"word": str, "location": str, "start": float, "end": float}
"""

from __future__ import annotations

import re
from typing import Optional

import numpy as np
import torch

# ─────────────────────────────────────────────────────────────────────────────
# Constants matching FastConformer architecture
# ─────────────────────────────────────────────────────────────────────────────
BLANK_ID   = 1024          # CTC blank is always the last class (vocab_size)
FRAME_RATE = 12.5          # encoder frames per second: 16000 / 160 / 8 = 12.5
FRAME_STEP = 1.0 / FRAME_RATE  # 0.08s per encoder frame

# Arabic diacritics to strip before tokenizing (model trained without them)
_DIAC_RE = re.compile(
    r'[\u0610-\u061a'
    r'\u064b-\u065f'
    r'\u0670'
    r'\u06d6-\u06dc'
    r'\u06df-\u06e4'
    r'\u06e7\u06e8'
    r'\u06ea-\u06ed]'
)


def _strip_diacritics(text: str) -> str:
    """Remove Arabic harakat / Quranic annotation marks."""
    return _DIAC_RE.sub('', text)


def _load_vocab(tokens_path: str) -> list[str]:
    """
    Load the FastConformer BPE vocabulary from tokens.txt.
    Format per line: '<token> <index>'
    """
    vocab = []
    with open(tokens_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.rstrip('\r\n')
            if line:
                # rsplit from right once to get token (handles tokens with spaces)
                parts = line.rsplit(' ', 1)
                vocab.append(parts[0])
    return vocab


def _build_char_to_id(vocab: list[str]) -> dict[str, int]:
    """
    Build a mapping from token string → token id.
    FastConformer BPE vocab uses '▁' as word-start marker.
    We index all tokens as-is so we can look them up during tokenization.
    """
    return {tok: idx for idx, tok in enumerate(vocab)}


def _tokenize_word(word: str, vocab: list[str], char_to_id: dict[str, int]) -> list[int]:
    """
    Greedy BPE tokenization of a single Arabic word using the FastConformer vocab.

    Strategy: try to match the longest prefix in the vocab (greedy longest match).
    Prepend '▁' to the first subword of each word (word-start marker).

    Returns list of token IDs.
    """
    plain = _strip_diacritics(word)
    if not plain:
        return []

    ids = []
    pos = 0
    first = True

    while pos < len(plain):
        # Try longest match first
        best_len = 0
        best_id  = -1

        for length in range(len(plain) - pos, 0, -1):
            candidate = plain[pos:pos + length]
            # Add word-start marker for the first subword of a word
            if first:
                tok_with_marker = '▁' + candidate
                if tok_with_marker in char_to_id:
                    best_len = length
                    best_id  = char_to_id[tok_with_marker]
                    break
            if candidate in char_to_id:
                best_len = length
                best_id  = char_to_id[candidate]
                break

        if best_id == -1:
            # Unknown character: skip
            pos += 1
            continue

        ids.append(best_id)
        pos   += best_len
        first  = False

    return ids


def _forced_align_chunk(
    log_probs_np: np.ndarray,   # shape (T_enc, vocab_size+1) or (1, T_enc, vocab_size)
    token_ids: list[int],
) -> tuple[np.ndarray, np.ndarray]:
    """
    Run torchaudio.functional.forced_align (Viterbi CTC alignment).

    Returns:
        alignments: np.ndarray shape (T_enc,) — state index per frame
        scores:     np.ndarray shape (T_enc,) — log-prob per frame
    """
    import torchaudio

    # Normalize shape → (T_enc, V)
    lp = np.array(log_probs_np, dtype=np.float32)
    if lp.ndim == 3:
        lp = lp[0]          # (T_enc, V)
    T, V = lp.shape

    N = len(token_ids)
    if N == 0:
        return np.zeros(T, dtype=np.int64), np.zeros(T, dtype=np.float32)

    # torchaudio expects (1, T, V) on CPU, float32
    lp_t = torch.from_numpy(lp).unsqueeze(0)   # (1, T, V)
    targets = torch.tensor(token_ids, dtype=torch.int32).unsqueeze(0)  # (1, N)
    input_lengths  = torch.tensor([T], dtype=torch.int32)
    target_lengths = torch.tensor([N], dtype=torch.int32)

    alignments, scores = torchaudio.functional.forced_align(
        log_probs=lp_t,
        targets=targets,
        input_lengths=input_lengths,
        target_lengths=target_lengths,
        blank=BLANK_ID,
    )
    return alignments[0].numpy(), scores[0].numpy()   # (T,), (T,)


def _frames_to_word_times(
    alignments: np.ndarray,   # (T,) label sequence from torchaudio.functional.forced_align
    scores:     np.ndarray,   # (T,) log-prob per frame
    token_ids:  list[int],
    word_token_counts: list[int],   # how many token ids belong to each word
    chunk_start_sec: float,
) -> list[dict]:
    """
    Convert frame-level CTC label sequence → word-level start/end times.
    
    torchaudio.functional.forced_align returns a sequence of the actual target labels,
    padded with BLANK_ID where appropriate.
    We scan the sequence to map frames to their respective token indices, then
    intelligently distribute the blank frames between adjacent tokens to ensure
    smooth boundaries.
    """
    T = len(alignments)
    N = len(token_ids)

    # 1. Map frames to token sequence
    token_frames = [[] for _ in range(N)]
    target_idx = 0
    prev_label = BLANK_ID

    for t in range(T):
        label = alignments[t]
        if label == BLANK_ID:
            prev_label = BLANK_ID
            continue

        if label == prev_label:
            # Continuation of the same token instance
            if target_idx < N:
                token_frames[target_idx].append(t)
        else:
            # Label changed (transition to the next token)
            if target_idx < N and len(token_frames[target_idx]) > 0:
                target_idx += 1
            if target_idx < N:
                token_frames[target_idx].append(t)
            prev_label = label

    # 2. Find core start/end frames for each token
    token_starts_f = []
    token_ends_f = []

    for i in range(N):
        if len(token_frames[i]) == 0:
            # Fallback if a token somehow got completely missed
            approx = int(i * T / max(N, 1))
            token_starts_f.append(approx)
            token_ends_f.append(approx)
        else:
            token_starts_f.append(token_frames[i][0])
            token_ends_f.append(token_frames[i][-1])

    # 3. Distribute blank frames between adjacent tokens
    # A word shouldn't expand infinitely into a long pause. Max expansion per token.
    MAX_EXPAND = 4  # max 320ms expansion into silence

    actual_starts_f = []
    actual_ends_f = []

    for i in range(N):
        core_start = token_starts_f[i]
        core_end = token_ends_f[i]

        # Expand start
        if i == 0:
            start_f = max(0, core_start - MAX_EXPAND)
        else:
            prev_end = token_ends_f[i - 1]
            gap = core_start - prev_end - 1
            if gap > 0:
                expand = min(gap // 2, MAX_EXPAND)
                start_f = core_start - expand
            else:
                start_f = core_start

        # Expand end
        if i == N - 1:
            end_f = min(T - 1, core_end + MAX_EXPAND)
        else:
            next_start = token_starts_f[i + 1]
            gap = next_start - core_end - 1
            if gap > 0:
                # The first half goes to this token (ceil division logic)
                expand = min(gap - (gap // 2), MAX_EXPAND)
                end_f = core_end + expand
            else:
                end_f = core_end

        actual_starts_f.append(start_f)
        actual_ends_f.append(end_f)

    # 4. Group tokens into words
    word_times: list[dict] = []
    tok_offset = 0

    for count in word_token_counts:
        if tok_offset >= N:
            break
            
        ws_f = actual_starts_f[tok_offset]
        we_f = actual_ends_f[tok_offset + count - 1]

        # Convert frames to absolute seconds
        ws = chunk_start_sec + ws_f * FRAME_STEP
        we = chunk_start_sec + (we_f + 1) * FRAME_STEP

        if we < ws:
            ws, we = we, ws

        word_times.append({"_start": ws, "_end": we})
        tok_offset += count

    return word_times


def run_ctc_alignment(
    segments: list,               # SegmentInfo objects with matched_text set
    stage_metrics: dict,          # from Phase 1: contains "logprobs" list
    vocab_path: str,              # path to tokens.txt
) -> None:
    """
    Main Phase 3 entry point.

    Fills seg.words for every segment that has a valid matched_text.
    Each word entry: {"word": str, "location": str|None, "start": float, "end": float}

    Args:
        segments:      List of SegmentInfo objects from Phase 2.
        stage_metrics: Dict containing "logprobs" (list of (np_array, start_sec)).
        vocab_path:    Absolute path to data/onnx/tokens.txt.
    """
    # Load vocabulary
    vocab       = _load_vocab(vocab_path)
    char_to_id  = _build_char_to_id(vocab)

    logprobs_list: list = stage_metrics.get("logprobs", [])

    if not logprobs_list:
        print("[Phase3] No logprobs in stage_metrics — skipping CTC alignment.")
        return

    print(f"[Phase3] CTC Forced Alignment on {len(segments)} segments...")

    # segments and logprobs_list are parallel (same index = same chunk)
    n = min(len(segments), len(logprobs_list))

    for i in range(n):
        seg = segments[i]

        matched_text = seg.matched_text or ""
        if not matched_text.strip():
            continue   # failed match → skip

        logprobs_entry = logprobs_list[i]
        if isinstance(logprobs_entry, tuple):
            logprobs_np, chunk_start_sec = logprobs_entry
        else:
            logprobs_np  = logprobs_entry
            chunk_start_sec = seg.start_time

        if logprobs_np is None:
            continue

        # Tokenize each word in the matched (reference) text
        ref_words = matched_text.split()
        token_ids: list[int]  = []
        word_token_counts: list[int] = []

        for word in ref_words:
            ids = _tokenize_word(word, vocab, char_to_id)
            if not ids:
                # Unknown word — use a single dummy id that won't match anything
                # We still need to reserve a slot so word count stays aligned
                ids = [0]
            token_ids.extend(ids)
            word_token_counts.append(len(ids))

        if not token_ids:
            continue

        # Run forced alignment
        try:
            alignments, scores = _forced_align_chunk(logprobs_np, token_ids)
        except Exception as e:
            print(f"[Phase3] Segment {i} forced_align failed: {e}")
            continue

        # Convert frames to word-level times
        word_times = _frames_to_word_times(
            alignments, scores, token_ids, word_token_counts, chunk_start_sec
        )

        if len(word_times) != len(ref_words):
            # Mismatch — tokenization issue; attach without location
            word_times = word_times[:len(ref_words)]
            while len(word_times) < len(ref_words):
                word_times.append({"_start": None, "_end": None})

        # Build final words list, attaching locations from seg.words if available
        # (Phase 2 sometimes stores location refs in seg.words when repetitions are detected)
        existing_locs: list[Optional[str]] = []
        if seg.words:
            existing_locs = [w.get("location") for w in seg.words]
            
        # If locations are still missing and we have a valid verse reference, pull them from QuranIndex
        if not any(existing_locs) and seg.matched_ref and ":" in seg.matched_ref and "+" not in seg.matched_ref:
            from src.core.quran_index import get_quran_index
            qi = get_quran_index()
            indices = qi.ref_to_indices(seg.matched_ref)
            if indices:
                start_idx, end_idx = indices
                if (end_idx - start_idx + 1) == len(ref_words):
                    existing_locs = [
                        f"{qi.words[gi].surah}:{qi.words[gi].ayah}:{qi.words[gi].word}"
                        for gi in range(start_idx, end_idx + 1)
                    ]
        
        while len(existing_locs) < len(ref_words):
            existing_locs.append(None)

        new_words = []
        for j, (word, wt) in enumerate(zip(ref_words, word_times)):
            entry: dict = {"word": word}
            loc = existing_locs[j] if j < len(existing_locs) else None
            if loc:
                entry["location"] = loc
            s = wt.get("_start")
            e = wt.get("_end")
            entry["start"] = round(s, 4) if s is not None else None
            entry["end"]   = round(e, 4) if e is not None else None
            new_words.append(entry)

        seg.words = new_words

    print("[Phase3] CTC Forced Alignment complete.")
