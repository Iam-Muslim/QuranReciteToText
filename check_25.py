import sys, json
sys.stdout.reconfigure(encoding="utf-8")
data = json.load(open("output.json", encoding="utf-8"))
segs = data["segments"]
print(f"Total segments: {len(segs)}")
for s in segs:
    rf = s.get("ref_from", "")
    rt = s.get("ref_to", "")
    txt = s.get("matched_text", "")
    mw = s.get("has_missing_words", False)
    if "52:25" in rf or "52:25" in rt or "52:24" in rf or "52:24" in rt:
        print(f"Seg {s['segment']}: ref {rf} -> {rt} | mw={mw} | text: {txt}")
        for w in s.get("words", [])[:6]:
            print(f"   word: {w.get('word')} ({w.get('location')}) start={w.get('start')} end={w.get('end')}")
