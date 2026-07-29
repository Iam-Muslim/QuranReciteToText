import sys, json
sys.stdout.reconfigure(encoding="utf-8")
data = json.load(open("output.json", encoding="utf-8"))
s = data["segments"][18] # 0-indexed segment 19
print("Segment 19 dict:")
print(json.dumps(s, ensure_ascii=False, indent=2))
