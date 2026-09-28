import json
import re

# Load 1.txt
with open('1.txt', 'r', encoding='utf-8') as f:
    text_1 = f.read()

# Load raw_transcription.json
with open('output/raw_transcription.json', 'r', encoding='utf-8') as f:
    raw_data = json.load(f)

# Load output.json (the aligned words if any)
with open('output/output.json', 'r', encoding='utf-8') as f:
    out_data = json.load(f)

phonemes = raw_data.get('phoneme_tokens', [])
pauses = raw_data.get('pause_intervals', [])
raw_text = raw_data.get('raw_text', '')

# List of repeated phrases we identified in 1.txt
target_repeats = [
    ("طه طه", ["t", "aa", "h", "aa"]),
    ("قال القها يا موسى", ["q", "aa", "l", "a", "l", "q"]),
    ("واصطنعتك لنفسي", ["w", "a", "s", "t", "a", "n"]),
    ("قد جئناك بآية من ربك", ["q", "a", "d", "j", "i", "n", "aa"]),
    ("منها خلقناكم", ["m", "i", "n", "h", "aa", "kh", "a", "l", "a", "q", "n", "aa", "k", "u", "m"]),
    ("وفيها نعيذكم ومنها نخرجكم تارة أخرى", ["w", "a", "f", "ii", "h", "aa"])
]

# Let's write detailed report to scratch/report.txt with utf-8
with open('scratch/report.txt', 'w', encoding='utf-8') as out:
    out.write("=== RAW TRANSCRIPTION STATS ===\n")
    out.write(f"Audio Duration: {raw_data.get('audio_duration_seconds')} s\n")
    out.write(f"Total Phonemes: {len(phonemes)}\n")
    out.write(f"Total Pauses Detected by VAD: {len(pauses)}\n\n")

    # Let's inspect pause distribution
    durations = [p['end'] - p['start'] for p in pauses]
    if durations:
        out.write(f"Pause Durations: min={min(durations):.3f}s, max={max(durations):.3f}s, avg={sum(durations)/len(durations):.3f}s\n\n")

    # Check how many times target phrases appear in raw_text or phonemes
    out.write("=== CHECKING REPEATS IN RAW TRANSCRIPTION ===\n")
    
    # We can search in phonemes or raw_tokens
    raw_ph_seq = " ".join(p['phoneme'] for p in phonemes)
    
    # Let's look for specific phoneme landmarks
    # 1. t aa h aa
    taha_matches = [i for i, p in enumerate(phonemes) if p['phoneme'] in ('t', 'T') and i+3 < len(phonemes) and phonemes[i+2]['phoneme'] in ('h', 'H')]
    out.write(f"Candidates around Taha: {len(taha_matches)}\n")
    for idx in taha_matches[:10]:
        ctx = " ".join(phonemes[j]['phoneme'] for j in range(max(0, idx-2), min(len(phonemes), idx+10)))
        t = phonemes[idx]['start']
        out.write(f"  t={t:.2f}s: {ctx}\n")

    out.write("\n=== CHECKING SPECIFIC PHONEME SEQUENCES IN PHONEMES ===\n")
    # Search for 'kh a l a q n aa k u m'
    for i in range(len(phonemes)-5):
        sub = [phonemes[i+k]['phoneme'] for k in range(5)]
        if 'kh' in sub and ('l' in sub or 'q' in sub):
            seq = " ".join(phonemes[i+k]['phoneme'] for k in range(min(12, len(phonemes)-i)))
            if 'kh' in seq and 'q' in seq:
                out.write(f"khalaqna match at t={phonemes[i]['start']:.2f}s: {seq}\n")

print("Report generated successfully in scratch/report.txt")
