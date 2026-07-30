"""Missing Words Computation & Injection."""

import json
from pathlib import Path
from src.core.segment_types import SegmentInfo

_verse_word_counts_cache = None


def _load_verse_word_counts() -> dict[int, dict[int, int]]:
    """Loads and caches verse word counts from surah_info.json."""
    global _verse_word_counts_cache
    if _verse_word_counts_cache is not None:
        return _verse_word_counts_cache

    app_path = Path(__file__).parent.parent.parent.resolve()
    surah_info_path = app_path / "data" / "surah_info.json"

    with open(surah_info_path, 'r', encoding='utf-8') as f:
        surah_info = json.load(f)

    _verse_word_counts_cache = {}
    for surah_num, data in surah_info.items():
        surah_int = int(surah_num)
        _verse_word_counts_cache[surah_int] = {
            v.get('verse'): v.get('num_words', 0)
            for v in data.get('verses', []) if v.get('verse')
        }

    return _verse_word_counts_cache


def _parse_ref_verse_ranges(matched_ref: str) -> list[tuple[int, int, int, int]]:
    """Decomposes a ref into per-verse (surah, ayah, word_from, word_to) ranges."""
    if not matched_ref:
        return []
    if "-" not in matched_ref:
        parts = matched_ref.split(":")
        if len(parts) < 3:
            return []
        try:
            s, a, w = int(parts[0]), int(parts[1]), int(parts[2])
            return [(s, a, w, w)]
        except ValueError:
            return []

    try:
        start_ref, end_ref = matched_ref.split("-", 1)
        sp, ep = start_ref.split(":"), end_ref.split(":")
        if len(sp) < 3 or len(ep) < 3:
            return []
        s_surah, s_ayah, s_word = int(sp[0]), int(sp[1]), int(sp[2])
        e_surah, e_ayah, e_word = int(ep[0]), int(ep[1]), int(ep[2])
    except ValueError:
        return []

    if s_surah != e_surah:
        return []

    if s_ayah == e_ayah:
        return [(s_surah, s_ayah, s_word, e_word)]

    verse_wc = _load_verse_word_counts()
    ranges = []
    for ayah in range(s_ayah, e_ayah + 1):
        expected = verse_wc.get(s_surah, {}).get(ayah, 0)
        if expected == 0:
            continue
        if ayah == s_ayah:
            ranges.append((s_surah, ayah, s_word, expected))
        elif ayah == e_ayah:
            ranges.append((s_surah, ayah, 1, e_word))
        else:
            ranges.append((s_surah, ayah, 1, expected))
    return ranges


def recompute_missing_words(segments: list[SegmentInfo]) -> None:
    """Recomputes has_missing_words flags for all segments based on word coverage."""
    verse_wc = _load_verse_word_counts()
    for seg in segments:
        seg.has_missing_words = False

    runs: list[list[tuple[int, int, int, int, int]]] = []
    cur: list[tuple[int, int, int, int, int]] = []
    cur_surah = None

    for i, seg in enumerate(segments):
        ranges = _parse_ref_verse_ranges(seg.matched_ref)
        if not ranges:
            continue
        surah = ranges[0][0]
        if cur and surah != cur_surah:
            runs.append(cur)
            cur = []
        cur_surah = surah
        for s, a, wf, wt in ranges:
            cur.append((s, a, wf, wt, i))
    if cur:
        runs.append(cur)

    for run in runs:
        coverage: dict[tuple[int, int], list[tuple[int, int, int]]] = {}
        for s, a, wf, wt, idx in run:
            coverage.setdefault((s, a), []).append((wf, wt, idx))

        for (surah, ayah), entries in coverage.items():
            expected = verse_wc.get(surah, {}).get(ayah, 0)
            if expected == 0:
                continue

            covered = [False] * (expected + 1)
            for wf, wt, _idx in entries:
                for w in range(max(1, wf), min(expected, wt) + 1):
                    covered[w] = True

            w = 1
            while w <= expected:
                if covered[w]:
                    w += 1
                    continue
                gap_lo = w
                while w <= expected and not covered[w]:
                    w += 1
                gap_hi = w - 1
                if gap_lo > 1:
                    for wf, wt, idx in entries:
                        if wt == gap_lo - 1:
                            segments[idx].has_missing_words = True
                if gap_hi < expected:
                    for wf, wt, idx in entries:
                        if wf == gap_hi + 1:
                            segments[idx].has_missing_words = True

        ayahs_sorted = sorted(coverage)
        for k in range(len(ayahs_sorted) - 1):
            (surah, ayah_a), (_, ayah_b) = ayahs_sorted[k], ayahs_sorted[k + 1]
            if ayah_b > ayah_a + 1:
                prev_entries = coverage[(surah, ayah_a)]
                next_entries = coverage[(surah, ayah_b)]
                last_in_prev = max(prev_entries, key=lambda e: e[1])[2]
                first_in_next = min(next_entries, key=lambda e: e[0])[2]
                segments[last_in_prev].has_missing_words = True
                segments[first_in_next].has_missing_words = True


def inject_missing_words(segments: list[SegmentInfo]) -> None:
    """Injects missing (unrecited) Quranic words into seg.words at their sequence position."""
    try:
        from config import ENABLE_MISSING_WORD_INJECTION
    except ImportError:
        ENABLE_MISSING_WORD_INJECTION = True

    if not ENABLE_MISSING_WORD_INJECTION:
        return

    from src.core.quran_index import get_quran_index
    qi = get_quran_index()
    verse_wc = _load_verse_word_counts()

    for seg_idx, seg in enumerate(segments):
        if not seg.words or not seg.has_missing_words or not seg.matched_ref or ":" not in seg.matched_ref:
            continue

        loc_words: list[tuple[int, int, int, dict]] = []
        for w in seg.words:
            loc = w.get("location")
            if loc and ":" in loc:
                parts = loc.split(":")
                try:
                    loc_words.append((int(parts[0]), int(parts[1]), int(parts[2]), w))
                except ValueError:
                    pass

        if not loc_words:
            continue

        surah, ayah = loc_words[0][0], loc_words[0][1]
        expected_total = verse_wc.get(surah, {}).get(ayah, 0)
        if expected_total == 0:
            continue

        present_w_nums = set(lw[2] for lw in loc_words if lw[0] == surah and lw[1] == ayah)
        min_w, max_w = min(present_w_nums), max(present_w_nums)

        target_max_w = max_w
        if seg_idx + 1 < len(segments):
            next_seg = segments[seg_idx + 1]
            if next_seg.matched_ref and f"{surah}:{ayah}:" in next_seg.matched_ref:
                next_locs = [w.get("location") for w in (next_seg.words or []) if w.get("location")]
                next_nums = [int(l.split(":")[2]) for l in next_locs if l.count(":") >= 2 and l.split(":")[0] == str(surah) and l.split(":")[1] == str(ayah)]
                if next_nums:
                    target_max_w = min(next_nums) - 1

        missing_nums = [w_num for w_num in range(min_w, target_max_w + 1) if w_num not in present_w_nums]
        if not missing_nums:
            continue

        num_to_dict = {lw[2]: lw[3] for lw in loc_words if lw[0] == surah and lw[1] == ayah}

        for m_num in missing_nums:
            prev_num = max([n for n in present_w_nums if n < m_num], default=None)
            next_num = min([n for n in present_w_nums if n > m_num], default=None)

            prev_end = num_to_dict[prev_num].get("end", 0.0) if prev_num else 0.0
            next_start = num_to_dict[next_num].get("start", prev_end) if next_num else prev_end

            q_idx = qi.ref_to_indices(f"{surah}:{ayah}:{m_num}")
            word_text = qi.words[q_idx[0]].text if q_idx else ""

            if word_text:
                seg.words.append({
                    "word": word_text,
                    "location": f"{surah}:{ayah}:{m_num}",
                    "start": prev_end,
                    "end": round(next_start, 4),
                    "is_missing": True
                })

        from src.core.quran_index import parse_location_key
        seg.words.sort(key=parse_location_key)
