"""QuranReciteToText Package Entry Point & Central Pipeline Coordinator."""

from __future__ import annotations

import os
import sys
import time
import logging
from typing import Optional, Callable, Dict, Any, List, Union, Tuple
import numpy as np

from config import (
    SAMPLE_RATE,
    BLANK_ID,
    DEFAULT_MODEL_PATH,
    DEFAULT_TOKENS_PATH,
    DEFAULT_QURAN_PHONEMES_PATH,
    DEFAULT_REF_NORM_PH_PATH,
    DEFAULT_PH_INDEX_PATH,
    ENABLE_SPEECH_RECOVERY,
    SPEECH_RECOVERY_ENERGY_THRESHOLD_DB,
    SPEECH_RECOVERY_MIN_HOLE_DURATION_S,
    SPEECH_RECOVERY_PADDING_S,
    SPEECH_RECOVERY_MIN_PHONEMES_IN_GAP,
)
from src.models import (
    PhonemeToken,
    RawTranscriptionResult,
    RecoveryEvent,
    RecoverySummary,
    SpeechRecoveryResult,
    QuranWord,
    AyahSubSegment,
    QuranSegment,
    PipelineProfiling,
    PipelineResult,
    PipelineStage,
    PipelineProgressEvent,
)
from src.audio import AudioDecoder
from src.transcriber import ZipformerONNX, SpeechRecoveryEngine
from src.aligner import CtcViterbiAligner
from src.matcher import QuranWordMatcher, MatcherConfig
from src.exporter import QuranJsonExporter

logger = logging.getLogger(__name__)


class AudioPipeline:
    """Central 4-phase audio transcription and Quran alignment coordinator."""

    def __init__(self):
        self.transcriber = ZipformerONNX.get_instance()
        self.matcher = QuranWordMatcher()

    def initialize(
        self,
        model_path: str = DEFAULT_MODEL_PATH,
        tokens_path: str = DEFAULT_TOKENS_PATH,
        quran_phonemes_path: str = DEFAULT_QURAN_PHONEMES_PATH,
        ref_norm_ph_path: str = DEFAULT_REF_NORM_PH_PATH,
        ph_index_path: str = DEFAULT_PH_INDEX_PATH,
        num_threads: int = 2,
    ) -> None:
        if not self.matcher.is_initialized and os.path.exists(quran_phonemes_path):
            self.matcher.initialize_from_file(
                json_file_path=quran_phonemes_path,
                ref_norm_ph_path=ref_norm_ph_path,
                ph_index_path=ph_index_path,
            )

    def process_audio_file(
        self,
        audio_file_path: str,
        output_dir: str = ".",
        export_json_files: bool = True,
        on_progress_event: Optional[Callable[[PipelineProgressEvent], None]] = None,
    ) -> PipelineResult:
        load_start = time.time()
        if on_progress_event:
            on_progress_event(
                PipelineProgressEvent(stage=PipelineStage.loading, percent=0.0, elapsed_seconds=0.0, message="Loading audio...")
            )

        audio_pcm = AudioDecoder.load_audio_file(audio_file_path)
        load_time = time.time() - load_start

        return self.process_pcm(
            audio_pcm=audio_pcm,
            load_time=load_time,
            output_dir=output_dir,
            export_json_files=export_json_files,
            on_progress_event=on_progress_event,
        )

    def process_pcm(
        self,
        audio_pcm: np.ndarray,
        load_time: float = 0.0,
        output_dir: str = ".",
        export_json_files: bool = True,
        on_progress_event: Optional[Callable[[PipelineProgressEvent], None]] = None,
    ) -> PipelineResult:
        overall_start = time.time()
        audio_duration = len(audio_pcm) / SAMPLE_RATE

        # Phase 1: ASR Transcription
        asr_start = time.time()
        raw_result = self.transcriber.transcribe_audio(audio=audio_pcm, sample_rate=SAMPLE_RATE)
        raw_phonemes = raw_result.phonemes
        asr_time = time.time() - asr_start

        # Phase 1.1: Speech Recovery (if enabled)
        effective_phonemes = raw_phonemes
        recovery_events: List[RecoveryEvent] = []
        recovery_summary = RecoverySummary(0.0, 0, 0, 0, 0)
        recovery_time = 0.0

        if ENABLE_SPEECH_RECOVERY:
            rec_start = time.time()
            rec_res = SpeechRecoveryEngine.recover_speech(
                audio_pcm=audio_pcm,
                initial_phonemes=raw_phonemes,
                audio_duration=audio_duration,
                transcriber=self.transcriber,
            )
            effective_phonemes = rec_res.recovered_phonemes
            recovery_events = rec_res.recovery_events
            recovery_summary = rec_res.recovery_summary
            recovery_time = time.time() - rec_start

        # Phase 2: CTC Viterbi Trellis Alignment
        align_start = time.time()
        aligned_phonemes = CtcViterbiAligner.align_phonemes(
            target_phonemes=effective_phonemes,
            audio_duration=audio_duration,
            token2id=self.transcriber.token2id,
            logprobs_matrix=raw_result.logprobs_matrix,
            num_frames=raw_result.num_frames,
            custom_blank_id=BLANK_ID,
        )
        align_time = time.time() - align_start

        # Phase 3: Quran Text Matcher & Sequencer
        match_start = time.time()
        if not self.matcher.is_initialized:
            self.matcher.initialize_from_file()

        segments = self.matcher.match_segments(
            aligned_phonemes=aligned_phonemes,
            audio_duration=audio_duration,
        )
        match_time = time.time() - match_start

        # Phase 4: Post-Processing & JSON Export
        export_start = time.time()
        segments = QuranJsonExporter.process_segments(segments)

        if export_json_files:
            QuranJsonExporter.export_all(
                output_dir=output_dir,
                audio_duration=audio_duration,
                raw_phonemes=raw_phonemes,
                recovery_summary=recovery_summary,
                recovery_events=recovery_events,
                aligned_phonemes=aligned_phonemes,
                segments=segments,
            )
        export_time = time.time() - export_start
        total_time = time.time() - overall_start

        profiling = PipelineProfiling(
            audio_duration=audio_duration,
            load_time=load_time,
            asr_time=asr_time,
            recovery_time=recovery_time,
            alignment_time=align_time,
            match_time=match_time,
            export_time=export_time,
            total_time=total_time,
        )

        return PipelineResult(
            audio_duration_seconds=audio_duration,
            raw_phonemes=raw_phonemes,
            recovered_phonemes=effective_phonemes,
            recovery_events=recovery_events,
            recovery_summary=recovery_summary,
            ctc_aligned_phonemes=aligned_phonemes,
            segments=segments,
            total_processing_time_seconds=total_time,
            profiling=profiling,
        )


_shared_pipeline: Optional[AudioPipeline] = None


def get_shared_pipeline() -> AudioPipeline:
    global _shared_pipeline
    if _shared_pipeline is None:
        _shared_pipeline = AudioPipeline()
        _shared_pipeline.initialize()
    return _shared_pipeline


def process_audio(
    audio_data: Union[str, np.ndarray, Tuple[int, np.ndarray]],
    output_dir: str = ".",
    export_json_files: bool = False,
    return_profiling: bool = False,
) -> Union[List[Dict[str, Any]], Tuple[List[Dict[str, Any]], PipelineProfiling]]:
    """Functional one-line runner for audio alignment."""
    pipeline = get_shared_pipeline()
    if isinstance(audio_data, str):
        result = pipeline.process_audio_file(
            audio_file_path=audio_data,
            output_dir=output_dir,
            export_json_files=export_json_files,
        )
    elif isinstance(audio_data, tuple):
        orig_sr, pcm = audio_data
        if orig_sr != SAMPLE_RATE:
            import librosa
            pcm = librosa.resample(pcm.astype(np.float32), orig_sr=orig_sr, target_sr=SAMPLE_RATE)
        result = pipeline.process_pcm(
            audio_pcm=pcm.astype(np.float32),
            output_dir=output_dir,
            export_json_files=export_json_files,
        )
    else:
        result = pipeline.process_pcm(
            audio_pcm=audio_data.astype(np.float32),
            output_dir=output_dir,
            export_json_files=export_json_files,
        )

    segments_dicts = [s.to_dict() for s in result.segments]
    if return_profiling:
        return segments_dicts, result.profiling
    return segments_dicts


__all__ = [
    "AudioPipeline",
    "process_audio",
    "get_shared_pipeline",
    "AudioDecoder",
    "ZipformerONNX",
    "SpeechRecoveryEngine",
    "CtcViterbiAligner",
    "QuranWordMatcher",
    "MatcherConfig",
    "QuranJsonExporter",
    "PhonemeToken",
    "QuranWord",
    "QuranSegment",
    "AyahSubSegment",
    "PipelineResult",
    "PipelineProfiling",
    "PipelineStage",
    "PipelineProgressEvent",
]
