from src.core.segment_types import SegmentInfo
from src.core.quran_index import get_quran_index

def inject_missing_words(segments: list[SegmentInfo]) -> list[SegmentInfo]:
    """
    Analyzes the finalized segments array and injects any missing words 
    directly into the `words` list with the `is_missing` flag.
    """
    if not segments:
        return segments

    q_index = get_quran_index()
    q_words = q_index.words

    for i in range(len(segments)):
        seg = segments[i]
        
        # Skip special segments (e.g. Basmala, Isti'adha)
        if not seg.matched_ref or seg.matched_ref in ["Basmala", "Isti'adha", "Isti'adha+Basmala"]:
            continue
            
        indices = q_index.ref_to_indices(seg.matched_ref)
        if not indices:
            continue
            
        start_idx, end_idx = indices
        
        # 1. Check for gap between this segment and the next
        if i + 1 < len(segments):
            next_seg = segments[i + 1]
            next_indices = q_index.ref_to_indices(next_seg.matched_ref)
            if next_indices:
                next_start, _ = next_indices
                
                # If there's a gap AND they are in the same Surah
                if next_start > end_idx + 1:
                    # Make sure it's the same Surah to avoid crossing chapters
                    if q_words[end_idx].surah == q_words[next_start - 1].surah:
                        _append_missing(seg, end_idx + 1, next_start - 1, q_words)
                        # Update the segment's end boundary since we appended words
                        end_idx = next_start - 1
                        
        # 2. Check for unfinished Ayah at the very end of the file
        if i == len(segments) - 1:
            verse_end_idx = end_idx
            while verse_end_idx + 1 < len(q_words) and q_words[verse_end_idx + 1].ayah == q_words[end_idx].ayah:
                verse_end_idx += 1
                
            if verse_end_idx > end_idx:
                _append_missing(seg, end_idx + 1, verse_end_idx, q_words)

    return segments

def _append_missing(seg: SegmentInfo, start_idx: int, end_idx: int, q_words):
    """Appends words from start_idx to end_idx into the segment's words array."""
    if seg.words is None:
        seg.words = []
        
    for w_idx in range(start_idx, end_idx + 1):
        q_w = q_words[w_idx]
        loc = f"{q_w.surah}:{q_w.ayah}:{q_w.word}"
        missing_entry = {
            "word": q_w.display_text,
            "location": loc,
            "start": None,
            "end": None,
            "is_missing": True
        }
        seg.words.append(missing_entry)
        
        # Append to matched text
        if seg.matched_text:
            seg.matched_text += f" {q_w.display_text}"
        else:
            seg.matched_text = q_w.display_text
            
    # Update matched_ref to encompass the newly added words
    first_q_w = q_words[start_idx]
    last_q_w = q_words[end_idx]
    
    if "-" in seg.matched_ref:
        ref_from = seg.matched_ref.split("-")[0]
        seg.matched_ref = f"{ref_from}-{last_q_w.surah}:{last_q_w.ayah}:{last_q_w.word}"
    else:
        # It was a single word, now it's a range
        seg.matched_ref = f"{seg.matched_ref}-{last_q_w.surah}:{last_q_w.ayah}:{last_q_w.word}"
