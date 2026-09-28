import sys
import os
sys.path.insert(0, os.path.abspath('.'))
import json
import numpy as np

sys.stdout.reconfigure(encoding='utf-8')

from src.audio import AudioDecoder
from src.vad import QuranSilenceVAD
from src.transcriber import ZipformerONNX
import config

print("Loading audio and running VAD...")
audio = AudioDecoder.load_audio_file('1.mp3')
sr = 16000
vad = QuranSilenceVAD(
    sample_rate=sr,
    hangover_s=getattr(config, 'VAD_HANGOVER_S', 0.08),
    min_pause_s=getattr(config, 'VAD_MIN_PAUSE_S', 0.20),
    max_pad_s=getattr(config, 'VAD_MAX_PAD_S', 0.25),
)
segs, pauses, pts = vad.detect_speech_and_pauses(audio)
t = ZipformerONNX.get_instance()

print(f"Total VAD segments: {len(segs)}, Total pauses: {len(pauses)}")

# Transcribe segments via the segmented pipeline
seg_phonemes_map = []
for i, s in enumerate(segs):
    s_samp = max(0, int(round(s.padded_start_sec * sr)))
    e_samp = min(len(audio), int(round(s.padded_end_sec * sr)))
    feats = t._extract_fbank(audio[s_samp:e_samp])
    lp, ph = t._transcribe_fbank_segment(feats, reset_states=True)
    # Convert local phoneme timestamps to global timestamps
    global_ph = []
    for p in ph:
        if p.start <= (s.duration_sec + 0.40):
            global_ph.append((p.phoneme, round(s.padded_start_sec + p.start, 3), round(s.padded_start_sec + p.end, 3)))
    seg_phonemes_map.append(global_ph)

# Now, test EVERY VAD cut between segment i and segment i+1:
print("\n" + "=" * 80)
print("TESTING EVERY VAD CUT BOUNDARY: CONTINUOUS (NO CUT) VS SEGMENTED")
print("=" * 80)

discrepancies = []
total_boundaries = len(segs) - 1

for i in range(total_boundaries):
    seg_curr = segs[i]
    seg_next = segs[i + 1]

    # Gap between raw speech
    gap_s = seg_next.raw_start_sec - seg_curr.raw_end_sec
    cut_center = (seg_curr.raw_end_sec + seg_next.raw_start_sec) / 2.0

    # Continuous window around the cut: 2.0s before end of seg_curr to 2.0s after start of seg_next
    win_start = max(0.0, seg_curr.raw_end_sec - 1.8)
    win_end = min(len(audio) / sr, seg_next.raw_start_sec + 1.8)

    w_s_samp = int(round(win_start * sr))
    w_e_samp = int(round(win_end * sr))
    cont_feats = t._extract_fbank(audio[w_s_samp:w_e_samp])
    _, cont_ph = t._transcribe_fbank_segment(cont_feats, reset_states=True)

    cont_tokens = []
    for p in cont_ph:
        g_s = round(win_start + p.start, 3)
        g_e = round(win_start + p.end, 3)
        # Only take phonemes that fall within the boundary focus: [seg_curr.raw_end_sec - 1.0, seg_next.raw_start_sec + 1.0]
        if (seg_curr.raw_end_sec - 1.2) <= g_s <= (seg_next.raw_start_sec + 1.2):
            cont_tokens.append((p.phoneme, g_s, g_e))

    # Segmented tokens in the exact same boundary focus
    seg_tokens = []
    for p_tok, g_s, g_e in (seg_phonemes_map[i] + seg_phonemes_map[i + 1]):
        if (seg_curr.raw_end_sec - 1.2) <= g_s <= (seg_next.raw_start_sec + 1.2):
            seg_tokens.append((p_tok, g_s, g_e))

    cont_str = " ".join(t[0] for t in cont_tokens)
    seg_str = " ".join(t[0] for t in seg_tokens)

    # Check match
    is_match = (cont_str == seg_str)
    if not is_match:
        discrepancies.append({
            'boundary': f"Seg {seg_curr.segment_id} -> Seg {seg_next.segment_id}",
            'gap_sec': round(gap_s, 3),
            'cut_time': round(cut_center, 3),
            'continuous': cont_str,
            'segmented': seg_str,
        })

print(f"\nTested {total_boundaries} VAD cut boundaries across the audio.")
print(f"Boundaries with 100% identical phonemes: {total_boundaries - len(discrepancies)} / {total_boundaries}")

if discrepancies:
    print(f"\nDiscrepancies found: {len(discrepancies)}")
    for d in discrepancies[:15]:
        print(f"\n--- Boundary {d['boundary']} (Cut at {d['cut_time']}s, Gap={d['gap_sec']}s) ---")
        print(f"  Continuous (no cut): {d['continuous']}")
        print(f"  Segmented  (VAD cut): {d['segmented']}")
else:
    print("\nPERFECT ZERO MISSED PHONEMES ACROSS ALL VAD CUTS!")
