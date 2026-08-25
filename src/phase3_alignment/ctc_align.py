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

_DIAC_RE = re.compile(r'[\u0610-\u061a\u064b-\u065f\u0670\u06d6-\u06dc\u06df-\u06e4\u06e7\u06e8\u06ea-\u06ed]')


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


def _map_asr_words_to_reference(
    asr_words: list[dict], ref_words: list[str]
) -> tuple[dict[int, dict], set[int]]:
    """Maps ASR words to canonical indices and returns unambiguously missing indices."""
    if not asr_words or not ref_words:
        return {}, set()

    from src.phase2_matching.normalize import normalize_arabic
    import difflib

    asr_norm = [normalize_arabic(word.get("word", word.get("phoneme", ""))) for word in asr_words]
    ref_norm = [normalize_arabic(word) for word in ref_words]
    mapping: dict[int, dict] = {}
    missing: set[int] = set()

    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(
        None, asr_norm, ref_norm, autojunk=False
    ).get_opcodes():
        if tag == "insert":
            missing.update(range(j1, j2))
        elif tag == "equal" or (tag == "replace" and i2 - i1 == j2 - j1):
            for asr_index, ref_index in zip(range(i1, i2), range(j1, j2)):
                mapping[ref_index] = asr_words[asr_index]

    return mapping, missing


def _strip_diacritics(text: str) -> str:
    return _DIAC_RE.sub('', text)


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


def _forced_align_chunk(log_probs_np: np.ndarray, token_ids: list[int]) -> tuple[np.ndarray, np.ndarray]:
    """Runs Viterbi dynamic programming trellis forced alignment over logprobs."""
    lp = np.array(log_probs_np, dtype=np.float32)
    if lp.ndim == 3:
        lp = lp[0]
    T, V = lp.shape
    N = len(token_ids)

    if N == 0 or T < N:
        return np.zeros(T, dtype=np.int64), np.zeros(T, dtype=np.float32)

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

    return state_path, scores


def _frames_to_word_times(
    state_path: np.ndarray,
    scores: np.ndarray,
    token_ids: list[int],
    word_token_counts: list[int],
    chunk_start_sec: float,
    seg_start_time: float,
    vocab: list[str] | None = None,
) -> list[dict]:
    """Converts CTC state trellis alignments into exact, non-overlapping word and phoneme spans."""
    T = len(state_path)
    N = len(token_ids)

    active_frames = {}
    for k in range(N):
        target_state = 2 * k + 1
        active_frames[k] = np.where(state_path == target_state)[0]

    # Find peak frame for each token from active Viterbi states
    peak_frames = np.zeros(N, dtype=float)
    for k in range(N):
        target_state = 2 * k + 1
        f_list = active_frames[k]
        if len(f_list) > 0:
            pk_idx = int(np.argmax(scores[f_list]))
            peak_frames[k] = float(f_list[pk_idx])
        else:
            peak_frames[k] = float(k * T / max(N, 1))

    # Midpoint acoustic boundary assignment within each word
    token_starts_f = np.zeros(N, dtype=float)
    token_ends_f = np.zeros(N, dtype=float)

    tok_offset = 0
    for count in word_token_counts:
        first_k = tok_offset
        last_k = tok_offset + count - 1

        first_active = active_frames[first_k]
        last_active = active_frames[last_k]

        w_start_f = float(first_active[0]) if len(first_active) > 0 else peak_frames[first_k]
        w_end_f = float(last_active[-1] + 1) if len(last_active) > 0 else peak_frames[last_k] + 1.0

        for i in range(count):
            k = first_k + i
            if i == 0:
                s_f = w_start_f
            else:
                s_f = token_ends_f[k - 1]

            if i == count - 1:
                e_f = w_end_f
            else:
                next_k = k + 1
                # Exact midpoint transition between peak energy of token k and token k+1
                mid_f = (peak_frames[k] + peak_frames[next_k]) / 2.0
                e_f = max(s_f + 0.5, mid_f)

            token_starts_f[k] = s_f
            token_ends_f[k] = max(s_f + 0.5, e_f)

        tok_offset += count

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

            # Compute acoustic confidence from CTC frame log-probabilities
            act_f = active_frames[k]
            if len(act_f) > 0:
                p_logp = float(np.mean(scores[act_f]))
                p_conf = float(np.clip(np.exp(p_logp), 0.05, 0.99))
            else:
                p_conf = 0.50
            token_confs.append(p_conf)

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

    n = min(len(segments), len(logprobs_list))

    for i in range(n):
        seg = segments[i]
        matched_text = seg.matched_text or ""
        transcribed_text = seg.transcribed_text or ""
        if not matched_text.strip():
            continue

        logprobs_entry = logprobs_list[i]
        if isinstance(logprobs_entry, tuple):
            logprobs_np, chunk_start_sec = logprobs_entry
        else:
            logprobs_np, chunk_start_sec = logprobs_entry, seg.start_time

        if logprobs_np is None or len(logprobs_np) == 0:
            continue

        prefix_words, suffix_words = _find_unmatched_affixes(transcribed_text, matched_text)
        ref_words = matched_text.split()
        asr_words_entry = asr_words_list[i] if i < len(asr_words_list) else None
        asr_words = asr_words_entry[0] if isinstance(asr_words_entry, tuple) else asr_words_entry
        asr_word_mapping, missing_word_indices = _map_asr_words_to_reference(
            asr_words or [], ref_words
        )

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
            alignments, scores = _forced_align_chunk(logprobs_np, full_token_ids)
        except Exception:
            continue

        full_word_times = _frames_to_word_times(
            alignments, scores, full_token_ids, full_word_token_counts, chunk_start_sec, seg.start_time, vocab=_vocab
        )
        start_idx = len(prefix_words)
        end_idx = len(prefix_words) + len(ref_words)

        word_times = full_word_times[start_idx:end_idx]
        while len(word_times) < len(ref_words):
            word_times.append({"_start": None, "_end": None})

        new_words = []
        mapped_asr_words = []
        for j, (word, wt) in enumerate(zip(ref_words, word_times)):
            if j in missing_word_indices:
                continue
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
            mapped_asr_words.append(asr_word_mapping.get(j))


        seg.words = new_words
        if stage_metrics.get("multi_chapter") and new_words:
            first_asr_word = asr_word_mapping.get(0)
            prefix_duration = (
                first_asr_word["start"] - seg.start_time
                if first_asr_word
                else new_words[0].get("start")
            )
            if prefix_duration is not None and prefix_duration > 0:
                seg.start_time = round(seg.start_time + prefix_duration, 3)
                for word in new_words:
                    if word.get("start") is not None:
                        word["start"] = round(max(0.0, word["start"] - prefix_duration), 4)
                    if word.get("end") is not None:
                        word["end"] = round(max(0.0, word["end"] - prefix_duration), 4)
                    for ph_item in word.get("phonemes", []):
                        if ph_item.get("start") is not None:
                            ph_item["start"] = round(max(0.0, ph_item["start"] - prefix_duration), 4)
                        if ph_item.get("end") is not None:
                            ph_item["end"] = round(max(0.0, ph_item["end"] - prefix_duration), 4)
        seg._asr_word_gaps = [None]
        seg._acoustic_word_gaps = [None]
        for previous_asr_word, current_asr_word in zip(
            mapped_asr_words, mapped_asr_words[1:]
        ):
            if previous_asr_word and current_asr_word:
                previous_end = previous_asr_word["end"]
                current_start = current_asr_word["start"]
                seg._asr_word_gaps.append(max(0.0, current_start - previous_end))
                seg._acoustic_word_gaps.append(
                    max(
                        (
                            max(
                                0.0,
                                min(current_start, silence_end)
                                - max(previous_end, silence_start),
                            )
                            for silence_start, silence_end in silence_intervals
                        ),
                        default=0.0,
                    )
                )
            else:
                seg._asr_word_gaps.append(None)
                seg._acoustic_word_gaps.append(None)
