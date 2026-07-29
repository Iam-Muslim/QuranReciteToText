from src.core.segment_types import SegmentInfo

def smooth_timestamps(segments: list[SegmentInfo]) -> list[SegmentInfo]:
    """
    Global post-processing pass to smooth and interpolate word timestamps.
    
    1. Interpolates timestamps for missing words (start: None) by distributing
       the time gap between the previous and next valid words proportionally
       based on the missing words' string lengths.
    2. Stretches the end time of every word exactly to the start time of the
       next word (zero-gap), ensuring trailing vowels (Madd) or pauses are
       captured and no screen-time gaps exist in subtitles.
    """
    if not segments:
        return segments

    # 1. Convert all timestamps to absolute time
    for seg in segments:
        if seg.words:
            for w in seg.words:
                if w.get('start') is not None:
                    w['start'] += seg.start_time
                if w.get('end') is not None:
                    w['end'] += seg.start_time

    # Flatten all words by reference so we can modify them globally
    all_words = []
    for seg in segments:
        if seg.words:
            all_words.extend(seg.words)

    if not all_words:
        return segments

    # PASS 1: Interpolate missing words (using absolute time)
    i = 0
    while i < len(all_words):
        if all_words[i].get('start') is None:
            # We found a block of missing words. Find where it ends.
            j = i
            while j < len(all_words) and all_words[j].get('start') is None:
                j += 1
            
            # The missing block is from i to j-1.
            missing_block = all_words[i:j]
            
            # Find prev_valid_end
            if i > 0 and all_words[i-1].get('end') is not None:
                prev_valid_end = all_words[i-1]['end']
            else:
                prev_valid_end = 0.0
                
            # Find next_valid_start
            if j < len(all_words) and all_words[j].get('start') is not None:
                next_valid_start = all_words[j]['start']
            else:
                # If there are no valid words after this block, just give them a fixed default duration
                next_valid_start = prev_valid_end + (len(missing_block) * 0.5)

            # Ensure we don't have negative gaps
            if next_valid_start < prev_valid_end:
                next_valid_start = prev_valid_end
                
            # Distribute the gap proportionally based on character length
            total_chars = sum(len(w.get('word', '')) for w in missing_block)
            if total_chars == 0:
                total_chars = 1 # fallback

            gap_duration = next_valid_start - prev_valid_end
            current_time = prev_valid_end
            
            for w in missing_block:
                char_len = len(w.get('word', ''))
                w_duration = (char_len / total_chars) * gap_duration
                w['start'] = current_time
                w['end'] = current_time + w_duration
                current_time += w_duration
                
            i = j
        else:
            i += 1

    # PASS 2: Contiguous stretching (end -> next_start)
    for i in range(len(all_words) - 1):
        curr_word = all_words[i]
        next_word = all_words[i + 1]
        
        # Stretch current word's end to the exact start of the next word
        curr_word['end'] = next_word['start']

    # PASS 3: Align Segment Boundaries to Prevent Overlap
    # Since words were stretched across VAD boundaries, we must update the segment
    # start_time and end_time to perfectly match the first and last words.
    for seg in segments:
        if seg.words:
            # Segment starts exactly when its first word starts
            first_start = next((w['start'] for w in seg.words if w.get('start') is not None), None)
            if first_start is not None:
                seg.start_time = first_start
                
            # Segment ends exactly when its last word ends
            last_end = next((w['end'] for w in reversed(seg.words) if w.get('end') is not None), None)
            if last_end is not None:
                seg.end_time = last_end

    # 4. Convert all timestamps back to relative time for the final JSON structure
    for seg in segments:
        if seg.words:
            for w in seg.words:
                if w.get('start') is not None:
                    w['start'] = round(max(0.0, w['start'] - seg.start_time), 4)
                if w.get('end') is not None:
                    w['end'] = round(max(0.0, w['end'] - seg.start_time), 4)

    return segments
