<template>
  <div class="projects-container">
    <input 
      type="file" 
      ref="fileInputRef" 
      accept=".qproj,.json" 
      style="display: none" 
      @change="handleFileInputChange" 
    />

    <!-- Modern Minimalist Toolbar -->
    <header class="hub-toolbar">
      <div class="toolbar-left">
        <!-- Quick Search -->
        <div class="search-wrap">
          <Search :size="13" class="search-icon" />
          <input 
            ref="searchInputRef"
            type="text" 
            v-model="searchQuery" 
            placeholder="Search projects…" 
            class="search-input"
            spellcheck="false"
          />
          <button v-if="searchQuery" class="clear-btn" @click="searchQuery = ''" title="Clear">✕</button>
          <span v-else class="kbd-hint search-kbd">/</span>
        </div>

        <!-- Filter Segmented Tabs -->
        <div class="status-tabs">
          <button 
            class="tab-btn" 
            :class="{ 'active': activeStatusFilter === 'all' }"
            @click="activeStatusFilter = 'all'"
          >
            All <span class="tab-badge">{{ projectsList.length }}</span>
          </button>
          <button 
            class="tab-btn" 
            :class="{ 'active': activeStatusFilter === 'verified' }"
            @click="activeStatusFilter = 'verified'"
          >
            <span class="dot dot-green"></span>
            Verified
          </button>
          <button 
            class="tab-btn" 
            :class="{ 'active': activeStatusFilter === 'needs_review' }"
            @click="activeStatusFilter = 'needs_review'"
          >
            <span class="dot dot-amber"></span>
            Review
          </button>
        </div>
      </div>

      <div class="toolbar-right">
        <!-- Sort Control -->
        <div class="sort-select-wrap">
          <SlidersHorizontal :size="12" class="sort-icon" />
          <select v-model="sortKey" class="sort-select">
            <option value="updated">Recent</option>
            <option value="review">Needs Review First</option>
            <option value="surahs">Surah Count</option>
            <option value="name">Name (A-Z)</option>
          </select>
        </div>

        <!-- Overflow Menu -->
        <div class="more-wrap" ref="moreWrapRef">
          <button 
            class="btn-icon" 
            :class="{ 'more-active': moreOpen }"
            @click.stop="moreOpen = !moreOpen" 
            title="More Options"
          >
            <MoreHorizontal :size="14" />
          </button>
          <div v-if="moreOpen" class="more-menu glass-float anim-scale">
            <button v-if="isTauriEnv" class="more-item" @click="revealProjectsDirectory(); moreOpen = false">
              <Folder :size="13" />
              <span>Open folder</span>
            </button>
            <button class="more-item" @click="triggerFileInput(); moreOpen = false">
              <FolderOpen :size="13" />
              <span>Import .qproj</span>
            </button>
            <button class="more-item" @click="fetchProjects(); moreOpen = false">
              <RefreshCw :size="13" :class="{ 'spin': isFetching }" />
              <span>Refresh list</span>
            </button>
          </div>
        </div>
      </div>
    </header>

    <!-- Welcome -->
    <div class="hub-hero-banner">
      <div v-if="loadError" class="error-banner anim-rise">
        <span>{{ loadError }}</span>
        <button class="error-dismiss" @click="loadError = ''">✕</button>
      </div>

      <h1 class="hero-title arabic-quran-text" dir="rtl">بِسْمِ اللَّهِ الرَّحْمَٰنِ الرَّحِيمِ</h1>
    </div>

    <!-- Main Workspace -->
    <main class="hub-main">
      <!-- Loading Shimmer -->
      <div v-if="isFetching && projectsList.length === 0" class="projects-grid">
        <div v-for="i in 6" :key="i" class="skeleton-card">
          <div class="skeleton-thumb shimmer"></div>
          <div class="skeleton-body">
            <div class="skeleton-line shimmer" style="width: 70%"></div>
            <div class="skeleton-line shimmer" style="width: 40%"></div>
          </div>
        </div>
      </div>

      <!-- Empty State -->
      <div v-else-if="filteredProjects.length === 0" class="empty-state anim-rise">
        <div class="empty-orb">
          <FolderKanban :size="28" class="empty-icon" />
        </div>
        <h3 class="empty-title">{{ searchQuery ? 'No matching projects' : 'No projects found' }}</h3>
        <p class="empty-desc">
          {{ searchQuery
            ? 'Try a different search query or filter.'
            : (isTauriEnv
              ? 'Create a recitation project or import an existing .qproj archive.'
              : 'Open your portable .qproj — timings and audio travel inside the file.') }}
        </p>
        <div class="empty-actions" v-if="!searchQuery">
          <button class="btn-primary" @click="showNewModal = true">
            <Plus :size="14" />
            <span>Create Project</span>
          </button>
          <button class="btn-secondary" @click="triggerFileInput">
            <FolderOpen :size="14" />
            <span>Import .qproj</span>
          </button>
        </div>
      </div>

      <!-- Project Card Grid -->
      <div v-else class="projects-grid stagger">
        <!-- New Project Tile -->
        <button class="create-tile" @click="showNewModal = true">
          <span class="create-orb">
            <Plus :size="18" />
          </span>
          <span class="create-label">New Project</span>
        </button>

        <!-- Project Cards -->
        <div 
          v-for="p in filteredProjects" 
          :key="p.file_name"
          class="project-card"
          @click="openProject(p)"
        >
          <!-- Card Header / Watermark -->
          <div class="card-thumbnail">
            <div class="watermark-layer">
              <span class="surah-watermark-ar" v-if="p.primary_surah?.surah_name_arabic" dir="rtl">
                {{ p.primary_surah.surah_name_arabic }}
              </span>
              <span class="surah-num-pill">Surah {{ getSurahWatermark(p) }}</span>
            </div>

            <!-- Review Toggle (same as the sidebar's ✓ button — one click marks reviewed) -->
            <button
              class="card-status-chip"
              :class="[getStatusClass(p.status), { 'is-done': isVerified(p) }]"
              @click.stop="toggleReview(p)"
              :title="isVerified(p) ? 'Reviewed — click to send back to review' : 'Click to mark reviewed'"
            >
              <CircleCheck :size="11" v-if="isVerified(p)" />
              <Circle :size="11" v-else />
              <span class="status-chip-label">{{ isVerified(p) ? 'Verified' : 'Review' }}</span>
            </button>

            <!-- Duration Badge -->
            <div class="thumbnail-duration" v-if="p.total_duration > 0">
              <span>{{ formatDuration(p.total_duration) }}</span>
            </div>
          </div>

          <!-- Card Info -->
          <div class="card-details">
            <h3 class="card-name" :title="p.project_name">{{ p.project_name }}</h3>
            
            <div class="card-meta-line">
              <span v-if="p.reciter" class="meta-tag">
                <span>{{ p.reciter }}</span>
              </span>
              <span v-if="p.total_ayahs > 0" class="meta-tag dim">
                <span>{{ p.total_ayahs }} ayahs</span>
              </span>
            </div>

            <div class="card-time-row">
              <span class="time-text">{{ formatDateRelative(p.updated_at) }}</span>
            </div>
          </div>

          <!-- Hover-Action Floating Dock -->
          <div class="card-actions-dock" @click.stop>
            <button class="btn-card-action" @click="duplicateProject(p)" title="Duplicate">
              <Copy :size="12" />
            </button>
            <button v-if="isTauriEnv" class="btn-card-action" @click="revealProjectInExplorer(p)" title="Open in Explorer">
              <Folder :size="12" />
            </button>
            <button class="btn-card-action" @click="exportProject(p)" title="Download .qproj">
              <Download :size="12" />
            </button>
            <button
              class="btn-card-action btn-delete"
              :class="{ 'armed-danger': confirmDeleteFile === p.file_name }"
              @click="requestDelete(p)"
              :title="confirmDeleteFile === p.file_name ? 'Click again to confirm delete' : 'Delete Project'"
            >
              <Trash2 :size="12" />
            </button>
          </div>
        </div>
      </div>
    </main>

    <!-- Clean, Minimalist Create Modal -->
    <div v-if="showNewModal" class="modal-backdrop" @click.self="showNewModal = false">
      <div class="modal-card glass-float anim-scale" @click.stop>
        <div class="modal-card-header">
          <h3 class="modal-heading">New Recitation Project</h3>
          <button class="btn-icon" @click="showNewModal = false" title="Close">✕</button>
        </div>

        <form @submit.prevent="handleCreateProject" class="modal-form">
          <div class="form-group">
            <label class="form-label">Project Name</label>
            <input 
              type="text" 
              v-model="newProjectName" 
              placeholder="e.g. Al-Fatihah · Mishary Rashid" 
              required
              autofocus
              class="form-input"
            />
          </div>

          <div class="form-group">
            <label class="form-label">Reciter (optional)</label>
            <input 
              type="text" 
              v-model="newReciterName" 
              placeholder="Reciter Name" 
              class="form-input"
            />
          </div>

          <div class="form-group">
            <label class="form-label">Recitation Tradition (Riwayah)</label>
            <select v-model="newRiwayah" class="form-input form-select">
              <option value="Hafs">حفص عن عاصم — Hafs 'an 'Asim</option>
              <option value="Warsh">ورش عن نافع — Warsh 'an Nafi'</option>
              <option value="Qaloon">قالون عن نافع — Qalun 'an Nafi'</option>
              <option value="Shouba">شعبة عن عاصم — Shu'bah 'an 'Asim</option>
              <option value="Doori">الدوري عن أبي عمرو — Al-Duri</option>
              <option value="Soosi">السوسي عن أبي عمرو — Al-Susi</option>
              <option value="Bazzi">البزي عن ابن كثير — Al-Bazzi</option>
              <option value="Qumbul">قنبل عن ابن كثير — Qumbul</option>
            </select>
          </div>

          <div class="modal-card-footer">
            <button type="button" class="btn-secondary" @click="showNewModal = false">Cancel</button>
            <button 
              type="submit" 
              class="btn-primary" 
              :disabled="isCreating || !newProjectName.trim()"
            >
              <span>{{ isCreating ? 'Creating…' : 'Create Project' }}</span>
            </button>
          </div>
        </form>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted, computed, watch } from 'vue';
import { projectStore } from '../services/projectStore';
import { listProjects, loadProject, revealInExplorer, isTauriEnvironment } from '../services/api';
import { vaultList } from '../services/projectVault';
import type { ProjectSummary } from '../types/aligner';
import { 
  FolderKanban,
  FolderOpen, 
  Folder, 
  Plus, 
  Copy,
  Download, 
  Trash2,
  Search,
  RefreshCw,
  Circle,
  CircleCheck,
  SlidersHorizontal,
  MoreHorizontal
} from 'lucide-vue-next';

const CACHE_KEY = 'quran_studio_projects_cache';

const searchQuery = ref('');
const activeStatusFilter = ref<'all' | 'verified' | 'needs_review'>('all');
const sortKey = ref<'updated' | 'review' | 'surahs' | 'name'>('updated');

const showNewModal = ref(false);
const newProjectName = ref('');
const newReciterName = ref('');
const newRiwayah = ref('Hafs');
const isCreating = ref(false);
const isFetching = ref(false);
const projectsList = ref<ProjectSummary[]>([]);
const fileInputRef = ref<HTMLInputElement | null>(null);
const searchInputRef = ref<HTMLInputElement | null>(null);

const moreOpen = ref(false);
const moreWrapRef = ref<HTMLElement | null>(null);

/** Desktop app vs shared-link/browser mode (vault storage, no folder reveal). */
const isTauriEnv = isTauriEnvironment();

const confirmDeleteFile = ref<string | null>(null);
const loadError = ref('');
let deleteArmTimer: ReturnType<typeof setTimeout> | null = null;

function requestDelete(p: ProjectSummary) {
  const fname = getProjectFileName(p) || '';
  if (!fname) return;
  (p as any).file_name = fname;
  if (confirmDeleteFile.value === fname) {
    deleteProject(p);
    return;
  }
  confirmDeleteFile.value = fname;
  if (deleteArmTimer) clearTimeout(deleteArmTimer);
  deleteArmTimer = setTimeout(() => { confirmDeleteFile.value = null; }, 3200);
}

watch(showNewModal, (open) => {
  if (!open) return;
  const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') showNewModal.value = false; };
  window.addEventListener('keydown', onKey);
  watch(showNewModal, () => window.removeEventListener('keydown', onKey), { once: true });
});

onMounted(() => {
  try {
    const cached = localStorage.getItem(CACHE_KEY);
    if (cached) {
      projectsList.value = JSON.parse(cached);
    }
  } catch {}

  fetchProjects();

  window.addEventListener('keydown', handleGlobalKey);
  window.addEventListener('click', handleOutsideClick);
});

onUnmounted(() => {
  window.removeEventListener('keydown', handleGlobalKey);
  window.removeEventListener('click', handleOutsideClick);
});

function handleOutsideClick(e: MouseEvent) {
  if (!moreOpen.value) return;
  const t = e.target as Node;
  if (moreWrapRef.value && !moreWrapRef.value.contains(t)) {
    moreOpen.value = false;
  }
}

watch(() => projectStore.currentTab.value, (newTab) => {
  if (newTab === 'projects') {
    fetchProjects();
  }
});

function handleGlobalKey(e: KeyboardEvent) {
  if (e.key !== '/' || projectStore.currentTab.value !== 'projects') return;
  const t = e.target as HTMLElement | null;
  if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.tagName === 'SELECT' || t.isContentEditable)) return;
  e.preventDefault();
  searchInputRef.value?.focus();
}

const filteredProjects = computed(() => {
  let list = projectsList.value;

  const q = searchQuery.value.trim().toLowerCase();
  if (q) {
    list = list.filter(p => {
      const matchName = p.project_name.toLowerCase().includes(q);
      const matchReciter = p.reciter && p.reciter.toLowerCase().includes(q);
      const matchRiwayah = p.riwayah && p.riwayah.toLowerCase().includes(q);
      const matchSurahAr = p.primary_surah?.surah_name_arabic && p.primary_surah.surah_name_arabic.includes(q);
      const matchSurahEn = p.primary_surah?.surah_name_english && p.primary_surah.surah_name_english.toLowerCase().includes(q);
      return matchName || matchReciter || matchRiwayah || matchSurahAr || matchSurahEn;
    });
  }

  if (activeStatusFilter.value !== 'all') {
    list = list.filter(p => {
      const st = String(p.status || '').toLowerCase();
      if (activeStatusFilter.value === 'verified') return st === 'verified' || st === 'completed' || st === 'done';
      if (activeStatusFilter.value === 'needs_review') return st === 'needs_review' || st === 'review' || st === 'aligned' || !p.status;
      return true;
    });
  }

  const byRecent = (a: ProjectSummary, b: ProjectSummary) =>
    (new Date(b.updated_at).getTime() || 0) - (new Date(a.updated_at).getTime() || 0);

  return [...list].sort((a, b) => {
    if (sortKey.value === 'name') {
      return a.project_name.localeCompare(b.project_name);
    } else if (sortKey.value === 'surahs') {
      return (b.surahs_count || 0) - (a.surahs_count || 0) || byRecent(a, b);
    } else if (sortKey.value === 'review') {
      // Unreviewed work first, most recently touched on top
      return (isVerified(a) ? 1 : 0) - (isVerified(b) ? 1 : 0) || byRecent(a, b);
    } else {
      return byRecent(a, b);
    }
  });
});

function getProjectFileName(p: any): string {
  return p?.file_name || p?._file || p?.file || (p?.project_name ? `${p.project_name}.qproj` : '');
}

async function fetchProjects(retries?: number | Event) {
  const retryCount = typeof retries === 'number' ? retries : 3;
  isFetching.value = true;
  try {
    // Browser/shared-link mode: projects (and audio) live in the local vault
    if (!isTauriEnvironment()) {
      const list = await vaultList();
      projectsList.value = list;
      try {
        localStorage.setItem(CACHE_KEY, JSON.stringify(list));
      } catch {}
      return;
    }
    const data = await listProjects();
    const rawList = data.projects || [];
    const list = rawList.map((p: any) => ({
      ...p,
      file_name: getProjectFileName(p),
    }));
    projectsList.value = list;
    try {
      localStorage.setItem(CACHE_KEY, JSON.stringify(list));
    } catch {}
  } catch (err) {
    if (retryCount > 0) {
      await new Promise(r => setTimeout(r, 600));
      return fetchProjects(retryCount - 1);
    }
    console.warn('Could not fetch projects:', err);
  } finally {
    isFetching.value = false;
  }
}

async function handleCreateProject() {
  if (!newProjectName.value.trim()) return;
  isCreating.value = true;
  try {
    const ok = await projectStore.createNewProject(
      newProjectName.value.trim(), 
      newReciterName.value.trim(),
      newRiwayah.value.trim()
    );
    if (ok) {
      showNewModal.value = false;
      newProjectName.value = '';
      newReciterName.value = '';
      await fetchProjects();
    }
  } finally {
    isCreating.value = false;
  }
}

function triggerFileInput() {
  fileInputRef.value?.click();
}

function handleFileInputChange(e: Event) {
  const input = e.target as HTMLInputElement;
  if (input.files && input.files[0]) {
    loadFile(input.files[0]);
  }
}

function loadFile(file: File) {
  const reader = new FileReader();
  reader.onload = async (event) => {
    try {
      const content = event.target?.result as string;
      const parsed = JSON.parse(content);
      if (parsed.surahs && parsed.project_name) {
        projectStore.loadProject(parsed);
        projectStore.currentTab.value = 'studio';
        // Shared-link mode: keep the opened project (and its embedded audio) in the vault
        if (!isTauriEnvironment()) {
          try {
            await projectStore.saveActiveProject();
          } catch { /* vault unavailable — project stays for this session */ }
        }
      } else if (parsed.surahs && parsed.surahs[0]?.ayahs) {
        projectStore.project.surahs = [];
        projectStore.loadAlignedSurah(parsed);
        projectStore.currentTab.value = 'studio';
      } else {
        loadError.value = 'Invalid project file format.';
        setTimeout(() => { loadError.value = ''; }, 4000);
      }
    } catch (err: any) {
      loadError.value = `Failed to load: ${err.message}`;
      setTimeout(() => { loadError.value = ''; }, 4000);
    }
  };
  reader.readAsText(file);
}

async function openProject(p: ProjectSummary) {
  const fname = getProjectFileName(p);
  if (fname) {
    const ok = await projectStore.openProjectByFileName(fname);
    if (!ok) {
      loadError.value = `Unable to open "${p.project_name}".`;
      setTimeout(() => { loadError.value = ''; }, 4000);
    }
  }
}

/** Mirrors the sidebar's ✓ toggle: one click marks the whole project reviewed. */
function isVerified(p: ProjectSummary): boolean {
  const st = String(p.status || '').toLowerCase();
  return st === 'verified' || st === 'completed' || st === 'done';
}

async function toggleReview(p: ProjectSummary) {
  const fname = getProjectFileName(p);
  if (!fname) return;
  const nowVerified = await projectStore.toggleProjectReview(fname);
  p.status = nowVerified ? 'verified' : 'needs_review';
  try {
    localStorage.setItem(CACHE_KEY, JSON.stringify(projectsList.value));
  } catch {}
}

async function deleteProject(p: ProjectSummary) {
  const fname = getProjectFileName(p);
  if (!fname) return;
  const ok = await projectStore.deleteProjectFile(fname);
  confirmDeleteFile.value = null;
  if (ok) {
    projectsList.value = projectsList.value.filter(item => getProjectFileName(item) !== fname);
    try {
      localStorage.setItem(CACHE_KEY, JSON.stringify(projectsList.value));
    } catch {}
    await fetchProjects();
  }
}

async function duplicateProject(p: ProjectSummary) {
  const fname = getProjectFileName(p);
  if (!fname) return;
  const ok = await projectStore.duplicateProjectFile(fname);
  if (ok) {
    await fetchProjects();
  }
}

async function exportProject(p: ProjectSummary) {
  const fname = getProjectFileName(p);
  if (!fname) return;
  try {
    const data = await loadProject(fname);
    if (!data) return;
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = fname.endsWith('.qproj') ? fname : `${fname}.qproj`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  } catch (err) {
    console.error('Failed to export:', err);
  }
}

async function revealProjectInExplorer(p: ProjectSummary) {
  const fname = getProjectFileName(p);
  try {
    await revealInExplorer(fname || p.project_name);
  } catch (err) {
    console.error('Failed to reveal:', err);
  }
}

async function revealProjectsDirectory() {
  try {
    await revealInExplorer('projects');
  } catch (err) {
    console.error('Failed to reveal folder:', err);
  }
}

function getStatusClass(status?: string): string {
  const st = (status || '').toLowerCase();
  if (st === 'verified' || st === 'completed' || st === 'done') return 'status-verified';
  return 'status-review';
}

function getSurahWatermark(p: ProjectSummary): string {
  if (p.primary_surah?.surah_number) {
    return String(p.primary_surah.surah_number).padStart(3, '0');
  }
  return '001';
}

function formatDuration(secs: number): string {
  if (isNaN(secs) || secs <= 0) return '—';
  const mins = Math.floor(secs / 60);
  const remainingSecs = Math.floor(secs % 60);
  if (mins >= 60) {
    const hrs = Math.floor(mins / 60);
    return `${hrs}h ${mins % 60}m`;
  }
  return `${mins}:${remainingSecs.toString().padStart(2, '0')}`;
}

function formatDateRelative(dateStr: string): string {
  try {
    const d = new Date(dateStr);
    const now = new Date();
    const diffSec = Math.floor((now.getTime() - d.getTime()) / 1000);
    if (diffSec < 60) return 'Just now';
    if (diffSec < 3600) return `${Math.floor(diffSec / 60)}m ago`;
    if (diffSec < 86400) return `${Math.floor(diffSec / 3600)}h ago`;
    return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
  } catch {
    return dateStr;
  }
}
</script>

<style scoped>
.projects-container {
  flex: 1;
  display: flex;
  flex-direction: column;
  height: calc(100vh - var(--header-height));
  color: var(--text-main);
  overflow-y: auto;
  overflow-x: hidden;
  background: var(--bg-base);
}

/* Minimalist Toolbar */
.hub-toolbar {
  position: sticky;
  top: 0;
  z-index: 20;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 24px;
  background: var(--glass-bg);
  backdrop-filter: blur(14px);
  -webkit-backdrop-filter: blur(14px);
  border-bottom: 1px solid var(--border-subtle);
}

.toolbar-left,
.toolbar-right {
  display: flex;
  align-items: center;
  gap: 8px;
}

.search-wrap {
  position: relative;
  display: flex;
  align-items: center;
}
.search-icon {
  position: absolute;
  left: 9px;
  color: var(--text-muted);
  pointer-events: none;
}
.search-input {
  background: var(--bg-input);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-sm);
  padding: 5px 28px 5px 28px;
  font-size: var(--text-xs);
  color: var(--text-main);
  width: 190px;
  transition: all var(--dur-fast) var(--ease-out);
}
.search-input:focus {
  width: 240px;
  border-color: var(--accent-border);
  box-shadow: 0 0 0 2px var(--accent-subtle);
  outline: none;
}
.search-kbd {
  position: absolute;
  right: 8px;
  pointer-events: none;
}
.clear-btn {
  position: absolute;
  right: 7px;
  background: none;
  border: none;
  color: var(--text-muted);
  font-size: 10px;
  cursor: pointer;
}

/* Status Filter Tabs */
.status-tabs {
  display: flex;
  align-items: center;
  background: var(--bg-input);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-sm);
  padding: 2px;
}
.status-tabs .tab-btn {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  background: transparent;
  border: none;
  padding: 3px 9px;
  font-size: 11px;
  font-weight: 500;
  color: var(--text-muted);
  border-radius: var(--radius-xs);
  cursor: pointer;
  transition: all var(--dur-fast) var(--ease-out);
}
.status-tabs .tab-btn:hover {
  color: var(--text-main);
}
.status-tabs .tab-btn.active {
  background: var(--bg-surface-elevated);
  color: var(--text-main);
  font-weight: 600;
  box-shadow: var(--shadow-e1);
}
.tab-badge {
  font-size: 10px;
  color: var(--text-muted);
}
.dot {
  width: 5px;
  height: 5px;
  border-radius: 50%;
}
.dot-green { background: var(--emerald-primary); }
.dot-amber { background: var(--amber-primary); }
.dot-gray { background: var(--text-muted); }

.sort-select-wrap {
  display: flex;
  align-items: center;
  position: relative;
}
.sort-icon {
  position: absolute;
  left: 8px;
  color: var(--text-muted);
  pointer-events: none;
}
.sort-select {
  background: var(--bg-input);
  border: 1px solid var(--border-subtle);
  color: var(--text-muted);
  font-size: 11px;
  padding: 5px 10px 5px 24px;
  border-radius: var(--radius-sm);
  cursor: pointer;
  outline: none;
}
.sort-select:hover {
  color: var(--text-main);
  border-color: var(--border-medium);
}

.more-wrap {
  position: relative;
}
.more-menu {
  position: absolute;
  top: 100%;
  right: 0;
  margin-top: 6px;
  background: var(--bg-surface-elevated);
  border: 1px solid var(--border-medium);
  border-radius: var(--radius-sm);
  padding: 4px;
  min-width: 140px;
  z-index: 100;
}
.more-item {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 7px;
  padding: 6px 10px;
  font-size: var(--text-xs);
  color: var(--text-main);
  background: none;
  border: none;
  border-radius: var(--radius-xs);
  cursor: pointer;
  text-align: left;
}
.more-item:hover {
  background: var(--bg-surface-hover);
}

/* Welcome */
.hub-hero-banner {
  padding: 30px 32px 22px;
  background: var(--bg-surface);
  border-bottom: 1px solid var(--border-subtle);
  position: relative;
}

@media (max-width: 700px) {
  .hub-toolbar {
    flex-wrap: wrap;
    gap: 8px;
    padding: 8px 12px;
  }

  .status-tabs {
    overflow-x: auto;
    scrollbar-width: none;
  }
  .status-tabs::-webkit-scrollbar {
    display: none;
  }

  .hub-hero-banner {
    padding: 20px 14px 14px;
  }

  .hub-main {
    padding: 14px 10px 20px;
  }

  .hero-title {
    font-size: 1.4rem;
  }
}

.hero-title {
  font-family: var(--font-arabic);
  font-size: 2rem;
  line-height: 1.4;
  color: var(--gold-primary);
  margin: 0;
  text-align: center;
  font-weight: 400;
}

/* Workspace Grid */
.hub-main {
  flex: 1;
  padding: 24px;
}

.projects-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(min(280px, 100%), 1fr));
  gap: 16px;
}

/* Create Tile */
.create-tile {
  background: var(--bg-surface);
  border: 1px dashed var(--border-medium);
  border-radius: var(--radius-md);
  padding: 24px 18px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  cursor: pointer;
  transition: border-color var(--dur-fast) var(--ease-out), background var(--dur-fast) var(--ease-out);
  min-height: 190px;
  position: relative;
  overflow: hidden;
}
.create-tile:hover {
  border-color: var(--accent-primary);
  background: var(--bg-surface-hover);
}
.create-orb {
  width: 36px;
  height: 36px;
  border-radius: var(--radius-md);
  background: var(--bg-surface-elevated);
  border: 1px solid var(--border-medium);
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--text-secondary);
  margin-bottom: 4px;
  transition: color var(--dur-fast) var(--ease-out), background var(--dur-fast) var(--ease-out);
}
.create-tile:hover .create-orb {
  color: var(--text-main);
}
.create-label {
  font-size: var(--text-sm);
  font-weight: 500;
  color: var(--text-main);
}

/* Project Card */
.project-card {
  background: var(--bg-surface);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-md);
  overflow: hidden;
  position: relative;
  cursor: pointer;
  display: flex;
  flex-direction: column;
  transition: border-color var(--dur-fast) var(--ease-out);
}
.project-card:hover {
  border-color: var(--border-medium);
}

.card-thumbnail {
  height: 84px;
  background: var(--bg-surface-elevated);
  border-bottom: 1px solid var(--border-subtle);
  position: relative;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 14px;
  overflow: hidden;
}

/* Waveform graphic (removed design) */

.watermark-layer {
  display: flex;
  align-items: center;
  gap: 8px;
  position: relative;
  z-index: 2;
}
.surah-watermark-ar {
  font-family: var(--font-arabic);
  font-size: 21px;
  color: var(--text-main);
  opacity: 0.88;
}
.surah-num-pill {
  font-family: var(--font-mono);
  font-size: 10px;
  font-weight: 600;
  color: var(--text-muted);
  background: var(--bg-base);
  padding: 2px 7px;
  border-radius: var(--radius-pill);
  border: 1px solid var(--border-subtle);
}

/* Review Toggle Chip — clickable, like the sidebar's ✓ button */
.card-status-chip {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 2px 8px;
  border-radius: var(--radius-pill);
  font-size: 10px;
  font-weight: 600;
  position: relative;
  z-index: 2;
  border: 1px solid transparent;
  background: none;
  cursor: pointer;
  transition: opacity 0.15s ease, transform 0.1s ease;
}
.card-status-chip:hover {
  opacity: 0.85;
}
.card-status-chip:active {
  transform: scale(0.94);
}
.card-status-chip.status-verified {
  background: var(--emerald-bg);
  color: var(--emerald-primary);
  border-color: var(--emerald-border);
}
.card-status-chip.status-review {
  background: var(--amber-bg);
  color: var(--amber-primary);
  border-color: var(--amber-border);
}

.thumbnail-duration {
  position: absolute;
  right: 12px;
  bottom: 8px;
  font-family: var(--font-mono);
  font-size: 10px;
  color: var(--text-muted);
  display: inline-flex;
  align-items: center;
  gap: 4px;
  background: var(--glass-bg);
  backdrop-filter: blur(6px);
  padding: 1px 5px;
  border-radius: 4px;
  z-index: 2;
}

.card-details {
  padding: 12px 14px;
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.card-name {
  margin: 0;
  font-size: 13.5px;
  font-weight: 600;
  color: var(--text-main);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.card-meta-line {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 5px;
}
.meta-tag {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  background: var(--bg-input);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-xs);
  padding: 2px 6px;
  font-size: 10.5px;
  color: var(--text-muted);
  transition: all var(--dur-fast) var(--ease-out);
}
.meta-tag:hover {
  color: var(--text-main);
  border-color: var(--border-medium);
}
.card-time-row {
  margin-top: auto;
  padding-top: 8px;
  font-size: 10.5px;
  color: var(--text-dim);
  border-top: 1px solid var(--border-subtle);
}

/* Floating Actions Dock on Card Hover */
.card-actions-dock {
  position: absolute;
  top: 8px;
  right: 8px;
  display: flex;
  align-items: center;
  gap: 3px;
  background: var(--bg-surface-elevated);
  border: 1px solid var(--border-medium);
  border-radius: var(--radius-sm);
  padding: 2px;
  opacity: 0;
  transform: translateY(-4px);
  transition: all var(--dur-fast) var(--ease-out);
  box-shadow: var(--shadow-e1);
}
.project-card:hover .card-actions-dock {
  opacity: 1;
  transform: translateY(0);
}
.btn-card-action {
  background: transparent;
  border: none;
  color: var(--text-muted);
  padding: 4px;
  border-radius: var(--radius-xs);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all var(--dur-fast) var(--ease-out);
}
.btn-card-action:hover {
  background: var(--bg-surface-hover);
  color: var(--text-main);
}
.btn-card-action.btn-delete:hover,
.btn-card-action.armed-danger {
  color: var(--ruby-primary) !important;
  background: rgba(239, 68, 68, 0.12) !important;
}

/* Modal Card */
.modal-card {
  width: min(420px, calc(100vw - 32px));
  background: var(--bg-surface-elevated);
  border: 1px solid var(--border-medium);
  border-radius: var(--radius-lg);
  padding: 20px;
  box-shadow: var(--shadow-e4);
}
.modal-card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16px;
}
.modal-heading {
  margin: 0;
  font-size: var(--text-md);
  font-weight: 600;
}
.modal-form {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.form-group {
  display: flex;
  flex-direction: column;
  gap: 5px;
}
.form-label {
  font-size: 11px;
  font-weight: 500;
  color: var(--text-muted);
}
.form-input {
  background: var(--bg-input);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-sm);
  padding: 8px 10px;
  font-size: var(--text-xs);
  color: var(--text-main);
  outline: none;
}
.form-input:focus {
  border-color: var(--accent-border);
  box-shadow: 0 0 0 2px var(--accent-subtle);
}
.form-select {
  cursor: pointer;
}
.modal-card-footer {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 10px;
}

/* Empty State */
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 60px 20px;
  text-align: center;
}
.empty-orb {
  width: 50px;
  height: 50px;
  border-radius: 50%;
  background: var(--bg-surface-elevated);
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--text-muted);
  margin-bottom: 12px;
}
.empty-title {
  margin: 0 0 4px 0;
  font-size: var(--text-md);
  font-weight: 600;
}
.empty-desc {
  margin: 0 0 16px 0;
  font-size: var(--text-xs);
  color: var(--text-muted);
  max-width: 320px;
}
.empty-actions {
  display: flex;
  gap: 8px;
}

/* Skeleton Loading */
.skeleton-card {
  background: var(--bg-surface);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-md);
  height: 160px;
  overflow: hidden;
}
.skeleton-thumb {
  height: 80px;
  background: var(--bg-surface-elevated);
}
.skeleton-body {
  padding: 12px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.skeleton-line {
  height: 12px;
  border-radius: var(--radius-xs);
  background: var(--bg-surface-hover);
}
.shimmer {
  animation: fade-in 1.2s var(--ease-in-out) infinite alternate;
}
</style>
