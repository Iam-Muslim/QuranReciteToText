<template>
  <header class="top-navbar glass-panel" data-tauri-drag-region>
    <!-- Brand & Tab Switcher (Left) -->
    <div class="brand-section">
      <div class="brand-header" @click="projectStore.currentTab.value = 'projects'">
        <img src="/logo.png" alt="Logo" class="brand-icon-img" />
        <span class="brand-title">Quran Recite2Text</span>
      </div>

      <!-- Glowing Auto-Update Notification Button (from QuranCaption) -->
      <button 
        v-if="versionService.hasUpdate.value"
        class="update-nav-btn" 
        @click="$emit('open-update-modal')" 
        title="New update available! Click to install"
      >
        <Sparkles :size="12" class="text-sky" />
        <span class="update-nav-text">v{{ versionService.latestVersion.value }}</span>
        <span class="update-pulse-ring"></span>
      </button>

      <div class="tab-divider"></div>

      <!-- First Tab Switcher: Projects / Studio -->
      <nav class="view-tabs">
        <button 
          class="tab-btn" 
          :class="{ 'active': projectStore.currentTab.value === 'projects' }"
          @click="projectStore.currentTab.value = 'projects'"
          title="Projects Hub (Create, Open, Manage Projects)"
        >
          <FolderKanban :size="13" />
          <span>Projects</span>
        </button>

        <button 
          class="tab-btn" 
          :class="{ 'active': projectStore.currentTab.value === 'studio' }"
          @click="projectStore.currentTab.value = 'studio'"
          title="Studio Workstation (Waveform & Mushaf Editor)"
        >
          <Sliders :size="13" />
          <span>Studio</span>
        </button>
      </nav>
    </div>

    <!-- Centered Ayah Banner without Tashkeel -->
    <div class="center-ayah-banner" title="وما اسالكم عليه من اجر ان اجري الا على رب العالمين">
      <span class="ayah-text">وما اسالكم عليه من اجر ان اجري الا على رب العالمين</span>
    </div>



    <!-- Right-Aligned Action Controls -->
    <div class="right-actions">
      <!-- Undo / Redo (Right Aligned) -->
      <button 
        class="btn-icon" 
        @click="projectStore.undo()" 
        :disabled="!projectStore.canUndo.value"
        title="Undo boundary edit (Ctrl+Z)"
      >
        <Undo2 :size="15" />
      </button>

      <button 
        class="btn-icon" 
        @click="projectStore.redo()" 
        :disabled="!projectStore.canRedo.value"
        title="Redo (Ctrl+Y)"
      >
        <Redo2 :size="15" />
      </button>

      <div class="divider"></div>

      <!-- Autosave Status Indicator Pill -->
      <div 
        class="autosave-status-pill" 
        :class="projectStore.saveStatus.value" 
        @click="saveProject"
        :title="autosaveTooltip"
      >
        <span v-if="projectStore.saveStatus.value === 'saving'" class="status-dot saving-spinner"></span>
        <span v-else-if="projectStore.saveStatus.value === 'unsaved'" class="status-dot unsaved-dot"></span>
        <span v-else-if="projectStore.saveStatus.value === 'error'" class="status-dot error-dot"></span>
        <Check v-else :size="11" class="saved-icon" />
        
        <span class="status-label">
          {{ autosaveLabel }}
        </span>
      </div>

      <!-- Quick Save Project -->
      <button 
        class="btn-icon save-btn-rel" 
        @click="saveProject" 
        :disabled="projectStore.isSaving.value"
        :title="saveSuccess ? 'Saved' : (projectStore.isDirty.value ? 'Unsaved edits - Click to save' : 'All changes saved')"
        :class="{ 'text-green': saveSuccess, 'has-unsaved': projectStore.isDirty.value }"
      >
        <Check v-if="saveSuccess" :size="15" />
        <Save v-else :size="15" />
        <span v-if="projectStore.isDirty.value && !saveSuccess" class="unsaved-badge-dot"></span>
      </button>

      <!-- Auditor Toggle -->
      <button 
        class="btn-icon auditor-btn" 
        :class="{ 'active': projectStore.issuesDrawerOpen.value }"
        @click="projectStore.issuesDrawerOpen.value = !projectStore.issuesDrawerOpen.value"
        title="Confidence Auditor"
      >
        <AlertCircle :size="15" />
        <span v-if="projectStore.issues.value.length > 0" class="issue-pill">
          {{ projectStore.issues.value.length }}
        </span>
      </button>

      <!-- Export Button -->
      <button class="btn-export" @click="$emit('open-export-modal')" title="Export Subtitles, Karaoke & Project">
        <Download :size="13" />
        <span>Export</span>
      </button>

      <!-- Custom Window Controls (Directly beside Export, matching QuranCaption TitleBar) -->
      <div class="window-controls-divider"></div>
      <div class="window-controls">
        <button 
          class="win-btn win-min" 
          @click="minimizeWindow" 
          title="Minimize" 
          aria-label="Minimize"
        >
          <Minus :size="13" />
        </button>
        <button 
          class="win-btn win-max" 
          @click="toggleMaximizeWindow" 
          :title="isMaximized ? 'Restore Down' : 'Maximize'" 
          :aria-label="isMaximized ? 'Restore Down' : 'Maximize'"
        >
          <Copy v-if="isMaximized" :size="11" class="restore-icon" />
          <Square v-else :size="11" />
        </button>
        <button 
          class="win-btn win-close" 
          @click="closeWindow" 
          title="Close" 
          aria-label="Close"
        >
          <X :size="14" />
        </button>
      </div>
    </div>
  </header>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue';
import { projectStore } from '../services/projectStore';
import { versionService } from '../services/VersionService';
import { getCurrentWindow } from '@tauri-apps/api/window';
import { 
  Undo2, 
  Redo2, 
  Download, 
  AlertCircle, 
  Check, 
  Save,
  FolderKanban,
  Sliders,
  Minus,
  Square,
  Copy,
  X,
  Sparkles
} from 'lucide-vue-next';

defineEmits<{
  (e: 'open-export-modal'): void;
  (e: 'open-update-modal'): void;
}>();

const saveSuccess = ref(false);

const autosaveLabel = computed(() => {
  if (projectStore.saveStatus.value === 'saving') return 'Saving...';
  if (projectStore.saveStatus.value === 'unsaved') return 'Unsaved';
  if (projectStore.saveStatus.value === 'error') return 'Save failed';
  if (projectStore.lastSavedAt.value) {
    const d = projectStore.lastSavedAt.value;
    const hh = String(d.getHours()).padStart(2, '0');
    const mm = String(d.getMinutes()).padStart(2, '0');
    const ss = String(d.getSeconds()).padStart(2, '0');
    return `Saved ${hh}:${mm}:${ss}`;
  }
  return 'Saved';
});

const autosaveTooltip = computed(() => {
  if (projectStore.saveStatus.value === 'unsaved') return 'Unsaved changes exist (idle autosave in ~15s or click to save now)';
  if (projectStore.saveStatus.value === 'saving') return 'Saving project state to disk...';
  if (projectStore.lastSavedAt.value) return `Last saved at ${projectStore.lastSavedAt.value.toLocaleTimeString()}`;
  return 'All changes saved to project';
});

async function saveProject() {
  saveSuccess.value = false;
  const ok = await projectStore.saveActiveProject();
  if (ok) {
    saveSuccess.value = true;
    setTimeout(() => { saveSuccess.value = false; }, 2000);
  }
}

const isMaximized = ref(false);

async function minimizeWindow() {
  try {
    const win = getCurrentWindow();
    await win.minimize();
  } catch (e) {
    console.debug('Window minimize error', e);
  }
}

async function toggleMaximizeWindow() {
  try {
    const win = getCurrentWindow();
    if (await win.isMaximized()) {
      await win.unmaximize();
      isMaximized.value = false;
    } else {
      await win.maximize();
      isMaximized.value = true;
    }
  } catch (e) {
    console.debug('Window maximize error', e);
  }
}

async function closeWindow() {
  try {
    const win = getCurrentWindow();
    if (await win.isDecorated()) {
      await win.setDecorations(false);
    }
    await win.close();
  } catch (e) {
    console.debug('Window close error', e);
    if (confirm('Are you sure you want to close Quran Recite2Text?')) {
      window.close();
    }
  }
}
</script>

<style scoped>
.top-navbar {
  height: var(--header-height);
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 12px 0 16px;
  position: relative;
  z-index: 50;
  border-bottom: 1px solid var(--border-subtle);
  background: var(--bg-surface);
  -webkit-app-region: drag;
  user-select: none;
}

.brand-section,
.view-tabs,
.tab-btn,
.right-actions,
.btn-icon,
.autosave-status-pill,
.btn-export,
.window-controls {
  -webkit-app-region: no-drag;
}

.brand-section {
  display: flex;
  align-items: center;
  gap: 12px;
}
.brand-header {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  user-select: none;
}
.brand-icon-img {
  width: 20px;
  height: 20px;
  border-radius: 4px;
  object-fit: contain;
}
.brand-title {
  font-size: 0.88rem;
  font-weight: 600;
  letter-spacing: -0.01em;
  color: var(--text-main);
}

/* Centered Ayah Banner between left and right controls */
.center-ayah-banner {
  position: absolute;
  left: 50%;
  transform: translateX(-50%);
  display: flex;
  align-items: center;
  justify-content: center;
  pointer-events: none;
  user-select: none;
  max-width: 48%;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.ayah-text {
  font-family: 'Amiri', 'Amiri Quran', 'Traditional Arabic', serif;
  font-size: 0.94rem;
  font-weight: 500;
  letter-spacing: 0.02em;
  color: #94a3b8;
  direction: rtl;
  text-shadow: 0 1px 2px rgba(0, 0, 0, 0.4);
  transition: color 0.2s ease, opacity 0.2s ease;
  opacity: 0.85;
}

.top-navbar:hover .ayah-text {
  color: #e2e8f0;
  opacity: 1;
}

.tab-divider {
  width: 1px;
  height: 16px;
  background: var(--border-subtle);
}

.view-tabs {
  display: flex;
  align-items: center;
  background: var(--bg-base);
  border: 1px solid var(--border-subtle);
  border-radius: 5px;
  padding: 2px;
  gap: 2px;
}

.tab-btn {
  display: flex;
  align-items: center;
  gap: 5px;
  padding: 3px 9px;
  border-radius: 3px;
  font-size: 0.72rem;
  font-weight: 500;
  color: var(--text-muted);
  background: transparent;
  border: 1px solid transparent;
  cursor: pointer;
  transition: all 0.1s ease;
}

.tab-btn:hover {
  color: var(--text-main);
}

.tab-btn.active {
  background: var(--bg-surface-elevated);
  color: var(--text-main);
  border-color: var(--border-medium);
}



.right-actions {
  display: flex;
  align-items: center;
  gap: 5px;
}

.divider {
  width: 1px;
  height: 16px;
  background: var(--border-subtle);
  margin: 0 2px;
}

.auditor-btn {
  position: relative;
}
.auditor-btn.active {
  background: var(--bg-surface-elevated);
  color: var(--text-main);
  border-color: var(--border-medium);
}
.issue-pill {
  position: absolute;
  top: 1px;
  right: 1px;
  background: var(--ruby-primary);
  color: #fff;
  font-size: 0.58rem;
  font-weight: 600;
  width: 13px;
  height: 13px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
}

.btn-export {
  display: flex;
  align-items: center;
  gap: 4px;
  background: var(--accent-primary);
  color: #ffffff;
  border: 1px solid var(--accent-hover);
  border-radius: 5px;
  padding: 4px 10px;
  font-size: 0.75rem;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.1s ease;
  margin-left: 4px;
}
.btn-export:hover {
  background: var(--accent-hover);
}

.text-green {
  color: var(--emerald-primary) !important;
}

.autosave-status-pill {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 3px 8px;
  border-radius: 9999px;
  font-size: 0.69rem;
  font-weight: 500;
  user-select: none;
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid var(--border-subtle);
  color: var(--text-muted);
  cursor: pointer;
  transition: all 0.15s ease;
}
.autosave-status-pill:hover {
  background: rgba(255, 255, 255, 0.06);
  border-color: var(--border-medium);
}
.autosave-status-pill.saved {
  color: #34d399;
  border-color: rgba(52, 211, 153, 0.22);
}
.autosave-status-pill.saving {
  color: #60a5fa;
  border-color: rgba(96, 165, 250, 0.25);
}
.autosave-status-pill.unsaved {
  color: #fbbf24;
  border-color: rgba(251, 191, 36, 0.25);
}
.autosave-status-pill.error {
  color: #f87171;
  border-color: rgba(248, 113, 113, 0.25);
}

.status-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  display: inline-block;
}
.unsaved-dot {
  background: #fbbf24;
  box-shadow: 0 0 5px rgba(251, 191, 36, 0.6);
}
.error-dot {
  background: #f87171;
}
.saving-spinner {
  border: 1.5px solid rgba(96, 165, 250, 0.3);
  border-top-color: #60a5fa;
  animation: spin 0.7s linear infinite;
}
.saved-icon {
  color: #34d399;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

/* Window Control Buttons (Directly adapted from QuranCaption TitleBar) */
.window-controls-divider {
  width: 1px;
  height: 16px;
  background: var(--border-subtle);
  margin: 0 4px;
}

.window-controls {
  display: flex;
  align-items: center;
  gap: 2px;
}

.win-btn {
  width: 28px;
  height: 28px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 6px;
  border: none;
  background: transparent;
  color: var(--text-dim);
  cursor: pointer;
  transition: all 0.12s ease;
  padding: 0;
}

.win-btn:hover {
  background: rgba(255, 255, 255, 0.08);
  color: var(--text-main);
}

.win-close:hover {
  background: #dc2626 !important;
  color: #ffffff !important;
}

.restore-icon {
  transform: rotate(180deg);
}

/* Glowing Auto-Update Notification Button (from QuranCaption) */
.update-nav-btn {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  background: rgba(14, 165, 233, 0.14);
  border: 1px solid rgba(14, 165, 233, 0.35);
  border-radius: 999px;
  padding: 3px 9px;
  font-size: 0.69rem;
  font-weight: 600;
  color: #38bdf8;
  cursor: pointer;
  position: relative;
  transition: all 0.15s ease;
  margin-left: 2px;
}
.update-nav-btn:hover {
  background: rgba(14, 165, 233, 0.25);
  border-color: #38bdf8;
  box-shadow: 0 0 12px rgba(56, 189, 248, 0.35);
}
.text-sky {
  color: #38bdf8;
}
.update-nav-text {
  font-family: monospace;
}
.update-pulse-ring {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #38bdf8;
  box-shadow: 0 0 6px #38bdf8;
  animation: pulse-glow 1.5s infinite;
}

@keyframes pulse-glow {
  0% { transform: scale(0.95); opacity: 0.7; }
  50% { transform: scale(1.3); opacity: 1; }
  100% { transform: scale(0.95); opacity: 0.7; }
}
</style>
