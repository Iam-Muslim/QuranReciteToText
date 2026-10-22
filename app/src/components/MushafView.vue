<template>
  <div class="mushaf-container">
    <!-- Pinned View Mode Switcher & Typography Sizing Bar -->
    <div class="view-switcher-bar" v-if="projectStore.activeSurah.value">
      <div class="switcher-left">
        <div class="view-toggle-pill">
          <button 
            class="toggle-btn" 
            :class="{ 'active': projectStore.viewMode.value === 'mushaf_page' }"
            @click="projectStore.viewMode.value = 'mushaf_page'"
            title="Medina Mushaf Sacred Page"
          >
            <BookOpen :size="12" />
            <span>Mushaf</span>
          </button>

          <button 
            class="toggle-btn" 
            :class="{ 'active': projectStore.viewMode.value === 'ayah_studio' }"
            @click="projectStore.viewMode.value = 'ayah_studio'"
            title="Verses Studio Cards"
          >
            <ListTree :size="12" />
            <span>Verses</span>
          </button>

          <button 
            class="toggle-btn" 
            :class="{ 'active': projectStore.viewMode.value === 'phoneme_inspector' }"
            @click="projectStore.viewMode.value = 'phoneme_inspector'"
            title="Phoneme Atoms Inspector"
          >
            <Layers :size="12" />
            <span>Phonemes</span>
          </button>
        </div>
      </div>

      <div class="switcher-right">
        <!-- Font Size Stepper (Mushaf Page Mode) -->
        <div class="font-stepper-group" v-if="projectStore.viewMode.value === 'mushaf_page'" title="Adjust Quran Font Size">
          <button 
            class="stepper-btn" 
            @click="projectStore.setMushafFontSize(projectStore.mushafFontSize.value - 0.15)"
            title="Decrease Font Size"
            :disabled="projectStore.mushafFontSize.value <= 1.3"
          >
            <span>A-</span>
          </button>
          <span class="stepper-val">{{ Math.round((projectStore.mushafFontSize.value / 1.95) * 100) }}%</span>
          <button 
            class="stepper-btn" 
            @click="projectStore.setMushafFontSize(projectStore.mushafFontSize.value + 0.15)"
            title="Increase Font Size"
            :disabled="projectStore.mushafFontSize.value >= 3.2"
          >
            <span>A+</span>
          </button>
        </div>
      </div>
    </div>

    <!-- Empty State -->
    <div v-if="!projectStore.activeSurah.value" class="mushaf-empty-wrapper">
      <div class="mushaf-empty-card">
        <BookOpen :size="28" class="empty-icon" />
        <span class="empty-title">No Recitation Active</span>
        <span class="empty-sub">Select or align a recitation in the sidebar to view Mushaf.</span>
      </div>
    </div>

    <!-- VIEW 1: Sacred Medina Mushaf -->
    <div 
      v-else-if="projectStore.viewMode.value === 'mushaf_page'" 
      class="mushaf-page-wrapper"
    >
      <div class="mushaf-card">
        <!-- Basmalah -->
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
        <div class="verses-flow arabic-quran-text" :style="{ fontSize: `${projectStore.mushafFontSize.value}rem` }">
          <template v-for="ayah in projectStore.activeSurah.value.ayahs" :key="ayah.ayah">
            <span 
              class="ayah-inline-group" 
              :class="{ 'ayah-focused': projectStore.activeAyahNumber.value === ayah.ayah }"
              :id="`ayah_block_${ayah.ayah}`"
            >
              <!-- Canonical Ayah Words -->
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

              <!-- Medina Ayah End Marker -->
              <span class="ayah-symbol" @click="handleAyahClick(ayah)" title="Ayah {{ ayah.ayah }}">
                <span class="ayah-num">{{ ayah.ayah }}</span>
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
        class="ayah-row-card"
        :class="{ 'card-active': projectStore.activeAyahNumber.value === ayah.ayah }"
        :id="`ayah_card_${ayah.ayah}`"
      >
        <div class="ayah-row-left">
          <button class="ayah-play-pill" @click="playAyah(ayah)" title="Play Ayah">
            <Play :size="10" />
            <span>{{ ayah.ayah }}</span>
          </button>
          <span 
            v-if="getCrossHafsAyahLabel(ayah.ayah)" 
            class="cross-hafs-pill" 
            :title="`يقابل في ترقيم حفص: ${getCrossHafsAyahLabel(ayah.ayah)}`"
          >
            حفص: {{ getCrossHafsAyahLabel(ayah.ayah) }}
          </span>
          <span class="ayah-time-subtle">{{ ayah.start.toFixed(1) }}s</span>
        </div>

        <div class="ayah-row-words arabic-quran-text">
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
        class="phoneme-ayah-row"
        :id="`ayah_card_${ayah.ayah}`"
      >
        <div class="ph-ayah-index">{{ ayah.ayah }}</div>
        <div class="ph-segments-container">
          <div 
            v-for="(seg, sIdx) in (ayah.segments || [])" 
            :key="`ph_seg_${ayah.ayah}_${seg.segment || sIdx}`"
            class="ph-segment-line"
            :class="{ 'is-repetition-segment': seg.is_repetition || sIdx > 0 }"
          >
            <div class="ph-segment-tag-row" v-if="(ayah.segments && ayah.segments.length > 1)">
              <span class="ph-seg-badge" :class="{ 'badge-rep': seg.is_repetition || sIdx > 0 }">
                {{ seg.is_repetition || sIdx > 0 ? `مقطع ${seg.segment || (sIdx + 1)} (إعادة)` : `المقطع ${seg.segment || (sIdx + 1)}` }}
              </span>
              <span class="ph-seg-timing">[{{ seg.start.toFixed(2) }}s - {{ seg.end.toFixed(2) }}s]</span>
            </div>

            <div class="ph-words-flow">
              <div 
                v-for="(word, wIdx) in seg.words" 
                :key="`ph_w_${ayah.ayah}_${sIdx}_${wIdx}_${word.start}`"
                class="ph-word-block"
                :class="{ 'ph-active': isPhonemeBlockActive(word) }"
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
import { 
  RiwayahProvider, 
  isNonHafsRiwayah
} from '../services/RiwayahProvider';
import type { AlignedWord, AyahItem, PhonemeItem } from '../types/aligner';
import { 
  BookOpen, 
  Play,
  ListTree,
  Layers
} from 'lucide-vue-next';

const emit = defineEmits<{
  (e: 'word-context-menu', event: MouseEvent, word: AlignedWord): void;
}>();

function getCrossHafsAyahLabel(ayahNum: number): string | null {
  const currentR = projectStore.project?.settings?.riwayah;
  if (!currentR || !isNonHafsRiwayah(currentR) || !projectStore.activeSurah.value) return null;
  const sNum = projectStore.activeSurah.value.surah_number;
  const hafsTargets = RiwayahProvider.riwayahToHafsAyahs(currentR, sNum, ayahNum);
  if (hafsTargets.length === 1 && hafsTargets[0] === ayahNum) return null;
  return hafsTargets.join('، ');
}

watch(
  () => projectStore.project?.settings?.riwayah,
  (newR) => {
    if (newR && isNonHafsRiwayah(newR)) {
      void RiwayahProvider.prefetch(newR);
    }
  },
  { immediate: true }
);

function getWordClasses(word: AlignedWord) {
  const isPlaying = projectStore.isPlaying.value;
  const isKaraokeActive = projectStore.currentKaraokeLocation.value === word.location;
  
  const isHighlighted = isPlaying
    ? isKaraokeActive
    : (isKaraokeActive || projectStore.activeWordLocation.value === word.location);
  
  return {
    'active-karaoke': isHighlighted,
  };
}

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
  padding: 12px 24px 36px;
  display: flex;
  flex-direction: column;
  background: var(--bg-base);
}

@media (max-width: 700px) {
  .mushaf-container {
    padding: 8px 10px 24px;
  }
}

/* Pinned View Mode Switcher & Sizing Bar */
.view-switcher-bar {
  position: sticky;
  top: 0;
  z-index: 30;
  display: flex;
  align-items: center;
  justify-content: space-between;
  max-width: 880px;
  width: 100%;
  margin: 0 auto 12px;
  pointer-events: none;
}

.switcher-left,
.switcher-right {
  pointer-events: auto;
  display: flex;
  align-items: center;
  gap: 8px;
}

.view-toggle-pill {
  display: flex;
  align-items: center;
  background: var(--glass-bg);
  backdrop-filter: blur(16px);
  -webkit-backdrop-filter: blur(16px);
  border: 1px solid var(--glass-border);
  border-radius: var(--radius-pill);
  padding: 3px;
  gap: 2px;
  box-shadow: var(--shadow-e2);
}

.toggle-btn {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  background: transparent;
  border: none;
  color: var(--text-muted);
  border-radius: var(--radius-pill);
  padding: 4px 12px;
  font-size: var(--text-xs);
  font-weight: 500;
  cursor: pointer;
  transition: all var(--dur-fast) var(--ease-out);
}
.toggle-btn:hover {
  color: var(--text-main);
}
.toggle-btn.active {
  background: var(--bg-surface-elevated);
  color: var(--text-main);
  box-shadow: var(--shadow-e1);
  font-weight: 600;
}

/* Font Size Stepper Control */
.font-stepper-group {
  display: flex;
  align-items: center;
  background: var(--glass-bg);
  backdrop-filter: blur(16px);
  -webkit-backdrop-filter: blur(16px);
  border: 1px solid var(--glass-border);
  border-radius: var(--radius-pill);
  padding: 2px 6px;
  gap: 4px;
  box-shadow: var(--shadow-e1);
}

.stepper-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  border-radius: var(--radius-pill);
  border: none;
  background: transparent;
  color: var(--text-secondary);
  font-size: 11px;
  font-weight: 700;
  cursor: pointer;
  transition: all var(--dur-fast) var(--ease-out);
}
.stepper-btn:hover:not(:disabled) {
  background: var(--bg-surface-elevated);
  color: var(--text-main);
  box-shadow: var(--shadow-e1);
}
.stepper-btn:disabled {
  opacity: 0.35;
  cursor: not-allowed;
}

.stepper-val {
  font-family: var(--font-mono);
  font-size: 10px;
  font-weight: 600;
  color: var(--text-muted);
  min-width: 32px;
  text-align: center;
}

/* Empty State */
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
  gap: 8px;
  padding: 36px 40px;
  border-radius: var(--radius-lg);
  background: var(--bg-surface);
  border: 1px dashed var(--border-subtle);
  max-width: 380px;
}
.empty-icon {
  color: var(--text-muted);
  margin-bottom: 4px;
}
.empty-title {
  font-size: var(--text-md);
  font-weight: 600;
}
.empty-sub {
  font-size: var(--text-xs);
  color: var(--text-muted);
  line-height: 1.4;
}

/* VIEW 1: Medina Mushaf */
.mushaf-page-wrapper {
  display: flex;
  justify-content: center;
  padding: 4px 0 24px;
}

.mushaf-card {
  max-width: 880px;
  width: 100%;
  background: var(--bg-surface);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-lg);
  padding: 28px 40px 44px;
  box-shadow: var(--shadow-e2);
}

@media (max-width: 700px) {
  .mushaf-card {
    padding: 18px 16px 26px;
  }
}

/* Basmalah Row */
.basmalah-row {
  text-align: center;
  margin-bottom: 24px;
  direction: rtl;
}
.basmalah-words {
  font-family: var(--font-arabic);
  font-size: 1.65rem;
  color: var(--text-main);
}

.verses-flow {
  font-size: 1.95rem;
  line-height: 2.3;
  color: var(--text-main);
  text-align: justify;
  text-align-last: center;
  word-spacing: 5px;
}

.ayah-inline-group {
  display: inline;
}

/* Authentic Medina Ayah End Marker */
.ayah-symbol {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
  margin: 0 6px;
  border-radius: 50%;
  border: 1.5px solid var(--gold-border);
  background: var(--gold-subtle);
  cursor: pointer;
  vertical-align: middle;
  transition: all var(--dur-fast) var(--ease-out);
  user-select: none;
}
.ayah-symbol:hover {
  border-color: var(--gold-primary);
  background: rgba(var(--gold-rgb), 0.20);
  transform: scale(1.08);
}
.ayah-num {
  font-family: var(--font-mono);
  font-size: 10px;
  font-weight: 700;
  color: var(--gold-primary);
  line-height: 1;
}

/* VIEW 2: Ayah Studio Workstation */
.ayah-cards-wrapper {
  display: flex;
  flex-direction: column;
  gap: 8px;
  max-width: 880px;
  margin: 0 auto;
  width: 100%;
}

.ayah-row-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 18px;
  border-radius: var(--radius-md);
  background: var(--bg-surface);
  border: 1px solid var(--border-subtle);
  transition: all var(--dur-fast) var(--ease-out);
}
.ayah-row-card.card-active {
  border-color: var(--accent-border);
  background: var(--bg-surface-elevated);
  box-shadow: 0 0 0 1px var(--accent-subtle), var(--shadow-e1);
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
  border-radius: var(--radius-pill);
  padding: 3px 9px;
  font-size: 11px;
  font-family: var(--font-mono);
  font-weight: 600;
  cursor: pointer;
  transition: all var(--dur-fast) var(--ease-out);
}
.ayah-play-pill:hover {
  background: var(--accent-primary);
  border-color: var(--accent-primary);
  color: #ffffff;
}
.ayah-time-subtle {
  font-family: var(--font-mono);
  font-size: 10px;
  color: var(--text-muted);
}
.cross-hafs-pill {
  font-size: 9px;
  color: #a78bfa;
  background: rgba(167, 139, 250, 0.1);
  border: 1px solid rgba(167, 139, 250, 0.25);
  padding: 1px 6px;
  border-radius: var(--radius-pill);
}

.ayah-row-words {
  direction: rtl;
  font-family: var(--font-arabic) !important;
  font-size: 1.65rem;
  line-height: 2;
}

/* VIEW 3: Phonemes */
.phoneme-inspector-wrapper {
  max-width: 880px;
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
  padding: 10px 14px;
  border-radius: var(--radius-sm);
  background: var(--bg-surface);
  border: 1px solid var(--border-subtle);
}
.ph-ayah-index {
  font-family: var(--font-mono);
  font-weight: 700;
  font-size: 11px;
  color: var(--accent-primary);
  padding-top: 4px;
}
.ph-segments-container {
  display: flex;
  flex-direction: column;
  gap: 8px;
  flex: 1;
}
.ph-segment-line {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 8px 10px;
  border-radius: var(--radius-xs);
  background: var(--bg-input);
  border: 1px solid var(--border-subtle);
}
.ph-segment-line.is-repetition-segment {
  border-style: dashed;
}
.ph-segment-tag-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.ph-seg-badge {
  font-size: 10px;
  font-weight: 600;
  color: var(--text-muted);
  background: var(--bg-surface);
  padding: 2px 7px;
  border-radius: var(--radius-xs);
}
.ph-seg-badge.badge-rep {
  color: #a5b4fc;
  background: rgba(99, 102, 241, 0.15);
}
.ph-seg-timing {
  font-family: var(--font-mono);
  font-size: 10px;
  color: var(--text-dim);
}
.ph-words-flow {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  direction: rtl;
}
.ph-word-block {
  background: var(--bg-surface-elevated);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-xs);
  padding: 4px 6px;
  display: flex;
  flex-direction: column;
  align-items: center;
  cursor: pointer;
  transition: all var(--dur-fast) var(--ease-out);
}
.ph-word-block.ph-active {
  border-color: var(--emerald-primary);
  background: rgba(16, 185, 129, 0.15);
}
.ph-word-text {
  font-family: var(--font-arabic);
  font-size: 1.1rem;
  color: var(--text-main);
}
.ph-chain {
  display: flex;
  gap: 2px;
  margin-top: 2px;
}
.ph-atom {
  font-family: var(--font-arabic);
  font-size: 10px;
  color: var(--text-secondary);
  background: var(--bg-base);
  border: 1px solid var(--border-subtle);
  padding: 1px 4px;
  border-radius: 2px;
  cursor: pointer;
}
.ph-atom.atom-playing {
  background: var(--emerald-primary);
  border-color: var(--emerald-primary);
  color: #ffffff;
}

/* Light Theme High-Contrast Overrides */
html[data-theme='light'] .cross-hafs-pill {
  color: #6d28d9;
  background: #ede9fe;
  border-color: #c4b5fd;
}
html[data-theme='light'] .ph-seg-badge.badge-rep {
  color: #4338ca;
  background: #e0e7ff;
}
html[data-theme='light'] .ph-word-block.ph-active {
  border-color: var(--emerald-primary);
  background: #d1fae5;
}
html[data-theme='light'] .ph-atom.atom-playing {
  background: var(--emerald-primary);
  border-color: var(--emerald-primary);
  color: #ffffff;
}
</style>
