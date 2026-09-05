"""Gene Myers' 64-bit Bit-Parallel Substring Search Algorithm.

Computes 64 Dynamic Programming matrix cells per single CPU bitwise cycle.
Mirrors Dart lib/phase3_matcher/surah_finder/fuzzy_search.dart exactly.
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import List, Dict


@dataclass
class FuzzyMatch:
    """Represents an approximate match region."""
    start: int
    end: int
    dist: int

    def __str__(self) -> str:
        return f"FuzzyMatch(start: {self.start}, end: {self.end}, dist: {self.dist})"


def find_near_matches(query: str, text: str, max_dist: int) -> List[FuzzyMatch]:
    """Finds all occurrences of query in text with Levenshtein distance <= max_dist.

    Uses Gene Myers' 64-bit Bit-Parallel algorithm for queries up to 64 chars,
    with automatic DP fallback for longer queries.
    """
    n = len(query)
    m = len(text)

    if n == 0 or m == 0 or max_dist < 0:
        return []

    if n <= 64:
        return _bit_parallel_search(query, text, max_dist)
    else:
        return _dp_search(query, text, max_dist)


def _bit_parallel_search(query: str, text: str, max_dist: int) -> List[FuzzyMatch]:
    """Myers' 64-bit Bit-Parallel Substring Search."""
    n = len(query)
    m = len(text)
    matches: List[FuzzyMatch] = []

    # Build character pattern bitmasks
    char_mask: Dict[int, int] = {}
    for i, ch in enumerate(query):
        code = ord(ch)
        char_mask[code] = char_mask.get(code, 0) | (1 << i)

    full_mask = (1 << n) - 1
    top_mask = 1 << (n - 1)

    vp = full_mask
    vn = 0
    curr_dist = n

    for j, ch in enumerate(text):
        pm = char_mask.get(ord(ch), 0)

        # Step 1: Computing D0
        x = pm | vn
        d0 = (((pm & vp) + vp) ^ vp) | x

        # Step 2: Computing HP and HN
        hn = vp & d0
        hp = vn | (~(vp | d0) & full_mask)

        # Step 3: Check boundary condition
        if (hp & top_mask) != 0:
            curr_dist += 1
        if (hn & top_mask) != 0:
            curr_dist -= 1

        # Step 4: Advance vectors
        hp = (hp << 1) & full_mask
        hn = (hn << 1) & full_mask
        vp = (hn | (~(d0 | hp) & full_mask)) & full_mask
        vn = hp & d0

        if curr_dist <= max_dist:
            match_end = j + 1
            estimated_start = max(0, min(match_end, match_end - n - curr_dist))
            matches.append(
                FuzzyMatch(
                    start=estimated_start,
                    end=match_end,
                    dist=curr_dist,
                )
            )

    return _filter_overlapping(matches)


def _dp_search(query: str, text: str, max_dist: int) -> List[FuzzyMatch]:
    """Fallback Dynamic Programming approach for queries longer than 64 phonemes."""
    matches: List[FuzzyMatch] = []
    n = len(query)
    m = len(text)

    prev_dist = [i for i in range(n + 1)]
    prev_start = [0] * (n + 1)
    curr_dist = [0] * (n + 1)
    curr_start = [0] * (n + 1)

    query_units = [ord(c) for c in query]
    text_units = [ord(c) for c in text]

    for j in range(1, m + 1):
        curr_dist[0] = 0
        curr_start[0] = j
        text_char = text_units[j - 1]

        for i in range(1, n + 1):
            cost = 0 if query_units[i - 1] == text_char else 1

            replace_dist = prev_dist[i - 1] + cost
            replace_start = prev_start[i - 1]

            delete_query_dist = prev_dist[i] + 1
            delete_query_start = prev_start[i]

            insert_query_dist = curr_dist[i - 1] + 1
            insert_query_start = curr_start[i - 1]

            min_dist = replace_dist
            best_start = replace_start

            if (delete_query_dist < min_dist or
                    (delete_query_dist == min_dist and delete_query_start > best_start)):
                min_dist = delete_query_dist
                best_start = delete_query_start

            if (insert_query_dist < min_dist or
                    (insert_query_dist == min_dist and insert_query_start > best_start)):
                min_dist = insert_query_dist
                best_start = insert_query_start

            curr_dist[i] = min_dist
            curr_start[i] = best_start

        if curr_dist[n] <= max_dist:
            matches.append(
                FuzzyMatch(
                    start=curr_start[n],
                    end=j,
                    dist=curr_dist[n],
                )
            )

        prev_dist, curr_dist = curr_dist, prev_dist
        prev_start, curr_start = curr_start, prev_start

    return _filter_overlapping(matches)


def _filter_overlapping(matches: List[FuzzyMatch]) -> List[FuzzyMatch]:
    """Filters overlapping matches, preserving lowest distance and tighter spans."""
    if not matches:
        return []

    matches.sort(key=lambda m: (m.start, m.end, m.dist))

    filtered: List[FuzzyMatch] = []
    current = matches[0]

    for i in range(1, len(matches)):
        nxt = matches[i]

        if nxt.start < current.end:
            if nxt.dist < current.dist:
                current = nxt
            elif nxt.dist == current.dist:
                current_len = current.end - current.start
                next_len = nxt.end - nxt.start
                if next_len < current_len:
                    current = nxt
        else:
            filtered.append(current)
            current = nxt

    filtered.append(current)
    return filtered
