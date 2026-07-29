import sys, json
sys.stdout.reconfigure(encoding="utf-8")

ref = json.load(open("C:/Users/redaa/Downloads/original_output.json", encoding="utf-8"))["segments"]
new = json.load(open("output.json", encoding="utf-8"))["segments"]

print(f"Reference segments: {len(ref)}")
print(f"New segments:       {len(new)}")
print()
print(f"{'#':<4} | {'REF (original_output.json)':<30} | {'NEW (output.json)':<30}")
print("-" * 70)

max_len = max(len(ref), len(new))
for i in range(max_len):
    r_str = ""
    if i < len(ref):
        r = ref[i]
        r_str = f"[{r['segment']:2d}] {r.get('ref_from',''):10s} -> {r.get('ref_to',''):10s}"
    n_str = ""
    if i < len(new):
        n = new[i]
        n_str = f"[{n['segment']:2d}] {n.get('ref_from',''):10s} -> {n.get('ref_to',''):10s}"
    print(f"{i+1:<4} | {r_str:<30} | {n_str:<30}")
