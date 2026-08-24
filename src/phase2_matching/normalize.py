"""Text Normalization & Resource Initialization (Phase 2 Matcher).

Builds Quranic ChapterReferences and PhonemeNgramIndex directly from
canonical Tajweed phonemes in data/ordered_quran_phonemes.json.
"""

import json
import re
from pathlib import Path
from collections import defaultdict
from functools import lru_cache
from qua_sdk.domain.chapter_refs import ChapterReference, RefWord, _assemble
from qua_sdk.domain.anchor_index import PhonemeNgramIndex
from qua_sdk.domain.sub_costs import SubCostTable
from qua_sdk.components.matching.lib.specials import SpecialTemplates
from qua_sdk.components.matching.runtimes.sequencer import MatchingResources
from config import DATA_PATH

PHONEMES_JSON_PATH = DATA_PATH / "ordered_quran_phonemes.json"
TOKENS_PATH = DATA_PATH / "onnx" / "tokens.txt"


def normalize_arabic(text: str) -> str:
    """Strips diacritics and normalizes orthography."""
    text = re.sub(r'[\u064B-\u065F\u0670\u06D6-\u06E9\u06EA-\u06ED٠-٩0-9]', '', text)
    text = re.sub(r'[إأآٱ]', 'ا', text)
    text = re.sub(r'[ىي]', 'ي', text)
    text = re.sub(r'ة', 'ه', text)
    return re.sub(r'ـ', '', text)


@lru_cache(maxsize=1)
def get_phoneme_vocab_set() -> set[str]:
    """Returns set of all valid phoneme units from tokens.txt."""
    vocab_set = set()
    if TOKENS_PATH.exists():
        with open(TOKENS_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    tok = line.rsplit(" ", 1)[0]
                    if tok != "<blank>":
                        vocab_set.add(tok)
    return vocab_set


def tokenize_phoneme_string(s: str, vocab_set: set[str] | None = None) -> list[str]:
    """Greedy longest-match tokenizer mapping a phoneme string into Zipformer units."""
    if not s:
        return []
    if vocab_set is None:
        vocab_set = get_phoneme_vocab_set()
    max_len = max((len(k) for k in vocab_set), default=12)
    res = []
    i = 0
    n = len(s)
    while i < n:
        matched = False
        for l in range(min(max_len, n - i), 0, -1):
            sub = s[i:i + l]
            if sub in vocab_set:
                res.append(sub)
                i += l
                matched = True
                break
        if not matched:
            res.append(s[i])
            i += 1
    return res


@lru_cache(maxsize=1)
def get_arabic_resources() -> MatchingResources:
    """Builds and caches MatchingResources (Phoneme N-Gram index & Quran references).

    Cached as a global singleton across the application.
    """
    vocab_set = get_phoneme_vocab_set()

    # Load canonical phoneme database
    with open(PHONEMES_JSON_PATH, "r", encoding="utf-8") as f:
        p_data = json.load(f)

    verses_dict = p_data.get("verses", p_data)

    surah_words: dict[int, list[RefWord]] = defaultdict(list)

    # Sort verse keys numerically: 1:1, 1:2, ... 114:6
    def _parse_vkey(k: str) -> tuple[int, int]:
        parts = k.split(":")
        if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
            return (int(parts[0]), int(parts[1]))
        return (999, 999)

    sorted_vkeys = sorted(
        [k for k in verses_dict.keys() if ":" in k and not k.startswith("_")],
        key=_parse_vkey
    )

    for v_key in sorted_vkeys:
        v_entry = verses_dict[v_key]
        surah, ayah = _parse_vkey(v_key)
        if surah == 999:
            continue

        words_text = v_entry.get("aya_text", "").split()
        words_phonemes_raw = v_entry.get("aya_phonemes_list", [])

        # Fallback if aya_phonemes_list is empty: split aya_phoneme by whitespace
        if not words_phonemes_raw and "aya_phoneme" in v_entry:
            words_phonemes_raw = v_entry["aya_phoneme"].split()

        for word_idx, w_text in enumerate(words_text, start=1):
            ph_str = words_phonemes_raw[word_idx - 1] if word_idx - 1 < len(words_phonemes_raw) else ""
            ph_tokens = tokenize_phoneme_string(ph_str, vocab_set) if ph_str else [w_text]

            surah_words[surah].append(RefWord(
                text=w_text,
                phonemes=ph_tokens,
                surah=surah,
                ayah=ayah,
                word_num=word_idx,
            ))

    chapter_refs = {s: _assemble(s, surah_words[s]) for s in sorted(surah_words)}

    ngram_positions = defaultdict(list)
    total_ngrams = 0
    NGRAM_SIZE = 6

    for surah, ref in chapter_refs.items():
        verse_tokens = defaultdict(list)
        for w in ref.words:
            verse_tokens[w.ayah].extend(w.phonemes)

        for ayah, tokens in verse_tokens.items():
            if len(tokens) < NGRAM_SIZE:
                continue
            for i in range(len(tokens) - NGRAM_SIZE + 1):
                ng = tuple(tokens[i:i + NGRAM_SIZE])
                ngram_positions[ng].append((surah, ayah))
                total_ngrams += 1

    ngram_index = PhonemeNgramIndex(
        ngram_positions=dict(ngram_positions),
        ngram_counts={ng: len(pos) for ng, pos in ngram_positions.items()},
        ngram_size=NGRAM_SIZE,
        total_ngrams=total_ngrams,
    )

    sub_table = SubCostTable(mode="arabic", default=1.0, pairs={})

    basmala_tokens = tokenize_phoneme_string("بِسمِللَااهِررَحمَاانِررَحِۦۦۦۦم", vocab_set)
    istiadha_tokens = tokenize_phoneme_string("ءَعُۥۥذُبِللَااهِمِنَششَيطَاانِرَّجِۦۦۦۦم", vocab_set)
    tahmeed_tokens = tokenize_phoneme_string("سَمِعَللَااهُلِمَندَ", vocab_set)
    combined_tokens = istiadha_tokens + basmala_tokens

    templates = SpecialTemplates(
        mode="arabic",
        special={
            "Basmala": basmala_tokens,
            "Isti'adha": istiadha_tokens,
        },
        transition={"Tahmeed": tahmeed_tokens},
        combined=combined_tokens,
    )

    return MatchingResources(
        mode="arabic",
        chapter_refs=chapter_refs,
        ngram_index=ngram_index,
        sub_table=sub_table,
        templates=templates,
    )
