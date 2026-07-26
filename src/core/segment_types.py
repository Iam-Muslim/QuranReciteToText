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
        # Determine if this segment is a special construct (like the Basmala)
        # Import the special names set from the qua_sdk domain.
        from qua_sdk.domain import SPECIAL_NAMES as ALL_SPECIAL_REFS
        # Check if the matched reference is in the set of special names.
        is_special = self.matched_ref in ALL_SPECIAL_REFS
        
        # Execute if this is a special reference (like "basmala").
        if is_special:
            # Special refs don't have start/end verse bounds, so empty them.
            ref_from, ref_to = "", ""
        # Execute if the reference contains a hyphen (indicating a range).
        elif self.matched_ref and "-" in self.matched_ref:
            # Split the reference string exactly once on the hyphen.
            parts = self.matched_ref.split("-", 1)
            # Assign the parts to from and to variables.
            ref_from, ref_to = parts[0], parts[1]
        # Execute if it's a standard single-word reference.
        else:
            # Assign the same reference to both from and to.
            ref_from = ref_to = self.matched_ref or ""
            
        # Build the core JSON dictionary
        # Initialize the output dictionary with required fields.
        d = {
            # Assign the sequence number.
            "segment": self.segment_number,
            # Round to milliseconds
            # Round start_time to 3 decimal places.
            "time_from": round(self.start_time, 3), 
            # Round end_time to 3 decimal places.
            "time_to": round(self.end_time, 3),
            # Assign the start reference boundary.
            "ref_from": ref_from,
            # Assign the end reference boundary.
            "ref_to": ref_to,
            # Ensure matched text is never None.
            "matched_text": self.matched_text or "",
            # Round the confidence score to 3 decimal places.
            "confidence": round(self.match_score, 3),
            # Assign the missing words boolean flag.
            "has_missing_words": self.has_missing_words,
            # Assign the repeated words boolean flag.
            "has_repeated_words": self.has_repeated_words,
            # Embed the special reference string if applicable, else None.
            "special_type": self.matched_ref if is_special else None,
            # Pass along any error states.
            "error": self.error,
        }
        
        # Conditionally append optional fields if they exist
        # Check if wrap ranges exist.
        if self.wrap_word_ranges:
            # Add wrap_word_ranges to the dictionary.
            d["wrap_word_ranges"] = self.wrap_word_ranges
        # Check if repeated ranges exist.
        if self.repeated_ranges:
            # Add repeated_ranges to the dictionary.
            d["repeated_ranges"] = self.repeated_ranges
        # Check if repeated text translations exist.
        if self.repeated_text:
            # Add repeated_text to the dictionary.
            d["repeated_text"] = self.repeated_text
            
        # Process and attach word-level timings if requested
        # Check if word timings should be included and if they actually exist.
        if include_words and self.words is not None:
            # Capture the start time of the segment for relative calculations.
            seg_start = self.start_time
            # Define an internal helper function to format a single word timing dictionary.
            def _make_word(w):
                # Initialize an empty dictionary for the word.
                entry = {}
                # Set the word text.
                entry["word"] = w.get("word", "")
                # Ensure the location key exists before transferring it.
                if "location" in w:
                    # Transfer the location reference string.
                    entry["location"] = w["location"]
                # Convert absolute audio timestamps into times relative to the start of this specific segment.
                # Calculate the relative start time, flooring at 0.0, and round to 4 decimals.
                entry["start"] = round(max(0.0, w.get("start", 0.0) - seg_start), 4)
                # Calculate the relative end time, flooring at 0.0, and round to 4 decimals.
                entry["end"] = round(max(0.0, w.get("end", 0.0) - seg_start), 4)
                # Return the formatted word dictionary.
                return entry
            # Process all words and assign the resulting array to the main dictionary.
            d["words"] = [_make_word(w) for w in self.words]
            
        # Append various grouping/dedup fields if they exist
        # Check for split group ID.
        if self.split_group_id:
            # Inject split group ID.
            d["split_group_id"] = self.split_group_id
        # Check for merge group ID.
        if self.merge_group_id:
            # Inject merge group ID.
            d["merge_group_id"] = self.merge_group_id
        # Check for merge members stash.
        if self.merge_members:
            # Inject merge members stash.
            d["merge_members"] = self.merge_members
        # Check for partial merge leftover string.
        if self.partial_merge_leftover:
            # Inject partial merge leftover string.
            d["partial_merge_leftover"] = self.partial_merge_leftover
        # Check if segment is marked as duplicated.
        if self.duplicated:
            # Inject duplicated boolean flag.
            d["duplicated"] = True
        # Check if duplicate kind string exists.
        if self.duplicate_kind is not None:
            # Inject duplicate kind string.
            d["duplicate_kind"] = self.duplicate_kind
        # Check if duplicate context string exists.
        if self.duplicate_context is not None:
            # Inject duplicate context string.
            d["duplicate_context"] = self.duplicate_context
        # Check if superseded ID exists.
        if self.duplicated_by_segment is not None:
            # Inject superseded ID.
            d["duplicated_by_segment"] = self.duplicated_by_segment
            
        # Return the fully constructed JSON dictionary.
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


# Define a utility function to convert a list of SegmentInfo objects to JSON.
def segments_to_json(segments: list, include_words: bool = False) -> dict:
    """
    Utility function to convert a list of SegmentInfo objects into the final 
    master JSON payload dictionary.
    """
    # Return a dictionary containing a 'segments' array.
    # The array is constructed using a list comprehension that calls to_json_dict on every object.
    return {"segments": [seg.to_json_dict(include_words=include_words) for seg in segments]}


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

    # Define a method to generate a human-readable text summary of the profiling data.
    def summary(self) -> str:
        # A docstring explaining the summary method.
        """Returns a human-readable string summarizing the pipeline's performance."""
        # Alias the internal formatting function for brevity.
        _fmt = self._fmt
        # Initialize a list of strings representing the lines of the summary output.
        lines = [
            # A decorative header line.
            "\n" + "=" * 60,
            # The title of the summary.
            "PROFILING SUMMARY",
            # A decorative header line.
            "=" * 60,
            # The preprocessing section title.
            f"  Preprocessing:",
            # Output the time taken for FFmpeg resampling.
            f"    Resample:        {self.resample_time:.3f}s",
            # Output the total ASR execution wall time.
            f"  ASR (Transcription):                 wall {_fmt(self.asr_time)}",
            # Output the ASR sorting time.
            f"    Sorting:         {self.asr_sorting_time:.3f}s",
            # Output the ASR batch build time.
            f"    Batch Build:     {self.asr_batch_build_time:.3f}s",
            # Output the number of processed batches.
            f"    Batches:         {len(self.asr_batch_profiling) if self.asr_batch_profiling else 0}",
        ]
        
        # Detailed batch logging for debugging ASR performance
        # Check if batch profiling statistics exist.
        if self.asr_batch_profiling:
            # Loop through each batch dictionary.
            for b in self.asr_batch_profiling:
                # Extract QK MB per head metric.
                qk_per = b.get('qk_mb_per_head')
                # Extract total QK MB metric.
                qk_all = b.get('qk_mb_all_heads')
                # Construct a string showing memory footprint if the metrics exist.
                qk_str = f", QK^T {qk_per:.1f} MB/head, {qk_all:.0f} MB total" if qk_per is not None else ""
                # Append a highly detailed row summarizing this specific batch's performance to the lines array.
                lines.append(
                    f"    Batch {b['batch_num']:>2}: {b['size']:>3} segs | "
                    f"{b['time']:.3f}s | "
                    f"{b['min_dur']:.2f}-{b['max_dur']:.2f}s "
                    f"(A {b['total_seconds']/b['size']:.2f}s, T {b['total_seconds']:.1f}s, W {b['pad_waste']:.0%}{qk_str})"
                )
                
        # Append Phase 2 statistics to the lines array.
        lines += [
            # The global anchor section title.
            f"  Global Anchor:",
            # Output the N-gram voting time.
            f"    N-gram Voting:   {self.anchor_time:.3f}s",
        ]
        
        # DP Math statistics
        # Calculate the success percentage of the DP engine, guarding against divide-by-zero.
        pct = 100 * self.segments_passed / self.segments_attempted if self.segments_attempted else 0
        # Fetch the retry segments list, defaulting to an empty list if None.
        retry_segs = self.retry_segments or []
        # Append alignment metrics to the lines array.
        lines += [
            # The alignment stats section title.
            f"  Alignment Stats:",
            # Output the total segments sent to DP.
            f"    Attempted:       {self.segments_attempted}",
            # Output the number of successful segments and percentage.
            f"    Passed:          {self.segments_passed}  ({pct:.1f}%)",
            # Output retry metrics.
            f"    Retries:         {self.retry_passed}/{self.retry_attempts} passed   segments: {retry_segs}",
            # Output reanchor metrics.
            f"    Reanchors (consec failures): {self.consec_reanchors}",
            # Output special merge metrics.
            f"    Special Merges:  {self.special_merges}",
            # Output transition skip metrics.
            f"    Transition Skips: {self.transition_skips}",
            # A decorative separator line.
            "-" * 60,
        ]
        
        # Final tally
        # Sum all individually profiled metrics to get the accounted time.
        profiled_sum = (self.resample_time + self.asr_time
                        + self.anchor_time + self.match_wall_time + self.result_build_time)
        # Subtract the accounted time from the true wall-clock time to find unaccounted overhead.
        unaccounted = self.total_time - profiled_sum
        # Append the final total statistics to the lines array.
        lines += [
            # Output the sum of all profiled steps.
            f"  PROFILED SUM:      {_fmt(profiled_sum)}",
            # Output the true wall-clock total and the unaccounted gap.
            f"  TOTAL (wall):      {_fmt(self.total_time)}   (unaccounted: {_fmt(unaccounted)})",
        ]
        # Append a closing decorative line.
        lines.append("=" * 60)
        # Join the list of strings with newline characters and return the massive text block.
        return "\n".join(lines)
