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

        <!-- Refresh Button -->
        <button 
          class="btn-icon" 
          @click="fetchProjects" 
          title="Refresh projects list"
        >
          <RefreshCw :size="13" :class="{ 'spin': isFetching }" />
        </button>
      </div>
    </header>

    <!-- Welcome -->
    <div class="hub-hero-banner">
      <div v-if="loadError" class="error-banner anim-rise">
        <span>{{ loadError }}</span>
        <button class="error-dismiss" @click="loadError = ''">✕</button>
      </div>

      <h1 class="hero-title arabic-quran-text" dir="rtl">وَمَا أَسْأَلُكُمْ عَلَيْهِ مِنْ أَجْرٍ ۖ إِنْ أَجْرِيَ إِلَّا عَلَىٰ رَبِّ الْعَالَمِينَ</h1>
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
              <span class="meta-tag surah-count-pill" :title="`${p.surahs_count || 1} Surah(s)`">
                <BookOpen :size="11" />
                <span>{{ p.surahs_count || 1 }} {{ (p.surahs_count || 1) === 1 ? 'Surah' : 'Surahs' }}</span>
              </span>
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
            <button class="btn-card-action" @click.stop="exportProject(p)" title="Download .qproj">
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

    <!-- Clean, Minimalist Create & Import Modal -->
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

        <!-- Seamless, Well-Aligned Import Options (QuranCaption pattern) -->
        <div class="modal-card-divider">
          <span>OR OPEN AN EXISTING PROJECT</span>
        </div>

        <div class="modal-import-grid">
          <button type="button" class="btn-import-card" @click="triggerFileInput(); showNewModal = false">
            <FolderOpen :size="16" class="import-icon" />
            <div class="import-info">
              <span class="import-title">Import .qproj File</span>
              <span class="import-sub">Load a saved recitation alignment project archive</span>
            </div>
          </button>

          <button v-if="isTauriEnv" type="button" class="btn-import-card" @click="revealProjectsDirectory(); showNewModal = false">
            <Folder :size="16" class="import-icon" />
            <div class="import-info">
              <span class="import-title">Open Projects Folder</span>
              <span class="import-sub">Reveal projects directory in Explorer</span>
            </div>
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted, computed, watch } from 'vue';
import { projectStore } from '../services/projectStore';
import { listProjects, loadProject, revealInExplorer, isTauriEnvironment } from '../services/api';
import { vaultList, vaultLoad } from '../services/projectVault';
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
  BookOpen
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
});

onUnmounted(() => {
  window.removeEventListener('keydown', handleGlobalKey);
});

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
  input.value = '';
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
    let data: any = null;
    if (isTauriEnvironment()) {
      try {
        data = await loadProject(fname);
      } catch {
        data = null;
      }
    }
    if (!data) {
      const vaultData = await vaultLoad(fname);
      data = vaultData?.project;
    }
    if (!data && projectStore.project && (projectStore.project.file_name === fname || projectStore.project.project_name === p.project_name)) {
      data = projectStore.buildPersistentSnapshot();
    }
    if (!data) {
      loadError.value = `Unable to export project "${p.project_name}".`;
      setTimeout(() => { loadError.value = ''; }, 3000);
      return;
    }
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = fname.endsWith('.qproj') ? fname : `${fname}.qproj`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  } catch (err: any) {
    console.error('Failed to export:', err);
    loadError.value = `Export failed: ${err?.message || err}`;
    setTimeout(() => { loadError.value = ''; }, 3000);
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

<style scoped src="./projects/projectsHub.css"></style>
