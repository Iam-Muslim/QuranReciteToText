"""Fixed Quran Reference Data Structures & Medina Mushaf Indexer.

Defines the indexed representation of Surahs, verses, words,
and phoneme sequences for recitation alignment.
"""

from __future__ import annotations

import os
import struct
from dataclasses import dataclass
from collections import defaultdict
from typing import List, Dict, Optional, Tuple
import numpy as np

import config


class ZfxReader:
    """Direct binary reader for expected_tj3.zfx Quran reference data."""

    def __init__(
        self,
        zfx_path: str,
        tokens_path: str,
        qpc_path: Optional[str] = None,
    ):
        if not os.path.isfile(zfx_path):
            raise FileNotFoundError(f"ZFX reference file not found: {zfx_path}")
        if not os.path.isfile(tokens_path):
            raise FileNotFoundError(f"Tokens file not found: {tokens_path}")

        with open(zfx_path, "rb") as f:
            self.data = f.read()
        if len(self.data) < 160 or self.data[:8] != b"ZFTJEXP1":
            raise ValueError(f"Invalid ZFX magic header in {zfx_path}")

        self.tokens_map: Dict[int, str] = {}
        with open(tokens_path, "r", encoding="utf-8") as f:
            for line in f:
                parts = line.strip().split()
                if len(parts) == 2:
                    self.tokens_map[int(parts[1])] = parts[0]

        # Extract section offsets from 160-byte header
        self.sec_offsets = [struct.unpack("<I", self.data[i : i + 4])[0] for i in range(104, 136, 4)]
        self.surah_table = self.data[self.sec_offsets[0] : self.sec_offsets[1]]
        self.ayah_table = self.data[self.sec_offsets[1] : self.sec_offsets[2]]
        self.sec2_tokens = self.data[self.sec_offsets[2] : self.sec_offsets[3]]
        self.sec3_words = self.data[self.sec_offsets[3] : self.sec_offsets[4]]

        self.surahs = struct.unpack(f"<{len(self.surah_table) // 2}H", self.surah_table)
        self.surah_start_ayah_idx = [0]
        for count in self.surahs:
            self.surah_start_ayah_idx.append(self.surah_start_ayah_idx[-1] + count)

        # Load Medina Mushaf Uthmani text mapping from QPC Hafs reference
        self.qpc_words: Dict[Tuple[int, int], List[str]] = defaultdict(list)
        target_qpc = qpc_path or getattr(config, "DEFAULT_QPC_HAFS_PATH", None)
        if target_qpc and os.path.isfile(target_qpc):
            import json
            with open(target_qpc, "r", encoding="utf-8") as f:
                qpc_data = json.load(f)
            for k, v in qpc_data.items():
                s, a, _ = map(int, k.split(":"))
                self.qpc_words[(s, a)].append(v.get("text", ""))

        self._global_search_index: Optional[Tuple[str, np.ndarray, np.ndarray]] = None

    def get_global_phonetic_search_index(self) -> Tuple[str, np.ndarray, np.ndarray]:
        """Extracts the full continuous Quran phonetic text, character codes, and (surah, ayah) index.

        Derives exact character codes and coordinates directly from expected_tj3.zfx in memory.

        Returns:
            (ref_norm_ph, ref_codes, index_array)
            where:
                ref_norm_ph: continuous phoneme string for the whole Quran (522,475 chars)
                ref_codes: np.ndarray of int32 character ordinals (shape: (522475,))
                index_array: np.ndarray of shape (522475, 2) dtype uint16 with [surah, ayah]
        """
        if self._global_search_index is not None:
            return self._global_search_index

        char_map = {tid: [ord(c) for c in tok] for tid, tok in self.tokens_map.items() if tok != "|"}
        ayah_fmt = f"<{len(self.ayah_table) // 20 * 5}I"
        ayah_ints = struct.unpack(ayah_fmt, self.ayah_table)

        codes: List[int] = []
        coords: List[Tuple[int, int]] = []
        g_idx = 0
        for s_idx, num_ayahs in enumerate(self.surahs):
            s = s_idx + 1
            for a in range(1, num_ayahs + 1):
                tok_off = ayah_ints[g_idx * 5]
                tok_count = ayah_ints[g_idx * 5 + 3] & 0xFFFF
                g_idx += 1
                toks = self.sec2_tokens[tok_off : tok_off + tok_count]
                for t in toks:
                    c_list = char_map.get(t)
                    if c_list:
                        for c in c_list:
                            codes.append(c)
                            coords.append((s, a))

        ref_codes = np.array(codes, dtype=np.int32)
        ref_norm_ph = "".join(chr(c) for c in codes)
        index_array = np.array(coords, dtype=np.uint16)

        self._global_search_index = (ref_norm_ph, ref_codes, index_array)
        return self._global_search_index

    def get_surah_data(self, surah: int) -> Tuple[Dict[int, List[str]], Dict[int, List[str]]]:
        """Extracts aligned phonetic words and Medina Mushaf Uthmani words for all Ayahs in the Surah.

        Returns:
            (ayah_phoneme_words, ayah_uthmani_words)
        """
        if surah < 1 or surah > len(self.surahs):
            return {}, {}

        s_idx = surah - 1
        start_ayah_g = self.surah_start_ayah_idx[s_idx]
        num_ayahs = self.surahs[s_idx]

        ayah_ph_words: Dict[int, List[str]] = {}
        ayah_uthmani_words: Dict[int, List[str]] = {}

        for a in range(1, num_ayahs + 1):
            g_idx = start_ayah_g + (a - 1)
            tok_off, tj_off, var_off, count_packed, word_count = struct.unpack(
                "<5I", self.ayah_table[g_idx * 20 : (g_idx + 1) * 20]
            )
            tok_count = count_packed & 0xFFFF
            toks = self.sec2_tokens[tok_off : tok_off + tok_count]
            w_ids = self.sec3_words[tok_off : tok_off + tok_count]

            words: List[str] = []
            curr_word: List[str] = []
            curr_wid = None
            for t, wid in zip(toks, w_ids):
                ch = self.tokens_map.get(t, "")
                if ch == "|":
                    continue
                if curr_wid is not None and wid != curr_wid:
                    words.append("".join(curr_word))
                    curr_word = []
                curr_wid = wid
                curr_word.append(ch)
            if curr_word:
                words.append("".join(curr_word))

            # Merge Muqatta'at letters if present so phonetic word count matches QPC Medina Mushaf 1:1
            qpc_list = self.qpc_words.get((surah, a))
            if qpc_list:
                diff = len(words) - len(qpc_list)
                if diff > 0:
                    words = ["".join(words[: diff + 1])] + words[diff + 1 :]
                ayah_ph_words[a] = words
                ayah_uthmani_words[a] = qpc_list
            else:
                ayah_ph_words[a] = words
                ayah_uthmani_words[a] = words

        return ayah_ph_words, ayah_uthmani_words

    def get_surah_words(self, surah: int) -> Dict[int, List[str]]:
        """Extracts cleanly separated phonetic words for all Ayahs in the requested Surah."""
        ph_words, _ = self.get_surah_data(surah)
        return ph_words


@dataclass(slots=True)
class RefWord:
    """Individual word entry in the Medina Mushaf reference text."""
    global_index: int
    surah: int
    ayah: int
    word_in_ayah: int
    uthmani: str
    phoneme: str
    location: str


class SurahReferenceData:
    """Indexed reference representation for a single Surah."""

    def __init__(
        self,
        surah: int,
        ayah_words: Dict[int, List[str]],
        uthmani_words: Optional[Dict[int, List[str]]] = None,
    ):
        self.surah = surah
        self.words: List[RefWord] = []
        self.ayah_to_words: Dict[int, List[RefWord]] = defaultdict(list)
        self.ayah_start_word_index: Dict[int, int] = {}

        for a in sorted(ayah_words.keys()):
            ph_words = ayah_words[a]
            u_words = uthmani_words.get(a) if uthmani_words else None
            if ph_words:
                self.ayah_start_word_index[a] = len(self.words)
                for i, ph_w in enumerate(ph_words):
                    uthmani_txt = u_words[i] if (u_words and i < len(u_words)) else str(ph_w)
                    w = RefWord(
                        global_index=len(self.words),
                        surah=surah,
                        ayah=a,
                        word_in_ayah=i + 1,
                        uthmani=uthmani_txt,
                        phoneme=str(ph_w),
                        location=f"{surah}:{a}:{i + 1}",
                    )
                    self.words.append(w)
                    self.ayah_to_words[a].append(w)

        self.num_words = len(self.words)
        self.word_boundaries = [0]
        for w in self.words:
            self.word_boundaries.append(self.word_boundaries[-1] + len(w.phoneme))
        self.full_phonemes = "".join(w.phoneme for w in self.words)

        self.flat_phone_to_word = np.zeros(len(self.full_phonemes), dtype=np.int32)
        for w_idx, w in enumerate(self.words):
            s = self.word_boundaries[w_idx]
            e = self.word_boundaries[w_idx + 1]
            self.flat_phone_to_word[s:e] = w_idx
