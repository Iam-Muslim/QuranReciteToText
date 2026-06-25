"""MFA-based splitting of combined/fused special segments (Isti\'adha/Basmala)."""
from src.core.segment_types import SegmentInfo


def _split_fused_segments(segments, audio_int16, sample_rate):
    """Post-processing: Split 30s Sliding Window segments by Ayah and Repetition."""
    # Import the Quran index, which holds the database of all Uthmani words.
    from src.core.quran_index import get_quran_index
    from src.core.segment_types import compute_reading_sequence, SegmentInfo
    
    # Retrieve the singleton instance of the Quran index.
    q_index = get_quran_index()
    
    # Precompute a ref -> index map for fast lookup.
    # This allows instantly finding the integer index of a specific word (e.g., "1:1:1" -> 0)
    ref_to_idx = {}
    for i, w in enumerate(q_index.words):
        ref_to_idx[f"{w.surah}:{w.ayah}:{w.word}"] = i
        
    # List to hold the newly created, finely split sub-segments.
    out_segments = []
    
    # Iterate over the large, raw 30-second blocks produced by the DP matcher.
    for seg in segments:
        # If the segment lacks words or failed to match against the reference, keep it as-is.
        if not seg.words or not seg.matched_ref:
            out_segments.append(seg)
            continue
            
        # Parse the reference range string (e.g., "1:1:1-1:2:3") into its start and end components.
        parts = seg.matched_ref.split("-")
        ref_from = parts[0]
        ref_to = parts[1] if len(parts) > 1 else parts[0]
        
        # Determine the logical sequence of verses read, accounting for wrap-arounds (repetitions).
        sections = compute_reading_sequence(ref_from, ref_to, seg.wrap_word_ranges)
        
        # Build the exact sequence of QuranWords that were recited in this block.
        seq_words = []
        for sec in sections:
            start_ref, end_ref = sec
            # Ensure both the start and end references exist in our index.
            if start_ref in ref_to_idx and end_ref in ref_to_idx:
                start_i = ref_to_idx[start_ref]
                end_i = ref_to_idx[end_ref]
                # Extract the continuous sequence of words from the index.
                for i in range(start_i, end_i + 1):
                    seq_words.append(q_index.words[i])
                    
        # If the number of extracted Quran words doesn't perfectly match the ASR word count,
        # fallback to leaving the segment undivided to avoid alignment drift.
        if len(seq_words) != len(seg.words):
            out_segments.append(seg)
            continue
            
        current_ayah_group = []
        # Pair each recognized ASR word with its mathematical Uthmani counterpart.
        for i in range(len(seg.words)):
            q_w = seq_words[i]
            s_w = seg.words[i]
            
            split_now = False
            # Check if we need to split the segment right before this word.
            if len(current_ayah_group) > 0:
                prev_q_w = current_ayah_group[-1][0]
                
                # Rule 1: Split if the current word crosses an Ayah or Surah boundary.
                if prev_q_w.surah != q_w.surah or prev_q_w.ayah != q_w.ayah:
                    split_now = True
                # Rule 2: Split if the current word skips backwards (a repetition / wrap-around).
                elif ref_to_idx[f"{q_w.surah}:{q_w.ayah}:{q_w.word}"] < ref_to_idx[f"{prev_q_w.surah}:{prev_q_w.ayah}:{prev_q_w.word}"]:
                    split_now = True
                    
            # If a boundary was detected, package the grouped words into a new segment.
            if split_now:
                out_segments.append(_create_sub_segment(seg, current_ayah_group, len(out_segments) + 1, SegmentInfo))
                current_ayah_group = []
                
            # Add the current word pair to the accumulating group.
            current_ayah_group.append((q_w, s_w))
            
        # Flush the final remaining group of words into a segment.
        if current_ayah_group:
            out_segments.append(_create_sub_segment(seg, current_ayah_group, len(out_segments) + 1, SegmentInfo))
            
    # Update sequential segment numbering for all extracted sections.
    for i, s in enumerate(out_segments):
        s.segment_number = i + 1
        
    return out_segments

def _create_sub_segment(parent_seg, group, number, SegmentInfoCls):
    """Helper: Instantiates a localized sub-segment based on a specific group of aligned words."""
    # Separate the Uthmani reference words and the ASR timing words.
    q_words = [g[0] for g in group]
    s_words = [g[1] for g in group]
    
    # Calculate the exact mathematical reference boundaries for this specific chunk.
    ref_from = f"{q_words[0].surah}:{q_words[0].ayah}:{q_words[0].word}"
    ref_to = f"{q_words[-1].surah}:{q_words[-1].ayah}:{q_words[-1].word}"
    seg_start = s_words[0]["start"]
    seg_end = s_words[-1]["end"]
    
    # Rebuild the plain string text for JSON viewing.
    matched_text = " ".join([s["word"] for s in s_words])
    
    # Stamp the Quran location ref and convert to relative timestamps.
    out_words = []
    for q_w, s_w in zip(q_words, s_words):
        w = dict(s_w)
        w["location"] = f"{q_w.surah}:{q_w.ayah}:{q_w.word}"
        out_words.append(w)
    
    # Construct and return the new data class.
    return SegmentInfoCls(
        start_time=seg_start,
        end_time=seg_end,
        transcribed_text="",
        matched_text=matched_text,
        matched_ref=f"{ref_from}-{ref_to}",
        match_score=parent_seg.match_score,
        error=parent_seg.error,
        words=out_words,
        segment_number=number
    )
