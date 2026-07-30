# Multiline string serving as a docstring for the entire module.
"""
Auto-Merge: Handling Natural Pauses (Waqf and Sakt)

When a reciter is speaking, they naturally pause for breath or stylistic reasons (Waqf/Sakt).
The Silero VAD (Voice Activity Detector) will often mistakenly chop a single continuous Ayah 
into two separate audio chunks because of this pause.

This module is responsible for detecting when the VAD chopped a single Ayah in half, 
and surgically stitching the two JSON output segments back together into one unified block.
"""

# Import the annotations feature from __future__ for newer type hinting syntax.
from __future__ import annotations

# Import the uuid module to generate unique identifiers.
import uuid

# Import the specific schema classes from the qua_sdk library.
from qua_sdk.schemas import AlignedSegment, Alignment, Regions

# Import the AUTO_MERGE_GROUP_PREFIX configuration variable from our config module.
from config import AUTO_MERGE_GROUP_PREFIX
# Import the SegmentInfo class from our segment_types module.
from src.core.segment_types import SegmentInfo


# Define the waqf_sakt_consumed_by_target function that takes an Alignment object.
def waqf_sakt_consumed_by_target(alignment: Alignment) -> dict[int, AlignedSegment]:
    """
    Scans the SDK's alignment results to find any segments that were 
    automatically absorbed (merged) into a parent segment due to a Waqf/Sakt pause.
    
    Returns a dictionary mapping the Parent ID -> The Absorbed Segment Data.
    """
    # Initialize an empty dictionary to hold the result mapping.
    out: dict[int, AlignedSegment] = {}
    # Iterate through all segments in the alignment result.
    for seg in alignment.segments:
        # If this segment wasn't merged into anything, skip it.
        # Check if the merged_into property is None.
        if seg.merged_into is None:
            # Continue to the next iteration if the segment was not merged.
            continue
            
        # Check if the reason for the merge was a Waqf or Sakt pause.
        # Use getattr to safely check the merge_reason attribute.
        if getattr(seg, "merge_reason", None) == "waqf_sakt":
            # Map the parent ID to this absorbed segment in the output dictionary.
            out[seg.merged_into] = seg
            
    # Return the populated dictionary.
    return out


# Define a function to update the segment info with the auto-merge data.
def stamp_auto_merge_group(info: SegmentInfo, target: AlignedSegment,
                           consumed: AlignedSegment, regions: Regions) -> None:
    """
    When an auto-merge occurs, this function modifies the Parent SegmentInfo object
    in place, adding a unique `merge_group_id` so that downstream UIs know this card
    was algorithmically stitched together.
    
    It also saves the original pre-merge halves into `merge_members` just in case 
    a user ever wants to 'Undo' the algorithmic merge.
    """
    # Reconstruct what the first half of the audio chunk was.
    # Call the helper function to calculate the first half's segment info.
    member_a = _target_half(info, target, consumed, regions)
    # Check if the first half reconstruction failed.
    if member_a is None:
        # Return early if it failed.
        return
        
    # Reconstruct what the second half of the audio chunk was.
    # Call the helper function to calculate the second half's segment info.
    member_b = _consumed_half(consumed)
    
    # Assign a unique hash ID (e.g., merge-auto-a1b2c3d4) to link them visually.
    # Generate a UUID, truncate it, and prepend the config prefix.
    info.merge_group_id = f"{AUTO_MERGE_GROUP_PREFIX}{uuid.uuid4().hex[:8]}"
    
    # Stash the JSON serialization of both original halves.
    # Create a list containing the serialized dictionaries of both members.
    info.merge_members = [member_a.to_json_dict(), member_b.to_json_dict()]


# Define a private helper function to reconstruct the first half of a merged segment.
def _target_half(info: SegmentInfo, target: AlignedSegment,
                 consumed: AlignedSegment, regions: Regions) -> SegmentInfo | None:
    # A docstring explaining the purpose of the function.
    """
    Reconstructs the first half of a merged segment (the part before the pause).
    """
    # Calculate the verse reference bounds for just the first half.
    # Determine the reference string before the pause using a helper function.
    a_ref = _ref_before_consumed(target.matched_ref or "", consumed.matched_ref or "")
    # Check if the reference calculation failed.
    if a_ref is None:
        # Return None if it failed.
        return None

    # Determine exactly when the first half ended in the audio file.
    # Check if the target segment ID is within the bounds of the regions list.
    if target.id < len(regions.regions):
        # Extract the end time in seconds from the regions list.
        end_s = regions.regions[target.id].end_s
    # Execute this block if the target ID is out of bounds.
    else:
        # Fall back to using the start time of the consumed segment.
        end_s = consumed.region.start_s

    # Build a new SegmentInfo representing just the first half.
    # Instantiate and return a new SegmentInfo object.
    return SegmentInfo(
        # Set the start time from the target segment's region.
        start_time=target.region.start_s,
        # Set the end time calculated previously.
        end_time=end_s,
        # Initialize the transcribed text as an empty string.
        transcribed_text="",
        
        # Chop off the Arabic text of the second half to leave just the first half text.
        # Use the text subtraction helper function to get the first half's text.
        matched_text=_text_without_consumed_suffix(
            info.matched_text or "", consumed.matched_text or "", a_ref),
            
        # Set the calculated reference string for the first half.
        matched_ref=a_ref,
        # Set the match score to match the parent segment's score.
        match_score=info.match_score,
    )


# Define a private helper function to reconstruct the second half of a merged segment.
def _consumed_half(consumed: AlignedSegment) -> SegmentInfo:
    """
    Reconstructs the second half of a merged segment (the part after the pause).
    This is much easier because the SDK's `consumed` object still holds all the original data.
    """
    # Import the derive_repetition function dynamically to avoid circular imports.
    from src.core.sdk_adapt import derive_repetition

    # Extract the matched reference from the consumed segment.
    ref = consumed.matched_ref or ""
    # Extract the word wrapping ranges from the consumed segment.
    wrap_ranges = consumed.wrap_word_ranges
    # Calculate any repetition ranges and text based on the reference and wrap ranges.
    rep_ranges, rep_text = derive_repetition(ref, wrap_ranges)
    
    # Return a new SegmentInfo object representing the second half.
    return SegmentInfo(
        # Set the start time directly from the consumed segment's region.
        start_time=consumed.region.start_s,
        # Set the end time directly from the consumed segment's region.
        end_time=consumed.region.end_s,
        # Initialize the transcribed text as an empty string.
        transcribed_text="",
        # Use the matched text directly from the consumed segment.
        matched_text=consumed.matched_text,
        # Use the extracted reference string.
        matched_ref=ref,
        # Use the confidence score from the consumed segment as the match score.
        match_score=consumed.confidence,
        # Check if there are wrap word ranges to determine if words are repeated.
        has_repeated_words=bool(wrap_ranges),
        # Store the word wrapping ranges.
        wrap_word_ranges=wrap_ranges,
        # Store the calculated repetition ranges.
        repeated_ranges=rep_ranges,
        # Store the calculated repetition text.
        repeated_text=rep_text,
    )


# Define a private helper function to calculate the Quranic reference before a pause.
def _ref_before_consumed(target_ref: str, consumed_ref: str) -> str | None:
    """
    A mathematical helper function to calculate the Quranic reference of the word 
    immediately *before* the pause happened.
    
    E.g. If the whole segment is words 1-10, and the pause happened at word 6, 
    this calculates that the first half must be words 1-5.
    """
    # Extract the starting reference part from the target reference string.
    start = target_ref.split("-")[0]
    # Extract the starting reference part from the consumed reference string.
    consumed_start = consumed_ref.split("-")[0]
    # Split the consumed start string into surah, ayah, and word components.
    parts = consumed_start.split(":")
    
    # Check if the start reference is invalid or if parts don't form a valid triplet.
    if not start or len(parts) != 3:
        # Return None if the format is unexpected.
        return None
        
    # Start a try block to handle potential conversion errors.
    try:
        # Convert the surah, ayah, and word string components into integers.
        surah, ayah, word = (int(p) for p in parts)
    # Catch any ValueError if the conversion fails.
    except ValueError:
        # Return None if conversion fails.
        return None
        
    # Check if the word index is less than 2, meaning it's the first word.
    if word < 2:
        # Return None as there's no "previous" word to reference.
        return None
        
    # Construct a string representing the reference of the previous word.
    prev_loc = f"{surah}:{ayah}:{word - 1}"
    # Return the simple reference if start equals prev_loc, otherwise a range reference.
    return prev_loc if start == prev_loc else f"{start}-{prev_loc}"


# Define a private helper function to remove the suffix from the merged text.
def _text_without_consumed_suffix(merged_text: str, consumed_text: str,
                                  a_ref: str) -> str:
    """
    A string manipulation helper. It takes the full Arabic text of the merged segment, 
    and subtracts the text of the second half, returning only the text of the first half.
    """
    # If it's a perfect string match at the end, just slice it off.
    # Check if consumed_text exists and if the merged_text correctly ends with it.
    if consumed_text and merged_text.endswith(consumed_text):
        # Calculate the length of the suffix, slice it off, and strip trailing whitespace.
        return merged_text[: len(merged_text) - len(consumed_text)].rstrip()

    # If slicing fails (due to minor typographic differences), fall back to querying 
    # the exact words from the global Quran index database.
    # Import the get_quran_index function dynamically.
    from src.core.quran_index import get_quran_index
    # Retrieve the global Quran index instance.
    qi = get_quran_index()
    # Resolve the start and end indices of the reference in the database.
    indices = qi.ref_to_indices(a_ref)
    
    # Check if the indices could not be resolved.
    if not indices:
        # Return the original merged_text as a final fallback.
        return merged_text
        
    # Unpack the start and end indices.
    s_i, e_i = indices
    # Reconstruct the string by joining the display_text of each word in the range.
    return " ".join(w.display_text for w in qi.words[s_i:e_i + 1])


def fuse_adjacent_same_ayah_segments(segments: list[SegmentInfo]) -> list[SegmentInfo]:
    """
    Fuses adjacent segments belonging to the SAME Ayah into a single unified segment card.

    E.g., if seg A is 3:72:1-6 and seg B is 3:72:8-17, they are fused into a single
    segment 3:72:1-17 spanning from seg A.start_time to seg B.end_time.
    """
    try:
        from config import ENABLE_SAME_AYAH_FUSION
    except ImportError:
        ENABLE_SAME_AYAH_FUSION = True

    if not ENABLE_SAME_AYAH_FUSION or not segments:
        return segments

    merged = []
    i = 0
    n = len(segments)
    n_fused = 0

    while i < n:
        curr = segments[i]
        rf = str(curr.matched_ref or "")
        if not rf or ":" not in rf:
            merged.append(curr)
            i += 1
            continue
        p = rf.split("-")[0].split(":")
        if len(p) < 2:
            merged.append(curr)
            i += 1
            continue
        s_id, a_id = p[0], p[1]

        to_fuse = [curr]
        j = i + 1
        while j < n:
            n_rf = str(segments[j].matched_ref or "")
            if not n_rf or ":" not in n_rf:
                break
            np = n_rf.split("-")[0].split(":")
            if len(np) >= 2 and np[0] == s_id and np[1] == a_id:
                to_fuse.append(segments[j])
                j += 1
            else:
                break

        if len(to_fuse) == 1:
            merged.append(curr)
            i += 1
        else:
            first = to_fuse[0]
            last = to_fuse[-1]

            fused_ref_start = first.matched_ref.split("-")[0]
            fused_ref_end = last.matched_ref.split("-")[-1]
            fused_ref = f"{fused_ref_start}-{fused_ref_end}"

            fused_text = " ".join(s.matched_text for s in to_fuse if s.matched_text)
            fused_words = []
            for s in to_fuse:
                if s.words:
                    fused_words.extend(s.words)

            from src.core.quran_index import parse_location_key
            fused_words.sort(key=parse_location_key)


            fused_seg = SegmentInfo(
                start_time=first.start_time,
                end_time=last.end_time,
                transcribed_text="",
                matched_text=fused_text,
                matched_ref=fused_ref,
                match_score=min(s.match_score for s in to_fuse),
                words=fused_words,
                has_missing_words=any(s.has_missing_words for s in to_fuse),
                has_repeated_words=any(s.has_repeated_words for s in to_fuse),
            )
            merged.append(fused_seg)
            n_fused += (len(to_fuse) - 1)
            i = j

    if n_fused > 0:
        print(f"[SAME_AYAH_FUSE] Fused {n_fused} adjacent same-ayah segments into unified per-ayah cards.")

    return merged
