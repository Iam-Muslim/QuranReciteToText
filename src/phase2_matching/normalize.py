"""
Text Normalization & Resource Initialization (Phase 2 Matcher)

This module prepares the raw Arabic text for the Dynamic Programming (DP) alignment engine.
It contains functions to strip diacritics, normalize orthography (e.g. converting different 
types of Alef into a single standard Alef), and build the N-Gram indices used for fast anchoring.
"""
# Import domain schemas required by the DP SDK.
from qua_sdk.domain.chapter_refs import ChapterReference, RefWord, _assemble
# Import the N-Gram index data structure.
from qua_sdk.domain.anchor_index import PhonemeNgramIndex
# Import the Substitution Cost Table structure.
from qua_sdk.domain.sub_costs import SubCostTable
# Import the special templates registry.
from qua_sdk.components.matching.lib.specials import SpecialTemplates
# Import the main matching resources container.
from qua_sdk.components.matching.runtimes.sequencer import MatchingResources
# Import the global Quran index provider.
from src.core.quran_index import get_quran_index
# Import the regular expressions module for text replacement.
import re

# Define the text normalization function.
def normalize_arabic(text: str) -> str:
    """
    Strips all diacritics and normalizes Arabic characters for robust text matching.
    
    Why? The ASR model (FastConformer) often hallucinates Taa Marbutah vs Haa, or misses 
    Hamzas on Alefs. By stripping all of these to their base skeletal forms, we force the 
    DP matcher to focus strictly on the core letters, virtually eliminating false-negatives.
    """
    # Remove tashkeel, Quranic punctuation, Ayah markers (۝), Hizb (۞), Sajdah (۩), and numbers.
    # Apply regex substitution to remove the specified characters.
    text = re.sub(r'[\u064B-\u065F\u0670\u06D6-\u06E9\u06EA-\u06ED٠-٩0-9]', '', text)
    # Normalize all Alef variants (with hamza, madda, etc.) to a plain bare Alef.
    # Apply regex substitution to replace all Alef variants with a standard Alef (ا).
    text = re.sub(r'[إأآٱ]', 'ا', text)
    # Normalize all Yaa variants (alef maksura, yaa) to a standard Yaa.
    # Apply regex substitution to replace all Yaa variants with a standard Yaa (ي).
    text = re.sub(r'[ىي]', 'ي', text)
    # Normalize Taa Marbutah to Haa (common in ASR outputs).
    # Apply regex substitution to replace Taa Marbutah with Haa.
    text = re.sub(r'ة', 'ه', text)
    # Remove Tatweel (the elongation character).
    # Apply regex substitution to remove Tatweel completely.
    text = re.sub(r'ـ', '', text)
    # Return the fully normalized string.
    return text

# Define the resource initialization function.
def get_arabic_resources() -> MatchingResources:
    """
    Build MatchingResources using character-level Arabic text alignment.
    
    This replaces the default phonetic aligner. It aligns individual normalized 
    characters to guarantee 100% accurate Uthmani mapping despite ASR word-spacing errors.
    """
    # Load the comprehensive Quran database containing every word and its metadata.
    # Retrieve the global Quran index instance.
    q_index = get_quran_index()
    
    # Group all words by their Surah (Chapter) number.
    # Initialize an empty dictionary to hold the grouped words.
    surah_words = {}
    # Iterate through every single word in the Quran index.
    for w in q_index.words:
        # Check if the current Surah has not been initialized in the dictionary.
        if w.surah not in surah_words:
            # Initialize an empty list for this Surah.
            surah_words[w.surah] = []
            
        # Strip diacritics from the Uthmani word so it perfectly matches the ASR format.
        # Call the normalizer on the canonical word.
        norm_text = normalize_arabic(w.text)
        
        # Package the word into the SDK's expected RefWord format.
        # We break the word down into a list of characters (plus a trailing space).
        # This tricks the DP Matcher into performing character-level sequence alignment.
        # Append the new RefWord object to the Surah's list.
        surah_words[w.surah].append(RefWord(
            # Pass the original unnormalized text for reference.
            text=w.text,
            # Pass the list of normalized characters (plus space) as the "phonemes".
            phonemes=list(norm_text) + [' '],
            # Pass the Surah number.
            surah=w.surah,
            # Pass the Ayah number.
            ayah=w.ayah,
            # Pass the Word number.
            word_num=w.word,
        ))
        
    # Compile the organized words into ChapterReference objects required by the SDK.
    # Use a dictionary comprehension to build ChapterReferences for each Surah.
    chapter_refs = {s: _assemble(s, surah_words[s]) for s in sorted(surah_words)}
    
    # Build a fast N-Gram index to allow the DP Engine to instantly find "Anchors" (starting points).
    # Import defaultdict for automatic list initialization.
    from collections import defaultdict
    # Initialize a defaultdict to store the positions of each N-Gram.
    ngram_positions = defaultdict(list)
    # Initialize a counter for the total number of N-Grams processed.
    total_ngrams = 0
    
    # Iterate through all chapters to map out character sequences for the N-Gram index.
    # Loop over all constructed ChapterReferences.
    for surah, ref in chapter_refs.items():
        # Initialize a defaultdict to temporarily store characters per Ayah.
        verse_chars = defaultdict(list)
        # Iterate through every word in the current chapter.
        for w in ref.words:
            # Flatten the individual characters of each verse into a single continuous list.
            # Extend the Ayah's list with the characters from the current word.
            verse_chars[w.ayah].extend(w.phonemes)
            
        # Iterate through the flattened verses.
        for ayah, chars in verse_chars.items():
            # Skip extremely short verses that cannot form a valid 10-character N-Gram.
            # Check if the verse has fewer than 10 characters.
            if len(chars) < 10:
                # Skip to the next verse.
                continue
            # Extract every overlapping 10-character sequence (N-Gram) and record its exact location.
            # Loop over all possible starting positions for a 10-character window.
            for i in range(len(chars) - 10 + 1):
                # Extract the 10-character tuple.
                ng = tuple(chars[i : i + 10])
                # Append the exact (Surah, Ayah) location to the index.
                ngram_positions[ng].append((surah, ayah))
                # Increment the total N-Gram counter.
                total_ngrams += 1
                
    # Finalize the N-Gram Index object.
    # Instantiate the PhonemeNgramIndex structure.
    ngram_index = PhonemeNgramIndex(
        # Convert the defaultdict back to a standard dict.
        ngram_positions=dict(ngram_positions),
        # Calculate the frequency count of each N-Gram.
        ngram_counts={ng: len(pos) for ng, pos in ngram_positions.items()},
        # Require 10 consecutive matching characters to establish a firm anchor.
        # Set the size parameter to 10.
        ngram_size=10,  
        # Pass the total counter.
        total_ngrams=total_ngrams,
    )
    
    # Define the Substitution Cost Table. 
    # default=1.0 means any character mismatch costs 1 penalty point in the DP matrix.
    # Instantiate the SubCostTable.
    sub_table = SubCostTable(mode="arabic", default=1.0, pairs={})
    # Instantiate the SpecialTemplates structure for common phrases.
    templates = SpecialTemplates(
        # Set the mode string.
        mode="arabic",
        # Define the Basmala template, split into normalized characters.
        special={"Basmala": list(normalize_arabic("بسم الله الرحمن الرحيم")) + [' ']},
        # Define a common prayer transition template.
        transition={"Tahmeed": list(normalize_arabic("سمع الله لمن حمده")) + [' ']},
        # Define an empty dictionary for combined templates.
        combined={}
    )
    
    # Return the fully constructed MatchingResources object.
    return MatchingResources(
        # Set the mode string.
        mode="arabic",
        # Pass the chapter references map.
        chapter_refs=chapter_refs,
        # Pass the N-Gram index.
        ngram_index=ngram_index,
        # Pass the substitution cost table.
        sub_table=sub_table,
        # Pass the special templates.
        templates=templates,
    )
