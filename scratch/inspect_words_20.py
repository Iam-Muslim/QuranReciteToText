import json

with open('output/output.json', 'r', encoding='utf-8') as f:
    out = json.load(f)

for a in out['surahs'][0]['ayahs']:
    if a['ayah'] in [111, 112, 128, 131, 135]:
        print(f"\n=== AYAH {a['ayah']} ===")
        print(f"Overall Ayah timing: {a.get('start')}s - {a.get('end')}s")
        print(f"Repeated ranges: {a.get('repeated_ranges')}")
        words = a.get('words', [])
        print(f"Word count: {len(words)}")
        for idx, w in enumerate(words):
            print(f"  [{idx+1}] {w.get('word')}: {w.get('start')}s - {w.get('end')}s (rep={w.get('is_repetition')})")
        print("\nSegments:")
        for s in a.get('segments', []):
            print(f"  Segment [{s.get('start')}s - {s.get('end')}s] is_rep={s.get('is_repetition')}:")
            for sw in s.get('words', []):
                print(f"     {sw.get('word')}: {sw.get('start')}s - {sw.get('end')}s")
