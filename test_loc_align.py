import sys, json
sys.stdout.reconfigure(encoding="utf-8")
from src.core.quran_index import get_quran_index

qi = get_quran_index()
ref_from = "52:23:1"
ref_to = "52:26:2"
indices = qi.ref_to_indices(f"{ref_from}-{ref_to}")
s, e = indices
q_locs = [f"{qi.words[gi].surah}:{qi.words[gi].ayah}:{qi.words[gi].word}" for gi in range(s, e + 1)]
print(f"Quran index returned {len(q_locs)} locations from {s} to {e}")

matched_text = "يَتَنَـٰزَعُونَ فِيهَا كَأْسࣰا لَّا لَغْوࣱ فِيهَا وَلَا تَأْثِيمࣱ ۞ وَيَطُوفُ عَلَيْهِمْ غِلْمَانࣱ لَّهُمْ كَأَنَّهُمْ لُؤْلُؤࣱ مَّكْنُونࣱ وَأَقْبَلَ بَعْضُهُمْ عَلَىٰ بَعْضࣲ يَتَسَآءَلُونَ قَالُوٓا۟ إِنَّا"
ref_words = matched_text.split()
print(f"ref_words count = {len(ref_words)}")

# Alignment:
locs = []
q_idx = 0
for w in ref_words:
    if w in ["۞", "۩"] or w.startswith("۞"):
        locs.append(None)
    elif q_idx < len(q_locs):
        locs.append(q_locs[q_idx])
        q_idx += 1
    else:
        locs.append(None)

print(f"Aligned {len(locs)} locations!")
for w, l in zip(ref_words, locs):
    print(f"  {w:20s} -> {l}")
