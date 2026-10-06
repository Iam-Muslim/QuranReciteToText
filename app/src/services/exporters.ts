import type { SurahItem, AlignerProject } from '../types/aligner';
import JSZip from 'jszip';

export type ExportFormatId = 'json' | 'qproj' | 'srt' | 'vtt' | 'ass' | 'qurancaption' | 'csv' | 'premiere';

/**
 * Sanitizes project or surah names for file systems (from QuranCaption BatchExportService.ts).
 */
export function sanitizeBatchExportFileName(name: string): string {
  let safeName = '';
  for (const character of name) {
    safeName += character.charCodeAt(0) <= 31 || '<>:"/\\|?*'.includes(character) ? '_' : character;
  }
  const sanitized = safeName.replace(/[. ]+$/g, '').trim();
  if (!sanitized) return 'project';
  return /^(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\.|$)/i.test(sanitized)
    ? `_${sanitized}`
    : sanitized;
}

function formatSrtTime(seconds: number): string {
  const s = Math.max(0, seconds);
  const hrs = Math.floor(s / 3600);
  const mins = Math.floor((s % 3600) / 60);
  const secs = Math.floor(s % 60);
  const ms = Math.floor((s % 1) * 1000);
  return `${String(hrs).padStart(2, '0')}:${String(mins).padStart(2, '0')}:${String(secs).padStart(2, '0')},${String(ms).padStart(3, '0')}`;
}

function formatVttTime(seconds: number): string {
  const s = Math.max(0, seconds);
  const hrs = Math.floor(s / 3600);
  const mins = Math.floor((s % 3600) / 60);
  const secs = Math.floor(s % 60);
  const ms = Math.floor((s % 1) * 1000);
  return `${String(hrs).padStart(2, '0')}:${String(mins).padStart(2, '0')}:${String(secs).padStart(2, '0')}.${String(ms).padStart(3, '0')}`;
}

function formatAssTime(seconds: number): string {
  const s = Math.max(0, seconds);
  const hrs = Math.floor(s / 3600);
  const mins = Math.floor((s % 3600) / 60);
  const secs = Math.floor(s % 60);
  const cs = Math.floor((s % 1) * 100);
  return `${hrs}:${String(mins).padStart(2, '0')}:${String(secs).padStart(2, '0')}.${String(cs).padStart(2, '0')}`;
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

/**
 * Builds canonical Ayahs hierarchy ensuring edited word boundaries are 100% synchronized
 * into segment and ayah boundaries.
 */
function buildSynchronizedAyahs(surah: SurahItem) {
  return surah.ayahs.map(a => {
    const segments = a.segments.map(s => {
      const segStart = s.words.length > 0 ? s.words[0].start : s.start;
      const segEnd = s.words.length > 0 ? s.words[s.words.length - 1].end : s.end;
      return {
        segment: s.segment,
        start: Number(segStart.toFixed(3)),
        end: Number(segEnd.toFixed(3)),
        transcribed_text: s.words.map(w => w.word).join(' '),
        words: s.words.map(w => ({
          word: w.word,
          location: w.location,
          start: Number(w.start.toFixed(3)),
          end: Number(w.end.toFixed(3)),
          score: Number((w.score ?? 1).toFixed(3)),
          phonemes: w.phonemes || [],
          ...(w.is_edited ? { is_edited: true } : {})
        }))
      };
    });

    const ayahStart = segments.length > 0 ? segments[0].start : a.start;
    const ayahEnd = segments.length > 0 ? segments[segments.length - 1].end : a.end;

    return {
      ayah: a.ayah,
      start: Number(ayahStart.toFixed(3)),
      end: Number(ayahEnd.toFixed(3)),
      matched_ref: a.matched_ref || `${surah.surah_number}:${a.ayah}:1`,
      segments,
    };
  });
}

// ==========================================
// 1. SINGLE SURAH EXPORTERS
// ==========================================

export function exportCanonicalJson(surah: SurahItem): string {
  const ayahs = buildSynchronizedAyahs(surah);
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

export function exportProjectFile(project: AlignerProject): string {
  return JSON.stringify(project, null, 2);
}

export function exportSrt(surah: SurahItem, wordLevel: boolean = false): string {
  const entries: string[] = [];
  let index = 1;

  if (surah.intro && surah.intro.words && surah.intro.words.length > 0) {
    if (wordLevel) {
      for (const w of surah.intro.words) {
        entries.push(`${index++}\n${formatSrtTime(w.start)} --> ${formatSrtTime(w.end)}\n${w.word}\n`);
      }
    } else {
      const text = surah.intro.words.map(w => w.word).join(' ');
      const start = surah.intro.words[0].start;
      const end = surah.intro.words[surah.intro.words.length - 1].end;
      entries.push(`${index++}\n${formatSrtTime(start)} --> ${formatSrtTime(end)}\n${text}\n`);
    }
  }

  for (const a of surah.ayahs) {
    for (const seg of a.segments) {
      if (wordLevel) {
        for (const w of seg.words) {
          entries.push(`${index++}\n${formatSrtTime(w.start)} --> ${formatSrtTime(w.end)}\n${w.word}\n`);
        }
      } else {
        const text = seg.words.map(w => w.word).join(' ');
        const segStart = seg.words.length > 0 ? seg.words[0].start : seg.start;
        const segEnd = seg.words.length > 0 ? seg.words[seg.words.length - 1].end : seg.end;
        entries.push(`${index++}\n${formatSrtTime(segStart)} --> ${formatSrtTime(segEnd)}\n${text} (${a.ayah})\n`);
      }
    }
  }

  return entries.join('\n');
}

export function exportVtt(surah: SurahItem): string {
  const lines: string[] = ['WEBVTT - Quran Recite Aligner\n'];
  let index = 1;

  if (surah.intro && surah.intro.words && surah.intro.words.length > 0) {
    const text = surah.intro.words.map(w => w.word).join(' ');
    const start = surah.intro.words[0].start;
    const end = surah.intro.words[surah.intro.words.length - 1].end;
    lines.push(`${index++}\n${formatVttTime(start)} --> ${formatVttTime(end)}\n${text}\n`);
  }

  for (const a of surah.ayahs) {
    for (const seg of a.segments) {
      const text = seg.words.map(w => w.word).join(' ');
      const segStart = seg.words.length > 0 ? seg.words[0].start : seg.start;
      const segEnd = seg.words.length > 0 ? seg.words[seg.words.length - 1].end : seg.end;
      lines.push(`${index++}\n${formatVttTime(segStart)} --> ${formatVttTime(segEnd)}\n${text} (${a.ayah})\n`);
    }
  }

  return lines.join('\n');
}

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

  if (surah.intro && surah.intro.words && surah.intro.words.length > 0) {
    const startStr = formatAssTime(surah.intro.words[0].start);
    const endStr = formatAssTime(surah.intro.words[surah.intro.words.length - 1].end);
    const karaokeWords = surah.intro.words.map(w => {
      const durationCs = Math.max(1, Math.round((w.end - w.start) * 100));
      return `{\\k${durationCs}}${w.word}`;
    }).join(' ');
    dialogLines.push(`Dialogue: 0,${startStr},${endStr},QuranKaraoke,,0,0,0,,${karaokeWords}`);
  }

  for (const a of surah.ayahs) {
    for (const seg of a.segments) {
      if (seg.words.length === 0) continue;
      const startStr = formatAssTime(seg.words[0].start);
      const endStr = formatAssTime(seg.words[seg.words.length - 1].end);

      const karaokeWords = seg.words.map(w => {
        const durationCs = Math.max(1, Math.round((w.end - w.start) * 100));
        return `{\\k${durationCs}}${w.word}`;
      }).join(' ');

      dialogLines.push(`Dialogue: 0,${startStr},${endStr},QuranKaraoke,,0,0,0,,${karaokeWords} (${a.ayah})`);
    }
  }

  return header + dialogLines.join('\n');
}

export function exportQuranCaption(surah: SurahItem): string {
  let segIndex = 1;
  const segments: any[] = [];

  if (surah.intro && surah.intro.words && surah.intro.words.length > 0) {
    const introStart = surah.intro.words[0].start;
    const introEnd = surah.intro.words[surah.intro.words.length - 1].end;
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

  for (const a of surah.ayahs) {
    for (const seg of a.segments) {
      if (seg.words.length === 0) continue;
      const segStart = seg.words[0].start;
      const segEnd = seg.words[seg.words.length - 1].end;
      const segDur = Math.max(0.01, segEnd - segStart);

      const relativeWords = seg.words.map((w) => ({
        word: w.word,
        location: w.location,
        start: Math.max(0, w.start - segStart),
        end: Math.max(0, w.end - segStart),
        score: w.score,
      }));
      const normWords = normalizeWordBoundaries(relativeWords, segDur);

      segments.push({
        segment: segIndex++,
        time_from: Number(segStart.toFixed(3)),
        time_to: Number(segEnd.toFixed(3)),
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

export function exportWordTimingsCsv(surah: SurahItem): string {
  const rows: string[] = [
    'surah,ayah,word_idx,word,location,start_s,end_s,duration_ms,confidence_score'
  ];

  if (surah.intro && surah.intro.words) {
    surah.intro.words.forEach((w, idx) => {
      const dur = Math.round((w.end - w.start) * 1000);
      rows.push(`${surah.surah_number},0,${idx + 1},"${w.word}",${w.location || ''},${w.start.toFixed(3)},${w.end.toFixed(3)},${dur},${(w.score ?? 1).toFixed(2)}`);
    });
  }

  for (const a of surah.ayahs) {
    for (const seg of a.segments) {
      seg.words.forEach((w, idx) => {
        const dur = Math.round((w.end - w.start) * 1000);
        rows.push(`${surah.surah_number},${a.ayah},${idx + 1},"${w.word}",${w.location || ''},${w.start.toFixed(3)},${w.end.toFixed(3)},${dur},${(w.score ?? 1).toFixed(2)}`);
      });
    }
  }

  return '\uFEFF' + rows.join('\r\n');
}

export function exportPremiereMarkers(surah: SurahItem): string {
  const rows: string[] = [
    'Marker Name,Description,In,Out,Duration,Marker Type'
  ];

  for (const a of surah.ayahs) {
    for (const seg of a.segments) {
      if (seg.words.length === 0) continue;
      const text = seg.words.map(w => w.word).join(' ');
      const segStart = seg.words[0].start;
      const segEnd = seg.words[seg.words.length - 1].end;
      const dur = (segEnd - segStart).toFixed(3);
      rows.push(`"Ayah ${surah.surah_number}:${a.ayah}","${text}",${segStart.toFixed(3)},${segEnd.toFixed(3)},${dur},Comment`);
    }
  }

  return '\uFEFF' + rows.join('\r\n');
}

// ==========================================
// 2. ALL SURAHS COMBINED EXPORTERS
// ==========================================

export function exportAllCanonicalJson(project: AlignerProject): string {
  const surahs = project.surahs.map(s => ({
    surah: s.surah_number,
    surah_name_arabic: s.surah_name_arabic,
    surah_name_english: s.surah_name_english,
    ...(s.intro ? { intro: s.intro } : {}),
    ayahs: buildSynchronizedAyahs(s),
  }));

  return JSON.stringify({
    total_surahs: surahs.length,
    surahs,
  }, null, 2);
}

export function exportAllSrt(project: AlignerProject, wordLevel: boolean = false): string {
  const entries: string[] = [];
  let index = 1;

  for (const surah of project.surahs) {
    if (surah.intro && surah.intro.words && surah.intro.words.length > 0) {
      if (wordLevel) {
        for (const w of surah.intro.words) {
          entries.push(`${index++}\n${formatSrtTime(w.start)} --> ${formatSrtTime(w.end)}\n${w.word}\n`);
        }
      } else {
        const text = surah.intro.words.map(w => w.word).join(' ');
        const start = surah.intro.words[0].start;
        const end = surah.intro.words[surah.intro.words.length - 1].end;
        entries.push(`${index++}\n${formatSrtTime(start)} --> ${formatSrtTime(end)}\n${text}\n`);
      }
    }

    for (const a of surah.ayahs) {
      for (const seg of a.segments) {
        if (wordLevel) {
          for (const w of seg.words) {
            entries.push(`${index++}\n${formatSrtTime(w.start)} --> ${formatSrtTime(w.end)}\n${w.word}\n`);
          }
        } else {
          const text = seg.words.map(w => w.word).join(' ');
          const segStart = seg.words.length > 0 ? seg.words[0].start : seg.start;
          const segEnd = seg.words.length > 0 ? seg.words[seg.words.length - 1].end : seg.end;
          entries.push(`${index++}\n${formatSrtTime(segStart)} --> ${formatSrtTime(segEnd)}\n${text} (${surah.surah_number}:${a.ayah})\n`);
        }
      }
    }
  }

  return entries.join('\n');
}

export function exportAllVtt(project: AlignerProject): string {
  const lines: string[] = ['WEBVTT - Quran Recite Aligner (All Surahs)\n'];
  let index = 1;

  for (const surah of project.surahs) {
    if (surah.intro && surah.intro.words && surah.intro.words.length > 0) {
      const text = surah.intro.words.map(w => w.word).join(' ');
      const start = surah.intro.words[0].start;
      const end = surah.intro.words[surah.intro.words.length - 1].end;
      lines.push(`${index++}\n${formatVttTime(start)} --> ${formatVttTime(end)}\n${text}\n`);
    }

    for (const a of surah.ayahs) {
      for (const seg of a.segments) {
        const text = seg.words.map(w => w.word).join(' ');
        const segStart = seg.words.length > 0 ? seg.words[0].start : seg.start;
        const segEnd = seg.words.length > 0 ? seg.words[seg.words.length - 1].end : seg.end;
        lines.push(`${index++}\n${formatVttTime(segStart)} --> ${formatVttTime(segEnd)}\n${text} (${surah.surah_number}:${a.ayah})\n`);
      }
    }
  }

  return lines.join('\n');
}

export function exportAllAssKaraoke(project: AlignerProject): string {
  const header = `[Script Info]
Title: Quran Recite Aligner Karaoke - ${project.project_name || 'Project'}
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

  for (const surah of project.surahs) {
    if (surah.intro && surah.intro.words && surah.intro.words.length > 0) {
      const startStr = formatAssTime(surah.intro.words[0].start);
      const endStr = formatAssTime(surah.intro.words[surah.intro.words.length - 1].end);
      const karaokeWords = surah.intro.words.map(w => {
        const durationCs = Math.max(1, Math.round((w.end - w.start) * 100));
        return `{\\k${durationCs}}${w.word}`;
      }).join(' ');
      dialogLines.push(`Dialogue: 0,${startStr},${endStr},QuranKaraoke,,0,0,0,,${karaokeWords}`);
    }

    for (const a of surah.ayahs) {
      for (const seg of a.segments) {
        if (seg.words.length === 0) continue;
        const startStr = formatAssTime(seg.words[0].start);
        const endStr = formatAssTime(seg.words[seg.words.length - 1].end);

        const karaokeWords = seg.words.map(w => {
          const durationCs = Math.max(1, Math.round((w.end - w.start) * 100));
          return `{\\k${durationCs}}${w.word}`;
        }).join(' ');

        dialogLines.push(`Dialogue: 0,${startStr},${endStr},QuranKaraoke,,0,0,0,,${karaokeWords} (${surah.surah_number}:${a.ayah})`);
      }
    }
  }

  return header + dialogLines.join('\n');
}

export function exportAllQuranCaption(project: AlignerProject): string {
  let segIndex = 1;
  const segments: any[] = [];

  for (const surah of project.surahs) {
    if (surah.intro && surah.intro.words && surah.intro.words.length > 0) {
      const introStart = surah.intro.words[0].start;
      const introEnd = surah.intro.words[surah.intro.words.length - 1].end;
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

    for (const a of surah.ayahs) {
      for (const seg of a.segments) {
        if (seg.words.length === 0) continue;
        const segStart = seg.words[0].start;
        const segEnd = seg.words[seg.words.length - 1].end;
        const segDur = Math.max(0.01, segEnd - segStart);

        const relativeWords = seg.words.map((w) => ({
          word: w.word,
          location: w.location,
          start: Math.max(0, w.start - segStart),
          end: Math.max(0, w.end - segStart),
          score: w.score,
        }));
        const normWords = normalizeWordBoundaries(relativeWords, segDur);

        segments.push({
          segment: segIndex++,
          time_from: Number(segStart.toFixed(3)),
          time_to: Number(segEnd.toFixed(3)),
          ref_from: seg.words[0]?.location || `${surah.surah_number}:${a.ayah}:1`,
          ref_to: seg.words[seg.words.length - 1]?.location || `${surah.surah_number}:${a.ayah}:1`,
          matched_text: seg.words.map(w => w.word).join(' '),
          confidence: Number((seg.words.reduce((sum, w) => sum + w.score, 0) / Math.max(1, seg.words.length)).toFixed(2)),
          words: normWords,
        });
      }
    }
  }

  return JSON.stringify({ segments }, null, 2);
}

export function exportAllWordTimingsCsv(project: AlignerProject): string {
  const rows: string[] = [
    'surah,ayah,word_idx,word,location,start_s,end_s,duration_ms,confidence_score'
  ];

  for (const surah of project.surahs) {
    if (surah.intro && surah.intro.words) {
      surah.intro.words.forEach((w, idx) => {
        const dur = Math.round((w.end - w.start) * 1000);
        rows.push(`${surah.surah_number},0,${idx + 1},"${w.word}",${w.location || ''},${w.start.toFixed(3)},${w.end.toFixed(3)},${dur},${(w.score ?? 1).toFixed(2)}`);
      });
    }

    for (const a of surah.ayahs) {
      for (const seg of a.segments) {
        seg.words.forEach((w, idx) => {
          const dur = Math.round((w.end - w.start) * 1000);
          rows.push(`${surah.surah_number},${a.ayah},${idx + 1},"${w.word}",${w.location || ''},${w.start.toFixed(3)},${w.end.toFixed(3)},${dur},${(w.score ?? 1).toFixed(2)}`);
        });
      }
    }
  }

  return '\uFEFF' + rows.join('\r\n');
}

export function exportAllPremiereMarkers(project: AlignerProject): string {
  const rows: string[] = [
    'Marker Name,Description,In,Out,Duration,Marker Type'
  ];

  for (const surah of project.surahs) {
    for (const a of surah.ayahs) {
      for (const seg of a.segments) {
        if (seg.words.length === 0) continue;
        const text = seg.words.map(w => w.word).join(' ');
        const segStart = seg.words[0].start;
        const segEnd = seg.words[seg.words.length - 1].end;
        const dur = (segEnd - segStart).toFixed(3);
        rows.push(`"Surah ${surah.surah_number} Ayah ${a.ayah}","${text}",${segStart.toFixed(3)},${segEnd.toFixed(3)},${dur},Comment`);
      }
    }
  }

  return '\uFEFF' + rows.join('\r\n');
}

// ==========================================
// 3. MULTI-SURAH BATCH ZIP GENERATOR
// ==========================================

export async function exportSurahsAsZip(
  project: AlignerProject,
  format: ExportFormatId,
  wordLevel: boolean = false
): Promise<Blob> {
  const zip = new JSZip();
  const projFolder = zip.folder(sanitizeBatchExportFileName(project.project_name || 'quran_recitations')) || zip;

  for (const surah of project.surahs) {
    const num = String(surah.surah_number).padStart(3, '0');
    const safeName = sanitizeBatchExportFileName(surah.surah_name_english || `Surah_${num}`);
    let content = '';
    let ext = '';

    switch (format) {
      case 'json':
        content = exportCanonicalJson(surah);
        ext = 'json';
        break;
      case 'srt':
        content = exportSrt(surah, wordLevel);
        ext = 'srt';
        break;
      case 'vtt':
        content = exportVtt(surah);
        ext = 'vtt';
        break;
      case 'ass':
        content = exportAssKaraoke(surah);
        ext = 'ass';
        break;
      case 'qurancaption':
        content = exportQuranCaption(surah);
        ext = 'json';
        break;
      case 'csv':
        content = exportWordTimingsCsv(surah);
        ext = 'csv';
        break;
      case 'premiere':
        content = exportPremiereMarkers(surah);
        ext = 'csv';
        break;
      case 'qproj':
        content = exportProjectFile(project);
        ext = 'qproj';
        break;
    }

    projFolder.file(`${num}_${safeName}.${ext}`, content);
  }

  // Also include the project file in root of zip
  projFolder.file('project_specification.qproj', exportProjectFile(project));

  return await zip.generateAsync({ type: 'blob' });
}

// ==========================================
// 4. DOWNLOAD UTILITIES
// ==========================================

export function downloadFile(content: string, filename: string, mimeType: string = 'application/json') {
  const blob = new Blob([content], { type: `${mimeType};charset=utf-8` });
  downloadBlob(blob, filename);
}

export function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}
