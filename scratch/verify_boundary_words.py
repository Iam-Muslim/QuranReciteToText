import sys
import os
sys.path.insert(0, os.path.abspath('.'))
import json

sys.stdout.reconfigure(encoding='utf-8')

with open('output/output.json', 'r', encoding='utf-8') as f:
    out = json.load(f)

ayahs = out['surahs'][0]['ayahs']

total_words = 0
matched_words = 0
word_list = []

for a in ayahs:
    for s in a.get('segments', []):
        for w in s.get('words', []):
            total_words += 1
            word_list.append((w.get('location'), w.get('word'), w.get('ref'), w.get('score'), w.get('start'), w.get('end')))

print(f"Total aligned words in output.json: {total_words}")
scores = [w[3] for w in word_list if w[3] is not None]
perfect = [w for w in word_list if w[3] is not None and w[3] >= 0.85]
print(f"Words with high match score (>=0.85): {len(perfect)} / {len(word_list)} ({len(perfect)/len(word_list)*100:.1f}%)")
print(f"Average word match score: {sum(scores)/len(scores):.3f}")

# Check words at segment boundaries
print("\nInspecting first & last words of segments to verify no truncation:")
for a in ayahs[:10]:
    for s in a.get('segments', []):
        words = s.get('words', [])
        if words:
            first_w = words[0]
            last_w = words[-1]
            print(f"  Ayah {a['ayah']} Seg {s['segment']}: first='{first_w['word']}' [{first_w['start']:.2f}s] last='{last_w['word']}' [{last_w['end']:.2f}s]")
