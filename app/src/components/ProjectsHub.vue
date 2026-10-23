<template>
  <div class="projects-container">
    <input 
      type="file" 
      ref="fileInputRef" 
      accept=".qproj,.json,application/json,*/*" 
      style="display: none" 
      @change="handleFileInputChange" 
    />

    <!-- 1. Sacred Ayah Banner on Top -->
    <div class="hub-hero-banner">
      <div v-if="loadError" class="error-banner anim-rise">
        <span>{{ loadError }}</span>
        <button class="error-dismiss" @click="loadError = ''">✕</button>
      </div>

      <div class="hero-inner">
        <div class="hero-calligraphy-frame">
          <h1 class="hero-title arabic-quran-text" dir="rtl">
            وما اسالكم عليه من اجر ان اجري الا على رب العالمين
          </h1>
        </div>
      </div>
    </div>

    <!-- 2. Modern Minimalist Toolbar UNDER the Ayah Banner -->
    <header class="hub-toolbar">
      <div class="toolbar-left">
        <!-- Quick Search -->
        <div class="search-wrap">
          <Search :size="13" class="search-icon" />
          <input 
            type="text" 
            v-model="searchQuery" 
            placeholder="Search projects…" 
            class="search-input"
            spellcheck="false"
          />
          <button v-if="searchQuery" class="clear-btn" @click="searchQuery = ''" title="Clear">✕</button>
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
          <select v-model="sortKey" class="sort-select" title="Sort Projects">
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

    <!-- Main Workspace -->
    <main class="hub-main">
      <!-- Loading Shimmer -->
      <div v-if="isFetching && projectsList.length === 0" class="projects-grid">
        <div v-for="i in 4" :key="i" class="skeleton-card">
          <div class="skeleton-thumb shimmer"></div>
          <div class="skeleton-body">
            <div class="skeleton-line shimmer" style="width: 70%"></div>
            <div class="skeleton-line shimmer" style="width: 40%"></div>
          </div>
        </div>
      </div>

      <!-- No search results state -->
      <div v-else-if="searchQuery && filteredProjects.length === 0" class="no-search-results anim-rise">
        <FolderKanban :size="28" class="empty-icon" />
        <h3 class="empty-title">No matching projects</h3>
        <p class="empty-desc">No project matching "{{ searchQuery }}".</p>
        <button class="btn-secondary" @click="searchQuery = ''">Clear Search</button>
      </div>

      <!-- Project Cards Grid -->
      <div v-else class="projects-grid stagger">
        <!-- The SAME Square New Project Tile -->
        <button class="create-tile" @click="showNewModal = true" title="Create New Recitation Project">
          <div class="create-orb">
            <Plus :size="22" />
          </div>
          <span class="create-label">New Project</span>
          <span class="create-sub">Start alignment workspace</span>
        </button>

        <!-- Modern Project Card -->
        <!-- Clean Modern Project Card -->
        <div 
          v-for="p in filteredProjects" 
          :key="p.file_name"
          class="project-card"
          @click="openProject(p)"
        >
          <!-- Top Row: Status Chip on Left + Quick Actions Dock on Right -->
          <div class="card-header-row">
            <button
              class="card-status-chip"
              :class="[getStatusClass(p.status), { 'is-done': isVerified(p) }]"
              @click.stop="toggleReview(p)"
              :title="isVerified(p) ? 'Reviewed — click to mark needs review' : 'Click to mark reviewed'"
            >
              <CircleCheck :size="11" v-if="isVerified(p)" />
              <Circle :size="11" v-else />
              <span class="status-chip-label">{{ isVerified(p) ? 'Verified' : 'Review' }}</span>
            </button>

            <!-- Quick Action Icons -->
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
                @click="requestDelete(p)"
                title="Delete Project"
              >
                <Trash2 :size="12" />
              </button>
            </div>
          </div>

          <!-- Card Body: Clear, Prominent Project Name -->
          <div class="card-body">
            <h3 class="card-name" :title="p.project_name">{{ p.project_name }}</h3>

            <div class="card-meta-line" v-if="p.surahs_count > 0 || p.reciter || (p.riwayah && p.riwayah !== 'Hafs')">
              <!-- Surah count ONLY if surahs_count > 0, NO Mushaf icon -->
              <span v-if="p.surahs_count > 0" class="meta-tag surah-count-pill">
                <span>{{ p.surahs_count }} {{ p.surahs_count === 1 ? 'Surah' : 'Surahs' }}</span>
              </span>

              <!-- Reciter tag if present -->
              <span v-if="p.reciter" class="meta-tag reciter-pill" :title="p.reciter">
                <Mic :size="10" />
                <span>{{ p.reciter }}</span>
              </span>

              <!-- Riwayah tag if customized -->
              <span v-if="p.riwayah && p.riwayah !== 'Hafs'" class="meta-tag riwayah-pill">
                <span>{{ p.riwayah }}</span>
              </span>
            </div>
          </div>

          <!-- Card Footer: Relative date & Open hint on hover -->
          <div class="card-footer-row">
            <span class="time-text">{{ formatDateRelative(p.updated_at) }}</span>
            <span class="open-hint">
              <span>Open</span>
              <ArrowRight :size="11" />
            </span>
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

    <!-- Approval / Delete Confirmation Dialog -->
    <div v-if="projectToDelete" class="modal-backdrop" @click.self="cancelDelete">
      <div class="modal-card modal-confirm glass-float anim-scale" @click.stop>
        <div class="confirm-content">
          <div class="confirm-icon-orb">
            <Trash2 :size="22" />
          </div>
          <div class="confirm-text">
            <h3 class="confirm-title">Delete Project?</h3>
            <p class="confirm-desc">
              Are you sure you want to delete <strong class="confirm-name">"{{ projectToDelete.project_name }}"</strong>?
            </p>
            <p class="confirm-sub">This action cannot be undone.</p>
          </div>
        </div>

        <div class="confirm-actions-row">
          <button type="button" class="btn-secondary" @click="cancelDelete" :disabled="isDeleting">
            Cancel
          </button>
          <button 
            type="button" 
            class="btn-confirm-delete" 
            @click="confirmAndExecuteDelete" 
            :disabled="isDeleting"
          >
            <span v-if="isDeleting">Deleting…</span>
            <span v-else>Delete Project</span>
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted, computed, watch } from 'vue';
import { projectStore } from '../services/projectStore';
import { listProjects, loadProject, revealInExplorer, isTauriEnvironment, saveFileToPath } from '../services/api';
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
  Mic,
  ArrowRight
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

/** Desktop app vs shared-link/browser mode (vault storage, no folder reveal). */
const isTauriEnv = isTauriEnvironment();

const projectToDelete = ref<ProjectSummary | null>(null);
const isDeleting = ref(false);
const loadError = ref('');

function requestDelete(p: ProjectSummary) {
  projectToDelete.value = p;
}

function cancelDelete() {
  projectToDelete.value = null;
}

async function confirmAndExecuteDelete() {
  if (!projectToDelete.value) return;
  const target = projectToDelete.value;
  isDeleting.value = true;
  try {
    await deleteProject(target);
    projectToDelete.value = null;
  } catch (err: any) {
    loadError.value = `Failed to delete project: ${err?.message || err}`;
    setTimeout(() => { loadError.value = ''; }, 4000);
  } finally {
    isDeleting.value = false;
  }
}

onMounted(() => {
  try {
    const cached = localStorage.getItem(CACHE_KEY);
    if (cached) {
      projectsList.value = JSON.parse(cached);
    }
  } catch {}

  fetchProjects();

  const handleGlobalKey = (e: KeyboardEvent) => {
    if (e.key === 'Escape') {
      if (projectToDelete.value) {
        projectToDelete.value = null;
      } else if (showNewModal.value) {
        showNewModal.value = false;
      }
    }
  };
  window.addEventListener('keydown', handleGlobalKey);
  onUnmounted(() => {
    window.removeEventListener('keydown', handleGlobalKey);
  });
});

watch(() => projectStore.currentTab.value, (newTab) => {
  if (newTab === 'projects') {
    fetchProjects();
  }
});

function normalizeProjectSummary(p: any): ProjectSummary {
  const surahs: any[] = Array.isArray(p.surahs) ? p.surahs : [];
  const surahsCount = surahs.length || (typeof p.surahs_count === 'number' ? p.surahs_count : 0);

  // Extract primary surah
  let primarySurah = p.primary_surah;
  if (!primarySurah && surahs.length > 0) {
    const s0 = surahs[0];
    primarySurah = {
      surah_number: s0.surah_number || 1,
      surah_name_arabic: s0.surah_name_arabic || '',
      surah_name_english: s0.surah_name_english || '',
    };
  }

  // Calculate total ayahs and total duration
  let totalAyahs = typeof p.total_ayahs === 'number' && p.total_ayahs > 0 ? p.total_ayahs : 0;
  if (totalAyahs === 0 && surahs.length > 0) {
    totalAyahs = surahs.reduce((sum: number, s: any) => sum + (Array.isArray(s.ayahs) ? s.ayahs.length : 0), 0);
  }

  let totalDuration = typeof p.total_duration === 'number' && p.total_duration > 0 ? p.total_duration : 0;
  if (totalDuration === 0 && surahs.length > 0) {
    totalDuration = surahs.reduce((sum: number, s: any) => sum + (Number(s.audio_duration_seconds) || 0), 0);
  }

  // Derive status
  let status = p.status;
  if (!status && surahs.length > 0) {
    const isAllVerified = surahs.every((s: any) => s.status === 'verified');
    status = isAllVerified ? 'verified' : 'needs_review';
  }

  const fileName = getProjectFileName(p);
  const rawProjectName = String(p.project_name || p.name || '').trim();
  const cleanBase = fileName.replace(/\.qproj$/i, '').replace(/^[.\s]+|[.\s]+$/g, '');
  const projectName = (rawProjectName && rawProjectName !== '.') 
    ? rawProjectName 
    : (cleanBase || 'Recitation Project');

  return {
    ...p,
    file_name: fileName,
    project_name: projectName,
    reciter: p.reciter || p.settings?.reciter_name || '',
    riwayah: p.riwayah || p.settings?.riwayah || 'Hafs',
    status: status || 'needs_review',
    surahs_count: surahsCount,
    surah_numbers: p.surah_numbers || surahs.map((s: any) => s.surah_number),
    primary_surah: primarySurah,
    total_ayahs: totalAyahs,
    total_duration: totalDuration,
    created_at: p.created_at || new Date().toISOString(),
    updated_at: p.updated_at || p.created_at || new Date().toISOString(),
    size_bytes: p.size_bytes || 0,
  };
}

const filteredProjects = computed(() => {
  let list = projectsList.value;

  const q = searchQuery.value.trim().toLowerCase();
  if (q) {
    list = list.filter(p => {
      const matchName = String(p.project_name || '').toLowerCase().includes(q);
      const matchReciter = p.reciter && String(p.reciter).toLowerCase().includes(q);
      const matchRiwayah = p.riwayah && String(p.riwayah).toLowerCase().includes(q);
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

  const byRecent = (a: ProjectSummary, b: ProjectSummary) => {
    const ta = new Date(a.updated_at || a.created_at || 0).getTime() || 0;
    const tb = new Date(b.updated_at || b.created_at || 0).getTime() || 0;
    return tb - ta;
  };

  return [...list].sort((a, b) => {
    if (sortKey.value === 'name') {
      return String(a.project_name || '').localeCompare(String(b.project_name || ''));
    } else if (sortKey.value === 'surahs') {
      return (Number(b.surahs_count) || 0) - (Number(a.surahs_count) || 0) || byRecent(a, b);
    } else if (sortKey.value === 'review') {
      return (isVerified(a) ? 1 : 0) - (isVerified(b) ? 1 : 0) || byRecent(a, b);
    } else {
      return byRecent(a, b);
    }
  });
});

function getProjectFileName(p: any): string {
  const raw = p?.file_name || p?._file || p?.file;
  if (raw) {
    return /\.qproj$/i.test(raw) ? raw : `${raw}.qproj`;
  }
  const name = String(p?.project_name || '').trim().replace(/^\.+|\.+$/g, '');
  return `${name || 'Recitation Project'}.qproj`;
}

async function fetchProjects(retries?: number | Event) {
  const retryCount = typeof retries === 'number' ? retries : 3;
  isFetching.value = true;
  try {
    let rawList: any[] = [];
    if (!isTauriEnvironment()) {
      rawList = await vaultList();
    } else {
      const data = await listProjects();
      rawList = data.projects || [];
    }

    let list = rawList.map(normalizeProjectSummary);

    // CRITICAL: Ensure currently active project in store is represented,
    // including brand new projects with 0 surahs or unsaved in-memory changes:
    if (projectStore.project && projectStore.project.project_name) {
      const activeFileName = getProjectFileName(projectStore.project);
      const isActualProject = Boolean(projectStore.project.file_name) || 
        (projectStore.project.surahs && projectStore.project.surahs.length > 0) || 
        projectStore.isDirty.value;

      if (isActualProject) {
        const existingIdx = list.findIndex(p => 
          getProjectFileName(p) === activeFileName || 
          p.project_name === projectStore.project.project_name
        );
        if (existingIdx === -1) {
          list.unshift(normalizeProjectSummary({
            ...projectStore.project,
            file_name: activeFileName,
          }));
          // Trigger immediate disk write if not yet saved
          projectStore.saveActiveProject().catch(() => {});
        } else {
          // If in-memory copy has more surahs or newer updates, upgrade it:
          const activeSurahs = projectStore.project.surahs || [];
          if (activeSurahs.length >= (list[existingIdx].surahs_count || 0)) {
            list[existingIdx] = normalizeProjectSummary({
              ...projectStore.project,
              file_name: activeFileName,
            });
          }
        }
      }
    }

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

    const content = JSON.stringify(data, null, 2);
    const defaultExportName = fname.endsWith('.qproj') ? fname : `${fname}.qproj`;

    if (isTauriEnvironment()) {
      try {
        const { save } = await import('@tauri-apps/plugin-dialog');
        const selectedPath = await save({
          defaultPath: defaultExportName,
          filters: [
            { name: 'Quran Recitation Project (*.qproj)', extensions: ['qproj'] },
            { name: 'All Files', extensions: ['*'] }
          ]
        });
        if (selectedPath) {
          await saveFileToPath(selectedPath, content);
          return;
        } else {
          return; // User cancelled
        }
      } catch (dialogErr) {
        console.warn('Native save dialog failed or unavailable, using browser download:', dialogErr);
      }
    }

    const blob = new Blob([content], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = defaultExportName;
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
