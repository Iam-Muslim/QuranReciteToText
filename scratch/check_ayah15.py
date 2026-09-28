import json
import sys

sys.stdout.reconfigure(encoding='utf-8')

with open('output/output.json', 'r', encoding='utf-8') as f:
    out = json.load(f)

for a in out['surahs'][0]['ayahs']:
    if a['ayah'] == 15:
        print("Ayah 15 in output.json:")
        print(f"Start: {a.get('start')}, End: {a.get('end')}")
        print(f"Matched ref: {a.get('matched_ref')}")
        print(f"Repeated ranges: {a.get('repeated_ranges')}")
        print(f"Segments count: {len(a.get('segments', []))}")
        for s in a.get('segments', []):
            print(f"\n  Segment {s.get('segment')} [{s.get('start'):.2f}s - {s.get('end'):.2f}s] (is_repetition={s.get('is_repetition')}):")
            print(f"    Transcribed text: '{s.get('transcribed_text')}'")
            print(f"    Words range: {s.get('words_range')}")
            for w in s.get('words', []):
                print(f"      {w.get('word')} [{w.get('start'):.2f}s - {w.get('end'):.2f}s] (loc={w.get('location')}, score={w.get('score')})")
