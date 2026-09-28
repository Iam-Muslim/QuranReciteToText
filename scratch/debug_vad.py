import sys
import os
sys.path.insert(0, os.path.abspath('.'))
from src.audio import AudioDecoder
from src.vad import QuranSilenceVAD

audio = AudioDecoder.load_audio_file('1.mp3')
vad = QuranSilenceVAD(sample_rate=16000)

# Intercept bridged_intervals
import src.vad
orig_dual_check = QuranSilenceVAD._detect_silero_dual_check

def intercepted_dual_check(self, audio, session, input_names):
    # let's run original and also check internal variables
    return orig_dual_check(self, audio, session, input_names)

# Let's inspect vad.pause_intervals
segs, pauses, pts = vad.detect_speech_and_pauses(audio)
for p in pauses:
    if 170 <= p.start_sec <= 215:
        print(f"Pause: [{p.start_sec:.3f} - {p.end_sec:.3f}] dur={p.duration_sec:.3f}s")

