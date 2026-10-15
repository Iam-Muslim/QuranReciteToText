/**
 * Riwayah & Canonical Qira'at Provider
 * Handles the 8 canonical Riwayat with cross-Riwayah Ayah mapping,
 * verse count synchronization, and font/script resolving.
 * Adapted directly from QuranCaption's RiwayahProvider.
 */

export const RIWAYAH_OPTIONS = [
  'Hafs',
  'Warsh',
  'Qaloon',
  'Shouba',
  'Doori',
  'Soosi',
  'Bazzi',
  'Qumbul'
] as const;

export type Riwayah = (typeof RIWAYAH_OPTIONS)[number];
export type NonHafsRiwayah = Exclude<Riwayah, 'Hafs'>;

export interface RiwayahMetadata {
  id: Riwayah;
  arabicName: string;
  englishName: string;
  readerArabic: string;
  readerEnglish: string;
  slug?: string;
  fontFamily?: string;
}

export const RIWAYAT_METADATA: Record<Riwayah, RiwayahMetadata> = {
  Hafs: {
    id: 'Hafs',
    arabicName: 'حفص عن عاصم',
    englishName: "Hafs 'an 'Asim",
    readerArabic: 'عاصم بن أبي النجود الكوفي',
    readerEnglish: "'Asim al-Kufi",
  },
  Warsh: {
    id: 'Warsh',
    arabicName: 'ورش عن نافع',
    englishName: "Warsh 'an Nafi'",
    readerArabic: 'نافع بن عبد الرحمن المدني',
    readerEnglish: "Nafi' al-Madani",
    slug: 'warsh',
    fontFamily: 'warsh10',
  },
  Qaloon: {
    id: 'Qaloon',
    arabicName: 'قالون عن نافع',
    englishName: "Qalun 'an Nafi'",
    readerArabic: 'نافع بن عبد الرحمن المدني',
    readerEnglish: "Nafi' al-Madani",
    slug: 'qaloon',
    fontFamily: 'qaloon10',
  },
  Shouba: {
    id: 'Shouba',
    arabicName: 'شعبة عن عاصم',
    englishName: "Shu'bah 'an 'Asim",
    readerArabic: 'عاصم بن أبي النجود الكوفي',
    readerEnglish: "'Asim al-Kufi",
    slug: 'shouba',
    fontFamily: 'shouba8',
  },
  Doori: {
    id: 'Doori',
    arabicName: 'الدوري عن أبي عمرو',
    englishName: "Al-Duri 'an Abi 'Amr",
    readerArabic: 'أبو عمرو بن العلاء البصري',
    readerEnglish: "Abu 'Amr al-Basri",
    slug: 'doori',
    fontFamily: 'doori9',
  },
  Soosi: {
    id: 'Soosi',
    arabicName: 'السوسي عن أبي عمرو',
    englishName: "Al-Susi 'an Abi 'Amr",
    readerArabic: 'أبو عمرو بن العلاء البصري',
    readerEnglish: "Abu 'Amr al-Basri",
    slug: 'soosi',
    fontFamily: 'soosi9',
  },
  Bazzi: {
    id: 'Bazzi',
    arabicName: 'البزي عن ابن كثير',
    englishName: "Al-Bazzi 'an Ibn Kathir",
    readerArabic: 'عبد الله بن كثير المكي',
    readerEnglish: "Ibn Kathir al-Makki",
    slug: 'bazzi',
    fontFamily: 'bazzi7',
  },
  Qumbul: {
    id: 'Qumbul',
    arabicName: 'قنبل عن ابن كثير',
    englishName: "Qumbul 'an Ibn Kathir",
    readerArabic: 'عبد الله بن كثير المكي',
    readerEnglish: "Ibn Kathir al-Makki",
    slug: 'qumbul',
    fontFamily: 'qumbul7',
  },
};

type RiwayahWord = {
  text: string;
  owner: number;
  source: number[];
  verseEnd?: number;
};

type RiwayahPayload = {
  verses: Record<string, { words: RiwayahWord[] }>;
};

type RiwayahAyahMapping = {
  hafs_to_riwayah: Record<string, Record<string, { targets: number[]; relation: string }>>;
  riwayah_to_hafs: Record<string, Record<string, { targets: number[]; relation: string }>>;
};

type RiwayahData = {
  verses: RiwayahPayload['verses'];
  mapping: RiwayahAyahMapping;
};

export type RiwayahRenderSlice = {
  text: string;
  words: string[];
  sourceWordIndexes: number[][];
  suffix: string;
  targetAyahs: number[];
  relation: string;
};

const dataCache = new Map<NonHafsRiwayah, RiwayahData>();
const loadingPromises = new Map<NonHafsRiwayah, Promise<void>>();

function formatArabicNumber(value: number): string {
  return value.toString().replace(/\d/g, (digit) => '٠١٢٣٤٥٦٧٨٩'[Number(digit)]);
}

async function loadRiwayahData(riwayah: NonHafsRiwayah): Promise<void> {
  if (dataCache.has(riwayah)) return;
  const currentPromise = loadingPromises.get(riwayah);
  if (currentPromise) return currentPromise;

  const slug = RIWAYAT_METADATA[riwayah]?.slug;
  if (!slug) return;

  const loadingPromise = Promise.all([
    fetch(`/riwayat/${slug}/verses.json`),
    fetch(`/riwayat/${slug}/ayah-map.json`)
  ])
    .then(async ([versesResponse, mappingResponse]) => {
      if (!versesResponse.ok) {
        throw new Error(`Failed to load ${riwayah} verses: ${versesResponse.status}`);
      }
      if (!mappingResponse.ok) {
        throw new Error(`Failed to load Hafs/${riwayah} ayah mapping: ${mappingResponse.status}`);
      }
      const [payload, mapping] = await Promise.all([
        versesResponse.json() as Promise<RiwayahPayload>,
        mappingResponse.json() as Promise<RiwayahAyahMapping>
      ]);
      dataCache.set(riwayah, { verses: payload.verses, mapping });
    })
    .finally(() => loadingPromises.delete(riwayah));

  loadingPromises.set(riwayah, loadingPromise);
  return loadingPromise;
}

export function isRiwayah(value: unknown): value is Riwayah {
  return typeof value === 'string' && RIWAYAH_OPTIONS.includes(value as Riwayah);
}

export function isNonHafsRiwayah(value: unknown): value is NonHafsRiwayah {
  return isRiwayah(value) && value !== 'Hafs';
}

export function normalizeRiwayahKey(value: string | undefined): Riwayah {
  if (!value) return 'Hafs';
  const v = value.toLowerCase().trim();
  if (v.includes('warsh') || v.includes('ورش')) return 'Warsh';
  if (v.includes('qalun') || v.includes('qaloon') || v.includes('قالون')) return 'Qaloon';
  if (v.includes('duri') || v.includes('doori') || v.includes('دوري')) return 'Doori';
  if (v.includes('susi') || v.includes('soosi') || v.includes('سوسي')) return 'Soosi';
  if (v.includes('shu') || v.includes('shouba') || v.includes('شعبة')) return 'Shouba';
  if (v.includes('bazzi') || v.includes('بزي')) return 'Bazzi';
  if (v.includes('qumbul') || v.includes('قنبل')) return 'Qumbul';
  return 'Hafs';
}

export class RiwayahProvider {
  static async prefetch(riwayah: NonHafsRiwayah): Promise<void> {
    await loadRiwayahData(riwayah);
  }

  static isReady(riwayah: NonHafsRiwayah): boolean {
    return dataCache.has(riwayah);
  }

  /**
   * Translates a Hafs Ayah number to the corresponding Ayah number(s) in the target Riwayah.
   */
  static hafsToRiwayahAyahs(riwayah: NonHafsRiwayah, surah: number, hafsAyah: number): number[] {
    const data = dataCache.get(riwayah);
    if (!data) {
      void loadRiwayahData(riwayah);
      return [hafsAyah];
    }
    const surahMapping = data.mapping.hafs_to_riwayah[String(surah)];
    const entry = surahMapping?.[String(hafsAyah)];
    return entry?.targets && entry.targets.length > 0 ? entry.targets : [hafsAyah];
  }

  /**
   * Translates a target Riwayah Ayah number back to the canonical Hafs Ayah number(s).
   */
  static riwayahToHafsAyahs(riwayah: NonHafsRiwayah, surah: number, riwayahAyah: number): number[] {
    const data = dataCache.get(riwayah);
    if (!data) {
      void loadRiwayahData(riwayah);
      return [riwayahAyah];
    }
    const surahMapping = data.mapping.riwayah_to_hafs[String(surah)];
    const entry = surahMapping?.[String(riwayahAyah)];
    return entry?.targets && entry.targets.length > 0 ? entry.targets : [riwayahAyah];
  }

  /**
   * Returns verse slice aligned from Hafs word index range into the target Riwayah words.
   */
  static getVerseSlice(
    riwayah: NonHafsRiwayah,
    surah: number,
    verse: number,
    startWordIndex: number,
    endWordIndex: number,
    showVerseNumbers = true
  ): RiwayahRenderSlice | null {
    const data = dataCache.get(riwayah);
    if (!data) {
      void loadRiwayahData(riwayah);
      return null;
    }

    const key = `${surah}:${verse}`;
    const verseData = data.verses[key];
    const mapping = data.mapping.hafs_to_riwayah[String(surah)]?.[String(verse)];
    if (!verseData || !mapping) return null;

    const selectedWords = verseData.words.filter(
      (word) => word.owner >= startWordIndex && word.owner <= endWordIndex
    );
    const words = selectedWords.map((word) => word.text);
    let suffix = '';
    if (showVerseNumbers) {
      for (let index = 0; index < selectedWords.length; index++) {
        const verseEnd = selectedWords[index].verseEnd;
        if (!verseEnd) continue;
        const number = formatArabicNumber(verseEnd);
        if (index === selectedWords.length - 1) suffix = ` ${number}`;
        else words[index] += `\u00A0${number}`;
      }
    }

    return {
      text: words.join(' '),
      words,
      sourceWordIndexes: selectedWords.map((word) => word.source),
      suffix,
      targetAyahs: mapping.targets,
      relation: mapping.relation
    };
  }
}

export default RiwayahProvider;
