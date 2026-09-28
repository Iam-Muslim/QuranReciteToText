import json
import sys

sys.stdout.reconfigure(encoding='utf-8')

with open('output/raw_transcription.json', 'r', encoding='utf-8') as f:
    raw = json.load(f)

pts = raw.get('phoneme_tokens', [])
print(f'Total raw phoneme tokens: {len(pts)}')
print('First 25 raw phoneme tokens:')
for p in pts[:25]:
    print(f"  {p['phoneme']} [{p['start']:.2f}s - {p['end']:.2f}s]")

with open('output/output.json', 'r', encoding='utf-8') as f:
    out = json.load(f)

surahs = out.get('surahs', [])
if surahs:
    ayahs = surahs[0].get('ayahs', [])
    print(f'\nTotal ayahs in output.json: {len(ayahs)}')
    for a in ayahs[:5]:
        print(f"Ayah {a.get('ayah_number')}: '{a.get('text', '')}'")
        for w in a.get('words', []):
            print(f"    word: {w.get('word', '')} [{w.get('start', 0):.2f}-{w.get('end', 0):.2f}] phonemes={w.get('phonemes', '')}")

