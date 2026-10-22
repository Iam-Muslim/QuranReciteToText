<template>
  <div v-if="visible" class="modal-backdrop" @click.self="close">
    <div class="edit-word-modal glass-panel anim-scale" @click.stop>
      <!-- Header -->
      <div class="modal-header">
        <h3 class="modal-title">Edit Word Location</h3>
        <button class="btn-icon close-btn" @click="close" title="Close">
          <X :size="15" />
        </button>
      </div>

      <!-- Live Uthmani Word Preview Card -->
      <div class="word-preview-card" :class="{ 'preview-invalid': !isValid && !isLoading }">
        <div class="preview-arabic-container">
          <Loader2 v-if="isLoading" class="animate-spin loading-icon" :size="32" />
          <span v-else class="preview-uthmani-text">{{ previewWord || '—' }}</span>
        </div>



        <!-- Location & Status Badge -->
        <div class="preview-meta-row">
          <span v-if="isValid" class="badge-valid">
            {{ surahName ? surahName + ' · ' : '' }}سورة {{ surahNum }} · آية {{ ayahNum }} · كلمة {{ wordNum }}
          </span>
          <span v-else-if="errorMessage" class="badge-invalid">
            ⚠️ {{ errorMessage }}
          </span>
        </div>

        <!-- Full Ayah Context Snippet -->
        <div v-if="ayahTextSnippet" class="ayah-context-box">
          <p class="ayah-snippet-content">{{ ayahTextSnippet }}</p>
        </div>
      </div>

      <!-- Location Input Controls -->
      <div class="location-controls-section">
        <span class="control-label">Surah · Ayah · Word</span>
        
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
  background: rgba(5, 6, 10, 0.62);
  backdrop-filter: blur(8px);
  z-index: 9999;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 16px;
  animation: fade-in var(--dur-base) var(--ease-out) both;
}

.edit-word-modal {
  width: 100%;
  max-width: 440px;
  background: var(--bg-surface);
  border: 1px solid var(--border-medium);
  border-radius: var(--radius-xl);
  box-shadow: var(--shadow-e4);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.modal-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  padding: 16px 20px 12px;
  border-bottom: 1px solid var(--border-subtle);
}

.header-titles {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.modal-title {
  font-size: 15px;
  font-weight: 700;
  color: var(--text-main);
  margin: 0;
}

.modal-subtitle {
  font-size: var(--text-xs);
  color: var(--text-dim);
}

.close-btn {
  background: transparent;
  border: none;
  color: var(--text-dim);
  cursor: pointer;
  padding: 4px;
  border-radius: var(--radius-xs);
  transition: color var(--dur-fast) var(--ease-out),
              background var(--dur-fast) var(--ease-out);
}
.close-btn:hover {
  color: var(--text-main);
  background: var(--bg-surface-hover);
}

/* Word Preview Card */
.word-preview-card {
  padding: 20px;
  background: var(--bg-surface);
  border-bottom: 1px solid var(--border-subtle);
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
  color: var(--emerald-primary);
  direction: rtl;
  text-shadow: var(--shadow-e1);
}



.loading-icon {
  color: var(--emerald-primary);
}

.preview-meta-row {
  display: flex;
  align-items: center;
  justify-content: center;
}

.badge-valid {
  font-size: var(--text-xs);
  font-weight: 600;
  color: var(--emerald-primary);
  background: var(--emerald-bg);
  border: 1px solid var(--emerald-border);
  padding: 2px 11px;
  border-radius: var(--radius-pill);
}

.badge-invalid {
  font-size: var(--text-xs);
  font-weight: 600;
  color: var(--ruby-primary);
  background: var(--ruby-bg);
  border: 1px solid var(--ruby-border);
  padding: 2px 11px;
  border-radius: var(--radius-pill);
}

.ayah-context-box {
  width: 100%;
  padding: 8px 12px;
  border-radius: var(--radius-sm);
  background: var(--bg-base);
  border: 1px solid var(--border-subtle);
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.ayah-snippet-label {
  font-size: 0.7rem;
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
  font-size: 0.7rem;
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
  font-size: 0.7rem;
  color: var(--text-dim);
}

.stepper-box {
  display: flex;
  align-items: center;
  background: var(--bg-input);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-sm);
  width: 100%;
  overflow: hidden;
  transition: border-color var(--dur-fast) var(--ease-out),
              box-shadow var(--dur-fast) var(--ease-out);
}
.stepper-box:focus-within {
  border-color: var(--emerald-border);
  box-shadow: 0 var(--shadow-e1);
}

.step-btn {
  background: transparent;
  border: none;
  color: var(--text-secondary);
  font-size: 14px;
  font-weight: 700;
  padding: 6px 10px;
  cursor: pointer;
  transition: background var(--dur-fast) var(--ease-out),
              color var(--dur-fast) var(--ease-out);
}
.step-btn:hover:not(:disabled) {
  background: var(--bg-surface-hover);
  color: var(--text-main);
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
  color: var(--text-main);
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
  font-size: var(--text-xs);
  color: var(--text-dim);
  white-space: nowrap;
}

.raw-input {
  flex: 1;
  background: var(--bg-input);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-sm);
  color: var(--text-main);
  font-size: var(--text-xs);
  font-family: var(--font-mono);
  font-weight: 600;
  padding: 6px 10px;
  outline: none;
  transition: border-color var(--dur-fast) var(--ease-out),
              box-shadow var(--dur-fast) var(--ease-out);
}
.raw-input:focus {
  border-color: var(--emerald-border);
  box-shadow: 0 var(--shadow-e1);
}

/* Footer */
.modal-footer {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
  padding: 12px 20px;
  border-top: 1px solid var(--border-subtle);
  background: var(--bg-surface);
}

.btn {
  padding: 7px 16px;
  font-size: var(--text-xs);
  font-weight: 600;
  border-radius: var(--radius-sm);
  border: none;
  cursor: pointer;
  transition: background var(--dur-fast) var(--ease-out),
              box-shadow var(--dur-fast) var(--ease-out);
}

.btn-secondary {
  background: var(--bg-surface-elevated);
  color: var(--text-secondary);
  border: 1px solid var(--border-subtle);
}
.btn-secondary:hover {
  background: var(--bg-surface-hover);
  color: var(--text-main);
  border-color: var(--border-medium);
}

.btn-primary {
  background: var(--emerald-primary);
  color: #fff;
}
.btn-primary:hover:not(:disabled) {
  background: var(--emerald-primary);
}
.btn-primary:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}
</style>
