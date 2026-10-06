import type { AlignerProject } from '../types/aligner';

export const SURAH_METADATA: { [num: number]: { arabic: string; english: string; total_ayahs: number } } = {
  1: { arabic: 'الفاتحة', english: 'Al-Fatihah', total_ayahs: 7 },
  2: { arabic: 'البقرة', english: 'Al-Baqarah', total_ayahs: 286 },
  3: { arabic: 'آل عمران', english: 'Ali Imran', total_ayahs: 200 },
  4: { arabic: 'النساء', english: 'An-Nisa', total_ayahs: 176 },
  5: { arabic: 'المائدة', english: 'Al-Maidah', total_ayahs: 120 },
  6: { arabic: 'الأنعام', english: 'Al-Anam', total_ayahs: 165 },
  7: { arabic: 'الأعراف', english: 'Al-Araf', total_ayahs: 206 },
  8: { arabic: 'الأنفال', english: 'Al-Anfal', total_ayahs: 75 },
  9: { arabic: 'التوبة', english: 'At-Tawbah', total_ayahs: 129 },
  10: { arabic: 'يونس', english: 'Yunus', total_ayahs: 109 },
  11: { arabic: 'هود', english: 'Hud', total_ayahs: 123 },
  12: { arabic: 'يوسف', english: 'Yusuf', total_ayahs: 111 },
  13: { arabic: 'الرعد', english: 'Ar-Rad', total_ayahs: 43 },
  14: { arabic: 'إبراهيم', english: 'Ibrahim', total_ayahs: 52 },
  15: { arabic: 'الحجر', english: 'Al-Hijr', total_ayahs: 99 },
  16: { arabic: 'النحل', english: 'An-Nahl', total_ayahs: 128 },
  17: { arabic: 'الإسراء', english: 'Al-Isra', total_ayahs: 111 },
  18: { arabic: 'الكهف', english: 'Al-Kahf', total_ayahs: 110 },
  19: { arabic: 'مريم', english: 'Maryam', total_ayahs: 98 },
  20: { arabic: 'طه', english: 'Taha', total_ayahs: 135 },
  36: { arabic: 'يس', english: 'Ya-Sin', total_ayahs: 83 },
  55: { arabic: 'الرحمن', english: 'Ar-Rahman', total_ayahs: 78 },
  67: { arabic: 'الملك', english: 'Al-Mulk', total_ayahs: 30 },
  108: { arabic: 'الكوثر', english: 'Al-Kawthar', total_ayahs: 3 },
  112: { arabic: 'الإخلاص', english: 'Al-Ikhlas', total_ayahs: 4 },
  113: { arabic: 'الفلق', english: 'Al-Falaq', total_ayahs: 5 },
  114: { arabic: 'الناس', english: 'An-Nas', total_ayahs: 6 },
};

export const SAMPLE_PROJECT: AlignerProject = {
  project_name: 'Sheikh Mishary Rashid Alafasy — Hafs 1445',
  app_version: '1.0.0',
  created_at: '2026-10-05T20:00:00Z',
  updated_at: '2026-10-05T20:15:00Z',
  settings: {
    snapping_tolerance_ms: 15,
    confidence_warning_threshold: 0.85,
    auto_save_interval_s: 60,
  },
  surahs: [
    {
      surah_number: 1,
      surah_name_arabic: 'الفاتحة',
      surah_name_english: 'Al-Fatihah',
      audio_duration_seconds: 42.50,
      status: 'needs_review',
      intro: {
        text: 'بِسْمِ ٱللَّهِ ٱلرَّحْمَـٰنِ ٱلرَّحِيمِ',
        start: 0.40,
        end: 4.10,
        words: [
          { word: 'بِسْمِ', location: '0:0:1', start: 0.40, end: 1.05, score: 0.99 },
          { word: 'ٱللَّهِ', location: '0:0:2', start: 1.05, end: 1.95, score: 0.98 },
          { word: 'ٱلرَّحْمَـٰنِ', location: '0:0:3', start: 1.95, end: 2.90, score: 0.97 },
          { word: 'ٱلرَّحِيمِ', location: '0:0:4', start: 2.90, end: 4.10, score: 0.99 },
        ]
      },
      ayahs: [
        {
          ayah: 1,
          start: 0.40,
          end: 4.10,
          matched_ref: '1:1:1-1:1:4',
          segments: [
            {
              segment: 1,
              start: 0.40,
              end: 4.10,
              words: [
                { word: 'بِسْمِ', location: '1:1:1', start: 0.40, end: 1.05, score: 0.99 },
                { word: 'ٱللَّهِ', location: '1:1:2', start: 1.05, end: 1.95, score: 0.98 },
                { word: 'ٱلرَّحْمَـٰنِ', location: '1:1:3', start: 1.95, end: 2.90, score: 0.97 },
                { word: 'ٱلرَّحِيمِ', location: '1:1:4', start: 2.90, end: 4.10, score: 0.99 },
              ]
            }
          ]
        },
        {
          ayah: 2,
          start: 4.80,
          end: 9.35,
          matched_ref: '1:2:1-1:2:4',
          segments: [
            {
              segment: 1,
              start: 4.80,
              end: 9.35,
              words: [
                { word: 'ٱلْحَمْدُ', location: '1:2:1', start: 4.80, end: 5.65, score: 0.98 },
                { word: 'لِلَّهِ', location: '1:2:2', start: 5.65, end: 6.45, score: 0.99 },
                { word: 'رَبِّ', location: '1:2:3', start: 6.45, end: 7.20, score: 0.96 },
                { word: 'ٱلْعَـٰلَمِينَ', location: '1:2:4', start: 7.20, end: 9.35, score: 0.98 },
              ]
            }
          ]
        },
        {
          ayah: 3,
          start: 10.10,
          end: 13.90,
          matched_ref: '1:3:1-1:3:2',
          segments: [
            {
              segment: 1,
              start: 10.10,
              end: 13.90,
              words: [
                { word: 'ٱلرَّحْمَـٰنِ', location: '1:3:1', start: 10.10, end: 11.50, score: 0.97 },
                { word: 'ٱلرَّحِيمِ', location: '1:3:2', start: 11.50, end: 13.90, score: 0.99 },
              ]
            }
          ]
        },
        {
          ayah: 4,
          start: 14.70,
          end: 18.60,
          matched_ref: '1:4:1-1:4:3',
          segments: [
            {
              segment: 1,
              start: 14.70,
              end: 18.60,
              words: [
                { word: 'مَـٰلِكِ', location: '1:4:1', start: 14.70, end: 15.65, score: 0.98 },
                { word: 'يَوْمِ', location: '1:4:2', start: 15.65, end: 16.40, score: 0.97 },
                { word: 'ٱلدِّينِ', location: '1:4:3', start: 16.40, end: 18.60, score: 0.99 },
              ]
            }
          ]
        },
        {
          ayah: 5,
          start: 19.40,
          end: 25.10,
          matched_ref: '1:5:1-1:5:4',
          segments: [
            {
              segment: 1,
              start: 19.40,
              end: 25.10,
              words: [
                { word: 'إِيَّاكَ', location: '1:5:1', start: 19.40, end: 20.55, score: 0.99 },
                { word: 'نَعْبُدُ', location: '1:5:2', start: 20.55, end: 21.65, score: 0.96 },
                { word: 'وَإِيَّاكَ', location: '1:5:3', start: 21.65, end: 22.90, score: 0.98 },
                { word: 'نَسْتَعِينُ', location: '1:5:4', start: 22.90, end: 25.10, score: 0.99 },
              ]
            }
          ]
        },
        {
          ayah: 6,
          start: 25.90,
          end: 30.80,
          matched_ref: '1:6:1-1:6:3',
          segments: [
            {
              segment: 1,
              start: 25.90,
              end: 30.80,
              words: [
                { word: 'ٱهْدِنَا', location: '1:6:1', start: 25.90, end: 27.05, score: 0.97 },
                { word: 'ٱلصِّرَاطَ', location: '1:6:2', start: 27.05, end: 28.35, score: 0.98 },
                { word: 'ٱلْمُسْتَقِيمَ', location: '1:6:3', start: 28.35, end: 30.80, score: 0.99 },
              ]
            }
          ]
        },
        {
          ayah: 7,
          start: 31.60,
          end: 42.20,
          matched_ref: '1:7:1-1:7:9',
          segments: [
            {
              segment: 1,
              start: 31.60,
              end: 42.20,
              words: [
                { word: 'صِرَاطَ', location: '1:7:1', start: 31.60, end: 32.55, score: 0.98 },
                { word: 'ٱلَّذِينَ', location: '1:7:2', start: 32.55, end: 33.50, score: 0.97 },
                { word: 'أَنْعَمْتَ', location: '1:7:3', start: 33.50, end: 34.70, score: 0.95 },
                { word: 'عَلَيْهِمْ', location: '1:7:4', start: 34.70, end: 35.80, score: 0.98 },
                { word: 'غَيْرِ', location: '1:7:5', start: 35.80, end: 36.65, score: 0.97 },
                { word: 'ٱلْمَغْضُوبِ', location: '1:7:6', start: 36.65, end: 37.95, score: 0.96 },
                { word: 'عَلَيْهِمْ', location: '1:7:7', start: 37.95, end: 38.80, score: 0.98 },
                { word: 'وَلَا', location: '1:7:8', start: 38.80, end: 39.40, score: 0.96 },
                // Notice: 0.74 score triggers the confidence auditor warning!
                { word: 'ٱلضَّآلِّينَ', location: '1:7:9', start: 39.40, end: 42.20, score: 0.74 },
              ]
            }
          ]
        }
      ]
    },
    {
      surah_number: 112,
      surah_name_arabic: 'الإخلاص',
      surah_name_english: 'Al-Ikhlas',
      audio_duration_seconds: 19.80,
      status: 'verified',
      ayahs: [
        {
          ayah: 1,
          start: 0.50,
          end: 4.20,
          matched_ref: '112:1:1-112:1:4',
          segments: [
            {
              segment: 1,
              start: 0.50,
              end: 4.20,
              words: [
                { word: 'قُلْ', location: '112:1:1', start: 0.50, end: 1.10, score: 0.99 },
                { word: 'هُوَ', location: '112:1:2', start: 1.10, end: 1.70, score: 0.98 },
                { word: 'ٱللَّهُ', location: '112:1:3', start: 1.70, end: 2.70, score: 0.99 },
                { word: 'أَحَدٌ', location: '112:1:4', start: 2.70, end: 4.20, score: 0.98 },
              ]
            }
          ]
        },
        {
          ayah: 2,
          start: 4.90,
          end: 8.50,
          matched_ref: '112:2:1-112:2:2',
          segments: [
            {
              segment: 1,
              start: 4.90,
              end: 8.50,
              words: [
                { word: 'ٱللَّهُ', location: '112:2:1', start: 4.90, end: 6.10, score: 0.99 },
                { word: 'ٱلصَّمَدُ', location: '112:2:2', start: 6.10, end: 8.50, score: 0.98 },
              ]
            }
          ]
        },
        {
          ayah: 3,
          start: 9.30,
          end: 14.10,
          matched_ref: '112:3:1-112:3:4',
          segments: [
            {
              segment: 1,
              start: 9.30,
              end: 14.10,
              words: [
                { word: 'لَمْ', location: '112:3:1', start: 9.30, end: 10.20, score: 0.98 },
                { word: 'يَلِدْ', location: '112:3:2', start: 10.20, end: 11.50, score: 0.97 },
                { word: 'وَلَمْ', location: '112:3:3', start: 11.50, end: 12.40, score: 0.98 },
                { word: 'يُولَدْ', location: '112:3:4', start: 12.40, end: 14.10, score: 0.99 },
              ]
            }
          ]
        },
        {
          ayah: 4,
          start: 14.90,
          end: 19.50,
          matched_ref: '112:4:1-112:4:5',
          segments: [
            {
              segment: 1,
              start: 14.90,
              end: 19.50,
              words: [
                { word: 'وَلَمْ', location: '112:4:1', start: 14.90, end: 15.80, score: 0.98 },
                { word: 'يَكُن', location: '112:4:2', start: 15.80, end: 16.70, score: 0.97 },
                { word: 'لَّهُۥ', location: '112:4:3', start: 16.70, end: 17.50, score: 0.99 },
                { word: 'كُفُوًا', location: '112:4:4', start: 17.50, end: 18.40, score: 0.96 },
                { word: 'أَحَدٌۢ', location: '112:4:5', start: 18.40, end: 19.50, score: 0.98 },
              ]
            }
          ]
        }
      ]
    },
    {
      surah_number: 108,
      surah_name_arabic: 'الكوثر',
      surah_name_english: 'Al-Kawthar',
      audio_duration_seconds: 14.20,
      status: 'verified',
      ayahs: [
        {
          ayah: 1,
          start: 0.40,
          end: 4.30,
          matched_ref: '108:1:1-108:1:3',
          segments: [
            {
              segment: 1,
              start: 0.40,
              end: 4.30,
              words: [
                { word: 'إِنَّآ', location: '108:1:1', start: 0.40, end: 1.50, score: 0.99 },
                { word: 'أَعْطَيْنَـٰكَ', location: '108:1:2', start: 1.50, end: 2.90, score: 0.98 },
                { word: 'ٱلْكَوْثَرَ', location: '108:1:3', start: 2.90, end: 4.30, score: 0.99 },
              ]
            }
          ]
        },
        {
          ayah: 2,
          start: 5.10,
          end: 9.20,
          matched_ref: '108:2:1-108:2:3',
          segments: [
            {
              segment: 1,
              start: 5.10,
              end: 9.20,
              words: [
                { word: 'فَصَلِّ', location: '108:2:1', start: 5.10, end: 6.20, score: 0.97 },
                { word: 'لِرَبِّكَ', location: '108:2:2', start: 6.20, end: 7.40, score: 0.98 },
                { word: 'وَٱنْحَرْ', location: '108:2:3', start: 7.40, end: 9.20, score: 0.99 },
              ]
            }
          ]
        },
        {
          ayah: 3,
          start: 9.90,
          end: 13.90,
          matched_ref: '108:3:1-108:3:3',
          segments: [
            {
              segment: 1,
              start: 9.90,
              end: 13.90,
              words: [
                { word: 'إِنَّ', location: '108:3:1', start: 9.90, end: 10.80, score: 0.99 },
                { word: 'شَانِئَكَ', location: '108:3:2', start: 10.80, end: 12.10, score: 0.97 },
                { word: 'هُوَ', location: '108:3:3', start: 12.10, end: 12.70, score: 0.98 },
                { word: 'ٱلْأَبْتَرُ', location: '108:3:4', start: 12.70, end: 13.90, score: 0.99 },
              ]
            }
          ]
        }
      ]
    }
  ]
};
