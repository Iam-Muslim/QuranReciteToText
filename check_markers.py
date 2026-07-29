import sys, json
sys.stdout.reconfigure(encoding="utf-8")
data = json.load(open("output.json", encoding="utf-8"))
found_markers = 0
for s in data["segments"]:
    for w in s.get("words", []):
        if w.get("word") in ["۞", "۩"] or w.get("word", "").startswith("۞"):
            found_markers += 1
            print(f"Found marker in seg {s['segment']}: {w}")
print(f"Total section/sajdah markers in words array: {found_markers}")
