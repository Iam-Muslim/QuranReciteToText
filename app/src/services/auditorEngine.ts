/**
 * Pure-TypeScript Auditor Engine for Quranic Recitation Datasets.
 *
 * Implements high-precision, pipeline-aware acoustic & phonetic diagnostics:
 * 1. Pipeline-Aware Sequence Diagnostics:
 *    - Respects normal Quranic Waqf & Ibtida (breath group resumptions).
 *    - Catches internal within-segment trellis match inversions.
 *    - Catches the Surah Al-Buruj twin phrase leap & regression dip across segments.
 * 2. Normalized Phoneme Coverage Analysis vs Medina Reference (collapses Tajweed elongation tokens).
 * 3. Madd-Aware Physical Duration Limits (prevents false positives on Tahqiq elongations).
 * 4. Ayah-Wide Missing Word Coverage Gap Detection.
 * 5. VAD Pause Boundary Stripping at silence edges.
 * 6. User Verification Tracking (reviewed warnings stay green and update health).
 */

import type { AlignedWord, AyahSegment, ConfidenceIssue, SurahItem } from '../types/aligner';

// Diacritics and zero-cost Tajweed pause marks to strip for phonetic comparison
const TASHKEEL_REGEX = /[\u064B-\u0652\u0670\u0640\u06D6-\u06ED\u0686\u0619]/g;

// Arabic single-consonant connectives that legitimately have micro-duration (60-90ms)
const SINGLE_LETTER_PARTICLES = new Set(['و', 'ف', 'ب', 'ل', 'ك', 'س']);

/**
 * Normalizes phonetic string for robust base-letter comparison.
 * Collapses Tajweed elongation vowels (اااا -> ا) and nasal Ghunnah markers (ںںں -> ن)
 * so that differing CTC token granularities do not produce false truncation warnings.
 */
export function normalizeForPhonemeComparison(str: string): string {
  if (!str) return '';
  return str
    .replace(TASHKEEL_REGEX, '')
    .replace(/ۦ/g, 'ي')
    .replace(/ۥ/g, 'و')
    .replace(/ں/g, 'ن')
    .replace(/(.)\1+/g, '$1'); // collapse consecutive identical phonetic tokens
}

/**
 * Calculates the base phonetic coverage ratio between acoustic tokens and canonical Medina reference.
 * Returns a value between 0.0 and 1.0.
 */
export function computeWordPhonemeCoverage(w: AlignedWord): number {
  if (!w.ref || !w.phonemes || w.phonemes.length === 0) {
    return 1.0;
  }

  const cleanRef = normalizeForPhonemeComparison(w.ref);
  if (cleanRef.length === 0) return 1.0;

  const rawAc = w.phonemes.map(p => p.phoneme || '').join('');
  const cleanAc = normalizeForPhonemeComparison(rawAc);

  return Math.min(1.0, cleanAc.length / cleanRef.length);
}

/**
 * Checks if a word contains legitimate Madd elongation (Tabii, Muttasil, Munfasil, Lazim, Arid).
 * Words with Madd can legitimately exceed 3.5s in slow recitation (Tahqiq).
 */
export function isMaddWord(w: AlignedWord): boolean {
  const ref = w.ref || '';
  const uthmani = w.word || '';

  // 1. Check Uthmani Maddah sign (ٓ or ~)
  if (/[\u0653~]/.test(uthmani) || /[\u0653~]/.test(ref)) {
    return true;
  }

  // 2. Check phonetic mora expansions (اا = 2, ۦۦ = 2, ۥۥ = 2, ۦۦۦۦ = 4, :4, :6)
  if (/اا|ۦۦ|ۥۥ|:4|:6/.test(ref)) {
    return true;
  }

  // 3. Check phoneme token rule annotations if present
  if (w.phonemes && w.phonemes.some(p => p.golden_len && p.golden_len >= 4)) {
    return true;
  }

  return false;
}

/**
 * Estimates the minimum expected recitation duration (in seconds) based on mora count.
 */
export function estimateExpectedDuration(w: AlignedWord, avgMoraTimeSec: number = 0.065): number {
  const cleanRef = (w.ref || w.word || '').replace(TASHKEEL_REGEX, '');
  const moraCount = Math.max(1, cleanRef.length);
  return Math.max(0.10, moraCount * avgMoraTimeSec);
}

/**
 * Parses location string 'surah:ayah:word' into numeric parts.
 */
export function parseLocation(loc?: string): [number, number, number] | null {
  if (!loc) return null;
  const parts = loc.split(':').map(Number);
  if (parts.length === 3 && !parts.some(isNaN)) {
    return [parts[0], parts[1], parts[2]];
  }
  return null;
}

export interface TajweedBridgeInfo {
  ruleName: string;
  detail: string;
}

const MUTAJANIS_PAIRS = new Set(['دت', 'تد', 'تط', 'طت', 'ذظ', 'ثذ', 'بم', 'لر', 'قك']);
const IKHFA_LETTERS = new Set(['ص', 'ذ', 'ث', 'ك', 'ج', 'ش', 'ق', 'س', 'د', 'ط', 'ز', 'ف', 'ت', 'ض', 'ظ']);

/**
 * Detects cross-word Tajweed boundary assimilation (Iqlab, Idgham Mutamathilayn, Idgham Ghunnah, 
 * Mutajanisayn, Ikhfa Shafawi, Wasl Madd Elision).
 * Identifies boundaries where merged letters often cause aligner timing shifts.
 */
export function detectTajweedBoundaryBridge(w1: AlignedWord, w2: AlignedWord): TajweedBridgeInfo | null {
  if (!w1 || !w2) return null;
  const dur1 = Math.max(0, w1.end - w1.start);
  const dur2 = Math.max(0, w2.end - w2.start);

  const clean1 = (w1.word || '').replace(TASHKEEL_REGEX, '').trim();
  const clean2 = (w2.word || '').replace(TASHKEEL_REGEX, '').trim();
  if (!clean1 || !clean2) return null;

  const lastChar1 = clean1.slice(-1);
  const firstChar2 = clean2[0];

  const hasBridgeFlag = (w1.phonemes || []).some(p => (p as any).is_assimilated_bridge);
  
  // Robust check for Noon Sakinah (both unvowelled & vowelled) or Tanween
  const endsWithNoon = clean1.endsWith('ن');
  const endsWithTanween = /[ًٌٍ\u064B\u064C\u064D]/.test(w1.word) || 
                          /[\u06E2\u06ED]/.test(w1.word) || 
                          (w1.ref && (w1.ref.includes('۾') || w1.ref.includes('ں')));
  const isNoonOrTanween = endsWithNoon || endsWithTanween;

  // 1. Iqlab: Noon/Tanween before Baa (e.g. من بعد -> مم بعد, عليم بذات -> عليمم بذات)
  if (isNoonOrTanween && firstChar2 === 'ب') {
    return {
      ruleName: 'إقلاب (ن/تنوين ← م قبل ب)',
      detail: `انقلبت النون/التنوين إلى ميم مخفاة عند الباء ("${w1.word}" ⇥ "${w2.word}")؛ راجع موضع الفاصل الزمني المشترك`,
    };
  }

  // 2. Ikhfa' Shafawi: Meem before Baa (e.g. ترميهم بحجارة, يعتصم بالله)
  if (clean1.endsWith('م') && firstChar2 === 'ب' && clean1.length > 1) {
    return {
      ruleName: 'إخفاء شفوي (م ← ب)',
      detail: `التقاء الشفتين للميم المخفاة مع الباء بغنة حركتين ("${w1.word}" ⇥ "${w2.word}")؛ موضع القطع متداخل`,
    };
  }

  // 3. Idgham Mutamathilayn: Identical consonants across boundary (e.g. ت + ت, د + د, ب + ب, ك + ك, ل + ل, م + م)
  if (lastChar1 && firstChar2 && lastChar1 === firstChar2 && !['ا', 'ى'].includes(lastChar1)) {
    return {
      ruleName: `إدغام متماثلين (${lastChar1} ← ${firstChar2})`,
      detail: `حرفان متطابقان التقيا عند الفاصل ("${w1.word}" ⇥ "${w2.word}") وأصبحا صوتاً مشدداً واحداً`,
    };
  }

  // 4. Idgham Mutajanisayn & Mutaqaribayn (e.g. قد تبين, أثقلت دعوا, يللهث ذلك, اركب معنا, قل رب)
  const pairKey = lastChar1 + firstChar2;
  if (MUTAJANIS_PAIRS.has(pairKey)) {
    return {
      ruleName: `إدغام متجانسين/متقاربين (${lastChar1} ← ${firstChar2})`,
      detail: `أُدغم الحرف الأول بالكامل في الثاني ("${w1.word}" ⇥ "${w2.word}")؛ راجع نقطة القطع المشتركة`,
    };
  }

  // 5. Idgham with Ghunnah (ي، ن، م، و)
  if (isNoonOrTanween && /^[ينمو]/.test(firstChar2)) {
    return {
      ruleName: `إدغام بغنة (ن/تنوين ← ${firstChar2})`,
      detail: `إدغام بغنة وصلاً بين الكلمتين ("${w1.word}" ⇥ "${w2.word}")؛ تشاركا في الغنة المشددة`,
    };
  }

  // 6. Idgham without Ghunnah (ل، ر)
  if (isNoonOrTanween && /^[لر]/.test(firstChar2)) {
    return {
      ruleName: `إدغام بغير غنة (ن/تنوين ← ${firstChar2})`,
      detail: `إدغام كامل بغير غنة ("${w1.word}" ⇥ "${w2.word}")؛ راجع ضبط الفاصل الزمني بينهما`,
    };
  }

  // 7. Dropping Madd vowel before Hamzatul Wasl (e.g. وقالوا الحمد, في الأرض, إذا السماء)
  const endsWithMadd = clean1.endsWith('وا') || clean1.endsWith('ي') || clean1.endsWith('ى') || (clean1.endsWith('ا') && clean1.length > 1);
  const startsWithWasl = w2.word.startsWith('ٱ') || clean2.startsWith('ال') || w2.word.startsWith('ٱل');
  if (endsWithMadd && startsWithWasl) {
    if (hasBridgeFlag || dur1 < 0.22 || dur2 < 0.22 || Math.abs(dur1 - dur2) > 0.7) {
      return {
        ruleName: 'سقوط حرف مد وصلاً (التقاء ساكنين)',
        detail: `سقط حرف المد وصلاً لالتقاء الساكنين ("${w1.word}" ⇥ "${w2.word}")؛ قد يمتد توقيت الأولى ويسرق بداية الثانية`,
      };
    }
  }

  // 8. Ikhfa' Haqiqi: Noon/Tanween before the 15 Ikhfa letters
  if (isNoonOrTanween && IKHFA_LETTERS.has(firstChar2)) {
    if (hasBridgeFlag || dur1 < 0.20 || dur2 < 0.20 || Math.abs(dur1 - dur2) > 0.7) {
      return {
        ruleName: `إخفاء حقيقي (ن/تنوين ← ${firstChar2})`,
        detail: `غنة إخفاء ممتدة قبل مخرج الحرف ("${w1.word}" ⇥ "${w2.word}")؛ راجع الفاصل الزمني`,
      };
    }
  }

  // 9. Aligner assimilated bridge token
  if (hasBridgeFlag) {
    return {
      ruleName: 'فاصل دمج تجويدي',
      detail: `تم دمج وتوزيع صوت الحرف المشترك بين الكلمتين ("${w1.word}" ⇥ "${w2.word}")`,
    };
  }

  return null;
}

/**
 * Deeply audits all words and segments in a Surah, generating a comprehensive list of actionable issues.
 */
export function auditSurah(
  surah: SurahItem,
  resolvedIds: Set<string> = new Set(),
  warningThreshold: number = 0.85
): ConfidenceIssue[] {
  const issues: ConfidenceIssue[] = [];
  const surahNum = surah.surah_number;

  // ─────────────────────────────────────────────────────────────────────────────
  // 1. SEQUENCE INVERSIONS & TWIN LEAPS (PIPELINE-AWARE)
  // ─────────────────────────────────────────────────────────────────────────────
  // A. WITHIN-SEGMENT MONOTONICITY:
  // Inside a single uninterrupted breath segment, words MUST move strictly forward.
  // If word i+1 is smaller than word i inside the SAME segment, that is a true match inversion.
  for (const a of surah.ayahs) {
    const segs = a.segments || [];

    for (let sIdx = 0; sIdx < segs.length; sIdx++) {
      const seg = segs[sIdx];
      const words = seg.words || [];

      for (let wIdx = 0; wIdx < words.length - 1; wIdx++) {
        const curWord = words[wIdx];
        const nextWord = words[wIdx + 1];

        const curLoc = parseLocation(curWord.location);
        const nextLoc = parseLocation(nextWord.location);

        if (curLoc && nextLoc && curLoc[1] === nextLoc[1]) {
          const cW = curLoc[2];
          const nW = nextLoc[2];

          // Strictly ascending within one segment
          if (nW <= cW) {
            const issueId = `inv_seg_${sIdx}_${nextWord.location}`;
            issues.push({
              id: issueId,
              surah_number: surahNum,
              ayah_number: a.ayah,
              location: nextWord.location,
              word: nextWord.word,
              timestamp: nextWord.start,
              score: nextWord.score,
              type: 'sequence_inversion',
              message: `قلب ترتيبي داخلي في المقطع ${sIdx + 1}: كلمة "${nextWord.word}" (${nW}) جاءت صوتياً بعد "${curWord.word}" (${cW})`,
              severity: 'critical',
              resolved: resolvedIds.has(issueId) || !!nextWord.is_verified,
              duration: round(nextWord.end - nextWord.start, 2),
              ref: nextWord.ref,
            });
          }
        }
      }
    }
  }

  // B. ACROSS-SEGMENT REGRESSION DIPS (SURAH AL-BURUJ TWIN PHRASE BUG):
  // In normal recitation with Waqf & Ibtida (e.g. Surah Taha 10):
  // Seg 1 ends at word 9, Seg 2 resumes at 4 and ends at 13, Seg 3 resumes at 10 and ends at 18.
  // The furthest word reached is monotonically increasing: 9 -> 13 -> 18!
  // In Al-Buruj bug:
  // Seg 1 ends at 10.
  // Seg 2 leaps forward to 11..12 (end = 12).
  // Seg 3 regresses back to word 10 (end = 10 < 12) - an isolated backward dip!
  // Seg 4 continues 11..13 (end = 13).
  // We detect any segment k+1 whose max word regresses behind segment k, when followed by a segment reaching >= k.
  for (const a of surah.ayahs) {
    const segs = a.segments || [];
    if (segs.length < 2) continue;

    interface SegRange {
      seg: AyahSegment;
      segIndex: number;
      minWord: number;
      maxWord: number;
      isRepetition: boolean;
      words: AlignedWord[];
    }

    const ranges: SegRange[] = [];
    for (let sIdx = 0; sIdx < segs.length; sIdx++) {
      const s = segs[sIdx];
      const sWords = s.words || [];
      if (sWords.length === 0) continue;

      let minW = Infinity;
      let maxW = -Infinity;
      for (const w of sWords) {
        const parsed = parseLocation(w.location);
        if (parsed && parsed[1] === a.ayah) {
          minW = Math.min(minW, parsed[2]);
          maxW = Math.max(maxW, parsed[2]);
        }
      }

      if (minW !== Infinity && maxW !== -Infinity) {
        ranges.push({
          seg: s,
          segIndex: sIdx,
          minWord: minW,
          maxWord: maxW,
          isRepetition: !!s.is_repetition,
          words: sWords,
        });
      }
    }

    // Check for regression dips
    for (let i = 0; i < ranges.length - 1; i++) {
      const cur = ranges[i];
      const next = ranges[i + 1];

      // If next segment ends strictly before current segment (and is not an intentional full repeat)
      if (next.maxWord < cur.maxWord && !next.isRepetition) {
        // Verify if a subsequent segment leaps forward again (the classic dip sandwich)
        const laterLeap = ranges.slice(i + 2).some(r => r.maxWord >= cur.maxWord);
        if (laterLeap) {
          const anomalousWord = next.words[0];
          const issueId = `leap_dip_${a.ayah}_seg_${next.segIndex}`;
          issues.push({
            id: issueId,
            surah_number: surahNum,
            ayah_number: a.ayah,
            location: anomalousWord.location,
            word: anomalousWord.word,
            timestamp: anomalousWord.start,
            score: anomalousWord.score,
            type: 'interleaved_twin',
            message: `قفزة وتداخل عبارات متشابهة: المقطع ${next.segIndex + 1} انتهى عند كلمة (${next.maxWord}) بعد أن وصل المقطع السابق لكلمة (${cur.maxWord})`,
            severity: 'critical',
            resolved: resolvedIds.has(issueId) || !!anomalousWord.is_verified,
            duration: round(anomalousWord.end - anomalousWord.start, 2),
            ref: anomalousWord.ref,
          });
        }
      }
    }
  }

  // ─────────────────────────────────────────────────────────────────────────────
  // 2. WORD-BY-WORD ACOUSTIC & TIMING DIAGNOSTICS
  // ─────────────────────────────────────────────────────────────────────────────
  for (const a of surah.ayahs) {
    const segs = a.segments || [];

    for (let sIdx = 0; sIdx < segs.length; sIdx++) {
      const seg = segs[sIdx];
      const words = seg.words || [];

      for (let i = 0; i < words.length; i++) {
        const w = words[i];
        const dur = Math.max(0, w.end - w.start);
        const coverage = computeWordPhonemeCoverage(w);
        const hasMadd = isMaddWord(w);
        const expectedDur = estimateExpectedDuration(w);

        // Check 1: Physical Duration Collapse (< 0.08s)
        const isSingleParticle = SINGLE_LETTER_PARTICLES.has(w.word.trim());
        if (dur < 0.08 && !isSingleParticle) {
          const issueId = `collapse_${w.location}_${sIdx}`;
          issues.push({
            id: issueId,
            surah_number: surahNum,
            ayah_number: a.ayah,
            location: w.location,
            word: w.word,
            timestamp: w.start,
            score: w.score,
            type: 'duration_collapse',
            message: `زمن الكلمة قصير جداً وغير طبيعي (${(dur * 1000).toFixed(0)}ms)`,
            severity: 'critical',
            resolved: resolvedIds.has(issueId) || !!w.is_verified,
            duration: round(dur, 2),
            expected_duration: round(expectedDur, 2),
            coverage: round(coverage, 2),
            ref: w.ref,
          });
        }
        // Check 2: Abnormally Short Recitation Duration (< 45% of expected mora time and < 150ms)
        else if (dur < 0.45 * expectedDur && !isSingleParticle && dur < 0.15) {
          const issueId = `short_${w.location}_${sIdx}`;
          issues.push({
            id: issueId,
            surah_number: surahNum,
            ayah_number: a.ayah,
            location: w.location,
            word: w.word,
            timestamp: w.start,
            score: w.score,
            type: 'abnormally_short',
            message: `زمن تلاوة سريع ومقتضب (${dur.toFixed(2)}s مقابل المتوقع ${expectedDur.toFixed(2)}s)`,
            severity: 'warning',
            resolved: resolvedIds.has(issueId) || !!w.is_verified,
            duration: round(dur, 2),
            expected_duration: round(expectedDur, 2),
            coverage: round(coverage, 2),
            ref: w.ref,
          });
        }

        // Check 3: Truncated Phonemes (Coverage < 60% after Tajweed token normalization)
        if (coverage < 0.60) {
          const issueId = `trunc_${w.location}_${sIdx}`;
          const isCrit = coverage < 0.40;
          issues.push({
            id: issueId,
            surah_number: surahNum,
            ayah_number: a.ayah,
            location: w.location,
            word: w.word,
            timestamp: w.start,
            score: w.score,
            type: 'truncated_phonemes',
            message: `تغطية فونيمات ناقصة (${(coverage * 100).toFixed(0)}% من الحروف المرجعية الصوتية)`,
            severity: isCrit ? 'critical' : 'warning',
            resolved: resolvedIds.has(issueId) || !!w.is_verified,
            coverage: round(coverage, 2),
            duration: round(dur, 2),
            ref: w.ref,
          });
        }

        // Check 4: VAD Boundary Stripping at Silence/Pause Edges
        const isLastWordInSeg = i === words.length - 1;
        const bordersSegEnd = Math.abs(seg.end - w.end) < 0.05;
        if (isLastWordInSeg && bordersSegEnd) {
          const lastPhone = w.phonemes && w.phonemes.length > 0 ? w.phonemes[w.phonemes.length - 1] : null;
          const phoneDur = lastPhone ? lastPhone.end - lastPhone.start : dur;
          if (phoneDur <= 0.045 && dur < 0.14) {
            const issueId = `vad_cut_${w.location}_${sIdx}`;
            issues.push({
              id: issueId,
              surah_number: surahNum,
              ayah_number: a.ayah,
              location: w.location,
              word: w.word,
              timestamp: w.end,
              score: w.score,
              type: 'vad_boundary_cut',
              message: `احتمال قطع الحرف الأخير بواسطة عازل الصوت VAD قبل الوقف`,
              severity: 'warning',
              resolved: resolvedIds.has(issueId) || !!w.is_verified,
              duration: round(dur, 2),
              coverage: round(coverage, 2),
              ref: w.ref,
            });
          }
        }

        // Check 5: Absorbed Silence (Long Word WITHOUT Madd, exceeding 2.2x expected duration)
        if (dur > 2.4 && !hasMadd && dur > 2.2 * expectedDur) {
          const issueId = `absorbed_${w.location}_${sIdx}`;
          issues.push({
            id: issueId,
            surah_number: surahNum,
            ayah_number: a.ayah,
            location: w.location,
            word: w.word,
            timestamp: w.start,
            score: w.score,
            type: 'absorbed_silence',
            message: `كلمة طويلة جداً (${dur.toFixed(2)}s) دون وجود مد يبررها؛ قد تكون ابتلعت صمتاً`,
            severity: 'warning',
            resolved: resolvedIds.has(issueId) || !!w.is_verified,
            duration: round(dur, 2),
            expected_duration: round(expectedDur, 2),
          });
        }

        // Check 6: Unnatural Silence Gap in Connected Speech (> 0.85s inside single segment)
        if (i < words.length - 1) {
          const nextW = words[i + 1];
          const gap = nextW.start - w.end;
          if (gap > 0.85) {
            const issueId = `gap_${w.location}_${sIdx}`;
            issues.push({
              id: issueId,
              surah_number: surahNum,
              ayah_number: a.ayah,
              location: w.location,
              word: w.word,
              timestamp: w.end,
              score: w.score,
              type: 'large_gap',
              message: `فجوة صمت غير معتادة (${gap.toFixed(2)}s) داخل الوصل بين "${w.word}" و "${nextW.word}"`,
              severity: 'warning',
              resolved: resolvedIds.has(issueId) || !!w.is_verified,
              duration: round(gap, 2),
            });
          }

          // Check 7: Cross-Word Tajweed Assimilation & Bridge Boundary Shift
          if (gap <= 0.16) {
            const bridge = detectTajweedBoundaryBridge(w, nextW);
            if (bridge) {
              const issueId = `bridge_${w.location}_to_${nextW.location}`;
              issues.push({
                id: issueId,
                surah_number: surahNum,
                ayah_number: a.ayah,
                location: w.location,
                word: `${w.word} ⇥ ${nextW.word}`,
                timestamp: w.end,
                score: w.score,
                type: 'tajweed_bridge',
                message: `${bridge.ruleName}: ${bridge.detail}`,
                severity: 'warning',
                resolved: resolvedIds.has(issueId) || !!w.is_verified,
                duration: round(w.end - w.start, 2),
                expected_duration: round(nextW.end - nextW.start, 2),
                ref: bridge.ruleName,
              });
            }
          }
        }

        // Check 7: Acoustic Score Uncertainty (if below threshold)
        if (w.score < warningThreshold) {
          const issueId = `low_conf_${w.location}_${sIdx}`;
          issues.push({
            id: issueId,
            surah_number: surahNum,
            ayah_number: a.ayah,
            location: w.location,
            word: w.word,
            timestamp: w.start,
            score: w.score,
            type: 'low_confidence',
            message: `شك صوتي في المحاذاة (دقة: ${(w.score * 100).toFixed(0)}%)`,
            severity: w.score < 0.75 ? 'critical' : 'warning',
            resolved: resolvedIds.has(issueId) || !!w.is_verified,
          });
        }
      }
    }
  }

  // ─────────────────────────────────────────────────────────────────────────────
  // 3. AYAH-WIDE COVERAGE GAP DETECTION (TRUE MISSING WORDS)
  // ─────────────────────────────────────────────────────────────────────────────
  // Checks if any word number in an Ayah is completely omitted across ALL segments of that Ayah
  for (const a of surah.ayahs) {
    const segs = a.segments || [];
    const presentWordIndices = new Set<number>();
    let maxFoundWord = 0;

    for (const seg of segs) {
      for (const w of seg.words || []) {
        const parsed = parseLocation(w.location);
        if (parsed && parsed[1] === a.ayah) {
          presentWordIndices.add(parsed[2]);
          maxFoundWord = Math.max(maxFoundWord, parsed[2]);
        }
      }
    }

    if (maxFoundWord > 1) {
      for (let expected = 1; expected <= maxFoundWord; expected++) {
        if (!presentWordIndices.has(expected)) {
          const missingLoc = `${surahNum}:${a.ayah}:${expected}`;
          const issueId = `missing_${missingLoc}`;
          issues.push({
            id: issueId,
            surah_number: surahNum,
            ayah_number: a.ayah,
            location: missingLoc,
            word: `[كلمة ${expected}]`,
            timestamp: a.start,
            score: 0.0,
            type: 'coverage_gap',
            message: `الكلمة رقم (${expected}) سقطت بالكامل ولم تُتْلَ في أي مقطع من الآية ${a.ayah}`,
            severity: 'critical',
            resolved: resolvedIds.has(issueId),
          });
        }
      }
    }
  }

  // Deduplicate issues by ID
  const uniqueMap = new Map<string, ConfidenceIssue>();
  for (const iss of issues) {
    if (!uniqueMap.has(iss.id)) {
      uniqueMap.set(iss.id, iss);
    }
  }

  return Array.from(uniqueMap.values());
}

function round(val: number, decimals: number): number {
  const factor = Math.pow(10, decimals);
  return Math.round(val * factor) / factor;
}
