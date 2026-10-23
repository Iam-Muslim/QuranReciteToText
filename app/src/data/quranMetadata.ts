import rawSurahs from './surahs.json';

export interface SurahMeta {
  surah_number: number;
  surah_name_arabic: string;
  surah_name_english: string;
  num_verses: number;
}

export const QURAN_SURAHS: SurahMeta[] = (rawSurahs as Array<{
  id: number;
  arabic: string;
  name: string;
  totalAyah: number;
}>).map((s) => ({
  surah_number: s.id,
  surah_name_arabic: s.arabic,
  surah_name_english: s.name,
  num_verses: s.totalAyah,
}));

export function getSurahMeta(num: number): {
  id: number;
  arabic: string;
  english: string;
  totalAyahs: number;
} {
  const meta = QURAN_SURAHS.find((s) => s.surah_number === num);
  if (meta) {
    return {
      id: meta.surah_number,
      arabic: meta.surah_name_arabic,
      english: meta.surah_name_english,
      totalAyahs: meta.num_verses,
    };
  }
  return {
    id: num,
    arabic: `سورة ${num}`,
    english: `Surah ${num}`,
    totalAyahs: 0,
  };
}
