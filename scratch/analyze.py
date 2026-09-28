"""
Analysis script - all output written to scratch/full_report.txt (utf-8)
Analyzes:
 1. What phonemes the model transcribed
 2. Where the VAD-detected pauses are
 3. What repeats exist in 1.txt 
 4. Whether those repeats are present or missing in transcription
"""
import json, re, sys

OUT = "scratch/full_report.txt"

def load():
    with open("output/raw_transcription.json", encoding="utf-8") as f:
        raw = json.load(f)
    with open("1.txt", encoding="utf-8") as f:
        ref = f.read()
    return raw, ref

def strip_tashkeel(s):
    return re.sub(r"[\u064B-\u0652\u0670\u0640]", "", s)

def find_repeats_in_ref(ref):
    """Find all consecutive-ish repeated phrases (2-10 words, within 20-word window)."""
    words = ref.split()
    words_c = [strip_tashkeel(w) for w in words]
    repeats = []
    for l in range(10, 1, -1):
        for i in range(len(words_c) - l):
            phrase = tuple(words_c[i:i+l])
            for j in range(i + l, min(len(words_c) - l + 1, i + l + 30)):
                if tuple(words_c[j:j+l]) == phrase:
                    orig1 = " ".join(words[i:i+l])
                    orig2 = " ".join(words[j:j+l])
                    repeats.append({"start1": i, "end1": i+l, "start2": j, "end2": j+l,
                                    "gap_words": j - (i+l), "orig1": orig1, "orig2": orig2, "len": l})
    # Deduplicate: prefer longer matches
    repeats.sort(key=lambda x: -x["len"])
    seen = set()
    deduped = []
    for r in repeats:
        key = (r["start1"], r["start2"])
        dominated = any(
            (d["start1"] <= r["start1"] and d["end1"] >= r["end1"] and
             d["start2"] <= r["start2"] and d["end2"] >= r["end2"])
            for d in deduped
        )
        if not dominated:
            deduped.append(r)
    return deduped

def phoneme_density_around(phonemes, t_start, t_end):
    """How many phonemes are in [t_start, t_end]?"""
    return [p for p in phonemes if p["start"] >= t_start and p["end"] <= t_end]

def main():
    raw, ref = load()
    pts = raw.get("phoneme_tokens", [])
    pauses = raw.get("pause_intervals", [])
    audio_dur = raw.get("audio_duration_seconds", 0)

    # Phoneme sequence as string for search
    ph_seq = "".join(p["phoneme"] for p in pts)

    lines = []
    lines.append("=" * 70)
    lines.append("TRANSCRIPTION STATS")
    lines.append("=" * 70)
    lines.append(f"Audio Duration       : {audio_dur:.1f}s")
    lines.append(f"Total Phoneme Tokens : {len(pts)}")
    lines.append(f"VAD Pause Segments   : {len(pauses)}")
    if pauses:
        durs = [p["end"] - p["start"] for p in pauses]
        lines.append(f"Pause Duration Range : {min(durs):.2f}s - {max(durs):.2f}s  avg={sum(durs)/len(durs):.2f}s")

    lines.append("")
    lines.append("=" * 70)
    lines.append("ALL PAUSE INTERVALS (VAD segments that caused state reset)")
    lines.append("=" * 70)
    for i, p in enumerate(pauses):
        d = p["end"] - p["start"]
        lines.append(f"  [{i+1:3d}] {p['start']:8.2f}s - {p['end']:8.2f}s  dur={d:.3f}s")

    lines.append("")
    lines.append("=" * 70)
    lines.append("PHONEME DENSITY PER 60s WINDOW (detect blank regions)")
    lines.append("=" * 70)
    window = 60.0
    t = 0.0
    while t < audio_dur:
        chunk_ph = phoneme_density_around(pts, t, t + window)
        lines.append(f"  {t:7.1f}s - {t+window:7.1f}s : {len(chunk_ph):4d} phonemes")
        t += window

    lines.append("")
    lines.append("=" * 70)
    lines.append("REPEATED PHRASES IN 1.txt AND THEIR TRANSCRIPTION STATUS")
    lines.append("=" * 70)
    repeats = find_repeats_in_ref(ref)
    lines.append(f"Found {len(repeats)} repeated phrase(s) in reference 1.txt:")
    for r in repeats:
        lines.append(f"\n  PHRASE (len={r['len']} words, gap={r['gap_words']} words):")
        lines.append(f"    Text : {r['orig1']}")
        lines.append(f"    Repeat: {r['orig2']}")

    lines.append("")
    lines.append("=" * 70)
    lines.append("PHONEME SEQUENCE AROUND EACH DETECTED SEGMENT BOUNDARY (pauses)")
    lines.append("=" * 70)
    # Show 10 phonemes before and after each pause
    for i, pause in enumerate(pauses[:50]):  # first 50
        before = [p for p in pts if p["end"] <= pause["start"] and p["end"] >= pause["start"] - 2.0][-5:]
        after  = [p for p in pts if p["start"] >= pause["end"] and p["start"] <= pause["end"] + 2.0][:5]
        d = pause["end"] - pause["start"]
        before_str = " ".join(p["phoneme"] for p in before)
        after_str  = " ".join(p["phoneme"] for p in after)
        lines.append(f"  Pause [{i+1}] {pause['start']:.2f}s-{pause['end']:.2f}s dur={d:.2f}s")
        lines.append(f"    Before: {before_str}")
        lines.append(f"    After : {after_str}")

    lines.append("")
    lines.append("=" * 70)
    lines.append("FIRST 200 PHONEMES (to check opening of audio)")
    lines.append("=" * 70)
    for p in pts[:200]:
        lines.append(f"  {p['start']:7.3f}s : {p['phoneme']}")

    # Write output
    with open(OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"Done. Report written to {OUT}")

main()
