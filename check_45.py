import sys, json
sys.stdout.reconfigure(encoding="utf-8")

orig = json.load(open("C:/Users/redaa/Downloads/original_output.json", encoding="utf-8"))["segments"]
curr = json.load(open("output.json", encoding="utf-8"))["segments"]

print("--- ORIGINAL OUTPUT.JSON (Ayah 45) ---")
for s in orig:
    if "52:45" in s.get("ref_from",""):
        print(json.dumps(s, ensure_ascii=False, indent=2))

print("\n--- CURRENT OUTPUT.JSON (Ayah 45) ---")
for s in curr:
    if "52:45" in s.get("ref_from",""):
        print(json.dumps(s, ensure_ascii=False, indent=2))
