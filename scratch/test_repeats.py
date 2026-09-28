import sys
import os
sys.path.insert(0, os.path.abspath('.'))
import json

sys.stdout.reconfigure(encoding='utf-8')

with open('output/raw_transcription.json', 'r', encoding='utf-8') as f:
    raw = json.load(f)

pts = raw.get('phoneme_tokens', [])

def get_phonemes_in_range(t0, t1):
    sub = [p for p in pts if t0 <= p['start'] <= t1]
    return ' '.join(p['phoneme'] for p in sub)

# Let's inspect regions around repeats:
# 1. 0 - 15s (طه طه ما أنزلنا)
print("=== Region 1: 0 - 15s (طه طه ما أنزلنا) ===")
print(get_phonemes_in_range(0.0, 15.0))

# 2. 180 - 215s (ألقها يا موسى)
print("\n=== Region 2: 180 - 215s (قال ألقها يا موسى) ===")
print(get_phonemes_in_range(180.0, 215.0))

# 3. Search for واصطنعتك لنفسي
# let's search for 'ص' or 'ط' around 350-450s
print("\n=== Region 3: 360 - 410s ===")
print(get_phonemes_in_range(360.0, 410.0))

# 4. Search for قد جئناك بآية من ربك
print("\n=== Region 4: 435 - 465s ===")
print(get_phonemes_in_range(435.0, 465.0))

# 5. Search for منها خلقناكم
print("\n=== Region 5: 530 - 580s ===")
print(get_phonemes_in_range(530.0, 580.0))

