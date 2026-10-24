import type { 
  SurahItem, 
  SurahIntro, 
  AyahItem, 
  AlignedWord 
} from '../types/aligner';
import { QURAN_SURAHS } from '../data/quranMetadata';
import { resolveAudioSourceUrl } from './api';
import { cleanPhonemes } from './exporters';

export function isIntroSegment(seg: any): boolean {
  if (!seg) return false;
  const st = String(seg.special_type || '').toLowerCase();
  if (st.includes('basm') || st.includes('isti') || st.includes('takb') || st.includes('tasm')) return true;
  const rf = String(seg.ref_from || '').toLowerCase();
  if (rf.includes('basm') || rf.includes('isti') || rf.includes('takb') || rf.includes('tasm')) return true;
  if (rf.includes(':0:') || rf.startsWith('0:')) return true;
  const rt = String(seg.ref_to || '').toLowerCase();
  if (rt.includes('basm') || rt.includes('isti') || rt.includes('takb') || rt.includes('tasm')) return true;
  if (rt.includes(':0:') || rt.startsWith('0:')) return true;
  if (Array.isArray(seg.words) && seg.words[0]) {
    const loc = String(seg.words[0].location || '');
    if (loc.startsWith('0:') || loc.includes(':0:')) return true;
  }
  return false;
}

export interface IngestResult {
  surahs: SurahItem[];
  firstAddedSurahNum: number | null;
}

/**
 * Ingests QuranCaption timeline segments directly, decomposing breath groups
 * into canonical Surahs and Ayahs, normalizing relative word timestamps into absolute
 * seconds matching the WaveformEditor coordinate space.
 */
export function parseQuranCaptionSegments(
  segments: any[], 
  audioPath?: string, 
  audioUrl?: string
): IngestResult {
  if (!segments || segments.length === 0) {
    return { surahs: [], firstAddedSurahNum: null };
  }

  interface PendingAyahSeg {
    segment: number;
    start: number;
    end: number;
    transcribed_text?: string;
    is_repetition?: boolean;
    words: AlignedWord[];
  }

  const surahsMap = new Map<number, {
    ayahsMap: Map<number, PendingAyahSeg[]>;
    introWords: AlignedWord[];
  }>();

  for (const seg of segments) {
    const segStart = Number(seg.time_from ?? 0);
    const segEnd = Number(seg.time_to ?? Math.max(segStart + 0.1, segStart));
    const isIntro = isIntroSegment(seg);
    const rawWords: any[] = Array.isArray(seg.words) ? seg.words : [];

    if (isIntro) {
      let targetSurah = Number(seg.surah_number || seg.surah || 0);
      if (!targetSurah || targetSurah <= 0) {
        for (const s of segments) {
          const sLoc = s.words?.[0]?.location || s.ref_from;
          if (sLoc && typeof sLoc === 'string' && sLoc.includes(':')) {
            const p = sLoc.split(':').map(Number);
            if (p.length >= 1 && !isNaN(p[0]) && p[0] > 0) {
              targetSurah = p[0];
              break;
            }
          }
        }
      }
      if (!targetSurah || targetSurah <= 0) targetSurah = 1;

      if (!surahsMap.has(targetSurah)) {
        surahsMap.set(targetSurah, { ayahsMap: new Map(), introWords: [] });
      }
      const introEntry = surahsMap.get(targetSurah)!;

      for (const w of rawWords) {
        const wRelStart = Number(w.start ?? 0);
        const wRelEnd = Number(w.end ?? Math.max(wRelStart + 0.1, wRelStart));
        introEntry.introWords.push({
          word: String(w.word || ''),
          location: String(w.location || `0:1:${introEntry.introWords.length + 1}`),
          ref: String(w.ref || w.word || ''),
          start: Number((segStart + wRelStart).toFixed(3)),
          end: Number((segStart + wRelEnd).toFixed(3)),
          score: Number(seg.confidence ?? 1.0),
          is_edited: false,
          is_repetition: !!w.is_repetition,
          phonemes: (w.phonemes || []).map((p: any) => {
            const pStart = p.start !== undefined ? (Number(p.start) < segStart ? segStart + Number(p.start) : Number(p.start)) : Number((segStart + wRelStart).toFixed(3));
            const pEnd = p.end !== undefined ? (Number(p.end) < segStart ? segStart + Number(p.end) : Number(p.end)) : Number((segStart + wRelEnd).toFixed(3));
            return {
              phoneme: String(p.phoneme || ''),
              start: Number(pStart.toFixed(3)),
              end: Number(pEnd.toFixed(3)),
            };
          }),
        });
      }
      continue;
    }

    // Partition words inside this segment by (surah, ayah)
    const groupKeyMap = new Map<string, AlignedWord[]>();

    for (let wIdx = 0; wIdx < rawWords.length; wIdx++) {
      const w = rawWords[wIdx];
      const wRelStart = Number(w.start ?? 0);
      const wRelEnd = Number(w.end ?? Math.max(wRelStart + 0.1, wRelStart));
      const absStart = Number((segStart + wRelStart).toFixed(3));
      const absEnd = Number((segStart + wRelEnd).toFixed(3));

      const locStr = String(w.location || seg.ref_from || "1:1:1");
      const parts = locStr.split(':').map(Number);
      const sNum = (parts.length >= 2 && !isNaN(parts[0]) && parts[0] > 0) ? parts[0] : 1;
      const aNum = (parts.length >= 2 && !isNaN(parts[1]) && parts[1] > 0) ? parts[1] : 1;

      const alignedWord: AlignedWord = {
        word: String(w.word || ''),
        location: locStr,
        ref: String(w.ref || w.word || ''),
        start: absStart,
        end: Math.max(absStart + 0.04, absEnd),
        score: Number(seg.confidence ?? 1.0),
        is_edited: false,
        is_repetition: !!w.is_repetition,
        phonemes: (w.phonemes || []).map((p: any) => {
          const pStart = p.start !== undefined ? (Number(p.start) < segStart ? segStart + Number(p.start) : Number(p.start)) : absStart;
          const pEnd = p.end !== undefined ? (Number(p.end) < segStart ? segStart + Number(p.end) : Number(p.end)) : absEnd;
          return {
            phoneme: String(p.phoneme || ''),
            start: Number(pStart.toFixed(3)),
            end: Number(pEnd.toFixed(3)),
          };
        }),
      };

      const key = `${sNum}:${aNum}`;
      if (!groupKeyMap.has(key)) {
        groupKeyMap.set(key, []);
      }
      groupKeyMap.get(key)!.push(alignedWord);
    }

    if (rawWords.length === 0) {
      const locStr = String(seg.ref_from || "1:1:1");
      const parts = locStr.split(':').map(Number);
      const sNum = (parts.length >= 2 && !isNaN(parts[0]) && parts[0] > 0) ? parts[0] : 1;
      const aNum = (parts.length >= 2 && !isNaN(parts[1]) && parts[1] > 0) ? parts[1] : 1;

      if (!surahsMap.has(sNum)) {
        surahsMap.set(sNum, { ayahsMap: new Map(), introWords: [] });
      }
      const sEntry = surahsMap.get(sNum)!;
      if (!sEntry.ayahsMap.has(aNum)) {
        sEntry.ayahsMap.set(aNum, []);
      }
      sEntry.ayahsMap.get(aNum)!.push({
        segment: seg.segment || (sEntry.ayahsMap.get(aNum)!.length + 1),
        start: segStart,
        end: segEnd,
        transcribed_text: seg.matched_text || '',
        is_repetition: !!seg.is_repetition,
        words: [],
      });
    } else {
      for (const [key, wordGroup] of groupKeyMap.entries()) {
        const [sNum, aNum] = key.split(':').map(Number);
        if (!surahsMap.has(sNum)) {
          surahsMap.set(sNum, { ayahsMap: new Map(), introWords: [] });
        }
        const sEntry = surahsMap.get(sNum)!;
        if (!sEntry.ayahsMap.has(aNum)) {
          sEntry.ayahsMap.set(aNum, []);
        }

        const subStart = wordGroup[0].start;
        const subEnd = wordGroup[wordGroup.length - 1].end;

        sEntry.ayahsMap.get(aNum)!.push({
          segment: seg.segment || (sEntry.ayahsMap.get(aNum)!.length + 1),
          start: subStart,
          end: subEnd,
          transcribed_text: wordGroup.map(w => w.word).join(' '),
          is_repetition: !!seg.is_repetition,
          words: wordGroup,
        });
      }
    }
  }

  if (surahsMap.size === 0) {
    return { surahs: [], firstAddedSurahNum: null };
  }

  // Ensure intro words are never orphaned if assigned to a surah number without ayahs
  const primarySurahKey = Array.from(surahsMap.keys()).find(k => (surahsMap.get(k)?.ayahsMap.size ?? 0) > 0);
  if (primarySurahKey !== undefined) {
    const primaryEntry = surahsMap.get(primarySurahKey)!;
    for (const [k, v] of surahsMap.entries()) {
      if (k !== primarySurahKey && v.ayahsMap.size === 0 && v.introWords.length > 0) {
        primaryEntry.introWords.push(...v.introWords);
        primaryEntry.introWords.sort((a, b) => a.start - b.start);
        v.introWords = [];
      }
    }
  }

  let firstAddedSurahNum: number | null = null;
  const effectiveUrl = resolveAudioSourceUrl({ audio_file: audioPath, audio_url: audioUrl }) || undefined;
  const resultSurahs: SurahItem[] = [];

  for (const [sNum, data] of surahsMap.entries()) {
    if (data.ayahsMap.size === 0 && data.introWords.length === 0) continue;
    const meta = QURAN_SURAHS.find(m => m.surah_number === sNum);
    const ayahsList: AyahItem[] = [];

    for (const [aNum, segList] of data.ayahsMap.entries()) {
      segList.sort((a, b) => a.start - b.start);
      const aStart = segList[0].start;
      const aEnd = segList[segList.length - 1].end;

      ayahsList.push({
        ayah: aNum,
        start: aStart,
        end: aEnd,
        segments: segList.map((s, idx) => ({
          segment: idx + 1,
          start: s.start,
          end: s.end,
          transcribed_text: s.transcribed_text,
          is_repetition: s.is_repetition,
          words: s.words,
        })),
      });
    }

    ayahsList.sort((a, b) => a.ayah - b.ayah);
    const lastAyah = ayahsList[ayahsList.length - 1];
    const totalDur = lastAyah ? Math.ceil(lastAyah.end) + 1.0 : 60.0;

    const introObj: SurahIntro | undefined = data.introWords.length > 0 ? {
      text: data.introWords.map(w => w.word).join(' '),
      start: data.introWords[0].start,
      end: data.introWords[data.introWords.length - 1].end,
      words: data.introWords,
    } : undefined;

    const newSurahObj: SurahItem = {
      surah_number: sNum,
      surah_name_arabic: meta ? meta.surah_name_arabic : `سورة ${sNum}`,
      surah_name_english: meta ? meta.surah_name_english : `Surah ${sNum}`,
      audio_file: audioPath,
      audio_url: effectiveUrl,
      audio_duration_seconds: totalDur,
      status: 'needs_review',
      intro: introObj,
      ayahs: ayahsList,
    };

    resultSurahs.push(newSurahObj);

    if (firstAddedSurahNum === null) {
      firstAddedSurahNum = sNum;
    }
  }

  return {
    surahs: resultSurahs,
    firstAddedSurahNum,
  };
}

/**
 * Ingest Canonical Pipeline Output JSON Directly (Supports Multi-Surah Recitations)
 */
export function parseCanonicalSurahs(
  canonicalOutput: any, 
  audioPath?: string, 
  audioUrl?: string
): IngestResult {
  if (!canonicalOutput) {
    return { surahs: [], firstAddedSurahNum: null };
  }

  const hasSegments = Array.isArray(canonicalOutput.segments) && canonicalOutput.segments.length > 0;

  let surahList: any[] = [];
  if (Array.isArray(canonicalOutput.surahs) && canonicalOutput.surahs.length > 0) {
    surahList = canonicalOutput.surahs.filter((s: any) => s && (s.surah || s.surah_number) && Array.isArray(s.ayahs) && s.ayahs.length > 0);
  } else if (canonicalOutput.surah && Array.isArray(canonicalOutput.ayahs) && canonicalOutput.ayahs.length > 0) {
    surahList = [canonicalOutput];
  } else if (Array.isArray(canonicalOutput) && canonicalOutput.length > 0) {
    surahList = canonicalOutput;
  }

  if (surahList.length === 0 && hasSegments) {
    return parseQuranCaptionSegments(canonicalOutput.segments, audioPath, audioUrl);
  }

  if (surahList.length === 0) {
    return { surahs: [], firstAddedSurahNum: null };
  }

  let firstAddedSurahNum: number | null = null;
  const resultSurahs: SurahItem[] = [];

  for (const sData of surahList) {
    const rawNum = sData.surah ?? sData.surah_number;
    const sNum = typeof rawNum === 'number' ? rawNum : parseInt(rawNum, 10);
    if (isNaN(sNum) || sNum <= 0) continue;

    const meta = QURAN_SURAHS.find(m => m.surah_number === sNum);

    let totalDur = 42.0;
    if (sData.ayahs && sData.ayahs.length > 0) {
      const lastAyah = sData.ayahs[sData.ayahs.length - 1];
      totalDur = Math.ceil(lastAyah.end) + 1.0;
    }

    const effectiveUrl = resolveAudioSourceUrl({ audio_file: audioPath, audio_url: audioUrl }) || undefined;

    let effectiveIntro: SurahIntro | undefined = undefined;
    if (sData.intro && sData.intro.words && sData.intro.words.length > 0) {
      effectiveIntro = {
        text: sData.intro.text || sData.intro.transcribed_text || sData.intro.words.map((w: any) => w.word || w.text || '').join(' '),
        start: sData.intro.start ?? sData.intro.words[0].start,
        end: sData.intro.end ?? sData.intro.words[sData.intro.words.length - 1].end,
        words: sData.intro.words.map((w: any, idx: number) => ({
          word: String(w.word || w.text || ''),
          location: String(w.location || `0:1:${w.w || idx + 1}`),
          ref: String(w.ref || w.word || w.text || ''),
          start: Number(w.start),
          end: Number(w.end),
          score: Number(w.score ?? 1.0),
          is_edited: false,
          phonemes: cleanPhonemes(w.phonemes || []),
        })),
      };
    } else if (hasSegments) {
      const introSegs = canonicalOutput.segments.filter(isIntroSegment);
      if (introSegs.length > 0) {
        const introWords: AlignedWord[] = [];
        for (const seg of introSegs) {
          const segStart = Number(seg.time_from ?? 0);
          for (const w of (seg.words || [])) {
            const wRelStart = Number(w.start ?? 0);
            const wRelEnd = Number(w.end ?? Math.max(wRelStart + 0.1, wRelStart));
            introWords.push({
              word: String(w.word || w.text || ''),
              location: String(w.location || `0:1:${introWords.length + 1}`),
              ref: String(w.ref || w.word || w.text || ''),
              start: Number((segStart + wRelStart).toFixed(3)),
              end: Number((segStart + wRelEnd).toFixed(3)),
              score: Number(seg.confidence ?? 1.0),
              is_edited: false,
              phonemes: cleanPhonemes(w.phonemes || []),
            });
          }
        }
        if (introWords.length > 0) {
          introWords.sort((a, b) => a.start - b.start);
          effectiveIntro = {
            text: introWords.map(w => w.word).join(' '),
            start: introWords[0].start,
            end: introWords[introWords.length - 1].end,
            words: introWords,
          };
        }
      }
    }

    const normalizedAyahs: AyahItem[] = (sData.ayahs || []).map((a: any) => {
      const aNum = a.ayah || a.ayah_number || 1;
      let segs: any[] = [];

      if (Array.isArray(a.segments) && a.segments.length > 0) {
        segs = a.segments.map((seg: any, sIdx: number) => ({
          ...seg,
          segment: seg.segment || sIdx + 1,
          start: Number(seg.start ?? 0),
          end: Number(seg.end ?? 0),
          transcribed_text: seg.transcribed_text || (seg.words || []).map((w: any) => w.word || w.text || '').join(' '),
          words: (seg.words || []).map((w: any, idx: number) => ({
            word: String(w.word || w.text || ''),
            location: String(w.location || `${sNum}:${aNum}:${w.w || idx + 1}`),
            ref: String(w.ref || w.word || w.text || ''),
            start: Number(w.start ?? 0),
            end: Number(w.end ?? 0),
            score: Number(w.score ?? 1.0),
            is_edited: false,
            is_repetition: !!w.is_repetition,
            phonemes: cleanPhonemes(w.phonemes || []),
          })),
        }));
      } else if (Array.isArray(a.phrases) && a.phrases.length > 0 && Array.isArray(a.words)) {
        const allWords = a.words.map((w: any, idx: number) => ({
          word: String(w.word || w.text || ''),
          location: String(w.location || `${sNum}:${aNum}:${w.w || idx + 1}`),
          ref: String(w.ref || w.word || w.text || ''),
          start: Number(w.start ?? 0),
          end: Number(w.end ?? 0),
          score: Number(w.score ?? 1.0),
          is_edited: false,
          is_repetition: !!w.is_repetition,
          phonemes: cleanPhonemes(w.phonemes || []),
        }));
        segs = a.phrases.map((p: any, pIdx: number) => {
          const pStart = Number(p.start ?? 0);
          const pEnd = Number(p.end ?? 0);
          const pWords = allWords.filter((w: AlignedWord) => w.start >= pStart - 0.05 && w.end <= pEnd + 0.05);
          return {
            segment: p.phrase || pIdx + 1,
            start: pStart,
            end: pEnd,
            transcribed_text: pWords.map((w: AlignedWord) => w.word).join(' '),
            words: pWords.length > 0 ? pWords : allWords,
          };
        });
      } else if (Array.isArray(a.words) && a.words.length > 0) {
        const words: AlignedWord[] = a.words.map((w: any, idx: number) => ({
          word: String(w.word || w.text || ''),
          location: String(w.location || `${sNum}:${aNum}:${w.w || idx + 1}`),
          ref: String(w.ref || w.word || w.text || ''),
          start: Number(w.start ?? 0),
          end: Number(w.end ?? 0),
          score: Number(w.score ?? 1.0),
          is_edited: false,
          is_repetition: !!w.is_repetition,
          phonemes: cleanPhonemes(w.phonemes || []),
        }));
        segs = [{
          segment: 1,
          start: a.start ?? words[0]?.start ?? 0,
          end: a.end ?? words[words.length - 1]?.end ?? 0,
          transcribed_text: words.map((w) => w.word).join(' '),
          words,
        }];
      }

      return {
        ...a,
        ayah: aNum,
        start: a.start ?? (segs[0]?.start ?? 0),
        end: a.end ?? (segs[segs.length - 1]?.end ?? 0),
        segments: segs,
      };
    });

    const newSurahObj: SurahItem = {
      surah_number: sNum,
      surah_name_arabic: meta ? meta.surah_name_arabic : `سورة ${sNum}`,
      surah_name_english: meta ? meta.surah_name_english : `Surah ${sNum}`,
      audio_file: audioPath,
      audio_url: effectiveUrl,
      audio_duration_seconds: totalDur,
      status: sData.status || 'verified',
      intro: effectiveIntro,
      ayahs: normalizedAyahs,
    };

    resultSurahs.push(newSurahObj);

    if (firstAddedSurahNum === null) {
      firstAddedSurahNum = sNum;
    }
  }

  return {
    surahs: resultSurahs,
    firstAddedSurahNum,
  };
}
