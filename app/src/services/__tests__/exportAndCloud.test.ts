import { describe, it, expect } from 'vitest';
import { exportCanonicalJson, exportAllCanonicalJson } from '../exporters';
import { normalizeHfRepoInput } from '../cloudDataset';
import type { AlignerProject, SurahItem } from '../../types/aligner';

describe('Canonical JSON Exporter & Cloud Helpers', () => {
  const dummySurah: SurahItem = {
    surah_number: 1,
    surah_name_arabic: 'الفاتحة',
    surah_name_english: 'Al-Faatiha',
    audio_duration_seconds: 35.5,
    status: 'verified',
    peaks: [0.12, 0.45, 0.78, 0.23],
    intro: {
      text: 'أعوذ بالله من الشيطان الرجيم',
      start: 0,
      end: 3.2,
    },
    ayahs: [
      {
        ayah: 1,
        start: 3.3,
        end: 7.8,
        segments: [
          {
            segment: 1,
            start: 3.3,
            end: 7.8,
            words: [
              { word: 'بِسْمِ', location: '1:1:1', start: 3.3, end: 4.1, score: 0.99 },
              { word: 'اللَّهِ', location: '1:1:2', start: 4.15, end: 5.1, score: 0.98 },
              { word: 'الرَّحْمَٰنِ', location: '1:1:3', start: 5.15, end: 6.4, score: 0.95 },
              { word: 'الرَّحِيمِ', location: '1:1:4', start: 6.45, end: 7.8, score: 0.97 },
            ],
          },
        ],
      },
    ],
  };

  const dummyProject: AlignerProject = {
    app_version: '1.0.0',
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    project_name: 'Mishary Alafasy Hafs',
    reciter: 'Mishary Rashid Alafasy',
    settings: {
      riwayah: 'Hafs',
      snapping_tolerance_ms: 25,
      confidence_warning_threshold: 0.85,
      auto_save_interval_s: 30,
      cloud_origin: true,
      cloud_folder: 'reciters/Mishary_Rashid_Alafasy',
      cloud_repo: 'Iam-Muslim/Quran-Recitations-Dataset',
    },
    surahs: [dummySurah],
  };

  it('exportCanonicalJson produces clean single-surah JSON with direct ayahs and words', () => {
    const jsonStr = exportCanonicalJson(dummySurah);
    const parsed = JSON.parse(jsonStr);

    expect(parsed.surah).toBe(1);
    expect(parsed.surah_name_arabic).toBe('الفاتحة');
    expect(parsed.duration).toBe(35.5);
    expect(parsed.status).toBe('verified');
    expect(parsed.intro?.text).toBe('أعوذ بالله من الشيطان الرجيم');
    expect(parsed.ayahs).toHaveLength(1);
    expect(parsed.ayahs[0].words).toHaveLength(4);
    expect(parsed.ayahs[0].words[0].text).toBe('بِسْمِ');
    expect(parsed.ayahs[0].words[0].w).toBe(1);
  });

  it('exportAllCanonicalJson exports whole project with all surahs in canonical structure', () => {
    const jsonStr = exportAllCanonicalJson(dummyProject);
    const parsed = JSON.parse(jsonStr);

    expect(parsed.project_name).toBe('Mishary Alafasy Hafs');
    expect(parsed.reciter).toBe('Mishary Rashid Alafasy');
    expect(parsed.riwayah).toBe('Hafs');
    expect(parsed.surahs).toHaveLength(1);
    expect(parsed.surahs[0].surah).toBe(1);
    expect(parsed.surahs[0].duration).toBe(35.5);
    expect(parsed.surahs[0].ayahs[0].words).toHaveLength(4);
  });

  it('normalizeHfRepoInput handles full URLs and shorthand', () => {
    expect(normalizeHfRepoInput('https://huggingface.co/datasets/Iam-Muslim/Quran-Recitations-Dataset')).toBe('Iam-Muslim/Quran-Recitations-Dataset');
    expect(normalizeHfRepoInput('https://huggingface.co/datasets/MyOrg/my-recitations/tree/main')).toBe('MyOrg/my-recitations');
    expect(normalizeHfRepoInput('user123/dataset456')).toBe('user123/dataset456');
    expect(normalizeHfRepoInput('')).toBe('Iam-Muslim/Quran-Recitations-Dataset');
  });

  it('correctly preserves phrases and is_repetition flags on repeated phrases and words', () => {
    const surahWithRepeats: SurahItem = {
      surah_number: 112,
      surah_name_arabic: 'الإخلاص',
      surah_name_english: 'Al-Ikhlaas',
      status: 'verified',
      ayahs: [
        {
          ayah: 1,
          start: 0,
          end: 6.0,
          segments: [
            {
              segment: 1,
              start: 0,
              end: 2.5,
              words: [
                { word: 'قُلْ', location: '112:1:1', start: 0, end: 0.8, score: 1 },
                { word: 'هُوَ', location: '112:1:2', start: 0.8, end: 1.5, score: 1 },
                { word: 'اللَّهُ', location: '112:1:3', start: 1.5, end: 2.0, score: 1 },
                { word: 'أَحَدٌ', location: '112:1:4', start: 2.0, end: 2.5, score: 1 },
              ],
            },
            {
              segment: 2,
              start: 3.5,
              end: 6.0,
              is_repetition: true,
              words: [
                { word: 'اللَّهُ', location: '112:1:3', start: 3.5, end: 4.5, score: 1, is_repetition: true },
                { word: 'أَحَدٌ', location: '112:1:4', start: 4.5, end: 6.0, score: 1, is_repetition: true },
              ],
            },
          ],
        },
      ],
    };

    const exported = JSON.parse(exportCanonicalJson(surahWithRepeats));
    expect(exported.ayahs[0].phrases).toHaveLength(2);
    expect(exported.ayahs[0].phrases[0].phrase).toBe(1);
    expect(exported.ayahs[0].phrases[1].phrase).toBe(2);
    expect(exported.ayahs[0].phrases[1].is_repetition).toBe(true);

    // Repeated words keep their true canonical index w: 3 and w: 4, not 5 and 6!
    const repeatedWords = exported.ayahs[0].words.filter((w: any) => w.is_repetition);
    expect(repeatedWords).toHaveLength(2);
    expect(repeatedWords[0].w).toBe(3);
    expect(repeatedWords[0].is_repetition).toBe(true);
    expect(repeatedWords[1].w).toBe(4);
    expect(repeatedWords[1].is_repetition).toBe(true);
  });
});
