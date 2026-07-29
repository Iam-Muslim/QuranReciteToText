import sys, json
sys.stdout.reconfigure(encoding="utf-8")
data = json.load(open("output.json", encoding="utf-8"))
s = data["segments"][1] # Segment 2
print("Segment 2 dict:")
print(json.dumps(s, ensure_ascii=False, indent=2))
