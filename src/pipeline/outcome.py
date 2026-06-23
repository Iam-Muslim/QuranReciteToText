"""PipelineOutcome — typed result of the pipeline entry functions."""
from dataclasses import dataclass
from typing import Any


@dataclass
class PipelineOutcome:
    """Result of process_audio / resegment_audio / retranscribe_audio / realign_audio.

    ``as_outputs()`` flattens to the positional 9-tuple the Gradio outputs
    wiring consumes — the field order is load-bearing, do not reorder.
    ``segments`` is a List[SegmentInfo] for UI callers and a JSON dict for API
    callers (``html`` is empty there).
    """
    html: Any = None
    segments: Any = None
    raw_speech_intervals: Any = None
    raw_is_complete: Any = None
    audio_ref: Any = None
    sample_rate: Any = None
    intervals: Any = None
    segment_dir: Any = None
    log_row: Any = None

    def as_outputs(self) -> tuple:
        return (self.html, self.segments, self.raw_speech_intervals,
                self.raw_is_complete, self.audio_ref, self.sample_rate,
                self.intervals, self.segment_dir, self.log_row)
