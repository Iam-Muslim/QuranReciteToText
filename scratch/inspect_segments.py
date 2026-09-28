"""
Deep dive: inspect actual VAD segments (start/end) around the طه طه repetition 
and around other known repeated phrases, to see if the second occurrence
falls inside a segment or between segments.
"""
import json, sys

with open("output/raw_transcription.json", encoding="utf-8") as f:
    raw = json.load(f)

pts   = raw.get("phoneme_tokens", [])
pauses = raw.get("pause_intervals", [])

# Reconstruct speech segments from pauses
# pauses = silence intervals; speech segments = everything between them
audio_dur = raw.get("audio_duration_seconds", 0)

seg_starts = [0.0]
seg_ends   = []
for p in pauses:
    seg_ends.append(p["start"])
    seg_starts.append(p["end"])
seg_ends.append(audio_dur)

segments = list(zip(seg_starts, seg_ends))

with open("scratch/segments_report.txt", "w", encoding="utf-8") as out:
    out.write("=" * 70 + "\n")
    out.write("ALL SPEECH SEGMENTS\n")
    out.write("=" * 70 + "\n")
    for i, (s, e) in enumerate(segments):
        # phonemes in this segment
        seg_ph = [p for p in pts if p["start"] >= s - 0.05 and p["end"] <= e + 0.05]
        seq = " ".join(p["phoneme"] for p in seg_ph)
        out.write(f"[{i+1:3d}] {s:8.2f}s - {e:8.2f}s  dur={e-s:.2f}s  ph={len(seg_ph)}\n")
        out.write(f"      {seq[:120]}\n")

    out.write("\n" + "=" * 70 + "\n")
    out.write("FOCUS: طه طه — first 3 segments (opening of surah)\n")
    out.write("=" * 70 + "\n")
    for i, (s, e) in enumerate(segments[:5]):
        seg_ph = [p for p in pts if p["start"] >= s - 0.1 and p["start"] <= e + 0.1]
        seq = " ".join(f"{p['phoneme']}@{p['start']:.2f}" for p in seg_ph)
        out.write(f"[{i+1}] {s:.2f}-{e:.2f}s: {seq}\n")

    # Find segment containing "واصطنعتك لنفسي" x2 (around word 329-331 of 1.txt)
    # These occur around 2/3 through 537 words → ~1250s in 1878s audio
    # Look for phonemes around 1250-1300s
    out.write("\n" + "=" * 70 + "\n")
    out.write("FOCUS: Segment around 1250-1290s (واصطنعتك لنفسي repeat)\n")
    out.write("=" * 70 + "\n")
    for i, (s, e) in enumerate(segments):
        if 1240 <= s <= 1300 or 1240 <= e <= 1300:
            seg_ph = [p for p in pts if p["start"] >= s - 0.1 and p["start"] <= e + 0.1]
            seq = " ".join(f"{p['phoneme']}@{p['start']:.2f}" for p in seg_ph)
            out.write(f"[{i+1}] {s:.2f}-{e:.2f}s: {seq}\n")

    # Look for phoneme density around the repeated منها خلقناكم region
    # ~word 450/537 → ~1580s
    out.write("\n" + "=" * 70 + "\n")
    out.write("FOCUS: Segment around 1570-1640s (منها خلقناكم repeat)\n")
    out.write("=" * 70 + "\n")
    for i, (s, e) in enumerate(segments):
        if 1560 <= s <= 1650 or 1560 <= e <= 1650:
            seg_ph = [p for p in pts if p["start"] >= s - 0.1 and p["start"] <= e + 0.1]
            seq = " ".join(f"{p['phoneme']}@{p['start']:.2f}" for p in seg_ph)
            out.write(f"[{i+1}] {s:.2f}-{e:.2f}s: {seq[:200]}\n")

    # Focus: قد جئناك بآية من ربك repeat — ~word 346-355/537 → ~1210s
    out.write("\n" + "=" * 70 + "\n")
    out.write("FOCUS: Segment around 1200-1240s (قد جئناك بآية من ربك repeat)\n")
    out.write("=" * 70 + "\n")
    for i, (s, e) in enumerate(segments):
        if 1195 <= s <= 1250 or 1195 <= e <= 1250:
            seg_ph = [p for p in pts if p["start"] >= s - 0.1 and p["start"] <= e + 0.1]
            seq = " ".join(f"{p['phoneme']}@{p['start']:.2f}" for p in seg_ph)
            out.write(f"[{i+1}] {s:.2f}-{e:.2f}s: {seq[:200]}\n")

print("Done: scratch/segments_report.txt")
