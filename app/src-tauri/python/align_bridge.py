#!/usr/bin/env python3
"""
Alignment Bridge redirector to local_word_timing_segmenter.py (QuranCaption architecture).
"""
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent.absolute()
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import local_word_timing_segmenter

if __name__ == "__main__":
    raise SystemExit(local_word_timing_segmenter.main())
