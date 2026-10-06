/**
 * Quran Linguistic & Verse Data Provider
 * Directly adapted from QuranCaption's Quran class and data architecture.
 * Loads canonical Surah and Verse data from static JSON files (/quran/surahs.json and /quran/{id}.json).
 */

export type RawWord = { c: string; d: string; e: string; i?: string };
export type RawVerse = { w: RawWord[]; a?: { g?: string } };
export type RawSurah = {
  id: number;
  arabic: string;
  name: string;
  translation: string;
  totalAyah: number;
  arabicLong: string;
  revelationPlace: string;
};

export class Word {
  arabic: string;
  indopak: string;
  transliteration: string;
  translation: string;

  constructor(arabic: string, transliteration: string, translation: string, indopak?: string) {
    this.arabic = arabic;
    this.indopak = indopak ?? arabic;
    this.transliteration = transliteration;
    this.translation = translation;
  }

  static fromJson(data: RawWord): Word {
    return new Word(data.c, data.d, data.e, data.i);
  }
}

export class Verse {
  id: number;
  words: Word[];
  translation?: string;

  constructor(id: number, words: Word[] = [], translation?: string) {
    this.id = id;
    this.words = words;
    this.translation = translation;
  }

  static fromJson(id: string, data: RawVerse): Verse {
    const words = (data.w || []).map((word) => Word.fromJson(word));
    const translation = data.a?.g;
    return new Verse(parseInt(id, 10), words, translation);
  }

  getArabicTextBetweenTwoIndexes(
    startIndex: number,
    endIndex: number,
    script: 'uthmani' | 'indopak' = 'uthmani'
  ): string {
    if (this.words.length === 0) return '';
    if (startIndex < 0 || endIndex >= this.words.length || startIndex > endIndex) {
      if (endIndex >= this.words.length) {
        return this.getArabicTextBetweenTwoIndexes(startIndex, this.words.length - 1, script);
      }
      return '';
    }
    return this.words
      .slice(startIndex, endIndex + 1)
      .map((word) => (script === 'indopak' ? word.indopak : word.arabic))
      .join(' ');
  }

  getWordByWordTranslationBetweenTwoIndexes(startIndex: number, endIndex: number): string[] {
    if (startIndex < 0 || endIndex >= this.words.length || startIndex > endIndex) {
      if (endIndex >= this.words.length) {
        return this.getWordByWordTranslationBetweenTwoIndexes(startIndex, this.words.length - 1);
      }
      return [];
    }
    return this.words.slice(startIndex, endIndex + 1).map((word) => word.translation);
  }
}

export class Surah {
  id: number;
  arabic: string;
  name: string;
  translation: string;
  totalAyah: number;
  verses: Verse[];
  arabicLong: string;
  revelationPlace: string;

  constructor(
    id: number,
    arabic: string,
    name: string,
    translation: string,
    totalAyah: number,
    arabicLong: string,
    revelationPlace: string,
    verses: Verse[] = []
  ) {
    this.id = id;
    this.arabic = arabic;
    this.name = name;
    this.translation = translation;
    this.totalAyah = totalAyah;
    this.arabicLong = arabicLong;
    this.revelationPlace = revelationPlace;
    this.verses = verses;
  }

  static fromJson(data: RawSurah): Surah {
    return new Surah(
      data.id,
      data.arabic,
      data.name,
      data.translation,
      data.totalAyah,
      data.arabicLong,
      data.revelationPlace,
      []
    );
  }
}

export class Quran {
  static surahs: Surah[] = [];
  private static loadPromise: Promise<void> | null = null;
  private static surahPromises = new Map<number, Promise<Surah>>();

  /**
   * Loads the Quran surahs metadata list (singleton pattern matching QuranCaption)
   */
  static async load(): Promise<void> {
    if (Quran.surahs.length > 0) return;
    if (Quran.loadPromise) return Quran.loadPromise;

    Quran.loadPromise = (async () => {
      try {
        const response = await fetch('/quran/surahs.json');
        if (!response.ok) {
          throw new Error(`Failed to load surahs metadata: ${response.status}`);
        }
        const data = (await response.json()) as RawSurah[];
        Quran.surahs = data.map((surahData) => Surah.fromJson(surahData));
      } catch (err) {
        Quran.loadPromise = null;
        throw err;
      }
    })();

    return Quran.loadPromise;
  }

  static getSurahs(): Surah[] {
    return Quran.surahs;
  }

  static getVerseCount(surah: number): number {
    const foundSurah = Quran.surahs.find((s) => s.id === surah);
    return foundSurah ? foundSurah.totalAyah : 0;
  }

  static getSurahsNames(): { id: number; transliteration: string; arabic: string }[] {
    return Quran.surahs.map((surah) => ({
      id: surah.id,
      transliteration: surah.name,
      arabic: surah.arabic,
    }));
  }

  /**
   * Retrieves a surah with its verses loaded from /quran/{id}.json
   */
  static async getSurah(id: number): Promise<Surah> {
    await Quran.load();
    const surah = Quran.surahs.find((item) => item.id === id);
    if (!surah) {
      throw new Error(`Surah ${id} not found`);
    }

    if (surah.verses.length > 0) {
      return surah;
    }

    const pending = Quran.surahPromises.get(id);
    if (pending) return pending;

    const promise = (async () => {
      try {
        const response = await fetch(`/quran/${id}.json`);
        if (!response.ok) {
          throw new Error(`Failed to fetch /quran/${id}.json: ${response.status}`);
        }
        const data = (await response.json()) as Record<string, RawVerse>;
        const verses: Verse[] = Object.entries(data).map(([verseId, verseData]) =>
          Verse.fromJson(verseId, verseData)
        );
        surah.verses = verses;
        return surah;
      } finally {
        Quran.surahPromises.delete(id);
      }
    })();

    Quran.surahPromises.set(id, promise);
    return promise;
  }

  /**
   * Retrieves a specific verse from a surah
   */
  static async getVerse(surahId: number, verseId: number): Promise<Verse | undefined> {
    const surah = await Quran.getSurah(surahId);
    return surah.verses.find((verse) => verse.id === verseId);
  }
}

export interface QuranWordLookupResult {
  success: boolean;
  location: string;
  word?: string;
  total_words?: number;
  ayah_text?: string;
  surah_name?: string;
  surah?: number;
  ayah?: number;
  word_index?: number;
  transliteration?: string;
  translation?: string;
  error?: string;
}

/**
 * Looks up a Quranic word given a 1-based location string (e.g. "85:1:1") or (surah, ayah, word).
 * Exactly replicates QuranCaption's word lookup without relying on an external engine.
 */
export async function getQuranWordByLocation(
  locationOrSurah: string | number,
  ayahParam?: number,
  wordParam?: number
): Promise<QuranWordLookupResult> {
  let surah = 1;
  let ayah = 1;
  let wordIdx = 1;

  if (typeof locationOrSurah === 'string') {
    const parts = locationOrSurah.trim().split(':');
    if (parts.length === 3) {
      surah = parseInt(parts[0], 10);
      ayah = parseInt(parts[1], 10);
      wordIdx = parseInt(parts[2], 10);
    } else {
      return {
        success: false,
        location: locationOrSurah,
        error: "Invalid location format. Expected 'surah:ayah:word' (e.g. 85:1:1)",
      };
    }
  } else {
    surah = locationOrSurah;
    ayah = ayahParam || 1;
    wordIdx = wordParam || 1;
  }

  const locKey = `${surah}:${ayah}:${wordIdx}`;

  if (surah < 1 || surah > 114) {
    return { success: false, location: locKey, error: `Invalid surah number ${surah}. Must be 1-114.` };
  }
  if (ayah < 1) {
    return { success: false, location: locKey, error: `Invalid ayah number ${ayah}. Must be >= 1.` };
  }
  if (wordIdx < 1) {
    return { success: false, location: locKey, error: `Invalid word index ${wordIdx}. Must be >= 1.` };
  }

  try {
    const surahObj = await Quran.getSurah(surah);
    const verseObj = surahObj.verses.find((v) => v.id === ayah);

    if (!verseObj) {
      return {
        success: false,
        location: locKey,
        error: `Surah ${surah} (${surahObj.name}) has only ${surahObj.totalAyah} ayahs. Ayah ${ayah} not found.`,
      };
    }

    const totalWords = verseObj.words.length;
    if (wordIdx > totalWords) {
      return {
        success: false,
        location: locKey,
        total_words: totalWords,
        error: `Ayah ${surah}:${ayah} has only ${totalWords} words. Word ${wordIdx} out of range.`,
      };
    }

    const wordItem = verseObj.words[wordIdx - 1];
    const fullAyahText = verseObj.getArabicTextBetweenTwoIndexes(0, totalWords - 1);

    return {
      success: true,
      location: locKey,
      word: wordItem.arabic,
      total_words: totalWords,
      ayah_text: fullAyahText,
      surah_name: surahObj.name,
      surah,
      ayah,
      word_index: wordIdx,
      transliteration: wordItem.transliteration,
      translation: wordItem.translation,
    };
  } catch (err: any) {
    return {
      success: false,
      location: locKey,
      error: err?.message || 'Failed to load Quranic data',
    };
  }
}
