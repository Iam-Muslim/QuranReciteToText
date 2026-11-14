"""Fixed Arabic, Tajweed, and Phonetic Linguistic Rules & Cost Functions.

Defines immutable linguistic constants and phonetic cost rules
for Arabic recitation matching the TajweedFormer V4 38-token vocabulary.
"""

from __future__ import annotations

from typing import Dict
import numpy as np

try:
    from numba import njit
except ImportError:
    def njit(*args, **kwargs):
        def decorator(func):
            return func
        return decorator


# ═══════════════════════════════════════════════════════════════════════════════
# 1. FIXED ARABIC & TAJWEEDFORMER V4 38-TOKEN CHARSETS
# ═══════════════════════════════════════════════════════════════════════════════

# Canonical Recitation Preamble & Prayer Transition Constants (TajweedFormer V4 38 tokens)
ISTIAADHA_TEXT: str = "أَعُوذُ بِٱللَّهِ مِنَ ٱلشَّيْطَـٰنِ ٱلرَّجِيمِ"
ISTIAADHA_PH: str = "ءaعuuذuبiلaaهiمiنaشaيطaaنiرaجiiم"

BASMALAH_TEXT: str = "بِسْمِ ٱللَّهِ ٱلرَّحْمَـٰنِ ٱلرَّحِيمِ"
BASMALAH_PH: str = "بiسمiلaaهiرaحمaaنiرaحiiم"

TAKBEER_TEXT: str = "اللَّهُ أَكْبَرُ"
TAKBEER_PH: str = "ءaلaaهuءaكبaر"

TASMEE_TEXT: str = "سَمِعَ اللَّهُ لِمَنْ حَمِدَهُ"
TASMEE_PH: str = "سaمiعaلaaهuلiمaنحaمiدaه"

# Verses containing phrases resembling prayer phrases (e.g. الله أكبر, سمع الله)
# that must NEVER be false matched as intro preambles:
PRAYER_EXCLUDED_VERSES: frozenset[tuple[int, int]] = frozenset({
    (2, 253),
    (3, 181),   # لقد سمع الله
    (4, 153),
    (6, 19), (6, 78),
    (7, 28),
    (9, 3), (9, 72),  # ورضوان من الله أكبر
    (10, 61),
    (12, 31),
    (16, 41),
    (17, 21),
    (18, 69),
    (21, 103),
    (29, 45),  # ولذكر الله أكبر
    (30, 11),
    (32, 21),
    (34, 3),
    (36, 47),
    (39, 26),
    (40, 10), (40, 57),  # لمقت الله أكبر
    (43, 48),
    (58, 1),   # قد سمع الله
    (68, 33),
    (88, 24),  # العذاب الأكبر
})

# Normalization core characters for fast phonetic search (TajweedFormer V4 38 tokens)
CORE_CHARS_SET: frozenset[str] = frozenset("ءبتثجحخدذرزسشصضطظعغفقكلمنهويںaiu")


def normalize_phoneme_query(query: str) -> str:
    """Normalizes a phoneme string for fast Myers bit-parallel search.

    Preserves vowels ('a', 'i', 'u') and Madd doubles ('aa', 'ii', 'uu'),
    while collapsing adjacent identical consonants.
    """
    parts: list[str] = []
    vowels = {"a", "i", "u"}
    prev = ""
    for c in query:
        if c in CORE_CHARS_SET:
            if c in vowels:
                # Keep vowels, allow up to double vowels for Madd ('aa', 'ii', 'uu')
                if len(parts) >= 2 and parts[-1] == c and parts[-2] == c:
                    continue
                parts.append(c)
                prev = c
            else:
                # Collapse repeated consonants
                if c != prev:
                    parts.append(c)
                    prev = c
    return "".join(parts)


# ═══════════════════════════════════════════════════════════════════════════════
# 2. PHONETIC & ACOUSTIC SUBSTITUTION COST KERNEL (JIT ACCELERATED)
# ═══════════════════════════════════════════════════════════════════════════════

@njit(fastmath=True, cache=True)
def _sub_cost_fast(a: int, b: int, confusion_cost: float = 0.25) -> float:
    """Computes exact substitution cost matching TajweedFormer 38-token acoustic variance."""
    if a == b:
        return 0.0
    mn, mx = (a, b) if a < b else (b, a)

    # 1. Vowel confusion (short vs long or vowel shifts):
    # 'a' (97), 'i' (105), 'u' (117)
    if (a in (97, 105, 117)) or (b in (97, 105, 117)):
        if (a in (97, 105, 117)) and (b in (97, 105, 117)):
            return confusion_cost
        return 1.0

    # 2. Acoustic Consonant Confusion Pairs (cost = confusion_cost):
    # ت 0x062A vs ط 0x0637
    # د 0x062F vs ض 0x0636
    # ذ 0x0630 vs ظ 0x0638 or ز 0x0632
    # س 0x0633 vs ص 0x0635
    # ق 0x0642 vs ك 0x0643
    # ع 0x0639 vs ء 0x0621
    # ح 0x062D vs ه 0x0647
    # خ 0x062E vs غ 0x063A
    # ج 0x062C vs ز 0x0632
    if (mn == 0x062A and mx == 0x0637) or \
       (mn == 0x062F and mx == 0x0636) or \
       (mn == 0x0630 and (mx == 0x0632 or mx == 0x0638)) or \
       (mn == 0x0633 and mx == 0x0635) or \
       (mn == 0x0642 and mx == 0x0643) or \
       (mn == 0x0621 and mx == 0x0639) or \
       (mn == 0x062D and mx == 0x0647) or \
       (mn == 0x062E and mx == 0x063A) or \
       (mn == 0x062C and mx == 0x0632):
        return confusion_cost

    return 1.0


@njit(cache=True)
def _fill_sub_cost_table(table: np.ndarray, confusion_cost: float) -> None:
    # All valid token char codes: vowels [97, 105, 117] and Arabic consonants [0x0621..0x06BA]
    vowel_codes = (97, 105, 117)
    # Populate Arabic block
    for a in range(0x0620, 0x06C0):
        for b in range(0x0620, 0x06C0):
            table[a, b] = _sub_cost_fast(a, b, confusion_cost)
    # Populate vowel vs vowel and vowel vs Arabic
    for v1 in vowel_codes:
        for v2 in vowel_codes:
            table[v1, v2] = _sub_cost_fast(v1, v2, confusion_cost)
        for a in range(0x0620, 0x06C0):
            c = _sub_cost_fast(v1, a, confusion_cost)
            table[v1, a] = c
            table[a, v1] = c


_SUB_COST_TABLES: Dict[float, np.ndarray] = {}


def get_sub_cost_table(confusion_cost: float = 0.25) -> np.ndarray:
    """Returns a precomputed 2048x2048 float64 lookup table filled directly by _sub_cost_fast."""
    key = round(float(confusion_cost), 4)
    if key in _SUB_COST_TABLES:
        return _SUB_COST_TABLES[key]

    table = np.ones((2048, 2048), dtype=np.float64)
    np.fill_diagonal(table, 0.0)
    _fill_sub_cost_table(table, float(confusion_cost))

    _SUB_COST_TABLES[key] = table
    return table


# ═══════════════════════════════════════════════════════════════════════════════
# 3. JIT VECTORIZED EDIT COST EVALUATORS
# ═══════════════════════════════════════════════════════════════════════════════

@njit(fastmath=True, cache=True)
def _compute_insertion_costs_fast(
    p_codes: np.ndarray, standard_cost: float, confusion_cost: float
) -> np.ndarray:
    m = len(p_codes)
    costs = np.full(m, standard_cost, dtype=np.float64)
    for i in range(m):
        code = p_codes[i]
        # Repeated vowel or consonant gets lower insertion penalty
        if i > 0 and code == p_codes[i - 1]:
            costs[i] = confusion_cost
        elif code in (97, 105, 117):  # 'a', 'i', 'u'
            costs[i] = standard_cost * 0.85
    return costs


@njit(fastmath=True, cache=True)
def _compute_deletion_costs_fast(
    r_codes: np.ndarray, standard_cost: float, confusion_cost: float
) -> np.ndarray:
    n = len(r_codes)
    costs = np.full(n, standard_cost, dtype=np.float64)
    for j in range(n):
        code = r_codes[j]
        if j > 0 and code == r_codes[j - 1]:
            costs[j] = confusion_cost
        elif code in (97, 105, 117):  # 'a', 'i', 'u'
            costs[j] = standard_cost * 0.85
    return costs
