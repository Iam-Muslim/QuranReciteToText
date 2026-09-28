import json

with open('output/output.json', 'r', encoding='utf-8') as f:
    out = json.load(f)

ayahs_list = out['surahs'][0].get('ayahs', [])
print(f"Total Ayahs in Surah 20: {len(ayahs_list)}")

# The timestamps provided by the user:
# 23:35 - 23:40 (1415s - 1420s) -> وعنت الوجوه للحي القيوم (Ayah 111)
# 23:55 - 24:15 (1435s - 1455s) -> ومن يعمل من الصالحات (Ayah 112)
# 27:55 - 28:20 (1675s - 1700s) -> افلم يهد لهم (Ayah 128)
# 29:10 - 29:20 (1750s - 1760s) -> ولا تمدن (Ayah 131)
# 29:45 - 29:55 (1785s - 1795s) -> ورزق ربك (Ayah 131)
# 31:00 - 31:05 (1860s - 1865s) -> قل كل متربص (Ayah 135)

target_ayahs = [111, 112, 128, 131, 135]

for a_entry in ayahs_list:
    num = a_entry['ayah']
    if num in target_ayahs:
        print(f"\n=================== AYAH {num} ===================")
        print(f"Text: {a_entry.get('text', '')}")
        reps = a_entry.get('repeated_ranges', [])
        rep_segs = a_entry.get('repeated_segments', [])
        print(f"Repeated ranges: {reps}")
        print(f"Repeated segments count: {len(rep_segs)}")
        segments = a_entry.get('segments', [])
        print(f"Segments in Ayah: {len(segments)}")
        for s_idx, seg in enumerate(segments):
            is_rep = seg.get('is_repetition', False)
            print(f"  Seg {s_idx+1}: [{seg['start']}s - {seg['end']}s] (is_rep={is_rep})")
            print(f"    Raw Text: {seg.get('raw_text', '')}")
            print(f"    Text: {seg.get('text', '')}")

print("\n\n=== CHECKING RAW TRANSCRIPTION AROUND TIMESTAMPS ===")
with open('output/raw_transcription.json', 'r', encoding='utf-8') as f:
    raw = json.load(f)

raw_phonemes = raw.get('phonemes', [])
pauses = raw.get('pause_intervals', [])
print(f"Total raw phonemes: {len(raw_phonemes)}, Total pauses: {len(pauses)}")

windows = [
    ("23:35 - 23:45 (Ayah 111)", 1410.0, 1425.0),
    ("23:50 - 24:20 (Ayah 112)", 1430.0, 1460.0),
    ("27:50 - 28:25 (Ayah 128)", 1670.0, 1705.0),
    ("29:05 - 29:30 (Ayah 131 - ولا تمدن)", 1745.0, 1770.0),
    ("29:40 - 30:05 (Ayah 131 - ورزق ربك)", 1780.0, 1805.0),
    ("30:55 - 31:15 (Ayah 135)", 1855.0, 1875.0),
]

for label, w_s, w_e in windows:
    print(f"\n--- Window: {label} [{w_s}s - {w_e}s] ---")
    p_in_win = [p for p in raw_phonemes if w_s <= p['start'] <= w_e]
    txt = "".join(p['phoneme'] for p in p_in_win)
    print(f"Phonemes ({len(p_in_win)}): {txt[:120]}...")
    pauses_in_win = [p for p in pauses if (w_s <= p['start'] <= w_e or w_s <= p['end'] <= w_e)]
    print(f"Pauses in window ({len(pauses_in_win)}):")
    for pa in pauses_in_win:
        print(f"  Pause: [{pa['start']}s - {pa['end']}s] dur={pa['duration']}s, type={pa.get('type')}")
