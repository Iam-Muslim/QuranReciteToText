"""Fixed Quran Reference Data Structures & Medina Mushaf Indexer.

Defines the memory-mapped representation of Surahs, verses, words,
and reading sequence calculation for linear and repeated recitations.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from collections import defaultdict
from typing import List, Dict, Any, Tuple
import numpy as np


@dataclass
class ContinuousQuranWord:
    """Individual word entry in the Medina reference text."""
    global_index: int
    surah: int
    ayah: int
    word_in_ayah: int
    uthmani: str
    phoneme: str
    location: str


RefWord = ContinuousQuranWord


class SurahReferenceData:
    """Indexed reference representation for a single Surah."""

    def __init__(self, surah: int, verses_dict: Dict[str, Any]):
        self.surah = surah
        self.words: List[ContinuousQuranWord] = []
        self.ayah_to_words: Dict[int, List[ContinuousQuranWord]] = defaultdict(list)
        self.ayah_texts: Dict[int, str] = {}
        self.ayah_start_word_index: Dict[int, int] = {}

        a = 1
        while f"{surah}:{a}" in verses_dict:
            v_data = verses_dict[f"{surah}:{a}"]
            ayah_text = v_data.get("aya_text", "")
            self.ayah_texts[a] = ayah_text
            ph_words = v_data.get("aya_phonemes_list", [])
            text_words = [w for w in re.split(r"\s+", ayah_text.strip()) if w]

            if ph_words:
                self.ayah_start_word_index[a] = len(self.words)
                for i, ph_w in enumerate(ph_words):
                    txt = text_words[i] if i < len(text_words) else str(ph_w)
                    cw = ContinuousQuranWord(
                        global_index=len(self.words),
                        surah=surah,
                        ayah=a,
                        word_in_ayah=i + 1,
                        uthmani=txt,
                        phoneme=str(ph_w),
                        location=f"{surah}:{a}:{i + 1}",
                    )
                    self.words.append(cw)
                    self.ayah_to_words[a].append(cw)
            a += 1

        self.num_words = len(self.words)
        self.word_boundaries = [0]
        for w in self.words:
            self.word_boundaries.append(self.word_boundaries[-1] + len(w.phoneme))
        self.full_phonemes = "".join(w.phoneme for w in self.words)

        # Word-level offsets
        self.flat_phone_to_word = np.zeros(len(self.full_phonemes), dtype=np.int32)
        for w_idx, w in enumerate(self.words):
            s = self.word_boundaries[w_idx]
            e = self.word_boundaries[w_idx + 1]
            self.flat_phone_to_word[s:e] = w_idx

        self.avg_phones_per_word = max(1.0, len(self.full_phonemes) / max(1, self.num_words))

