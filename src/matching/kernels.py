"""Pure Numba JIT Accelerated Dynamic Programming Math Kernels.

Contains:
1. 3D Wraparound Dynamic Programming with exact Viterbi backtracking.
2. Gene Myers 64-bit Bit-Parallel Substring Search kernel.
3. JIT warmup routines.
"""

from __future__ import annotations

from typing import Tuple, List
import numpy as np

from src.matching.phonetics import _sub_cost_fast, get_sub_cost_table

try:
    from numba import njit
    HAS_NUMBA = True
except ImportError:
    HAS_NUMBA = False
    def njit(*args, **kwargs):
        def decorator(func):
            return func
        return decorator


# ═══════════════════════════════════════════════════════════════════════════════
# 1. 3D WRAPAROUND DYNAMIC PROGRAMMING KERNEL WITH EXACT BACKTRACKING
# ═══════════════════════════════════════════════════════════════════════════════

@njit(fastmath=True, cache=True)
def _dp_wraparound_fast(
    p_codes: np.ndarray,
    r_codes: np.ndarray,
    r_phone_to_word: np.ndarray,
    word_starts_mask: np.ndarray,
    word_ends_mask: np.ndarray,
    del_costs: np.ndarray,
    ins_costs: np.ndarray,
    sub_table: np.ndarray,
    max_wraps: int,
    cost_sub: float,
    cost_del: float,
    cost_ins: float,
    wrap_penalty: float,
    wrap_span_weight: float,
    confusion_cost: float,
    prior_weight: float,
    expected_word: int,
) -> Tuple[int, int, int, float, float, int, int, np.ndarray, np.ndarray]:
    """3D Dynamic Programming core with exact Viterbi word-boundary backtracking.

    Returns:
      (best_i, best_k, best_j, best_cost, best_norm, j_start, max_j_reached, word_asr_starts, word_asr_ends)
    """
    m = len(p_codes)
    n = len(r_codes)
    K = max_wraps
    INF = 1e9

    dp = np.full((m + 1, K + 1, n + 1), INF, dtype=np.float64)
    start_arr = np.full((m + 1, K + 1, n + 1), -1, dtype=np.int32)
    max_j_arr = np.full((m + 1, K + 1, n + 1), -1, dtype=np.int32)
    min_w_arr = np.full((m + 1, K + 1, n + 1), 999999, dtype=np.int32)

    # Backtrack tracking: 1=SUB, 2=DEL, 3=INS, 4=WRAP
    backtrack_op = np.zeros((m + 1, K + 1, n + 1), dtype=np.uint8)
    wrap_from = np.zeros((m + 1, K + 1, n + 1), dtype=np.int32)

    # Initialize: k=0, start cost penalizes deviation from expected_word
    for j in range(n + 1):
        if word_starts_mask[j]:
            w_j = r_phone_to_word[j] if j < n else (r_phone_to_word[n - 1] + 1)
            start_dev = abs(w_j - expected_word)
            start_cost = start_dev * 2.0 if start_dev > 0 else 0.0
            dp[0, 0, j] = start_cost
            start_arr[0, 0, j] = j
            max_j_arr[0, 0, j] = j
            if j < n:
                min_w_arr[0, 0, j] = r_phone_to_word[j]

    # Core 3D DP Fill
    for i in range(1, m + 1):
        p_code = p_codes[i - 1]
        ins_c = ins_costs[i - 1]

        for k in range(K + 1):
            if k == 0 and word_starts_mask[0]:
                dp[i, k, 0] = i * cost_del
                start_arr[i, k, 0] = 0
                max_j_arr[i, k, 0] = 0
                min_w_arr[i, k, 0] = min_w_arr[i - 1, k, 0]
                backtrack_op[i, k, 0] = 2  # DEL from (i-1, 0, 0)

            for j in range(1, n + 1):
                del_opt = dp[i - 1, k, j] + del_costs[j - 1] if dp[i - 1, k, j] < INF else INF
                ins_opt = dp[i, k, j - 1] + ins_c if dp[i, k, j - 1] < INF else INF

                r_code = r_codes[j - 1]
                sub_c = sub_table[p_code, r_code]
                sub_opt = dp[i - 1, k, j - 1] + sub_c if dp[i - 1, k, j - 1] < INF else INF


                # Tie-breaking: sub <= del <= ins
                best = sub_opt
                choice = 0
                if del_opt < best:
                    best = del_opt
                    choice = 1
                if ins_opt < best:
                    best = ins_opt
                    choice = 2

                if best < INF:
                    dp[i, k, j] = best
                    w_j = r_phone_to_word[j - 1] if j > 0 else 999999
                    if choice == 0:
                        start_arr[i, k, j] = start_arr[i - 1, k, j - 1]
                        max_j_arr[i, k, j] = max(max_j_arr[i - 1, k, j - 1], j)
                        min_w_arr[i, k, j] = min(min_w_arr[i - 1, k, j - 1], w_j)
                        backtrack_op[i, k, j] = 1
                    elif choice == 1:
                        start_arr[i, k, j] = start_arr[i - 1, k, j]
                        max_j_arr[i, k, j] = max(max_j_arr[i - 1, k, j], j)
                        min_w_arr[i, k, j] = min(min_w_arr[i - 1, k, j], w_j)
                        backtrack_op[i, k, j] = 2
                    else:
                        start_arr[i, k, j] = start_arr[i, k, j - 1]
                        max_j_arr[i, k, j] = max(max_j_arr[i, k, j - 1], j)
                        min_w_arr[i, k, j] = min(min_w_arr[i, k, j - 1], w_j)
                        backtrack_op[i, k, j] = 3

        # Wrap transitions (jumping backward at word boundaries)
        for k in range(K):
            for j_end in range(1, n + 1):
                if not word_ends_mask[j_end] or dp[i, k, j_end] >= INF:
                    continue
                cost_at_end = dp[i, k, j_end]
                w_end = r_phone_to_word[j_end - 1]

                for j_start in range(n + 1):
                    if not word_starts_mask[j_start] or j_start >= j_end:
                        continue
                    w_start = r_phone_to_word[j_start] if j_start < n else w_end
                    word_span = abs(w_end - w_start)
                    new_cost = cost_at_end + wrap_penalty + (wrap_span_weight * word_span)

                    if new_cost < dp[i, k + 1, j_start]:
                        dp[i, k + 1, j_start] = new_cost
                        start_arr[i, k + 1, j_start] = start_arr[i, k, j_end]
                        max_j_arr[i, k + 1, j_start] = max(max_j_arr[i, k, j_end], j_end)
                        min_w_arr[i, k + 1, j_start] = min(min_w_arr[i, k, j_end], w_start)
                        backtrack_op[i, k + 1, j_start] = 4
                        wrap_from[i, k + 1, j_start] = j_end

            # Re-propagate insertions from wrap positions
            for j in range(1, n + 1):
                ins_opt = dp[i, k + 1, j - 1] + ins_c if dp[i, k + 1, j - 1] < INF else INF
                if ins_opt < dp[i, k + 1, j]:
                    dp[i, k + 1, j] = ins_opt
                    start_arr[i, k + 1, j] = start_arr[i, k + 1, j - 1]
                    max_j_arr[i, k + 1, j] = max(max_j_arr[i, k + 1, j - 1], j)
                    min_w_arr[i, k + 1, j] = min(min_w_arr[i, k + 1, j - 1], r_phone_to_word[j - 1])
                    backtrack_op[i, k + 1, j] = 3

    # Search for best endpoint candidate along word ends across all valid rows i
    best_score = INF
    best_cost_val = INF
    best_norm = INF
    best_i = m
    best_k = -1
    best_j = -1
    best_j_start = -1
    best_max_j = -1

    for i in range(1, m + 1):
        for k in range(K + 1):
            for j in range(1, n + 1):
                if not word_ends_mask[j] or dp[i, k, j] >= INF:
                    continue
                # A word match cannot end on a trailing deletion (extra speech after the word)
                op = backtrack_op[i, k, j]
                if op == 2:
                    continue
                j_s = start_arr[i, k, j]
                ref_len = j - j_s
                if ref_len < 2:
                    continue
                dist = dp[i, k, j]
                denom = max(i, ref_len)
                nd = dist / denom
                min_w = min_w_arr[i, k, j]
                prior = prior_weight * abs(min_w - expected_word)
                score = nd + prior

                if score < best_score:
                    best_score = score
                    best_cost_val = dist
                    best_norm = nd
                    best_i = i
                    best_k = k
                    best_j = j
                    best_j_start = j_s
                    best_max_j = max_j_arr[i, k, j]

    # Exact Viterbi Backtracking: strictly partition speech characters to (word, pass)
    char_word_map = np.full(m, -1, dtype=np.int32)
    char_pass_map = np.full(m, -1, dtype=np.int32)

    if best_j > 0:
        ci = best_i
        ck = best_k
        cj = best_j

        while ci > 0 or cj > best_j_start:
            op = backtrack_op[ci, ck, cj]
            if op == 1:  # SUB (speech character matched to reference character)
                w = r_phone_to_word[cj - 1]
                char_word_map[ci - 1] = w
                char_pass_map[ci - 1] = ck
                ci -= 1
                cj -= 1
            elif op == 2:  # DEL (speech insertion within active word)
                w = -1
                if cj > 0 and cj <= n:
                    w = r_phone_to_word[cj - 1]
                elif cj < n:
                    w = r_phone_to_word[cj]
                char_word_map[ci - 1] = w
                char_pass_map[ci - 1] = ck
                ci -= 1
            elif op == 3:  # INS (reference deletion, omitted speech)
                cj -= 1
            elif op == 4:  # WRAP (repetition jump)
                cj = wrap_from[ci, ck, cj]
                ck -= 1
            else:
                if cj > best_j_start:
                    cj -= 1
                elif ci > 0:
                    ci -= 1
                else:
                    break

    return (best_i, best_k, best_j, best_cost_val, best_norm, best_j_start, best_max_j, char_word_map, char_pass_map)

# ═══════════════════════════════════════════════════════════════════════════════
# 1.5 GLOBAL GRAPH VITERBI DECODER (JumpDTW)
# ═══════════════════════════════════════════════════════════════════════════════

@njit(fastmath=True, cache=True)
def _global_viterbi_fast(
    p_codes: np.ndarray,
    r_codes: np.ndarray,
    r_phone_to_word: np.ndarray,
    word_starts_mask: np.ndarray,
    word_ends_mask: np.ndarray,
    del_costs: np.ndarray,
    ins_costs: np.ndarray,
    sub_table: np.ndarray,
    cost_sub: float,
    cost_del: float,
    cost_ins: float,
    wrap_penalty: float,
    wrap_span_weight: float,
    confusion_cost: float = 0.25,
) -> Tuple[int, int, float, np.ndarray, np.ndarray]:
    m = len(p_codes)
    n = len(r_codes)
    INF = 1e9

    dp_prev = np.full(n + 1, INF, dtype=np.float64)
    dp_curr = np.full(n + 1, INF, dtype=np.float64)

    backtrack_op = np.zeros((m + 1, n + 1), dtype=np.uint8)
    wrap_from_j = np.zeros((m + 1, n + 1), dtype=np.uint16)
    
    dp_prev[0] = 0.0

    for j in range(1, n + 1):
        dp_prev[j] = dp_prev[j - 1] + del_costs[j - 1]
        backtrack_op[0, j] = 3  # REF DEL
        
    min_C_after = np.empty(n + 2, dtype=np.float64)
    best_j_after = np.empty(n + 2, dtype=np.int32)

    for i in range(1, m + 1):
        p_code = p_codes[i - 1]
        ins_c = ins_costs[i - 1]

        dp_curr[0] = dp_prev[0] + ins_c
        backtrack_op[i, 0] = 2  # ASR INS

        for j in range(1, n + 1):
            asr_ins_opt = dp_prev[j] + ins_c
            ref_del_opt = dp_curr[j - 1] + del_costs[j - 1]
            
            r_code = r_codes[j - 1]
            sub_c = sub_table[p_code, r_code]
            sub_opt = dp_prev[j - 1] + sub_c

            best = sub_opt
            choice = 1
            if asr_ins_opt < best:
                best = asr_ins_opt
                choice = 2
            if ref_del_opt < best:
                best = ref_del_opt
                choice = 3

            dp_curr[j] = best
            backtrack_op[i, j] = choice

        min_C_after[n + 1] = INF
        best_j_after[n + 1] = -1
        current_min_C = INF
        current_best_j = -1
        
        for j in range(n, -1, -1):
            if word_ends_mask[j] and dp_curr[j] < INF:
                w_end = r_phone_to_word[j - 1]
                C = dp_curr[j] + (wrap_span_weight * w_end)
                if C < current_min_C:
                    current_min_C = C
                    current_best_j = j
            min_C_after[j] = current_min_C
            best_j_after[j] = current_best_j

        has_wrap = False
        for j_start in range(n + 1):
            if word_starts_mask[j_start]:
                c_after = min_C_after[j_start + 1]
                if c_after < INF:
                    w_start = r_phone_to_word[j_start] if j_start < n else r_phone_to_word[n - 1] + 1
                    new_cost = c_after + wrap_penalty - (wrap_span_weight * w_start)
                    if new_cost < dp_curr[j_start]:
                        dp_curr[j_start] = new_cost
                        backtrack_op[i, j_start] = 4
                        wrap_from_j[i, j_start] = best_j_after[j_start + 1]
                        has_wrap = True

        if has_wrap:
            for j in range(1, n + 1):
                ref_del_opt = dp_curr[j - 1] + del_costs[j - 1]
                if ref_del_opt < dp_curr[j]:
                    dp_curr[j] = ref_del_opt
                    backtrack_op[i, j] = 3

        dp_prev[:] = dp_curr[:]

    best_score = INF
    best_j = -1
    for j in range(1, n + 1):
        if word_ends_mask[j] and dp_curr[j] < best_score:
            best_score = dp_curr[j]
            best_j = j

    char_word_map = np.full(m, -1, dtype=np.int32)
    char_j_map = np.full(m, -1, dtype=np.int32)
    ci = m
    cj = best_j
    
    while ci > 0 or cj > 0:
        op = backtrack_op[ci, cj]
        if op == 1:
            w = r_phone_to_word[cj - 1]
            char_word_map[ci - 1] = w
            char_j_map[ci - 1] = cj - 1
            ci -= 1
            cj -= 1
        elif op == 2:
            w = r_phone_to_word[cj - 1] if cj > 0 else -1
            char_word_map[ci - 1] = w
            char_j_map[ci - 1] = cj - 1 if cj > 0 else -1
            ci -= 1
        elif op == 3:
            cj -= 1
        elif op == 4:
            cj = int(wrap_from_j[ci, cj])
        else:
            if cj > 0: cj -= 1
            elif ci > 0: ci -= 1
            else: break
            
    return m, best_j, best_score, char_word_map, char_j_map


# ═══════════════════════════════════════════════════════════════════════════════
# 2. GENE MYERS' 64-BIT BIT-PARALLEL SEARCH KERNEL (JIT ACCELERATED)
# ═══════════════════════════════════════════════════════════════════════════════

@njit(fastmath=True, cache=True)
def _bit_parallel_search_fast(
    query_codes: np.ndarray,
    text_codes: np.ndarray,
    max_dist: int,
) -> Tuple[List[int], List[int], List[int]]:
    """Gene Myers' 64-bit Bit-Parallel Substring Search Algorithm."""
    n = len(query_codes)
    m = len(text_codes)
    char_mask = np.zeros(2048, dtype=np.uint64)
    for i in range(n):
        c = query_codes[i]
        if c < 2048:
            char_mask[c] |= (np.uint64(1) << np.uint64(i))

    full_mask = (np.uint64(1) << np.uint64(n)) - np.uint64(1)
    top_mask = np.uint64(1) << np.uint64(n - 1)
    vp = full_mask
    vn = np.uint64(0)
    curr_dist = n

    match_starts = []
    match_ends = []
    match_dists = []

    for j in range(m):
        code = text_codes[j]
        pm = char_mask[code] if code < 2048 else np.uint64(0)
        x = pm | vn
        d0 = (((pm & vp) + vp) ^ vp) | x
        hn = vp & d0
        hp = vn | (~(vp | d0) & full_mask)

        if (hp & top_mask) != 0:
            curr_dist += 1
        if (hn & top_mask) != 0:
            curr_dist -= 1

        hp = (hp << 1) & full_mask
        hn = (hn << 1) & full_mask
        vp = (hn | (~(d0 | hp) & full_mask)) & full_mask
        vn = hp & d0

        if curr_dist <= max_dist:
            match_end = j + 1
            match_starts.append(max(0, min(match_end, match_end - n - curr_dist)))
            match_ends.append(match_end)
            match_dists.append(curr_dist)

    return match_starts, match_ends, match_dists


# ═══════════════════════════════════════════════════════════════════════════════
# 3. JIT WARMUP ROUTINES
# ═══════════════════════════════════════════════════════════════════════════════

def warmup_matcher_jit() -> None:
    """Pre-compiles Numba JIT kernels for the 3D wraparound DP."""
    if not HAS_NUMBA:
        return
    try:
        p_dummy = np.array([0x0642, 0x0627, 0x0644], dtype=np.int32)
        r_dummy = np.array([0x0642, 0x0627, 0x0644], dtype=np.int32)
        phone_to_w = np.array([0, 0, 0], dtype=np.int32)
        w_starts = np.array([True, False, False, False], dtype=np.bool_)
        w_ends = np.array([False, False, False, True], dtype=np.bool_)
        del_c = np.array([1.0, 1.0, 1.0], dtype=np.float64)
        ins_c = np.array([0.75, 0.75, 0.75], dtype=np.float64)

        tbl_dummy = get_sub_cost_table(0.25)

        _dp_wraparound_fast(
            p_codes=p_dummy,
            r_codes=r_dummy,
            r_phone_to_word=phone_to_w,
            word_starts_mask=w_starts,
            word_ends_mask=w_ends,
            del_costs=del_c,
            ins_costs=ins_c,
            sub_table=tbl_dummy,
            max_wraps=1,
            cost_sub=1.0,
            cost_del=1.0,
            cost_ins=0.75,
            wrap_penalty=0.8,
            wrap_span_weight=0.05,
            confusion_cost=0.25,
            prior_weight=0.02,
            expected_word=0,
        )
        _global_viterbi_fast(
            p_codes=p_dummy,
            r_codes=r_dummy,
            r_phone_to_word=phone_to_w,
            word_starts_mask=w_starts,
            word_ends_mask=w_ends,
            del_costs=del_c,
            ins_costs=ins_c,
            sub_table=tbl_dummy,
            cost_sub=1.0,
            cost_del=1.0,
            cost_ins=0.75,
            wrap_penalty=0.8,
            wrap_span_weight=0.05,
            confusion_cost=0.25,
        )
    except Exception:
        pass



def warmup_detector_jit() -> None:
    """Pre-compiles Myers bit-parallel search with dummy arrays so first query is instant."""
    if not HAS_NUMBA:
        return
    try:
        _bit_parallel_search_fast(np.array([1575], dtype=np.int32), np.array([1575, 1576], dtype=np.int32), 1)
    except Exception:
        pass
