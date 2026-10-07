<template>
  <div class="mushaf-container">
    <!-- View Switcher & Minimal Controls (Pinned Sticky Header) -->
    <div class="view-header">
      <div class="view-toggle">
        <button 
          class="toggle-btn" 
          :class="{ 'active': projectStore.viewMode.value === 'mushaf_page' }"
          @click="projectStore.viewMode.value = 'mushaf_page'"
          title="Medina Mushaf View"
        >
          <span>Mushaf</span>
        </button>

        <button 
          class="toggle-btn" 
          :class="{ 'active': projectStore.viewMode.value === 'ayah_studio' }"
          @click="projectStore.viewMode.value = 'ayah_studio'"
          title="Ayah-by-Ayah View"
        >
          <span>Verses</span>
        </button>

        <button 
          class="toggle-btn" 
          :class="{ 'active': projectStore.viewMode.value === 'phoneme_inspector' }"
          @click="projectStore.viewMode.value = 'phoneme_inspector'"
          title="Phoneme Inspector"
        >
          <span>Phonemes</span>
        </button>
      </div>
    </div>

    <!-- Empty State when no recitation is active -->
    <div v-if="!projectStore.activeSurah.value" class="mushaf-empty-wrapper">
      <div class="mushaf-empty-card glass-panel">
        <BookOpen :size="30" class="empty-icon" />
        <span class="empty-title">No Recitation Active</span>
        <span class="empty-sub">Add a recitation in the sidebar or open a project in the Projects tab.</span>
      </div>
    </div>

    <!-- VIEW 1: Pure Sacred Medina Mushaf -->
    <div 
      v-else-if="projectStore.viewMode.value === 'mushaf_page'" 
      class="mushaf-page-wrapper"
    >
      <div class="mushaf-card glass-panel">
        <!-- Surah Ornate Banner -->
        <div class="surah-banner">
          <div class="banner-border">
            <h2 class="surah-title">سُورَةُ {{ projectStore.activeSurah.value.surah_name_arabic }}</h2>
          </div>
        </div>

        <!-- Basmalah: ONLY if present in JSON intro -->
        <div 
          class="basmalah-row" 
          v-if="projectStore.activeSurah.value.intro && projectStore.activeSurah.value.intro.words && projectStore.activeSurah.value.intro.words.length > 0"
        >
          <span class="basmalah-words">
            <span
              v-for="w in projectStore.activeSurah.value.intro.words"
              :key="w.location"
              class="quran-word-item"
              :class="getWordClasses(w)"
              @click="handleWordClick(w)"
              @contextmenu.prevent="handleContextMenu($event, w)"
              :id="`word_el_${w.location}`"
            >
              {{ w.word }}
            </span>
          </span>
        </div>

        <!-- Sacred Verses Flow -->
        <div class="verses-flow arabic-quran-text">
          <template v-for="ayah in projectStore.activeSurah.value.ayahs" :key="ayah.ayah">
            <span 
              class="ayah-inline-group" 
              :class="{ 'ayah-focused': projectStore.activeAyahNumber.value === ayah.ayah }"
              :id="`ayah_block_${ayah.ayah}`"
            >
              <!-- Canonical Ayah Words displayed strictly once (No duplicate repeats in sacred text) -->
              <span 
                v-for="word in getCanonicalAyahWords(ayah)" 
                :key="word.location"
                class="quran-word-item"
                :class="getWordClasses(word)"
                @click="handleWordClick(word)"
                @contextmenu.prevent="handleContextMenu($event, word)"
                :id="`word_el_${word.location}`"
              >
                {{ word.word }}
              </span>
              <!-- Ayah End Number (Without Bracket, very small) -->
              <span class="ayah-symbol" @click="handleAyahClick(ayah)">
                {{ toArabicNumerals(ayah.ayah) }}
              </span>
            </span>
          </template>
        </div>
      </div>
    </div>

    <!-- VIEW 2: Ayah Studio Workstation -->
    <div 
      v-else-if="projectStore.viewMode.value === 'ayah_studio'" 
      class="ayah-cards-wrapper"
    >
      <div 
        v-for="ayah in projectStore.activeSurah.value?.ayahs" 
        :key="ayah.ayah"
        class="ayah-row-card glass-panel"
        :class="{ 'card-active': projectStore.activeAyahNumber.value === ayah.ayah }"
        :id="`ayah_card_${ayah.ayah}`"
      >
        <div class="ayah-row-left">
          <button class="ayah-play-pill" @click="playAyah(ayah)" title="Play verse">
            <Play :size="10" />
            <span>{{ ayah.ayah }}</span>
          </button>
          <span class="ayah-time-subtle">{{ ayah.start.toFixed(1) }}s</span>
        </div>

        <div class="ayah-row-words">
          <!-- Canonical Verse Words displayed once -->
          <span 
            v-for="word in getCanonicalAyahWords(ayah)" 
            :key="word.location"
            class="quran-word-item"
            :class="getWordClasses(word)"
            @click="handleWordClick(word)"
            @contextmenu.prevent="handleContextMenu($event, word)"
            :id="`verse_word_el_${word.location}`"
          >
            {{ word.word }}
          </span>
        </div>
      </div>
    </div>

    <!-- VIEW 3: Phoneme Precision Inspector -->
    <div 
      v-else-if="projectStore.viewMode.value === 'phoneme_inspector'" 
      class="phoneme-inspector-wrapper"
    >
      <div 
        v-for="ayah in projectStore.activeSurah.value?.ayahs" 
        :key="ayah.ayah"
        class="phoneme-ayah-row glass-panel"
        :id="`ayah_card_${ayah.ayah}`"
      >
        <div class="ph-ayah-index">{{ ayah.ayah }}</div>
        <div class="ph-segments-container">
          <!-- Each segment/take is isolated in its own line/sub-box to prevent timing collisions -->
          <div 
            v-for="(seg, sIdx) in (ayah.segments || [])" 
            :key="`ph_seg_${ayah.ayah}_${seg.segment || sIdx}`"
            class="ph-segment-line"
            :class="{ 'is-repetition-segment': seg.is_repetition || sIdx > 0 }"
          >
            <div class="ph-segment-tag-row" v-if="(ayah.segments && ayah.segments.length > 1)">
              <span class="ph-seg-badge" :class="{ 'badge-rep': seg.is_repetition || sIdx > 0 }">
                {{ seg.is_repetition || sIdx > 0 ? `مقطع ${seg.segment || (sIdx + 1)} (إعادة تلاوة)` : `المقطع ${seg.segment || (sIdx + 1)}` }}
              </span>
              <span class="ph-seg-timing">[{{ seg.start.toFixed(2) }}s - {{ seg.end.toFixed(2) }}s]</span>
            </div>

            <div class="ph-words-flow">
              <div 
                v-for="(word, wIdx) in seg.words" 
                :key="`ph_w_${ayah.ayah}_${sIdx}_${wIdx}_${word.start}`"
                class="ph-word-block"
                :class="{ 
                  'ph-active': isPhonemeBlockActive(word)
                }"
                @click="handleWordClick(word)"
                :id="`ph_word_${word.location}_${sIdx}`"
              >
                <span class="ph-word-text">{{ word.word }}</span>
                <div class="ph-chain" v-if="word.phonemes && word.phonemes.length">
                  <span 
                    v-for="(p, i) in word.phonemes" 
                    :key="i"
                    class="ph-atom"
                    :class="{ 'atom-playing': isPhonemeActive(p) }"
                    @click.stop="seekTo(p.start)"
                  >
                    {{ p.phoneme }}
                  </span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { watch, nextTick } from 'vue';
import { projectStore } from '../services/projectStore';
import type { AlignedWord, AyahItem, PhonemeItem } from '../types/aligner';
import { 
  BookOpen, 
  Play 
} from 'lucide-vue-next';

const emit = defineEmits<{
  (e: 'word-context-menu', event: MouseEvent, word: AlignedWord): void;
}>();

function getWordClasses(word: AlignedWord) {
  const isPlaying = projectStore.isPlaying.value;
  const isKaraokeActive = projectStore.currentKaraokeLocation.value === word.location;
  
  // When playing, only the currently reciting word lights up (no stuck past selection).
  // When paused, if a word is clicked it lights up with the same soft emerald tone.
  const isHighlighted = isPlaying
    ? isKaraokeActive
    : (isKaraokeActive || projectStore.activeWordLocation.value === word.location);
  
  return {
    'active-karaoke': isHighlighted,
  };
}

// Canonical words deduplicated by Quranic word position (avoids printing repeated phrases twice)
function getCanonicalAyahWords(ayah: AyahItem): AlignedWord[] {
  if (!ayah.segments || ayah.segments.length === 0) return [];
  const wordMap = new Map<string, AlignedWord>();
  for (const seg of ayah.segments) {
    for (const w of (seg.words || [])) {
      if (!wordMap.has(w.location)) {
        wordMap.set(w.location, w);
      }
    }
  }
  return Array.from(wordMap.values()).sort((a, b) => {
    const partsA = a.location.split(':');
    const partsB = b.location.split(':');
    const idxA = parseInt(partsA[2] || '0', 10);
    const idxB = parseInt(partsB[2] || '0', 10);
    return idxA - idxB;
  });
}

function isPhonemeWordActive(word: AlignedWord): boolean {
  const t = projectStore.currentTime.value;
  return t >= word.start && t <= word.end;
}

function isPhonemeBlockActive(word: AlignedWord): boolean {
  if (projectStore.isPlaying.value) {
    return isPhonemeWordActive(word);
  }
  return isPhonemeWordActive(word) || projectStore.activeWordLocation.value === word.location;
}

function isPhonemeActive(ph: PhonemeItem): boolean {
  const t = projectStore.currentTime.value;
  return t >= ph.start && t <= ph.end;
}

function handleWordClick(word: AlignedWord) {
  projectStore.selectWord(word.location, true);
}

function handleAyahClick(ayah: AyahItem) {
  projectStore.selectAyah(ayah.ayah);
}

function playAyah(ayah: AyahItem) {
  projectStore.selectAyah(ayah.ayah);
}

function seekTo(t: number) {
  projectStore.currentTime.value = t;
}

function handleContextMenu(event: MouseEvent, word: AlignedWord) {
  projectStore.selectWord(word.location, false);
  emit('word-context-menu', event, word);
}

function toArabicNumerals(num: number): string {
  const arabicDigits = ['٠', '١', '٢', '٣', '٤', '٥', '٦', '٧', '٨', '٩'];
  return String(num).split('').map(d => arabicDigits[parseInt(d)]).join('');
}

// Auto-scroll follow across Mushaf, Verses, and Phonemes tabs (maintains highlighted word at mid of screen)
watch(() => projectStore.currentWordAtPlayhead.value, (word) => {
  if (!word || !projectStore.autoScrollMushaf.value) return;

  nextTick(() => {
    const el = document.getElementById(`word_el_${word.location}`);
    if (el) {
      el.scrollIntoView({ behavior: 'smooth', block: 'center' });
    } else {
      const locParts = word.location.split(':');
      if (locParts.length >= 2) {
        const ayahNum = locParts[1];
        const card = document.getElementById(`ayah_card_${ayahNum}`) || document.getElementById(`ayah_block_${ayahNum}`);
        if (card) {
          card.scrollIntoView({ behavior: 'smooth', block: 'center' });
        }
      }
    }
  });
});

watch(() => projectStore.activeAyahNumber.value, (ayahNum) => {
  if (!ayahNum || !projectStore.autoScrollMushaf.value) return;
  nextTick(() => {
    const card = document.getElementById(`ayah_card_${ayahNum}`) || document.getElementById(`ayah_block_${ayahNum}`);
    if (card) {
      card.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
  });
});
</script>

<style scoped>
.mushaf-container {
  flex: 1;
  overflow-y: auto;
  padding: 12px 20px 30px;
  display: flex;
  flex-direction: column;
  background: var(--bg-base);
}

/* Pinned View Header Bar */
.view-header {
  position: sticky;
  top: -12px;
  z-index: 30;
  display: flex;
  align-items: center;
  justify-content: flex-start;
  padding: 10px 0 10px 0;
  margin-bottom: 12px;
  background: var(--bg-base);
  border-bottom: 1px solid var(--border-subtle);
}

.view-toggle {
  display: flex;
  background: var(--bg-surface);
  border: 1px solid var(--border-subtle);
  border-radius: 6px;
  padding: 2px;
  gap: 2px;
}
.toggle-btn {
  display: flex;
  align-items: center;
  gap: 5px;
  background: transparent;
  border: none;
  color: var(--text-dim);
  border-radius: 4px;
  padding: 4px 12px;
  font-size: 0.72rem;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.12s ease;
}
.toggle-btn:hover {
  color: var(--text-main);
}
.toggle-btn.active {
  background: var(--bg-surface-elevated);
  color: var(--text-main);
  border: 1px solid var(--border-medium);
}

/* VIEW 1: Medina Mushaf */
.mushaf-page-wrapper {
  display: flex;
  justify-content: center;
}

.mushaf-card {
  max-width: 920px;
  width: 100%;
  background: var(--bg-surface);
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  padding: 24px 36px 36px;
}

.surah-banner {
  display: flex;
  justify-content: center;
  margin-bottom: 18px;
}
.banner-border {
  background: var(--bg-surface-elevated);
  border: 1px solid var(--border-medium);
  border-radius: 6px;
  padding: 4px 20px;
}
.surah-title {
  font-family: var(--font-arabic);
  font-size: 1.55rem;
  color: #fff;
  margin: 0;
}

.basmalah-row {
  text-align: center;
  margin-bottom: 20px;
  direction: rtl;
}
.static-basmalah, .basmalah-words {
  font-family: var(--font-arabic);
  font-size: 1.55rem;
  color: var(--text-main);
}

.verses-flow {
  font-size: 1.9rem;
  line-height: 2.25;
  color: #f8fafc;
  text-align: justify;
  text-align-last: center;
  word-spacing: 4px;
}

.ayah-inline-group {
  display: inline;
}



.ayah-symbol {
  font-family: var(--font-arabic);
  font-size: 0.6em;
  color: var(--text-muted);
  margin: 0 4px;
  cursor: pointer;
  vertical-align: middle;
  padding: 1px 3px;
  border-radius: 3px;
  transition: all 0.1s ease;
  user-select: none;
}
.ayah-symbol:hover {
  color: var(--accent-primary);
  background: var(--accent-subtle);
}

/* VIEW 2: Ayah Studio Workstation */
.ayah-cards-wrapper {
  display: flex;
  flex-direction: column;
  gap: 8px;
  max-width: 920px;
  margin: 0 auto;
  width: 100%;
}

.ayah-row-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 16px;
  border-radius: 10px;
  background: var(--bg-surface);
  border: 1px solid var(--border-subtle);
  transition: border-color 0.15s ease;
}
.ayah-row-card.card-active {
  border-color: var(--accent-primary);
  background: var(--bg-surface-elevated);
}

.ayah-row-left {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}
.ayah-play-pill {
  display: flex;
  align-items: center;
  gap: 4px;
  background: var(--bg-surface-elevated);
  border: 1px solid var(--border-subtle);
  color: var(--text-secondary);
  border-radius: 4px;
  padding: 3px 8px;
  font-size: 0.72rem;
  font-family: var(--font-mono);
  font-weight: 600;
  cursor: pointer;
  transition: all 0.12s ease;
}
.ayah-play-pill:hover {
  background: var(--accent-primary);
  border-color: var(--accent-primary);
  color: #fff;
}
.ayah-time-subtle {
  font-family: var(--font-mono);
  font-size: 0.68rem;
  color: var(--text-dim);
}

.ayah-row-words {
  direction: rtl;
  font-size: 1.45rem;
  line-height: 1.8;
}

/* VIEW 3: Phonemes */
.phoneme-inspector-wrapper {
  max-width: 920px;
  margin: 0 auto;
  width: 100%;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.phoneme-ayah-row {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  padding: 8px 12px;
  border-radius: 6px;
  background: var(--bg-surface);
  border: 1px solid var(--border-subtle);
}
.ph-ayah-index {
  font-family: var(--font-mono);
  font-weight: 700;
  font-size: 0.75rem;
  color: var(--accent-primary);
  padding-top: 4px;
}
.ph-segments-container {
  display: flex;
  flex-direction: column;
  gap: 10px;
  flex: 1;
}
.ph-segment-line {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 8px 10px;
  border-radius: 6px;
  background: rgba(255, 255, 255, 0.02);
  border: 1px solid rgba(255, 255, 255, 0.05);
}
.ph-segment-line.is-repetition-segment {
  background: rgba(99, 102, 241, 0.04);
  border: 1px dashed rgba(99, 102, 241, 0.25);
}
.ph-segment-tag-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 2px;
}
.ph-seg-badge {
  font-size: 10px;
  font-weight: 600;
  color: #94a3b8;
  background: rgba(255, 255, 255, 0.06);
  padding: 2px 8px;
  border-radius: 4px;
}
.ph-seg-badge.badge-rep {
  color: #a5b4fc;
  background: rgba(99, 102, 241, 0.15);
  border: 1px solid rgba(99, 102, 241, 0.3);
}
.ph-seg-timing {
  font-family: var(--font-mono);
  font-size: 10px;
  color: var(--text-dim);
}
.ph-words-flow {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  direction: rtl;
  flex: 1;
}
.ph-word-block {
  background: var(--bg-surface-elevated);
  border: 1px solid var(--border-subtle);
  border-radius: 4px;
  padding: 4px 6px;
  display: flex;
  flex-direction: column;
  align-items: center;
  cursor: pointer;
  transition: all 0.12s ease;
}
.ph-word-block.ph-selected {
  border-color: #10b981;
  background: rgba(16, 185, 129, 0.18);
  box-shadow: none;
}
.ph-word-block.ph-active {
  border-color: #10b981;
  background: rgba(16, 185, 129, 0.18);
  box-shadow: none;
}
.ph-word-text {
  font-family: var(--font-arabic);
  font-size: 1.1rem;
  color: #fff;
}
.ph-chain {
  display: flex;
  gap: 3px;
  margin-top: 2px;
}
.ph-atom {
  font-family: var(--font-arabic);
  font-size: 0.85rem;
  color: var(--text-secondary);
  background: var(--bg-base);
  border: 1px solid var(--border-subtle);
  padding: 1px 4px;
  border-radius: 3px;
  cursor: pointer;
}
.ph-atom.atom-playing {
  background: var(--emerald-primary);
  border-color: var(--emerald-primary);
  color: #fff;
}

.mushaf-empty-wrapper {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 40px;
}
.mushaf-empty-card {
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
  gap: 10px;
  padding: 36px 48px;
  border-radius: 12px;
  background: var(--bg-surface);
  border: 1px dashed var(--border-subtle);
  max-width: 440px;
}
.empty-title {
  font-size: 1.05rem;
  font-weight: 600;
  color: #fff;
}
.empty-desc {
  font-size: 0.8rem;
  color: var(--text-dim);
  line-height: 1.45;
}
</style>
