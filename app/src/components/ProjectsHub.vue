<template>
  <div class="projects-container">
    <!-- Clean Desktop Header (QuranCaption Aesthetic) -->
    <header class="hub-header">
      <div class="header-main">
        <div class="title-group">
          <h1 class="page-title">Projects</h1>
          <p class="page-subtitle">Quran recitation alignment workspaces and audio sessions</p>
        </div>

        <div class="action-group">
          <input 
            type="file" 
            ref="fileInputRef" 
            accept=".qproj,.json" 
            style="display: none" 
            @change="handleFileInputChange" 
          />
          <button 
            class="btn-secondary" 
            @click="triggerFileInput" 
            title="Import .qproj project file"
          >
            <FolderOpen :size="14" />
            <span>Import</span>
          </button>

          <button 
            class="btn-secondary" 
            @click="revealProjectsDirectory" 
            title="Reveal projects folder in Explorer"
          >
            <Folder :size="14" />
            <span>Folder</span>
          </button>

          <button 
            class="btn-icon" 
            @click="fetchProjects" 
            :disabled="isFetching"
            title="Refresh projects"
          >
            <RefreshCw :size="14" :class="{ 'spin': isFetching }" />
          </button>

          <button 
            class="btn-primary" 
            @click="showNewModal = true" 
            title="Create a new recitation alignment project"
          >
            <Plus :size="15" />
            <span>New Project</span>
          </button>
        </div>
      </div>

      <!-- Controls Row: Search, Status Filter, Sort & View Switcher -->
      <div class="controls-row">
        <!-- Search Input -->
        <div class="search-wrap">
          <Search :size="14" class="search-icon" />
          <input 
            type="text" 
            v-model="searchQuery" 
            placeholder="Search by name, reciter, or surah..." 
            class="search-input"
          />
          <button v-if="searchQuery" class="clear-btn" @click="searchQuery = ''">✕</button>
        </div>

        <!-- Minimal Status Tabs -->
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
            Needs Review
          </button>
          <button 
            class="tab-btn" 
            :class="{ 'active': activeStatusFilter === 'draft' }"
            @click="activeStatusFilter = 'draft'"
          >
            <span class="dot dot-gray"></span>
            Draft
          </button>
        </div>

        <!-- Right Side: Sort & View Mode Switcher -->
        <div class="view-controls">
          <div class="sort-select-wrap">
            <SlidersHorizontal :size="12" class="sort-icon" />
            <select v-model="sortKey" class="sort-select">
              <option value="updated">Recently Modified</option>
              <option value="name">Name (A-Z)</option>
              <option value="duration">Audio Duration</option>
              <option value="ayahs">Ayah Count</option>
            </select>
          </div>

          <div class="mode-toggle">
            <button 
              class="mode-btn" 
              :class="{ 'active': viewMode === 'grid' }"
              @click="setViewMode('grid')"
              title="Card Grid View"
            >
              <LayoutGrid :size="14" />
            </button>
            <button 
              class="mode-btn" 
              :class="{ 'active': viewMode === 'list' }"
              @click="setViewMode('list')"
              title="Table List View"
            >
              <List :size="14" />
            </button>
          </div>
        </div>
      </div>
    </header>

    <!-- Main Workspace Area -->
    <main class="hub-main">
      <!-- Loading Skeleton (Initial Fetch Only) -->
      <div v-if="isFetching && projectsList.length === 0" class="empty-state">
        <RefreshCw :size="24" class="spin text-accent" />
        <p class="state-text">Loading projects...</p>
      </div>

      <!-- Empty State -->
      <div v-else-if="filteredProjects.length === 0" class="empty-state">
        <FolderKanban :size="38" class="empty-icon" />
        <h3 class="empty-title">{{ searchQuery ? 'No matching projects found' : 'No projects created yet' }}</h3>
        <p class="empty-desc">
          {{ searchQuery ? 'Try adjusting your search query or status filter.' : 'Create your first recitation alignment project or import an existing .qproj file.' }}
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

      <!-- View 1: Card Grid (Directly modeled on QuranCaption's ProjectDetailCard) -->
      <div v-else-if="viewMode === 'grid'" class="projects-grid">
        <div 
          v-for="p in filteredProjects" 
          :key="p.file_name"
          class="project-card"
          @click="openProject(p)"
        >
          <!-- Card Thumbnail Header (QuranCaption Style) -->
          <div class="card-thumbnail">
            <!-- Center Surah Number / Watermark -->
            <div class="thumbnail-surah">
              <span class="surah-num">{{ getSurahWatermark(p) }}</span>
              <span class="surah-name" v-if="p.primary_surah?.surah_name_arabic">
                {{ p.primary_surah.surah_name_arabic }}
              </span>
            </div>

            <!-- Top Right: Status Badge -->
            <div class="thumbnail-status" :class="getStatusClass(p.status)">
              <span class="status-dot"></span>
              <span>{{ getStatusLabel(p.status) }}</span>
            </div>

            <!-- Bottom Left: Reciter -->
            <div class="thumbnail-reciter" v-if="p.reciter">
              <Mic :size="11" />
              <span>{{ p.reciter }}</span>
            </div>

            <!-- Bottom Right: Duration Badge -->
            <div class="thumbnail-duration" v-if="p.total_duration > 0">
              <Clock :size="10" />
              <span>{{ formatDuration(p.total_duration) }}</span>
            </div>
          </div>

          <!-- Card Details -->
          <div class="card-details">
            <h3 class="card-name" :title="p.project_name">{{ p.project_name }}</h3>

            <div class="card-meta">
              <span class="meta-item" v-if="p.riwayah">{{ p.riwayah }}</span>
              <span class="meta-dot" v-if="p.riwayah && p.total_ayahs > 0">•</span>
              <span class="meta-item" v-if="p.total_ayahs > 0">{{ p.total_ayahs }} Ayahs</span>
              <span class="meta-dot">•</span>
              <span class="meta-item time">{{ formatDateRelative(p.updated_at) }}</span>
            </div>
          </div>

          <!-- Card Footer Actions -->
          <div class="card-footer" @click.stop>
            <button class="btn-card-open" @click="openProject(p)" title="Open in Studio">
              <span>Open</span>
              <ArrowRight :size="13" />
            </button>

            <div class="card-icons">
              <button 
                class="btn-card-tool" 
                @click="duplicateProject(p)" 
                title="Duplicate project"
              >
                <Copy :size="13" />
              </button>
              <button 
                class="btn-card-tool" 
                @click="revealProjectInExplorer(p)" 
                title="Reveal in Windows Explorer"
              >
                <Folder :size="13" />
              </button>
              <a 
                :href="`/api/engine/projects/load?file=${encodeURIComponent(p.file_name)}`" 
                :download="p.file_name" 
                class="btn-card-tool" 
                title="Download .qproj"
              >
                <Download :size="13" />
              </a>
              <button 
                class="btn-card-tool btn-danger" 
                @click="deleteProject(p)" 
                title="Delete project"
              >
                <Trash2 :size="13" />
              </button>
            </div>
          </div>
        </div>
      </div>

      <!-- View 2: High-Density Table List View -->
      <div v-else class="table-wrap">
        <table class="projects-table">
          <thead>
            <tr>
              <th class="col-surah">Surah</th>
              <th class="col-name">Project Name</th>
              <th class="col-reciter">Reciter</th>
              <th class="col-riwayah">Riwayah</th>
              <th class="col-status">Status</th>
              <th class="col-ayahs">Ayahs</th>
              <th class="col-duration">Duration</th>
              <th class="col-updated">Updated</th>
              <th class="col-actions">Actions</th>
            </tr>
          </thead>
          <tbody>
            <tr 
              v-for="p in filteredProjects" 
              :key="p.file_name"
              class="table-row"
              @click="openProject(p)"
            >
              <td class="col-surah">
                <span class="table-surah-badge">{{ getSurahWatermark(p) }}</span>
              </td>
              <td class="col-name">
                <div class="name-text" :title="p.project_name">{{ p.project_name }}</div>
                <div class="file-text">{{ p.file_name }}</div>
              </td>
              <td class="col-reciter">
                {{ p.reciter || '—' }}
              </td>
              <td class="col-riwayah">
                {{ p.riwayah || '—' }}
              </td>
              <td class="col-status">
                <span class="status-badge-inline" :class="getStatusClass(p.status)">
                  <span class="status-dot"></span>
                  <span>{{ getStatusLabel(p.status) }}</span>
                </span>
              </td>
              <td class="col-ayahs">
                {{ p.total_ayahs || 0 }}
              </td>
              <td class="col-duration">
                {{ formatDuration(p.total_duration) }}
              </td>
              <td class="col-updated">
                {{ formatDateRelative(p.updated_at) }}
              </td>
              <td class="col-actions" @click.stop>
                <div class="table-actions-row">
                  <button class="btn-table-open" @click="openProject(p)" title="Open in Studio">
                    Open
                  </button>
                  <button class="btn-card-tool" @click="duplicateProject(p)" title="Duplicate">
                    <Copy :size="12" />
                  </button>
                  <button class="btn-card-tool" @click="revealProjectInExplorer(p)" title="Reveal folder">
                    <Folder :size="12" />
                  </button>
                  <button class="btn-card-tool btn-danger" @click="deleteProject(p)" title="Delete">
                    <Trash2 :size="12" />
                  </button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </main>

    <!-- Create New Project Modal -->
    <div v-if="showNewModal" class="modal-backdrop" @click.self="showNewModal = false">
      <div class="modal-box">
        <div class="modal-header">
          <h3 class="modal-title">New Recitation Project</h3>
          <button class="modal-close-btn" @click="showNewModal = false">✕</button>
        </div>

        <form @submit.prevent="handleCreateProject" class="modal-form">
          <div class="form-group">
            <label class="form-label">Project Name *</label>
            <input 
              type="text" 
              v-model="newProjectName" 
              placeholder="e.g., Surat Al-Kahf - Mishary Rashid" 
              required
              autofocus
              class="form-input"
            />
          </div>

          <div class="form-group">
            <label class="form-label">Reciter (Optional)</label>
            <input 
              type="text" 
              v-model="newReciterName" 
              placeholder="e.g., Sheikh Mishary Rashid Alafasy" 
              class="form-input"
            />
          </div>

          <div class="form-group">
            <label class="form-label">Riwayah</label>
            <select v-model="newRiwayah" class="form-select">
              <option value="Hafs 'an 'Asim">Hafs 'an 'Asim</option>
              <option value="Warsh 'an Nafi'">Warsh 'an Nafi'</option>
              <option value="Qalun 'an Nafi'">Qalun 'an Nafi'</option>
              <option value="Al-Duri 'an Abi 'Amr">Al-Duri 'an Abi 'Amr</option>
              <option value="Shu'bah 'an 'Asim">Shu'bah 'an 'Asim</option>
              <option value="Al-Susi 'an Abi 'Amr">Al-Susi 'an Abi 'Amr</option>
            </select>
          </div>

          <div class="modal-actions">
            <button 
              type="button" 
              class="btn-secondary" 
              @click="showNewModal = false"
            >
              Cancel
            </button>
            <button 
              type="submit" 
              class="btn-primary" 
              :disabled="isCreating || !newProjectName.trim()"
            >
              <span v-if="isCreating">Creating...</span>
              <span v-else>Create Project</span>
            </button>
          </div>
        </form>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, computed, watch } from 'vue';
import { projectStore } from '../services/projectStore';
import type { ProjectSummary } from '../types/aligner';
import { 
  FolderKanban,
  FolderOpen, 
  Folder, 
  Plus, 
  ArrowRight, 
  Copy,
  Download, 
  Trash2,
  Search,
  Clock,
  RefreshCw,
  LayoutGrid,
  List,
  SlidersHorizontal,
  Mic
} from 'lucide-vue-next';

const CACHE_KEY = 'quran_studio_projects_cache';

// Reactive State
const searchQuery = ref('');
const activeStatusFilter = ref<'all' | 'verified' | 'needs_review' | 'draft'>('all');
const sortKey = ref<'updated' | 'name' | 'duration' | 'ayahs'>('updated');
const viewMode = ref<'grid' | 'list'>('grid');

const showNewModal = ref(false);
const newProjectName = ref('');
const newReciterName = ref('');
const newRiwayah = ref("Hafs 'an 'Asim");
const isCreating = ref(false);
const isFetching = ref(false);
const projectsList = ref<ProjectSummary[]>([]);
const fileInputRef = ref<HTMLInputElement | null>(null);

// Lifecycle
onMounted(() => {
  // 1. Instant cache load (0ms rendering)
  try {
    const cached = localStorage.getItem(CACHE_KEY);
    if (cached) {
      projectsList.value = JSON.parse(cached);
    }
  } catch {}

  const savedView = localStorage.getItem('quran_projects_view_mode');
  if (savedView === 'grid' || savedView === 'list') {
    viewMode.value = savedView;
  }

  // 2. Auto-fetch only when engine supervisor signals ready (or if already ready)
  if ((window as any).__ENGINE_READY__) {
    fetchProjects();
  }
  window.addEventListener('engine-ready', () => {
    (window as any).__ENGINE_READY__ = true;
    fetchProjects();
  });
});

watch(() => projectStore.currentTab.value, (newTab) => {
  if (newTab === 'projects') {
    fetchProjects();
  }
});

function setViewMode(mode: 'grid' | 'list') {
  viewMode.value = mode;
  try {
    localStorage.setItem('quran_projects_view_mode', mode);
  } catch {}
}

// Filtered & Sorted Projects
const filteredProjects = computed(() => {
  let list = projectsList.value;

  // 1. Search Query
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

  // 2. Status Filter
  if (activeStatusFilter.value !== 'all') {
    list = list.filter(p => {
      const st = (p.status || 'draft').toLowerCase();
      if (activeStatusFilter.value === 'verified') return st === 'verified' || st === 'completed' || st === 'done';
      if (activeStatusFilter.value === 'needs_review') return st === 'needs_review' || st === 'review';
      if (activeStatusFilter.value === 'draft') return st === 'draft' || st === 'aligned' || !p.status;
      return true;
    });
  }

  // 3. Sorting
  return [...list].sort((a, b) => {
    if (sortKey.value === 'name') {
      return a.project_name.localeCompare(b.project_name);
    } else if (sortKey.value === 'duration') {
      return (b.total_duration || 0) - (a.total_duration || 0);
    } else if (sortKey.value === 'ayahs') {
      return (b.total_ayahs || 0) - (a.total_ayahs || 0);
    } else {
      const timeA = new Date(a.updated_at).getTime() || 0;
      const timeB = new Date(b.updated_at).getTime() || 0;
      return timeB - timeA;
    }
  });
});

// Network Fetching (Sub-millisecond backend cache response with auto-retry)
async function fetchProjects(retries?: number | Event) {
  const retryCount = typeof retries === 'number' ? retries : 3;
  isFetching.value = true;
  try {
    const res = await fetch('/api/engine/projects');
    if (res.ok) {
      const data = await res.json();
      const list = data.projects || [];
      projectsList.value = list;
      try {
        localStorage.setItem(CACHE_KEY, JSON.stringify(list));
      } catch {}
    } else if (res.status === 503 && retryCount > 0) {
      await new Promise(r => setTimeout(r, 600));
      return fetchProjects(retryCount - 1);
    }
  } catch (err) {
    if (retryCount > 0) {
      await new Promise(r => setTimeout(r, 600));
      return fetchProjects(retryCount - 1);
    }
    console.warn('Could not fetch projects from backend:', err);
  } finally {
    isFetching.value = false;
  }
}

// User Actions
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
  reader.onload = (event) => {
    try {
      const content = event.target?.result as string;
      const parsed = JSON.parse(content);
      if (parsed.surahs && parsed.project_name) {
        projectStore.loadProject(parsed);
        projectStore.currentTab.value = 'studio';
      } else if (parsed.surahs && parsed.surahs[0]?.ayahs) {
        projectStore.project.surahs = [];
        projectStore.loadAlignedSurah(parsed);
        projectStore.currentTab.value = 'studio';
      } else {
        alert('Invalid project file structure.');
      }
    } catch (err: any) {
      alert(`Error reading project file: ${err.message}`);
    }
  };
  reader.readAsText(file);
}

async function openProject(p: ProjectSummary) {
  await projectStore.openProjectByFileName(p.file_name);
}

async function deleteProject(p: ProjectSummary) {
  if (confirm(`Are you sure you want to delete "${p.project_name}"?`)) {
    const ok = await projectStore.deleteProjectFile(p.file_name);
    if (ok) {
      projectsList.value = projectsList.value.filter(item => item.file_name !== p.file_name);
      try {
        localStorage.setItem(CACHE_KEY, JSON.stringify(projectsList.value));
      } catch {}
      await fetchProjects();
    }
  }
}

async function duplicateProject(p: ProjectSummary) {
  const ok = await projectStore.duplicateProjectFile(p.file_name);
  if (ok) {
    await fetchProjects();
  }
}

async function revealProjectInExplorer(p: ProjectSummary) {
  try {
    await fetch('/api/engine/system/reveal', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path: p.file_name }),
    });
  } catch (err) {
    console.error('Failed to reveal file:', err);
  }
}

async function revealProjectsDirectory() {
  try {
    await fetch('/api/engine/system/reveal', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path: 'projects' }),
    });
  } catch (err) {
    console.error('Failed to reveal projects folder:', err);
  }
}

// Helpers
function getStatusLabel(status?: string): string {
  const st = (status || 'draft').toLowerCase();
  if (st === 'verified' || st === 'completed' || st === 'done') return 'Verified';
  if (st === 'needs_review' || st === 'review') return 'Needs Review';
  return 'Draft';
}

function getStatusClass(status?: string): string {
  const st = (status || 'draft').toLowerCase();
  if (st === 'verified' || st === 'completed' || st === 'done') return 'status-verified';
  if (st === 'needs_review' || st === 'review') return 'status-review';
  return 'status-draft';
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
  background: #090d16;
  color: #f3f4f6;
  overflow-y: auto;
  overflow-x: hidden;
}

/* ==============================================================================
   1. Clean Desktop Header (QuranCaption Style)
   ============================================================================== */
.hub-header {
  background: #0d111a;
  border-bottom: 1px solid #1e2638;
  padding: 20px 32px 16px 32px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.header-main {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
}

.title-group {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.page-title {
  font-size: 1.45rem;
  font-weight: 700;
  color: #ffffff;
  margin: 0;
  letter-spacing: -0.01em;
}

.page-subtitle {
  font-size: 0.8rem;
  color: #8b949e;
  margin: 0;
}

.action-group {
  display: flex;
  align-items: center;
  gap: 8px;
}

/* Buttons */
.btn-primary {
  background: #2563eb;
  color: #ffffff;
  border: 1px solid rgba(255, 255, 255, 0.15);
  font-size: 0.8rem;
  font-weight: 600;
  padding: 7px 14px;
  border-radius: 6px;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  cursor: pointer;
  transition: background 0.1s ease;
}
.btn-primary:hover:not(:disabled) {
  background: #1d4ed8;
}
.btn-primary:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.btn-secondary {
  background: #161b26;
  border: 1px solid #28334a;
  color: #c9d1d9;
  font-size: 0.8rem;
  font-weight: 500;
  padding: 7px 12px;
  border-radius: 6px;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  cursor: pointer;
  transition: all 0.1s ease;
}
.btn-secondary:hover:not(:disabled) {
  background: #21293a;
  color: #ffffff;
  border-color: #3e4e70;
}

.btn-icon {
  background: #161b26;
  border: 1px solid #28334a;
  color: #c9d1d9;
  padding: 7px 9px;
  border-radius: 6px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: all 0.1s ease;
}
.btn-icon:hover:not(:disabled) {
  background: #21293a;
  color: #ffffff;
}

/* Controls Row */
.controls-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
}

.search-wrap {
  position: relative;
  width: 280px;
}
.search-icon {
  position: absolute;
  left: 10px;
  top: 50%;
  transform: translateY(-50%);
  color: #6b7280;
  pointer-events: none;
}
.search-input {
  width: 100%;
  background: #121722;
  border: 1px solid #232d42;
  border-radius: 6px;
  padding: 6px 28px 6px 30px;
  font-size: 0.78rem;
  color: #ffffff;
  outline: none;
  transition: border-color 0.1s ease;
}
.search-input:focus {
  border-color: #3b82f6;
}
.clear-btn {
  position: absolute;
  right: 8px;
  top: 50%;
  transform: translateY(-50%);
  background: transparent;
  border: none;
  color: #9ca3af;
  font-size: 0.75rem;
  cursor: pointer;
}

.status-tabs {
  display: flex;
  align-items: center;
  gap: 4px;
  background: #121722;
  padding: 3px;
  border-radius: 6px;
  border: 1px solid #1e2638;
}
.tab-btn {
  background: transparent;
  border: none;
  color: #8b949e;
  font-size: 0.75rem;
  font-weight: 500;
  padding: 4px 10px;
  border-radius: 4px;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  cursor: pointer;
  transition: all 0.1s ease;
}
.tab-btn:hover {
  color: #ffffff;
}
.tab-btn.active {
  background: #1e2638;
  color: #ffffff;
  font-weight: 600;
}
.tab-badge {
  background: #2a344d;
  color: #c9d1d9;
  font-size: 0.68rem;
  padding: 1px 5px;
  border-radius: 10px;
}

.dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
}
.dot-green { background: #10b981; }
.dot-amber { background: #f59e0b; }
.dot-gray { background: #6b7280; }

.view-controls {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-left: auto;
}

.sort-select-wrap {
  display: flex;
  align-items: center;
  position: relative;
}
.sort-icon {
  position: absolute;
  left: 8px;
  color: #6b7280;
  pointer-events: none;
}
.sort-select {
  background: #121722;
  border: 1px solid #232d42;
  color: #c9d1d9;
  font-size: 0.75rem;
  padding: 6px 10px 6px 26px;
  border-radius: 6px;
  cursor: pointer;
  outline: none;
}
.sort-select:focus {
  border-color: #3b82f6;
}

.mode-toggle {
  display: flex;
  align-items: center;
  background: #121722;
  border: 1px solid #1e2638;
  border-radius: 6px;
  padding: 2px;
}
.mode-btn {
  background: transparent;
  border: none;
  color: #6b7280;
  padding: 4px 7px;
  border-radius: 4px;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}
.mode-btn.active {
  background: #1e2638;
  color: #ffffff;
}

/* ==============================================================================
   2. Main Content & Cards Grid
   ============================================================================== */
.hub-main {
  padding: 24px 32px;
  flex: 1;
}

.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  padding: 60px 20px;
  color: #8b949e;
}
.empty-icon {
  color: #3b4252;
  margin-bottom: 12px;
}
.empty-title {
  font-size: 1.05rem;
  font-weight: 600;
  color: #ffffff;
  margin: 0 0 6px 0;
}
.empty-desc {
  font-size: 0.82rem;
  max-width: 400px;
  margin: 0 0 16px 0;
}
.empty-actions {
  display: flex;
  gap: 8px;
}
.state-text {
  margin-top: 10px;
  font-size: 0.82rem;
}

/* Cards Grid */
.projects-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(290px, 1fr));
  gap: 20px;
}

.project-card {
  background: #111622;
  border: 1px solid #1e2638;
  border-radius: 10px;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  cursor: pointer;
  transition: border-color 0.15s ease, transform 0.15s ease;
}
.project-card:hover {
  border-color: #388bfd;
  transform: translateY(-2px);
}

/* Thumbnail */
.card-thumbnail {
  background: #0d111a;
  height: 120px;
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
  border-bottom: 1px solid #1a2233;
}

.thumbnail-surah {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
}
.surah-num {
  font-family: 'Amiri', 'Amiri Quran', serif;
  font-size: 2.5rem;
  font-weight: 700;
  line-height: 1;
  color: #2b354d;
  letter-spacing: 0.05em;
}
.surah-name {
  font-family: 'Amiri', serif;
  font-size: 0.85rem;
  color: #6b7280;
}

.thumbnail-status {
  position: absolute;
  top: 8px;
  right: 8px;
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 0.68rem;
  font-weight: 600;
  padding: 2px 7px;
  border-radius: 10px;
  background: rgba(0, 0, 0, 0.4);
}
.status-verified {
  color: #34d399;
}
.status-verified .status-dot {
  background: #10b981;
}
.status-review {
  color: #fbbf24;
}
.status-review .status-dot {
  background: #f59e0b;
}
.status-draft {
  color: #9ca3af;
}
.status-draft .status-dot {
  background: #6b7280;
}
.status-dot {
  width: 5px;
  height: 5px;
  border-radius: 50%;
}

.thumbnail-reciter {
  position: absolute;
  bottom: 8px;
  left: 10px;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 0.7rem;
  font-weight: 500;
  color: #c9d1d9;
  background: rgba(0, 0, 0, 0.5);
  padding: 2px 6px;
  border-radius: 4px;
  max-width: 60%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.thumbnail-duration {
  position: absolute;
  bottom: 8px;
  right: 10px;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 0.68rem;
  font-weight: 600;
  color: #9ca3af;
  background: rgba(0, 0, 0, 0.5);
  padding: 2px 6px;
  border-radius: 4px;
}

/* Card Details */
.card-details {
  padding: 14px 16px 10px 16px;
  display: flex;
  flex-direction: column;
  gap: 6px;
  flex: 1;
}

.card-name {
  font-size: 0.92rem;
  font-weight: 600;
  color: #ffffff;
  margin: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.card-meta {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 0.72rem;
  color: #8b949e;
}
.meta-dot {
  color: #4b5563;
}
.meta-item.time {
  color: #6b7280;
}

/* Card Footer */
.card-footer {
  padding: 8px 14px 12px 14px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-top: 1px solid #1a2233;
}

.btn-card-open {
  background: #1e2638;
  color: #ffffff;
  border: 1px solid #28334a;
  border-radius: 5px;
  font-size: 0.75rem;
  font-weight: 600;
  padding: 5px 12px;
  display: inline-flex;
  align-items: center;
  gap: 5px;
  cursor: pointer;
  transition: all 0.1s ease;
}
.btn-card-open:hover {
  background: #2563eb;
  border-color: #2563eb;
}

.card-icons {
  display: flex;
  align-items: center;
  gap: 3px;
}
.btn-card-tool {
  background: transparent;
  border: none;
  color: #6b7280;
  padding: 5px;
  border-radius: 4px;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  text-decoration: none;
  transition: color 0.1s ease, background 0.1s ease;
}
.btn-card-tool:hover {
  color: #ffffff;
  background: #1e2638;
}
.btn-card-tool.btn-danger:hover {
  color: #ef4444;
  background: rgba(239, 68, 68, 0.15);
}

/* ==============================================================================
   3. High-Density Table List View
   ============================================================================== */
.table-wrap {
  background: #111622;
  border: 1px solid #1e2638;
  border-radius: 8px;
  overflow: hidden;
}

.projects-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.78rem;
  text-align: left;
}

.projects-table th {
  background: #0d111a;
  color: #8b949e;
  font-weight: 600;
  padding: 10px 14px;
  border-bottom: 1px solid #1e2638;
  white-space: nowrap;
}

.table-row {
  border-bottom: 1px solid #161d2b;
  cursor: pointer;
  transition: background 0.1s ease;
}
.table-row:hover {
  background: #161d2a;
}

.table-row td {
  padding: 10px 14px;
  color: #c9d1d9;
  vertical-align: middle;
}

.table-surah-badge {
  background: #1a2233;
  color: #8b949e;
  font-family: monospace;
  font-size: 0.75rem;
  font-weight: 700;
  padding: 2px 6px;
  border-radius: 4px;
}

.name-text {
  font-weight: 600;
  color: #ffffff;
}
.file-text {
  font-size: 0.68rem;
  color: #6b7280;
}

.status-badge-inline {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 0.72rem;
  font-weight: 500;
}

.table-actions-row {
  display: flex;
  align-items: center;
  gap: 4px;
}
.btn-table-open {
  background: #1e2638;
  color: #ffffff;
  border: 1px solid #28334a;
  border-radius: 4px;
  font-size: 0.72rem;
  font-weight: 600;
  padding: 3px 8px;
  cursor: pointer;
}
.btn-table-open:hover {
  background: #2563eb;
  border-color: #2563eb;
}

/* ==============================================================================
   4. Modal
   ============================================================================== */
.modal-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.75);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}

.modal-box {
  background: #111622;
  border: 1px solid #28334a;
  border-radius: 10px;
  width: 440px;
  max-width: 90vw;
  box-shadow: 0 10px 25px rgba(0, 0, 0, 0.5);
}

.modal-header {
  padding: 16px 20px;
  border-bottom: 1px solid #1e2638;
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.modal-title {
  font-size: 1rem;
  font-weight: 700;
  color: #ffffff;
  margin: 0;
}
.modal-close-btn {
  background: transparent;
  border: none;
  color: #8b949e;
  font-size: 1rem;
  cursor: pointer;
}
.modal-close-btn:hover {
  color: #ffffff;
}

.modal-form {
  padding: 20px;
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.form-group {
  display: flex;
  flex-direction: column;
  gap: 5px;
}
.form-label {
  font-size: 0.75rem;
  font-weight: 600;
  color: #c9d1d9;
}
.form-input, .form-select {
  background: #0d111a;
  border: 1px solid #232d42;
  border-radius: 6px;
  padding: 8px 10px;
  font-size: 0.82rem;
  color: #ffffff;
  outline: none;
}
.form-input:focus, .form-select:focus {
  border-color: #3b82f6;
}

.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 10px;
}

/* Animations */
.spin {
  animation: spin 1s linear infinite;
}
@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}
</style>
