import type { SurahItem, AlignerProject } from '../types/aligner';

function formatSrtTime(seconds: number): string {
  const hrs = Math.floor(seconds / 3600);
  const mins = Math.floor((seconds % 3600) / 60);
  const secs = Math.floor(seconds % 60);
  const ms = Math.floor((seconds % 1) * 1000);
  return `${String(hrs).padStart(2, '0')}:${String(mins).padStart(2, '0')}:${String(secs).padStart(2, '0')},${String(ms).padStart(3, '0')}`;
}

function formatVttTime(seconds: number): string {
  const hrs = Math.floor(seconds / 3600);
  const mins = Math.floor((seconds % 3600) / 60);
  const secs = Math.floor(seconds % 60);
  const ms = Math.floor((seconds % 1) * 1000);
  return `${String(hrs).padStart(2, '0')}:${String(mins).padStart(2, '0')}:${String(secs).padStart(2, '0')}.${String(ms).padStart(3, '0')}`;
}

function formatAssTime(seconds: number): string {
  const hrs = Math.floor(seconds / 3600);
  const mins = Math.floor((seconds % 3600) / 60);
  const secs = Math.floor(seconds % 60);
  const cs = Math.floor((seconds % 1) * 100);
  return `${hrs}:${String(mins).padStart(2, '0')}:${String(secs).padStart(2, '0')}.${String(cs).padStart(2, '0')}`;
}

// 1. Export Canonical output.json
export function exportCanonicalJson(surah: SurahItem): string {
  const ayahs = surah.ayahs.map(a => ({
    ayah: a.ayah,
    start: a.start,
    end: a.end,
    matched_ref: a.matched_ref || `${surah.surah_number}:${a.ayah}:1`,
    segments: a.segments.map(s => ({
      segment: s.segment,
      start: s.start,
      end: s.end,
      transcribed_text: s.words.map(w => w.word).join(' '),
      words: s.words.map(w => ({
        word: w.word,
        location: w.location,
        start: w.start,
        end: w.end,
        score: w.score,
        phonemes: w.phonemes || [],
      }))
    }))
  }));

  const outDoc = {
    total_surahs: 1,
    surahs: [
      {
        surah: surah.surah_number,
        surah_name_arabic: surah.surah_name_arabic,
        surah_name_english: surah.surah_name_english,
        ...(surah.intro ? { intro: surah.intro } : {}),
        ayahs,
      }
    ]
  };

  return JSON.stringify(outDoc, null, 2);
}

// 2. Export Full Project Specification (.qproj)
export function exportProjectFile(project: AlignerProject): string {
  return JSON.stringify(project, null, 2);
}

// 3. Export Universal Subtitles (.srt)
export function exportSrt(surah: SurahItem, wordLevel: boolean = false): string {
  const entries: string[] = [];
  let index = 1;

  if (wordLevel) {
    for (const a of surah.ayahs) {
      for (const seg of a.segments) {
        for (const w of seg.words) {
          entries.push(`${index++}\n${formatSrtTime(w.start)} --> ${formatSrtTime(w.end)}\n${w.word}\n`);
        }
      }
    }
  } else {
    for (const a of surah.ayahs) {
      for (const seg of a.segments) {
        const text = seg.words.map(w => w.word).join(' ');
        entries.push(`${index++}\n${formatSrtTime(seg.start)} --> ${formatSrtTime(seg.end)}\n${text} ${a.ayah}\n`);
      }
    }
  }

  return entries.join('\n');
}

// 4. Export Web Video Subtitles (.vtt)
export function exportVtt(surah: SurahItem): string {
  const lines: string[] = ['WEBVTT - Quran Recite Aligner\n'];
  let index = 1;

  for (const a of surah.ayahs) {
    for (const seg of a.segments) {
      const text = seg.words.map(w => w.word).join(' ');
      lines.push(`${index++}\n${formatVttTime(seg.start)} --> ${formatVttTime(seg.end)}\n${text} ${a.ayah}\n`);
    }
  }

  return lines.join('\n');
}

// 5. Export Advanced SubStation Alpha Karaoke (.ass)
export function exportAssKaraoke(surah: SurahItem): string {
  const header = `[Script Info]
Title: Quran Recite Aligner Karaoke - Surah ${surah.surah_name_english}
ScriptType: v4.00+
WrapStyle: 0
ScaledBorderAndShadow: yes
PlayResX: 1920
PlayResY: 1080

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: QuranKaraoke,Amiri Quran,68,&H00FFFFFF,&H0000D7FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,3,2,2,100,100,120,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
`;

  const dialogLines: string[] = [];

  for (const a of surah.ayahs) {
    for (const seg of a.segments) {
      const startStr = formatAssTime(seg.start);
      const endStr = formatAssTime(seg.end);

      // Build \k<centiseconds> word tags
      const karaokeWords = seg.words.map(w => {
        const durationCs = Math.max(1, Math.round((w.end - w.start) * 100));
        return `{\\k${durationCs}}${w.word}`;
      }).join(' ');

      dialogLines.push(`Dialogue: 0,${startStr},${endStr},QuranKaraoke,,0,0,0,,${karaokeWords} ${a.ayah}`);
    }
  }

  return header + dialogLines.join('\n');
}

/**
 * Strips silent letter marker glyphs (small rounded zero U+06DF / U+06E0) for display or export
 * (directly from QuranCaption WbwHelper.ts).
 */
export function stripWbwDisplayMarkers(text: string): string {
  return text.replace(/[۟۠]/g, '');
}

/**
 * Normalizes word boundaries within a segment so word ends strictly meet the next word start
 * and the last word meets segment duration (directly from QuranCaption normalize_word_boundaries).
 */
export function normalizeWordBoundaries<T extends { start: number; end: number }>(words: T[], segmentDuration: number): T[] {
  if (!words || words.length === 0) return words;
  const duration = Math.max(0.001, segmentDuration);
  const starts: number[] = [];
  let prevStart = 0;
  for (let i = 0; i < words.length; i++) {
    const rawStart = i === 0 ? 0 : Math.max(0, words[i].start);
    const s = Math.max(prevStart, Math.min(duration, rawStart));
    starts.push(s);
    prevStart = s;
  }
  return words.map((w, i) => {
    const start = starts[i];
    const end = i < words.length - 1 ? Math.max(start, starts[i + 1]) : duration;
    return {
      ...w,
      start: Number(start.toFixed(3)),
      end: Number(Math.max(start, end).toFixed(3)),
    };
  });
}

// 6. Export QuranCaption JSON format
export function exportQuranCaption(surah: SurahItem): string {
  let segIndex = 1;
  const segments: any[] = [];

  // 1. Export Surah Intro (Isti'adha / Basmalah) if present (QuranCaption compatibility)
  if (surah.intro && surah.intro.words && surah.intro.words.length > 0) {
    const introStart = surah.intro.start ?? surah.intro.words[0].start;
    const introEnd = surah.intro.end ?? surah.intro.words[surah.intro.words.length - 1].end;
    const introDur = Math.max(0.01, introEnd - introStart);

    const relativeWords = surah.intro.words.map(w => ({
      word: w.word,
      location: w.location,
      start: Math.max(0, w.start - introStart),
      end: Math.max(0, w.end - introStart),
      score: w.score,
    }));
    const normWords = normalizeWordBoundaries(relativeWords, introDur);

    segments.push({
      segment: segIndex++,
      time_from: Number(introStart.toFixed(3)),
      time_to: Number(introEnd.toFixed(3)),
      ref_from: surah.intro.words[0]?.location || `${surah.surah_number}:0:1`,
      ref_to: surah.intro.words[surah.intro.words.length - 1]?.location || `${surah.surah_number}:0:1`,
      matched_text: surah.intro.text || surah.intro.words.map(w => w.word).join(' '),
      confidence: Number((surah.intro.words.reduce((sum, w) => sum + w.score, 0) / Math.max(1, surah.intro.words.length)).toFixed(2)),
      words: normWords,
    });
  }

  // 2. Export Surah Ayah Segments
  for (const a of surah.ayahs) {
    for (const seg of a.segments) {
      const segDur = Math.max(0.01, seg.end - seg.start);
      const relativeWords = seg.words.map((w) => ({
        word: w.word,
        location: w.location,
        start: Math.max(0, w.start - seg.start),
        end: Math.max(0, w.end - seg.start),
        score: w.score,
      }));
      const normWords = normalizeWordBoundaries(relativeWords, segDur);

      segments.push({
        segment: segIndex++,
        time_from: Number(seg.start.toFixed(3)),
        time_to: Number(seg.end.toFixed(3)),
        ref_from: seg.words[0]?.location || `${surah.surah_number}:${a.ayah}:1`,
        ref_to: seg.words[seg.words.length - 1]?.location || `${surah.surah_number}:${a.ayah}:1`,
        matched_text: seg.words.map(w => w.word).join(' '),
        confidence: Number((seg.words.reduce((sum, w) => sum + w.score, 0) / Math.max(1, seg.words.length)).toFixed(2)),
        words: normWords,
      });
    }
  }

  return JSON.stringify({ segments }, null, 2);
}

// 7. Browser Download Trigger Utility
export function downloadFile(content: string, filename: string, mimeType: string = 'application/json') {
  const blob = new Blob([content], { type: `${mimeType};charset=utf-8` });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}
