"""Multi-Surah Detection Engine that identifies multiple distinct Surahs and Ayah ranges in a single continuous audio file.

Mirrors Dart lib/phase3_matcher/surah_finder/multi_surah_finder.dart exactly.
"""

from __future__ import annotations
import json
import os
from dataclasses import dataclass
from typing import Optional, List, Dict, Any

from config import DEFAULT_QURAN_PHONEMES_PATH
from src.core.models import PhonemeToken
from src.phase3_matcher.surah_finder.models import SurahDetectionResult, SurahAudioBlock
from src.phase3_matcher.surah_finder.phonetic_search import PhoneticSearch


@dataclass
class _TimelineProbe:
    phoneme_idx: int
    timestamp: float
    surah: int
    ayah: int
    distance: int


class MultiSurahFinder:
    """Detects single or multiple Surah passages in a continuous recitation."""

    def __init__(self):
        self._phonetic_search = PhoneticSearch()
        self._verses: Dict[str, Any] = {}
        self._is_initialized: bool = False

    @property
    def is_initialized(self) -> bool:
        return self._is_initialized

    def initialize(
        self,
        quran_json_path: Optional[str] = None,
        ref_norm_ph_path: Optional[str] = None,
        ph_index_path: Optional[str] = None,
    ) -> None:
        """Initializes the Quran reference data and binary index."""
        if self._is_initialized:
            return

        json_path = quran_json_path or DEFAULT_QURAN_PHONEMES_PATH
        if os.path.exists(json_path):
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                self._verses = data.get("verses", {})

        self._phonetic_search.load(
            ref_norm_ph_path=ref_norm_ph_path,
            ph_index_path=ph_index_path,
        )

        self._is_initialized = True

    def _ensure_initialized(self) -> None:
        if not self._is_initialized:
            self.initialize()

    def detect_single_surah(
        self,
        aligned_phonemes: List[PhonemeToken],
        sample_length: int = 35,
    ) -> SurahDetectionResult:
        """Fast single Surah & starting Ayah detection from an initial audio sample."""
        self._ensure_initialized()
        if not aligned_phonemes:
            return SurahDetectionResult(surah=1, start_ayah=1, end_ayah=1)

        query_text = "".join(p.phoneme for p in aligned_phonemes[:sample_length])
        results = self._phonetic_search.search(query_text, error_ratio=0.25)

        if results:
            best = results[0]

            # If initial query matched Basmalah (1:1), but audio is longer, check if it was just a prologue
            if best.surah_number == 1 and best.ayah_number == 1 and len(aligned_phonemes) > 20:
                for offset in (10, 16, 20, 24, 28, 30, 32, 36):
                    if offset < len(aligned_phonemes):
                        post_query = "".join(p.phoneme for p in aligned_phonemes[offset:offset + sample_length])
                        if len(post_query) >= 6:
                            post_results = self._phonetic_search.search(post_query, error_ratio=0.25)
                            if post_results and post_results[0].surah_number != 1:
                                post_best = post_results[0]
                                return SurahDetectionResult(
                                    surah=post_best.surah_number,
                                    start_ayah=post_best.ayah_number,
                                    end_ayah=post_best.ayah_number,
                                    start_time=aligned_phonemes[0].start,
                                    end_time=aligned_phonemes[-1].end,
                                    confidence=max(0.5, 1.0 - (post_best.distance / max(1, len(post_query)))),
                                )

            return SurahDetectionResult(
                surah=best.surah_number,
                start_ayah=best.ayah_number,
                end_ayah=best.ayah_number,
                start_time=aligned_phonemes[0].start,
                end_time=aligned_phonemes[-1].end,
                confidence=max(0.5, 1.0 - (best.distance / max(1, len(query_text)))),
            )

        # If initial query didn't match, try skipping possible Isti'adhah/Basmalah prologue
        if len(aligned_phonemes) > 15:
            for offset in (10, 16, 20, 24, 28, 30, 32, 36):
                if offset < len(aligned_phonemes):
                    post_query = "".join(p.phoneme for p in aligned_phonemes[offset:offset + sample_length])
                    if len(post_query) >= 6:
                        post_results = self._phonetic_search.search(post_query, error_ratio=0.25)
                        if post_results:
                            post_best = post_results[0]
                            return SurahDetectionResult(
                                surah=post_best.surah_number,
                                start_ayah=post_best.ayah_number,
                                end_ayah=post_best.ayah_number,
                                start_time=aligned_phonemes[0].start,
                                end_time=aligned_phonemes[-1].end,
                                confidence=max(0.5, 1.0 - (post_best.distance / max(1, len(post_query)))),
                            )

        # Fallback: Default to Surah 1 Ayah 1
        return SurahDetectionResult(
            surah=1,
            start_ayah=1,
            end_ayah=1,
            start_time=aligned_phonemes[0].start,
            end_time=aligned_phonemes[-1].end,
            confidence=0.5,
        )

    def detect_multiple_surahs(
        self,
        aligned_phonemes: List[PhonemeToken],
        probe_window_size: int = 35,
        probe_step_size: int = 25,
    ) -> List[SurahAudioBlock]:
        """Partitions a continuous audio stream into multiple distinct SurahAudioBlock sections."""
        self._ensure_initialized()
        if not aligned_phonemes:
            return []

        total_phonemes = len(aligned_phonemes)

        # If audio is short (< 80 phonemes), treat as single block
        if total_phonemes < 80:
            single = self.detect_single_surah(aligned_phonemes)
            meta = self._get_surah_metadata(single.surah, single.start_ayah)
            return [
                SurahAudioBlock(
                    block_index=1,
                    surah_number=single.surah,
                    surah_name_ar=meta.get("ar", ""),
                    surah_name_en=meta.get("en", ""),
                    start_ayah=single.start_ayah,
                    end_ayah=single.end_ayah,
                    start_time_seconds=aligned_phonemes[0].start,
                    end_time_seconds=aligned_phonemes[-1].end,
                    start_phoneme_idx=0,
                    end_phoneme_idx=total_phonemes,
                    confidence=single.confidence,
                    phonemes=aligned_phonemes,
                )
            ]

        # ── 1. Sparse Timeline Probing ──
        probes: List[_TimelineProbe] = []

        for idx in range(0, total_phonemes - 10, probe_step_size):
            length = min(probe_window_size, total_phonemes - idx)
            slice_tokens = aligned_phonemes[idx:idx + length]
            query = "".join(p.phoneme for p in slice_tokens)

            results = self._phonetic_search.search(query, error_ratio=0.22)
            if results:
                best = results[0]
                probes.append(
                    _TimelineProbe(
                        phoneme_idx=idx,
                        timestamp=slice_tokens[0].start,
                        surah=best.surah_number,
                        ayah=best.ayah_number,
                        distance=best.distance,
                    )
                )

        if not probes:
            single = self.detect_single_surah(aligned_phonemes)
            meta = self._get_surah_metadata(single.surah, single.start_ayah)
            return [
                SurahAudioBlock(
                    block_index=1,
                    surah_number=single.surah,
                    surah_name_ar=meta.get("ar", ""),
                    surah_name_en=meta.get("en", ""),
                    start_ayah=single.start_ayah,
                    end_ayah=single.end_ayah,
                    start_time_seconds=aligned_phonemes[0].start,
                    end_time_seconds=aligned_phonemes[-1].end,
                    start_phoneme_idx=0,
                    end_phoneme_idx=total_phonemes,
                    phonemes=aligned_phonemes,
                )
            ]

        # ── 2. Temporal Clustering & Transition Point Detection ──
        blocks: List[SurahAudioBlock] = []
        block_idx = 1

        cur_surah = probes[0].surah
        cur_start_ayah = probes[0].ayah
        cur_max_ayah = probes[0].ayah
        cur_start_phoneme_idx = 0
        cur_start_time = aligned_phonemes[0].start

        for i in range(1, len(probes)):
            probe = probes[i]

            # Check if Surah changed
            if probe.surah != cur_surah:
                # Confirmation check: verify that this is not an isolated random noise probe
                confirmed = False
                if i + 1 < len(probes) and probes[i + 1].surah == probe.surah:
                    confirmed = True
                elif i + 1 >= len(probes):
                    confirmed = True

                if confirmed:
                    # Surah transition detected at probe.phoneme_idx!
                    end_phoneme_idx = probe.phoneme_idx
                    end_time = aligned_phonemes[min(end_phoneme_idx, total_phonemes - 1)].start
                    meta = self._get_surah_metadata(cur_surah, cur_start_ayah)

                    slice_tokens = aligned_phonemes[cur_start_phoneme_idx:end_phoneme_idx]

                    blocks.append(
                        SurahAudioBlock(
                            block_index=block_idx,
                            surah_number=cur_surah,
                            surah_name_ar=meta.get("ar", ""),
                            surah_name_en=meta.get("en", ""),
                            start_ayah=cur_start_ayah,
                            end_ayah=cur_max_ayah,
                            start_time_seconds=cur_start_time,
                            end_time_seconds=end_time,
                            start_phoneme_idx=cur_start_phoneme_idx,
                            end_phoneme_idx=end_phoneme_idx,
                            phonemes=slice_tokens,
                        )
                    )
                    block_idx += 1

                    # Start new block
                    cur_surah = probe.surah
                    cur_start_ayah = probe.ayah
                    cur_max_ayah = probe.ayah
                    cur_start_phoneme_idx = end_phoneme_idx
                    cur_start_time = end_time
            else:
                # Same Surah, update max Ayah seen
                if probe.ayah > cur_max_ayah:
                    cur_max_ayah = probe.ayah

        # Close the final block
        meta = self._get_surah_metadata(cur_surah, cur_start_ayah)
        slice_tokens = aligned_phonemes[cur_start_phoneme_idx:total_phonemes]

        blocks.append(
            SurahAudioBlock(
                block_index=block_idx,
                surah_number=cur_surah,
                surah_name_ar=meta.get("ar", ""),
                surah_name_en=meta.get("en", ""),
                start_ayah=cur_start_ayah,
                end_ayah=cur_max_ayah,
                start_time_seconds=cur_start_time,
                end_time_seconds=aligned_phonemes[-1].end,
                start_phoneme_idx=cur_start_phoneme_idx,
                end_phoneme_idx=total_phonemes,
                phonemes=slice_tokens,
            )
        )

        return blocks

    def _get_surah_metadata(self, surah: int, ayah: int) -> Dict[str, str]:
        key = f"{surah}:{ayah}"
        if key in self._verses:
            v = self._verses[key]
            return {
                "ar": str(v.get("suraname_ar", "")),
                "en": str(v.get("suraname_en", "")),
            }
        return {"ar": "", "en": ""}
