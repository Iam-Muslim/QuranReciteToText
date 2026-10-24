/**
 * Timings import — turns external word-timing JSON (from any script/tool)
 * into the canonical aligned-surah shape used by the studio.
 *
 * Design goal: accept every common shape comfortably and never lose words.
 *  - Top level: array of ayahs, { surah, ayahs }, { surahs: [...] },
 *    { words: [...] } (flat, words carry an ayah number), or
 *    { segments: [...] } QuranCaption segments.
 *  - Ayah keys:  ayah | ayah_number | verse | n | i
 *  - Word text:  word | text | token | uthmani | qpc_uthmani
 *  - Timing:     start/end | t0/t1 | from/to | times: [s, e]
 *  - Units:      seconds (milliseconds detected automatically and divided)
 */
import type { AlignedWord, PhonemeItem } from '../types/aligner';

export interface TimingImportWarning {
  surah: number;
  message: string;
}

export interface NormalizedTimings {
  surahs: Array<{
    surah: number;
    ayahs: Array<{
      ayah: number;
      start: number;
      end: number;
      segments: Array<{ segment: number; start: number; end: number; words: AlignedWord[] }>;
    }>;
  }>;
  warnings: string[];
  wordCount: number;
}

/* ---------------------------------- helpers ---------------------------------- */

function num(v: unknown): number | undefined {
  if (typeof v === 'number' && isFinite(v)) return v;
  if (typeof v === 'string') {
    const n = parseFloat(v.replace(',', '.'));
    return isFinite(n) ? n : undefined;
  }
  return undefined;
}

function pick(obj: any, keys: string[]): unknown {
  for (const k of keys) {
    if (obj && obj[k] !== undefined && obj[k] !== null && obj[k] !== '') return obj[k];
  }
  return undefined;
}

function parseLocationAyah(loc: unknown): number | undefined {
  if (typeof loc !== 'string') return undefined;
  const n = parseInt((loc.trim().match(/^\d+:(\d+)/) || [])[1] || '', 10);
  return n > 0 ? n : undefined;
}

/** For flat word lists whose only surah hint is the location string "s:a:w". */
function parseLocationSurah(loc: unknown): number | undefined {
  if (typeof loc !== 'string') return undefined;
  const n = parseInt((loc.trim().match(/^(\d+):/) || [])[1] || '', 10);
  return n >= 1 && n <= 114 ? n : undefined;
}

/** Best-effort surah number from a stem like "002", "002 Al-Baqarah", "2". */
export function surahNumberFromStem(stem: string): number | undefined {
  const m = stem.match(/^0*(\d{1,3})(?:[\s_\-.]|$)/);
  if (!m) return undefined;
  const n = parseInt(m[1], 10);
  return n >= 1 && n <= 114 ? n : undefined;
}

function wordStart(w: any): number | undefined {
  const times = w && Array.isArray(w.times) ? w.times : undefined;
  if (times && times.length >= 2) return num(times[0]);
  return num(pick(w, ['start', 't0', 'from', 'time_start', 'begin']));
}

function wordEnd(w: any): number | undefined {
  const times = w && Array.isArray(w.times) ? w.times : undefined;
  if (times && times.length >= 2) return num(times[1]);
  return num(pick(w, ['end', 't1', 'to', 'time_end']));
}

/** Optional per-word phoneme rows: { phoneme, start, end } or [phoneme, start, end] tuples. */
function wordPhonemes(w: any, scale: number): PhonemeItem[] {
  const raw = w && Array.isArray(w.phonemes) ? w.phonemes : undefined;
  if (!raw || raw.length === 0) return [];
  const items: PhonemeItem[] = [];
  for (const p of raw) {
    if (!p) continue;
    if (Array.isArray(p) && p.length >= 3) {
      const pn = String(p[0] || '').trim();
      const ps = num(p[1]);
      const pe = num(p[2]);
      if (pn && ps !== undefined && pe !== undefined) {
        items.push({
          phoneme: pn,
          start: Number((ps * scale).toFixed(3)),
          end: Number((pe * scale).toFixed(3)),
        });
      }
      continue;
    }
    const ps = num(wordStart(p));
    const pe = num(wordEnd(p));
    const pn = typeof p === 'string' ? p : pick(p, ['phoneme', 'p', 'char', 'symbol', 'text']);
    if (pn === undefined || ps === undefined || pe === undefined) continue;
    items.push({
      phoneme: String(pn).trim(),
      start: Number((ps * scale).toFixed(3)),
      end: Number((pe * scale).toFixed(3)),
    });
  }
  return items;
}

/*
 * Word identity — the mushaf reference is the source of truth.
 *
 * A timed word is identified by its POSITION ("surah:ayah:word"), exactly
 * like the aligner output and the studio viewer. Inline text (text / word /
 * token) is an optional extra: when it is absent, the Arabic text is filled
 * automatically from the bundled mushaf (/quran/{id}.json) at the same
 * index — see hydrateWordTextsFromReference().
 */

/** Declared position inside its ayah: "s:a:w" location, or an explicit index field. */
function wordIndexInAyah(w: any): number | undefined {
  const loc = pick(w, ['location', 'loc']);
  if (typeof loc === 'string') {
    const parts = loc.trim().split(':');
    const wi = parseInt(parts[2], 10);
    if (parts.length >= 3 && Number.isInteger(wi) && wi > 0) return wi;
  }
  const n = num(pick(w, ['word_index', 'index', 'i', 'w']));
  return n !== undefined && Number.isInteger(n) && n > 0 ? n : undefined;
}

function wordText(w: any): string | undefined {
  const t = pick(w, ['word', 'text', 'token', 'uthmani', 'qpc_uthmani', 'uthmani_text']);
  return t !== undefined ? String(t) : undefined;
}

/* ------------------------------- normalization ------------------------------- */

/**
 * @param data        parsed JSON (any shape)
 * @param audioDurSec duration of the paired audio in seconds (if known) — used
 *                    to detect millisecond units robustly.
 * @param stemHint    file name stem, used to infer the surah number when the
 *                    JSON itself doesn't provide one.
 */
export function normalizeTimedJson(data: any, audioDurSec?: number, stemHint?: string): NormalizedTimings {
  const warnings: string[] = [];
  const out: NormalizedTimings = { surahs: [], warnings, wordCount: 0 };

  if (!data || typeof data !== 'object') {
    throw new Error('The JSON file is not a JSON object or array.');
  }

  // Collect raw surah-shaped buckets: { surah_number, ayahs[] } entries.
  type RawAyah = { ayah: number | undefined; words: any[] };
  type RawSurah = { surah: number | undefined; ayahs: RawAyah[]; intro?: any };
  const rawSurahs: RawSurah[] = [];

  const pushWordsInto = (bucket: RawAyah[], key: number | undefined, words: any[]) => {
    let entry = bucket.find(a => a.ayah === key);
    if (!entry) {
      entry = { ayah: key, words: [] };
      bucket.push(entry);
    }
    entry.words.push(...words);
  };

  const trySurahBucket = (obj: any): boolean => {
    const ayahs = pick(obj, ['ayahs', 'verses']);
    if (!Array.isArray(ayahs) || ayahs.length === 0) return false;
    const sNum = num(pick(obj, ['surah', 'surah_number', 'sura', 'surah_no', 's']));
    const bucket: RawAyah[] = [];
    for (const a of ayahs) {
      if (!a || typeof a !== 'object') continue;
      const aNum = num(pick(a, ['ayah', 'ayah_number', 'verse', 'n', 'i']));
      let words: any[] = [];
      const direct = pick(a, ['words', 'tokens']);
      const segs = pick(a, ['segments', 'phrases']);
      if (Array.isArray(direct)) {
        words = direct;
      } else if (Array.isArray(segs)) {
        for (const s of segs) {
          const sw = pick(s, ['words', 'tokens']);
          if (Array.isArray(sw)) words.push(...sw);
        }
      }
      if (words.length > 0) pushWordsInto(bucket, aNum, words);
    }
    if (bucket.length === 0) return false;
    const introObj = pick(obj, ['intro', 'basmala', 'bismillah']);
    rawSurahs.push({ surah: sNum, ayahs: bucket, intro: introObj });
    return true;
  };

  if (Array.isArray(data)) {
    // Array of ayah objects, or array of surah objects, or flat words.
    let asSurah = false;
    for (const item of data) {
      if (item && typeof item === 'object' && Array.isArray(pick(item, ['ayahs', 'verses']))) {
        if (trySurahBucket(item)) { asSurah = true; continue; }
      }
    }
    if (!asSurah) {
      const isAyahList = data.some(item => item && typeof item === 'object' && Array.isArray(pick(item, ['words', 'tokens', 'segments', 'phrases'])));
      if (isAyahList) {
        const bucket: RawAyah[] = [];
        let locSurah: number | undefined;
        for (const a of data) {
          if (!a || typeof a !== 'object') continue;
          const aNum = num(pick(a, ['ayah', 'ayah_number', 'verse', 'n', 'i']));
          locSurah = num(pick(a, ['surah', 'surah_number'])) ?? locSurah;
          let words: any[] = [];
          const direct = pick(a, ['words', 'tokens']);
          const segs = pick(a, ['segments', 'phrases']);
          if (Array.isArray(direct)) {
            words = direct;
          } else if (Array.isArray(segs)) {
            for (const s of segs) {
              const sw = pick(s, ['words', 'tokens']);
              if (Array.isArray(sw)) words.push(...sw);
            }
          }
          if (words.length > 0) {
            pushWordsInto(bucket, aNum, words);
          }
        }
        if (bucket.length > 0) {
          rawSurahs.push({ surah: locSurah, ayahs: bucket });
          asSurah = true;
        }
      }
    }
    if (!asSurah) {
      // Flat word list (with optional ayah on each word)
      const bucket: RawAyah[] = [];
      let locSurah: number | undefined;
      for (const w of data) {
        if (!w || typeof w !== 'object') continue;
        locSurah = parseLocationSurah(pick(w, ['location', 'loc'])) ?? locSurah;
        const aNum = num(pick(w, ['ayah', 'ayah_number', 'verse', 'n'])) ?? parseLocationAyah(pick(w, ['location', 'loc']));
        pushWordsInto(bucket, aNum, [w]);
      }
      if (bucket.length === 0) throw new Error('No word entries were found inside the array.');
      rawSurahs.push({ surah: locSurah, ayahs: bucket });
    }
  } else if (trySurahBucket(data)) {
    // { surah, ayahs: [...] }
  } else if (Array.isArray(data.surahs)) {
    for (const s of data.surahs) {
      if (s && typeof s === 'object') trySurahBucket(s);
    }
  } else if (Array.isArray(data.words) || Array.isArray(data.tokens)) {
    const bucket: RawAyah[] = [];
    let locSurah: number | undefined;
    for (const w of (data.words || data.tokens)) {
      if (!w || typeof w !== 'object') continue;
      locSurah = parseLocationSurah(pick(w, ['location', 'loc'])) ?? locSurah;
      const aNum = num(pick(w, ['ayah', 'ayah_number', 'verse', 'n'])) ?? parseLocationAyah(pick(w, ['location', 'loc'])) ?? num(pick(data, ['ayah', 'verse']));
      pushWordsInto(bucket, aNum, [w]);
    }
    if (bucket.length === 0) throw new Error('The "words" array is empty.');
    rawSurahs.push({ surah: num(pick(data, ['surah', 'surah_number', 'sura'])) ?? locSurah, ayahs: bucket });
  } else {
    throw new Error(
      'Recognized shapes: { surah, ayahs } · { surahs: [...] } · [ ayah, ... ] · { words: [...] } · { segments: [...] }. ' +
      'See the format guide inside the import dialog.'
    );
  }

  if (rawSurahs.length === 0) {
    throw new Error('No timed verses were found in this JSON.');
  }

  // ---- unit detection: ms vs seconds ---------------------------------------
  let maxEnd = 0;
  for (const rs of rawSurahs) {
    for (const ra of rs.ayahs) {
      for (const w of ra.words) {
        const e = wordEnd(w);
        if (e !== undefined && e > maxEnd) maxEnd = e;
      }
    }
  }
  let scale = 1;
  if (audioDurSec && audioDurSec > 0 && maxEnd > audioDurSec * 1.55) scale = 0.001;
  else if (!audioDurSec && maxEnd > 1800) scale = 0.001; // no audio duration: heuristic
  if (scale < 1) warnings.push('Milliseconds detected — timings were converted to seconds.');

  // ---- build canonical output ----------------------------------------------
  for (const rs of rawSurahs) {
    let sNum = rs.surah ?? surahNumberFromStem(String(stemHint || ''));
    if (sNum === undefined) {
      throw new Error('The surah number is missing. Add a "surah" field (1–114) or name the file like "002".');
    }
    if (sNum < 1 || sNum > 114) throw new Error(`Surah number ${sNum} is out of range (1–114).`);

    const ayahsOut: NormalizedTimings['surahs'][0]['ayahs'] = [];
    // sort ayah buckets by their ayah number (undefined sorts last)
    rs.ayahs.sort((a, b) => {
      if (a.ayah === undefined) return 1;
      if (b.ayah === undefined) return -1;
      return a.ayah - b.ayah;
    });

    let fallbackAyah = 0;
    for (const ra of rs.ayahs) {
      let aNum = ra.ayah ?? 0;
      if (aNum <= 0) {
        fallbackAyah += 1;
        aNum = fallbackAyah;
        warnings.push(`A word group had no ayah number — it was placed in ayah ${aNum}.`);
      }
      const words: AlignedWord[] = [];
      for (const w of ra.words) {
        const st = num(wordStart(w));
        const en = num(wordEnd(w)) ?? (st !== undefined ? st : undefined);
        const text = wordText(w);
        if (st === undefined || en === undefined) continue;
        if (text !== undefined && !text.trim()) continue; // present but empty
        const declaredIdx = wordIndexInAyah(w);
        // A word is identified by its position: the declared "surah:ayah:word"
        // index, otherwise its order inside this ayah's word list. Inline text
        // is optional — the mushaf hydrate step fills it in by position.
        const segStart = st * scale;
        const segEnd = en * scale;
        const phonemes = wordPhonemes(w, scale);
        const aw: AlignedWord = {
          // Empty when only the position was given — the mushaf hydrate
          // step fills it in before the word reaches the studio.
          word: text ?? '',
          location: `${sNum}:${aNum}:${declaredIdx || words.length + 1}`,
          ref: String(pick(w, ['ref']) ?? text ?? ''),
          start: Number(segStart.toFixed(3)),
          end: Number(Math.max(segEnd, segStart + 0.01).toFixed(3)),
          score: num(pick(w, ['score', 'confidence'])) ?? 1.0,
          is_edited: false,
          is_repetition: !!w.is_repetition,
          phonemes,
        };
        (aw as any)._wIndex = declaredIdx;
        words.push(aw);
      }
      if (words.length === 0) continue;
      words.sort((a, b) => a.start - b.start);
      // Preserve declared word index if provided, otherwise sequential
      words.forEach((w, i) => { 
        const wi = (w as any)._wIndex || (i + 1);
        w.location = `${sNum}:${aNum}:${wi}`; 
      });
      const seg = {
        segment: 1,
        start: words[0].start,
        end: words[words.length - 1].end,
        words,
      };
      ayahsOut.push({ ayah: aNum, start: seg.start, end: seg.end, segments: [seg] });
      out.wordCount += words.length;
    }

    if (ayahsOut.length === 0) {
      throw new Error(`Surah ${sNum}: no timed words were found — every word needs start and end times.`);
    }
    ayahsOut.sort((a, b) => a.ayah - b.ayah);

    let introOut: any;
    const introObj = rs.intro as any;
    if (introObj && typeof introObj === 'object') {
      const iw: AlignedWord[] = [];
      const iWords = introObj.words;
      if (Array.isArray(iWords)) {
        for (const w of iWords) {
          const st = num(wordStart(w)), en = num(wordEnd(w)), t = wordText(w);
          if (st === undefined || en === undefined || !t) continue;
          iw.push({
            word: t,
            location: `${sNum}:0:${iw.length + 1}`,
            ref: t,
            start: Number((st * scale).toFixed(3)),
            end: Number((en * scale).toFixed(3)),
            score: 1.0,
            is_edited: false,
            phonemes: wordPhonemes(w, scale),
          });
        }
      }
      if (iw.length > 0) {
        introOut = {
          text: iw.map(w => w.word).join(' '),
          start: iw[0].start,
          end: iw[iw.length - 1].end,
          words: iw,
        };
      }
    }

    out.surahs.push({ surah: sNum, ayahs: ayahsOut });
    // attach intro through the canonical slot the store reads (sData.intro)
    if (introOut) (out.surahs[out.surahs.length - 1] as any).intro = introOut;
  }

  return out;
}

/* --------------------------------- reference -------------------------------- */

/**
 * Fill in word text from the bundled mushaf for entries that were identified
 * only by their position ("surah:ayah:word"). The aligner output is
 * position-based — the viewer matches words by location, and the Arabic text
 * lives in /quran/{id}.json at the same index.
 *
 * - Word index: the declared "s:a:w" location, else the word's ordinal order
 *   inside its ayah (1-based).
 * - Words that match no mushaf entry are reported (never silently dropped).
 */
export async function hydrateWordTextsFromReference(normalized: NormalizedTimings): Promise<string[]> {
  const warnings: string[] = [];
  for (const s of normalized.surahs) {
    const pending = s.ayahs.flatMap(a => a.segments.flatMap(sg => sg.words))
      .filter(w => !String(w.word || '').trim());
    if (pending.length === 0) continue;

    let ref: Record<string, { w?: any[] }> | null = null;
    try {
      const res = await fetch(`/quran/${s.surah}.json`);
      if (res.ok) ref = await res.json();
    } catch { ref = null; }

    const prefix = `Surah ${s.surah}: `;
    if (!ref) {
      warnings.push(`${prefix}${pending.length} word(s) had no text and the mushaf reference is not available here — add a "text" field for them.`);
      continue;
    }

    let resolved = 0;
    let missing = 0;
    for (const a of s.ayahs) {
      const refAyah = ref[String(a.ayah)];
      const refWords = refAyah && Array.isArray(refAyah.w) ? refAyah.w : null;
      for (const sg of a.segments) {
        sg.words.forEach((w, ord) => {
          if (String(w.word || '').trim()) return;
          const anyW = w as any;
          const idx = Number.isInteger(anyW._wIndex) ? anyW._wIndex : ord + 1;
          const rw = refWords && refWords[idx - 1];
          const text = rw ? String(pick(rw, ['c', 'i', 'd', 'word', 'text']) ?? '') : '';
          delete anyW._wIndex; // runtime-only helper — never stored in the project
          if (text.trim()) {
            w.word = text;
            resolved++;
          } else {
            missing++;
          }
        });
      }
    }

    if (resolved > 0) {
      warnings.push(`${prefix}${resolved} word(s) had no text — filled from the bundled mushaf by position.`);
    }
    if (missing > 0) {
      warnings.push(`${prefix}${missing} word(s) matched no mushaf entry. Check positions: they must be whole 1-based word indexes like "surah:ayah:word".`);
    }
  }
  return warnings;
}

/**
 * Sanity-check imported timings against the offline mushaf reference
 * (/quran/{id}.json — bundled, works without any backend):
 *  - flags ayah numbers that don't exist in the reference surah
 *  - warns when the word count differs from the reference ayah
 *    (typical when an external script's output is mis-indexed)
 */
export async function validateAgainstReference(normalized: NormalizedTimings): Promise<string[]> {
  const warnings: string[] = [];
  for (const s of normalized.surahs) {
    try {
      const res = await fetch(`/quran/${s.surah}.json`);
      if (!res.ok) continue;
      const data = (await res.json()) as Record<string, { w?: unknown[] }>;
      const refAyahs = Object.keys(data).map(Number).filter(n => n > 0);
      if (refAyahs.length === 0) continue;
      const maxRef = Math.max(...refAyahs);
      for (const a of s.ayahs) {
        if (a.ayah > maxRef) {
          warnings.push(
            `Surah ${s.surah}: ayah ${a.ayah} does not exist in the mushaf (reference has ${maxRef} ayahs).`
          );
          continue;
        }
        const ref = data[String(a.ayah)];
        if (!ref || !Array.isArray(ref.w)) continue;
        const imported = a.segments.reduce((n, sg) => n + sg.words.length, 0);
        if (imported > 0 && imported !== ref.w.length) {
          warnings.push(
            `Surah ${s.surah}:${a.ayah}: imported ${imported} word(s), the mushaf has ${ref.w.length}. Check the source script.`
          );
        }
      }
    } catch {
      // Reference unavailable — skip silently; import still proceeds.
    }
  }
  return warnings;
}

/* --------------------------------- examples --------------------------------- */

export const EXAMPLE_TIMINGS_JSON = {
  surah: 1,
  ayahs: [
    {
      ayah: 1,
      words: [
        // Identified by position "surah:ayah:word" — the Arabic text is
        // filled automatically from the bundled mushaf at the same index.
        {
          location: '1:1:1',
          start: 0.12,
          end: 0.98,
          phonemes: [
            { phoneme: 'ب', start: 0.12, end: 0.31 },
            { phoneme: 'س', start: 0.31, end: 0.58 },
            { phoneme: 'م', start: 0.58, end: 0.98 }
          ]
        },
        { location: '1:1:2', start: 0.98, end: 1.86 },
        { location: '1:1:3', start: 1.86, end: 3.02 },
        { location: '1:1:4', start: 3.02, end: 4.1 }
      ]
    },
    {
      ayah: 2,
      words: [
        { location: '1:2:1', start: 6.0, end: 7.1 },
        { location: '1:2:2', start: 7.1, end: 7.85 },
        { location: '1:2:3', start: 7.85, end: 8.5 },
        { location: '1:2:4', start: 8.5, end: 10.2 }
      ]
    }
  ]
};

export const EXAMPLE_TIMINGS_STRING = JSON.stringify(EXAMPLE_TIMINGS_JSON, null, 2);

export const TIMING_RULES: string[] = [
  'Words are identified by their position: "location": "surah:ayah:word". The Arabic text is filled in automatically from the bundled mushaf.',
  'You can also give each word its text directly ("text" or "word") — then the position is optional.',
  'Every word needs a start and an end.',
  'phonemes is optional: leave it out or give each one its start and end.',
  'Times are in seconds. Milliseconds are detected and converted automatically.',
  'Each ayah needs an ayah number (1, 2, 3 …) so words land on the right verse.',
  'Batch import: audio and JSON must share the same file name (002.mp3 + 002.json).',
  'Audio is optional — import the JSON now, drop the audio on the timeline later.',
  'A portable .qproj exported by this app opens straight from the Projects hub — timings and audio travel inside it.',
];
