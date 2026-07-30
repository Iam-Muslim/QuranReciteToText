"""
QuranIndex: The Single Source of Truth for Quranic Text

This module pre-loads and indexes every single word of the Quran into memory.
It uses two different scripts (orthographies) to balance computational accuracy with visual beauty:
1. QPC Hafs (qpc_hafs.json) - Used for mathematical string matching. It accurately reflects the 
   acoustic sounds of the reciter without confusing the DP algorithm with extra combining marks.
2. Digital Khatt (digital_khatt_v2_script.json) - Used exclusively for display. It contains all 
   the complex typography (waqf marks, small meems) needed for beautiful front-end rendering.
"""

# Import the annotations feature for advanced type hinting.
from __future__ import annotations

# Import the json module to parse the index files.
import json
# Import the dataclass decorator for clean data structures.
from dataclasses import dataclass
# Import the Path object for file path handling.
from pathlib import Path
# Import the Optional type hint for variables that can be None.
from typing import Optional

# Import the script paths from the main config file securely.
import sys
from pathlib import Path

# Add project root to path securely if not present to avoid namespace collisions with pip `config` package
_project_root = Path(__file__).parent.parent.parent.resolve()
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from config import QURAN_SCRIPT_PATH_COMPUTE


# Verse markers (the decorated circle denoting the end of an Ayah).
# We filter these out because reciters don't verbally say "ayah marker", 
# so including them would break the alignment engine.
# Define the special Unicode character used for verse markers.
VERSE_MARKER_PREFIX = '۝'


# Apply the dataclass decorator to automatically generate boilerplate methods for the class.
@dataclass
# Define the WordInfo class to represent a single Quranic word.
class WordInfo:
    """
    Data structure representing a single logical word in the Quran.
    
    Properties:
        global_idx: Absolute index (0 to ~77430) of the word in the entire Quran.
        surah: Chapter number (1-114).
        ayah: Verse number.
        word: The N-th word within the Ayah.
        text: The computational text used for algorithmic matching (QPC Hafs).
        display_text: The canonical text used for UI rendering.
    """
    global_idx: int       
    surah: int
    ayah: int
    word: int
    text: str             
    display_text: str     


# Apply the dataclass decorator to the QuranIndex class.
@dataclass
# Define the QuranIndex class to manage the global word index.
class QuranIndex:
    """
    A globally accessible, pre-indexed dictionary of the entire Quran.
    
    Primary purpose: Converting string references like "2:255:1-2:255:5" (Al-Baqarah 255, words 1 to 5)
    back into the exact Arabic text that needs to be outputted to the final JSON payload.
    """
    words: list[WordInfo]                           
    word_lookup: dict[tuple[int, int, int], int]    

    @classmethod
    def load(cls, compute_path: Optional[Path] = None) -> "QuranIndex":
        """
        Reads the JSON script from disk, parses it, and constructs the in-memory index.
        """
        if compute_path is None:
            compute_path = QURAN_SCRIPT_PATH_COMPUTE

        with open(compute_path, "r", encoding="utf-8") as f:
            compute_data = json.load(f)

        words: list[WordInfo] = []
        word_lookup: dict[tuple[int, int, int], int] = {}
        sorted_keys = sorted(compute_data.keys(), key=parse_location_key)

        for key in sorted_keys:
            entry = compute_data[key]
            text = entry["text"]

            if text.startswith(VERSE_MARKER_PREFIX):
                continue

            surah = int(entry["surah"])
            ayah = int(entry["ayah"])
            word = int(entry["word"])

            word_info = WordInfo(
                global_idx=len(words),
                surah=surah,
                ayah=ayah,
                word=word,
                text=text,
                display_text=text,
            )
            words.append(word_info)
            word_lookup[(surah, ayah, word)] = word_info.global_idx

        print(f"[QuranIndex] Loaded {len(words)} words")

        return cls(
            words=words,
            word_lookup=word_lookup,
        )

    # Define a method to convert reference strings into global indices.
    def ref_to_indices(self, ref: str) -> Optional[tuple[int, int]]:
        """
        Parses a hyphenated reference string and returns the absolute global start and end indices.
        
        Example: "1:1:1-1:1:4" -> (0, 3) 
                 "114:6:3"     -> (77429, 77429)
        """
        # Check if the reference is empty or invalid (missing colons).
        if not ref or ":" not in ref:
            # Return None if it's invalid.
            return None
        # Start a try block to handle parsing errors.
        try:
            # Handle both ranges (Start-End) and single-word references.
            # Check if there is a hyphen indicating a range.
            if "-" in ref:
                # Split the reference string into start and end parts.
                start_ref, end_ref = ref.split("-")
            # Execute this block if it's a single word reference.
            else:
                # Assign the same reference to both start and end.
                start_ref = end_ref = ref

            # Define a nested helper function for safe dictionary lookup.
            def _lookup(r: str) -> Optional[int]:
                # A docstring for the helper function.
                """Helper to safely query the dictionary."""
                # Split the individual reference string by colons.
                parts = r.split(":")
                # Ensure there are exactly 3 parts (surah, ayah, word).
                if len(parts) < 3:
                    # Return None if the format is malformed.
                    return None
                # Query the lookup dictionary using integer tuples and return the index.
                return self.word_lookup.get((int(parts[0]), int(parts[1]), int(parts[2])))

            # Look up the global index for the start reference.
            start_idx = _lookup(start_ref)
            # Look up the global index for the end reference.
            end_idx = _lookup(end_ref)
            
            # Ensure both the start and end indices were successfully resolved.
            if start_idx is None or end_idx is None:
                # Return None if either failed.
                return None
            # Return a tuple of the resolved integer indices.
            return start_idx, end_idx
        # Catch any generic exception during parsing.
        except Exception:
            # Return None to fail gracefully.
            return None


def parse_location_key(item) -> tuple[int, int, int]:
    """
    Universal helper to parse a location string like '2:255:3' or a word dict with a 'location' key
    into a comparable tuple (2, 255, 3) for mathematical sorting.
    """
    if isinstance(item, dict):
        key = str(item.get("location", ""))
    else:
        key = str(item)

    if ":" in key:
        parts = key.split(":")
        if len(parts) >= 3:
            try:
                return (int(parts[0]), int(parts[1]), int(parts[2]))
            except ValueError:
                pass
    return (0, 0, 0)

# Alias for backward compatibility
_parse_location_key = parse_location_key



# ==============================================================================
# Singleton Architecture
# ==============================================================================
# Loading the JSON indices takes hundreds of milliseconds. We don't want to do that 
# every time we lookup a word. This singleton ensures the index is loaded exactly once,
# stored in memory, and instantly available to all modules.
# Initialize a global cache variable to None.
_quran_index_cache: Optional[QuranIndex] = None


# Define a global accessor function to fetch the singleton instance.
def get_quran_index() -> QuranIndex:
    # A docstring explaining the global accessor.
    """Global accessor for the QuranIndex. Initializes it on the first call."""
    # Declare the use of the global cache variable.
    global _quran_index_cache
    # Check if the cache is currently empty (None).
    if _quran_index_cache is None:
        # Load the index from files and store it in the cache.
        _quran_index_cache = QuranIndex.load()
    # Return the cached instance.
    return _quran_index_cache
