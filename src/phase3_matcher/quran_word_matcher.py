"""Phase 3 Quran Word Matcher: Pure DTW alignment and word sequencing across single/multi-Surah audio recordings.

Mirrors Dart lib/phase3_matcher/quran_word_matcher.dart exactly.
"""

from __future__ import annotations
import json
import os
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any

from config import DEFAULT_QURAN_PHONEMES_PATH, DEFAULT_REF_NORM_PH_PATH, DEFAULT_PH_INDEX_PATH
from src.core.models import PhonemeToken, QuranSegment
from src.phase4_export.quran_json_exporter import QuranJsonExporter
from src.phase3_matcher.matcher_config import MatcherConfig
from src.phase3_matcher.dictation_matcher import QuranDictationMatcher
from src.phase3_matcher.dictation_sequencer import DictationSequencer, RefWord, SequencedWord
from src.phase3_matcher.surah_finder.models import SurahAudioBlock
from src.phase3_matcher.surah_finder.multi_surah_finder import MultiSurahFinder


@dataclass
class MatchedAyah:
    """Strongly-typed mathematical match result for a single Ayah before export formatting."""
    segment_number: int
    surah: int
    ayah: int
    ayah_text: str
    v_key: str
    transcribed_text: str
    words: List[SequencedWord]
    has_missing_words: bool
    default_ayah_start: float
    prologue: Optional[Dict[str, Any]] = None
    repeated_ranges: List[Dict[str, Any]] = field(default_factory=list)
    repeated_text: List[str] = field(default_factory=list)


class BaseQuranMatcher(ABC):
    """Abstract contract for Phase 3 Quran Matcher implementations."""

    @abstractmethod
    def match_segments(
        self,
        aligned_phonemes: List[PhonemeToken],
        audio_duration: float,
        target_surah: Optional[int] = None,
        start_ayah: Optional[int] = None,
    ) -> List[QuranSegment]:
        pass


class QuranWordMatcher(BaseQuranMatcher):
    """Phase 3 Quran Word Matcher and Verse Finder engine."""

    _istiadhah_ph = "ءَعُۥذُبِللَااهِمِنَششَيطَاانِرَّجِۦۦۦۦم"
    _basmalah_ph = "بِسمِللَااهِررَحمَاانِررَحِۦۦۦۦم"

    def __init__(self, config: MatcherConfig = MatcherConfig()):
        self.config = config
        self.surah_finder = MultiSurahFinder()
        self._sequencer = DictationSequencer()
        self._dtw_matcher = QuranDictationMatcher()
        self._verses: Dict[str, Any] = {}
        self._is_initialized: bool = False

    @property
    def is_initialized(self) -> bool:
        return self._is_initialized

    def initialize_from_data(self, quran_json_data: Dict[str, Any]) -> None:
        self._verses = quran_json_data.get("verses", {})
        self._is_initialized = True

    def initialize_from_file(
        self,
        json_file_path: Optional[str] = None,
        ref_norm_ph_path: Optional[str] = None,
        ph_index_path: Optional[str] = None,
    ) -> None:
        path = json_file_path or DEFAULT_QURAN_PHONEMES_PATH
        if not os.path.exists(path):
            raise FileNotFoundError(f"Quran phonemes file not found at: {path}")

        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.initialize_from_data(data)

        self.surah_finder.initialize(
            quran_json_path=path,
            ref_norm_ph_path=ref_norm_ph_path or DEFAULT_REF_NORM_PH_PATH,
            ph_index_path=ph_index_path or DEFAULT_PH_INDEX_PATH,
        )

    def _ensure_initialized(self) -> None:
        if not self._is_initialized:
            self.initialize_from_file()
        if not self.surah_finder.is_initialized:
            self.surah_finder.initialize()

    def detect_surah_blocks(self, aligned_phonemes: List[PhonemeToken]) -> List[SurahAudioBlock]:
        """Detects all Surah blocks present in a continuous audio recording."""
        self._ensure_initialized()
        return self.surah_finder.detect_multiple_surahs(aligned_phonemes)

    def detect_surah_and_ayah(
        self,
        aligned_phonemes: List[PhonemeToken],
        sample_length: int = 35,
    ) -> Dict[str, int]:
        """Fast single Surah & starting Ayah detection."""
        self._ensure_initialized()
        res = self.surah_finder.detect_single_surah(aligned_phonemes, sample_length=sample_length)
        return {"surah": res.surah, "ayah": res.start_ayah}

    def match_ayahs(
        self,
        aligned_phonemes: List[PhonemeToken],
        audio_duration: float,
        target_surah: Optional[int] = None,
        start_ayah: Optional[int] = None,
    ) -> List[MatchedAyah]:
        """Core Phase 3 matching: returns pure mathematical match results per Ayah."""
        self._ensure_initialized()
        if not aligned_phonemes or not self._verses:
            return []

        self._sequencer.reset()

        if target_surah is not None:
            return self._match_surah_span(
                aligned_phonemes=aligned_phonemes,
                surah=target_surah,
                start_ayah=start_ayah or 1,
                start_segment_number=1,
            )

        surah_blocks = self.surah_finder.detect_multiple_surahs(aligned_phonemes)
        all_ayahs: List[MatchedAyah] = []
        cur_segment_num = 1

        for block in surah_blocks:
            block_ayahs = self._match_surah_span(
                aligned_phonemes=block.phonemes,
                surah=block.surah_number,
                start_ayah=block.start_ayah,
                start_segment_number=cur_segment_num,
            )
            all_ayahs.extend(block_ayahs)
            cur_segment_num += len(block_ayahs)

        return all_ayahs

    def match_segments(
        self,
        aligned_phonemes: List[PhonemeToken],
        audio_duration: float,
        target_surah: Optional[int] = None,
        start_ayah: Optional[int] = None,
    ) -> List[QuranSegment]:
        """Convenience facade: executes Phase 3 matching then formats into QuranSegments."""
        ayahs = self.match_ayahs(
            aligned_phonemes=aligned_phonemes,
            audio_duration=audio_duration,
            target_surah=target_surah,
            start_ayah=start_ayah,
        )
        return QuranJsonExporter.build_segments(ayahs)

    def _match_surah_span(
        self,
        aligned_phonemes: List[PhonemeToken],
        surah: int,
        start_ayah: int,
        start_segment_number: int,
    ) -> List[MatchedAyah]:
        ayahs: List[MatchedAyah] = []
        if not aligned_phonemes:
            return ayahs

        # 1. Expand aligned_phonemes into continuous character stream and character-indexed arrays
        asr_buffer: List[str] = []
        char_start_ts: List[float] = []
        char_end_ts: List[float] = []
        char_to_tokens: List[PhonemeToken] = []

        for tok in aligned_phonemes:
            for ch in tok.phoneme:
                asr_buffer.append(ch)
                char_start_ts.append(tok.start)
                char_end_ts.append(tok.end)
                char_to_tokens.append(tok)

        full_asr_text = "".join(asr_buffer)
        current_char_idx = 0

        # 2. Build continuous RefWord stream for the entire Surah
        surah_words: List[RefWord] = []
        ayah_start_indices: List[int] = []
        ayah_texts: Dict[int, str] = {}

        a = start_ayah
        while f"{surah}:{a}" in self._verses:
            v_data = self._verses[f"{surah}:{a}"]
            ayah_text = v_data.get("aya_text", "")
            ph_words_list = v_data.get("aya_phonemes_list", [])

            text_words = [w for w in re.split(r"\s+", ayah_text.strip()) if w]
            ph_words = [str(p) for p in ph_words_list]

            if ph_words:
                ayah_start_indices.append(len(surah_words))
                ayah_texts[a] = ayah_text

                for i, ph_word in enumerate(ph_words):
                    txt = text_words[i] if i < len(text_words) else ph_word
                    surah_words.append(
                        RefWord(
                            global_index=len(surah_words),
                            surah=surah,
                            ayah=a,
                            word_index_in_ayah=i + 1,
                            text=txt,
                            ref_phoneme=ph_word,
                            location=f"{surah}:{a}:{i + 1}",
                        )
                    )
            a += 1

        if not surah_words:
            return ayahs

        # 3. Audio-Onset Prologue check (guard Surah 1 and Surah 9)
        initial_prologue: Optional[Dict[str, Any]] = None

        def apply_prologue(match: Optional[Dict[str, Any]]) -> None:
            nonlocal initial_prologue, current_char_idx
            if match is not None and initial_prologue is None:
                initial_prologue = match
                chars_consumed = match.pop("chars_consumed", 0)
                current_char_idx += chars_consumed

        if surah != 1 and surah != 9:
            apply_prologue(
                self._match_preamble(
                    asr_text=full_asr_text,
                    char_start_ts=char_start_ts,
                    char_end_ts=char_end_ts,
                    ref_ph=f"{self._istiadhah_ph}{self._basmalah_ph}",
                    preamble_type="istiadhah+basmalah",
                    text="أَعُوذُ بِٱللَّهِ مِنَ ٱلشَّيْطَـٰنِ ٱلرَّجِيمِ بِسْمِ ٱللَّهِ ٱلرَّحْمَـٰنِ ٱلرَّحِيمِ",
                    max_chars=120,
                )
            )

        apply_prologue(
            self._match_preamble(
                asr_text=full_asr_text,
                char_start_ts=char_start_ts,
                char_end_ts=char_end_ts,
                ref_ph=self._istiadhah_ph,
                preamble_type="istiadhah",
                text="أَعُوذُ بِٱللَّهِ مِنَ ٱلشَّيْطَـٰنِ ٱلرَّجِيمِ",
                max_chars=60,
            )
        )

        # 4. Standalone Basmalah check for Ayah 1 (excluding Surah 1 & 9)
        if initial_prologue is None and start_ayah == 1 and surah != 1 and surah != 9:
            apply_prologue(
                self._match_preamble(
                    asr_text=full_asr_text[current_char_idx:],
                    char_start_ts=char_start_ts[current_char_idx:],
                    char_end_ts=char_end_ts[current_char_idx:],
                    ref_ph=self._basmalah_ph,
                    preamble_type="basmalah",
                    text="بِسْمِ ٱللَّهِ ٱلرَّحْمَـٰنِ ٱلرَّحِيمِ",
                    max_chars=60,
                )
            )

        # 5. Unified Continuous Word Sequence Tracking across the Entire Surah
        default_start = (
            char_start_ts[current_char_idx]
            if current_char_idx < len(char_start_ts)
            else 0.0
        )

        seq_result = self._sequencer.sequence_words(
            asr_text=full_asr_text[current_char_idx:],
            asr_start_timestamps=char_start_ts[current_char_idx:],
            asr_end_timestamps=char_end_ts[current_char_idx:],
            char_to_tokens=char_to_tokens[current_char_idx:],
            ref_words=surah_words,
            config=self.config,
            default_start_time=default_start,
            ayah_start_indices=ayah_start_indices,
        )

        # 6. Partition the continuous sequenced words into Ayah segments
        words_by_ayah: Dict[int, List[SequencedWord]] = {}
        for sw in seq_result.words:
            words_by_ayah.setdefault(sw.ayah, []).append(sw)

        segment_number = start_segment_number

        for cur_ayah, a_words in words_by_ayah.items():
            if not a_words:
                continue

            v_key = f"{surah}:{cur_ayah}"
            a_text = ayah_texts.get(cur_ayah, "")

            a_reps = [
                r for r in seq_result.repeated_ranges
                if str(r.get("from_ref", "")).startswith(f"{surah}:{cur_ayah}:")
            ]

            a_start = a_words[0].start
            a_end = a_words[-1].end

            for rep in a_reps:
                fst = rep.get("first_start_time")
                if fst is not None and fst < a_start:
                    a_start = fst

            first_idx = -1
            for idx, ts in enumerate(char_start_ts):
                if ts >= a_start:
                    first_idx = idx
                    break

            last_match = -1
            for idx in range(len(char_end_ts) - 1, -1, -1):
                if char_end_ts[idx] <= a_end:
                    last_match = idx
                    break

            last_idx = (
                min(len(full_asr_text), last_match + 1)
                if last_match >= 0
                else len(full_asr_text)
            )

            a_transcribed = (
                full_asr_text[first_idx:last_idx]
                if (0 <= first_idx < last_idx)
                else ""
            )

            a_rep_texts = [str(r.get("text", "")) for r in a_reps]

            ayahs.append(
                MatchedAyah(
                    segment_number=segment_number,
                    surah=surah,
                    ayah=cur_ayah,
                    ayah_text=a_text,
                    v_key=v_key,
                    transcribed_text=a_transcribed,
                    prologue=initial_prologue if cur_ayah == start_ayah else None,
                    words=a_words,
                    has_missing_words=any(w.is_red for w in a_words),
                    default_ayah_start=a_start,
                    repeated_ranges=a_reps,
                    repeated_text=a_rep_texts,
                )
            )
            segment_number += 1

        return ayahs

    def _match_preamble(
        self,
        asr_text: str,
        char_start_ts: List[float],
        char_end_ts: List[float],
        ref_ph: str,
        preamble_type: str,
        text: str,
        max_chars: int = 60,
    ) -> Optional[Dict[str, Any]]:
        """Compact preamble matcher (Isti'adhah / Basmalah)."""
        if len(asr_text) < 15:
            return None

        check_len = min(len(asr_text), max_chars)
        slice_text = asr_text[:check_len]
        slice_ts = char_start_ts[:check_len]

        res = self._dtw_matcher.match_word(
            asr_text=slice_text,
            asr_timestamps=slice_ts,
            full_phonemes=ref_ph,
            ref_start=0,
            ref_end=len(ref_ph),
            config=self.config,
        )

        if res is not None and res.tokens_consumed > 0 and res.path_cost <= 0.25:
            start_time = (
                res.timestamps[0]
                if res.timestamps
                else (char_start_ts[0] if char_start_ts else 0.0)
            )
            last_char = min(res.tokens_consumed - 1, len(char_end_ts) - 1)
            end_time = (
                char_end_ts[last_char]
                if last_char >= 0
                else (start_time + 0.5)
            )

            return {
                "type": preamble_type,
                "text": text,
                "start_time": round(start_time, 2),
                "end_time": round(end_time, 2),
                "score": round(max(0.0, min(1.0, 1.0 - res.path_cost)), 2),
                "chars_consumed": res.tokens_consumed,
            }

        return None
