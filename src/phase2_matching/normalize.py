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


def build_tajweed_sub_costs() -> dict[tuple[str, str], float]:
    """Builds pairwise substitution costs for Tajweed and phonetic variations.

    Assigns low penalties (0.10 - 0.20) to equivalent acoustic realizations
    (Madd lengths, Ghunnah/Ikhfa/Iqlab, Qalqalah, Shaddah geminations, Hamza carriers)
    to prevent excessive Levenshtein distance penalties in qua_sdk.
    """
    pairs: dict[tuple[str, str], float] = {}

    def add_group(group: list[str], cost: float):
        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                pairs[(group[i], group[j])] = cost
                pairs[(group[j], group[i])] = cost

    def add_pairs(a_list: list[str], b_list: list[str], cost: float):
        for a in a_list:
            for b in b_list:
                pairs[(a, b)] = cost
                pairs[(b, a)] = cost

    # Madd length variations (Alif, Waw, Yaa)
    add_group(["ا", "اا", "اااا", "ااااا", "اااااا", "ااۜ"], 0.10)
    add_group(["ۦ", "ۦۦ", "ۦۦۦۦ", "ۦۦۦۦۦ", "ۦۦۦۦۦۦ", "ي", "يي", "ييي", "ييييي"], 0.10)
    add_group(["ۥ", "ۥۥ", "ۥۥۥۥ", "ۥۥۥۥۥ", "ۥۥۥۥۥۥ", "و", "وو", "ووو"], 0.10)

    # Ikhfa / Iqlab / Ghunnah
    add_pairs(["ںںں", "ں", "نؙ", "نۜ"], ["نَ", "نِ", "نُ", "ن", "ننن", "ننننَ", "ننننِ", "ننننُ"], 0.15)
    add_pairs(["۾۾۾", "۾"], ["مَ", "مِ", "مُ", "م", "ممم", "ممممَ", "ممممِ", "ممممُ"], 0.15)
    add_pairs(["ممم", "ممممَ", "ممممِ", "ممممُ"], ["مَ", "مِ", "مُ", "م"], 0.15)
    add_pairs(["ننن", "ننننَ", "ننننِ", "ننننُ"], ["نَ", "نِ", "نُ", "ن"], 0.15)

    # Qalqalah vs plain consonants
    add_pairs(["بڇ", "ببڇ"], ["ب", "بَ", "بِ", "بُ", "ببَ"], 0.10)
    add_pairs(["جڇ", "ججڇ"], ["ج", "جَ", "جِ", "جُ", "ججَ"], 0.10)
    add_pairs(["دڇ", "ددڇ"], ["د", "دَ", "دِ", "دُ", "ددَ"], 0.10)
    add_pairs(["طڇ"], ["ط", "طَ", "طِ", "طُ", "ططَ"], 0.10)
    add_pairs(["قڇ", "ققڇ"], ["ق", "قَ", "قِ", "قُ", "ققَ"], 0.10)

    # Shaddah / Gemination vs single
    add_pairs(["ببَ", "ببُ", "ببِ"], ["بَ", "بُ", "بِ", "ب"], 0.15)
    add_pairs(["تتَ", "تتُ", "تتِ"], ["تَ", "تُ", "تِ", "ت"], 0.15)
    add_pairs(["ثثَ", "ثثُ", "ثثِ"], ["ثَ", "ثُ", "ثِ", "ث"], 0.15)
    add_pairs(["ججَ", "ججُ", "ججِ"], ["جَ", "جُ", "جِ", "ج"], 0.15)
    add_pairs(["ححَ", "ححِ", "حح"], ["حَ", "حِ", "حُ", "ح"], 0.15)
    add_pairs(["خخَ", "خخِ"], ["خَ", "خِ", "خُ", "خ"], 0.15)
    add_pairs(["ددَ", "ددُ", "ددِ"], ["دَ", "دُ", "دِ", "د"], 0.15)
    add_pairs(["ذذَ", "ذذُ", "ذذِ"], ["ذَ", "ذُ", "ذِ", "ذ"], 0.15)
    add_pairs(["ررَ", "ررُ", "ررِ", "رر"], ["رَ", "رُ", "رِ", "ر"], 0.15)
    add_pairs(["ززَ", "ززُ", "ززِ"], ["زَ", "زُ", "زِ", "ز"], 0.15)
    add_pairs(["سسَ", "سسُ", "سسِ", "سس"], ["سَ", "سُ", "سِ", "س"], 0.15)
    add_pairs(["ششَ", "ششُ", "ششِ"], ["شَ", "شُ", "شِ", "ش"], 0.15)
    add_pairs(["صصَ", "صصُ", "صصِ"], ["صَ", "صُ", "صِ", "ص"], 0.15)
    add_pairs(["ضضَ", "ضضُ", "ضضِ"], ["ضَ", "ضُ", "ضِ", "ض"], 0.15)
    add_pairs(["ططَ", "ططُ", "ططِ"], ["طَ", "طُ", "طِ", "ط"], 0.15)
    add_pairs(["ظظَ", "ظظُ", "ظظِ"], ["ظَ", "ظُ", "ظِ", "ظ"], 0.15)
    add_pairs(["ععَ", "ععُ", "ععِ"], ["عَ", "عُ", "عِ", "ع"], 0.15)
    add_pairs(["ففَ", "ففُ", "ففِ", "فف"], ["فَ", "فُ", "فِ", "ف"], 0.15)
    add_pairs(["ققَ", "ققُ", "ققِ"], ["قَ", "قُ", "قِ", "ق"], 0.15)
    add_pairs(["ككَ", "ككُ", "ككِ", "كك"], ["كَ", "كُ", "كِ", "ك"], 0.15)
    add_pairs(["للَ", "للُ", "للِ", "لل", "لۜ"], ["لَ", "لُ", "لِ", "ل"], 0.15)
    add_pairs(["ههَ", "ههُ", "ههِ"], ["هَ", "هُ", "هِ", "ه"], 0.15)
    add_pairs(["ووَ", "ووُ", "ووِ"], ["وَ", "وُ", "وِ", "و"], 0.15)
    add_pairs(["ييَ", "ييُ", "ييِ"], ["يَ", "يُ", "يِ", "ي"], 0.15)

    # Acoustic Consonant Confusion Matrix (from ReciteQuran Acoustic Cost Engine)
    # ت <-> ط
    add_pairs(["تَ", "تُ", "تِ", "ت", "تتَ", "تتُ", "تتِ"], ["طَ", "طُ", "طِ", "ط", "ططَ", "ططُ", "ططِ", "طڇ"], 0.25)
    # ج <-> ز
    add_pairs(["جَ", "جُ", "جِ", "ج", "جڇ", "ججَ"], ["زَ", "زُ", "زِ", "ز", "ززَ"], 0.25)
    # خ <-> غ
    add_pairs(["خَ", "خُ", "خِ", "خ", "خخَ"], ["غَ", "غُ", "غِ", "غ"], 0.25)
    # د <-> ض
    add_pairs(["دَ", "دُ", "دِ", "د", "دڇ", "ددَ", "ددڇ"], ["ضَ", "ضُ", "ضِ", "ض", "ضضَ"], 0.25)
    # ذ <-> ز and ذ <-> ظ
    add_pairs(["ذَ", "ذُ", "ذِ", "ذ", "ذذَ"], ["زَ", "زُ", "زِ", "ز", "ززَ", "ظَ", "ظُ", "ظِ", "ظ", "ظظَ"], 0.25)
    # س <-> ص
    add_pairs(["سَ", "سُ", "سِ", "س", "سسَ", "سس"], ["صَ", "صُ", "صِ", "ص", "صصَ"], 0.25)
    # ق <-> ك
    add_pairs(["قَ", "قُ", "قِ", "ق", "قڇ", "ققَ", "ققڇ"], ["كَ", "كُ", "كِ", "ك", "ككَ"], 0.25)

    # Hamza carriers & special marks
    add_pairs(["ءَ", "ءُ", "ءِ", "ء", "ٲ"], ["ا", "و", "ي"], 0.20)
    add_pairs(["ر۪"], ["رِ", "رَ"], 0.15)
    add_pairs(["لۜ"], ["ل", "لَ"], 0.10)
    add_pairs(["نۜ"], ["ن", "نَ"], 0.10)
    add_pairs(["ااۜ"], ["اا", "ا"], 0.10)

    return pairs



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

    sub_table = SubCostTable(mode="arabic", default=1.0, pairs=build_tajweed_sub_costs())

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
