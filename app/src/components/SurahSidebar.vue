<template>
  <aside class="surah-sidebar glass-panel">
    <!-- Top Action: Add Audio Recitation -->
    <div class="sidebar-header">
      <button class="add-audio-btn" @click="$emit('add-surah')" title="Align new recitation audio">
        <Plus :size="14" />
        <span>Add Recitation</span>
      </button>
    </div>

    <!-- Active Recitations List (Only Loaded/Aligned Audios in Project!) -->
    <div class="surah-list">
      <div 
        v-for="s in projectStore.project.surahs" 
        :key="s.surah_number"
        class="recitation-card"
        :class="{ 'active': s.surah_number === projectStore.activeSurahNumber.value }"
        @click="projectStore.selectSurah(s.surah_number)"
      >
        <div class="card-left">
          <span class="surah-num">{{ s.surah_number }}.</span>
          <div class="surah-info">
            <div class="surah-header-row">
              <span class="name-ar">{{ s.surah_name_arabic }}</span>
              <button 
                class="btn-done-toggle" 
                :class="s.status === 'verified' ? 'is-done' : 'is-review'"
                @click.stop="projectStore.toggleSurahVerified(s.surah_number)"
                :title="s.status === 'verified' ? 'Verified (Click to toggle)' : 'Needs review (Click to mark Done)'"
              >
                <Check v-if="s.status === 'verified'" :size="10" />
                <span>{{ s.status === 'verified' ? 'Done' : 'Review' }}</span>
              </button>
            </div>
            <span class="name-en">{{ s.surah_name_english }}</span>
            <span class="meta-line">
              {{ s.ayahs.length }} Ayahs
              <span v-if="s.audio_duration_seconds">• {{ formatDuration(s.audio_duration_seconds) }}</span>
            </span>
          </div>
        </div>

        <div class="card-right">
          <button 
            class="btn-remove" 
            @click.stop="removeSurah(s.surah_number)" 
            title="Delete recitation from project"
          >
            <Trash2 :size="13" />
          </button>
        </div>
      </div>

      <!-- Empty State if no audios aligned yet -->
      <div v-if="projectStore.project.surahs.length === 0" class="empty-sidebar" @click="$emit('add-surah')">
        <UploadCloud :size="22" class="empty-cloud-icon" />
        <span class="empty-prompt">No recitations</span>
        <span class="empty-sub">Click to align an audio file. The pipeline will auto-detect the Surah.</span>
      </div>
    </div>
  </aside>
</template>

<script setup lang="ts">
import { projectStore } from '../services/projectStore';
import { Plus, Trash2, UploadCloud, Check } from 'lucide-vue-next';

defineEmits<{
  (e: 'add-surah'): void;
}>();

function formatDuration(secs: number): string {
  if (isNaN(secs) || secs <= 0) return '0:00';
  const m = Math.floor(secs / 60);
  const s = Math.floor(secs % 60);
  return `${m}:${String(s).padStart(2, '0')}`;
}

function removeSurah(surahNum: number) {
  projectStore.deleteSurah(surahNum);
}
</script>

<style scoped>
.surah-sidebar {
  width: var(--sidebar-width);
  height: calc(100vh - var(--header-height));
  display: flex;
  flex-direction: column;
  border-right: 1px solid var(--border-subtle);
  background: var(--bg-surface);
  flex-shrink: 0;
}

.sidebar-header {
  padding: 10px;
  border-bottom: 1px solid var(--border-subtle);
}

.add-audio-btn {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  background: var(--bg-surface-elevated);
  border: 1px solid var(--border-medium);
  color: var(--text-main);
  border-radius: 5px;
  padding: 6px 10px;
  font-size: 0.74rem;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.1s ease;
}
.add-audio-btn:hover {
  background: var(--bg-surface-hover);
  border-color: var(--accent-primary);
}

.surah-list {
  flex: 1;
  overflow-y: auto;
  padding: 6px;
}

.recitation-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 10px;
  border-radius: 5px;
  cursor: pointer;
  margin-bottom: 3px;
  border: 1px solid var(--border-subtle);
  transition: all 0.1s ease;
  background: var(--bg-surface);
}
.recitation-card:hover {
  background: var(--bg-surface-elevated);
  border-color: var(--border-medium);
}
.recitation-card.active {
  border-color: var(--accent-primary);
  background: var(--accent-subtle);
}

.card-left {
  display: flex;
  align-items: flex-start;
  gap: 8px;
}
.surah-num {
  font-family: var(--font-mono);
  font-size: 0.75rem;
  font-weight: 600;
  color: var(--accent-primary);
  padding-top: 1px;
}
.surah-info {
  display: flex;
  flex-direction: column;
}
.name-ar {
  font-family: var(--font-arabic);
  font-size: 1.05rem;
  color: #fff;
  line-height: 1.15;
}
.name-en {
  font-size: 0.72rem;
  color: var(--text-muted);
}
.meta-line {
  font-family: var(--font-mono);
  font-size: 0.65rem;
  color: var(--text-dim);
  margin-top: 2px;
}

.card-right {
  display: flex;
  align-items: center;
  gap: 6px;
}
.surah-header-row {
  display: flex;
  align-items: center;
  gap: 6px;
}

.btn-done-toggle {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  padding: 1px 6px;
  border-radius: 3px;
  font-size: 0.65rem;
  font-family: var(--font-ui);
  font-weight: 600;
  cursor: pointer;
  transition: all 0.1s ease;
  line-height: 1.2;
}
.btn-done-toggle.is-done {
  background: var(--emerald-bg);
  color: var(--emerald-primary);
  border: 1px solid var(--emerald-border);
}
.btn-done-toggle.is-done:hover {
  background: rgba(34, 197, 94, 0.2);
}
.btn-done-toggle.is-review {
  background: var(--bg-surface-elevated);
  color: var(--text-muted);
  border: 1px solid var(--border-subtle);
}
.btn-done-toggle.is-review:hover {
  background: var(--bg-surface-hover);
  color: var(--text-main);
  border-color: var(--border-medium);
}

.btn-remove {
  background: none;
  border: none;
  color: var(--text-dim);
  cursor: pointer;
  padding: 2px;
  display: flex;
  align-items: center;
  opacity: 0.6;
}
.btn-remove:hover {
  color: #f87171;
  opacity: 1;
}

.empty-sidebar {
  padding: 24px 12px;
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
  gap: 6px;
  border: 1px dashed var(--border-subtle);
  border-radius: 6px;
  margin: 10px 4px;
  cursor: pointer;
  transition: all 0.12s ease;
}
.empty-sidebar:hover {
  border-color: var(--accent-primary);
  background: var(--accent-subtle);
}
.empty-cloud-icon {
  color: var(--text-muted);
}
.empty-prompt {
  font-size: 0.78rem;
  font-weight: 500;
  color: var(--text-main);
}
.empty-sub {
  font-size: 0.68rem;
  color: var(--text-muted);
  line-height: 1.35;
}
</style>
