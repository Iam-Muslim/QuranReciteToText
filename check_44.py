import sys, json
sys.stdout.reconfigure(encoding="utf-8")

orig = json.load(open("C:/Users/redaa/Downloads/original_output.json", encoding="utf-8"))["segments"]
curr = json.load(open("output.json", encoding="utf-8"))["segments"]

print("--- ORIGINAL Ayah 44 (seg 58) & 45 (seg 59) ---")
print(orig[57]["time_from"], "->", orig[57]["time_to"], orig[57]["ref_from"], "->", orig[57]["ref_to"])
print(orig[58]["time_from"], "->", orig[58]["time_to"], orig[58]["ref_from"], "->", orig[58]["ref_to"])

print("\n--- CURRENT Ayah 44 (seg 53) & 45 (seg 54) ---")
print(curr[52]["time_from"], "->", curr[52]["time_to"], curr[52]["ref_from"], "->", curr[52]["ref_to"])
print(curr[53]["time_from"], "->", curr[53]["time_to"], curr[53]["ref_from"], "->", curr[53]["ref_to"])
