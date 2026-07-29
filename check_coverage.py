import sys, json
sys.stdout.reconfigure(encoding="utf-8")
from src.core.quran_index import get_quran_index

qi = get_quran_index()
data = json.load(open("output.json", encoding="utf-8"))["segments"]

# Get total words in Surah 52 (At-Tur)
s52_words = [w for w in qi.words if w.surah == 52]
print(f"Surah 52 Total Words in Quran Index: {len(s52_words)} words across 49 Ayahs")

covered = set()
for s in data:
    rf = s.get("ref_from", "")
    rt = s.get("ref_to", "")
    if rf and ":" in rf:
        ref_str = rf if rf == rt else f"{rf}-{rt}"
        idx_range = qi.ref_to_indices(ref_str)
        if idx_range:
            for gi in range(idx_range[0], idx_range[1] + 1):
                covered.add(gi)

s52_indices = set(range(qi.ref_to_indices("52:1:1-52:49:5")[0], qi.ref_to_indices("52:1:1-52:49:5")[1] + 1))
missing = s52_indices - covered

print(f"Total Surah 52 words covered by current output.json: {len(covered)} / {len(s52_indices)}")
if not missing:
    print("SUCCESS: 100% COVERAGE! EVERY SINGLE WORD AND AYAH OF SURAH AT-TUR IS COVERED!")
else:
    print(f"MISSING WORDS ({len(missing)}):")
    for m in sorted(missing):
        w = qi.words[m]
        print(f"  - {w.surah}:{w.ayah}:{w.word} ({w.display_text})")
