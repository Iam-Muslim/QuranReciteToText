"""Tajweed-Aware Phonetic & Acoustic Cost Engine for Zipformer-P Arabic ASR.

Mirrors Dart lib/phase3_matcher/phonetic_cost_engine.dart exactly.
"""

from __future__ import annotations


class PhoneticCostEngine:
    """Evaluates phonetic, acoustic, and Tajweed costs between ASR predictions and Quran reference."""

    # ── 1. Zero-Cost Tajweed & Auxiliary Markers ──
    @staticmethod
    def is_zero_cost_marker(code_unit: int) -> bool:
        return (
            code_unit == 0x0686 or  # 'چ' - Qalqalah variant
            code_unit == 0x0687 or  # 'ڇ' - Qalqalah release burst
            code_unit == 0x06DC or  # 'ۜ' - Sakt
            code_unit == 0x0619 or  # 'ؙ' - Ishmam
            code_unit == 0x06EA or  # '۪' - Imalah
            code_unit == 0x0640     # 'ـ' - Tatweel
        )

    @staticmethod
    def is_zero_cost_token(token: str) -> bool:
        return token in ('ـ', 'ــ', 'ۜ', 'ؙ', '۪', 'ڇ', 'چ')

    # ── 2. Interchangeable Quranic Glyphs (Cost = 0.0) ──
    @classmethod
    def is_equivalent_glyph(cls, a: int, b: int) -> bool:
        if a == b:
            return True

        asr_code = min(a, b)
        ref_code = max(a, b)

        if asr_code == 0x0645 and ref_code == 0x06FE:
            return True  # م <-> ۾ (Iqlab)
        if asr_code == 0x0646 and ref_code == 0x06BA:
            return True  # ن <-> ں (Ikhfaa)
        if asr_code == 0x0648 and ref_code == 0x06E5:
            return True  # و <-> ۥ (Small Waw)
        if asr_code == 0x064A and ref_code == 0x06E6:
            return True  # ي <-> ۦ (Small Yaa)

        if cls.is_hamza_variant(asr_code) and cls.is_hamza_variant(ref_code):
            return True

        # Ta-Marbuta (ة) sounds like Haa (ه) in Waqf or Taa (ت) in Wasl
        if asr_code == 0x0629 and ref_code == 0x0647:
            return True  # ة <-> ه
        if (asr_code == 0x0629 and ref_code == 0x062A) or (asr_code == 0x062A and ref_code == 0x0629):
            return True  # ة <-> ت

        return False

    @staticmethod
    def is_hamza_variant(code: int) -> bool:
        return code in (0x0621, 0x0622, 0x0623, 0x0625, 0x0672)  # ء, آ, أ, إ, ٲ

    # ── 3. Model Acoustic Confusion Matrix (Cost = 0.25) ──
    @staticmethod
    def is_acoustic_confusion(asr_code: int, ref_code: int) -> bool:
        if asr_code > ref_code:
            asr_code, ref_code = ref_code, asr_code

        # Vowels vs Harakat (Short vs Long vowel duration confusion)
        if asr_code == 0x0627:  # ا (Alif)
            return ref_code == 0x064E  # َ (Fatha)
        if asr_code == 0x0648:  # و (Waw)
            return ref_code == 0x064F  # ُ (Damma)
        if asr_code == 0x064F:  # ُ (Damma) (smaller than Small Waw 0x06E5)
            return ref_code == 0x06E5  # ۥ (Small Waw)
        if asr_code == 0x064A:  # ي (Yaa)
            return ref_code == 0x0650  # ِ (Kasra)
        if asr_code == 0x0650:  # ِ (Kasra) (smaller than Small Yaa 0x06E6)
            return ref_code == 0x06E6  # ۦ (Small Yaa)

        # Consonant acoustic confusions
        if asr_code == 0x062A:  # ت
            return ref_code == 0x0637  # ط
        if asr_code == 0x062C:  # ج
            return ref_code == 0x0632  # ز
        if asr_code == 0x062E:  # خ
            return ref_code == 0x063A  # غ
        if asr_code == 0x062F:  # د
            return ref_code == 0x0636  # ض
        if asr_code == 0x0630:  # ذ
            return ref_code in (0x0632, 0x0638)  # ز, ظ
        if asr_code == 0x0633:  # س
            return ref_code == 0x0635  # ص
        if asr_code == 0x0642:  # ق
            return ref_code == 0x0643  # ك

        return False

    # ── 4. Tashkeel / Short Vowel Detection (Cost = 1.0) ──
    @staticmethod
    def is_tashkeel(code: int) -> bool:
        return code in (0x064E, 0x064F, 0x0650)  # Fatha, Damma, Kasra

    # ── 5. Substitution Cost Evaluation ──
    @classmethod
    def get_substitution_cost(
        cls,
        asr_code_unit: int,
        ref_code_unit: int,
        acoustic_confusion_cost: float = 0.25,
    ) -> float:
        if asr_code_unit == 0 or ref_code_unit == 0:
            return 1.0
        if asr_code_unit == ref_code_unit:
            return 0.0

        if cls.is_equivalent_glyph(asr_code_unit, ref_code_unit):
            return 0.0

        if cls.is_acoustic_confusion(asr_code_unit, ref_code_unit):
            return acoustic_confusion_cost

        # Harakat mismatch (e.g. Fatha vs Kasra)
        if cls.is_tashkeel(asr_code_unit) or cls.is_tashkeel(ref_code_unit):
            return 1.00

        return 1.00

    # ── 6. Deletion Cost (Missing expected reference sound) ──
    @classmethod
    def get_deletion_cost(
        cls,
        full_phonemes: str,
        g_ref_idx: int,
        standard_deletion_cost: float = 1.0,
        acoustic_confusion_cost: float = 0.25,
    ) -> float:
        if g_ref_idx < 0 or g_ref_idx >= len(full_phonemes):
            return standard_deletion_cost
        code = ord(full_phonemes[g_ref_idx])

        if cls.is_zero_cost_marker(code):
            return 0.0

        if cls.is_hamza_variant(code):
            return acoustic_confusion_cost

        # CTC acoustic spike compression discount
        if g_ref_idx > 0 and code == ord(full_phonemes[g_ref_idx - 1]):
            return acoustic_confusion_cost

        return standard_deletion_cost

    # ── 7. Insertion Cost (Extra ASR sound) ──
    @classmethod
    def get_insertion_cost(
        cls,
        asr_text: str,
        asr_idx: int,
        standard_insertion_cost: float = 1.0,
        acoustic_confusion_cost: float = 0.25,
    ) -> float:
        if asr_idx < 0 or asr_idx >= len(asr_text):
            return standard_insertion_cost
        code = ord(asr_text[asr_idx])

        if cls.is_zero_cost_marker(code):
            return 0.0

        # Consecutive vowel insertion discount (CTC prolonged acoustic spike)
        if asr_idx > 0 and code == ord(asr_text[asr_idx - 1]):
            if code in (0x0627, 0x0648, 0x064A, 0x06E5, 0x06E6):
                return acoustic_confusion_cost

        return standard_insertion_cost

    # ── 8. Effective Length Calculation ──
    @classmethod
    def get_effective_length(cls, phonemes: str, start: int, end: int) -> int:
        eff = 0
        limit = min(end, len(phonemes))
        for j in range(start, limit):
            code = ord(phonemes[j])
            if cls.is_zero_cost_marker(code):
                continue
            if (
                j > start
                and code == ord(phonemes[j - 1])
                and code in (0x0627, 0x0648, 0x064A, 0x06E5, 0x06E6)
            ):
                continue
            eff += 1
        return max(1, eff)

    # ── CamelCase Aliases for 100% Dart Parity ──
    isZeroCostMarker = is_zero_cost_marker
    isZeroCostToken = is_zero_cost_token
    isEquivalentGlyph = is_equivalent_glyph
    isHamzaVariant = is_hamza_variant
    isAcousticConfusion = is_acoustic_confusion
    isTashkeel = is_tashkeel
    getSubstitutionCost = get_substitution_cost
    getDeletionCost = get_deletion_cost
    getInsertionCost = get_insertion_cost
    getEffectiveLength = get_effective_length
