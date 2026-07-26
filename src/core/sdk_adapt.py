"""
SDK Adapter & Translation Layer

This module acts as a "translation layer" between the external qua_sdk (which generates the alignments)
and the specific JSON data structures expected by this application.

It converts SDK-specific objects like `Alignment`, `Emissions`, and `Regions` into 
app-specific objects like `SegmentInfo` and formatted dictionaries.
"""

# Import the annotations feature from __future__ for advanced type hinting.
from __future__ import annotations

# Import numpy for fast array manipulation.
import numpy as np

# Import specific schemas from the qua_sdk library.
from qua_sdk.schemas import Alignment, Emissions, Region, Regions, Timings

# Import the auto_merge functions to handle Sakt/Waqf merges.
from src.core.auto_merge import stamp_auto_merge_group, waqf_sakt_consumed_by_target
# Import the data types from the local segment_types module.
from src.core.segment_types import ProfilingData, SegmentInfo, compute_reading_sequence

# The global sample rate expectation for all time/sample conversions.
# Define the constant SAMPLE_RATE to 16,000 Hz.
SAMPLE_RATE = 16_000


# ==============================================================================
# 1. Primary Mapping Logic (Alignment -> SegmentInfo)
# ==============================================================================

# Define a function to convert an Alignment object to a list of SegmentInfos.
def alignment_to_segment_infos(
    # The primary Alignment object output by the SDK.
    alignment: Alignment,
    # The acoustic emissions (ASR output) from the FastConformer.
    emissions: Emissions,
    # The temporal regions (VAD output).
    regions: Regions,
) -> list[SegmentInfo]:
    """
    Converts the raw Dynamic Programming (DP) alignment output from the SDK 
    into a structured list of `SegmentInfo` objects.
    
    This function handles edge cases like "Waqf Sakt" (short pauses) where the SDK 
    may have forcefully merged two speech segments together to form a complete Ayah.
    """
    # Extract the raw transcribed tokens (the ASR output)
    # Get the raw list of tokens from the emissions object.
    tokens = emissions.tokens
    
    # Identify any segments that were automatically merged due to natural pauses (Sakt/Waqf)
    # Call the helper function to map parent IDs to absorbed segments.
    auto_merged = waqf_sakt_consumed_by_target(alignment)
    
    # Initialize an empty list to store the final SegmentInfo objects.
    segments: list[SegmentInfo] = []

    # Loop over every matched segment returned by the DP alignment engine.
    for seg in alignment.segments:
        # If this segment was absorbed into another segment during DP, skip it.
        # We only output the master "target" segment.
        # Check if the segment was merged into a parent.
        if seg.merged_into is not None:
            # Skip to the next iteration.
            continue

        # Extract the matched reference string, defaulting to an empty string.
        matched_ref = seg.matched_ref or ""
        
        # Reconstruct the transcribed string from the raw token array
        # Join the tokens with spaces, ensuring we don't index out of bounds.
        asr_text = " ".join(tokens[seg.id]) if seg.id < len(tokens) else ""
        
        # Handle repetitions (where a reciter repeats a phrase)
        # Extract the word wrapping ranges from the segment.
        wrap_ranges = seg.wrap_word_ranges
        # Call the derive_repetition helper to calculate exact repeated phrases.
        rep_ranges, rep_text = derive_repetition(matched_ref, wrap_ranges)

        # Create the high-level SegmentInfo object
        # Instantiate a new SegmentInfo data class.
        info = SegmentInfo(
            # Set the start time from the SDK region.
            start_time=seg.region.start_s,
            # Set the end time from the SDK region.
            end_time=seg.region.end_s,
            # Set the transcribed text from the ASR.
            transcribed_text=asr_text,
            # Set the matched Arabic text from the SDK.
            matched_text=seg.matched_text,
            # Set the matched Quran reference from the SDK.
            matched_ref=matched_ref,
            # Set the confidence score from the SDK.
            match_score=seg.confidence,
            # Pass along any error messages from the SDK.
            error=seg.error,
            # `has_missing_words` is calculated later via a coverage algorithm.
            # Initialize has_missing_words to False.
            has_missing_words=False,
            # Boolean flag indicating if words were repeated based on wrap ranges.
            has_repeated_words=bool(wrap_ranges),
            # Store the raw wrap ranges.
            wrap_word_ranges=wrap_ranges,
            # Store the calculated repetition ranges.
            repeated_ranges=rep_ranges,
            # Store the calculated repetition text.
            repeated_text=rep_text,
            # Store the original ID so we can later link precise word timings back to this segment.
            # Calculate a 1-based index from the 0-based segment ID.
            _original_alignment_idx=seg.id + 1,
        )
        
        # If this segment absorbed a smaller segment due to an auto-merge, stamp the details.
        # Attempt to fetch the consumed segment using the parent ID.
        consumed = auto_merged.get(seg.id)
        # Check if this segment actually consumed another.
        if consumed is not None:
            # Call the auto-merge stamper to inject the merge metadata.
            stamp_auto_merge_group(info, seg, consumed, regions)
            
        # Append the fully constructed SegmentInfo object to the final list.
        segments.append(info)

    # Return the list of structured segments.
    return segments


# Define a helper function to calculate exact repetitions.
def derive_repetition(matched_ref: str, wrap_ranges) -> tuple[list | None, list | None]:
    """
    Analyzes 'wrap ranges' (where a reciter jumps backwards) to determine exactly 
    which words were repeated.
    
    Returns a tuple of (List of Reference Ranges, List of Display Texts).
    """
    # Check if the required inputs are invalid or missing.
    if not (wrap_ranges and matched_ref and "-" in matched_ref):
        # Return Nones if no repetitions exist.
        return None, None
        
    # Dynamically import the Quran index accessor to avoid circular dependencies.
    from src.core.quran_index import get_quran_index

    # Break the matched reference into start and end points
    # Split the matched reference by the hyphen.
    ref_from, ref_to = matched_ref.split("-", 1)
    
    # Calculate the exact chronological reading sequence (e.g. read 1-5, jump back to 3, read 3-8)
    # Call the helper to determine the sequence.
    rep_ranges = compute_reading_sequence(ref_from, ref_to, wrap_ranges)
    
    # Look up the actual Arabic display text for each of those repeated sections
    # Retrieve the global Quran index instance.
    qi = get_quran_index()
    # Initialize an empty list for the translated Arabic texts.
    rep_text = []
    
    # Loop over the calculated chronological ranges.
    for sec_from, sec_to in rep_ranges:
        # Resolve the global indices for the current range.
        indices = qi.ref_to_indices(f"{sec_from}-{sec_to}")
        # Check if the indices were resolved successfully.
        if indices:
            # Unpack the start and end global indices.
            s_i, e_i = indices
            # Concatenate the display_text of all words in this repeated section
            # Extract and join the text for the matched words.
            rep_text.append(" ".join(w.display_text for w in qi.words[s_i:e_i + 1]))
        # Execute this block if indices were not resolved.
        else:
            # Append an empty string as a fallback.
            rep_text.append("")
            
    # Return the repetition ranges and their Arabic translations.
    return rep_ranges, rep_text


# ==============================================================================
# 2. Timing Extraction (Timings -> Words)
# ==============================================================================

# Define a function to map SDK Timings to our SegmentInfo objects.
def timings_to_words(timings: Timings, segment_infos: list[SegmentInfo]) -> None:
    """
    The SDK calculates word-by-word and letter-by-letter timestamps. 
    This function extracts those timings and attaches them to the `words` attribute 
    of our `SegmentInfo` objects.
    """
    # Create a quick dictionary to look up SegmentInfo by its ID.
    # Initialize an empty dictionary.
    by_id = {}
    # Iterate over our existing list of SegmentInfo objects.
    for seg in segment_infos:
        # Check if the segment retains its original ID.
        if seg._original_alignment_idx is not None:
            # Map the 0-based SDK ID back to the SegmentInfo object.
            by_id[seg._original_alignment_idx - 1] = seg

    # Iterate through every timed segment returned by the SDK.
    # Loop through the SDK's timed segments.
    for st in timings.segments:
        # Fetch the corresponding SegmentInfo object from our lookup dictionary.
        seg = by_id.get(st.segment_id)
        # Check if the segment was deleted (e.g. absorbed) or has no word timings.
        if seg is None or st.words is None:
            # Skip to the next iteration.
            continue
            
        # Initialize an empty list to store structured word timings.
        words = []
        # Loop through each individual word timing provided by the SDK.
        for w in st.words:
            # Build the core dictionary for a single word
            # Create a dictionary with location and timing data.
            entry = {"location": w.location, "start": w.start_s, "end": w.end_s}
            
            # If letter-level timings are enabled (via FastConformer emissions), attach them.
            # Check if letter timings exist for this word.
            if w.letters:
                # Add a list of letter timings to the dictionary.
                entry["letters"] = [
                    # Construct a small dictionary for each letter.
                    {"char": ch, "start": s, "end": e} for ch, s, e in w.letters
                ]
                
            # Check if line index information exists for UI rendering.
            if w.line_idx is not None:
                # Add the line index to the dictionary.
                entry["line_idx"] = w.line_idx
                
            # Append the constructed word dictionary to the list.
            words.append(entry)
            
        # Attach the fully constructed word array to the SegmentInfo object in place.
        # Mutate the SegmentInfo object directly.
        seg.words = words


# ==============================================================================
# 3. Audio Region Conversion Utilities
# ==============================================================================

# Define a function to convert SDK Regions to a raw integer state format.
def regions_to_state(regions: Regions) -> tuple[np.ndarray | None, bool | None]:
    # A docstring explaining the regions_to_state function.
    """Converts SDK Region objects into a raw integer NumPy array (samples)."""
    # Use the raw list if it exists, otherwise use the regions list.
    raw_list = regions.raw if regions.raw is not None else regions.regions
    # Check if there are no regions to process.
    if not raw_list:
        # Return None and the completion status.
        return None, regions.is_complete
        
    # Convert the seconds into integer sample indices and create a NumPy array.
    raw = np.array(
        # Multiply by SAMPLE_RATE and round to get sample indices.
        [[round(r.start_s * SAMPLE_RATE), round(r.end_s * SAMPLE_RATE)] for r in raw_list],
        # Explicitly set data type to 64-bit integer.
        dtype=np.int64,
    # Reshape the array into pairs of (start, end).
    ).reshape(-1, 2)
    # Return the raw array and completion status.
    return raw, regions.is_complete


# Define a function to convert raw integer state back to SDK Regions.
def state_to_regions(raw_state, is_complete, audio_duration_s: float | None = None) -> Regions:
    # A docstring explaining the state_to_regions function.
    """Converts a raw integer array (samples) back into float SDK Region objects."""
    # Check if the state is a PyTorch tensor (by checking for detach).
    if hasattr(raw_state, "detach"):  
        # Detach and convert to a NumPy array.
        raw_state = raw_state.detach().cpu().numpy()
    # Check if the state is a NumPy array.
    if isinstance(raw_state, np.ndarray):
        # Convert it to a standard Python list.
        raw_state = raw_state.tolist()
        
    # Reconstruct the Region objects by dividing by the sample rate.
    raw = [
        # Create a new Region object for each start/end pair.
        Region(start_s=float(s) / SAMPLE_RATE, end_s=float(e) / SAMPLE_RATE)
        for s, e in raw_state
    ]
    
    # Check if is_complete is a single-item tensor or numpy array.
    if hasattr(is_complete, "item"): 
        # Extract the boolean value safely.
        is_complete = bool(np.asarray(is_complete).all())
        
    # Construct and return a new SDK Regions object.
    return Regions(
        # Empty regions list (can be populated later).
        regions=[],
        # Set the completion status.
        is_complete=bool(is_complete) if is_complete is not None else None,
        # Set the raw list of Regions we just constructed.
        raw=raw,
        # Pass along the audio duration.
        audio_duration_s=audio_duration_s,
    )


# Define a function to simplify Regions into simple float tuples.
def intervals_from_regions(regions: Regions) -> list[tuple[float, float]]:
    # A docstring explaining the intervals_from_regions function.
    """Converts SDK Regions into a simple list of (start_seconds, end_seconds) tuples."""
    # List comprehension to extract start and end seconds.
    return [(r.start_s, r.end_s) for r in regions.regions]


# ==============================================================================
# 4. Metrics & Profiling Translation
# ==============================================================================

# Define a function to copy metrics from the SDK stages to our ProfilingData object.
def metrics_to_profiling(stages: dict, profiling: ProfilingData) -> None:
    """
    Extracts granular timing metrics from the SDK (e.g., how long sorting took, 
    how many segments passed/failed) and maps them to our application's `ProfilingData` object.
    """
    # Extract the recognition stage metrics.
    rec = _metrics(stages.get("recognition"))
    # Check if recognition metrics exist.
    if rec:
        # Copy the ASR sorting time.
        profiling.asr_sorting_time = rec.get("sorting_s", 0.0)
        # Copy the ASR batch build time.
        profiling.asr_batch_build_time = rec.get("batch_build_s", 0.0)
        # Copy the detailed batch profiling array.
        profiling.asr_batch_profiling = rec.get("batches") or []

    # Extract the matching stage metrics.
    match = _metrics(stages.get("matching"))
    # Check if matching metrics exist.
    if match:
        # Copy the retry attempts count.
        profiling.retry_attempts = match.get("retry_attempts", 0)
        # Copy the number of retries that passed.
        profiling.retry_passed = match.get("retry_passed", 0)
        # Copy the list of segments that were retried.
        profiling.retry_segments = match.get("retry_segments", [])
        # Copy the consecutive reanchor count.
        profiling.consec_reanchors = match.get("consec_reanchors", 0)
        # Copy the total number of segments attempted.
        profiling.segments_attempted = match.get("segments_attempted", 0)
        # Copy the number of segments that successfully passed DP.
        profiling.segments_passed = match.get("segments_passed", 0)
        # Copy the count of special DP merges.
        profiling.special_merges = match.get("special_merges", 0)
        # Copy the count of transition skips.
        profiling.transition_skips = match.get("transition_skips", 0)
        
        # Extract the wall time for the matching stage.
        wall = _wall_s(stages.get("matching"))
        # Check if the wall time exists.
        if wall is not None:
            # Store the wall time.
            profiling.match_wall_time = wall


# Define a function to forward matching events to a log collector.
def matching_events_to_collector(stages: dict, dc) -> None:
    # A docstring explaining the function.
    """Passes detailed debugging events from the SDK matching algorithm to the app's log collector."""
    # Check if the data collector is None (disabled).
    if dc is None:
        # Return early.
        return
    # Extract the matching stage metrics.
    match = _metrics(stages.get("matching"))
    # Loop over every event found in the metrics.
    for ev in (match or {}).get("events") or []:
        # Filter out the 'event' key to get the rest of the fields.
        fields = {k: v for k, v in ev.items() if k != "event"}
        # Add the event to the collector.
        dc.add_event(ev.get("event"), **fields)


# Define a helper function to safely fetch metrics.
def _metrics(stage) -> dict | None:
    # A docstring explaining the helper function.
    """Helper to safely extract metrics from a stage object."""
    # Check if the stage is None.
    if stage is None:
        # Return None.
        return None
    # Return stage.metrics if it exists, otherwise try to cast to a dict.
    return stage.metrics if hasattr(stage, "metrics") else dict(stage)


# Define a helper function to safely fetch wall-clock time.
def _wall_s(stage) -> float | None:
    # A docstring explaining the helper function.
    """Helper to safely extract wall-clock time from a stage object."""
    # Check if the stage is None.
    if stage is None:
        # Return None.
        return None
    # Safely get the wall_s attribute, returning None if absent.
    return getattr(stage, "wall_s", None)
