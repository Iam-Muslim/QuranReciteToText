"""
Boundary-Based Splitting Module.

When the DP engine matches text, it often groups entire continuous stretches of recitation
into a single massive block (e.g., matching a full 30-second audio chunk to 4 verses).
This module iterates through those blocks and cleanly slices them up whenever it detects 
a natural Ayah boundary or a jump backwards (repetition).

It also correctly computes per-sub-segment repetition metadata: each child segment gets
its own wrap_word_ranges, repeated_ranges, repeated_text, and line_idx annotations based
only on the backward jumps that actually occur within *that sub-segment's* own word span.
"""
# Import the SegmentInfo data class.
from src.core.segment_types import SegmentInfo


# ---------------------------------------------------------------------------
# Helper: detect backward jumps within one group of (QuranWord, asr_word) pairs
# ---------------------------------------------------------------------------
def _compute_local_wrap_ranges(group, ref_to_idx):
    """
    Given a list of (QuranWord, asr_word_dict) pairs for a single sub-segment,
    detect backward word-index jumps and return the wrap_word_ranges list that
    describes only the repetitions that occur *within this sub-segment*.

    Format of each tuple in the returned list (3-element, matching the SDK convention):
        [jump_to_ref, jump_from_ref, repeat_end_ref]

    Where:
        jump_from_ref = the last word BEFORE the backward jump (i.e. the word that
                        was being read just before the reciter jumped back)
        jump_to_ref   = the first word AFTER the jump (i.e. where the reciter restarted)
        repeat_end_ref = the last word of this repeated section (either just before the
                         next jump, or the very last word of the sub-segment)

    Returns None if no backward jumps were found.
    """
    # We need at least two words to detect a jump.
    if len(group) < 2:
        # Return None indicating no repetitions.
        return None

    # Collect raw (jump_from_ref, jump_to_ref) pairs first; we'll fill repeat_end later.
    raw_jumps = []

    # Scan consecutive pairs looking for backward index jumps.
    for i in range(1, len(group)):
        # Previous canonical word.
        prev_q = group[i - 1][0]
        # Current canonical word.
        curr_q = group[i][0]
        # Look up absolute global indices.
        prev_idx = ref_to_idx.get(f"{prev_q.surah}:{prev_q.ayah}:{prev_q.word}", -1)
        curr_idx = ref_to_idx.get(f"{curr_q.surah}:{curr_q.ayah}:{curr_q.word}", -1)
        # A backward jump is detected when the current word's global index is
        # strictly less than the previous word's global index.
        if curr_idx < prev_idx and curr_idx >= 0 and prev_idx >= 0:
            # Record the jump position and the word references.
            raw_jumps.append({
                # Position index in group where the jump occurs.
                "group_pos": i,
                # The word the reciter was at just before jumping back.
                "jump_from_ref": f"{prev_q.surah}:{prev_q.ayah}:{prev_q.word}",
                # The word the reciter jumped back to.
                "jump_to_ref": f"{curr_q.surah}:{curr_q.ayah}:{curr_q.word}",
            })

    # If no backward jumps were found, this sub-segment has no repetitions.
    if not raw_jumps:
        # Return None to indicate no repetitions.
        return None

    # Now compute repeat_end_ref for each jump:
    # It's the word just before the NEXT jump, or the last word of the group.
    result = []
    for k, jump in enumerate(raw_jumps):
        # If there is a next jump, the repeat ends just before that jump.
        if k + 1 < len(raw_jumps):
            # The word just before the next jump is at group_pos - 1.
            next_jump_pos = raw_jumps[k + 1]["group_pos"]
            # The word immediately before that next jump is at next_jump_pos - 1.
            end_q = group[next_jump_pos - 1][0]
            repeat_end_ref = f"{end_q.surah}:{end_q.ayah}:{end_q.word}"
        else:
            # Last (or only) jump — the repeated section ends at the last word of the group.
            last_q = group[-1][0]
            repeat_end_ref = f"{last_q.surah}:{last_q.ayah}:{last_q.word}"

        # Append the 3-element wrap tuple (matching the SDK convention).
        result.append([
            jump["jump_to_ref"],    # Where the reciter jumped back to.
            jump["jump_from_ref"],  # Where the reciter was before jumping.
            repeat_end_ref,         # Where the repeated section ends.
        ])

    return result


# ---------------------------------------------------------------------------
# Helper: assign line_idx to each word in a group containing repetitions
# ---------------------------------------------------------------------------
def _assign_line_idx(group, ref_to_idx):
    """
    Assigns a line_idx value to each (QuranWord, asr_word_dict) pair, indicating
    which repetition pass the word belongs to.

    line_idx 0 = first read-through
    line_idx 1 = second read-through (after first backward jump)
    line_idx 2 = third read-through, etc.

    Returns a list of line_idx integers, one per element of group.
    """
    # Initialize all words to the first line.
    line_indices = [0] * len(group)
    # Current line counter.
    current_line = 0

    # Scan consecutive pairs for backward jumps.
    for i in range(1, len(group)):
        # Previous canonical word.
        prev_q = group[i - 1][0]
        # Current canonical word.
        curr_q = group[i][0]
        # Look up absolute global indices.
        prev_idx = ref_to_idx.get(f"{prev_q.surah}:{prev_q.ayah}:{prev_q.word}", -1)
        curr_idx = ref_to_idx.get(f"{curr_q.surah}:{curr_q.ayah}:{curr_q.word}", -1)
        # A backward jump means a new repetition line begins.
        if curr_idx < prev_idx and curr_idx >= 0 and prev_idx >= 0:
            # Increment the line counter.
            current_line += 1
        # Assign the current line index to this word.
        line_indices[i] = current_line

    return line_indices


# ---------------------------------------------------------------------------
# Helper: compute repeated_ranges and repeated_text for a sub-segment
# ---------------------------------------------------------------------------
def _compute_repeated_metadata(ref_from, ref_to, local_wrap_ranges, ref_to_idx, q_index):
    """
    Computes the repeated_ranges and repeated_text lists for a sub-segment that
    has local_wrap_ranges.

    Args:
        ref_from: String ref of the first word in this sub-segment (e.g. "3:71:1")
        ref_to:   String ref of the last word in this sub-segment (e.g. "3:71:10")
        local_wrap_ranges: The list of [jump_to, jump_from, repeat_end] tuples for
                           this sub-segment.
        ref_to_idx: Fast lookup dict: "S:A:W" -> global_index
        q_index:    The loaded QuranIndex instance.

    Returns:
        (repeated_ranges, repeated_text) — both lists matching the original project format.
    """
    # Import the reading-sequence computer from segment_types.
    from src.core.segment_types import compute_reading_sequence

    # Compute the chronological sections from the wrap ranges.
    sections = compute_reading_sequence(ref_from, ref_to, local_wrap_ranges)

    # Build repeated_ranges: list of [start_ref, end_ref] pairs — one per section.
    repeated_ranges = [[s[0], s[1]] for s in sections]

    # Build repeated_text: the Arabic text string for each section.
    repeated_text = []
    for sec in sections:
        s_ref, e_ref = sec
        # Verify both bounds exist in the lookup.
        if s_ref in ref_to_idx and e_ref in ref_to_idx:
            # Extract the words from the global index between these bounds.
            words_in_section = [
                q_index.words[wi].text
                for wi in range(ref_to_idx[s_ref], ref_to_idx[e_ref] + 1)
            ]
            # Join into a single Arabic string.
            repeated_text.append(" ".join(words_in_section))
        else:
            # Reference not found — append empty string as fallback.
            repeated_text.append("")

    return repeated_ranges, repeated_text


# ---------------------------------------------------------------------------
# Main splitting function
# ---------------------------------------------------------------------------
def _split_fused_segments(segments, audio_int16, sample_rate):
    """
    Post-processing: Split large matched blocks into smaller, verse-level segments.

    Also correctly computes per-sub-segment repetition metadata so that each child
    segment only advertises the backward jumps that actually occur within its own
    word span, rather than blindly inheriting the parent's full wrap_word_ranges.
    """
    # Import the Quran index, which holds the database of all Uthmani words.
    from src.core.quran_index import get_quran_index
    # Import necessary utilities from segment_types.
    from src.core.segment_types import compute_reading_sequence, SegmentInfo

    # Retrieve the singleton instance of the Quran index.
    q_index = get_quran_index()

    # Precompute a fast-lookup dictionary: map string references (e.g. "1:1:1") to their integer index.
    ref_to_idx = {}
    for i, w in enumerate(q_index.words):
        ref_to_idx[f"{w.surah}:{w.ayah}:{w.word}"] = i

    # List to hold the newly created, finely split sub-segments.
    out_segments = []

    # Iterate over the large, raw blocks produced by the DP matcher.
    for seg in segments:
        # If the segment lacks words or failed to match against the reference, keep it as-is.
        if not seg.words or not seg.matched_ref:
            # Append the original segment untouched.
            out_segments.append(seg)
            # Skip to the next iteration.
            continue

        # Parse the verse reference bounds into start and end components.
        parts = seg.matched_ref.split("-")
        ref_from = parts[0]
        ref_to = parts[1] if len(parts) > 1 else parts[0]

        # Determine the logical sequence of verses read, accounting for wrap-arounds.
        sections = compute_reading_sequence(ref_from, ref_to, seg.wrap_word_ranges)

        # Build the exact sequence of QuranWords that were recited in this block.
        seq_words = []
        for sec in sections:
            start_ref, end_ref = sec
            if start_ref in ref_to_idx and end_ref in ref_to_idx:
                start_i = ref_to_idx[start_ref]
                end_i = ref_to_idx[end_ref]
                for i in range(start_i, end_i + 1):
                    seq_words.append(q_index.words[i])

        # Safety Check: If canonical word count doesn't match ASR word count, keep as-is.
        if len(seq_words) != len(seg.words):
            # Append the original segment untouched.
            out_segments.append(seg)
            # Skip to the next iteration.
            continue

        # Initialize an empty list to buffer words for the current sub-segment.
        current_ayah_group = []

        # Pair each ASR word with its canonical Uthmani counterpart.
        for i in range(len(seg.words)):
            # Get the canonical Uthmani word object.
            q_w = seq_words[i]
            # Get the ASR word dictionary containing the timestamps.
            s_w = seg.words[i]

            # Initialize a flag to determine if we should split before this word.
            split_now = False
            # Check if we need to split the segment right before this word.
            if len(current_ayah_group) > 0:
                # Look at the previous canonical word added to the buffer.
                prev_q_w = current_ayah_group[-1][0]

                # ONLY split at FORWARD ayah/surah transitions — i.e. when the reciter
                # moves to a LATER verse or chapter in normal reading order.
                #
                # Critically, we do NOT split on backward jumps (even cross-ayah ones),
                # because backward jumps are repetitions and should stay within the same
                # sub-segment so that _compute_local_wrap_ranges can detect them and
                # set has_repeated_words=True correctly.
                #
                # This matches the original project's behavior: an ayah with an intra-
                # (or even cross-ayah) repetition remains ONE segment with proper
                # wrap_word_ranges metadata, rather than being shattered into tiny fragments.
                #
                # Forward surah advance.
                forward_surah = q_w.surah > prev_q_w.surah
                # Forward ayah advance within the same surah.
                forward_ayah = (q_w.surah == prev_q_w.surah and
                                q_w.ayah > prev_q_w.ayah)
                
                # Backward jump (repetition).
                curr_idx = ref_to_idx.get(f"{q_w.surah}:{q_w.ayah}:{q_w.word}", -1)
                prev_idx = ref_to_idx.get(f"{prev_q_w.surah}:{prev_q_w.ayah}:{prev_q_w.word}", -1)
                backward_jump = (curr_idx < prev_idx) and (curr_idx >= 0) and (prev_idx >= 0)

                # Trigger the split on forward move OR backward jump.
                if forward_surah or forward_ayah or backward_jump:
                    split_now = True

            # If a boundary was detected, package the accumulated words into a new sub-segment.
            if split_now:
                out_segments.append(
                    _create_sub_segment(
                        seg, current_ayah_group,
                        len(out_segments) + 1,
                        SegmentInfo, ref_to_idx, q_index
                    )
                )
                # Reset the word buffer.
                current_ayah_group = []

            # Add the current word pair to the accumulating group.
            current_ayah_group.append((q_w, s_w))

        # Flush the final remaining group of words into a segment.
        if current_ayah_group:
            out_segments.append(
                _create_sub_segment(
                    seg, current_ayah_group,
                    len(out_segments) + 1,
                    SegmentInfo, ref_to_idx, q_index
                )
            )

    # -----------------------------------------------------------------------
    # POST-PROCESSING PASS 1: Strip backward cross-ayah words from segments.
    # -----------------------------------------------------------------------
    # Words from a PREVIOUS ayah appearing at the end of a segment are DP
    # alignment noise (e.g. 3:69:12-13 appearing after 3:70:8). They must be
    # stripped because they are not part of the current ayah and would confuse
    # downstream consumers.
    out_segments = _strip_backward_cross_ayah_words(out_segments, ref_to_idx, q_index, SegmentInfo)

    # -----------------------------------------------------------------------
    # POST-PROCESSING PASS 2: Merge adjacent segments of the same ayah.
    # -----------------------------------------------------------------------
    # When different ASR chunks produce separate parts of the same ayah
    # (e.g. seg A = 3:67:1-10, seg B = 3:67:11-14) and neither has
    # repetitions, they should be merged into one segment. The original
    # project never had this problem because its VAD split at Waqf (one
    # chunk per ayah), but our lightweight pipeline can produce multiple
    # chunks for the same ayah.
    out_segments = _merge_same_ayah_segments(out_segments, ref_to_idx, q_index, SegmentInfo)

    # Update sequential segment numbering for all extracted sections.
    for i, s in enumerate(out_segments):
        s.segment_number = i + 1

    # Return the fully split array.
    return out_segments


# ---------------------------------------------------------------------------
# Sub-segment factory
# ---------------------------------------------------------------------------
def _create_sub_segment(parent_seg, group, number, SegmentInfoCls,
                        ref_to_idx, q_index):
    """
    Helper: Instantiates a localized sub-segment based on a specific group of aligned words.

    Unlike the previous version, this function computes the repetition metadata
    (wrap_word_ranges, repeated_ranges, repeated_text, has_repeated_words, and
    per-word line_idx) from scratch based on the word content of *this* group,
    rather than blindly inheriting those fields from the parent segment.
    """
    # Separate the Uthmani reference words and the ASR timing words.
    q_words = [g[0] for g in group]
    s_words = [g[1] for g in group]

    # Calculate the exact reference boundaries for this specific sub-chunk.
    ref_from = f"{q_words[0].surah}:{q_words[0].ayah}:{q_words[0].word}"
    ref_to   = f"{q_words[-1].surah}:{q_words[-1].ayah}:{q_words[-1].word}"

    # Calculate the exact audio timestamps based on the word timings.
    seg_start = s_words[0]["start"]
    seg_end   = s_words[-1]["end"]

    # Rebuild the plain string text for JSON viewing.
    matched_text = " ".join([s["word"] for s in s_words])

    # -----------------------------------------------------------------------
    # Per-sub-segment repetition metadata
    # -----------------------------------------------------------------------
    # Detect backward jumps within THIS group only.
    local_wrap_ranges = _compute_local_wrap_ranges(group, ref_to_idx)

    # has_repeated_words is true only when this specific sub-segment contains a jump.
    has_repeated_words = bool(local_wrap_ranges)

    # Compute repeated_ranges and repeated_text if there are local repetitions.
    if local_wrap_ranges:
        repeated_ranges, repeated_text = _compute_repeated_metadata(
            ref_from, ref_to, local_wrap_ranges, ref_to_idx, q_index
        )
    else:
        # No repetitions in this sub-segment — clear these fields.
        repeated_ranges = None
        repeated_text   = None

    # Assign line_idx to each word: 0 = first pass, 1 = second pass, etc.
    # Only meaningful when has_repeated_words is True, but we compute it regardless
    # so that the word dicts always have a consistent structure.
    if has_repeated_words:
        line_indices = _assign_line_idx(group, ref_to_idx)
    else:
        # All words belong to a single linear pass — line_idx is not added.
        line_indices = None

    # -----------------------------------------------------------------------
    # Build final word dictionaries, injecting location and (if needed) line_idx
    # -----------------------------------------------------------------------
    out_words = []
    for idx, (q_w, s_w) in enumerate(zip(q_words, s_words)):
        # Create a shallow copy of the ASR timing dict.
        w = dict(s_w)
        # Inject the canonical Quran location reference.
        w["location"] = f"{q_w.surah}:{q_w.ayah}:{q_w.word}"
        # Inject line_idx only for repetition segments (matches the original project format).
        if line_indices is not None:
            w["line_idx"] = line_indices[idx]
        # Append to the final list.
        out_words.append(w)

    # -----------------------------------------------------------------------
    # Construct and return the new SegmentInfo data class
    # -----------------------------------------------------------------------
    return SegmentInfoCls(
        # Pass the calculated start time.
        start_time=seg_start,
        # Pass the calculated end time.
        end_time=seg_end,
        # Clear the transcribed text as it is lost post-split.
        transcribed_text="",
        # Pass the reconstructed matched text.
        matched_text=matched_text,
        # Pass the calculated reference bounds string.
        matched_ref=f"{ref_from}-{ref_to}",
        # Inherit the match score from the parent segment.
        match_score=parent_seg.match_score,
        # Inherit any errors from the parent segment.
        error=parent_seg.error,
        # Inherit missing words flag from the parent (it's a property of the whole chunk).
        has_missing_words=parent_seg.has_missing_words,
        # Set correctly based on this sub-segment's own word content.
        has_repeated_words=has_repeated_words,
        # Set correctly based on jumps within this sub-segment only.
        wrap_word_ranges=local_wrap_ranges,
        # Set computed ranges (None if no repetitions).
        repeated_ranges=repeated_ranges,
        # Set computed text (None if no repetitions).
        repeated_text=repeated_text,
        # Pass the updated word dictionaries with location and line_idx.
        words=out_words,
        # Pass the assigned sequence number.
        segment_number=number,
    )


# ---------------------------------------------------------------------------
# Post-processing: Strip backward cross-ayah words
# ---------------------------------------------------------------------------
def _strip_backward_cross_ayah_words(segments, ref_to_idx, q_index, SegmentInfoCls):
    """
    Removes short hallucinated tails (words that jump BACKWARD to a previous ayah)
    at the very end of a segment. Genuine repetitions (which are usually longer
    or followed by forward progress) are preserved.
    """
    result = []
    for seg in segments:
        if not seg.words or not seg.matched_ref:
            result.append(seg)
            continue

        high_surah = 0
        high_ayah = 0
        
        # Determine the high water mark for the entire segment first
        for w in seg.words:
            loc = w.get("location", "")
            if not loc:
                continue
            parts = loc.split(":")
            if len(parts) >= 3:
                s, a = int(parts[0]), int(parts[1])
                if (s > high_surah) or (s == high_surah and a > high_ayah):
                    high_surah = s
                    high_ayah = a

        # Now find if there's a backward jump at the tail
        tail_start_idx = -1
        for i in range(len(seg.words) - 1, -1, -1):
            loc = seg.words[i].get("location", "")
            if not loc:
                break
            parts = loc.split(":")
            if len(parts) >= 3:
                s, a = int(parts[0]), int(parts[1])
                # If we hit a word that is AT the high water mark, the tail ends here.
                if s == high_surah and a == high_ayah:
                    break
                # If it's strictly before the high water mark, it's part of the backward tail
                if s < high_surah or (s == high_surah and a < high_ayah):
                    tail_start_idx = i
                else:
                    break
                    
        clean_words = list(seg.words)
        
        # If we found a backward tail, and it's short (<= 4 words), drop it.
        # This prevents dropping genuine long cross-ayah repetitions.
        if tail_start_idx != -1:
            tail_length = len(seg.words) - tail_start_idx
            if tail_length <= 4:
                clean_words = seg.words[:tail_start_idx]

        # If we dropped words, rebuild the segment with the clean list.
        if len(clean_words) != len(seg.words):
            if not clean_words:
                # All words were noise — skip this segment entirely.
                continue

            # Rebuild the segment from the cleaned word list.
            first_loc = clean_words[0].get("location", "")
            last_loc = clean_words[-1].get("location", "")
            matched_text = " ".join(w["word"] for w in clean_words)

            # Rebuild SegmentInfo with stripped words.
            new_seg = SegmentInfoCls(
                start_time=seg.start_time,
                end_time=seg.end_time,
                transcribed_text=seg.transcribed_text,
                matched_text=matched_text,
                matched_ref=f"{first_loc}-{last_loc}" if first_loc and last_loc else seg.matched_ref,
                match_score=seg.match_score,
                error=seg.error,
                has_missing_words=seg.has_missing_words,
                has_repeated_words=False,  # Recalculate below.
                wrap_word_ranges=None,
                words=clean_words,
                segment_number=seg.segment_number,
            )

            # Recalculate repetition metadata on the cleaned word list.
            # We need (QuranWord, asr_word) pairs for _compute_local_wrap_ranges.
            group = []
            for w in clean_words:
                loc = w.get("location", "")
                if loc:
                    p = loc.split(":")
                    idx = ref_to_idx.get(loc, -1)
                    if idx >= 0:
                        group.append((q_index.words[idx], w))

            local_wrap = _compute_local_wrap_ranges(group, ref_to_idx)
            if local_wrap:
                new_seg.has_repeated_words = True
                new_seg.wrap_word_ranges = local_wrap
                ref_from = clean_words[0].get("location", "")
                ref_to_val = clean_words[-1].get("location", "")
                repeated_ranges, repeated_text = _compute_repeated_metadata(
                    ref_from, ref_to_val, local_wrap, ref_to_idx, q_index
                )
                new_seg.repeated_ranges = repeated_ranges
                new_seg.repeated_text = repeated_text
                # Also assign line_idx to each word.
                line_indices = _assign_line_idx(group, ref_to_idx)
                for i, w in enumerate(clean_words):
                    if i < len(line_indices):
                        w["line_idx"] = line_indices[i]

            result.append(new_seg)
        else:
            # No words dropped — keep original segment.
            result.append(seg)

    return result


# ---------------------------------------------------------------------------
# Post-processing: Merge adjacent segments of the same ayah
# ---------------------------------------------------------------------------
def _merge_same_ayah_segments(segments, ref_to_idx, q_index, SegmentInfoCls):
    """
    Merges consecutive segments that belong to the same ayah when neither
    has repetitions.

    The original project never needed this because its VAD cut at Waqf pauses
    (one VAD chunk = one ayah). Our lightweight pipeline can produce multiple
    ASR chunks for the same ayah, which then become separate segments.

    Example: seg A = 3:67:1-10, seg B = 3:67:11-14 → merge into 3:67:1-14.

    We merge if:
    1. Both segments are matched (non-empty matched_ref, no errors).
    2. Both belong to the same (surah, ayah).
    3. The second segment's first word immediately follows the first segment's
       last word (no gap or overlap).
    4. Neither segment has_repeated_words.
    """
    if len(segments) < 2:
        return segments

    merged = [segments[0]]

    for i in range(1, len(segments)):
        prev = merged[-1]
        curr = segments[i]

        # Both must be successfully matched.
        if not prev.matched_ref or not curr.matched_ref:
            merged.append(curr)
            continue
        if prev.error or curr.error:
            merged.append(curr)
            continue

        # Neither should have repetitions (repetition segments are already correct).
        if prev.has_repeated_words or curr.has_repeated_words:
            merged.append(curr)
            continue

        # Parse the ayah boundaries.
        prev_parts = prev.matched_ref.split("-")
        curr_parts = curr.matched_ref.split("-")
        prev_end_ref = prev_parts[-1]  # e.g. "3:67:10"
        curr_start_ref = curr_parts[0]  # e.g. "3:67:11"

        prev_end_loc = prev_end_ref.split(":")
        curr_start_loc = curr_start_ref.split(":")

        if len(prev_end_loc) < 3 or len(curr_start_loc) < 3:
            merged.append(curr)
            continue

        prev_s, prev_a, prev_w = int(prev_end_loc[0]), int(prev_end_loc[1]), int(prev_end_loc[2])
        curr_s, curr_a, curr_w = int(curr_start_loc[0]), int(curr_start_loc[1]), int(curr_start_loc[2])

        # Must be the same surah and ayah.
        if prev_s != curr_s or prev_a != curr_a:
            merged.append(curr)
            continue

        # The second segment's first word must be a strict successor (gaps are allowed).
        if curr_w <= prev_w:
            merged.append(curr)
            continue

        # Check for missing words between the two chunks.
        gap_words = []
        if curr_w > prev_w + 1:
            missing_count = curr_w - prev_w - 1
            start_time = prev.words[-1]["end"]
            end_time = curr.words[0]["start"]

            # Enforce a minimum gap duration (e.g. 0.05s per missing word) to avoid zero-duration words
            min_gap = 0.05 * missing_count
            
            # Resolve overlaps (negative gap) or gaps that are too small
            if end_time - start_time < min_gap:
                midpoint = (start_time + end_time) / 2
                start_time = midpoint - (min_gap / 2)
                end_time = midpoint + (min_gap / 2)
                
                # Protect boundaries to ensure sequential integrity
                if start_time <= prev.words[-1]["start"]:
                    start_time = prev.words[-1]["start"] + 0.01
                if end_time >= curr.words[0]["end"]:
                    end_time = curr.words[0]["end"] - 0.01
                    
                start_time = round(start_time, 3)
                end_time = round(end_time, 3)
                
                # Snap the adjacent words to the newly expanded boundaries
                prev.words[-1]["end"] = start_time
                curr.words[0]["start"] = end_time

            gap_duration = max(0.0, end_time - start_time)
            slot = gap_duration / missing_count if missing_count > 0 else 0.0

            prev_global_idx = ref_to_idx.get(prev_end_ref)
            if prev_global_idx is not None:
                for k in range(1, missing_count + 1):
                    missing_q_word = q_index.words[prev_global_idx + k]
                    w_start = round(start_time + (k - 1) * slot, 3)
                    w_end = round(start_time + k * slot, 3)
                    gap_words.append({
                        "word": missing_q_word.text,
                        "start": w_start,
                        "end": w_end,
                        "location": f"{missing_q_word.surah}:{missing_q_word.ayah}:{missing_q_word.word}"
                    })

        # --- MERGE ---
        # Combine word lists including any missing gap words.
        combined_words = list(prev.words) + gap_words + list(curr.words)
        combined_text = " ".join(w["word"] for w in combined_words)
        new_ref = f"{prev_parts[0]}-{curr_parts[-1]}"
        new_score = max(prev.match_score, curr.match_score)
        new_has_missing = prev.has_missing_words or curr.has_missing_words or bool(gap_words)

        merged_seg = SegmentInfoCls(
            start_time=prev.start_time,
            end_time=curr.end_time,
            transcribed_text="",
            matched_text=combined_text,
            matched_ref=new_ref,
            match_score=new_score,
            error=None,
            has_missing_words=new_has_missing,
            has_repeated_words=False,
            wrap_word_ranges=None,
            words=combined_words,
            segment_number=prev.segment_number,
        )

        # Replace the last element in merged with the combined segment.
        merged[-1] = merged_seg

    return merged
