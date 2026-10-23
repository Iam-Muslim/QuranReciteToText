<template>
  <aside class="surah-sidebar glass-panel" :class="{ 'collapsed': projectStore.sidebarCollapsed.value }">
    <!-- Sidebar Header -->
    <div class="sidebar-header">
      <div class="header-left-title">
        <span class="sidebar-title">Recitations</span>
        <span v-if="projectStore.project.surahs.length > 0" class="surah-count-chip">
          {{ projectStore.project.surahs.length }}
        </span>
      </div>
      <div class="header-actions">
        <button class="btn-icon add-btn" @click="$emit('add-surah')" title="Align New Recitation Audio (Ctrl+Shift+A)">
          <Plus :size="13" />
        </button>
        <button class="export-labeled-btn" @click="$emit('export')" title="Export Subtitles & Audio">
          <Download :size="12" />
          <span>Export</span>
        </button>
      </div>
    </div>

    <!-- Quick Filter for multiple recitations -->
    <div v-if="projectStore.project.surahs.length > 3" class="sidebar-search-wrap">
      <Search :size="11" class="search-icon" />
      <input 
        type="text" 
        v-model="sidebarFilter" 
        placeholder="Filter surahs…" 
        class="sidebar-search-input"
        spellcheck="false"
      />
      <button v-if="sidebarFilter" class="clear-search-btn" @click="sidebarFilter = ''">✕</button>
    </div>

    <!-- Active Recitations List -->
    <div class="surah-list">
      <div
        v-for="s in filteredSurahs"
        :key="s.surah_number"
        class="recitation-card"
        :class="{ 'active': s.surah_number === projectStore.activeSurahNumber.value }"
        @click="projectStore.selectSurah(s.surah_number)"
      >
        <!-- Surah Number Pill -->
        <span class="surah-badge">{{ String(s.surah_number).padStart(3, '0') }}</span>

        <!-- Surah Info -->
        <div class="surah-info">
          <span class="name-ar">{{ s.surah_name_arabic }}</span>
          <span class="meta-line">
            {{ s.ayahs.length }} ayahs<span v-if="s.audio_duration_seconds"> · {{ formatDuration(s.audio_duration_seconds) }}</span>
          </span>
        </div>

        <!-- Verification Toggle -->
        <button
          class="review-toggle"
          :class="{ 'is-done': s.status === 'verified' }"
          @click.stop="projectStore.toggleSurahVerified(s.surah_number)"
          :title="s.status === 'verified' ? 'Reviewed — click to send back to review' : 'Click to mark reviewed'"
        >
          <CircleCheck :size="14" v-if="s.status === 'verified'" />
          <Circle :size="14" v-else />
        </button>

        <!-- Remove Action -->
        <button
          class="btn-remove"
          :class="{ 'armed': confirmDeleteNum === s.surah_number }"
          @click.stop="requestRemove(s.surah_number)"
          :title="confirmDeleteNum === s.surah_number ? 'Confirm remove' : 'Remove recitation'"
        >
          <Trash2 :size="11" />
        </button>
      </div>

      <!-- Empty State -->
      <div v-if="projectStore.project.surahs.length === 0" class="empty-sidebar" @click="$emit('add-surah')">
        <UploadCloud :size="20" class="empty-icon" />
        <span class="empty-prompt">{{ isTauri ? 'Add Recitation Audio' : 'Import Recitation Timings' }}</span>
        <span class="empty-sub">{{ isTauri ? 'Automatic alignment & word timestamps' : 'Import JSON timings and audio files' }}</span>
      </div>
    </div>
  </aside>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue';
import { projectStore } from '../services/projectStore';
import { isTauriEnvironment } from '../services/api';
import { Plus, Trash2, UploadCloud, Search, CircleCheck, Circle, Download } from 'lucide-vue-next';

const isTauri = isTauriEnvironment();

defineEmits<{
  (e: 'add-surah'): void;
  (e: 'export'): void;
}>();

const confirmDeleteNum = ref<number | null>(null);
const sidebarFilter = ref<string>('');
let deleteArmTimer: ReturnType<typeof setTimeout> | null = null;

const filteredSurahs = computed(() => {
  const q = sidebarFilter.value.trim().toLowerCase();
  const list = projectStore.project.surahs || [];
  if (!q) return list;
  return list.filter(s => 
    s.surah_name_arabic.includes(q) || 
    (s.surah_name_english && s.surah_name_english.toLowerCase().includes(q)) ||
    String(s.surah_number) === q
  );
});

function formatDuration(secs: number): string {
  if (isNaN(secs) || secs <= 0) return '0:00';
  const m = Math.floor(secs / 60);
  const s = Math.floor(secs % 60);
  return `${m}:${String(s).padStart(2, '0')}`;
}

function requestRemove(surahNum: number) {
  if (confirmDeleteNum.value === surahNum) {
    confirmDeleteNum.value = null;
    projectStore.deleteSurah(surahNum);
    return;
  }
  confirmDeleteNum.value = surahNum;
  if (deleteArmTimer) clearTimeout(deleteArmTimer);
  deleteArmTimer = setTimeout(() => { confirmDeleteNum.value = null; }, 3200);
}
</script>

<style scoped>
.surah-sidebar {
  width: var(--sidebar-width);
  height: 100%;
  display: flex;
  flex-direction: column;
  border-right: 1px solid var(--border-subtle);
  background: var(--bg-surface);
  flex-shrink: 0;
  transition: width var(--dur-base) var(--ease-spring), opacity var(--dur-fast) var(--ease-out);
}

.surah-sidebar.collapsed {
  width: 0;
  border-right-color: transparent;
  opacity: 0;
  overflow: hidden;
  pointer-events: none;
}

.sidebar-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 10px;
  border-bottom: 1px solid var(--border-subtle);
  background: var(--bg-surface);
}
.header-left-title {
  display: flex;
  align-items: center;
  gap: 6px;
}
.sidebar-title {
  font-size: 11px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--text-muted);
}
.surah-count-chip {
  font-family: var(--font-mono);
  font-size: 10px;
  font-weight: 700;
  color: var(--text-secondary);
  background: var(--bg-surface-elevated);
  border: 1px solid var(--border-subtle);
  padding: 0 5px;
  border-radius: var(--radius-pill);
}
.header-actions {
  display: flex;
  align-items: center;
  gap: 2px;
}
.add-btn {
  padding: 4px;
  color: var(--text-muted);
}
.add-btn:hover {
  color: var(--text-main);
  background: var(--bg-surface-hover);
}

.export-labeled-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  height: 24px;
  padding: 0 8px;
  border-radius: var(--radius-xs);
  border: 1px solid var(--border-subtle);
  background: var(--bg-surface-elevated);
  color: var(--text-secondary);
  font-size: 11px;
  font-weight: 600;
  cursor: pointer;
  transition: all var(--dur-fast) var(--ease-out);
}
.export-labeled-btn:hover {
  background: var(--hover-overlay);
  border-color: var(--accent-border);
  color: var(--text-main);
}

/* Sidebar Search */
.sidebar-search-wrap {
  position: relative;
  display: flex;
  align-items: center;
  padding: 6px 8px;
  border-bottom: 1px solid var(--border-subtle);
  background: var(--bg-base);
}
.sidebar-search-wrap .search-icon {
  position: absolute;
  left: 14px;
  color: var(--text-muted);
  pointer-events: none;
}
.sidebar-search-input {
  width: 100%;
  background: var(--bg-input);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-xs);
  padding: 3px 20px 3px 24px;
  font-size: 11px;
  color: var(--text-main);
  outline: none;
  transition: all var(--dur-fast) var(--ease-out);
}
.sidebar-search-input:focus {
  border-color: var(--accent-primary);
  box-shadow: 0 0 0 1px var(--accent-subtle);
}
.clear-search-btn {
  position: absolute;
  right: 12px;
  background: none;
  border: none;
  color: var(--text-muted);
  font-size: 10px;
  cursor: pointer;
  padding: 2px;
}

.surah-list {
  flex: 1;
  overflow-y: auto;
  padding: 8px;
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.recitation-card {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 10px;
  border-radius: var(--radius-sm);
  cursor: pointer;
  border: 1px solid transparent;
  position: relative;
  background: transparent;
  transition: all var(--dur-fast) var(--ease-out);
}
.recitation-card:hover {
  background: var(--bg-surface-elevated);
}
.recitation-card.active {
  border-color: var(--accent-border);
  background: var(--accent-subtle);
}
.recitation-card.active::before {
  content: '';
  position: absolute;
  left: 0;
  top: 8px;
  bottom: 8px;
  width: 2px;
  border-radius: var(--radius-pill);
  background: var(--accent-primary);
}

.surah-badge {
  font-family: var(--font-mono);
  font-size: 10px;
  color: var(--text-muted);
  background: var(--bg-input);
  padding: 2px 5px;
  border-radius: var(--radius-xs);
  border: 1px solid var(--border-subtle);
}

.surah-info {
  display: flex;
  flex-direction: column;
  min-width: 0;
  flex: 1;
}
.name-ar {
  font-family: var(--font-arabic);
  font-size: 15px;
  color: var(--text-main);
  line-height: 1.3;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.meta-line {
  font-size: 10px;
  color: var(--text-muted);
}

.review-toggle {
  background: none;
  border: none;
  padding: 3px;
  flex-shrink: 0;
  cursor: pointer;
  color: var(--text-dim);
  border-radius: var(--radius-xs);
  display: flex;
  align-items: center;
  transition: color var(--dur-fast) var(--ease-out), background var(--dur-fast) var(--ease-out);
}
.review-toggle:hover {
  background: var(--bg-surface-hover);
  color: var(--text-main);
}
.review-toggle.is-done {
  color: var(--emerald-primary);
}

.btn-remove {
  background: none;
  border: none;
  color: var(--text-dim);
  cursor: pointer;
  padding: 3px;
  border-radius: var(--radius-xs);
  display: flex;
  align-items: center;
  opacity: 0;
  transition: all var(--dur-fast) var(--ease-out);
}
.recitation-card:hover .btn-remove {
  opacity: 0.8;
}
@media (hover: none), (max-width: 768px) {
  .btn-remove {
    opacity: 0.65;
  }
}
.btn-remove:hover,
.btn-remove.armed {
  color: var(--ruby-primary);
  background: var(--ruby-bg);
  opacity: 1;
}

/* Empty Sidebar */
.empty-sidebar {
  padding: 32px 14px;
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
  gap: 6px;
  border: 1px dashed var(--border-medium);
  border-radius: var(--radius-md);
  margin: 12px 4px;
  cursor: pointer;
  transition: all var(--dur-fast) var(--ease-out);
}
.empty-sidebar:hover {
  border-color: var(--accent-primary);
  background: var(--accent-subtle);
}
.empty-icon {
  color: var(--text-muted);
}
.empty-prompt {
  font-size: var(--text-xs);
  font-weight: 600;
  color: var(--text-main);
}
.empty-sub {
  font-size: 10px;
  color: var(--text-muted);
  line-height: 1.4;
}
</style>
