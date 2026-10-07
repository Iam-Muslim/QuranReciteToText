<template>
  <div class="app-layout">
    <!-- Top Global Navigation Bar -->
    <TopNavbar 
      @open-export-modal="exportModalRef?.open()" 
      @open-alignment-modal="alignmentModalRef?.open()" 
      @open-update-modal="updateModalRef?.open()" 
    />

    <!-- First Tab: Projects Hub (Visual Studio / Editor Start Hub) -->
    <ProjectsHub v-show="projectStore.currentTab.value === 'projects'" />

    <!-- Second Tab: Main Studio Workspace (Cached in Memory for 0% CPU & Disk Spikes) -->
    <div v-show="projectStore.currentTab.value === 'studio'" class="workspace-body">
      <!-- Left: Surah Project Tree (Only Active Recitations) -->
      <SurahSidebar @add-surah="alignmentModalRef?.open()" />

      <!-- Center: Timeline & Mushaf View -->
      <main class="center-stage">
        <!-- Interactive Multi-Res Waveform with Draggable Handles -->
        <WaveformEditor @word-context-menu="handleWordContextMenu" />

        <!-- Synchronized Medina Mushaf View with Precision Word Tracking -->
        <MushafView @word-context-menu="handleWordContextMenu" />
      </main>

      <!-- Right: Automated Confidence Auditor Drawer -->
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
    <UpdateModal ref="updateModalRef" />
  </div>
</template>
<script setup lang="ts">
import { ref, onMounted } from 'vue';
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
import type { AlignedWord } from './types/aligner';

const contextMenuRef = ref<InstanceType<typeof WordContextMenu> | null>(null);
const editWordModalRef = ref<InstanceType<typeof EditWordModal> | null>(null);
const exportModalRef = ref<InstanceType<typeof ExportModal> | null>(null);
const alignmentModalRef = ref<InstanceType<typeof AlignmentModal> | null>(null);
const updateModalRef = ref<InstanceType<typeof UpdateModal> | null>(null);

onMounted(async () => {
  projectStore.currentTab.value = 'projects';

  const isTauri = typeof window !== 'undefined' && (('__TAURI__' in (window as any)) || ('__TAURI_INTERNALS__' in (window as any)));
  if (isTauri) {
    try {
      const { invoke } = await import('@tauri-apps/api/core');
      const status = await invoke<{ ready: boolean }>('get_engine_status');
      if (!status || !status.ready) {
        updateModalRef.value?.open('app_init');
      } else {
        versionService.init();
      }
    } catch {
      versionService.init();
    }
  } else {
    versionService.init();
  }
});

function handleWordContextMenu(e: MouseEvent, word: AlignedWord) {
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
  width: 100vw;
  overflow: hidden;
  background-color: var(--bg-base);
}

.workspace-body {
  display: flex;
  flex: 1;
  height: calc(100vh - var(--header-height));
  position: relative;
  overflow: hidden;
}

.center-stage {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  position: relative;
}
</style>
