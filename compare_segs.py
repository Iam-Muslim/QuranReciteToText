import json

ref = json.load(open("C:/Users/redaa/Downloads/original_output.json", encoding="utf-8"))
new = json.load(open("output.json", encoding="utf-8"))
ref_segs = ref["segments"]
new_segs = new["segments"]

print(f"Reference: {len(ref_segs)} segments")
print(f"New:       {len(new_segs)} segments")
print()
print("--- First 15 reference segments ---")
for s in ref_segs[:15]:
    print(f"  [{s['segment']:2d}] {s['ref_from']:12s} -> {s['ref_to']:12s} | {s['time_from']:6.2f}s - {s['time_to']:6.2f}s | {s['matched_text'][:40]}")
print()
print("--- First 15 new segments ---")
for s in new_segs[:15]:
    rf = s.get("ref_from","")
    rt = s.get("ref_to","")
    print(f"  [{s['segment']:2d}] {rf:12s} -> {rt:12s} | {s['time_from']:6.2f}s - {s['time_to']:6.2f}s | {s['matched_text'][:40]}")
print()
print("--- All reference refs ---")
for s in ref_segs:
    print(f"  [{s['segment']:2d}] {s['ref_from']:12s} -> {s['ref_to']}")
print()
print("--- All new refs ---")
for s in new_segs:
    rf = s.get("ref_from","")
    rt = s.get("ref_to","")
    print(f"  [{s['segment']:2d}] {rf:12s} -> {rt}")
