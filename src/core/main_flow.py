"""Central Pipeline Coordinator & Entry Point.

Orchestrates the 4 unified phases:
- Phase 1: Pure ONNX Zipformer CTC Transcription (phase1_transcriber)
- Phase 1.1: Speech & Repetition Recovery (phase1_transcriber)
- Phase 2: CTC Viterbi Trellis Forced Alignment (phase2_aligner)
- Phase 3: Tajweed Quran Text Matcher & Ayah Sequencer (phase3_matcher)
- Phase 4: Pause Calculation, Subsegmentation & JSON Export (phase4_export)

Mirrors Dart lib/core/pipeline.dart directly.
"""

from __future__ import annotations

import os
import sys
import time
import logging
from typing import Optional, Callable, Dict, Any, List, Union, Tuple
import numpy as np

from config import (
    PipelineConfig,
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
from src.core.models import (
    PipelineStage,
    PipelineProgressEvent,
    PipelineProfiling,
    PipelineResult,
    PhonemeToken,
    RecoveryEvent,
    RecoverySummary,
    QuranSegment,
)
from src.core.audio_decoder import AudioDecoder
from src.phase1_transcriber.transcriber import OfflineTranscriber
from src.phase1_transcriber.speech_recovery import SpeechRecoveryEngine
from src.phase2_aligner.ctc_aligner import CtcViterbiAligner
from src.phase3_matcher.quran_word_matcher import QuranWordMatcher, BaseQuranMatcher
from src.phase4_export.quran_json_exporter import QuranJsonExporter

logger = logging.getLogger(__name__)


class AudioPipeline:
    """Central 4-phase audio transcription and Quran alignment coordinator."""

    def __init__(self):
        self.transcriber: OfflineTranscriber = OfflineTranscriber.get_instance()
        self.matcher: BaseQuranMatcher = QuranWordMatcher()

    def initialize(
        self,
        model_path: str = DEFAULT_MODEL_PATH,
        tokens_path: str = DEFAULT_TOKENS_PATH,
        quran_phonemes_path: str = DEFAULT_QURAN_PHONEMES_PATH,
        ref_norm_ph_path: str = DEFAULT_REF_NORM_PH_PATH,
        ph_index_path: str = DEFAULT_PH_INDEX_PATH,
        num_threads: int = 2,
        custom_matcher: Optional[BaseQuranMatcher] = None,
    ) -> None:
        """Initializes acoustic and phonetic reference resources."""
        if custom_matcher is not None:
            self.matcher = custom_matcher

        if isinstance(self.matcher, QuranWordMatcher):
            if not self.matcher.is_initialized:
                if os.path.exists(quran_phonemes_path):
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
        on_progress: Optional[Callable[..., None]] = None,
    ) -> PipelineResult:
        """Processes an audio file from path (mirroring Dart AudioPipeline.processAudioFile)."""
        logger.info(f"[Pipeline] Step 1: Loading audio file: {audio_file_path}")
        load_start = time.time()

        if on_progress_event:
            on_progress_event(
                PipelineProgressEvent(
                    stage=PipelineStage.loading,
                    percent=0.0,
                    elapsed_seconds=0.0,
                    message="جارٍ قراءة وفك تشفير الملف الصوتي...",
                )
            )
        if on_progress:
            on_progress(PipelineStage.loading.name, 0.0, 0.0)

        audio_pcm = AudioDecoder.load_audio_file(audio_file_path)
        audio_duration = len(audio_pcm) / AudioDecoder.target_sample_rate
        load_time = time.time() - load_start

        logger.info(f"[Pipeline] Audio decoded: {audio_duration:.2f}s in {load_time:.2f}s")
        if on_progress_event:
            on_progress_event(
                PipelineProgressEvent(
                    stage=PipelineStage.loading,
                    percent=100.0,
                    elapsed_seconds=load_time,
                    message=f"تم فك تشفير الصوت ({audio_duration:.1f} ثانية)",
                )
            )
        if on_progress:
            on_progress(PipelineStage.loading.name, 100.0, load_time)

        return self.process_pcm(
            audio_pcm=audio_pcm,
            load_time=load_time,
            output_dir=output_dir,
            export_json_files=export_json_files,
            on_progress_event=on_progress_event,
            on_progress=on_progress,
        )

    def process_audio_bytes(
        self,
        audio_bytes: bytes,
        output_dir: str = ".",
        export_json_files: bool = True,
        on_progress_event: Optional[Callable[[PipelineProgressEvent], None]] = None,
        on_progress: Optional[Callable[..., None]] = None,
    ) -> PipelineResult:
        """Processes raw audio file bytes directly in memory."""
        logger.info(f"[Pipeline] Step 1: Decoding in-memory audio bytes ({len(audio_bytes)} bytes)...")
        load_start = time.time()

        if on_progress_event:
            on_progress_event(
                PipelineProgressEvent(
                    stage=PipelineStage.loading,
                    percent=0.0,
                    elapsed_seconds=0.0,
                    message="جارٍ قراءة وفك تشفير الملف الصوتي...",
                )
            )
        if on_progress:
            on_progress(PipelineStage.loading.name, 0.0, 0.0)

        audio_pcm = AudioDecoder.decode_bytes(audio_bytes)
        audio_duration = len(audio_pcm) / AudioDecoder.target_sample_rate
        load_time = time.time() - load_start

        if on_progress_event:
            on_progress_event(
                PipelineProgressEvent(
                    stage=PipelineStage.loading,
                    percent=100.0,
                    elapsed_seconds=load_time,
                    message=f"تم فك تشفير الصوت ({audio_duration:.1f} ثانية)",
                )
            )
        if on_progress:
            on_progress(PipelineStage.loading.name, 100.0, load_time)

        return self.process_pcm(
            audio_pcm=audio_pcm,
            load_time=load_time,
            output_dir=output_dir,
            export_json_files=export_json_files,
            on_progress_event=on_progress_event,
            on_progress=on_progress,
        )

    def process_pcm(
        self,
        audio_pcm: np.ndarray,
        load_time: float = 0.0,
        output_dir: str = ".",
        export_json_files: bool = True,
        on_progress_event: Optional[Callable[[PipelineProgressEvent], None]] = None,
        on_progress: Optional[Callable[..., None]] = None,
    ) -> PipelineResult:
        """Common pipeline execution from 16kHz normalized mono PCM (mirrors Dart processPcm)."""
        overall_start = time.time()
        audio_duration = len(audio_pcm) / AudioDecoder.target_sample_rate

        def emit(stage: PipelineStage, pct: float, elapsed: float, speed_x: Optional[float] = None, msg: str = ""):
            if on_progress_event:
                on_progress_event(
                    PipelineProgressEvent(
                        stage=stage,
                        percent=pct,
                        elapsed_seconds=elapsed,
                        speed_x=speed_x,
                        message=msg,
                    )
                )
            if on_progress:
                on_progress(stage.name, pct, elapsed, speed_x=speed_x)

        # ── 2. Phase 1: Pure ONNX Zipformer CTC Transcription ──
        logger.info("[Pipeline] Step 2: Phase 1 ONNX Zipformer CTC Transcription...")
        asr_start = time.time()
        emit(PipelineStage.transcribing, 0.0, 0.0, msg="بدء النسخ الصوتي...")

        def _on_asr_progress(pct: float, spd: float, elp: float):
            emit(
                PipelineStage.transcribing,
                pct,
                elp,
                speed_x=spd,
                msg=f"النسخ الصوتي: {pct:.1f}% ({spd:.1f}x)",
            )

        raw_result = self.transcriber.transcribe_audio(
            audio=audio_pcm,
            sample_rate=AudioDecoder.target_sample_rate,
            on_progress=_on_asr_progress,
        )
        raw_phonemes = raw_result.phonemes
        asr_time = time.time() - asr_start
        asr_speed = (audio_duration / asr_time) if asr_time > 0 else 0.0

        logger.info(
            f"[Pipeline] Phase 1 Finished: {len(raw_phonemes)} raw phonemes in {asr_time:.2f}s ({asr_speed:.1f}x)"
        )
        emit(
            PipelineStage.transcribing,
            100.0,
            asr_time,
            speed_x=asr_speed,
            msg=f"تم النسخ: {len(raw_phonemes)} فونيم ({asr_speed:.1f}x)",
        )

        # ── 3. Phase 1.1: Authentic Speech & Repetition Recovery ──
        recovery_start = time.time()
        effective_phonemes = raw_phonemes
        recovery_events: List[RecoveryEvent] = []
        recovery_summary = RecoverySummary(
            scanned_gaps_count=0,
            speech_holes_detected=0,
            recovered_events_count=0,
            recovered_phonemes_count=0,
            recovery_time_seconds=0.0,
            energy_threshold_db=SPEECH_RECOVERY_ENERGY_THRESHOLD_DB,
            min_hole_duration_s=SPEECH_RECOVERY_MIN_HOLE_DURATION_S,
        )
        recovery_time = 0.0

        if ENABLE_SPEECH_RECOVERY:
            logger.info("[Pipeline] Step 3: Phase 1.1 Speech & Repetition Recovery...")
            emit(PipelineStage.recovering, 0.0, 0.0, msg="فحص واسترجاع المقاطع غير المكتشفة...")

            def _on_rec_progress(pct: float, elp: float):
                spd = (audio_duration * (pct / 100.0)) / elp if elp > 0 else 0.0
                emit(
                    PipelineStage.recovering,
                    pct,
                    elp,
                    speed_x=spd,
                    msg=f"استرجاع الكلام: {pct:.1f}% ({spd:.1f}x)",
                )

            recovery_res = SpeechRecoveryEngine.recover_speech(
                audio_pcm=audio_pcm,
                initial_phonemes=raw_phonemes,
                audio_duration=audio_duration,
                transcriber=self.transcriber,
                energy_threshold_db=SPEECH_RECOVERY_ENERGY_THRESHOLD_DB,
                min_hole_duration_s=SPEECH_RECOVERY_MIN_HOLE_DURATION_S,
                padding_s=SPEECH_RECOVERY_PADDING_S,
                min_phonemes_in_gap=SPEECH_RECOVERY_MIN_PHONEMES_IN_GAP,
                on_progress=_on_rec_progress,
            )
            effective_phonemes = recovery_res.recovered_phonemes
            recovery_events = recovery_res.recovery_events
            recovery_summary = recovery_res.recovery_summary
            recovery_time = time.time() - recovery_start
            recovery_speed = (audio_duration / recovery_time) if recovery_time > 0 else 0.0

            logger.info(
                f"[Pipeline] Phase 1.1 Finished: {len(effective_phonemes)} effective phonemes "
                f"({len(recovery_events)} events) in {recovery_time:.2f}s"
            )
            emit(
                PipelineStage.recovering,
                100.0,
                recovery_time,
                speed_x=recovery_speed,
                msg=f"تم الاسترجاع: {len(effective_phonemes)} فونيم إجمالي ({len(recovery_events)} حدث)",
            )

        # ── 4. Phase 2: CTC Viterbi Trellis Forced Alignment ──
        logger.info("[Pipeline] Step 4: Phase 2 CTC Viterbi Trellis Forced Alignment...")
        align_start = time.time()
        emit(PipelineStage.aligning, 0.0, 0.0, msg="بدء المحاذاة الزمنية الدقيقة (CTC Aligner)...")

        aligned_phonemes = CtcViterbiAligner.align_phonemes(
            target_phonemes=effective_phonemes,
            audio_duration=audio_duration,
            token2id=self.transcriber.token2id,
            logprobs_matrix=raw_result.logprobs_matrix,
            num_frames=raw_result.num_frames,
            custom_blank_id=BLANK_ID,
        )
        align_time = time.time() - align_start

        logger.info(f"[Pipeline] Phase 2 Finished: {len(aligned_phonemes)} aligned phonemes in {align_time:.2f}s")
        emit(
            PipelineStage.aligning,
            100.0,
            align_time,
            msg=f"اكتملت المحاذاة: {len(aligned_phonemes)} فونيم في {align_time:.2f} ثانية",
        )

        # ── 5. Phase 3: Quran Text Matcher & Ayah/Word Segmentation ──
        logger.info("[Pipeline] Step 5: Phase 3 Quran Text Matcher & Verse Finder...")
        match_start = time.time()
        emit(PipelineStage.matching, 0.0, 0.0, msg="مطابقة النص القرآني وتقسيم الآيات والكلمات...")

        if isinstance(self.matcher, QuranWordMatcher) and not self.matcher.is_initialized:
            self.matcher.initialize_from_file()

        segments: List[QuranSegment] = self.matcher.match_segments(
            aligned_phonemes=aligned_phonemes,
            audio_duration=audio_duration,
        )
        match_time = time.time() - match_start

        logger.info(f"[Pipeline] Phase 3 Finished: {len(segments)} Quran segments matched in {match_time:.2f}s")
        emit(
            PipelineStage.matching,
            100.0,
            match_time,
            msg=f"اكتملت المطابقة: {len(segments)} مقطع قرآني في {match_time:.2f} ثانية",
        )

        # ── 6. Phase 4: JSON Export ──
        export_start = time.time()
        if export_json_files:
            emit(PipelineStage.exporting, 0.0, 0.0, msg="تصدير ملفات JSON...")
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
        emit(PipelineStage.exporting, 100.0, export_time, msg="تم تصدير ملفات JSON بنجاح")

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

        emit(
            PipelineStage.completed,
            100.0,
            total_time,
            speed_x=profiling.real_time_factor,
            msg=f"اكتملت المعالجة بنجاح ({profiling.real_time_factor:.1f}x)",
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

    def destroy(self) -> None:
        pass


_shared_pipeline: Optional[AudioPipeline] = None


def get_shared_pipeline() -> AudioPipeline:
    """Returns or lazily creates a shared singleton AudioPipeline instance."""
    global _shared_pipeline
    if _shared_pipeline is None:
        _shared_pipeline = AudioPipeline()
        _shared_pipeline.initialize()
    return _shared_pipeline


def process_audio(
    audio_data: Union[str, np.ndarray, Tuple[int, np.ndarray]],
    model_name: str = "Base",
    profile_name: str = "auto",
    return_profiling: bool = False,
    progress_callback=None,
    output_dir: str = ".",
    export_json_files: bool = False,
) -> Union[List[Dict[str, Any]], Tuple[List[Dict[str, Any]], PipelineProfiling]]:
    """Functional wrapper for AudioPipeline.

    Args:
        audio_data: Audio file path, raw numpy array, or (sample_rate, numpy_array).
        model_name: Acoustic model name (default: 'Base').
        profile_name: Transcription profile preset (default: 'auto').
        return_profiling: If True, returns (segments_dicts, profiling).
        progress_callback: Optional callable(pct, msg) for progress tracking.
        output_dir: Output directory for JSON files if export_json_files is True.
        export_json_files: If True, writes the 4 standard JSON artifacts to output_dir.

    Returns:
        List of segment dicts (or (segments, profiling) if return_profiling=True).
    """
    if audio_data is None:
        empty_prof = PipelineProfiling()
        return ([], empty_prof) if return_profiling else []

    pipeline = get_shared_pipeline()

    def _on_progress(stage: str, pct: float, elapsed: float, speed_x: Optional[float] = None):
        if progress_callback:
            msg = f"[{stage}] {pct:.1f}% ({speed_x:.1f}x)" if speed_x else f"[{stage}] {pct:.1f}%"
            try:
                progress_callback(pct, msg)
            except TypeError:
                progress_callback(pct)

    if isinstance(audio_data, str):
        result = pipeline.process_audio_file(
            audio_file_path=audio_data,
            output_dir=output_dir,
            export_json_files=export_json_files,
            on_progress=_on_progress,
        )
    elif isinstance(audio_data, tuple):
        orig_sr, pcm = audio_data
        if orig_sr != AudioDecoder.target_sample_rate:
            import librosa
            pcm = librosa.resample(pcm.astype(np.float32), orig_sr=orig_sr, target_sr=AudioDecoder.target_sample_rate)
        result = pipeline.process_pcm(
            audio_pcm=pcm.astype(np.float32),
            output_dir=output_dir,
            export_json_files=export_json_files,
            on_progress=_on_progress,
        )
    else:
        pcm = audio_data.astype(np.float32)
        result = pipeline.process_pcm(
            audio_pcm=pcm,
            output_dir=output_dir,
            export_json_files=export_json_files,
            on_progress=_on_progress,
        )

    segments_dicts = [s.to_dict() for s in result.segments]

    if return_profiling:
        return segments_dicts, result.profiling
    return segments_dicts
