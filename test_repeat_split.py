import sys, json
sys.stdout.reconfigure(encoding="utf-8")

data = json.load(open("output.json", encoding="utf-8"))
seg = data["segments"][5] # Segment 6 (index 5)

words = seg["words"]

def _ayah_key_and_word(location):
    if not location:
        return None, None
    parts = location.split(":")
    if len(parts) >= 3:
        return f"{parts[0]}:{parts[1]}", int(parts[2])
    elif len(parts) >= 2:
        return f"{parts[0]}:{parts[1]}", None
    return None, None

groups = []
prev_key = None
prev_word_num = None

for w in words:
    key, word_num = _ayah_key_and_word(w.get("location"))
    
    # Check if this word belongs to a new group:
    # 1. Key changed (e.g. 52:5 -> 52:6)
    # 2. Key is the same, but word_num went backward (e.g. 52:7:4 -> 52:7:1 repeat!)
    is_new_group = False
    if not groups:
        is_new_group = True
    elif key != prev_key:
        is_new_group = True
    elif word_num is not None and prev_word_num is not None and word_num <= prev_word_num:
        is_new_group = True # Repeat detected!
        
    if is_new_group:
        groups.append([key, [w]])
    else:
        groups[-1][1].append(w)
        
    prev_key = key
    prev_word_num = word_num

print(f"Total groups created: {len(groups)}")
for g_idx, (g_key, g_words) in enumerate(groups):
    locs = [w.get("location") for w in g_words]
    print(f"  Group {g_idx+1}: key={g_key:6s} | words={len(g_words)} | locs={locs[0]} -> {locs[-1]}")
