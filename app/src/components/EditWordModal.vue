<template>
  <div v-if="visible" class="modal-backdrop" @click="close">
    <div class="edit-word-modal glass-panel" @click.stop>
      <!-- Header -->
      <div class="modal-header">
        <div class="header-titles">
          <h3 class="modal-title">Edit Word</h3>
          <span class="modal-subtitle">Choose canonical Quranic location for this word</span>
        </div>
        <button class="btn-icon close-btn" @click="close" title="Close">
          <X :size="16" />
        </button>
      </div>

      <!-- Live Uthmani Word Preview Card -->
      <div class="word-preview-card" :class="{ 'preview-invalid': !isValid && !isLoading }">
        <div class="preview-arabic-container">
          <Loader2 v-if="isLoading" class="animate-spin loading-icon" :size="32" />
          <span v-else class="preview-uthmani-text">{{ previewWord || '—' }}</span>
        </div>

        <!-- Transliteration & Word Translation (from QuranCaption) -->
        <div v-if="wordTransliteration || wordTranslation" class="word-meanings-row">
          <span v-if="wordTransliteration" class="word-transliteration">{{ wordTransliteration }}</span>
          <span v-if="wordTranslation" class="word-translation">"{{ wordTranslation }}"</span>
        </div>

        <!-- Location & Status Badge -->
        <div class="preview-meta-row">
          <span v-if="isValid" class="badge-valid">
            {{ surahName ? surahName + ' • ' : '' }}سورة {{ surahNum }} • آية {{ ayahNum }} • الكلمة {{ wordNum }} من {{ totalWords }}
          </span>
          <span v-else-if="errorMessage" class="badge-invalid">
            ⚠️ {{ errorMessage }}
          </span>
        </div>

        <!-- Full Ayah Context Snippet -->
        <div v-if="ayahTextSnippet" class="ayah-context-box">
          <span class="ayah-snippet-label">سياق الآية:</span>
          <p class="ayah-snippet-content">{{ ayahTextSnippet }}</p>
        </div>
      </div>

      <!-- Location Input Controls -->
      <div class="location-controls-section">
        <label class="control-label">QURANIC LOCATION (Surah : Ayah : Word)</label>
        
        <div class="location-inputs-row">
          <div class="stepper-group">
            <span class="stepper-label">Surah</span>
            <div class="stepper-box">
              <button class="step-btn" @click="stepSurah(-1)" :disabled="surahNum <= 1">−</button>
              <input type="number" min="1" max="114" v-model.number="surahNum" class="stepper-input" @input="onNumbersChange" />
              <button class="step-btn" @click="stepSurah(1)" :disabled="surahNum >= 114">+</button>
            </div>
          </div>

          <div class="stepper-divider">:</div>

          <div class="stepper-group">
            <span class="stepper-label">Ayah</span>
            <div class="stepper-box">
              <button class="step-btn" @click="stepAyah(-1)" :disabled="ayahNum <= 1">−</button>
              <input type="number" min="1" :max="maxAyahsForSurah" v-model.number="ayahNum" class="stepper-input" @input="onNumbersChange" />
              <button class="step-btn" @click="stepAyah(1)" :disabled="ayahNum >= maxAyahsForSurah">+</button>
            </div>
          </div>

          <div class="stepper-divider">:</div>

          <div class="stepper-group">
            <span class="stepper-label">Word</span>
            <div class="stepper-box">
              <button class="step-btn" @click="stepWord(-1)" :disabled="wordNum <= 1">−</button>
              <input type="number" min="1" :max="totalWords || 100" v-model.number="wordNum" class="stepper-input" @input="onNumbersChange" />
              <button class="step-btn" @click="stepWord(1)" :disabled="totalWords > 0 && wordNum >= totalWords">+</button>
            </div>
          </div>
        </div>

        <!-- Direct Raw Location Input -->
        <div class="raw-location-row">
          <span class="raw-label">Raw Location:</span>
          <input 
            type="text" 
            v-model="rawLocationInput" 
            class="raw-input" 
            placeholder="e.g. 85:1:1" 
            @input="onRawInput" 
          />
        </div>
      </div>

      <!-- Action Buttons -->
      <div class="modal-footer">
        <button class="btn btn-secondary" @click="close">Cancel</button>
        <button 
          class="btn btn-primary" 
          :disabled="!isValid || isLoading || !previewWord" 
          @click="save"
        >
          Save
        </button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue';
import type { AlignedWord } from '../types/aligner';
import { projectStore } from '../services/projectStore';
import { getQuranWordByLocation, Quran } from '../services/Quran';
import { X, Loader2 } from 'lucide-vue-next';

const visible = ref(false);
const targetWord = ref<AlignedWord | null>(null);

const surahNum = ref(1);
const ayahNum = ref(1);
const wordNum = ref(1);
const rawLocationInput = ref('1:1:1');

const previewWord = ref('');
const ayahTextSnippet = ref('');
const surahName = ref('');
const wordTransliteration = ref('');
const wordTranslation = ref('');
const totalWords = ref(0);
const isLoading = ref(false);
const isValid = ref(true);
const errorMessage = ref('');

const maxAyahsForSurah = computed(() => {
  const count = Quran.getVerseCount(surahNum.value);
  return count > 0 ? count : 286;
});

let debounceTimer: ReturnType<typeof setTimeout> | null = null;

function open(word: AlignedWord) {
  targetWord.value = word;
  
  const parts = word.location.split(':');
  surahNum.value = parseInt(parts[0] || '1', 10);
  ayahNum.value = parseInt(parts[1] || '1', 10);
  wordNum.value = parseInt(parts[2] || '1', 10);
  rawLocationInput.value = word.location;
  
  previewWord.value = word.word;
  ayahTextSnippet.value = '';
  surahName.value = '';
  wordTransliteration.value = '';
  wordTranslation.value = '';
  errorMessage.value = '';
  isValid.value = true;
  visible.value = true;

  fetchQuranWord();
}

function close() {
  visible.value = false;
  targetWord.value = null;
  if (debounceTimer) clearTimeout(debounceTimer);
}

function onNumbersChange() {
  rawLocationInput.value = `${surahNum.value}:${ayahNum.value}:${wordNum.value}`;
  scheduleFetch();
}

function onRawInput() {
  const parts = rawLocationInput.value.split(':');
  if (parts.length === 3) {
    const s = parseInt(parts[0], 10);
    const a = parseInt(parts[1], 10);
    const w = parseInt(parts[2], 10);
    if (!isNaN(s) && s >= 1 && s <= 114) surahNum.value = s;
    if (!isNaN(a) && a >= 1) ayahNum.value = a;
    if (!isNaN(w) && w >= 1) wordNum.value = w;
  }
  scheduleFetch();
}

function stepSurah(delta: number) {
  surahNum.value = Math.max(1, Math.min(114, surahNum.value + delta));
  if (ayahNum.value > maxAyahsForSurah.value) {
    ayahNum.value = maxAyahsForSurah.value;
  }
  onNumbersChange();
}

function stepAyah(delta: number) {
  const max = maxAyahsForSurah.value;
  ayahNum.value = Math.max(1, Math.min(max, ayahNum.value + delta));
  onNumbersChange();
}

function stepWord(delta: number) {
  const max = totalWords.value > 0 ? totalWords.value : 100;
  wordNum.value = Math.max(1, Math.min(max, wordNum.value + delta));
  onNumbersChange();
}

function scheduleFetch() {
  if (debounceTimer) clearTimeout(debounceTimer);
  debounceTimer = setTimeout(() => {
    fetchQuranWord();
  }, 100);
}

async function fetchQuranWord() {
  const loc = `${surahNum.value}:${ayahNum.value}:${wordNum.value}`;
  isLoading.value = true;
  errorMessage.value = '';

  // 1. Instant optimistic lookup from loaded project if matching
  const existingWord = projectStore.findWordByLocation(loc);
  if (existingWord) {
    previewWord.value = existingWord.word;
    isValid.value = true;
  }

  // 2. Fetch canonical Uthmani text directly via Quran service (matching QuranCaption)
  try {
    const quranData = await getQuranWordByLocation(surahNum.value, ayahNum.value, wordNum.value);
    if (quranData.success && quranData.word) {
      previewWord.value = quranData.word;
      ayahTextSnippet.value = quranData.ayah_text || '';
      surahName.value = quranData.surah_name || '';
      wordTransliteration.value = quranData.transliteration || '';
      wordTranslation.value = quranData.translation || '';
      totalWords.value = quranData.total_words || 0;
      isValid.value = true;
      errorMessage.value = '';
      isLoading.value = false;
      return;
    } else if (quranData.error) {
      isValid.value = false;
      errorMessage.value = quranData.error;
      if (!existingWord) {
        previewWord.value = '';
        ayahTextSnippet.value = '';
      }
      isLoading.value = false;
      return;
    }
  } catch (err: any) {
    console.warn('Local Quran lookup failed, falling back to engine:', err);
  }

  // No HTTP fallback needed — local Quran data is complete
  if (!isValid.value && !existingWord) {
    isValid.value = false;
    errorMessage.value = errorMessage.value || 'Invalid Quranic Location';
  }
  isLoading.value = false;
}

function save() {
  if (!targetWord.value || !isValid.value || !previewWord.value) return;
  const newLoc = `${surahNum.value}:${ayahNum.value}:${wordNum.value}`;
  projectStore.rebindWordLocation(targetWord.value, newLoc, previewWord.value);
  close();
}

function handleKeydown(e: KeyboardEvent) {
  if (!visible.value) return;
  if (e.key === 'Escape') {
    close();
  } else if (e.key === 'Enter' && isValid.value && !isLoading.value && previewWord.value) {
    save();
  }
}

onMounted(() => {
  window.addEventListener('keydown', handleKeydown);
});

onUnmounted(() => {
  window.removeEventListener('keydown', handleKeydown);
});

defineExpose({
  open,
  close,
});
</script>

<style scoped>
.modal-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.72);
  backdrop-filter: blur(8px);
  z-index: 9999;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 16px;
}

.edit-word-modal {
  width: 100%;
  max-width: 440px;
  background: rgba(15, 23, 42, 0.95);
  border: 1px solid rgba(255, 255, 255, 0.12);
  border-radius: 12px;
  box-shadow: 0 16px 40px rgba(0, 0, 0, 0.6);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.modal-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  padding: 16px 20px 12px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
}

.header-titles {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.modal-title {
  font-size: 15px;
  font-weight: 700;
  color: #fff;
  margin: 0;
}

.modal-subtitle {
  font-size: 11px;
  color: var(--text-dim);
}

.close-btn {
  background: transparent;
  border: none;
  color: var(--text-dim);
  cursor: pointer;
  padding: 4px;
  border-radius: 4px;
  transition: all 0.1s ease;
}
.close-btn:hover {
  color: #fff;
  background: rgba(255, 255, 255, 0.08);
}

/* Word Preview Card */
.word-preview-card {
  padding: 20px;
  background: rgba(0, 0, 0, 0.25);
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
}

.preview-arabic-container {
  min-height: 54px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.preview-uthmani-text {
  font-family: var(--font-arabic);
  font-size: 2.4rem;
  color: #10b981;
  direction: rtl;
  text-shadow: 0 0 12px rgba(16, 185, 129, 0.25);
}

.word-meanings-row {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 11px;
}

.word-transliteration {
  color: #38bdf8;
  font-weight: 600;
}

.word-translation {
  color: var(--text-secondary);
  font-style: italic;
}

.loading-icon {
  color: #10b981;
}

.preview-meta-row {
  display: flex;
  align-items: center;
  justify-content: center;
}

.badge-valid {
  font-size: 11px;
  font-weight: 600;
  color: #a7f3d0;
  background: rgba(16, 185, 129, 0.15);
  border: 1px solid rgba(16, 185, 129, 0.3);
  padding: 2px 10px;
  border-radius: 12px;
}

.badge-invalid {
  font-size: 11px;
  font-weight: 600;
  color: #fca5a5;
  background: rgba(239, 68, 68, 0.15);
  border: 1px solid rgba(239, 68, 68, 0.3);
  padding: 2px 10px;
  border-radius: 12px;
}

.ayah-context-box {
  width: 100%;
  padding: 8px 12px;
  border-radius: 6px;
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid rgba(255, 255, 255, 0.05);
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.ayah-snippet-label {
  font-size: 10px;
  color: var(--text-dim);
  text-align: right;
  direction: rtl;
}

.ayah-snippet-content {
  font-family: var(--font-arabic);
  font-size: 13px;
  line-height: 1.6;
  color: var(--text-secondary);
  direction: rtl;
  text-align: justify;
  margin: 0;
}

/* Location Controls */
.location-controls-section {
  padding: 16px 20px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.control-label {
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.05em;
  color: var(--text-dim);
}

.location-inputs-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.stepper-group {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  flex: 1;
}

.stepper-label {
  font-size: 10px;
  color: var(--text-dim);
}

.stepper-box {
  display: flex;
  align-items: center;
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 6px;
  width: 100%;
  overflow: hidden;
}

.step-btn {
  background: transparent;
  border: none;
  color: var(--text-secondary);
  font-size: 14px;
  font-weight: 700;
  padding: 6px 10px;
  cursor: pointer;
  transition: all 0.1s ease;
}
.step-btn:hover:not(:disabled) {
  background: rgba(255, 255, 255, 0.1);
  color: #fff;
}
.step-btn:disabled {
  opacity: 0.3;
  cursor: not-allowed;
}

.stepper-input {
  width: 100%;
  text-align: center;
  background: transparent;
  border: none;
  color: #fff;
  font-size: 13px;
  font-weight: 700;
  padding: 6px 0;
  outline: none;
  -moz-appearance: textfield;
}
.stepper-input::-webkit-outer-spin-button,
.stepper-input::-webkit-inner-spin-button {
  -webkit-appearance: none;
  margin: 0;
}

.stepper-divider {
  font-size: 14px;
  font-weight: 700;
  color: var(--text-dim);
  margin-top: 14px;
}

.raw-location-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 4px;
}

.raw-label {
  font-size: 11px;
  color: var(--text-dim);
  white-space: nowrap;
}

.raw-input {
  flex: 1;
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 6px;
  color: #fff;
  font-size: 12px;
  font-family: monospace;
  font-weight: 600;
  padding: 6px 10px;
  outline: none;
}
.raw-input:focus {
  border-color: #10b981;
}

/* Footer */
.modal-footer {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
  padding: 12px 20px;
  border-top: 1px solid rgba(255, 255, 255, 0.08);
  background: rgba(0, 0, 0, 0.15);
}

.btn {
  padding: 7px 16px;
  font-size: 12px;
  font-weight: 600;
  border-radius: 6px;
  border: none;
  cursor: pointer;
  transition: all 0.15s ease;
}

.btn-secondary {
  background: rgba(255, 255, 255, 0.08);
  color: var(--text-secondary);
}
.btn-secondary:hover {
  background: rgba(255, 255, 255, 0.12);
  color: #fff;
}

.btn-primary {
  background: #10b981;
  color: #fff;
}
.btn-primary:hover:not(:disabled) {
  background: #059669;
}
.btn-primary:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}
</style>
