<template>
  <div class="app-layout">
    <!-- Top Global Navigation Bar -->
    <TopNavbar 
      @open-update-modal="updateModalRef?.open()" 
    />

    <!-- First Tab: Projects Hub (Visual Studio / Editor Start Hub) -->
    <ProjectsHub v-show="projectStore.currentTab.value === 'projects'" />

    <!-- Second Tab: Main Studio Workspace (Cached in Memory for 0% CPU & Disk Spikes) -->
    <div v-show="projectStore.currentTab.value === 'studio'" class="workspace-body">
      <!-- Mobile drawer backdrops -->
      <div
        class="sidebar-backdrop"
        :class="{ visible: !projectStore.sidebarCollapsed.value }"
        @click="projectStore.sidebarCollapsed.value = true"
        aria-hidden="true"
      ></div>
      <div
        class="sidebar-backdrop issues-backdrop"
        :class="{ visible: projectStore.issuesDrawerOpen.value }"
        @click="projectStore.issuesDrawerOpen.value = false"
        aria-hidden="true"
      ></div>

      <!-- Left: Surah Project Tree (Only Active Recitations) -->
      <SurahSidebar @add-surah="alignmentModalRef?.open()" @export="exportModalRef?.open()" />

      <!-- Center: Timeline & Mushaf View (Timeline always at full useful height) -->
      <main class="center-stage">
        <!-- Interactive Multi-Res Waveform with Draggable Handles -->
        <div class="timeline-pane-wrapper">
          <WaveformEditor @word-context-menu="handleWordContextMenu" />
        </div>

        <!-- Synchronized Medina Mushaf View with Precision Word Tracking -->
        <div class="mushaf-pane-wrapper">
          <MushafView @word-context-menu="handleWordContextMenu" />
        </div>
      </main>

      <!-- Right: Automated Quality Check Panel (In-flow layout, does NOT cover segments) -->
      <IssuesDrawer />
    </div>

    <!-- Modals & Overlays -->
    <WordContextMenu 
      ref="contextMenuRef" 
      @open-edit-word="handleOpenEditWord" 
    />
    <EditWordModal ref="editWordModalRef" />
    <ExportModal ref="exportModalRef" />
    <AlignmentModal ref="alignmentModalRef" />
    <!-- Desktop-only overlays (unmounted on mobile browser) -->
    <template v-if="isTauri">
      <UpdateModal ref="updateModalRef" />
      <CommandPalette 
        @open-export-modal="exportModalRef?.open()" 
        @open-alignment-modal="alignmentModalRef?.open()" 
        @open-update-modal="updateModalRef?.open('app_update')" 
      />
      <HotkeyCheatSheet />
    </template>
  </div>
</template>
<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue';
import { isTauriEnvironment } from './services/api';

const isTauri = isTauriEnvironment();

function handleGlobalKeydown(e: KeyboardEvent) {
  if (!isTauri) return;
  // Ctrl+B: Toggle Recitations Sidebar
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'b') {
    const target = e.target as HTMLElement | null;
    if (target && (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable)) return;
    e.preventDefault();
    projectStore.sidebarCollapsed.value = !projectStore.sidebarCollapsed.value;
  }
}
import { projectStore } from './services/projectStore';
import { versionService } from './services/VersionService';
import TopNavbar from './components/TopNavbar.vue';
import ProjectsHub from './components/ProjectsHub.vue';
import SurahSidebar from './components/SurahSidebar.vue';
import WaveformEditor from './components/WaveformEditor.vue';
import MushafView from './components/MushafView.vue';
import IssuesDrawer from './components/IssuesDrawer.vue';
import WordContextMenu from './components/WordContextMenu.vue';
import EditWordModal from './components/EditWordModal.vue';
import ExportModal from './components/ExportModal.vue';
import AlignmentModal from './components/AlignmentModal.vue';
import UpdateModal from './components/UpdateModal.vue';
import CommandPalette from './components/CommandPalette.vue';
import HotkeyCheatSheet from './components/HotkeyCheatSheet.vue';
import type { AlignedWord } from './types/aligner';

const contextMenuRef = ref<InstanceType<typeof WordContextMenu> | null>(null);
const editWordModalRef = ref<InstanceType<typeof EditWordModal> | null>(null);
const exportModalRef = ref<InstanceType<typeof ExportModal> | null>(null);
const alignmentModalRef = ref<InstanceType<typeof AlignmentModal> | null>(null);
const updateModalRef = ref<InstanceType<typeof UpdateModal> | null>(null);

onMounted(async () => {
  projectStore.currentTab.value = 'projects';

  // Small screens: start with the sidebar closed (it becomes a drawer)
  try {
    if (window.innerWidth <= 760) projectStore.sidebarCollapsed.value = true;
  } catch { /* no window */ }

  if (isTauri) {
    try {
      const { invoke } = await import('@tauri-apps/api/core');
      const isInstalled = await invoke<boolean>('is_engine_installed');
      if (!isInstalled) {
        updateModalRef.value?.open('app_init');
      } else {
        versionService.init();
      }
    } catch {
      versionService.init();
    }
    window.addEventListener('keydown', handleGlobalKeydown);

    const openEngineSetup = () => updateModalRef.value?.open('app_init');
    window.addEventListener('quran-open-setup', openEngineSetup);
    (window as any).__quranRemoveEngineSetup = () => window.removeEventListener('quran-open-setup', openEngineSetup);
  }
});

onUnmounted(() => {
  if (isTauri) {
    try { (window as any).__quranRemoveEngineSetup?.(); } catch { /* noop */ }
    window.removeEventListener('keydown', handleGlobalKeydown);
  }
});

function handleWordContextMenu(e: MouseEvent | TouchEvent, word: AlignedWord) {
  contextMenuRef.value?.open(e, word);
}

function handleOpenEditWord(word: AlignedWord) {
  editWordModalRef.value?.open(word);
}
</script>

<style scoped>
.app-layout {
  display: flex;
  flex-direction: column;
  height: 100vh;
  height: 100dvh;
  width: 100vw;
  padding-bottom: env(safe-area-inset-bottom, 0px);
  overflow: hidden;
  background: var(--bg-base);
}

.workspace-body {
  display: flex;
  flex: 1;
  min-height: 0;
  position: relative;
  overflow: hidden;
}

.center-stage {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  position: relative;
}

/* Master Timeline Pane — tightly fitted to tracks, zero empty space */
.timeline-pane-wrapper {
  width: 100%;
  overflow: hidden;
  position: relative;
  flex-shrink: 0;
  height: auto;
  display: flex;
  flex-direction: column;
}

/* Sacred Mushaf Viewer Pane */
.mushaf-pane-wrapper {
  flex: 1;
  min-height: 0;
  width: 100%;
  overflow: hidden;
  position: relative;
  display: flex;
  flex-direction: column;
}

/* Mobile drawer backdrop (hidden on desktop) */
.sidebar-backdrop {
  display: none;
}

@media (max-width: 760px) {
  .workspace-body {
    position: relative;
  }

  /* Sidebar becomes an overlay drawer */
  .workspace-body > :deep(aside.surah-sidebar:not(.collapsed)) {
    position: absolute;
    top: 0;
    left: 0;
    bottom: 0;
    z-index: 60;
    width: min(80vw, 320px) !important;
    box-shadow: var(--shadow-e4);
    border-right: 1px solid var(--border-medium);
  }

  .sidebar-backdrop.visible {
    display: block;
    position: absolute;
    inset: 0;
    z-index: 55;
    background: rgba(0, 0, 0, 0.45);
  }

  /* Cap the timeline pane so the mushaf stays visible */
  .timeline-pane-wrapper {
    height: auto;
    max-height: 42vh !important;
    min-height: 180px;
  }
}
</style>
