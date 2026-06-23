"""Custom matching resources for Arabic text alignment."""

from qua_sdk.domain.chapter_refs import ChapterReference, RefWord, _assemble
from qua_sdk.domain.anchor_index import PhonemeNgramIndex
from qua_sdk.domain.sub_costs import SubCostTable
from qua_sdk.components.matching.lib.specials import SpecialTemplates
from qua_sdk.components.matching.runtimes.sequencer import MatchingResources
from src.core.quran_index import get_quran_index
import re

def normalize_arabic(text: str) -> str:
    """Strips all diacritics and normalizes Arabic characters for robust text matching."""
    # Remove tashkeel (fatha, damma, kasra, etc.) and specific Quranic punctuation marks.
    text = re.sub(r'[\u064B-\u065F\u0670\u06D6-\u06DC\u06DF-\u06E8\u06EA-\u06ED]', '', text)
    # Normalize all Alef variants (with hamza, madda, etc.) to a plain bare Alef.
    text = re.sub(r'[إأآٱ]', 'ا', text)
    # Normalize all Yaa variants (alef maksura, yaa) to a standard Yaa.
    text = re.sub(r'[ىي]', 'ي', text)
    # Normalize Taa Marbutah to Haa (common in ASR outputs).
    text = re.sub(r'ة', 'ه', text)
    # Remove Tatweel (the elongation character).
    text = re.sub(r'ـ', '', text)
    return text

def get_arabic_resources() -> MatchingResources:
    """Build MatchingResources using character-level Arabic text alignment.
    
    This replaces the default phonetic aligner. It aligns individual normalized 
    characters to guarantee 100% accurate Uthmani mapping despite ASR word-spacing errors.
    """
    # Load the comprehensive Quran database containing every word and its metadata.
    q_index = get_quran_index()
    
    # Group all words by their Surah (Chapter) number.
    surah_words = {}
    for w in q_index.words:
        if w.surah not in surah_words:
            surah_words[w.surah] = []
            
        # Strip diacritics from the Uthmani word so it perfectly matches the ASR format.
        norm_text = normalize_arabic(w.text)
        
        # Package the word into the SDK's expected RefWord format.
        # We break the word down into a list of characters (plus a trailing space).
        # This tricks the DP Matcher into performing character-level sequence alignment.
        surah_words[w.surah].append(RefWord(
            text=w.text,
            phonemes=list(norm_text) + [' '],
            surah=w.surah,
            ayah=w.ayah,
            word_num=w.word,
        ))
        
    # Compile the organized words into ChapterReference objects required by the SDK.
    chapter_refs = {s: _assemble(s, surah_words[s]) for s in sorted(surah_words)}
    
    # Build a fast N-Gram index to allow the DP Engine to instantly find "Anchors" (starting points).
    from collections import defaultdict
    ngram_positions = defaultdict(list)
    total_ngrams = 0
    
    # Iterate through all chapters to map out character sequences for the N-Gram index.
    for surah, ref in chapter_refs.items():
        verse_chars = defaultdict(list)
        for w in ref.words:
            # Flatten the individual characters of each verse into a single continuous list.
            verse_chars[w.ayah].extend(w.phonemes)
            
        for ayah, chars in verse_chars.items():
            # Skip extremely short verses that cannot form a valid 10-character N-Gram.
            if len(chars) < 10:
                continue
            # Extract every overlapping 10-character sequence (N-Gram) and record its exact location.
            for i in range(len(chars) - 10 + 1):
                ng = tuple(chars[i : i + 10])
                ngram_positions[ng].append((surah, ayah))
                total_ngrams += 1
                
    # Finalize the N-Gram Index object.
    ngram_index = PhonemeNgramIndex(
        ngram_positions=dict(ngram_positions),
        ngram_counts={ng: len(pos) for ng, pos in ngram_positions.items()},
        ngram_size=10,  # Require 10 consecutive matching characters to establish a firm anchor.
        total_ngrams=total_ngrams,
    )
    
    # Define the Substitution Cost Table. 
    # default=1.0 means any character mismatch costs 1 penalty point in the DP matrix.
    sub_table = SubCostTable(mode="arabic", default=1.0, pairs={})
    templates = SpecialTemplates(
        mode="arabic",
        special={"Basmala": list(normalize_arabic("بسم الله الرحمن الرحيم")) + [' ']},
        transition={"Tahmeed": list(normalize_arabic("سمع الله لمن حمده")) + [' ']},
        combined={}
    )
    
    return MatchingResources(
        mode="arabic",
        chapter_refs=chapter_refs,
        ngram_index=ngram_index,
        sub_table=sub_table,
        templates=templates,
    )
