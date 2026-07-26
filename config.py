# Import the os module for interacting with the operating system environment variables.
import os
# Import the Path class from pathlib module to handle filesystem paths in a cross-platform way.
from pathlib import Path

# Multiline string serving as a docstring for the entire module.
"""
Global Configuration & Path Definitions.

This file acts as the central hub for static file paths and tuning parameters. 
By centralizing these variables, we ensure the entire pipeline pulls from a single 
source of truth. If you need to troubleshoot missing index files or change caching limits, check here.
"""

# ==============================================================================
# 1. Base Directory Resolution
# ==============================================================================
# PROJECT_ROOT dynamically resolves the absolute path to the directory containing this config.py file.
# Using absolute paths prevents "file not found" errors when the script is run from different working directories.
# Calculate the absolute path of the parent directory of this script and assign it to PROJECT_ROOT.
PROJECT_ROOT = Path(__file__).parent.absolute()

# DATA_PATH points to the core 'data' folder where models, text indices, and temporary files are stored.
# Create a new Path object for the 'data' subdirectory inside the PROJECT_ROOT.
DATA_PATH = PROJECT_ROOT / "data"


# ==============================================================================
# 2. Quran Script References (Uthmani Text)
# ==============================================================================
# These JSON files contain the canonical Uthmani script used by the qua_sdk.
# The pipeline relies on these exact character sequences to perform mathematical string matching (Dynamic Programming).

# Used by the computational engine for character-level matching and DP alignment.
# Define the path to 'qpc_hafs.json' inside the data folder for computational matching.
QURAN_SCRIPT_PATH_COMPUTE = DATA_PATH / "qpc_hafs.json"

# Used by the presentation layer (if any) to display the beautifully formatted digital khatt script to the end-user.
# Define the path to 'digital_khatt_v2_script.json' inside the data folder for display purposes.
QURAN_SCRIPT_PATH_DISPLAY = DATA_PATH / "digital_khatt_v2_script.json"


# ==============================================================================
# 3. Pipeline Processing Directives
# ==============================================================================
# AUTO_MERGE_GROUP_PREFIX is a tag used by the post-processing engine.
# Often, reciters pause naturally (Waqf) or take a short breath (Sakt), causing the VAD to split 
# what is actually a single logical Ayah into multiple segments. 
# When the DP engine forces these adjacent short segments back together into one block,
# it tags the ID with this prefix so downstream applications know it was an algorithmic merge.
# Assign the string "merge-auto-" to the AUTO_MERGE_GROUP_PREFIX variable.
AUTO_MERGE_GROUP_PREFIX = "merge-auto-"

# AUDIO_CACHE_MAX_ENTRIES controls the memory footprint of the SDK cache.
# When batching multiple audio files, the SDK caches recent segments to speed up repeated queries.
# This value pulls from the system environment variable (defaulting to 32 if not set) 
# to allow users to scale memory usage up or down depending on their hardware.
# Retrieve the 'AUDIO_CACHE_MAX_ENTRIES' environment variable, default to '32', and convert it to an integer.
AUDIO_CACHE_MAX_ENTRIES = int(os.environ.get("AUDIO_CACHE_MAX_ENTRIES", "32"))
