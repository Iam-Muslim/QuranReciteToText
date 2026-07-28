"""Post-alignment segment subdivision using MFA word timestamps.

Two independent criteria (either or both can apply):
    - max verses spanned per segment
    - max words per segment

Segments that violate the active criteria are batch-submitted to MFA for
word-level timestamps, then cut at the best word boundary:
    1. Verse pass first — split at verse boundaries.
    2. Word pass — split at a waqf (stop-sign) if present in preferred order
       preferred_stop > optional_stop > preferred_continue (phonemizer-canonical
       labels). Tiebreak: word index closest to the middle. If no stop sign
       exists at any recursion depth, fall back to an equal-word split.

Recurses until every leaf sub-segment satisfies the active criteria (no cap).

Pure module: no Gradio, no session state.
"""

from __future__ import annotations

import copy
import math
import uuid
from dataclasses import replace
from typing import Callable, Optional

from qua_sdk.domain import SPECIAL_NAMES as ALL_SPECIAL_REFS

from config import AUTO_MERGE_GROUP_PREFIX
from src.core.quran_index import get_quran_index
from src.core.segment_types import SegmentInfo
from src.core.segment_types import SegmentInfo
# src.ui does not exist in this repo, so we remove the imports and hardcode what's needed.

WAQF_MARK_BY_LABEL = {
    "preferred_stop": "ۖ",
    "optional_stop": "ۚ",
    "preferred_continue": "صلے",
}

import json
from pathlib import Path

_verse_word_counts_cache = None

def _load_verse_word_counts() -> dict[int, dict[int, int]]:
    """Load and cache verse word counts from surah_info.json."""
    global _verse_word_counts_cache
    if _verse_word_counts_cache is not None:
        return _verse_word_counts_cache

    # Assuming surah_info.json is in the data folder relative to project root
    app_path = Path(__file__).parent.parent.parent.resolve()
    surah_info_path = app_path / "data" / "surah_info.json"

    with open(surah_info_path, 'r', encoding='utf-8') as f:
        surah_info = json.load(f)

    _verse_word_counts_cache = {}
    for surah_num, data in surah_info.items():
        surah_int = int(surah_num)
        _verse_word_counts_cache[surah_int] = {}
        for verse_data in data.get('verses', []):
            verse_num = verse_data.get('verse')
            num_words = verse_data.get('num_words', 0)
            if verse_num:
                _verse_word_counts_cache[surah_int][verse_num] = num_words

    return _verse_word_counts_cache

def _parse_ref_verse_ranges(matched_ref: str) -> list[tuple[int, int, int, int]]:
    """Decompose a ref into per-verse (surah, ayah, word_from, word_to) ranges."""
    if not matched_ref:
        return []
    if "-" not in matched_ref:
        parts = matched_ref.split(":")
        if len(parts) < 3:
            return []
        try:
            s, a, w = int(parts[0]), int(parts[1]), int(parts[2])
        except (ValueError, IndexError):
            return []
        return [(s, a, w, w)]
    try:
        start_ref, end_ref = matched_ref.split("-", 1)
        sp = start_ref.split(":")
        ep = end_ref.split(":")
        if len(sp) < 3 or len(ep) < 3:
            return []
        s_surah, s_ayah, s_word = int(sp[0]), int(sp[1]), int(sp[2])
        e_surah, e_ayah, e_word = int(ep[0]), int(ep[1]), int(ep[2])
    except (ValueError, IndexError):
        return []

    if s_surah != e_surah:
        return []

    surah = s_surah
    if s_ayah == e_ayah:
        return [(surah, s_ayah, s_word, e_word)]

    verse_wc = _load_verse_word_counts()
    ranges = []
    for ayah in range(s_ayah, e_ayah + 1):
        expected = verse_wc.get(surah, {}).get(ayah, 0)
        if expected == 0:
            continue
        if ayah == s_ayah:
            ranges.append((surah, ayah, s_word, expected))
        elif ayah == e_ayah:
            ranges.append((surah, ayah, 1, e_word))
        else:
            ranges.append((surah, ayah, 1, expected))
    return ranges



# Waqf stop-sign priority for SPLITTING (phonemizer-canonical labels, highest
# first). A deliberate subset of the canonical waqf marks (see src/ui/waqf.py):
# compulsory_stop is never a desirable split point, so it is excluded here.
# Marks come from the shared WAQF_MARK_BY_LABEL map to avoid duplicating the
# Unicode literals. See quranic_phonemizer README §Stops (Waqf).
_SPLIT_PRIORITY_LABELS = ("preferred_stop", "optional_stop", "preferred_continue")
STOP_SIGN_PRIORITY = tuple(
    (label, WAQF_MARK_BY_LABEL[label]) for label in _SPLIT_PRIORITY_LABELS
)

_MANUAL_SPLIT_SPECIAL_REFS = {"Basmala", "Isti'adha"}

_SPECIAL_TEXT_BY_REF = {
    "Basmala": "بِسْمِ ٱللَّهِ ٱلرَّحْمَٰنِ ٱلرَّحِيم",
    "Isti'adha": "أَعُوذُ بِٱللَّهِ مِنَ الشَّيْطَانِ الرَّجِيم",
}


# ---------------------------------------------------------------------------
# Eligibility + counting helpers
# ---------------------------------------------------------------------------

def is_eligible(seg: SegmentInfo) -> bool:
    """Segment is a split candidate (also excluded from count totals when False)."""
    if not seg.matched_ref:
        return False
    if seg.matched_ref in ALL_SPECIAL_REFS:
        return False
    if "+" in seg.matched_ref:
        return False   # compound special+verse (e.g. "Basmala+2:255:1-2:255:5")
    if seg.has_repeated_words:
        return False
    if seg.error:
        return False
    return True


def verse_span(seg: SegmentInfo) -> int:
    """Number of distinct verses a segment spans (0 if unparseable/special)."""
    if not is_eligible(seg):
        return 0
    ranges = _parse_ref_verse_ranges(seg.matched_ref)
    return len(ranges)


def word_count_of(seg: SegmentInfo) -> int:
    """Number of Quran words the segment covers, using QuranIndex for ground truth."""
    if not is_eligible(seg):
        return 0
    indices = get_quran_index().ref_to_indices(seg.matched_ref)
    if not indices:
        return 0
    start_idx, end_idx = indices
    return end_idx - start_idx + 1


def duration_of(seg: SegmentInfo) -> float:
    """Segment duration in seconds."""
    return max(0.0, seg.end_time - seg.start_time)


def violates(seg: SegmentInfo, max_verses: Optional[int],
             max_words: Optional[int],
             max_duration: Optional[float] = None) -> tuple[bool, bool, bool]:
    """Return (violates_verse, violates_word, violates_duration)."""
    if not is_eligible(seg):
        return False, False, False
    v_bad = bool(max_verses is not None and verse_span(seg) > max_verses)
    w_bad = bool(max_words is not None and word_count_of(seg) > max_words)
    d_bad = bool(max_duration is not None and duration_of(seg) > max_duration)
    return v_bad, w_bad, d_bad


# ---------------------------------------------------------------------------
# Word-level helpers
# ---------------------------------------------------------------------------

def _segment_word_texts(seg: SegmentInfo) -> list[str]:
    """Return QPC Hafs text for each word in the segment, in order.

    Uses QuranIndex (ground truth), not seg.matched_text, so waqf marks that
    live as combining characters on the QPC string are visible.
    """
    indices = get_quran_index().ref_to_indices(seg.matched_ref)
    if not indices:
        return []
    start_idx, end_idx = indices
    words = get_quran_index().words
    return [words[i].text for i in range(start_idx, end_idx + 1)]


def _display_word_texts(text: str) -> list[str]:
    """Split display text into words, dropping verse markers."""
    if not text:
        return []
    return text.replace(" \u06dd ", " ").split()


def _special_word_texts(seg: SegmentInfo) -> list[str]:
    """Return special-segment words in display order."""
    if seg.matched_text:
        words = _display_word_texts(seg.matched_text)
        if words:
            return words
    return _display_word_texts(_SPECIAL_TEXT_BY_REF.get(seg.matched_ref, ""))


def manual_split_supported(seg: SegmentInfo) -> bool:
    """Segment supports manual split mode in the UI."""
    if not seg.matched_ref or seg.has_repeated_words:
        return False

    if seg.matched_ref in ALL_SPECIAL_REFS:
        return False

    indices = get_quran_index().ref_to_indices(seg.matched_ref)
    if not indices:
        return False
    return (indices[1] - indices[0] + 1) >= 2


def _manual_word_count(seg: SegmentInfo) -> int:
    """Return the word count used by manual split selection validation."""
    indices = get_quran_index().ref_to_indices(seg.matched_ref)
    if not indices:
        return 0
    return indices[1] - indices[0] + 1


def find_stop_split_idx(word_texts: list[str]) -> Optional[int]:
    """Return 0-based index of the word AFTER which to cut.

    Walks the priority tuple; the first class with any hit wins. Within that
    class, picks the hit whose index is closest to the middle of the segment.
    The LAST word is never a valid cut point (would yield an empty right half)
    so it's excluded from candidates.
    """
    n = len(word_texts)
    if n < 2:
        return None
    middle = (n - 1) / 2.0

    for _label, mark in STOP_SIGN_PRIORITY:
        hits = [i for i in range(n - 1) if mark in word_texts[i]]
        if hits:
            return min(hits, key=lambda i: abs(i - middle))
    return None


# ---------------------------------------------------------------------------
# Ref arithmetic
# ---------------------------------------------------------------------------

def _make_ref_from_global(start_global_idx: int, end_global_idx: int) -> str:
    """Build a matched_ref string from two global word indices (inclusive)."""
    words = get_quran_index().words
    a = words[start_global_idx]
    b = words[end_global_idx]
    if start_global_idx == end_global_idx:
        return f"{a.surah}:{a.ayah}:{a.word}"
    return f"{a.surah}:{a.ayah}:{a.word}-{b.surah}:{b.ayah}:{b.word}"


def _matched_text_from_global(start_global_idx: int, end_global_idx: int) -> str:
    """Rebuild matched_text (display script) over a global word range."""
    words = get_quran_index().words
    return " ".join(words[i].display_text for i in range(start_global_idx, end_global_idx + 1))


# ---------------------------------------------------------------------------
# Split point → sub-segment construction
# ---------------------------------------------------------------------------

def _slice_mfa_words(mfa_words: list[dict], lo: int, hi: int, new_zero: float) -> list[dict]:
    """Return a deep-copied slice of mfa_words with times re-based to new_zero."""
    return _shift_mfa_words(mfa_words[lo:hi + 1], -new_zero)


def _shift_mfa_words(mfa_words: list[dict], delta: float) -> list[dict]:
    """Return a deep-copied MFA words list with all times shifted by delta."""
    out = []
    for w in mfa_words:
        nw = dict(w)
        if isinstance(nw.get("start"), (int, float)):
            nw["start"] = round(nw["start"] + delta, 4)
        if isinstance(nw.get("end"), (int, float)):
            nw["end"] = round(nw["end"] + delta, 4)
        if "letters" in nw and isinstance(nw["letters"], list):
            letters = []
            for lt in nw["letters"]:
                nlt = dict(lt)
                if isinstance(nlt.get("start"), (int, float)):
                    nlt["start"] = round(nlt["start"] + delta, 4)
                if isinstance(nlt.get("end"), (int, float)):
                    nlt["end"] = round(nlt["end"] + delta, 4)
                letters.append(nlt)
            nw["letters"] = letters
        out.append(nw)
    return out


def _merge_child_mfa_words(group: list[SegmentInfo]) -> Optional[list[dict]]:
    """Combine child-local MFA timestamps back into one merged local timeline."""
    if not group or not all(seg.words for seg in group):
        return None

    merged_zero = group[0].start_time
    out = []
    for seg in group:
        delta = seg.start_time - merged_zero
        out.extend(_shift_mfa_words(seg.words or [], delta))
    return out


def _build_child(parent: SegmentInfo,
                 start_global_idx: int, end_global_idx: int,
                 rel_start: float, rel_end: float,
                 mfa_word_lo: int, mfa_word_hi: int,
                 mfa_words: Optional[list],
                 group_id: str) -> SegmentInfo:
    """Build a sub-segment from parent, covering [start_global_idx..end_global_idx].

    rel_start/rel_end are in parent-local seconds (0 == parent.start_time).
    """
    abs_start = parent.start_time + rel_start
    abs_end = parent.start_time + rel_end
    new_ref = _make_ref_from_global(start_global_idx, end_global_idx)
    new_text = _matched_text_from_global(start_global_idx, end_global_idx)

    sliced_words = None
    if mfa_words is not None and mfa_word_hi >= mfa_word_lo:
        sliced_words = _slice_mfa_words(mfa_words, mfa_word_lo, mfa_word_hi, rel_start)

    return replace(
        parent,
        start_time=abs_start,
        end_time=abs_end,
        matched_ref=new_ref,
        matched_text=new_text,
        transcribed_text="",            # ASR transcript not sliceable
        words=sliced_words,
        wrap_word_ranges=None,
        repeated_ranges=None,
        repeated_text=None,
        has_missing_words=False,
        has_repeated_words=False,
        error=None,
        split_group_id=group_id,
        # segment_number reassigned by caller at the end
        segment_number=0,
    )


# ---------------------------------------------------------------------------
# MFA word indexing
# ---------------------------------------------------------------------------

def _build_mfa_location_to_idx(mfa_words: list[dict]) -> dict[str, int]:
    """Map MFA location strings ('s:a:w') to their position in the words list."""
    out = {}
    for i, w in enumerate(mfa_words):
        loc = w.get("location")
        if loc and loc not in out:
            out[loc] = i
    return out


def _parent_segment_word_global_indices(seg: SegmentInfo) -> list[int]:
    """Global word indices the segment covers, in order."""
    indices = get_quran_index().ref_to_indices(seg.matched_ref)
    if not indices:
        return []
    return list(range(indices[0], indices[1] + 1))


def _mfa_rel_start(mfa_words: list[dict], idx: int, fallback: float) -> float:
    v = mfa_words[idx].get("start") if 0 <= idx < len(mfa_words) else None
    return float(v) if isinstance(v, (int, float)) else float(fallback)


def _mfa_rel_end(mfa_words: list[dict], idx: int, fallback: float) -> float:
    v = mfa_words[idx].get("end") if 0 <= idx < len(mfa_words) else None
    return float(v) if isinstance(v, (int, float)) else float(fallback)


# ---------------------------------------------------------------------------
# Verse pass
# ---------------------------------------------------------------------------

def _verse_cut_indices(seg: SegmentInfo, max_verses: int) -> list[int]:
    """0-based local-word indices after which to cut to limit verse span.

    For a segment covering V verses with limit N<V, group verses into chunks
    of <=N and compute cut indices at the last local-word of each non-final
    chunk.
    """
    ranges = _parse_ref_verse_ranges(seg.matched_ref)
    if len(ranges) <= max_verses:
        return []

    per_verse_wc = [(wt - wf + 1) for (_s, _a, wf, wt) in ranges]

    cut_after_local = []
    cumulative = 0
    v = 0
    while v < len(ranges):
        chunk_end = min(v + max_verses, len(ranges))
        chunk_words = sum(per_verse_wc[v:chunk_end])
        cumulative += chunk_words
        if chunk_end < len(ranges):
            cut_after_local.append(cumulative - 1)
        v = chunk_end
    return cut_after_local


def _split_by_indices(parent: SegmentInfo, mfa_words: list[dict],
                      cut_after_local: list[int],
                      group_id: str) -> list[SegmentInfo]:
    """Split parent at the given local-word indices.

    cut_after_local: 0-based local-word indices after which to cut (not
    including the final word). Returns new sub-segments in order. Uses MFA
    word times for the actual boundary timestamps.

    If mfa_words is unavailable/misaligned, returns [parent] unchanged.
    """
    local_global = _parent_segment_word_global_indices(parent)
    n_words = len(local_global)
    if n_words == 0 or not cut_after_local:
        return [parent]

    # Map each parent-local word index -> its position in the MFA words list
    # (MFA may have non-Quran prefix words like Basmala at 0:0:x — we only
    # consider MFA entries whose location matches one of our global words.)
    loc_to_mfa = _build_mfa_location_to_idx(mfa_words or [])
    words = get_quran_index().words
    local_to_mfa = []
    for gi in local_global:
        w = words[gi]
        loc = f"{w.surah}:{w.ayah}:{w.word}"
        local_to_mfa.append(loc_to_mfa.get(loc))

    # If any required boundary word has no MFA entry, bail out — can't cut.
    boundary_indices = set(cut_after_local) | {i + 1 for i in cut_after_local}
    for bi in boundary_indices:
        if 0 <= bi < n_words and local_to_mfa[bi] is None:
            return [parent]

    # Parent duration fallback if first/last words missing MFA timestamps.
    parent_dur = max(0.0, parent.end_time - parent.start_time)

    segments: list[SegmentInfo] = []
    prev_local = 0
    for cut in cut_after_local:
        # Left sub-segment: local [prev_local .. cut]
        lo_global = local_global[prev_local]
        hi_global = local_global[cut]
        mfa_lo = local_to_mfa[prev_local]
        mfa_hi = local_to_mfa[cut]
        rel_start = _mfa_rel_start(mfa_words, mfa_lo, 0.0) if prev_local > 0 else 0.0
        rel_end = _mfa_rel_end(mfa_words, mfa_hi, parent_dur)
        segments.append(_build_child(
            parent, lo_global, hi_global, rel_start, rel_end,
            mfa_lo, mfa_hi, mfa_words, group_id,
        ))
        prev_local = cut + 1

    # Final sub-segment
    lo_global = local_global[prev_local]
    hi_global = local_global[-1]
    mfa_lo = local_to_mfa[prev_local]
    mfa_hi = local_to_mfa[n_words - 1]
    rel_start = _mfa_rel_start(mfa_words, mfa_lo, 0.0)
    rel_end = parent_dur  # Always extend last sub-segment to parent's end
    segments.append(_build_child(
        parent, lo_global, hi_global, rel_start, rel_end,
        mfa_lo, mfa_hi, mfa_words, group_id,
    ))
    return segments


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def _batch_mfa(segments: list[SegmentInfo],
               indices_to_call: list[int]) -> dict[int, Optional[list]]:
    """Return the already-computed words for each segment from CTC alignment."""
    if not indices_to_call:
        return {}
    return {i: segments[i].words for i in indices_to_call}


def split_segments(segments: list[SegmentInfo],
                   max_verses: Optional[int],
                   max_words: Optional[int],
                   max_duration: Optional[float] = None,
                   require_stop_sign: bool = False,
                   progress_cb: Optional[Callable[[int, int], None]] = None,
                   ) -> tuple[list[SegmentInfo], dict]:
    """Subdivide segments that violate max_verses / max_words / max_duration.

    Args:
        segments: current SegmentInfo list (will not be mutated).
        max_verses:   int > 0, or None to disable the verse criterion.
        max_words:    int > 0, or None to disable the word criterion.
        max_duration: float seconds > 0, or None to disable the duration criterion.
        require_stop_sign: if True, skip the equal-word fallback in the word /
                      duration pass — segments with no waqf mark stay unsplit.
                      Does NOT affect the verse pass.
        progress_cb: optional(completed_violators: int, total_violators: int).

    Returns:
        (new_segments, report) where report contains:
            "split_groups":  {group_id: [new_indices_in_new_list, ...]}
            "failed":        [original_idx, ...] — MFA failure, kept unsplit
            "unchanged_original_indices": set(original_idx, ...)
            "unchanged_new_indices":      {original_idx: new_idx}
            "violator_count":  int
    """
    n = len(segments)
    report: dict = {
        "split_groups": {},
        "failed": [],
        "unchanged_original_indices": set(),
        "unchanged_new_indices": {},
        "violator_count": 0,
    }

    if n == 0 or (max_verses is None and max_words is None and max_duration is None):
        report["unchanged_original_indices"] = set(range(n))
        report["unchanged_new_indices"] = {i: i for i in range(n)}
        return list(segments), report

    # -----------------------------------------------------------------
    # Pass 1 — verse split (only on violators of the verse criterion)
    # -----------------------------------------------------------------
    working: list[SegmentInfo] = list(segments)
    # Tracks which original indices have been replaced (and therefore should
    # NOT be in unchanged_original_indices).
    replaced_original: set[int] = set()
    # Maps each element of `working` to its original index IF unchanged.
    original_idx_of: dict[int, int] = {i: i for i in range(n)}
    failed_original: set[int] = set()

    def _mark_split_from_original(new_idx_in_working: int,
                                  original_idx: Optional[int]):
        original_idx_of.pop(new_idx_in_working, None)
        if original_idx is not None:
            replaced_original.add(original_idx)

    if max_verses is not None:
        violators = [i for i, s in enumerate(working)
                     if violates(s, max_verses, None, None)[0]]
        report["violator_count"] = len(violators)
        if violators:
            mfa_out = _batch_mfa(working, violators)
            if progress_cb:
                progress_cb(len(violators), len(violators))

            new_working: list[SegmentInfo] = []
            new_original_idx_of: dict[int, int] = {}
            for i, seg in enumerate(working):
                orig_i = original_idx_of.get(i)
                if i in violators:
                    mfa_words = mfa_out.get(i)
                    if not mfa_words:
                        failed_original.add(orig_i if orig_i is not None else -1)
                        bad = replace(seg, error="split_failed")
                        new_working.append(bad)
                        if orig_i is not None:
                            new_original_idx_of[len(new_working) - 1] = orig_i
                        continue
                    group_id = f"split-{uuid.uuid4().hex[:8]}"
                    cuts = _verse_cut_indices(seg, max_verses)
                    if not cuts:
                        new_working.append(seg)
                        if orig_i is not None:
                            new_original_idx_of[len(new_working) - 1] = orig_i
                        continue
                    children = _split_by_indices(seg, mfa_words, cuts, group_id)
                    if len(children) <= 1:
                        new_working.append(seg)
                        if orig_i is not None:
                            new_original_idx_of[len(new_working) - 1] = orig_i
                        continue
                    for child in children:
                        new_working.append(child)
                        _mark_split_from_original(len(new_working) - 1, orig_i)
                    if orig_i is not None:
                        replaced_original.add(orig_i)
                else:
                    new_working.append(seg)
                    if orig_i is not None:
                        new_original_idx_of[len(new_working) - 1] = orig_i

            working = new_working
            original_idx_of = new_original_idx_of

    # -----------------------------------------------------------------
    # Pass 2 — word / duration split, recursing until every leaf satisfies
    # both criteria. Each outer iteration batches one MFA call for all
    # current violators. Same cut logic (stop-sign > equal-word) serves both.
    # -----------------------------------------------------------------
    if max_words is not None or max_duration is not None:
        while True:
            def _word_or_dur_violator(s):
                _vv, w_bad, d_bad = violates(s, None, max_words, max_duration)
                return w_bad or d_bad

            violators = [i for i, s in enumerate(working)
                         if _word_or_dur_violator(s)]
            if not violators:
                break

            mfa_out = _batch_mfa(working, violators)
            if progress_cb:
                progress_cb(len(violators), len(violators))

            new_working: list[SegmentInfo] = []
            new_original_idx_of: dict[int, int] = {}
            any_progress = False
            for i, seg in enumerate(working):
                orig_i = original_idx_of.get(i)
                if i in violators:
                    mfa_words = mfa_out.get(i)
                    if not mfa_words:
                        # MFA failed — mark and stop trying to split this one.
                        failed_original.add(orig_i if orig_i is not None else -1)
                        bad = replace(seg, error="split_failed")
                        new_working.append(bad)
                        if orig_i is not None:
                            new_original_idx_of[len(new_working) - 1] = orig_i
                        continue

                    # Verse boundary is highest priority — always cut there first
                    # regardless of whether pass 1 ran or what max_verses was set to.
                    verse_cuts = _verse_cut_indices(seg, 1)
                    if verse_cuts:
                        group_id = seg.split_group_id or f"split-{uuid.uuid4().hex[:8]}"
                        children = _split_by_indices(seg, mfa_words, verse_cuts, group_id)
                        if len(children) > 1:
                            for child in children:
                                new_working.append(child)
                                _mark_split_from_original(len(new_working) - 1, orig_i)
                            if orig_i is not None:
                                replaced_original.add(orig_i)
                            any_progress = True
                            continue
                        # _split_by_indices bailed (missing MFA boundary) — fall through

                    word_texts = _segment_word_texts(seg)
                    cut = find_stop_split_idx(word_texts)
                    if cut is None:
                        # No stop sign. If the caller requires a stop sign,
                        # leave this segment unsplit even though it violates.
                        if require_stop_sign:
                            new_working.append(seg)
                            if orig_i is not None:
                                new_original_idx_of[len(new_working) - 1] = orig_i
                            continue
                        # Equal-word split fallback
                        if len(word_texts) < 2:
                            new_working.append(seg)
                            if orig_i is not None:
                                new_original_idx_of[len(new_working) - 1] = orig_i
                            continue
                        cut = (len(word_texts) // 2) - 1
                        if cut < 0:
                            cut = 0

                    group_id = seg.split_group_id or f"split-{uuid.uuid4().hex[:8]}"
                    children = _split_by_indices(seg, mfa_words, [cut], group_id)
                    if len(children) <= 1:
                        # Could not cut (e.g. missing MFA for boundary) — stop.
                        new_working.append(seg)
                        if orig_i is not None:
                            new_original_idx_of[len(new_working) - 1] = orig_i
                        continue
                    for child in children:
                        new_working.append(child)
                        _mark_split_from_original(len(new_working) - 1, orig_i)
                    if orig_i is not None:
                        replaced_original.add(orig_i)
                    any_progress = True
                else:
                    new_working.append(seg)
                    if orig_i is not None:
                        new_original_idx_of[len(new_working) - 1] = orig_i

            working = new_working
            original_idx_of = new_original_idx_of
            if not any_progress:
                break  # every violator refused to split — avoid infinite loop

    # -----------------------------------------------------------------
    # Finalize: renumber, build report.
    # -----------------------------------------------------------------
    for new_idx, seg in enumerate(working):
        seg.segment_number = new_idx + 1
        if seg.split_group_id:
            report["split_groups"].setdefault(seg.split_group_id, []).append(new_idx)

    report["failed"] = sorted(i for i in failed_original if i >= 0)
    report["unchanged_original_indices"] = {
        orig for new, orig in original_idx_of.items()
        if orig not in replaced_original
    }
    report["unchanged_new_indices"] = dict(original_idx_of)
    return working, report


def split_segment_manual(segments: list[SegmentInfo],
                         segment_idx: int,
                         cut_after_local: list[int]) -> tuple[list[SegmentInfo], dict]:
    """Split a single user-selected segment at explicit local-word cuts."""
    n = len(segments)
    report: dict = {
        "split_groups": {},
        "failed": [],
        "unchanged_original_indices": set(),
        "unchanged_new_indices": {},
        "violator_count": 1,
    }

    if n == 0:
        raise ValueError("No segments available.")
    if segment_idx < 0 or segment_idx >= n:
        raise ValueError("Segment index out of range.")

    parent = segments[segment_idx]
    if not manual_split_supported(parent):
        raise ValueError("This segment does not support manual splitting.")

    try:
        cuts = sorted({int(c) for c in cut_after_local})
    except (TypeError, ValueError) as exc:
        raise ValueError("Invalid manual split selection.") from exc

    total_words = _manual_word_count(parent)
    if total_words < 2:
        raise ValueError("This segment is too short to split.")
    if not cuts:
        raise ValueError("Choose at least one split point.")

    max_cut = total_words - 2
    if any(c < 0 or c > max_cut for c in cuts):
        raise ValueError("Split points are out of range.")

    mfa_words = parent.words

    if not mfa_words:
        raise RuntimeError("No word boundaries for this segment.")

    group_id = parent.split_group_id or f"split-{uuid.uuid4().hex[:8]}"
    children = _split_by_indices(parent, mfa_words, cuts, group_id)

    if len(children) <= 1:
        raise RuntimeError("Could not split this segment at the selected boundaries.")

    new_segments = list(segments[:segment_idx]) + children + list(segments[segment_idx + 1:])
    for new_idx, seg in enumerate(new_segments):
        seg.segment_number = new_idx + 1

    report["split_groups"] = {group_id: list(range(segment_idx, segment_idx + len(children)))}
    report["unchanged_original_indices"] = set(range(n)) - {segment_idx}

    shift = len(children) - 1
    unchanged_new_indices = {}
    for old_idx in range(n):
        if old_idx == segment_idx:
            continue
        new_idx = old_idx if old_idx < segment_idx else old_idx + shift
        unchanged_new_indices[new_idx] = old_idx
    report["unchanged_new_indices"] = unchanged_new_indices

    return new_segments, report


def undo_split_group(segments: list[SegmentInfo],
                     segment_idx: int) -> tuple[list[SegmentInfo], dict]:
    """Merge a contiguous split-group run back into a single segment."""
    n = len(segments)
    if n == 0:
        raise ValueError("No segments available.")
    if segment_idx < 0 or segment_idx >= n:
        raise ValueError("Split group index is out of range.")

    seed = segments[segment_idx]
    group_id = seed.split_group_id
    if not group_id:
        raise ValueError("This segment is not inside a split group.")

    start_idx = segment_idx
    while start_idx > 0 and segments[start_idx - 1].split_group_id == group_id:
        start_idx -= 1

    end_idx = segment_idx
    while end_idx + 1 < n and segments[end_idx + 1].split_group_id == group_id:
        end_idx += 1

    if end_idx <= start_idx:
        raise ValueError("This split group does not have multiple segments.")

    group = segments[start_idx:end_idx + 1]
    first = group[0]
    last = group[-1]

    if first.matched_ref in _MANUAL_SPLIT_SPECIAL_REFS:
        merged_ref = first.matched_ref
        merged_text = _SPECIAL_TEXT_BY_REF.get(merged_ref) or " ".join(
            (seg.matched_text or "").strip() for seg in group if (seg.matched_text or "").strip()
        )
    else:
        first_bounds = get_quran_index().ref_to_indices(first.matched_ref)
        last_bounds = get_quran_index().ref_to_indices(last.matched_ref)
        if not first_bounds or not last_bounds:
            raise ValueError("Could not reconstruct the original split range.")
        merged_ref = _make_ref_from_global(first_bounds[0], last_bounds[1])
        merged_text = _matched_text_from_global(first_bounds[0], last_bounds[1])

    merged = replace(
        first,
        start_time=first.start_time,
        end_time=last.end_time,
        matched_ref=merged_ref,
        matched_text=merged_text,
        transcribed_text="",
        words=_merge_child_mfa_words(group),
        wrap_word_ranges=None,
        repeated_ranges=None,
        repeated_text=None,
        has_missing_words=False,
        has_repeated_words=False,
        error=None,
        split_group_id=None,
        segment_number=0,
    )

    new_segments = list(segments[:start_idx]) + [merged] + list(segments[end_idx + 1:])
    for new_idx, seg in enumerate(new_segments):
        seg.segment_number = new_idx + 1

    unchanged_new_indices = {}
    shift = end_idx - start_idx
    for old_idx in range(n):
        if start_idx <= old_idx <= end_idx:
            continue
        new_idx = old_idx if old_idx < start_idx else old_idx - shift
        unchanged_new_indices[new_idx] = old_idx

    report = {
        "undo_group_id": group_id,
        "undo_original_indices": list(range(start_idx, end_idx + 1)),
        "unchanged_new_indices": unchanged_new_indices,
    }
    return new_segments, report


# ---------------------------------------------------------------------------
# Merge (inverse of split): fuse adjacent segments into one collapsed card
# ---------------------------------------------------------------------------

def _loc_of_global(global_idx: int) -> str:
    """Return the 's:a:w' location string for a global word index."""
    w = get_quran_index().words[global_idx]
    return f"{w.surah}:{w.ayah}:{w.word}"


def _ref_from_member_dict(d: dict) -> str:
    """Reconstruct a matched_ref from a serialized member dict (to_json_dict form)."""
    if d.get("special_type"):
        return d["special_type"]
    if d.get("ref_to"):
        return f"{d['ref_from']}-{d['ref_to']}"
    return d.get("ref_from", "")


def can_merge_pair(seg_a: SegmentInfo, seg_b: SegmentInfo) -> bool:
    """Whether two adjacent segments may be merged (drives the merge chip).

    Both must be ordinary Quran-ref segments (non-special, no compound '+',
    parseable, not in a split group, no alignment error) AND the join between
    them must be a *natural continuity*:
        - overlap (the reciter went back into the first segment) — repetition; or
        - contiguous, or a small 1-2 word gap, within the SAME surah.
    A surah change, a re-anchor jump, or a gap > 2 words blocks the merge.
    Merge-group members ARE allowed — that is what enables cascading.
    """
    qi = get_quran_index()
    for s in (seg_a, seg_b):
        if not s.matched_ref:
            return False
        if s.matched_ref in ALL_SPECIAL_REFS:
            return False
        if "+" in s.matched_ref:
            return False
        if s.split_group_id:
            return False
        if s.error:
            return False
        if qi.ref_to_indices(s.matched_ref) is None:
            return False

    l0, l1 = qi.ref_to_indices(seg_a.matched_ref)
    r0, _r1 = qi.ref_to_indices(seg_b.matched_ref)
    words = qi.words

    # Overlap: the second segment starts inside the first (reciter went back).
    if l0 <= r0 <= l1:
        return True
    # Forward join must stay in the same surah (blocks surah change / re-anchor).
    if words[l1].surah != words[r0].surah:
        return False
    # Contiguous (gap == 0) or a small natural gap (<= 2 words, auto-filled).
    gap = r0 - l1 - 1
    return 0 <= gap <= 2


def _merge_two(left: SegmentInfo, right: SegmentInfo, *,
               members: list, group_id: str) -> SegmentInfo:
    """Build the single collapsed card that fuses ``left`` and ``right``.

    Unions the Quran refs (min start .. max end), joins the audio span
    [left.start_time, right.end_time], and concatenates the existing MFA word
    timestamps. ``members`` is the flat recitation-order member list stamped on
    the card for lossless undo; ``group_id`` is the stable merge id. Overlap
    between the two ref ranges is detected and surfaced as repetition.
    """
    qi = get_quran_index()
    left_ref = qi.ref_to_indices(left.matched_ref)
    right_ref = qi.ref_to_indices(right.matched_ref)
    ranges = [r for r in (left_ref, right_ref) if r is not None]
    if not ranges:
        raise ValueError("Could not resolve the merged reference.")

    start_gi = min(g0 for g0, _g1 in ranges)
    end_gi = max(g1 for _g0, g1 in ranges)
    covered = end_gi - start_gi + 1
    total = sum(g1 - g0 + 1 for g0, g1 in ranges)

    merged_ref = _make_ref_from_global(start_gi, end_gi)
    merged_text = _matched_text_from_global(start_gi, end_gi)

    # total > covered means member ranges overlap → the reciter repeated words.
    # Show each member range line-separated (via repeated_ranges) rather than one
    # contiguous block. total < covered means an auto-filled gap (single block).
    if total > covered:
        has_repeated = True
        repeated_ranges = [[_loc_of_global(g0), _loc_of_global(g1)]
                           for g0, g1 in ranges]
        repeated_text = [_matched_text_from_global(g0, g1) for g0, g1 in ranges]
    else:
        has_repeated = False
        repeated_ranges = None
        repeated_text = None

    return replace(
        left,
        start_time=left.start_time,
        end_time=right.end_time,
        matched_ref=merged_ref,
        matched_text=merged_text,
        transcribed_text="",
        match_score=min(left.match_score, right.match_score),
        words=_merge_child_mfa_words([left, right]),
        wrap_word_ranges=None,
        repeated_ranges=repeated_ranges,
        repeated_text=repeated_text,
        # Provisional flag only. Merge is coverage-monotone for *gaining* — the
        # union can't introduce a new gap — so when neither child was flagged
        # the OR is False and the caller's surgical path can skip recompute. But
        # a merge CAN clear a flag: a gap that sat between the two pieces is now
        # covered. The OR can't see that, so callers that started from a flagged
        # member must run recompute_missing_words() on the result to get the
        # authoritative flag — see merge_segments_audio's fallback path.
        has_missing_words=bool(left.has_missing_words or right.has_missing_words),
        has_repeated_words=has_repeated,
        error=None,
        split_group_id=None,
        merge_group_id=group_id,
        merge_members=members,
        # A merge result is never itself a partial-merge leftover. Clear it so the
        # marker can't propagate when a grown partial-merge card is later cascaded.
        partial_merge_leftover=None,
        segment_number=0,
    )


def merge_segments(segments: list[SegmentInfo],
                   left_idx: int) -> tuple[list[SegmentInfo], dict]:
    """Merge segments[left_idx] and segments[left_idx + 1] into one card.

    Unions the Quran refs (min start .. max end), joins the audio span
    [left.start_time, right.end_time] (already covers the removed silence), and
    concatenates the existing MFA word timestamps — no MFA call is needed.
    Cascades: if either side is already a merge card, its stored members are
    absorbed so the result keeps one flat ``merge_members`` list.
    """
    n = len(segments)
    if n == 0:
        raise ValueError("No segments available.")
    if left_idx < 0 or left_idx + 1 >= n:
        raise ValueError("Merge index is out of range.")

    left = segments[left_idx]
    right = segments[left_idx + 1]
    if not can_merge_pair(left, right):
        raise ValueError("These segments cannot be merged.")
    # A partial-merge unit (grown card + its linked leftover) is locked: undo the
    # partial merge before either piece can join another merge — same principle as
    # split members. Keeps the partial structure simple and undo lossless.
    if (is_partial_merge_member(left, segments)
            or is_partial_merge_member(right, segments)):
        raise ValueError("Undo the partial merge before merging these segments.")

    # Flat member list in recitation order (absorb already-merged sides).
    left_members = left.merge_members or [left.to_json_dict()]
    right_members = right.merge_members or [right.to_json_dict()]
    members = list(left_members) + list(right_members)

    # Cascading onto a pipeline auto-merge makes the group user-owned: mint a
    # fresh user id so the card's tag flips from "Auto-merged" to "Merged".
    group_id = left.merge_group_id or right.merge_group_id
    if not group_id or group_id.startswith(AUTO_MERGE_GROUP_PREFIX):
        group_id = f"merge-{uuid.uuid4().hex[:8]}"

    merged = _merge_two(left, right, members=members, group_id=group_id)

    new_segments = list(segments[:left_idx]) + [merged] + list(segments[left_idx + 2:])
    for new_idx, seg in enumerate(new_segments):
        seg.segment_number = new_idx + 1

    unchanged_new_indices = {}
    for old_idx in range(n):
        if old_idx in (left_idx, left_idx + 1):
            continue
        new_idx = old_idx if old_idx < left_idx else old_idx - 1
        unchanged_new_indices[new_idx] = old_idx

    report = {
        "merge_group_id": group_id,
        "merged_original_indices": [left_idx, left_idx + 1],
        "unchanged_new_indices": unchanged_new_indices,
    }
    return new_segments, report


# ---------------------------------------------------------------------------
# Partial merge: move N boundary words of one segment into its neighbour,
# leaving a trimmed "leftover" remainder. Asymmetric counterpart of merge —
# instead of fusing two whole cards, it slides a few words across the boundary.
# ---------------------------------------------------------------------------

def can_partial_merge_pair(seg_a: SegmentInfo, seg_b: SegmentInfo, *,
                           source: SegmentInfo) -> bool:
    """Whether ``source`` may donate boundary words to its neighbour.

    Inherits every rule of :func:`can_merge_pair` (overlap / <=2-word gap /
    same surah / no specials / no compound '+' / no split group / no error /
    parseable) by delegating to it with the pair in recitation order — overlap
    is intentionally NOT blocked, ``_merge_two`` handles repetition. Adds one
    requirement: the SOURCE must have >= 2 words, otherwise there is nothing to
    move while leaving a non-empty leftover.
    """
    if not can_merge_pair(seg_a, seg_b):
        return False
    idx = get_quran_index().ref_to_indices(source.matched_ref)
    if idx is None:
        return False
    return (idx[1] - idx[0] + 1) >= 2


def is_partial_merge_member(seg: SegmentInfo, segments: list[SegmentInfo]) -> bool:
    """Whether ``seg`` is part of a partial-merge unit (grown card or its leftover).

    The leftover stores the grown card's id in ``partial_merge_leftover``; the grown
    card is the one whose ``merge_group_id`` some leftover points at. Such cards are
    locked from further merges until the partial merge is undone.
    """
    if seg.partial_merge_leftover:
        return True
    return bool(seg.merge_group_id) and any(
        s.partial_merge_leftover == seg.merge_group_id for s in segments)


def _slice_segment_words(source: SegmentInfo, g_lo: int, g_hi: int,
                         word_lo: Optional[int], word_hi: Optional[int]) -> SegmentInfo:
    """Build a synthetic SegmentInfo over the source's global range [g_lo..g_hi].

    ``word_lo``/``word_hi`` index into ``source.words`` (the MFA word list) when
    present; times come from those words, else fall back to a proportional slice
    of the source's audio span. Used both for the moved slice and the leftover.
    """
    new_ref = _make_ref_from_global(g_lo, g_hi)
    new_text = _matched_text_from_global(g_lo, g_hi)

    src_idx = get_quran_index().ref_to_indices(source.matched_ref)
    s0, s1 = src_idx
    n_src = s1 - s0 + 1
    span = max(0.0, source.end_time - source.start_time)

    sliced_words = None
    if source.words:
        sliced_words = [dict(w) for w in source.words[word_lo:word_hi + 1]]

    # Timestamps: prefer MFA word boundaries, else proportional across the span.
    if sliced_words:
        starts = [w["start"] for w in sliced_words if isinstance(w.get("start"), (int, float))]
        ends = [w["end"] for w in sliced_words if isinstance(w.get("end"), (int, float))]
        abs_start = min(starts) if starts else source.start_time
        abs_end = max(ends) if ends else source.end_time
    else:
        # Proportional fallback based on local word offsets within the source.
        local_lo = g_lo - s0
        local_hi = g_hi - s0
        per = span / n_src if n_src else 0.0
        abs_start = source.start_time + per * local_lo
        abs_end = source.start_time + per * (local_hi + 1)

    return replace(
        source,
        start_time=abs_start,
        end_time=abs_end,
        matched_ref=new_ref,
        matched_text=new_text,
        transcribed_text="",
        words=sliced_words,
        wrap_word_ranges=None,
        repeated_ranges=None,
        repeated_text=None,
        has_missing_words=False,
        has_repeated_words=False,
        error=None,
        split_group_id=None,
        merge_group_id=None,
        merge_members=None,
        partial_merge_leftover=None,
        segment_number=0,
    )


def partial_merge(segments: list[SegmentInfo],
                  source_idx: int,
                  take_from: str,
                  count: int) -> tuple[list[SegmentInfo], dict]:
    """Move ``count`` boundary words of segments[source_idx] into a neighbour.

    ``take_from="head"``: the source's leading ``count`` words move into the
    PREVIOUS segment (segments[source_idx - 1]); the source keeps its tail.
    ``take_from="tail"``: the trailing ``count`` words move into the NEXT
    segment (segments[source_idx + 1]); the source keeps its head.

    Produces two cards in reading order: a *grown* neighbour (a merge card whose
    ``merge_members`` are the two ORIGINAL pre-action segments, for lossless
    undo) and a *leftover* (the trimmed source, sharing the grown card's
    ``merge_group_id`` and flagged ``partial_merge_leftover``). Per-word MFA data
    is invalidated on both (``words=None``, ``transcribed_text=""``) so MFA
    recomputes lazily over the new boundaries.
    """
    n = len(segments)
    if n == 0:
        raise ValueError("No segments available.")
    if source_idx < 0 or source_idx >= n:
        raise ValueError("Partial merge index is out of range.")
    if take_from not in ("head", "tail"):
        raise ValueError("take_from must be 'head' or 'tail'.")

    source = segments[source_idx]
    src_idx = get_quran_index().ref_to_indices(source.matched_ref)
    if src_idx is None:
        raise ValueError("Could not resolve the source reference.")
    g0, g1 = src_idx
    src_word_count = g1 - g0 + 1

    if not (1 <= count < src_word_count):
        raise ValueError("Word count to move is out of range.")

    if take_from == "head":
        if source_idx - 1 < 0:
            raise ValueError("No previous segment to merge into.")
        neighbor_idx = source_idx - 1
    else:
        if source_idx + 1 >= n:
            raise ValueError("No next segment to merge into.")
        neighbor_idx = source_idx + 1
    neighbor = segments[neighbor_idx]

    # Pair in recitation order for the eligibility check (matches _merge_two order).
    left, right = (neighbor, source) if take_from == "head" else (source, neighbor)
    if not can_partial_merge_pair(left, right, source=source):
        raise ValueError("These segments cannot be partially merged.")
    # Lock: don't partial-merge into/out of an existing partial-merge unit; undo
    # the prior partial merge first (mirrors the merge_segments guard).
    if (is_partial_merge_member(source, segments)
            or is_partial_merge_member(neighbor, segments)):
        raise ValueError("Undo the partial merge before merging these segments.")

    # The two ORIGINAL pre-action segments in recitation order, for lossless undo
    # from the grown card: head → [neighbor(prev), source]; tail → [source, neighbor(next)].
    if take_from == "head":
        origin = [neighbor.to_json_dict(), source.to_json_dict()]
    else:
        origin = [source.to_json_dict(), neighbor.to_json_dict()]
    new_id = f"merge-{uuid.uuid4().hex[:8]}"

    if take_from == "head":
        # Moved slice = leading `count` words; leftover = the tail.
        slice_seg = _slice_segment_words(source, g0, g0 + count - 1, 0, count - 1)
        leftover = _slice_segment_words(
            source, g0 + count, g1, count, src_word_count - 1)
        grown = _merge_two(neighbor, slice_seg, members=origin, group_id=new_id)
    else:
        # Moved slice = trailing `count` words; leftover = the head.
        slice_seg = _slice_segment_words(
            source, g1 - count + 1, g1, src_word_count - count, src_word_count - 1)
        leftover = _slice_segment_words(
            source, g0, g1 - count, 0, src_word_count - count - 1)
        grown = _merge_two(slice_seg, neighbor, members=origin, group_id=new_id)

    # Stamp the leftover: it renders as an ORDINARY card (no merge_group_id, or it
    # would wrongly render as its own collapsed "Merged" card). It links to the
    # grown card by storing the grown card's group id in partial_merge_leftover;
    # undo is driven from the grown card, which finds and removes this sibling.
    leftover.merge_group_id = None
    leftover.merge_members = None
    leftover.partial_merge_leftover = new_id
    leftover.match_score = source.match_score

    # Invalidate stale per-word MFA on BOTH cards — boundaries moved, so the old
    # word timestamps no longer correspond. MFA recomputes lazily. Keep grown's
    # repeated_* (computed by _merge_two from the union ranges).
    grown.words = None
    grown.transcribed_text = ""
    leftover.words = None
    leftover.transcribed_text = ""

    if take_from == "head":
        # Reading order: grown (was previous) then leftover (trimmed source).
        replacement = [grown, leftover]
        lo = neighbor_idx  # == source_idx - 1
    else:
        # Reading order: leftover (trimmed source) then grown (was next).
        replacement = [leftover, grown]
        lo = source_idx

    new_segments = list(segments[:lo]) + replacement + list(segments[lo + 2:])
    for new_idx, seg in enumerate(new_segments):
        seg.segment_number = new_idx + 1

    # Both consumed slots collapse back to two new slots at [lo, lo + 1] — the
    # index map is identity (one in, one out per slot), so other cards just shift
    # by 0 (a partial merge keeps the segment count constant).
    unchanged_new_indices = {}
    for old_idx in range(n):
        if old_idx in (lo, lo + 1):
            continue
        unchanged_new_indices[old_idx] = old_idx

    report = {
        "merge_group_id": new_id,
        "affected_original_indices": [lo, lo + 1],
        "unchanged_new_indices": unchanged_new_indices,
        "partial_merge": True,
    }
    return new_segments, report


def undo_merge_group(segments: list[SegmentInfo],
                     segment_idx: int) -> tuple[list[SegmentInfo], dict]:
    """Restore the stored original members of a merge card.

    Handles both kinds of merge:
      * **Whole-card merge** — one collapsed card carrying ``merge_members``.
        Restores the members in place of that single card.
      * **Partial merge** — a *grown* card (``merge_group_id`` + ``merge_members``
        = the two originals) plus an ordinary-looking *leftover* card that stores
        the grown card's id in ``partial_merge_leftover`` (no ``merge_group_id``,
        no members). Undo is driven from the grown card; both slots are removed
        and the two original members reinserted. (Clicking the leftover is also
        handled defensively.)
    """
    n = len(segments)
    if n == 0:
        raise ValueError("No segments available.")
    if segment_idx < 0 or segment_idx >= n:
        raise ValueError("Merge group index is out of range.")

    card = segments[segment_idx]
    # The pairing id is the grown card's merge_group_id, which the leftover stores
    # in partial_merge_leftover. Resolve it from whichever card was clicked.
    group_id = card.merge_group_id or card.partial_merge_leftover
    if not group_id:
        raise ValueError("This segment is not a merge group.")

    # Grown / collapsed card carries the members; a partial leftover links by id.
    members_card_idx = segment_idx if card.merge_members else None
    leftover_idx = segment_idx if card.partial_merge_leftover == group_id else None
    for i, sib in enumerate(segments):
        if i == segment_idx:
            continue
        if sib.merge_members and sib.merge_group_id == group_id and members_card_idx is None:
            members_card_idx = i
        if sib.partial_merge_leftover == group_id and leftover_idx is None:
            leftover_idx = i

    is_partial = leftover_idx is not None and members_card_idx is not None

    if not is_partial:
        # Whole-card merge: the clicked card must itself carry the members.
        if not card.merge_members:
            raise ValueError("This segment is not a merge group.")
        members_card_idx = segment_idx
        consumed = [segment_idx]
    else:
        consumed = sorted({members_card_idx, leftover_idx})

    members = segments[members_card_idx].merge_members
    if not members:
        raise ValueError("This segment is not a merge group.")

    restored = []
    for i, m in enumerate(members):
        seg = SegmentInfo.from_json_dict(m, index=i)
        seg.merge_group_id = None
        seg.merge_members = None
        seg.partial_merge_leftover = None
        restored.append(seg)

    insert_at = consumed[0]
    consumed_set = set(consumed)
    tail = [j for j in range(insert_at, n) if j not in consumed_set]
    new_segments = (list(segments[:insert_at]) + restored
                    + [segments[j] for j in tail])
    for new_idx, seg in enumerate(new_segments):
        seg.segment_number = new_idx + 1

    # Map every untouched old index to its position in new_segments by walking
    # the same construction order (head untouched, restored block, then tail).
    unchanged_new_indices = {old: old for old in range(insert_at) if old not in consumed_set}
    base = insert_at + len(restored)
    for offset, old_idx in enumerate(tail):
        unchanged_new_indices[base + offset] = old_idx

    report = {
        "undo_merge_group_id": group_id,
        "undo_original_index": insert_at,
        "undo_original_indices": consumed,
        "restored_count": len(restored),
        "partial_merge": is_partial,
        "unchanged_new_indices": unchanged_new_indices,
    }
    return new_segments, report
