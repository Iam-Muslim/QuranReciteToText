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

print("=== VERIFYING 44.mp3 VAD CUTS & REPETITIONS ===")
audio = AudioDecoder.load_audio_file('44.mp3')
sr = 16000
vad = QuranSilenceVAD(
    sample_rate=sr,
    hangover_s=getattr(config, 'VAD_HANGOVER_S', 0.08),
    min_pause_s=getattr(config, 'VAD_MIN_PAUSE_S', 0.20),
    max_pad_s=getattr(config, 'VAD_MAX_PAD_S', 0.25),
)
segs, pauses, pts = vad.detect_speech_and_pauses(audio)
t = ZipformerONNX.get_instance()

print(f"Total VAD segments in 44.mp3: {len(segs)}")
print(f"Total pauses (cuts): {len(pauses)}")

# 1. Transcribe each segment with current architecture
seg_phonemes = []
for i, s in enumerate(segs):
    s_samp = max(0, int(round(s.padded_start_sec * sr)))
    e_samp = min(len(audio), int(round(s.padded_end_sec * sr)))
    feats = t._extract_fbank(audio[s_samp:e_samp])
    lp, ph = t._transcribe_fbank_segment(feats, reset_states=True)
    seg_phonemes.append((s, ph))

# 2. Check every boundary between consecutive segments:
# Ensure no phoneme is cut at the end of seg_i or start of seg_{i+1}
boundary_report = []
for i in range(len(segs) - 1):
    s_curr, ph_curr = seg_phonemes[i]
    s_next, ph_next = seg_phonemes[i + 1]

    # Trailing phonemes of s_curr
    trailing = [p for p in ph_curr if p.start >= (s_curr.duration_sec - 0.40)]
    trailing_str = " ".join(p.phoneme for p in trailing) if trailing else "(none)"

    # Onset phonemes of s_next
    onset = [p for p in ph_next if p.start <= 0.60]
    onset_str = " ".join(p.phoneme for p in onset) if onset else "(none)"

    gap = s_next.raw_start_sec - s_curr.raw_end_sec
    boundary_report.append((i + 1, round(s_curr.raw_end_sec, 2), round(s_next.raw_start_sec, 2), round(gap, 3), trailing_str, onset_str))

print("\n" + "=" * 80)
print("BOUNDARY CHECK: FIRST 15 CUTS (TRAILING & ONSET PHONEMES)")
print("=" * 80)
for b_idx, e_curr, s_nxt, gap, tr, on in boundary_report[:15]:
    print(f"Cut {b_idx:2d} [{e_curr:6.2f}s -> {s_nxt:6.2f}s] (gap={gap:.3f}s):")
    print(f"   End of Seg {b_idx:2d}  trailing: {tr}")
    print(f"   Start of Seg {b_idx+1:2d} onset: {on}")

# 3. Check all repeated Ayahs in output.json for 44.mp3
with open('output/output.json', 'r', encoding='utf-8') as f:
    out = json.load(f)

ayahs = out['surahs'][0]['ayahs']
reps_found = []
for a in ayahs:
    reps = a.get('repeated_ranges', [])
    seg_reps = [s for s in a.get('segments', []) if s.get('is_repetition')]
    if reps or seg_reps:
        reps_found.append((a['ayah'], len(reps), len(seg_reps), [s.get('transcribed_text') for s in seg_reps]))

print("\n" + "=" * 80)
print(f"ALL DETECTED REPETITIONS IN 44.mp3 ({len(reps_found)} Ayahs with repetitions)")
print("=" * 80)
for a_num, n_rng, n_seg, rep_texts in reps_found:
    print(f"\nAyah {a_num}: {n_rng} repeated ranges, {n_seg} repeated segments")
    for txt in rep_texts:
        print(f"   Repeated segment text: '{txt}'")
