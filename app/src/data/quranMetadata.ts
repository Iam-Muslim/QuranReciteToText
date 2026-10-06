export interface SurahMeta {
  surah_number: number;
  surah_name_arabic: string;
  surah_name_english: string;
  num_verses: number;
  type: 'makki' | 'madani';
}

export const QURAN_SURAHS: SurahMeta[] = [
  {
    "surah_number": 1,
    "surah_name_arabic": "ٱلْفَاتِحَةِ",
    "surah_name_english": "Al-Faatiha",
    "num_verses": 7,
    "type": "makki"
  },
  {
    "surah_number": 2,
    "surah_name_arabic": "البَقَرَةِ",
    "surah_name_english": "Al-Baqara",
    "num_verses": 286,
    "type": "madani"
  },
  {
    "surah_number": 3,
    "surah_name_arabic": "آلِ عِمۡرَانَ",
    "surah_name_english": "Aal-i-Imraan",
    "num_verses": 200,
    "type": "madani"
  },
  {
    "surah_number": 4,
    "surah_name_arabic": "النِّسَاءِ",
    "surah_name_english": "An-Nisaa",
    "num_verses": 176,
    "type": "madani"
  },
  {
    "surah_number": 5,
    "surah_name_arabic": "المَائـِدَةِ",
    "surah_name_english": "Al-Maaida",
    "num_verses": 120,
    "type": "madani"
  },
  {
    "surah_number": 6,
    "surah_name_arabic": "الأَنۡعَامِ",
    "surah_name_english": "Al-An'aam",
    "num_verses": 165,
    "type": "makki"
  },
  {
    "surah_number": 7,
    "surah_name_arabic": "الأَعۡرَافِ",
    "surah_name_english": "Al-A'raaf",
    "num_verses": 206,
    "type": "makki"
  },
  {
    "surah_number": 8,
    "surah_name_arabic": "الأَنفَالِ",
    "surah_name_english": "Al-Anfaal",
    "num_verses": 75,
    "type": "madani"
  },
  {
    "surah_number": 9,
    "surah_name_arabic": "التَّوۡبَةِ",
    "surah_name_english": "At-Tawba",
    "num_verses": 129,
    "type": "madani"
  },
  {
    "surah_number": 10,
    "surah_name_arabic": "يُونُسَ",
    "surah_name_english": "Yunus",
    "num_verses": 109,
    "type": "makki"
  },
  {
    "surah_number": 11,
    "surah_name_arabic": "هُودٍ",
    "surah_name_english": "Hud",
    "num_verses": 123,
    "type": "makki"
  },
  {
    "surah_number": 12,
    "surah_name_arabic": "يُوسُفَ",
    "surah_name_english": "Yusuf",
    "num_verses": 111,
    "type": "makki"
  },
  {
    "surah_number": 13,
    "surah_name_arabic": "الرَّعۡدِ",
    "surah_name_english": "Ar-Ra'd",
    "num_verses": 43,
    "type": "makki"
  },
  {
    "surah_number": 14,
    "surah_name_arabic": "إِبۡرَاهِيمَ",
    "surah_name_english": "Ibrahim",
    "num_verses": 52,
    "type": "makki"
  },
  {
    "surah_number": 15,
    "surah_name_arabic": "الحِجۡرِ",
    "surah_name_english": "Al-Hijr",
    "num_verses": 99,
    "type": "makki"
  },
  {
    "surah_number": 16,
    "surah_name_arabic": "النَّحۡلِ",
    "surah_name_english": "An-Nahl",
    "num_verses": 128,
    "type": "makki"
  },
  {
    "surah_number": 17,
    "surah_name_arabic": "الإِسۡرَاءِ",
    "surah_name_english": "Al-Israa",
    "num_verses": 111,
    "type": "makki"
  },
  {
    "surah_number": 18,
    "surah_name_arabic": "الكَهۡفِ",
    "surah_name_english": "Al-Kahf",
    "num_verses": 110,
    "type": "makki"
  },
  {
    "surah_number": 19,
    "surah_name_arabic": "مَرۡيَمَ",
    "surah_name_english": "Maryam",
    "num_verses": 98,
    "type": "makki"
  },
  {
    "surah_number": 20,
    "surah_name_arabic": "طه",
    "surah_name_english": "Taa-Haa",
    "num_verses": 135,
    "type": "makki"
  },
  {
    "surah_number": 21,
    "surah_name_arabic": "الأَنبِيَاءِ",
    "surah_name_english": "Al-Anbiyaa",
    "num_verses": 112,
    "type": "makki"
  },
  {
    "surah_number": 22,
    "surah_name_arabic": "الحَجِّ",
    "surah_name_english": "Al-Hajj",
    "num_verses": 78,
    "type": "madani"
  },
  {
    "surah_number": 23,
    "surah_name_arabic": "المُؤۡمِنُونَ",
    "surah_name_english": "Al-Muminoon",
    "num_verses": 118,
    "type": "makki"
  },
  {
    "surah_number": 24,
    "surah_name_arabic": "النُّورِ",
    "surah_name_english": "An-Noor",
    "num_verses": 64,
    "type": "madani"
  },
  {
    "surah_number": 25,
    "surah_name_arabic": "الفُرۡقَانِ",
    "surah_name_english": "Al-Furqaan",
    "num_verses": 77,
    "type": "makki"
  },
  {
    "surah_number": 26,
    "surah_name_arabic": "الشُّعَرَاءِ",
    "surah_name_english": "Ash-Shu'araa",
    "num_verses": 227,
    "type": "makki"
  },
  {
    "surah_number": 27,
    "surah_name_arabic": "النَّمۡلِ",
    "surah_name_english": "An-Naml",
    "num_verses": 93,
    "type": "makki"
  },
  {
    "surah_number": 28,
    "surah_name_arabic": "القَصَصِ",
    "surah_name_english": "Al-Qasas",
    "num_verses": 88,
    "type": "makki"
  },
  {
    "surah_number": 29,
    "surah_name_arabic": "العَنكَبُوتِ",
    "surah_name_english": "Al-Ankaboot",
    "num_verses": 69,
    "type": "makki"
  },
  {
    "surah_number": 30,
    "surah_name_arabic": "الرُّومِ",
    "surah_name_english": "Ar-Room",
    "num_verses": 60,
    "type": "makki"
  },
  {
    "surah_number": 31,
    "surah_name_arabic": "لُقۡمَانَ",
    "surah_name_english": "Luqman",
    "num_verses": 34,
    "type": "makki"
  },
  {
    "surah_number": 32,
    "surah_name_arabic": "السَّجۡدَةِ",
    "surah_name_english": "As-Sajda",
    "num_verses": 30,
    "type": "makki"
  },
  {
    "surah_number": 33,
    "surah_name_arabic": "الأَحۡزَابِ",
    "surah_name_english": "Al-Ahzaab",
    "num_verses": 73,
    "type": "madani"
  },
  {
    "surah_number": 34,
    "surah_name_arabic": "سَبَإٍ",
    "surah_name_english": "Saba",
    "num_verses": 54,
    "type": "makki"
  },
  {
    "surah_number": 35,
    "surah_name_arabic": "فَاطِرٍ",
    "surah_name_english": "Faatir",
    "num_verses": 45,
    "type": "makki"
  },
  {
    "surah_number": 36,
    "surah_name_arabic": "يسٓ",
    "surah_name_english": "Yaseen",
    "num_verses": 83,
    "type": "makki"
  },
  {
    "surah_number": 37,
    "surah_name_arabic": "الصَّافَّاتِ",
    "surah_name_english": "As-Saaffaat",
    "num_verses": 182,
    "type": "makki"
  },
  {
    "surah_number": 38,
    "surah_name_arabic": "صٓ",
    "surah_name_english": "Saad",
    "num_verses": 88,
    "type": "makki"
  },
  {
    "surah_number": 39,
    "surah_name_arabic": "الزُّمَرِ",
    "surah_name_english": "Az-Zumar",
    "num_verses": 75,
    "type": "makki"
  },
  {
    "surah_number": 40,
    "surah_name_arabic": "غَافِرٍ",
    "surah_name_english": "Ghafir",
    "num_verses": 85,
    "type": "makki"
  },
  {
    "surah_number": 41,
    "surah_name_arabic": "فُصِّلَتۡ",
    "surah_name_english": "Fussilat",
    "num_verses": 54,
    "type": "makki"
  },
  {
    "surah_number": 42,
    "surah_name_arabic": "الشُّورَىٰ",
    "surah_name_english": "Ash-Shura",
    "num_verses": 53,
    "type": "makki"
  },
  {
    "surah_number": 43,
    "surah_name_arabic": "الزُّخۡرُفِ",
    "surah_name_english": "Az-Zukhruf",
    "num_verses": 89,
    "type": "makki"
  },
  {
    "surah_number": 44,
    "surah_name_arabic": "الدُّخَانِ",
    "surah_name_english": "Ad-Dukhaan",
    "num_verses": 59,
    "type": "makki"
  },
  {
    "surah_number": 45,
    "surah_name_arabic": "الجَاثِيَةِ",
    "surah_name_english": "Al-Jaathiya",
    "num_verses": 37,
    "type": "makki"
  },
  {
    "surah_number": 46,
    "surah_name_arabic": "الأَحۡقَافِ",
    "surah_name_english": "Al-Ahqaf",
    "num_verses": 35,
    "type": "makki"
  },
  {
    "surah_number": 47,
    "surah_name_arabic": "مُحَمَّدٍ",
    "surah_name_english": "Muhammad",
    "num_verses": 38,
    "type": "madani"
  },
  {
    "surah_number": 48,
    "surah_name_arabic": "الفَتۡحِ",
    "surah_name_english": "Al-Fath",
    "num_verses": 29,
    "type": "madani"
  },
  {
    "surah_number": 49,
    "surah_name_arabic": "الحُجُرَاتِ",
    "surah_name_english": "Al-Hujuraat",
    "num_verses": 18,
    "type": "madani"
  },
  {
    "surah_number": 50,
    "surah_name_arabic": "قٓ",
    "surah_name_english": "Qaaf",
    "num_verses": 45,
    "type": "makki"
  },
  {
    "surah_number": 51,
    "surah_name_arabic": "الذَّارِيَاتِ",
    "surah_name_english": "Adh-Dhaariyat",
    "num_verses": 60,
    "type": "makki"
  },
  {
    "surah_number": 52,
    "surah_name_arabic": "الطُّورِ",
    "surah_name_english": "At-Tur",
    "num_verses": 49,
    "type": "makki"
  },
  {
    "surah_number": 53,
    "surah_name_arabic": "النَّجۡمِ",
    "surah_name_english": "An-Najm",
    "num_verses": 62,
    "type": "makki"
  },
  {
    "surah_number": 54,
    "surah_name_arabic": "القَمَرِ",
    "surah_name_english": "Al-Qamar",
    "num_verses": 55,
    "type": "makki"
  },
  {
    "surah_number": 55,
    "surah_name_arabic": "الرَّحۡمَٰن",
    "surah_name_english": "Ar-Rahmaan",
    "num_verses": 78,
    "type": "makki"
  },
  {
    "surah_number": 56,
    "surah_name_arabic": "الوَاقِعَةِ",
    "surah_name_english": "Al-Waaqia",
    "num_verses": 96,
    "type": "makki"
  },
  {
    "surah_number": 57,
    "surah_name_arabic": "الحَدِيدِ",
    "surah_name_english": "Al-Hadid",
    "num_verses": 29,
    "type": "madani"
  },
  {
    "surah_number": 58,
    "surah_name_arabic": "المُجَادلَةِ",
    "surah_name_english": "Al-Mujaadila",
    "num_verses": 22,
    "type": "madani"
  },
  {
    "surah_number": 59,
    "surah_name_arabic": "الحَشۡرِ",
    "surah_name_english": "Al-Hashr",
    "num_verses": 24,
    "type": "madani"
  },
  {
    "surah_number": 60,
    "surah_name_arabic": "المُمۡتَحنَةِ",
    "surah_name_english": "Al-Mumtahana",
    "num_verses": 13,
    "type": "madani"
  },
  {
    "surah_number": 61,
    "surah_name_arabic": "الصَّفِّ",
    "surah_name_english": "As-Saff",
    "num_verses": 14,
    "type": "madani"
  },
  {
    "surah_number": 62,
    "surah_name_arabic": "الجُمُعَةِ",
    "surah_name_english": "Al-Jumu'a",
    "num_verses": 11,
    "type": "madani"
  },
  {
    "surah_number": 63,
    "surah_name_arabic": "المُنَافِقُونَ",
    "surah_name_english": "Al-Munaafiqoon",
    "num_verses": 11,
    "type": "madani"
  },
  {
    "surah_number": 64,
    "surah_name_arabic": "التَّغَابُنِ",
    "surah_name_english": "At-Taghaabun",
    "num_verses": 18,
    "type": "madani"
  },
  {
    "surah_number": 65,
    "surah_name_arabic": "الطَّلَاقِ",
    "surah_name_english": "At-Talaaq",
    "num_verses": 12,
    "type": "madani"
  },
  {
    "surah_number": 66,
    "surah_name_arabic": "التَّحۡرِيمِ",
    "surah_name_english": "At-Tahrim",
    "num_verses": 12,
    "type": "madani"
  },
  {
    "surah_number": 67,
    "surah_name_arabic": "المُلۡكِ",
    "surah_name_english": "Al-Mulk",
    "num_verses": 30,
    "type": "makki"
  },
  {
    "surah_number": 68,
    "surah_name_arabic": "القَلَمِ",
    "surah_name_english": "Al-Qalam",
    "num_verses": 52,
    "type": "makki"
  },
  {
    "surah_number": 69,
    "surah_name_arabic": "الحَاقَّةِ",
    "surah_name_english": "Al-Haaqqa",
    "num_verses": 52,
    "type": "makki"
  },
  {
    "surah_number": 70,
    "surah_name_arabic": "المَعَارِجِ",
    "surah_name_english": "Al-Ma'aarij",
    "num_verses": 44,
    "type": "makki"
  },
  {
    "surah_number": 71,
    "surah_name_arabic": "نُوحٍ",
    "surah_name_english": "Nooh",
    "num_verses": 28,
    "type": "makki"
  },
  {
    "surah_number": 72,
    "surah_name_arabic": "الجِنِّ",
    "surah_name_english": "Al-Jinn",
    "num_verses": 28,
    "type": "makki"
  },
  {
    "surah_number": 73,
    "surah_name_arabic": "المُزَّمِّلِ",
    "surah_name_english": "Al-Muzzammil",
    "num_verses": 20,
    "type": "makki"
  },
  {
    "surah_number": 74,
    "surah_name_arabic": "المُدَّثِّرِ",
    "surah_name_english": "Al-Muddaththir",
    "num_verses": 56,
    "type": "makki"
  },
  {
    "surah_number": 75,
    "surah_name_arabic": "القِيَامَةِ",
    "surah_name_english": "Al-Qiyaama",
    "num_verses": 40,
    "type": "makki"
  },
  {
    "surah_number": 76,
    "surah_name_arabic": "الإِنسَانِ",
    "surah_name_english": "Al-Insaan",
    "num_verses": 31,
    "type": "makki"
  },
  {
    "surah_number": 77,
    "surah_name_arabic": "المُرۡسَلَاتِ",
    "surah_name_english": "Al-Mursalaat",
    "num_verses": 50,
    "type": "makki"
  },
  {
    "surah_number": 78,
    "surah_name_arabic": "النَّبَإِ",
    "surah_name_english": "An-Naba",
    "num_verses": 40,
    "type": "makki"
  },
  {
    "surah_number": 79,
    "surah_name_arabic": "النَّازِعَاتِ",
    "surah_name_english": "An-Naazi'aat",
    "num_verses": 46,
    "type": "makki"
  },
  {
    "surah_number": 80,
    "surah_name_arabic": "عَبَسَ",
    "surah_name_english": "Abasa",
    "num_verses": 42,
    "type": "makki"
  },
  {
    "surah_number": 81,
    "surah_name_arabic": "التَّكۡوِيرِ",
    "surah_name_english": "At-Takwir",
    "num_verses": 29,
    "type": "makki"
  },
  {
    "surah_number": 82,
    "surah_name_arabic": "الانفِطَارِ",
    "surah_name_english": "Al-Infitaar",
    "num_verses": 19,
    "type": "makki"
  },
  {
    "surah_number": 83,
    "surah_name_arabic": "المُطَفِّفِينَ",
    "surah_name_english": "Al-Mutaffifin",
    "num_verses": 36,
    "type": "makki"
  },
  {
    "surah_number": 84,
    "surah_name_arabic": "الانشِقَاقِ",
    "surah_name_english": "Al-Inshiqaaq",
    "num_verses": 25,
    "type": "makki"
  },
  {
    "surah_number": 85,
    "surah_name_arabic": "البُرُوجِ",
    "surah_name_english": "Al-Burooj",
    "num_verses": 22,
    "type": "makki"
  },
  {
    "surah_number": 86,
    "surah_name_arabic": "الطَّارِقِ",
    "surah_name_english": "At-Taariq",
    "num_verses": 17,
    "type": "makki"
  },
  {
    "surah_number": 87,
    "surah_name_arabic": "الأَعۡلَىٰ",
    "surah_name_english": "Al-A'laa",
    "num_verses": 19,
    "type": "makki"
  },
  {
    "surah_number": 88,
    "surah_name_arabic": "الغَاشِيَةِ",
    "surah_name_english": "Al-Ghaashiya",
    "num_verses": 26,
    "type": "makki"
  },
  {
    "surah_number": 89,
    "surah_name_arabic": "الفَجۡرِ",
    "surah_name_english": "Al-Fajr",
    "num_verses": 30,
    "type": "makki"
  },
  {
    "surah_number": 90,
    "surah_name_arabic": "البَلَدِ",
    "surah_name_english": "Al-Balad",
    "num_verses": 20,
    "type": "makki"
  },
  {
    "surah_number": 91,
    "surah_name_arabic": "الشَّمۡسِ",
    "surah_name_english": "Ash-Shams",
    "num_verses": 15,
    "type": "makki"
  },
  {
    "surah_number": 92,
    "surah_name_arabic": "اللَّيۡلِ",
    "surah_name_english": "Al-Lail",
    "num_verses": 21,
    "type": "makki"
  },
  {
    "surah_number": 93,
    "surah_name_arabic": "الضُّحَىٰ",
    "surah_name_english": "Ad-Dhuhaa",
    "num_verses": 11,
    "type": "makki"
  },
  {
    "surah_number": 94,
    "surah_name_arabic": "الشَّرۡحِ",
    "surah_name_english": "Ash-Sharh",
    "num_verses": 8,
    "type": "makki"
  },
  {
    "surah_number": 95,
    "surah_name_arabic": "التِّينِ",
    "surah_name_english": "At-Tin",
    "num_verses": 8,
    "type": "makki"
  },
  {
    "surah_number": 96,
    "surah_name_arabic": "العَلَقِ",
    "surah_name_english": "Al-Alaq",
    "num_verses": 19,
    "type": "makki"
  },
  {
    "surah_number": 97,
    "surah_name_arabic": "القَدۡرِ",
    "surah_name_english": "Al-Qadr",
    "num_verses": 5,
    "type": "makki"
  },
  {
    "surah_number": 98,
    "surah_name_arabic": "البَيِّنَةِ",
    "surah_name_english": "Al-Bayyina",
    "num_verses": 8,
    "type": "makki"
  },
  {
    "surah_number": 99,
    "surah_name_arabic": "الزَّلۡزَلَةِ",
    "surah_name_english": "Az-Zalzala",
    "num_verses": 8,
    "type": "makki"
  },
  {
    "surah_number": 100,
    "surah_name_arabic": "العَادِيَاتِ",
    "surah_name_english": "Al-Aadiyaat",
    "num_verses": 11,
    "type": "makki"
  },
  {
    "surah_number": 101,
    "surah_name_arabic": "القَارِعَةِ",
    "surah_name_english": "Al-Qaari'a",
    "num_verses": 11,
    "type": "makki"
  },
  {
    "surah_number": 102,
    "surah_name_arabic": "التَّكَاثُرِ",
    "surah_name_english": "At-Takaathur",
    "num_verses": 8,
    "type": "makki"
  },
  {
    "surah_number": 103,
    "surah_name_arabic": "العَصۡرِ",
    "surah_name_english": "Al-Asr",
    "num_verses": 3,
    "type": "makki"
  },
  {
    "surah_number": 104,
    "surah_name_arabic": "الهُمَزَةِ",
    "surah_name_english": "Al-Humaza",
    "num_verses": 9,
    "type": "makki"
  },
  {
    "surah_number": 105,
    "surah_name_arabic": "الفِيلِ",
    "surah_name_english": "Al-Fil",
    "num_verses": 5,
    "type": "makki"
  },
  {
    "surah_number": 106,
    "surah_name_arabic": "قُرَيۡشٍ",
    "surah_name_english": "Quraish",
    "num_verses": 4,
    "type": "makki"
  },
  {
    "surah_number": 107,
    "surah_name_arabic": "المَاعُونِ",
    "surah_name_english": "Al-Maa'un",
    "num_verses": 7,
    "type": "makki"
  },
  {
    "surah_number": 108,
    "surah_name_arabic": "الكَوۡثَرِ",
    "surah_name_english": "Al-Kawthar",
    "num_verses": 3,
    "type": "makki"
  },
  {
    "surah_number": 109,
    "surah_name_arabic": "الكَافِرُونَ",
    "surah_name_english": "Al-Kaafiroon",
    "num_verses": 6,
    "type": "makki"
  },
  {
    "surah_number": 110,
    "surah_name_arabic": "النَّصۡرِ",
    "surah_name_english": "An-Nasr",
    "num_verses": 3,
    "type": "madani"
  },
  {
    "surah_number": 111,
    "surah_name_arabic": "المَسَدِ",
    "surah_name_english": "Al-Masad",
    "num_verses": 5,
    "type": "makki"
  },
  {
    "surah_number": 112,
    "surah_name_arabic": "الإِخۡلَاصِ",
    "surah_name_english": "Al-Ikhlaas",
    "num_verses": 4,
    "type": "makki"
  },
  {
    "surah_number": 113,
    "surah_name_arabic": "الفَلَقِ",
    "surah_name_english": "Al-Falaq",
    "num_verses": 5,
    "type": "makki"
  },
  {
    "surah_number": 114,
    "surah_name_arabic": "النَّاسِ",
    "surah_name_english": "An-Naas",
    "num_verses": 6,
    "type": "makki"
  }
];
