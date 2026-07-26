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

# Import the script paths from the main config file.
from config import QURAN_SCRIPT_PATH_COMPUTE, QURAN_SCRIPT_PATH_DISPLAY


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
        display_text: The typographically rich text used for UI rendering (Digital Khatt).
    """
    # Type hint for the global index integer.
    global_idx: int       
    # Type hint for the surah number integer.
    surah: int
    # Type hint for the ayah number integer.
    ayah: int
    # Type hint for the word number integer.
    word: int
    # Type hint for the computational text string.
    text: str             
    # Type hint for the display text string.
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
    # Type hint for the list of WordInfo objects.
    # A flat, ordered array of every word.
    words: list[WordInfo]                           
    # Type hint for the reverse-lookup dictionary mapping tuples to integers.
    # A fast reverse-lookup dictionary: (surah, ayah, word) -> global_idx
    word_lookup: dict[tuple[int, int, int], int]    

    # Use the classmethod decorator to define a factory method.
    @classmethod
    # Define the load method to construct a QuranIndex instance from files.
    def load(cls, compute_path: Optional[Path] = None, display_path: Optional[Path] = None) -> "QuranIndex":
        # A docstring explaining the load method.
        """
        Reads the JSON scripts from disk, parses them, merges compute and display data,
        and constructs the in-memory index.
        """
        # Check if the compute_path parameter was not provided.
        if compute_path is None:
            # Fall back to the default compute path from the config.
            compute_path = QURAN_SCRIPT_PATH_COMPUTE
        # Check if the display_path parameter was not provided.
        if display_path is None:
            # Fall back to the default display path from the config.
            display_path = QURAN_SCRIPT_PATH_DISPLAY

        # Load the computational script (mandatory).
        # Open the compute JSON file in read mode with UTF-8 encoding.
        with open(compute_path, "r", encoding="utf-8") as f:
            # Parse the JSON file into a Python dictionary.
            compute_data = json.load(f)
            
        # Initialize an empty dictionary for display data.
        display_data = {}
        # Start a try block to handle potential missing display files gracefully.
        try:
            # Load the display script (optional, gracefully degrades if missing).
            # Open the display JSON file in read mode.
            with open(display_path, "r", encoding="utf-8") as f:
                # Parse the JSON file into the display_data dictionary.
                display_data = json.load(f)
        # Catch the FileNotFoundError if the display file is missing.
        except FileNotFoundError:
            # Print a warning message and fallback.
            print(f"[QuranIndex] Display file {display_path} not found. Falling back to compute text.")

        # Initialize an empty list to store WordInfo objects.
        words: list[WordInfo] = []
        # Initialize an empty dictionary for the reverse lookup map.
        word_lookup: dict[tuple[int, int, int], int] = {}

        # The JSON dict keys are inherently unordered in old Python versions.
        # We explicitly sort them by (surah, ayah, word) to guarantee 1:1:1 comes before 1:1:2.
        # Extract keys from compute_data, sort them using the custom parse function.
        sorted_keys = sorted(compute_data.keys(), key=_parse_location_key)

        # Loop through each properly sorted key.
        for key in sorted_keys:
            # Retrieve the entry data for the current key.
            entry = compute_data[key]
            # Extract the computational text from the entry.
            text = entry["text"]

            # Filter out non-spoken verse markers.
            # Check if the text starts with the verse marker prefix.
            if text.startswith(VERSE_MARKER_PREFIX):
                # Skip this entry entirely.
                continue

            # Extract the surah number and convert to integer.
            surah = int(entry["surah"])
            # Extract the ayah number and convert to integer.
            ayah = int(entry["ayah"])
            # Extract the word number and convert to integer.
            word = int(entry["word"])

            # Attempt to pull the beautiful display text. If it doesn't exist, fallback to the compute text.
            # Use dictionary get() to safely fetch the display entry.
            dk_entry = display_data.get(key)
            # Assign display_text from dk_entry if it exists, otherwise fallback to compute text.
            display_text = dk_entry["text"] if dk_entry else text

            # Create the WordInfo struct
            # Instantiate a new WordInfo object with the extracted data.
            word_info = WordInfo(
                # Set the global index based on the current length of the words list.
                global_idx=len(words),
                # Set the surah number.
                surah=surah,
                # Set the ayah number.
                ayah=ayah,
                # Set the word number.
                word=word,
                # Set the computational text.
                text=text,
                # Set the display text.
                display_text=display_text,
            )
            # Append the completed WordInfo object to the main list.
            words.append(word_info)
            # Add to fast-lookup dictionary
            # Map the (surah, ayah, word) tuple to the global index integer.
            word_lookup[(surah, ayah, word)] = word_info.global_idx

        # Print a message indicating how many words were successfully loaded.
        print(f"[QuranIndex] Loaded {len(words)} words")

        # Return a new instance of the QuranIndex class populated with the parsed data.
        return cls(
            # Pass the complete list of WordInfo objects.
            words=words,
            # Pass the completed lookup dictionary.
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


# Define a private helper function to parse dictionary keys for sorting.
def _parse_location_key(key: str) -> tuple[int, int, int]:
    """
    Helper function to parse a string key like '2:255:3' into a comparable tuple (2, 255, 3).
    Used as the `key` argument in `sorted()` to ensure mathematical ordering.
    """
    # Split the string key by colons.
    parts = key.split(":")
    # Return a tuple of integers representing the surah, ayah, and word.
    return (int(parts[0]), int(parts[1]), int(parts[2]))


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
