import json
import sys

sys.stdout.reconfigure(encoding='utf-8')

with open('output/output.json', 'r', encoding='utf-8') as f:
    out = json.load(f)

ayahs = out['surahs'][0]['ayahs']
print(f'Total Ayahs in output: {len(ayahs)}')
rep_count = 0
for a in ayahs:
    reps = a.get('repeated_ranges', [])
    seg_reps = [s for s in a.get('segments', []) if s.get('is_repetition')]
    if reps or seg_reps:
        rep_count += 1
        print(f"Ayah {a['ayah']} (repetition detected): {len(reps)} repeated ranges, {len(seg_reps)} repeated segments")
        for s in a.get('segments', []):
            is_r = s.get('is_repetition', False)
            print(f"   Seg {s.get('segment')}: [{s.get('start'):.2f}-{s.get('end'):.2f}] (rep={is_r}): '{s.get('transcribed_text')}'")
print(f'\nTotal ayahs with repetitions: {rep_count}')
