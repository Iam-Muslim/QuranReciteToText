import json
data = json.load(open("C:/Users/redaa/Downloads/original_output.json", encoding="utf-8"))["segments"]
true_segs = [s for s in data if s.get("has_repeated_words") is True]
print(f"Original output.json total segments with has_repeated_words=True: {len(true_segs)}")
for s in true_segs:
    print(f"  Seg {s['segment']}: {s.get('ref_from')} -> {s.get('ref_to')} | {s.get('matched_text')[:50]}")
