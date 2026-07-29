import sys, json
sys.stdout.reconfigure(encoding="utf-8")
data = json.load(open("output.json", encoding="utf-8"))
s = data["segments"][5] # Segment 6
print("Segment 6 dict:")
print(json.dumps(s, ensure_ascii=False, indent=2))
