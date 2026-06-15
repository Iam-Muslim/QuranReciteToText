 <div align="center"> ولقد يسرنا القرآن للذكر فهل من مدكر  </div>
 <div align="center"> ربنا تقبل منا انك انت السميع العليم </div>

# Quran Karim Recitation Auto-Segmenter 

Automatically align raw audio of Quran recitation with the authentic Uthmani text, generating perfectly timestamped subtitles (`qc_subtitles.json`).

##  Features

- **Auto-Surah Identification:** Automatically scans the entire Quran DB to anchor the audio to the exact Surah and Ayah being recited.
- **Repetition Handling:** Natively understands when a reciter repeats a phrase and perfectly maps the timing without breaking the Ayah sequence.
- **Mathematical Interpolation:** If the ASR model completely drops a word, the pipeline mathematically calculates and bridges the silence gap, ensuring a perfect 0-loss subtitle track.

##  Architecture

The `run.py` script executes a highly orchestrated 5-phase pipeline:

1. **Silence-Based Chunking (ffmpeg)**
   Slices the raw audio into manageable chunks by detecting natural pauses, ensuring the neural network doesn't run out of RAM.

2. **Transcription (ONNX FastConformer)**
   Extracts `global_logprobs` (CTC Emission Matrix) and generates a highly accurate raw Arabic transcription of the audio.


3. **Offline Text Search (QuranDB)**
   Uses Levenshtein distances to slide the raw transcription across the entire Quran database, locking into the exact Surahs and Ayahs being recited.

4. **Trellis Forced Alignment (Torchaudio)**
   Uses the Viterbi Trellis algorithm to map frame-level timings to every single raw word. Maps the raw ASR words back to the Canonical Quran text. Employs a robust **Block Interpolator** to mathematically patch any words the AI hallucinated or dropped.

5. **JSON Export & Subtitle**
   Sorts all segments chronologically. Handles complex repetitions (e.g. `[Ayah 1 pass 1] -> [Ayah 1 pass 2]`) and outputs `qc_subtitles.json`.

##  Directory Structure
```text
.
├── QuranKarim/            # Core AI and mathematical processing modules
│   ├── aligner.py         # Torchaudio Trellis matrix alignment
│   ├── audio_features.py  # Log-Mel Spectrogram extraction
│   ├── decoder.py         # CTC Decoding utilities
│   ├── normalizer.py      # Arabic text normalization (Tashkeel stripping)
│   └── quran_db.py        # Database lookup engine
├── data/
│   ├── model.onnx         # Acoustic model weights
│   └── quran.json         # Canonical Uthmani text database
├── outputs/
│   ├── segmented.json     # Word-level timestamps and repetition segments
│   └── qc_subtitles.json  # Final grouped subtitle track
└── run.py                 # Main execution pipeline
```

## Usage

### Standard Execution
```bash
python run.py audio.mp3
```

### Advanced Flags
- `--fast`: Unlocks 100% CPU thread utilization. (By default, the script caps CPU usage to prevent hardware freezing).
- `--split`: Outputs individual `.mp3` slices for every Ayah.
- `--multiple`: Enables dynamic re-anchoring, allowing you to process multiple Surahs in same audio file.

##  Example Output (`qc_subtitles.json`)
```json
{
    "subtitle_index": 1,
    "surah": 2,
    "ayah": 25,
    "is_repetition": false,
    "start": 0.5,
    "end": 4.2,
    "text": "وَبَشِّرِ ٱلَّذِينَ ءَامَنُوا۟",
    "words": [
        {
            "word": "وَبَشِّرِ",
            "start": 0.5,
            "end": 1.2
        },
        ...
    ]
}
```
 **هذا من فضل ربي — الحمد لله** سبحان الله عما يصفون

**Onnx Model - FastConformer ar**  
   [Yazinsai Offline-Tarteel](https://github.com/yazinsai/offline-tarteel) 
