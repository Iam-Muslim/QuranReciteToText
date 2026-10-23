import { describe, it, expect } from 'vitest';

// Function under test matching ProjectsHub normalization logic
function normalizeProjectSummary(p: any) {
  const surahs: any[] = Array.isArray(p.surahs) ? p.surahs : [];
  const surahsCount = surahs.length || (typeof p.surahs_count === 'number' ? p.surahs_count : 0);

  let primarySurah = p.primary_surah;
  if (!primarySurah && surahs.length > 0) {
    const s0 = surahs[0];
    primarySurah = {
      surah_number: s0.surah_number || 1,
      surah_name_arabic: s0.surah_name_arabic || '',
      surah_name_english: s0.surah_name_english || '',
    };
  }

  let totalAyahs = typeof p.total_ayahs === 'number' && p.total_ayahs > 0 ? p.total_ayahs : 0;
  if (totalAyahs === 0 && surahs.length > 0) {
    totalAyahs = surahs.reduce((sum: number, s: any) => sum + (Array.isArray(s.ayahs) ? s.ayahs.length : 0), 0);
  }

  let totalDuration = typeof p.total_duration === 'number' && p.total_duration > 0 ? p.total_duration : 0;
  if (totalDuration === 0 && surahs.length > 0) {
    totalDuration = surahs.reduce((sum: number, s: any) => sum + (Number(s.audio_duration_seconds) || 0), 0);
  }

  let status = p.status;
  if (!status && surahs.length > 0) {
    const isAllVerified = surahs.every((s: any) => s.status === 'verified');
    status = isAllVerified ? 'verified' : 'needs_review';
  }

  const fileName = p.file_name || `${p.project_name || 'project'}.qproj`;
  const projectName = String(p.project_name || p.name || 'Recitation Project');

  return {
    ...p,
    file_name: fileName,
    project_name: projectName,
    status: status || 'needs_review',
    surahs_count: surahsCount,
    primary_surah: primarySurah,
    total_ayahs: totalAyahs,
    total_duration: totalDuration,
  };
}

describe('normalizeProjectSummary', () => {
  it('correctly handles multi-surah projects and does not lock count to 1', () => {
    const rawDiskProject = {
      project_name: 'Three Surahs Recitation',
      surahs: [
        { surah_number: 1, surah_name_arabic: 'الفاتحة', ayahs: [{}, {}, {}], audio_duration_seconds: 40 },
        { surah_number: 112, surah_name_arabic: 'الإخلاص', ayahs: [{}, {}, {}, {}], audio_duration_seconds: 25 },
        { surah_number: 113, surah_name_arabic: 'الفلق', ayahs: [{}, {}, {}, {}, {}], audio_duration_seconds: 30 },
      ]
    };

    const summary = normalizeProjectSummary(rawDiskProject);

    expect(summary.surahs_count).toBe(3);
    expect(summary.total_ayahs).toBe(12);
    expect(summary.total_duration).toBe(95);
    expect(summary.primary_surah?.surah_name_arabic).toBe('الفاتحة');
    expect(summary.primary_surah?.surah_number).toBe(1);
  });

  it('handles empty projects with 0 surahs gracefully without error', () => {
    const emptyProj = {
      project_name: 'Empty Project',
      surahs: []
    };

    const summary = normalizeProjectSummary(emptyProj);

    expect(summary.surahs_count).toBe(0);
    expect(summary.total_ayahs).toBe(0);
    expect(summary.total_duration).toBe(0);
    expect(summary.primary_surah).toBeUndefined();
  });
});
