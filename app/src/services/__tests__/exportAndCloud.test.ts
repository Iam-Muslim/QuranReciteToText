import { describe, it, expect } from 'vitest';
import { exportCanonicalJson, exportAllCanonicalJson } from '../exporters';
import { normalizeHfRepoInput } from '../cloudDataset';
import { parseCanonicalSurahs } from '../segmentIngest';
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

  it('exportCanonicalJson produces clean single-surah JSON without metadata bloat', () => {
    const jsonStr = exportCanonicalJson(dummySurah);
    const parsed = JSON.parse(jsonStr);

    expect(parsed.surah).toBe(1);
    // Verified: No bloated metadata fields
    expect(parsed.surah_name_arabic).toBeUndefined();
    expect(parsed.surah_name_english).toBeUndefined();
    expect(parsed.duration).toBeUndefined();
    expect(parsed.status).toBeUndefined();
    expect(parsed.peaks).toBeUndefined();

    expect(parsed.intro?.text).toBe('أعوذ بالله من الشيطان الرجيم');
    expect(parsed.ayahs).toHaveLength(1);
    expect(parsed.ayahs[0].words).toHaveLength(4);
    expect(parsed.ayahs[0].words[0].text).toBe('بِسْمِ');
    expect(parsed.ayahs[0].words[0].w).toBe(1);
    expect(parsed.ayahs[0].words[0].score).toBeUndefined();
  });

  it('exportAllCanonicalJson exports whole project with all surahs in canonical clean structure', () => {
    const jsonStr = exportAllCanonicalJson(dummyProject);
    const parsed = JSON.parse(jsonStr);

    expect(parsed.project_name).toBe('Mishary Alafasy Hafs');
    expect(parsed.reciter).toBe('Mishary Rashid Alafasy');
    expect(parsed.riwayah).toBe('Hafs');
    expect(parsed.surahs).toHaveLength(1);
    expect(parsed.surahs[0].surah).toBe(1);
    expect(parsed.surahs[0].surah_name_arabic).toBeUndefined();
    expect(parsed.surahs[0].duration).toBeUndefined();
    expect(parsed.surahs[0].ayahs[0].words).toHaveLength(4);
  });

  it('strips peak_frame and peak_timestamp from phonemes and round-trips correctly', () => {
    const surahWithPhonemePeaks: SurahItem = {
      surah_number: 1,
      surah_name_arabic: 'الفاتحة',
      surah_name_english: 'Al-Faatiha',
      status: 'verified',
      ayahs: [
        {
          ayah: 1,
          start: 0,
          end: 2.0,
          segments: [
            {
              segment: 1,
              start: 0,
              end: 2.0,
              words: [
                {
                  word: 'بِسْمِ',
                  location: '1:1:1',
                  start: 0,
                  end: 0.8,
                  score: 1.0,
                  phonemes: [
                    { phoneme: 'بِ', start: 0, end: 0.3, peak_frame: 69, peak_timestamp: 0.15 } as any,
                    { phoneme: 'س', start: 0.3, end: 0.55, peak_frame: 74, peak_timestamp: 0.4 } as any,
                  ],
                },
              ],
            },
          ],
        },
      ],
    };

    const exportedStr = exportCanonicalJson(surahWithPhonemePeaks);
    const parsed = JSON.parse(exportedStr);

    const firstWordPhonemes = parsed.ayahs[0].words[0].phonemes;
    expect(firstWordPhonemes).toHaveLength(2);
    expect(firstWordPhonemes[0].phoneme).toBe('بِ');
    expect(firstWordPhonemes[0].start).toBe(0);
    expect(firstWordPhonemes[0].end).toBe(0.3);
    // Verified: No peak frame or timestamp in export
    expect(firstWordPhonemes[0].peak_frame).toBeUndefined();
    expect(firstWordPhonemes[0].peak_timestamp).toBeUndefined();
  });

  it('normalizeHfRepoInput handles full URLs and shorthand', () => {
    expect(normalizeHfRepoInput('https://huggingface.co/datasets/TheGreatQuran/Quran-recite2text')).toBe('TheGreatQuran/Quran-recite2text');
    expect(normalizeHfRepoInput('https://huggingface.co/datasets/MyOrg/my-recitations/tree/main')).toBe('MyOrg/my-recitations');
    expect(normalizeHfRepoInput('user123/dataset456')).toBe('user123/dataset456');
    expect(normalizeHfRepoInput('')).toBe('TheGreatQuran/Quran-recite2text');
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

    const rawJson = exportCanonicalJson(surahWithRepeats);
    // Verified: ALWAYS minified (no formatting newlines)
    expect(rawJson).not.toContain('\n');

    const exported = JSON.parse(rawJson);
    expect(exported.ayahs[0].phrases).toHaveLength(2);
    expect(exported.ayahs[0].phrases[0].phrase).toBe(1);
    expect(exported.ayahs[0].phrases[1].phrase).toBe(2);

    // Repeated words keep their true canonical index w: 3 and w: 4 along the timeline: [1, 2, 3, 4, 3, 4]
    const wordIndices = exported.ayahs[0].words.map((w: any) => w.w);
    expect(wordIndices).toEqual([1, 2, 3, 4, 3, 4]);

    // Zero bloat: no redundant is_repetition flags in JSON
    expect(exported.ayahs[0].words[4].is_repetition).toBeUndefined();
    expect(exported.ayahs[0].words[4].w).toBe(3);
    expect(exported.ayahs[0].words[5].w).toBe(4);
  });

  it('round-trip test: exported unbloated canonical JSON is loaded by parseCanonicalSurahs', () => {
    const rawJson = exportCanonicalJson(dummySurah);
    const parsedJson = JSON.parse(rawJson);

    const { surahs, firstAddedSurahNum } = parseCanonicalSurahs(parsedJson);
    expect(surahs).toHaveLength(1);
    expect(firstAddedSurahNum).toBe(1);

    const s = surahs[0];
    expect(s.surah_number).toBe(1);
    expect(s.surah_name_arabic).toBe('الفاتحة');
    expect(s.surah_name_english).toBe('Al-Fatihah');
    expect(s.ayahs).toHaveLength(1);
    expect(s.ayahs[0].segments[0].words).toHaveLength(4);
    expect(s.ayahs[0].segments[0].words[0].word).toBe('بِسْمِ');
    expect(s.ayahs[0].segments[0].words[0].location).toBe('1:1:1');
  });
});
