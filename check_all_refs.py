import sys, json
sys.stdout.reconfigure(encoding="utf-8")
data = json.load(open("output.json", encoding="utf-8"))
segs = data["segments"]
print(f"Total segments: {len(segs)}")
for s in segs:
    rf = s.get("ref_from", "")
    rt = s.get("ref_to", "")
    print(f"Seg {s['segment']:2d}: {rf:12s} -> {rt:12s} | {s['matched_text'][:40]}")
