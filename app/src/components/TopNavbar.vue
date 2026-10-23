<template>
  <header class="top-navbar">
    <!-- Left: Brand, View Tabs, Update badge -->
    <div class="nav-left">
      <button class="brand-btn" @click="switchTab('projects')" title="Quran Recite2Text">
        <img src="/logo.png" alt="Logo" class="brand-icon-img" />
      </button>

      <!-- Modern Segmented Pill Control -->
      <nav class="view-tabs" role="tablist">
        <span class="tab-indicator" :class="`pos-${projectStore.currentTab.value === 'projects' ? 0 : 1}`"></span>
        <button
          class="tab-btn"
          role="tab"
          :aria-selected="projectStore.currentTab.value === 'projects'"
          :class="{ 'active': projectStore.currentTab.value === 'projects' }"
          @click="switchTab('projects')"
        >
          <span>Projects</span>
        </button>

        <button
          class="tab-btn"
          role="tab"
          :aria-selected="projectStore.currentTab.value === 'studio'"
          :class="{ 'active': projectStore.currentTab.value === 'studio' }"
          @click="switchTab('studio')"
        >
          <span>Studio</span>
        </button>
      </nav>

      <!-- Sidebar Toggle (Studio Mode Only) -->
      <button
        v-if="projectStore.currentTab.value === 'studio'"
        class="btn-icon sidebar-toggle-btn"
        :class="{ 'active': !projectStore.sidebarCollapsed.value }"
        @click="projectStore.sidebarCollapsed.value = !projectStore.sidebarCollapsed.value"
        :title="projectStore.sidebarCollapsed.value ? 'Show Recitations (Ctrl+B)' : 'Hide Recitations (Ctrl+B)'"
        aria-label="Toggle Recitations Sidebar"
      >
        <PanelLeft :size="14" />
      </button>

      <!-- Subtle Update Badge (Desktop Only) -->
      <button
        v-if="isTauri && versionService.hasUpdate.value"
        class="update-nav-btn"
        @click="$emit('open-update-modal')"
        title="Update Available"
      >
        <span class="update-dot"></span>
        <span class="update-nav-text">Update</span>
      </button>
    </div>

    <!-- Center: Ayah (Quran font, always visible, window drag area) -->
    <div class="nav-center-ayah" dir="rtl" lang="ar" aria-hidden="true" data-tauri-drag-region>
      الحمد لله رب العالمين
    </div>

    <!-- Right: Tool Cluster & Window Controls -->
    <div class="right-actions">
      <!-- Edit / History Group with clear labels -->
      <div class="nav-btn-group" role="group" aria-label="History actions">
        <button
          class="nav-tool-btn"
          @click="projectStore.undo()"
          :disabled="!projectStore.canUndo.value"
          title="Undo (Ctrl+Z)"
          aria-label="Undo last change"
        >
          <Undo2 :size="13" />
          <span class="nav-btn-label">Undo</span>
        </button>
        <button
          class="nav-tool-btn"
          @click="projectStore.redo()"
          :disabled="!projectStore.canRedo.value"
          title="Redo (Ctrl+Y)"
          aria-label="Redo last change"
        >
          <Redo2 :size="13" />
          <span class="nav-btn-label">Redo</span>
        </button>
      </div>

      <!-- Clear, Intuitive Save Button & Status -->
      <button
        class="nav-save-btn"
        :class="[`status-${projectStore.saveStatus.value}`, { 'is-saving': projectStore.isSaving.value }]"
        @click="saveProject"
        :disabled="projectStore.isSaving.value"
        :title="autosaveTooltip"
      >
        <span v-if="projectStore.saveStatus.value === 'saving'" class="saving-spinner"></span>
        <Save v-else-if="projectStore.saveStatus.value === 'unsaved'" :size="13" class="save-icon unsaved" />
        <AlertCircle v-else-if="projectStore.saveStatus.value === 'error'" :size="13" class="save-icon error" />
        <Check v-else :size="13" class="save-icon saved" />

        <span class="save-btn-text">
          <template v-if="projectStore.saveStatus.value === 'saving'">Saving…</template>
          <template v-else-if="projectStore.saveStatus.value === 'unsaved'">Save</template>
          <template v-else-if="projectStore.saveStatus.value === 'error'">Retry</template>
          <template v-else>Saved</template>
        </span>
      </button>

      <!-- Theme Switcher (bulb) -->
      <button
        class="btn-icon theme-bulb"
        :class="{ 'lit': theme === 'light' }"
        @click="setTheme(theme === 'dark' ? 'light' : 'dark')"
        :title="theme === 'dark' ? 'Turn on the light' : 'Turn off the light'"
        aria-label="Toggle Theme"
      >
        <Lightbulb :size="15" />
      </button>

      <!-- Window Controls (Desktop Only) -->
      <template v-if="isTauri">
        <div class="window-controls-divider"></div>
        <div class="window-controls">
          <button class="win-btn win-min" @click="minimizeWindow" title="Minimize" aria-label="Minimize">
            <Minus :size="12" />
          </button>
          <button
            class="win-btn win-max"
            @click="toggleMaximizeWindow"
            :title="isMaximized ? 'Restore' : 'Maximize'"
            :aria-label="isMaximized ? 'Restore' : 'Maximize'"
          >
            <Copy v-if="isMaximized" :size="10" class="restore-icon" />
            <Square v-else :size="10" />
          </button>
          <button
            class="win-btn win-close"
            :class="{ 'armed': closeArmed }"
            @click="closeWindow"
            :title="closeArmed ? 'Click to confirm close' : 'Close'"
            aria-label="Close"
          >
            <X :size="13" />
          </button>
        </div>
      </template>
    </div>
  </header>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue';
import { projectStore } from '../services/projectStore';
import { versionService } from '../services/VersionService';
import { isTauriEnvironment } from '../services/api';
import { getCurrentWindow } from '@tauri-apps/api/window';
import {
  Undo2,
  Redo2,
  AlertCircle,
  Check,
  Save,
  Minus,
  Square,
  Copy,
  X,
  Lightbulb,
  PanelLeft
} from 'lucide-vue-next';

defineEmits<{
  (e: 'open-update-modal'): void;
}>();

/* ---- Light/dark theme toggle ---- */
const theme = ref<string>(localStorage.getItem('quran_theme') || 'dark');

function applyTheme() {
  document.documentElement.dataset.theme = theme.value;
  window.dispatchEvent(new Event('quran-theme-changed'));
}

function setTheme(mode: string) {
  theme.value = mode;
  try { localStorage.setItem('quran_theme', mode); } catch {}
  applyTheme();
}

onMounted(() => {
  applyTheme();
});

const saveSuccess = ref(false);

const autosaveTooltip = computed(() => {
  if (projectStore.saveStatus.value === 'unsaved') return 'Unsaved changes (click to save)';
  if (projectStore.saveStatus.value === 'saving') return 'Saving to disk...';
  if (projectStore.lastSavedAt.value) return `Saved at ${projectStore.lastSavedAt.value.toLocaleTimeString()} (click to save)`;
  return 'Saved (click to save)';
});

async function saveProject() {
  saveSuccess.value = false;
  await projectStore.saveActiveProject();
}

async function switchTab(tab: 'projects' | 'studio') {
  if (projectStore.currentTab.value === tab) return;
  if (projectStore.isDirty.value) {
    await projectStore.flushAutosave();
  }
  projectStore.currentTab.value = tab;
}

const isTauri = isTauriEnvironment();
const isMaximized = ref(false);
const closeArmed = ref(false);
let closeArmTimer: ReturnType<typeof setTimeout> | null = null;

async function minimizeWindow() {
  if (!isTauri) return;
  try {
    const win = getCurrentWindow();
    await win.minimize();
  } catch (e) {
    console.debug('Window minimize error', e);
  }
}

async function toggleMaximizeWindow() {
  if (!isTauri) return;
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
  if (!isTauri) return;
  try {
    const win = getCurrentWindow();
    if (await win.isDecorated()) {
      await win.setDecorations(false);
    }
    await win.close();
  } catch (e) {
    console.debug('Window close error', e);
    requestClose();
  }
}

function requestClose() {
  if (closeArmed.value) {
    closeArmed.value = false;
    try {
      window.close();
    } catch (e) {
      console.debug('Window close error', e);
    }
    return;
  }
  closeArmed.value = true;
  if (closeArmTimer) clearTimeout(closeArmTimer);
  closeArmTimer = setTimeout(() => { closeArmed.value = false; }, 3200);
}
</script>

<style scoped>
.top-navbar {
  height: calc(var(--header-height) + env(safe-area-inset-top, 0px));
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: env(safe-area-inset-top, 0px) 10px 0 12px;
  position: relative;
  z-index: 50;
  border-bottom: 1px solid var(--border-subtle);
  background: var(--bg-surface);
  user-select: none;
}

.brand-btn,
.view-tabs,
.tab-btn,
.sidebar-toggle-btn,
.update-nav-btn,
.right-actions,
.save-chip,
.window-controls {
  -webkit-app-region: no-drag;
}

.nav-left {
  display: flex;
  align-items: center;
  gap: 12px;
}

.brand-btn {
  display: flex;
  align-items: center;
  cursor: pointer;
  border-radius: var(--radius-sm);
  padding: 2px;
  background: transparent;
  border: none;
  transition: opacity var(--dur-fast) var(--ease-out);
}
.brand-btn:hover {
  opacity: 0.85;
}
.brand-icon-img {
  width: 22px;
  height: 22px;
  border-radius: 6px;
  object-fit: contain;
}

/* Modern Sliding Segmented Pill */
.view-tabs {
  display: flex;
  align-items: center;
  position: relative;
  background: var(--bg-base);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-pill);
  padding: 3px;
  height: 28px;
}

.tab-indicator {
  position: absolute;
  top: 3px;
  bottom: 3px;
  left: 3px;
  width: calc(50% - 3px);
  background: var(--bg-surface-elevated);
  border: 1px solid var(--border-medium);
  border-radius: var(--radius-pill);
  box-shadow: var(--shadow-e1);
  transition: transform var(--dur-base) var(--ease-spring);
}
.tab-indicator.pos-0 { transform: translateX(0); }
.tab-indicator.pos-1 { transform: translateX(100%); }

.tab-btn {
  position: relative;
  z-index: 1;
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 0 14px;
  height: 100%;
  border-radius: var(--radius-pill);
  font-size: var(--text-xs);
  font-weight: 500;
  color: var(--text-muted);
  background: transparent;
  border: none;
  cursor: pointer;
  transition: color var(--dur-fast) var(--ease-out);
}
.tab-btn:hover {
  color: var(--text-main);
}
.tab-btn.active {
  color: var(--text-main);
  font-weight: 600;
}

.update-nav-btn {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  background: transparent;
  border: none;
  padding: 3px 8px;
  font-size: 11px;
  font-weight: 500;
  color: var(--sky-primary);
  cursor: pointer;
  border-radius: var(--radius-sm);
  transition: background var(--dur-fast) var(--ease-out);
}
.update-nav-btn:hover {
  background: var(--bg-surface-hover);
}
.update-nav-text {
  font-family: var(--font-mono);
}
.update-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--sky-primary);
}

.right-actions {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
}

/* History / Undo-Redo Tool Group */
.nav-btn-group {
  display: inline-flex;
  align-items: center;
  background: var(--bg-surface-elevated);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-sm);
  padding: 2px;
  gap: 2px;
}

.nav-tool-btn {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 3px 8px;
  border-radius: var(--radius-xs);
  border: none;
  background: transparent;
  color: var(--text-secondary);
  font-size: 11.5px;
  font-weight: 500;
  cursor: pointer;
  transition: all var(--dur-fast) var(--ease-out);
}
.nav-tool-btn:hover:not(:disabled) {
  background: var(--bg-surface-hover);
  color: var(--text-main);
}
.nav-tool-btn:disabled {
  opacity: 0.35;
  cursor: default;
}

/* Clear, Self-Explanatory Save Button */
.nav-save-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  border-radius: var(--radius-sm);
  font-size: 11.5px;
  font-weight: 600;
  cursor: pointer;
  border: 1px solid var(--border-subtle);
  background: var(--bg-surface-elevated);
  color: var(--text-secondary);
  transition: all var(--dur-fast) var(--ease-out);
  box-shadow: var(--shadow-e1);
}
.nav-save-btn:hover:not(:disabled) {
  background: var(--bg-surface-hover);
  border-color: var(--border-medium);
  transform: translateY(-1px);
}
.nav-save-btn:disabled {
  opacity: 0.7;
  cursor: default;
}

.nav-save-btn.status-saved {
  color: var(--emerald-primary);
  background: var(--emerald-bg);
  border-color: var(--emerald-border);
}
.nav-save-btn.status-saved:hover:not(:disabled) {
  border-color: var(--emerald-primary);
}

.nav-save-btn.status-unsaved {
  color: var(--amber-primary);
  background: var(--amber-bg);
  border-color: var(--amber-border);
  box-shadow: 0 0 8px rgba(217, 119, 6, 0.18);
}
.nav-save-btn.status-unsaved:hover:not(:disabled) {
  border-color: var(--amber-primary);
}

.nav-save-btn.status-error {
  color: var(--ruby-primary);
  background: var(--ruby-bg);
  border-color: var(--ruby-border);
}

.save-icon {
  flex-shrink: 0;
}
.save-icon.saved {
  color: var(--emerald-primary);
}
.save-icon.unsaved {
  color: var(--amber-primary);
}
.save-icon.error {
  color: var(--ruby-primary);
}

.save-btn-text {
  line-height: 1;
}

.saving-spinner {
  width: 12px;
  height: 12px;
  border-radius: 50%;
  border: 2px solid var(--accent-subtle);
  border-top-color: var(--accent-primary);
  animation: spin 0.7s linear infinite;
  flex-shrink: 0;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

/* Center Ayah */
.nav-center-ayah {
  position: absolute;
  left: 50%;
  transform: translateX(-50%);
  font-family: var(--font-quran);
  font-size: 14.5px;
  line-height: 1;
  color: var(--text-muted);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 44%;
  pointer-events: auto;
  -webkit-app-region: drag;
}

@media (max-width: 980px) {
  .nav-center-ayah {
    display: none;
  }
}

@media (max-width: 640px) {
  .top-navbar {
    padding: 0 8px;
    gap: 6px;
  }
  .nav-btn-label {
    display: none;
  }
  .tab-btn {
    padding: 0 8px;
  }
  .nav-save-btn {
    padding: 4px 8px;
  }
}

/* Theme bulb */
.theme-bulb {
  color: var(--text-dim);
}
.theme-bulb.lit {
  color: var(--gold-primary);
  filter: drop-shadow(0 0 5px rgba(var(--gold-rgb), 0.55));
}


.window-controls-divider {
  width: 1px;
  height: 16px;
  background: var(--border-subtle);
  margin: 0 4px;
}

.window-controls {
  display: flex;
  align-items: center;
  gap: 1px;
}

.win-btn {
  width: 28px;
  height: 28px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: var(--radius-sm);
  border: none;
  background: transparent;
  color: var(--text-muted);
  cursor: pointer;
  transition: all 0.12s ease;
  padding: 0;
}
.win-btn:hover {
  background: var(--hover-overlay);
  color: var(--text-main);
}
.win-close.armed {
  background: rgba(220, 38, 38, 0.85) !important;
  color: #ffffff !important;
}
.win-close:hover {
  background: var(--ruby-primary) !important;
  color: #ffffff !important;
}
.restore-icon {
  transform: rotate(180deg);
}

/* Small screens: compact chrome, keep window controls */
@media (max-width: 760px) {
  .top-navbar {
    padding: 0 6px;
  }

  .nav-left {
    gap: 6px;
  }

  .tab-btn {
    padding: 0 10px;
  }

  /* Undo/redo and the save chip hide on phones (Ctrl+Z / autosave still work) */
  .btn-group,
  .save-chip {
    display: none;
  }

  .update-nav-text {
    display: none;
  }

  .update-nav-btn {
    padding: 3px 5px;
  }
}
</style>
