"""Pipeline package — orchestrates qua_sdk stages for the aligner app."""

from src.pipeline.entries import process_audio
from src.pipeline.outcome import PipelineOutcome

__all__ = [
    "PipelineOutcome",
    "process_audio",
]
