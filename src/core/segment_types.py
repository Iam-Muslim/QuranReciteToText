"""
Data types for the segmentation pipeline.

This module defines the core data classes used throughout the application to store
information about each audio segment (start time, end time, transcribed text, matched text, etc.).
"""

# Import the dataclass decorator for clean, boilerplate-free data structures.
from dataclasses import dataclass
# Import the Optional type hint for attributes that can be None.
from typing import Optional


# Define a function to reconstruct the chronological reading order of repetitions.
def compute_reading_sequence(ref_from: str, ref_to: str,
                             wrap_word_ranges: list) -> list:
    """
    Computes the chronological reading order of verses when a reciter repeats a section.
    
    When reciters read, they often pause, jump backwards a few words to establish context, 
    and then continue. This function reconstructs that exact spoken sequence so UI applications
    can highlight the text exactly as it was spoken.
    
    Args:
        ref_from: The starting word of the entire sequence (e.g. "2:255:1")
        ref_to: The ending word of the entire sequence (e.g. "2:255:10")
        wrap_word_ranges: A list of tuples denoting where the reciter jumped back.

    Returns:
        A list of [start, end] string pairs showing the chronological reading order.
        Example: [["2:255:1", "2:255:5"], ["2:255:3", "2:255:8"]]
    """
    # Check if there are no wrap ranges (meaning no repetitions occurred).
    if not wrap_word_ranges:
        # Return a simple single-element list with the start and end points.
        return [[ref_from, ref_to]]
        
    # Check if wrap ranges exist and if they use the newer 3-element format.
    if wrap_word_ranges and len(wrap_word_ranges[0]) >= 3:
        # 3-element format: (jump_to, jump_from, repeat_end)
        # Forward section: The initial recitation before the first jump backwards.
        # Create the first section from the start to the word immediately before the first jump.
        sections = [[ref_from, wrap_word_ranges[0][1]]]
        
        # Each wrap represents a repeated sequence.
        # Loop through each wrap range tuple.
        for wr in wrap_word_ranges:
            # Append the repeated section based on the jump_to (0) and repeat_end (2) indices.
            sections.append([wr[0], wr[2]])
        # Return the fully reconstructed sequence.
        return sections

    # Legacy 2-element format: (jump_to, jump_from)
    # Create the first section from the start to the first jump_from point.
    sections = [[ref_from, wrap_word_ranges[0][1]]]
    # Loop through the remaining wraps, mapping each jump_to to the NEXT jump_from.
    for i in range(len(wrap_word_ranges) - 1):
        # Append the intermediate sections.
        sections.append([wrap_word_ranges[i][0], wrap_word_ranges[i + 1][1]])
    # Append the final section, from the last jump_to point to the absolute end.
    sections.append([wrap_word_ranges[-1][0], ref_to])
    # Return the reconstructed sequence.
    return sections


# Apply the dataclass decorator to the SegmentInfo class.
@dataclass
# Define the SegmentInfo class.
class SegmentInfo:
    """
    The master data structure representing a single logical segment of recitation.
    
    This object holds everything: the raw audio timestamps, the transcribed text from 
    FastConformer, the canonical matched text from the Quran index, and detailed 
    word-level timings.
    """
    # Audio Boundaries (in seconds)
    # The start time of the segment in seconds.
    start_time: float
    # The end time of the segment in seconds.
    end_time: float
    
    # Textual Information
    # The raw, imperfect output from FastConformer ASR.
    transcribed_text: str          
    # The perfect, canonical Quranic script from the DP matcher.
    matched_text: str              
    # The exact verse bounds (e.g. "2:255:1-2:255:5").
    matched_ref: str               
    # Confidence score (0.0 to 1.0) from the alignment engine.
    match_score: float             
    # Any processing errors encountered during DP.
    error: Optional[str] = None    
    
    # Grading & Anomaly Flags
    # True if the reciter skipped a required word (Hifz error).
    has_missing_words: bool = False   
    # True if the reciter jumped backwards.
    has_repeated_words: bool = False  
    
    # Repetition Tracking (Populated if has_repeated_words is True)
    # The raw wrap ranges from the DP engine.
    wrap_word_ranges: Optional[list] = None
    # The calculated chronological repetition ranges.
    repeated_ranges: Optional[list] = None   
    # The translated Arabic text for those repetitions.
    repeated_text: Optional[list] = None     
    
    # Miscellaneous State
    # 1-based index denoting order in the JSON array.
    segment_number: int = 0                  
    # Internal tracking for original references.
    _original_ref: Optional[str] = None      
    # Internal tracking for original DP score.
    _original_score: Optional[float] = None  
    # Boolean flag indicating if a human manually reviewed this segment.
    manually_confirmed: bool = False         
    
    # High-Fidelity Word & Letter Timestamps
    # A list of dictionaries containing precise word timings.
    words: Optional[list] = None             
    
    # Grouping IDs (Used for UI rendering of split/merged segments)
    # The 1-based ID from the raw SDK alignment output.
    _original_alignment_idx: Optional[int] = None
    # A unique hash ID linking segments that were split.
    split_group_id: Optional[str] = None
    # A unique hash ID linking segments that were algorithmically merged.
    merge_group_id: Optional[str] = None
    # JSON stashes of the pre-merge segment states.
    merge_members: Optional[list] = None
    # Unmatched Arabic text leftover from a partial merge.
    partial_merge_leftover: Optional[str] = None
    
    # Deduplication Flags (If multiple takes of the same verse exist)
    # Boolean flag indicating if this segment is a duplicate take.
    duplicated: bool = False
    # String indicating the reason/kind of deduplication.
    duplicate_kind: Optional[str] = None
    # Context string regarding the deduplication.
    duplicate_context: Optional[str] = None
    # The integer segment ID that supersedes this duplicate.
    duplicated_by_segment: Optional[int] = None

    # Define a method to convert this class into a JSON-ready dictionary.
    def to_json_dict(self, include_words: bool = False) -> dict:
        """
        Serializes this Python object into a clean dictionary ready for json.dump().
        This dictates exactly what the final output.json looks like.
        """
        from qua_sdk.domain import SPECIAL_NAMES as ALL_SPECIAL_REFS
        is_special = self.matched_ref in ALL_SPECIAL_REFS
        
        if is_special:
            ref_from, ref_to = "", ""
        elif self.matched_ref and "-" in self.matched_ref:
            parts = self.matched_ref.split("-", 1)
            ref_from, ref_to = parts[0], parts[1]
        else:
            ref_from = ref_to = self.matched_ref or ""
            
        d = {
            "segment": self.segment_number,
            "time_from": round(self.start_time, 3) if self.start_time is not None else None, 
            "time_to": round(self.end_time, 3) if self.end_time is not None else None,
            "ref_from": ref_from,
            "ref_to": ref_to,
            "matched_text": self.matched_text or "",
            "confidence": round(self.match_score, 3) if self.match_score is not None else 0.0,
            "has_missing_words": self.has_missing_words,
            "has_repeated_words": self.has_repeated_words,
            "special_type": self.matched_ref if is_special else None,
            "error": self.error,
        }
        
        if self.wrap_word_ranges:
            d["wrap_word_ranges"] = self.wrap_word_ranges
        if self.repeated_ranges:
            d["repeated_ranges"] = self.repeated_ranges
        if self.repeated_text:
            d["repeated_text"] = self.repeated_text
            
        if include_words and self.words is not None:
            def _make_word(w):
                entry = {}
                entry["word"] = w.get("word", "")
                if "location" in w:
                    entry["location"] = w["location"]
                if "line_idx" in w:
                    entry["line_idx"] = w["line_idx"]
                if w.get("is_missing"):
                    entry["is_missing"] = True
                    
                start_val = w.get("start")
                end_val = w.get("end")
                
                # Timestamps are natively relative to the segment's start time from Phase 3
                entry["start"] = round(start_val, 3) if start_val is not None else None
                entry["end"] = round(end_val, 3) if end_val is not None else None
                return entry
            d["words"] = [_make_word(w) for w in self.words]
            
        return d

    # Apply the classmethod decorator to define a factory constructor.
    @classmethod
    # Define a method to instantiate SegmentInfo from a JSON dict.
    def from_json_dict(cls, d: dict, index: int = 0) -> 'SegmentInfo':
        """
        Deserializes a JSON dictionary back into a SegmentInfo Python object.
        Used primarily when loading pre-existing sessions or cached data.
        """
        # Check if the special_type field is present in the dictionary.
        if d.get("special_type"):
            # Use the special_type value as the matched reference.
            ref = d["special_type"]
        # Check if ref_to field exists (indicating a range).
        elif d.get("ref_to"):
            # Construct a hyphenated range string.
            ref = f"{d['ref_from']}-{d['ref_to']}"
        # Execute if neither exist (meaning it's a single word or empty).
        else:
            # Use ref_from, defaulting to empty string.
            ref = d.get("ref_from", "")
            
        # Call the class constructor (cls) with dictionary values.
        return cls(
            # Extract time_from, defaulting to 0.
            start_time=d.get("time_from", 0),
            # Extract time_to, defaulting to 0.
            end_time=d.get("time_to", 0),
            # Set transcribed_text to an empty string (lost during serialization).
            transcribed_text="",
            # Extract matched_text, defaulting to an empty string.
            matched_text=d.get("matched_text", ""),
            # Set matched_ref to the string computed above.
            matched_ref=ref,
            # Extract confidence, defaulting to 0.
            match_score=d.get("confidence", 0),
            # Extract error string.
            error=d.get("error"),
            # Extract has_missing_words flag.
            has_missing_words=d.get("has_missing_words", False),
            # Extract has_repeated_words flag.
            has_repeated_words=d.get("has_repeated_words", False),
            # Extract wrap_word_ranges array.
            wrap_word_ranges=d.get("wrap_word_ranges"),
            # Extract repeated_ranges array.
            repeated_ranges=d.get("repeated_ranges"),
            # Extract repeated_text array.
            repeated_text=d.get("repeated_text"),
            # Extract segment number or compute it from the index parameter.
            segment_number=d.get("segment", index + 1),
            # Extract words array.
            words=d.get("words"),
            # Extract split_group_id.
            split_group_id=d.get("split_group_id"),
            # Extract merge_group_id.
            merge_group_id=d.get("merge_group_id"),
            # Extract merge_members array.
            merge_members=d.get("merge_members"),
            # Extract partial_merge_leftover string.
            partial_merge_leftover=d.get("partial_merge_leftover"),
            # Extract duplicated flag.
            duplicated=d.get("duplicated", False),
            # Extract duplicate_kind string.
            duplicate_kind=d.get("duplicate_kind"),
            # Extract duplicate_context string.
            duplicate_context=d.get("duplicate_context"),
            # Extract duplicated_by_segment ID.
            duplicated_by_segment=d.get("duplicated_by_segment"),
        )


# Apply the dataclass decorator to the ProfilingData class.
@dataclass
# Define the ProfilingData class.
class ProfilingData:
    """
    A tracking object used to measure exactly how many seconds each phase of 
    the pipeline takes. This is highly useful for benchmarking performance on 
    different CPU architectures.
    """
    # Preprocessing
    # Time spent in FFmpeg resampling
    resample_time: float = 0.0               
    
    # ASR (Phase 1) Profiling
    # Total FastConformer execution time
    asr_time: float = 0.0                    
    # Time taken to sort audio segments by length.
    asr_sorting_time: float = 0.0            
    # Time taken to group segments into computational batches.
    asr_batch_build_time: float = 0.0        
    # An array containing execution statistics for each individual batch.
    asr_batch_profiling: list = None         
    
    # Global Anchor & DP (Phase 2) Profiling
    # Time spent in N-gram anchoring
    anchor_time: float = 0.0                 
    # Total DP sequence matching time
    match_wall_time: float = 0.0             
    
    # DP Edge Cases
    # Total number of times the DP engine failed and retried.
    retry_attempts: int = 0
    # Total number of retries that successfully found a match.
    retry_passed: int = 0
    # List of segment IDs that required a retry.
    retry_segments: list = None
    # Number of times consecutive segments failed anchoring.
    consec_reanchors: int = 0
    # Total number of segments sent to the DP engine.
    segments_attempted: int = 0
    # Total number of segments successfully aligned by the DP engine.
    segments_passed: int = 0
    # Total number of special algorithm merges performed (e.g. Sakt/Waqf).
    special_merges: int = 0
    # Total number of transition skips executed.
    transition_skips: int = 0

    # Total End-to-End Pipeline Time
    # Time taken to construct the final JSON object.
    result_build_time: float = 0.0           
    # Time taken to encode audio chunks into base64 (if requested).
    result_audio_encode_time: float = 0.0    
    # Total wall-clock time from start to finish.
    total_time: float = 0.0                  

    # Apply the staticmethod decorator to define a utility function attached to the class.
    @staticmethod
    # Define an internal time formatting function.
    def _fmt(seconds):
        # A docstring explaining the formatting logic.
        """Format seconds as m:ss.fff when >= 60s, else as s.fffs."""
        # Check if the time is 60 seconds or longer.
        if seconds >= 60:
            # Calculate minutes and remaining seconds using divmod.
            m, s = divmod(seconds, 60)
            # Return string formatted as "M:SS.ms".
            return f"{int(m)}:{s:06.3f}"
        # Execute if time is less than 60 seconds.
        # Return string formatted as "SS.mss".
        return f"{seconds:.3f}s"

    def summary(self) -> str:
        """Returns a human-readable string summarizing the pipeline's performance."""
        _fmt = self._fmt
        lines = [
            "\n" + "=" * 60,
            "PROFILING SUMMARY",
            "=" * 60,
        ]
        
        if self.resample_time > 0.001:
            lines.append(f"  Resample:          {self.resample_time:.3f}s")
        if self.asr_time > 0.001:
            lines.append(f"  Transcription:     {_fmt(self.asr_time)}")
        if self.anchor_time > 0.001:
            lines.append(f"  N-gram Voting:     {self.anchor_time:.3f}s")
        if self.match_wall_time > 0.001:
            lines.append(f"  DP Matching:       {_fmt(self.match_wall_time)}")

        pct = 100 * self.segments_passed / self.segments_attempted if self.segments_attempted else 0
        lines.append(f"\n  Alignment:         {self.segments_passed}/{self.segments_attempted} segments ({pct:.1f}%)")
        
        if self.retry_attempts > 0:
            lines.append(f"  Retries:           {self.retry_passed}/{self.retry_attempts} passed")
        if self.consec_reanchors > 0:
            lines.append(f"  Reanchors:         {self.consec_reanchors}")
        if self.special_merges > 0:
            lines.append(f"  Special Merges:    {self.special_merges}")
        if self.transition_skips > 0:
            lines.append(f"  Transition Skips:  {self.transition_skips}")

        lines.append("-" * 60)
        lines.append(f"  TOTAL TIME:        {_fmt(self.total_time)}")
        lines.append("=" * 60)
        
        return "\n".join(lines)
