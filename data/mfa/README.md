---
license: apache-2.0
language:
  - ar
tags:
  - montreal-forced-aligner
  - forced-alignment
  - quran
  - recitation
  - tajweed
  - speech
library_name: montreal-forced-aligner
---

# MFA Acoustic Model for Quranic Recitation (Hafs)

A Montreal Forced Aligner acoustic model purpose-built for **Quranic recitation
in the Hafs riwaya**, with a pronunciation dictionary derived from a
rule-verified phonetic script. Built for phone-level tajweed measurement:
madd durations, ghunna, qalqala, not just word timestamps.

## What makes it different

Generic Arabic aligners fail on recitation: multi-second madd vowels, ghunna
nasals, melismatic (mujawwad) style, and mosque reverb are far outside normal
speech. This model was trained and evaluated specifically against those:

- **Phone set**: derived from the Quran Phonetic Script via
  [quran-transcript](https://github.com/obadx/quran-transcript), re-encoded so
  every articulation is ONE phone (`ا+` = long vowel of any prescribed length,
  vs. the source convention of repeating characters, which is degenerate for
  HMM alignment). 67 symbols; tajweed-bearing segments are single intervals.
- **Pronunciation dictionary**: whole-ayah contextual phonetization (wasl
  forms, cross-word idgham/ikhfa/iqlab), never isolated-word forms, which
  measure 20.5% phone error vs. 1.6% for contextual.
- **Training data (~110 h, style-balanced)**: human-word-count-validated ayah
  clips from QUL reciters, a targeted lazem/mottasel oversample, and 40 h of
  mujawwad cut from a large verified crawl. Balance matters: a 5x larger
  unbalanced corpus *degraded* mujawwad coverage in our ablations.
- **Training config**: silence_probability 0.15, boost_silence 1.0 (defaults
  subsidize the silence model, which then swallows sustained vowels), beams
  40/160 for multi-second phones.

## Measured performance

| Metric | Result |
|---|---|
| Phone-boundary jitter vs. signal landmarks (geminate stop releases, n=533, 4 reciters incl. mujawwad) | **10-20 ms median** |
| Speech uncovered by any phone (murattal, held-out reciters) | **0.0-0.4%** |
| Speech uncovered (mujawwad, Abdul Basit held-out) | 5.0% |
| Madd duration vs. prescription (tempo-normalized, anchored): normal (2) / monfasel (4) | 2.1 / 4.8 |
| Word boundary on a human-labelled mujawwad elongation (58:20) | within ~100 ms |

Notes for measurement use: word-onset comparisons against QUL word timings are
biased: QUL starts are ~245 ms early vs. physical burst landmarks (playback
convention). Trust obstruent-anchored spans; treat boundaries *inside*
sonorant runs as untrustworthy and measure rule segments between obstruent
anchors. Pre-pause madds benefit from an energy/voicing end-trim (breath and
room decay otherwise attach to the final phone).

## Files

| File | Purpose |
|---|---|
| `quran_hafs_acoustic.zip` | MFA acoustic model (train with MFA 3.4) |
| `quran_hafs.dict` | pronunciation dictionary (20,967 entries, contextual) |
| `tokens.txt` | phone symbol table (67 + blank) for CTC integrations |
| `rule_index.jsonl` | per-ayah tajweed rule annotations: 93,430 positions with the governing rule and its prescribed length (`golden_len`); join with alignments to measure tajweed |

## Usage

```bash
mfa align CORPUS_DIR quran_hafs.dict quran_hafs_acoustic.zip OUT_DIR \
  --beam 40 --retry_beam 160
```

Corpus: one wav (16 kHz mono) + one `.lab` per ayah clip, `.lab` containing
the **Uthmani** ayah text (whole words; the dictionary handles phonetization).
Keep all paths ASCII (OpenFST on Windows fails on non-ASCII paths).

## Limitations

- **Hafs only.** The phonetizer supports no other riwaya; aligning Warsh/Qalun
  audio with this model would systematically mislabel exactly the features
  tajweed cares about.
- Mid-ayah waqf is unmodelled (the Uthmani text carries no waqf marks); a
  reciter pausing mid-ayah takes pausal forms the dictionary does not offer.
- Mujawwad residual: ~5% of sung speech (mostly pre-breath decrescendos) is
  attributed to silence; use signal-side end-trims for duration work there.
- One model, deliberately: a mujawwad-specialist ablation *underperformed*
  this balanced model, and MFA performs per-speaker adaptation at align time.

## Provenance

Built by the Quran-Lab effort on a 59,000-hour multi-site crawl of public
recitation audio (verified per-ayah against canonical text before any
training; label source is always the canonical Uthmani text, never ASR
output). Phone representation and rule index from the companion
`quran-phones` package.
