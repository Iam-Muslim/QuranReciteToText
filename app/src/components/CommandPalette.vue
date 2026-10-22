<template>
  <div v-if="visible" class="palette-backdrop" @click.self="close">
    <div class="command-palette glass-float anim-scale" role="dialog" aria-label="Command Palette">
      <!-- Search Input -->
      <div class="palette-search-row">
        <Search :size="15" class="palette-search-icon" />
        <input
          ref="inputRef"
          v-model="query"
          type="text"
          class="palette-input"
          placeholder="Type a command or project name..."
          @keydown="onInputKeydown"
          spellcheck="false"
        />
        <span class="kbd-hint">Esc</span>
      </div>

      <!-- Results -->
      <div class="palette-results" ref="resultsRef">
        <div
          v-for="(cmd, idx) in filteredCommands"
          :key="cmd.id"
          class="palette-item"
          :class="{ 'is-active': idx === activeIndex }"
          role="option"
          :aria-selected="idx === activeIndex"
          @mouseenter="activeIndex = idx"
          @click="execute(cmd)"
        >
          <component :is="cmd.icon" :size="15" class="palette-item-icon" />
          <span class="palette-item-label">{{ cmd.label }}</span>
          <span v-if="cmd.section" class="palette-item-section">{{ cmd.section }}</span>
          <CornerDownLeft v-if="idx === activeIndex" :size="12" class="palette-enter-icon" />
        </div>

        <div v-if="filteredCommands.length === 0" class="palette-empty">
          <span>No matching commands</span>
        </div>
      </div>

      <!-- Footer Hints -->
      <div class="palette-footer">
        <span class="palette-hint"><span class="kbd-hint">↑</span><span class="kbd-hint">↓</span> navigate</span>
        <span class="palette-hint"><span class="kbd-hint">↵</span> run</span>
        <span class="palette-hint"><span class="kbd-hint">Esc</span> close</span>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, nextTick, onMounted, onUnmounted } from 'vue';
import { projectStore } from '../services/projectStore';
import { isTauriEnvironment, revealInExplorer } from '../services/api';
import {
  Search,
  CornerDownLeft,
  FolderKanban,
  Sliders,
  Save,
  Download,
  AlertCircle,
  Folder,
  CheckCheck,
  RefreshCw,
  FileAudio,
  PanelLeft,
} from 'lucide-vue-next';

const emit = defineEmits<{
  (e: 'open-export-modal'): void;
  (e: 'open-alignment-modal'): void;
  (e: 'open-update-modal'): void;
}>();

interface Command {
  id: string;
  label: string;
  section: string;
  icon: any;
  keywords: string;
  action: () => void | Promise<void>;
  /** Desktop-only (Tauri) — hidden when running as a shared web link. */
  desktop?: boolean;
}

const visible = ref(false);
const query = ref('');
const activeIndex = ref(0);
const inputRef = ref<HTMLInputElement | null>(null);
const resultsRef = ref<HTMLElement | null>(null);

interface ProjectCacheEntry {
  file_name?: string;
  project_name: string;
  reciter?: string;
}

function readProjectCache(): ProjectCacheEntry[] {
  try {
    const cached = localStorage.getItem('quran_studio_projects_cache');
    return cached ? JSON.parse(cached) : [];
  } catch {
    return [];
  }
}

function buildCommands(): Command[] {
  const cmds: Command[] = [
    {
      id: 'go-projects',
      label: 'Go to Projects',
      section: 'Navigate',
      icon: FolderKanban,
      keywords: 'projects hub home dashboard',
      action: () => { projectStore.currentTab.value = 'projects'; },
    },
    {
      id: 'go-studio',
      label: 'Go to Studio',
      section: 'Navigate',
      icon: Sliders,
      keywords: 'studio editor workspace waveform mushaf',
      action: () => { projectStore.currentTab.value = 'studio'; },
    },
    {
      id: 'toggle-sidebar',
      label: 'Toggle Recitations Sidebar',
      section: 'View',
      icon: PanelLeft,
      keywords: 'sidebar recitations panel toggle collapse ctrl+b',
      action: () => { projectStore.sidebarCollapsed.value = !projectStore.sidebarCollapsed.value; },
    },
    {
      id: 'save',
      label: 'Save Project Now',
      section: 'Project',
      icon: Save,
      keywords: 'save commit write disk ctrl+s',
      action: () => { projectStore.saveActiveProject(); },
    },
    {
      id: 'export',
      label: 'Export Subtitles & Data…',
      section: 'Project',
      icon: Download,
      keywords: 'export srt vtt ass json csv premiere qproj subtitles karaoke',
      action: () => { emit('open-export-modal'); },
    },
    {
      id: 'align',
      label: 'Align New Recitation…',
      section: 'Project',
      icon: FileAudio,
      keywords: 'align recitation audio transcribe pipeline new surah',
      action: () => { emit('open-alignment-modal'); },
    },
    {
      id: 'auditor',
      label: 'Toggle Confidence Auditor',
      section: 'Review',
      icon: AlertCircle,
      keywords: 'auditor issues drawer confidence panel toggle',
      action: () => { projectStore.issuesDrawerOpen.value = !projectStore.issuesDrawerOpen.value; },
    },
    {
      id: 'next-issue',
      label: 'Jump to Next Issue',
      section: 'Review',
      icon: CheckCheck,
      keywords: 'next issue jump review tab verify problem',
      action: () => { projectStore.jumpToNextIssue(); },
    },
    {
      id: 'folder',
      label: 'Open Projects Folder',
      section: 'Navigate',
      icon: Folder,
      keywords: 'folder explorer files disk reveal projects directory',
      action: async () => { try { await revealInExplorer('projects'); } catch (e) { console.error(e); } },
      desktop: true,
    },
    {
      id: 'updates',
      label: 'Check for Updates…',
      section: 'App',
      icon: RefreshCw,
      keywords: 'update version upgrade check install',
      action: () => { emit('open-update-modal'); },
      desktop: true,
    },
  ].filter(c => !c.desktop || isTauriEnvironment());

  // Dynamic: open project by name (instant cache)
  for (const p of readProjectCache()) {
    const fname = p.file_name || p.project_name;
    if (!fname) continue;
    cmds.push({
      id: `open-${fname}`,
      label: `Open: ${p.project_name}${p.reciter ? ` — ${p.reciter}` : ''}`,
      section: 'Projects',
      icon: FolderKanban,
      keywords: `open project ${p.project_name} ${p.reciter || ''}`,
      action: async () => {
        await projectStore.openProjectByFileName(fname);
      },
    });
  }

  return cmds;
}

const filteredCommands = computed(() => {
  const cmds = buildCommands();
  const q = query.value.trim().toLowerCase();
  if (!q) return cmds;
  return cmds.filter(c =>
    c.label.toLowerCase().includes(q) ||
    c.section.toLowerCase().includes(q) ||
    c.keywords.includes(q)
  );
});

function open() {
  visible.value = true;
  query.value = '';
  activeIndex.value = 0;
  nextTick(() => inputRef.value?.focus());
}

function close() {
  visible.value = false;
}

function execute(cmd: Command) {
  close();
  // Let the palette unmount before modal opens (avoids backdrop overlap flash)
  setTimeout(() => { Promise.resolve(cmd.action()).catch(e => console.error(e)); }, 30);
}

function onInputKeydown(e: KeyboardEvent) {
  const list = filteredCommands.value;
  if (e.key === 'ArrowDown') {
    e.preventDefault();
    activeIndex.value = list.length ? (activeIndex.value + 1) % list.length : 0;
    scrollToActive();
  } else if (e.key === 'ArrowUp') {
    e.preventDefault();
    activeIndex.value = list.length ? (activeIndex.value - 1 + list.length) % list.length : 0;
    scrollToActive();
  } else if (e.key === 'Enter') {
    e.preventDefault();
    if (list[activeIndex.value]) execute(list[activeIndex.value]);
  } else if (e.key === 'Escape') {
    e.preventDefault();
    close();
  }
}

function scrollToActive() {
  nextTick(() => {
    const el = resultsRef.value?.querySelector('.palette-item.is-active');
    el?.scrollIntoView({ block: 'nearest' });
  });
}

function handleGlobalKeydown(e: KeyboardEvent) {
  if ((e.ctrlKey || e.metaKey) && (e.key === 'p' || e.key === 'k')) {
    e.preventDefault();
    if (visible.value) close();
    else open();
  }
}

onMounted(() => window.addEventListener('keydown', handleGlobalKeydown));
onUnmounted(() => window.removeEventListener('keydown', handleGlobalKeydown));

defineExpose({ open, close });
</script>

<style scoped>
.palette-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(5, 6, 10, 0.55);
  backdrop-filter: blur(6px);
  -webkit-backdrop-filter: blur(6px);
  display: flex;
  align-items: flex-start;
  justify-content: center;
  padding-top: 14vh;
  z-index: 2000;
  animation: fade-in var(--dur-fast) var(--ease-out) both;
}

.command-palette {
  width: min(560px, calc(100vw - 28px));
  max-width: 92vw;
  border-radius: var(--radius-lg);
  overflow: hidden;
  display: flex;
  flex-direction: column;
  animation: rise-in var(--dur-rise) var(--ease-spring) both;
}

.palette-search-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 14px;
  border-bottom: 1px solid var(--border-subtle);
}

.palette-search-icon {
  color: var(--text-muted);
  flex-shrink: 0;
}

.palette-input {
  flex: 1;
  background: transparent;
  border: none;
  outline: none;
  color: var(--text-main);
  font-size: 0.95rem;
  font-family: var(--font-ui);
}
.palette-input::placeholder { color: var(--text-dim); }

.palette-results {
  max-height: 380px;
  overflow-y: auto;
  padding: 6px;
}

.palette-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 12px;
  border-radius: var(--radius-sm);
  cursor: pointer;
  color: var(--text-secondary);
  transition: background var(--dur-fast) var(--ease-out),
              color var(--dur-fast) var(--ease-out);
}

.palette-item.is-active {
  background: var(--accent-subtle);
  color: var(--text-main);
}

.palette-item-icon {
  color: var(--text-muted);
  flex-shrink: 0;
}
.palette-item.is-active .palette-item-icon {
  color: var(--accent-hover);
}

.palette-item-label {
  flex: 1;
  font-size: var(--text-sm);
  font-weight: 500;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.palette-item-section {
  font-size: 0.68rem;
  color: var(--text-dim);
  background: var(--bg-surface-elevated);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-pill);
  padding: 1px 8px;
  flex-shrink: 0;
}

.palette-enter-icon {
  color: var(--accent-hover);
  flex-shrink: 0;
}

.palette-empty {
  padding: 28px 12px;
  text-align: center;
  color: var(--text-muted);
  font-size: var(--text-sm);
}

.palette-footer {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 8px 14px;
  border-top: 1px solid var(--border-subtle);
  background: var(--bg-surface);
}

.palette-hint {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 0.68rem;
  color: var(--text-muted);
}
</style>
