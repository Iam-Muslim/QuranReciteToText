"""Quran Linguistic & Verse Data Provider.

Provides instant word-level Arabic text lookups and references from
the canonical static Quran database (data/ordered_quran_phonemes.json).
"""

from __future__ import annotations

import re
import json
from pathlib import Path
from typing import Dict, Any, Optional

import sys
_CURRENT_DIR = Path(__file__).parent.resolve()
_APP_DIR = _CURRENT_DIR.parent.resolve()
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

try:
    from .config import DATA_DIR
except (ImportError, ValueError):
    from engine.config import DATA_DIR

_quran_verses_cache: Optional[Dict[str, Any]] = None
_qpc_hafs_cache: Optional[Dict[str, Any]] = None


def get_verse_word_from_location(surah: int, ayah: int, word_idx: int) -> Dict[str, Any]:
    """
    Looks up the Arabic word text for a specific (surah, ayah, word_index) location.
    Word indices are 1-based (e.g., location '1:1:1' -> word_index=1).
    """
    global _quran_verses_cache, _qpc_hafs_cache

    if word_idx < 1:
        return {"success": False, "error": "Word index must be >= 1"}

    loc_key = f"{surah}:{ayah}:{word_idx}"
    target_word = None

    # 1. First try direct QPC Hafs database for exact Medina Uthmani script
    qpc_path = DATA_DIR / "qpc_hafs.json"
    if _qpc_hafs_cache is None and qpc_path.is_file():
        try:
            with open(qpc_path, "r", encoding="utf-8") as f:
                _qpc_hafs_cache = json.load(f)
        except Exception:
            _qpc_hafs_cache = {}

    if _qpc_hafs_cache and loc_key in _qpc_hafs_cache:
        raw_item = _qpc_hafs_cache[loc_key]
        target_word = raw_item.get("text") if isinstance(raw_item, dict) else str(raw_item)

    # 2. Load verse metadata and text context from ordered_quran_phonemes.json
    if _quran_verses_cache is None:
        quran_path = DATA_DIR / "ordered_quran_phonemes.json"
        if quran_path.is_file():
            try:
                with open(quran_path, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                    _quran_verses_cache = raw.get("verses", raw)
            except Exception:
                _quran_verses_cache = {}
        else:
            _quran_verses_cache = {}

    v_key = f"{surah}:{ayah}"
    aya_data = _quran_verses_cache.get(v_key, {}) if _quran_verses_cache else {}
    aya_text = aya_data.get("aya_text", "").strip() if isinstance(aya_data, dict) else ""
    words = [w for w in re.split(r"\s+", aya_text) if w] if aya_text else []
    total_words = len(words)

    # Fallback to splitting aya_text if QPC Hafs didn't have the word
    if not target_word:
        if not words:
            return {"success": False, "error": f"Ayah {v_key} not found"}
        if word_idx > total_words:
            return {
                "success": False,
                "error": f"Ayah {v_key} contains only {total_words} words",
                "total_words": total_words,
            }
        target_word = words[word_idx - 1]

    return {
        "success": True,
        "location": loc_key,
        "word": target_word,
        "total_words": total_words or word_idx,
        "surah": surah,
        "ayah": ayah,
        "word_index": word_idx,
        "ayah_text": aya_text,
    }
