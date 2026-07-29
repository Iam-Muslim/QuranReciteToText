import sys, json
sys.stdout.reconfigure(encoding="utf-8")

ref_data = json.load(open("C:/Users/redaa/Downloads/original_output.json", encoding="utf-8"))["segments"]
new_data = json.load(open("output.json", encoding="utf-8"))["segments"]

print(f"=== FULL PIPELINE AUDIT REPORT ===")
print(f"Original output.json total segments : {len(ref_data)}")
print(f"Current output.json total segments  : {len(new_data)}")
print("=" * 80)

# Build map of verse refs in original
ref_by_verse = {}
for idx, s in enumerate(ref_data):
    rf = s.get("ref_from", "")
    rt = s.get("ref_to", "")
    key = f"{rf}-{rt}" if rf else "SPECIAL"
    ref_by_verse.setdefault(key, []).append((idx, s))

new_by_verse = {}
for idx, s in enumerate(new_data):
    rf = s.get("ref_from", "")
    rt = s.get("ref_to", "")
    key = f"{rf}-{rt}" if rf else "SPECIAL"
    new_by_verse.setdefault(key, []).append((idx, s))

print(f"\n--- 1. SEGMENT COMPARISON BY VERSE RANGE ---")
print(f"{'Verse Range':<22} | {'Original Segs':<15} | {'Current Segs':<15} | {'Status'}")
print("-" * 80)

all_keys = list(dict.fromkeys(list(ref_by_verse.keys()) + list(new_by_verse.keys())))

diff_count = 0
for k in all_keys:
    r_list = ref_by_verse.get(k, [])
    n_list = new_by_verse.get(k, [])
    
    r_count = len(r_list)
    n_count = len(n_list)
    
    status = "OK" if r_count == n_count else f"DIFF (Orig:{r_count} vs Curr:{n_count})"
    if r_count != n_count:
        diff_count += 1
        
    print(f"{k:<22} | {r_count:<15} | {n_count:<15} | {status}")

print("\n--- 2. DETAILED AUDIT OF CURRENT OUTPUT.JSON ---")
issues = []
for i, s in enumerate(new_data):
    seg_num = s.get("segment")
    rf = s.get("ref_from", "")
    rt = s.get("ref_to", "")
    words = s.get("words", [])
    mw = s.get("has_missing_words", False)
    text = s.get("matched_text", "")
    
    # Check 1: Empty words array
    if not words and rf != "":
        issues.append(f"Seg {seg_num} ({rf}->{rt}): words array is empty!")
        
    # Check 2: Missing locations on words
    no_loc_words = [w["word"] for w in words if not w.get("location")]
    if no_loc_words:
        issues.append(f"Seg {seg_num} ({rf}->{rt}): {len(no_loc_words)} words missing location: {no_loc_words}")
        
    # Check 3: Non-word markers in words
    markers = [w["word"] for w in words if w.get("word") in ["۞", "۩"]]
    if markers:
        issues.append(f"Seg {seg_num} ({rf}->{rt}): found markers in words array: {markers}")
        
    # Check 4: Unsorted or negative timestamps
    prev_end = 0.0
    for w_idx, w in enumerate(words):
        st = w.get("start")
        et = w.get("end")
        if st is not None and et is not None:
            if st < 0 or et < 0:
                issues.append(f"Seg {seg_num} ({rf}->{rt}) word {w.get('word')}: negative timestamp ({st}, {et})")
            if et < st:
                issues.append(f"Seg {seg_num} ({rf}->{rt}) word {w.get('word')}: end < start ({st}, {et})")

if not issues:
    print("NO QUALITY ISSUES FOUND IN WORDS / LOCATIONS / TIMESTAMPS!")
else:
    print(f"FOUND {len(issues)} ISSUES:")
    for issue in issues:
        print("  - " + issue)
