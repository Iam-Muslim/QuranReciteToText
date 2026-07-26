"""
Post-ASR Matcher & Alignment Engine.

This module executes Phase 2 of the pipeline. It takes the raw, imperfect text 
transcribed by FastConformer and aligns it mathematically against the perfect Uthmani script 
using Dynamic Programming (DP) algorithms (specifically Needleman-Wunsch).

It acts as a bridge between the ASR output and the final serialized JSON payload.
"""
# Import json for potential debugging outputs.
import json
# Import time for performance profiling and benchmarking.
import time
# Import numpy for fast matrix math during timestamp interpolation.
import numpy as np

# Import specific domain schemas from the DP SDK.
from qua_sdk.schemas import Region, Regions
# Import the parameters structure used to configure the DP engine.
from qua_sdk.components.matching.runtimes.wraparound_params import WraparoundDpParams
# Import the primary DP execution function.
from qua_sdk.components.matching.runtimes.sequencer import run_matching_sequence
# Import the N-Gram anchoring logic.
from qua_sdk.components.matching.runtimes.runtime import find_anchor_by_voting
# Import our custom Arabic normalization rules.
from src.phase2_matching.normalize import get_arabic_resources

# Import our custom SDK adapter utilities.
from src.core import sdk_adapt
# Import the final JSON serializer.
from src.core.segment_types import segments_to_json
# Import the boundary splitting post-processor.
from src.phase2_matching.split import _split_fused_segments

# Define the main orchestration function.
def _run_post_asr_pipeline(
    # The preprocessed audio float32 array (or file path).
    audio, 
    # The sample rate.
    sample_rate, 
    # A list of start/end tuple times defining chunks.
    intervals,
    # The name of the acoustic model.
    model_name, 
    # The ProfilingData instance for tracking metrics.
    profiling, 
    # The unix timestamp when the script first launched.
    pipeline_start,
    # Optional explicitly provided SDK Regions.
    regions=None,
    # Optional explicitly provided FastConformer Emissions.
    emissions=None, 
    # Optional metrics passed down from Phase 1.
    stage_metrics=None
):
    """
    Main orchestration function for Phase 2 (Text Matching & JSON Generation).

    Args:
        audio: The preprocessed float32 mono 16kHz audio array (unused here, kept for API compatibility).
        sample_rate: The sample rate (always 16000).
        intervals: List of (start_s, end_s) tuples defining each speech chunk.
        model_name: The name of the acoustic model used (usually "Base").
        profiling: The ProfilingData instance used to track execution speeds.
        pipeline_start: The Unix timestamp when the user first launched the script.
        regions: SDK Region objects containing absolute start/end times.
        emissions: The raw transcribed text tokens from FastConformer.
        stage_metrics: Metrics passed down from the FastConformer inference stage.

    Returns:
        A dictionary representing the final JSON payload containing fully aligned verses.
    """
    # Guard clause: check if the intervals array is completely empty.
    if not intervals:
        # Return an empty JSON structure if nothing was processed.
        return []

    # If regions weren't provided explicitly, construct them from the raw intervals.
    # Check if the regions argument is None.
    if regions is None:
        # Calculate the total audio duration, defaulting to 0.0 if a string path was passed.
        duration = len(audio) / sample_rate if not isinstance(audio, str) else 0.0
        # Instantiate a new Regions wrapper object.
        regions = Regions(
            # Create a list of Region objects using list comprehension.
            regions=[Region(start_s=float(s), end_s=float(e)) for s, e in intervals],
            # Pass the calculated audio duration.
            audio_duration_s=duration,
        )

    # Print a status message showing the number of VAD chunks.
    print(f"[Sliding Window] {len(intervals)} chunks")
    # Print a status message showing the number of transcribed blocks.
    print(f"[ASR] {len(emissions.tokens)} results")
    
    # Extract the raw list of tokens from the emissions object.
    transcribed_tokens = emissions.tokens
    # Extract the Phase 1 batch profiling array.
    asr_batch_profiling = profiling.asr_batch_profiling

    # Print out detailed profiling data about the ASR execution if available.
    # Check if the array contains any data.
    if asr_batch_profiling:
        # Iterate over each dictionary in the array.
        for b in asr_batch_profiling:
            # Print a highly detailed formatted string summarizing the batch's performance.
            print(f"  Batch {b['batch_num']:>2}: {b['size']:>3} segs | "
                  f"{b['time']:.3f}s | "
                  f"{b['min_dur']:.2f}-{b['max_dur']:.2f}s "
                  f"(A {b['total_seconds']/b['size']:.2f}s, T {b['total_seconds']:.1f}s, W {b['pad_waste']:.0%}, "
                  f"QK^T {b['qk_mb_per_head']:.1f} MB/head, {b['qk_mb_all_heads']:.0f} MB total)")


    # =====================================================================
    # DP MATCHING STAGE
    # =====================================================================
    # Print a status message indicating the start of the matching phase.
    print(f"[STAGE] Text Matching (Arabic Word Mode)...")

    # Record the timestamp before starting the DP execution.
    match_start = time.time()
    # Start a try block to gracefully catch DP algorithm failures.
    try:
        # Load the custom Arabic character-level matching resources (quran_index, substitution costs, etc.)
        # Call the function to retrieve the Resources object.
        resources = get_arabic_resources()
        # Instantiate the configuration parameters for the DP algorithm.
        params = WraparoundDpParams()
        
        # With proper VAD + audio preprocessing, ASR text is clean enough for
        # reliable 5-gram anchoring. Stricter anchors (5 segments long) prevent false matches
        # which can severely misalign the rest of the file.
        # Set the N-gram size parameter to 5.
        params.anchor.ngram_size = 5
        # Set the required segments parameter to 5.
        params.anchor.segments = 5
        
        # =====================================================================
        # PHASE 2.1: GLOBAL ANCHOR DETECTION (N-Gram Matching)
        # We can't run Dynamic Programming (DP) across the entire 604-page 
        # Quran index because it would take too long and consume too much RAM.
        # Instead, we use a fast N-Gram lookup to find exactly which Surah/Ayah
        # the audio starts at. This gives our DP algorithm a "start anchor".
        # =====================================================================
        # Call the voting function to determine the start location based on early transcriptions.
        start_surah, start_ayah = find_anchor_by_voting(transcribed_tokens, resources.ngram_index, params.anchor)
        
        # Guard clause: check if the anchoring completely failed.
        if start_surah <= 0:
            # Raise a fatal error indicating the audio couldn't be located in the Quran.
            raise ValueError("Could not anchor to any chapter — no n-gram matches found")
            
        # Print a success message showing the determined start location.
        print(f"[ANCHOR] Anchored to Surah {start_surah}:{start_ayah}")
        
        # We need the 0-indexed absolute word pointer for the start_ayah.
        # We iterate through the chapter's words to find exactly where this Ayah begins.
        # Retrieve the ChapterReference object for the anchored Surah.
        chapter_ref = resources.chapter_refs[start_surah]
        # Initialize the pointer variable.
        start_pointer = 0
        # Iterate over all words in the chapter using enumerate.
        for i, w in enumerate(chapter_ref.words):
            # Check if we've reached the anchored Ayah.
            if w.ayah == start_ayah:
                # Store the absolute integer index.
                start_pointer = i
                # Break the loop early for efficiency.
                break

        # =====================================================================
        # PHASE 2.2: SEQUENTIAL DYNAMIC PROGRAMMING (DP) ALIGNMENT
        # Now that we know where the recitation starts (start_pointer), we run 
        # a continuous Sequence Alignment algorithm (Needleman-Wunsch).
        # It maps the raw ASR text output to the perfect Quran script, natively handling
        # skipped words, repeated words (repetitions), and pauses.
        # =====================================================================
        # Invoke the core DP matching sequence function.
        sdk_result = run_matching_sequence(
            # Pass the list of raw text tokens to align.
            phoneme_texts=transcribed_tokens,
            # Pass the starting Surah.
            start_surah=start_surah,
            # Start at index 0 of the provided texts.
            first_quran_idx=0,
            # Empty list as no special forced results are used here.
            special_results=[],
            # Pass the absolute integer start pointer.
            start_pointer=start_pointer,
            # Pass the tuning parameters.
            params=params,
            # Pass the loaded substitution costs and indexes.
            resources=resources,
            # No callback is used for events currently.
            on_event=None,
        )
        
    # Catch any general exceptions thrown during the DP process.
    except Exception as e:
        # Gracefully surface anchoring errors to the user (e.g. if the audio isn't Quran).
        # Check if a custom user-facing message was attached to the exception.
        user_message = getattr(e, "user_message", None)
        # If it exists.
        if user_message:
            # Reraise as a ValueError with the clean message.
            raise ValueError(user_message) from e
        # If no clean message exists, just reraise the original error.
        raise
        
    # Calculate the total wall-clock time spent inside the DP engine.
    match_time = time.time() - match_start
    # Save the time to the ProfilingData instance.
    profiling.match_wall_time = match_time
    # Print a status message summarizing the DP results.
    print(f"[MATCH] {len(sdk_result.results)} alignments in {match_time:.2f}s")

    # Add the internal DP metrics (e.g., transition skips, retry attempts) to our global tracker.
    # Call the adapter function to migrate the SDK's metrics object over.
    sdk_adapt.metrics_to_profiling({"matching": sdk_result.metrics}, profiling)

    # =====================================================================
    # RESULTS BUILDING STAGE
    # =====================================================================
    # Print a status message indicating result assembly has begun.
    print(f"[STAGE] Building results...")

    # Initialize an empty list to hold the finalized SegmentInfo objects.
    segments = []
    # Import the SegmentInfo class.
    from src.core.segment_types import SegmentInfo
    # Import the FastConformer singleton (though not used directly in this block).
    from src.phase1_transcribe.fastconformer import FastConformerONNX
    
    # Retrieve the raw word-level timestamps generated during Phase 1 ASR.
    # Extract the timing array from the metrics dictionary, defaulting to empty.
    asr_words_entries = stage_metrics.get("asr_words", [])
    
    # Import the reading sequence computer.
    from src.core.segment_types import compute_reading_sequence

    # Singletons for Quran lookups
    # Initialize the Quran index to None.
    q_index = None
    # Initialize the lookup dictionary to None.
    ref_to_idx = None

    # Define an internal function for lazy-loading.
    def _ensure_q_index():
        # A docstring explaining the lazy-loading concept.
        """Lazy-loads the Quran Index to prevent unnecessary overhead if it's not needed."""
        # Use nonlocal to modify the variables defined in the outer scope.
        nonlocal q_index, ref_to_idx
        # Check if it hasn't been loaded yet.
        if q_index is None:
            # Import the provider.
            from src.core.quran_index import get_quran_index
            # Call the provider.
            q_index = get_quran_index()
            # Build a fast mapping from reference string (Surah:Ayah:Word) to the integer index
            # Construct the dictionary using a comprehension.
            ref_to_idx = {f"{w.surah}:{w.ayah}:{w.word}": idx for idx, w in enumerate(q_index.words)}

    # Define an internal function for sub-word alignment.
    def align_words_dp(asr_words, true_text, chunk_origin):
        """
        DP Timestamp Interpolation. 
        
        The DP matcher (run_matching_sequence) aligns text, but it does NOT align timestamps.
        FastConformer spits out timestamps for the raw ASR text, which might contain errors or missing words.
        
        This inner function runs a localized Needleman-Wunsch algorithm between the 
        raw ASR words and the true Uthmani words, mapping the FastConformer timestamps 
        onto the perfect Uthmani script so that every correct word has an exact timestamp.
        """
        # Split the perfect Uthmani text string into a list of words.
        true_words = true_text.split()
        # Guard clause: check if the text is empty.
        if not true_words:
            # Return an empty list.
            return []
            
        # Build the DP Matrix
        # Define dimensions n (ASR words) and m (True words).
        n, m = len(asr_words), len(true_words)
        # Initialize an (n+1) by (m+1) numpy array with zeros.
        dp = np.zeros((n + 1, m + 1), dtype=float)
        
        # Initialize penalties
        # Loop over rows.
        for i in range(1, n + 1):
            # Apply a linear deletion penalty.
            dp[i][0] = dp[i-1][0] - 1  # Deletion penalty
        # Loop over columns.
        for j in range(1, m + 1):
            # Apply a linear insertion penalty.
            dp[0][j] = dp[0][j-1] - 1  # Insertion penalty
            
        # Fill the matrix
        # Iterate over all rows (ASR words).
        for i in range(1, n + 1):
            # Iterate over all columns (True words).
            for j in range(1, m + 1):
                # Extract the text of the current ASR word.
                w_asr = asr_words[i-1]["word"]
                # Extract the text of the current True word.
                w_true = true_words[j-1]
                
                # Import the normalizer locally.
                from src.phase2_matching.normalize import normalize_arabic
                # If the normalized ASR word matches the normalized Uthmani word perfectly, 
                # assign a high positive score (+1.0). Otherwise, assign a negative penalty (-1.0).
                # Compare the normalized forms of both words.
                if normalize_arabic(w_asr) == normalize_arabic(w_true):
                    # Set the match score to a positive 1.0.
                    match_score = 1.0
                # Execute if the strings don't match.
                else:
                    # Set the match score to a negative 1.0 penalty.
                    match_score = -1.0
                    
                # The DP algorithm decides the best path (Match vs Insert vs Delete)
                # Calculate the maximum possible score for the current cell using dynamic programming.
                dp[i][j] = max(
                    # Diagonal move: Score from aligning the two words.
                    dp[i-1][j-1] + match_score,
                    # Vertical move: Penalty for deleting an ASR word.
                    dp[i-1][j] - 1,
                    # Horizontal move: Penalty for inserting a True word.
                    dp[i][j-1] - 1
                )
                
        # Backtrack through the matrix to find the optimal alignment path
        # Start at the bottom-right corner of the matrix.
        i, j = n, m
        # Initialize an empty list to store the optimal sequence of moves.
        alignment = []
        # Loop until we reach the top-left corner.
        while i > 0 and j > 0:
            # Re-extract the ASR word for the current cell.
            w_asr = asr_words[i-1]["word"]
            # Re-extract the True word for the current cell.
            w_true = true_words[j-1]
            # Import normalizer locally again.
            from src.phase2_matching.normalize import normalize_arabic
            # Recalculate the match score used for this cell.
            match_score = 1.0 if normalize_arabic(w_asr) == normalize_arabic(w_true) else -1.0
            
            # Check if this cell's score came from a diagonal move (a match/substitution).
            if dp[i][j] == dp[i-1][j-1] + match_score:
                # Add the coordinate pair to the alignment path.
                alignment.append((i-1, j-1))
                # Move diagonally up-left.
                i -= 1
                j -= 1
            # Check if the score came from a vertical move (deletion).
            elif dp[i][j] == dp[i-1][j] - 1:
                # Move straight up.
                i -= 1
            # Otherwise, the score came from a horizontal move (insertion).
            else:
                # Move straight left.
                j -= 1
        
        # Convert the alignment path into a direct mapping (true_idx -> asr_idx)
        # Reverse the path and build a dictionary mapping the canonical word index to the ASR word index.
        aligned_map = {true_idx: asr_idx for asr_idx, true_idx in reversed(alignment)}
        
        # Initialize the final list of words.
        result_words = []
        # Initialize a tracker for the end time of the previous word.
        last_end = chunk_origin
        
        # Iterate through the true Uthmani words and stamp them with their matched ASR timestamps.
        # We use a gap-proportional strategy for missing words: instead of guessing a flat 100ms 
        # for every dropped word, we look ahead to the next matched word's start time and 
        # distribute the entire available gap evenly across all consecutive missing words.
        # This produces much better alignment when the ASR skips multiple words in a row.
        j = 0
        # Loop until every canonical word has been assigned a timestamp.
        while j < len(true_words):
            # Case 1: This word was matched by the ASR model — use its real timestamp directly.
            if j in aligned_map:
                # Retrieve the matched ASR word index.
                asr_idx = aligned_map[j]
                # The ASR timestamps are already in absolute audio seconds.
                start = asr_words[asr_idx]["start"]
                # End time is already absolute.
                end = asr_words[asr_idx]["end"]
                # Update the "cursor" to this word's end for the next gap calculation.
                last_end = end
                # Append the matched word entry.
                result_words.append({
                    # Store the canonical Uthmani text.
                    "word": true_words[j],
                    # Store the matched start time.
                    "start": start,
                    # Store the matched end time.
                    "end": end
                })
                # Advance to the next word.
                j += 1
            # Case 2: One or more consecutive words were missed by the ASR model.
            else:
                # Collect the full contiguous run of missing words so we can distribute
                # the time gap proportionally across all of them at once.
                # Mark where the gap starts.
                gap_start = j
                # Scan forward until we either hit a matched word or reach the end.
                while j < len(true_words) and j not in aligned_map:
                    j += 1
                # Number of consecutive words that were missed.
                count = j - gap_start
                
                # Find the anchor time that marks the end of this gap.
                # If there is a matched word after the gap, use its start time as the ceiling.
                if j < len(true_words) and j in aligned_map:
                    # Look up the next matched ASR word's start time.
                    next_anchor = asr_words[aligned_map[j]]["start"]
                else:
                    # Fallback: no more matched words exist, so use a small fixed slot.
                    next_anchor = last_end + count * 0.1
                    
                # Calculate the total time available to distribute across all missing words.
                # Clamp to 0.0 in case of minor floating-point errors.
                available = max(0.0, next_anchor - last_end)
                # Each missing word gets an equal time slot within the gap.
                slot = available / count if count > 0 else 0.0
                
                # Assign a proportional timestamp to each missing word in this run.
                for k in range(count):
                    # Calculate start time for the k-th missing word.
                    w_start = last_end + k * slot
                    # Calculate end time for the k-th missing word.
                    w_end = last_end + (k + 1) * slot
                    # Append the interpolated word entry.
                    result_words.append({
                        # Store the canonical Uthmani text.
                        "word": true_words[gap_start + k],
                        # Store the proportionally-interpolated start time.
                        "start": w_start,
                        # Store the proportionally-interpolated end time.
                        "end": w_end
                    })
                # Advance the cursor to the end of the last missing word's slot.
                last_end = last_end + count * slot
            
        # Return the final array of words with precise timestamps.
        return result_words

    # =====================================================================
    # SEGMENT PACKAGING
    # =====================================================================
    # Iterate through all the perfectly matched results from the SDK.
    # Loop over the alignment blocks returned by the DP engine.
    for i, res in enumerate(sdk_result.results):
        # Unpack the 4-tuple returned by the SDK.
        matched_text, score, matched_ref, wrap_ranges = res
        # Extract the original audio segment start time.
        seg_start = regions.regions[i].start_s
        # Extract the original audio segment end time.
        seg_end = regions.regions[i].end_s
        # Reconstruct the raw ASR string for debugging.
        transcribed_text = " ".join(transcribed_tokens[i])
        
        # For repetition segments, we must carefully rebuild the matched_text 
        # from the quran index to reflect the chronological reading sequence.
        # Check if wrap ranges exist and if the reference is standard.
        if wrap_ranges and matched_ref and ":" in matched_ref:
            # Ensure the global Quran index is loaded into memory.
            _ensure_q_index()
            # Split the hyphenated bounds string.
            parts = matched_ref.split("-")
            # Extract the starting bound.
            ref_from = parts[0]
            # Extract the ending bound.
            ref_to = parts[1] if len(parts) > 1 else parts[0]
            
            # Compute the chronological reading order array.
            sections = compute_reading_sequence(ref_from, ref_to, wrap_ranges)
            # Initialize an empty list for the text strings.
            recited_words = []
            
            # Iterate through each computed section.
            for sec in sections:
                # Unpack the section bounds.
                s_ref, e_ref = sec
                # Verify bounds exist in the fast lookup dictionary.
                if s_ref in ref_to_idx and e_ref in ref_to_idx:
                    # Iterate through the mathematical indices.
                    for w_i in range(ref_to_idx[s_ref], ref_to_idx[e_ref] + 1):
                        # Append the actual canonical string text.
                        recited_words.append(q_index.words[w_i].text)
                        
            # If the extraction was successful.
            if recited_words:
                # Overwrite the matched_text with the chronologically correct string.
                matched_text = " ".join(recited_words)
        
        # Finalize timestamps
        # Initialize the words attribute to None.
        words = None
        # Check if the block actually matched anything successfully.
        if score > 0 and i < len(asr_words_entries) and matched_text:
            # Retrieve the raw ASR word timings for this chunk.
            asr_entry = asr_words_entries[i]
            # Check if the entry is a tuple containing the chunk origin offset.
            if isinstance(asr_entry, tuple):
                # Unpack the tuple.
                asr_words, chunk_origin = asr_entry
            # Execute if it's just the raw array.
            else:
                # Fallback to unpacking it directly and assuming the chunk origin is seg_start.
                asr_words, chunk_origin = asr_entry, seg_start

            # Invoke the DP interpolation function defined above.
            words = align_words_dp(asr_words, matched_text, chunk_origin)
            
            # Stamp Quran location refs onto each word.
            # E.g., attaching "2:255:1" to the first word object.
            # Check if words exist and the reference is standard.
            if matched_ref and ":" in matched_ref and words:
                # Ensure the global Quran index is loaded into memory.
                _ensure_q_index()
                # Split the hyphenated bounds string.
                parts = matched_ref.split("-")
                # Extract the starting bound.
                r_from = parts[0]
                # Extract the ending bound.
                r_to = parts[1] if len(parts) > 1 else parts[0]
                # Compute the chronological reading order array.
                sections = compute_reading_sequence(r_from, r_to, wrap_ranges or [])
                
                # Initialize a flat list for the reference strings.
                loc_refs = []
                # Iterate through each computed section.
                for sec in sections:
                    # Unpack the section bounds.
                    s_ref, e_ref = sec
                    # Verify bounds exist in the fast lookup dictionary.
                    if s_ref in ref_to_idx and e_ref in ref_to_idx:
                        # Iterate through the mathematical indices.
                        for w_i in range(ref_to_idx[s_ref], ref_to_idx[e_ref] + 1):
                            # Retrieve the QuranWord object.
                            qw = q_index.words[w_i]
                            # Construct and append the reference string.
                            loc_refs.append(f"{qw.surah}:{qw.ayah}:{qw.word}")
                            
                # Loop through the previously interpolated word objects.
                for j, w in enumerate(words):
                    # Safety check to avoid index out of bounds.
                    if j < len(loc_refs):
                        # Inject the location string into the dictionary.
                        w['location'] = loc_refs[j]
        
        # Build the final SegmentInfo data class.
        # Instantiate and append to the main segments list.
        segments.append(SegmentInfo(
            # Pass the start time.
            start_time=seg_start,
            # Pass the end time.
            end_time=seg_end,
            # Pass the raw ASR text.
            transcribed_text=transcribed_text,
            # Pass the perfect Uthmani text.
            matched_text=matched_text,
            # Pass the hyphenated bounds string.
            matched_ref=matched_ref,
            # Pass the DP confidence score.
            match_score=score,
            # Pass the repetition tuples.
            wrap_word_ranges=wrap_ranges,
            # A complex ternary logic to generate human-readable error strings.
            error=f"Low confidence ({score:.0%})" if score < 0.2 and score > 0 else ("Failed" if score == 0 else None),
            # Check if this segment was marked as having missing words.
            has_missing_words=(i in sdk_result.gap_segments),
            # Check if this segment was marked as containing repetitions.
            has_repeated_words=(i in sdk_result.repetition_segments),
            # Pass the final fully-stamped array of word dictionaries.
            words=words,
        ))
        
    # Record the timestamp before post-processing starts.
    result_build_start = time.time()
    # Initialize the encoding time variable (legacy/placeholder).
    audio_encode_time = 0.0

    # Post-processing: split combined/fused segments via sequence boundaries
    # E.g., if a 30s chunk contains 3 Ayahs, split it into 3 segments.
    # Call the external splitting function.
    segments = _split_fused_segments(segments, None, sample_rate)

    # Clean up segment boundaries.
    # Prevent segment 2 from 'starting' before segment 1 'ends', which happens 
    # due to minor floating point rounding errors in the DP interpolation.
    # Loop over all segments except the very last one.
    for i in range(len(segments) - 1):
        # Check if an overlap exists.
        if segments[i].end_time > segments[i + 1].start_time:
            # Snap the end time of the current segment to the start of the next.
            segments[i].end_time = segments[i + 1].start_time

    # =====================================================================
    # FINAL METRICS & SUMMARY
    # =====================================================================
    # Initialize a list to hold word counts for each segment.
    _seg_word_counts = []
    # Initialize a list to hold durations for each segment.
    _seg_durations = []
    # Initialize a list to hold character counts for each segment.
    _seg_char_counts = []
    # Initialize a list to hold Ayah span metadata for each segment.
    _seg_ayah_spans = []
    
    # Iterate through every final segment.
    for i, seg in enumerate(segments):
        # Calculate the mathematical duration in seconds.
        duration = seg.end_time - seg.start_time
        # Calculate the number of words by splitting the reference string (rough estimate).
        word_count = len(seg.matched_ref.split()) if seg.matched_ref else 0
        # Placeholder for Ayah spans.
        ayah_span = ""
        # Append word count.
        _seg_word_counts.append(word_count)
        # Append duration.
        _seg_durations.append(duration)
        # Append character count (unused currently, set to 0).
        _seg_char_counts.append(0)
        # Append Ayah span.
        _seg_ayah_spans.append(ayah_span)

    # Update profiling data with total generated segments.
    profiling.segments_attempted = len(segments)
    # Update profiling data with total successful segments.
    profiling.segments_passed = sum(1 for s in segments if s.match_score > 0.0)

    # Calculate time taken for result assembly.
    result_build_total_time = time.time() - result_build_start
    # Save the time to profiling.
    profiling.result_build_time = result_build_total_time
    # Save encoding time to profiling.
    profiling.result_audio_encode_time = audio_encode_time

    # Print profiling summary to the terminal.
    # Calculate the grand total wall-clock time from start to finish.
    profiling.total_time = time.time() - pipeline_start
    # Print the formatted text block to the terminal.
    print(profiling.summary())

    # Segment distribution stats
    # Filter the arrays to only include successful (non-zero word) segments.
    matched_words = [w for w in _seg_word_counts if w > 0]
    # Filter the durations similarly.
    matched_durs = [d for i, d in enumerate(_seg_durations) if _seg_word_counts[i] > 0]
    # Filter the character counts similarly.
    matched_chars = [p for i, p in enumerate(_seg_char_counts) if _seg_word_counts[i] > 0]
    # Calculate the silent pause time between consecutive chunks.
    pauses = [intervals[i + 1][0] - intervals[i][1]
              for i in range(len(intervals) - 1)]
    # Remove negative or zero pauses.
    pauses = [p for p in pauses if p > 0]
    
    # Check if any matches occurred at all.
    if matched_words:
        # Define a quick helper function to calculate standard deviation.
        def _std(vals):
            # A docstring explaining the helper.
            # Get the number of elements.
            n = len(vals)
            # Cannot compute standard deviation on < 2 elements.
            if n < 2:
                # Return 0.
                return 0.0
            # Calculate the mean (average).
            mean = sum(vals) / n
            # Return the square root of the variance.
            return (sum((v - mean) ** 2 for v in vals) / n) ** 0.5

        # Calculate average words per segment.
        avg_w = sum(matched_words) / len(matched_words)
        # Calculate standard deviation of words per segment.
        std_w = _std(matched_words)
        # Determine minimum and maximum words per segment.
        min_w, max_w = min(matched_words), max(matched_words)
        # Calculate average duration per segment.
        avg_d = sum(matched_durs) / len(matched_durs)
        # Calculate standard deviation of duration per segment.
        std_d = _std(matched_durs)
        # Determine minimum and maximum duration per segment.
        min_d, max_d = min(matched_durs), max(matched_durs)
        
        # Calculate the sum total of all speech durations.
        total_speech_sec = sum(matched_durs)
        # Calculate the grand total of words recited.
        total_words = sum(matched_words)
        # Calculate the grand total of characters recited.
        total_chars = sum(matched_chars)
        
        # Calculate the pacing: Words Per Minute.
        wpm = total_words / (total_speech_sec / 60) if total_speech_sec > 0 else 0
        # Calculate the pacing: Characters Per Second.
        cps = total_chars / total_speech_sec if total_speech_sec > 0 else 0
        
        # Print a header for the statistics block.
        print(f"\n[SEGMENT STATS] {len(segments)} total segments, {len(matched_words)} matched")
        # Print the word statistics.
        print(f"  Words/segment : min={min_w}, max={max_w}, avg={avg_w:.1f}\u00b1{std_w:.1f}")
        # Print the duration statistics.
        print(f"  Duration (s)  : min={min_d:.1f}, max={max_d:.1f}, avg={avg_d:.1f}\u00b1{std_d:.1f}")
        # Check if pauses existed.
        if pauses:
            # Calculate average pause length.
            avg_p = sum(pauses) / len(pauses)
            # Calculate standard deviation of pauses.
            std_p = _std(pauses)
            # Print the pause statistics.
            print(f"  Pause (s)     : min={min(pauses):.1f}, max={max(pauses):.1f}, avg={avg_p:.1f}\u00b1{std_p:.1f}")
        # Print the pacing statistics.
        print(f"  Speech pace   : {wpm:.1f} words/min, {cps:.1f} chars/sec (speech time only)")

    # Stamp segment_number onto all finalized segments sequentially (1, 2, 3...)
    # Iterate over the final segments array.
    for i, seg in enumerate(segments):
        # Assign a 1-based index.
        seg.segment_number = i + 1

    # Serialize the list of objects into the final JSON payload dict.
    # Call the utility function.
    json_output = segments_to_json(segments, include_words=True)
    
    # Return the massive JSON dictionary back to the caller (run.py).
    return json_output
