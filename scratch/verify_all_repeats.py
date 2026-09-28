import sys
import os
sys.path.insert(0, os.path.abspath('.'))
from src.audio import AudioDecoder
from src.vad import QuranSilenceVAD
from src.transcriber import ZipformerONNX
import config

sys.stdout.reconfigure(encoding='utf-8')

config.ENABLE_IN_LOOP_BLANK_RESET = False

audio = AudioDecoder.load_audio_file('1.mp3')
vad = QuranSilenceVAD(
    sample_rate=16000,
    hangover_s=0.08,
    min_pause_s=0.20,
    max_pad_s=0.25,
)
segs, pauses, pts = vad.detect_speech_and_pauses(audio)
t = ZipformerONNX.get_instance()
sr = 16000

segment_transcripts = []
for s in segs:
    s_samp = int(round(s.padded_start_sec * sr))
    e_samp = int(round(s.padded_end_sec * sr))
    seg_pcm = audio[s_samp:e_samp]
    feats = t._extract_fbank(seg_pcm)
    lp, ph = t._transcribe_fbank_segment(feats, reset_states=True)
    text = ' '.join(p.phoneme for p in ph)
    segment_transcripts.append((s.segment_id, s.padded_start_sec, s.padded_end_sec, text))

# Print first 5 segments
print("=== FIRST 5 SEGMENTS ===")
for sid, t0, t1, text in segment_transcripts[:5]:
    print(f"[{sid:2d}] {t0:5.2f}s-{t1:5.2f}s: {text}")

# Check key repeat segments:
print("\n=== REPEAT REGIONS ===")
for sid, t0, t1, text in segment_transcripts:
    # 1. طه
    if t0 < 15.0:
        if 'طَ' in text or 'قَ' in text:
            print(f"Repeat 1 (طه): Seg {sid:2d} [{t0:5.2f}s-{t1:5.2f}s]: {text[:80]}")
    # 2. ألقها يا موسى
    if 180.0 <= t0 <= 215.0:
        print(f"Repeat 2 (ألقها): Seg {sid:2d} [{t0:5.2f}s-{t1:5.2f}s]: {text[:80]}")
    # 3. واصطنعتك لنفسي
    if 360.0 <= t0 <= 400.0:
        print(f"Repeat 3 (واصطنعتك): Seg {sid:2d} [{t0:5.2f}s-{t1:5.2f}s]: {text[:80]}")
    # 4. قد جئناك
    if 435.0 <= t0 <= 465.0:
        print(f"Repeat 4 (قد جئناك): Seg {sid:2d} [{t0:5.2f}s-{t1:5.2f}s]: {text[:80]}")
    # 5. منها خلقناكم
    if 530.0 <= t0 <= 570.0:
        print(f"Repeat 5 (منها خلقناكم): Seg {sid:2d} [{t0:5.2f}s-{t1:5.2f}s]: {text[:80]}")
