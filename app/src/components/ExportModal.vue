<template>
  <div v-if="visible" class="modal-overlay" @click.self="close">
    <div class="export-modal glass-panel">
      <!-- Modal Header -->
      <div class="modal-header">
        <div class="header-left">
          <Download :size="18" class="text-accent" />
          <div class="header-titles">
            <h3 class="modal-title">Export</h3>
          </div>
        </div>
        <button class="btn-icon" @click="close" title="Close">
          <X :size="15" />
        </button>
      </div>

      <!-- Scope Selector Tabs: Current Surah vs All Surahs -->
      <div class="scope-tabs-bar">
        <button 
          class="scope-tab-btn" 
          :class="{ 'active': exportScope === 'current' }"
          @click="setExportScope('current')"
        >
          <FileText :size="13" />
          <span>Current ({{ projectStore.activeSurah.value?.surah_name_english || 'Active' }})</span>
        </button>
        <button 
          class="scope-tab-btn" 
          :class="{ 'active': exportScope === 'all' }"
          @click="setExportScope('all')"
          :disabled="totalSurahsCount <= 1"
          :title="totalSurahsCount <= 1 ? 'Add more surahs to export in batch' : 'Export all project surahs'"
        >
          <Layers :size="13" />
          <span>All Surahs ({{ totalSurahsCount }})</span>
        </button>
      </div>

      <!-- Multi-Surah Package Mode Switcher (Visible only when All Surahs is active) -->
      <div v-if="exportScope === 'all'" class="all-surahs-banner">
        <div class="project-stats-pill">
          <span class="stat-item"><strong>{{ totalSurahsCount }}</strong> Surahs</span>
          <span class="stat-dot">•</span>
          <span class="stat-item"><strong>{{ totalAyahsCount }}</strong> Ayahs</span>
          <span class="stat-dot">•</span>
          <span class="stat-item"><strong>{{ totalWordsCount }}</strong> Words</span>
        </div>

        <div class="batch-mode-toggle">
          <button 
            class="mode-pill-btn" 
            :class="{ 'active': allSurahsMode === 'combined' }"
            @click="setAllSurahsMode('combined')"
          >
            <FileSpreadsheet :size="13" />
            <span>Combined Single File</span>
          </button>
          <button 
            class="mode-pill-btn" 
            :class="{ 'active': allSurahsMode === 'zip' }"
            @click="setAllSurahsMode('zip')"
          >
            <Archive :size="13" />
            <span>ZIP Package (Separate File per Surah)</span>
          </button>
        </div>
      </div>

      <!-- Format Selection Grid -->
      <div class="modal-body">
        <div class="format-grid">
          <button 
            v-for="fmt in availableFormats" 
            :key="fmt.id"
            class="format-card"
            :class="{ 'selected': selectedFormat === fmt.id }"
            @click="selectFormat(fmt.id)"
          >
            <div class="format-card-top">
              <span class="fmt-ext">{{ fmt.ext }}</span>
              <span class="fmt-badge">{{ fmt.badge }}</span>
            </div>
            <span class="fmt-title">{{ fmt.title }}</span>
            <p class="fmt-desc">{{ fmt.description }}</p>
          </button>
        </div>

        <!-- Optional Format Toggle (Word vs Ayah for SRT) -->
        <div class="format-options" v-if="selectedFormat === 'srt'">
          <label class="toggle-label">
            <input type="checkbox" v-model="srtWordLevel" @change="generatePreview" />
            <span>Word-by-Word SRT Subtitles (High granularity, single word per line)</span>
          </label>
        </div>

        <!-- Preview Code Box -->
        <div class="preview-section">
          <div class="preview-header">
            <span class="preview-title">
              PREVIEW ({{ selectedFormat.toUpperCase() }} — {{ previewScopeLabel }})
            </span>
            <button 
              v-if="exportScope === 'current' || allSurahsMode === 'combined'"
              class="copy-btn" 
              @click="copyToClipboard"
            >
              <Check v-if="copied" :size="12" class="text-success" />
              <Copy v-else :size="12" />
              <span>{{ copied ? 'Copied!' : 'Copy to Clipboard' }}</span>
            </button>
            <span v-else class="preview-zip-badge">
              Archive contains {{ totalSurahsCount }} formatted files + project.qproj
            </span>
          </div>
          <pre class="preview-content">{{ previewContent }}</pre>
        </div>
      </div>

      <!-- Modal Footer -->
      <div class="modal-footer">
        <button class="btn btn-secondary" @click="close" :disabled="isExporting">Cancel</button>
        <button class="btn btn-primary" @click="handleDownload" :disabled="isExporting">
          <Loader2 v-if="isExporting" :size="15" class="animate-spin" />
          <Download v-else :size="15" />
          <span>{{ downloadButtonLabel }}</span>
        </button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue';
import { projectStore } from '../services/projectStore';
import { 
  exportCanonicalJson, 
  exportProjectFile,
  exportSrt, 
  exportVtt, 
  exportAssKaraoke, 
  exportQuranCaption, 
  exportWordTimingsCsv,
  exportPremiereMarkers,
  exportAllCanonicalJson,
  exportAllSrt,
  exportAllVtt,
  exportAllAssKaraoke,
  exportAllQuranCaption,
  exportAllWordTimingsCsv,
  exportAllPremiereMarkers,
  exportSurahsAsZip,
  buildPortableProject,
  downloadFile,
  downloadBlob,
  sanitizeBatchExportFileName,
  type ExportFormatId
} from '../services/exporters';
import { 
  Download, 
  X, 
  Copy, 
  Check, 
  FileText, 
  Layers, 
  Archive, 
  FileSpreadsheet, 
  Loader2 
} from 'lucide-vue-next';

const visible = ref(false);
const exportScope = ref<'current' | 'all'>('current');
const allSurahsMode = ref<'combined' | 'zip'>('combined');
const selectedFormat = ref<ExportFormatId>('json');
const srtWordLevel = ref(false);
const previewContent = ref('');
const copied = ref(false);
const isExporting = ref(false);

const totalSurahsCount = computed(() => projectStore.project.surahs.length);

const totalAyahsCount = computed(() => {
  return projectStore.project.surahs.reduce((sum, s) => sum + s.ayahs.length, 0);
});

const totalWordsCount = computed(() => {
  return projectStore.project.surahs.reduce((sum, s) => {
    return sum + s.ayahs.reduce((aSum, a) => {
      return aSum + a.segments.reduce((segSum, seg) => segSum + seg.words.length, 0);
    }, 0);
  }, 0);
});

const availableFormats = computed(() => {
  return [
    {
      id: 'json' as ExportFormatId,
      ext: '.JSON',
      badge: 'Canonical',
      title: 'Canonical Medina JSON',
      description: 'Full Mushaf word hierarchy & boundary timings.',
    },
    {
      id: 'srt' as ExportFormatId,
      ext: '.SRT',
      badge: 'Universal',
      title: 'Universal Subtitles',
      description: 'Standard SubRip for Premiere, DaVinci, VLC & YouTube.',
    },
    {
      id: 'vtt' as ExportFormatId,
      ext: '.VTT',
      badge: 'Web Standard',
      title: 'WebVTT Subtitles',
      description: 'HTML5 video subtitle track for modern browsers.',
    },
    {
      id: 'ass' as ExportFormatId,
      ext: '.ASS',
      badge: 'Karaoke',
      title: 'Word Karaoke Subtitles',
      description: 'Advanced SubStation Alpha with \\k centisecond tags.',
    },
    {
      id: 'qurancaption' as ExportFormatId,
      ext: '.JSON',
      badge: 'Video Tool',
      title: 'QuranCaption Format',
      description: 'Direct 1-click import into QuranCaption video timeline.',
    },
    {
      id: 'csv' as ExportFormatId,
      ext: '.CSV',
      badge: 'Spreadsheet',
      title: 'Word Timings CSV',
      description: 'Data table with millisecond durations & confidence.',
    },
    {
      id: 'premiere' as ExportFormatId,
      ext: '.CSV',
      badge: 'NLE Markers',
      title: 'Premiere / DaVinci Markers',
      description: 'Sequence markers ready to drag onto your video timeline.',
    },
    {
      id: 'qproj' as ExportFormatId,
      ext: '.QPROJ',
      badge: 'Portable',
      title: 'Quran Studio Project',
      description: 'Complete project with audio embedded — one file, works on any device or cloud.',
    },
  ];
});

const previewScopeLabel = computed(() => {
  if (exportScope.value === 'current') {
    const s = projectStore.activeSurah.value;
    return `Surah ${s ? s.surah_name_english : 'Active'}`;
  }
  if (allSurahsMode.value === 'zip') {
    return `ZIP Archive (${totalSurahsCount.value} Surahs)`;
  }
  return `Combined Project (${totalSurahsCount.value} Surahs)`;
});

const currentFilename = computed(() => {
  const safeProj = sanitizeBatchExportFileName(projectStore.project.project_name || 'quran_project');

  if (exportScope.value === 'all') {
    if (allSurahsMode.value === 'zip') {
      return `${safeProj}_all_surahs_batch.zip`;
    }
    switch (selectedFormat.value) {
      case 'json': return `${safeProj}_all_surahs_output.json`;
      case 'qproj': return `${safeProj}.qproj`;
      case 'srt': return `${safeProj}_all_surahs.srt`;
      case 'vtt': return `${safeProj}_all_surahs.vtt`;
      case 'ass': return `${safeProj}_all_surahs_karaoke.ass`;
      case 'qurancaption': return `${safeProj}_all_surahs_qurancaption.json`;
      case 'csv': return `${safeProj}_all_words.csv`;
      case 'premiere': return `${safeProj}_markers.csv`;
    }
  }

  // Single Surah Mode
  const s = projectStore.activeSurah.value;
  const num = s ? String(s.surah_number).padStart(3, '0') : '001';
  const name = s ? sanitizeBatchExportFileName(s.surah_name_english) : 'surah';
  switch (selectedFormat.value) {
    case 'json': return `surah_${num}_${name}_output.json`;
    case 'qproj': return `${safeProj}.qproj`;
    case 'srt': return `surah_${num}_${name}.srt`;
    case 'vtt': return `surah_${num}_${name}.vtt`;
    case 'ass': return `surah_${num}_${name}_karaoke.ass`;
    case 'qurancaption': return `surah_${num}_${name}_qurancaption.json`;
    case 'csv': return `surah_${num}_${name}_word_timings.csv`;
    case 'premiere': return `surah_${num}_${name}_markers.csv`;
  }
});

const downloadButtonLabel = computed(() => {
  if (isExporting.value) return 'Generating Archive...';
  return `Download ${currentFilename.value}`;
});

function open() {
  visible.value = true;
  if (totalSurahsCount.value > 1 && !projectStore.activeSurah.value) {
    exportScope.value = 'all';
  }
  generatePreview();
}

function close() {
  visible.value = false;
}

function setExportScope(scope: 'current' | 'all') {
  exportScope.value = scope;
  generatePreview();
}

function setAllSurahsMode(mode: 'combined' | 'zip') {
  allSurahsMode.value = mode;
  generatePreview();
}

function selectFormat(fmtId: ExportFormatId) {
  selectedFormat.value = fmtId;
  generatePreview();
}

function generatePreview() {
  if (exportScope.value === 'all') {
    if (allSurahsMode.value === 'zip') {
      const fileList = projectStore.project.surahs.map((s, idx) => {
        const num = String(s.surah_number).padStart(3, '0');
        const ext = selectedFormat.value === 'qurancaption' ? 'json' : selectedFormat.value;
        return `  ${idx + 1}. ${num}_${sanitizeBatchExportFileName(s.surah_name_english)}.${ext}`;
      }).join('\n');
      previewContent.value = `// ZIP ARCHIVE PACKAGE CONTENTS:\n\n${fileList}\n  + project_specification.qproj\n\nClick Download to package all ${totalSurahsCount.value} Surahs into a ready-to-use ZIP file.`;
      return;
    }

    // All Surahs Combined Preview
    switch (selectedFormat.value) {
      case 'json':
        previewContent.value = exportAllCanonicalJson(projectStore.project);
        break;
      case 'qproj':
        previewContent.value = exportProjectFile(projectStore.project);
        break;
      case 'srt':
        previewContent.value = exportAllSrt(projectStore.project, srtWordLevel.value);
        break;
      case 'vtt':
        previewContent.value = exportAllVtt(projectStore.project);
        break;
      case 'ass':
        previewContent.value = exportAllAssKaraoke(projectStore.project);
        break;
      case 'qurancaption':
        previewContent.value = exportAllQuranCaption(projectStore.project);
        break;
      case 'csv':
        previewContent.value = exportAllWordTimingsCsv(projectStore.project);
        break;
      case 'premiere':
        previewContent.value = exportAllPremiereMarkers(projectStore.project);
        break;
    }
    return;
  }

  // Single Surah Preview
  const surah = projectStore.activeSurah.value;
  if (!surah) {
    previewContent.value = '// No active Surah loaded. Select a Surah or switch to "All Surahs" tab.';
    return;
  }

  switch (selectedFormat.value) {
    case 'json':
      previewContent.value = exportCanonicalJson(surah);
      break;
    case 'qproj':
      previewContent.value = exportProjectFile(projectStore.project);
      break;
    case 'srt':
      previewContent.value = exportSrt(surah, srtWordLevel.value);
      break;
    case 'vtt':
      previewContent.value = exportVtt(surah);
      break;
    case 'ass':
      previewContent.value = exportAssKaraoke(surah);
      break;
    case 'qurancaption':
      previewContent.value = exportQuranCaption(surah);
      break;
    case 'csv':
      previewContent.value = exportWordTimingsCsv(surah);
      break;
    case 'premiere':
      previewContent.value = exportPremiereMarkers(surah);
      break;
  }
}

async function handleDownload() {
  if (isExporting.value) return;

  if (exportScope.value === 'all' && allSurahsMode.value === 'zip') {
    isExporting.value = true;
    try {
      const zipBlob = await exportSurahsAsZip(
        projectStore.project, 
        selectedFormat.value, 
        srtWordLevel.value
      );
      downloadBlob(zipBlob, currentFilename.value);
      close();
    } catch (err) {
      console.error('Failed to create ZIP export:', err);
    } finally {
      isExporting.value = false;
    }
    return;
  }

  // Single File Download (Current or Combined)
  let mime = 'application/json';
  if (['srt', 'vtt', 'ass'].includes(selectedFormat.value)) {
    mime = 'text/plain';
  } else if (['csv', 'premiere'].includes(selectedFormat.value)) {
    mime = 'text/csv';
  }

  // Portable .qproj: embed reachable audio so the file is self-contained
  if (selectedFormat.value === 'qproj') {
    isExporting.value = true;
    try {
      const portable = await buildPortableProject(projectStore.project);
      downloadFile(exportProjectFile(portable), currentFilename.value, mime);
      close();
    } catch (err) {
      console.error('Failed to create portable project export:', err);
    } finally {
      isExporting.value = false;
    }
    return;
  }

  downloadFile(previewContent.value, currentFilename.value, mime);
  close();
}

function copyToClipboard() {
  navigator.clipboard.writeText(previewContent.value);
  copied.value = true;
  setTimeout(() => { copied.value = false; }, 2000);
}

defineExpose({
  open,
  close,
});

function handleKeydown(e: KeyboardEvent) {
  if (visible.value && e.key === 'Escape') close();
}
onMounted(() => window.addEventListener('keydown', handleKeydown));
onUnmounted(() => window.removeEventListener('keydown', handleKeydown));
</script>

<style scoped>
.modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(5, 6, 10, 0.68);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
  animation: fade-in var(--dur-fast) var(--ease-out);
}

.export-modal {
  width: 900px;
  max-width: 95vw;
  max-height: 90vh;
  display: flex;
  flex-direction: column;
  background: var(--bg-surface);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-e3);
  overflow: hidden;
  animation: scale-up var(--dur-rise) var(--ease-spring);
}

.modal-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 18px;
  border-bottom: 1px solid var(--border-subtle);
  background: var(--bg-surface-elevated);
}

.header-left {
  display: flex;
  align-items: center;
  gap: 10px;
}

.header-titles {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.modal-title {
  margin: 0;
  font-size: 14px;
  font-weight: 700;
  color: var(--text-main);
}

.modal-subtitle {
  font-size: 11px;
  color: var(--text-muted);
}

/* Scope Tabs Bar */
.scope-tabs-bar {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 18px;
  background: var(--bg-input);
  border-bottom: 1px solid var(--border-subtle);
}

.scope-tab-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 12px;
  border-radius: var(--radius-pill);
  border: 1px solid transparent;
  background: transparent;
  color: var(--text-muted);
  font-size: 11.5px;
  font-weight: 500;
  cursor: pointer;
  transition: all var(--dur-fast) var(--ease-out);
}

.scope-tab-btn:hover:not(:disabled) {
  color: var(--text-main);
  background: var(--bg-surface-elevated);
}

.scope-tab-btn.active {
  background: var(--bg-surface-elevated);
  color: var(--accent-hover);
  border-color: var(--accent-border);
  font-weight: 600;
}

.scope-tab-btn:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

/* All Surahs Banner */
.all-surahs-banner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 18px;
  background: var(--accent-subtle);
  border-bottom: 1px solid var(--accent-border);
}

.project-stats-pill {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: var(--text-main);
}

.stat-item strong {
  color: var(--accent-hover);
}

.stat-dot {
  color: var(--text-muted);
}

.batch-mode-toggle {
  display: flex;
  align-items: center;
  gap: 4px;
  background: var(--bg-surface);
  padding: 3px;
  border-radius: var(--radius-pill);
  border: 1px solid var(--border-subtle);
}

.mode-pill-btn {
  display: flex;
  align-items: center;
  gap: 5px;
  padding: 3px 10px;
  border-radius: var(--radius-pill);
  border: none;
  background: transparent;
  color: var(--text-muted);
  font-size: 11px;
  cursor: pointer;
  transition: all var(--dur-fast) var(--ease-out);
}

.mode-pill-btn:hover {
  color: var(--text-main);
}

.mode-pill-btn.active {
  background: var(--accent-primary);
  color: #ffffff;
  font-weight: 600;
}

.modal-body {
  padding: 16px 18px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 12px;
  flex: 1;
}

/* Format Cards Grid */
.format-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 8px;
}

@media (max-width: 800px) {
  .format-grid {
    grid-template-columns: repeat(2, 1fr);
  }
}

.format-card {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  padding: 10px 12px;
  background: var(--bg-surface);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-sm);
  cursor: pointer;
  text-align: left;
  transition: all var(--dur-fast) var(--ease-out);
}

.format-card:hover {
  border-color: var(--border-medium);
  background: var(--bg-surface-elevated);
}

.format-card.selected {
  border-color: var(--accent-primary);
  background: var(--accent-subtle);
  box-shadow: 0 0 0 1px var(--accent-border);
}

.format-card-top {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 4px;
}

.fmt-ext {
  font-family: var(--font-mono);
  font-weight: 700;
  font-size: 11px;
  color: var(--accent-hover);
}

.fmt-badge {
  font-size: 9px;
  padding: 1px 5px;
  background: var(--bg-input);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-xs);
  color: var(--text-muted);
}

.fmt-title {
  font-size: 11.5px;
  font-weight: 600;
  color: var(--text-main);
  margin-bottom: 2px;
}

.fmt-desc {
  margin: 0;
  font-size: 10.5px;
  color: var(--text-muted);
  line-height: 1.35;
}

.format-options {
  padding: 8px 12px;
  background: var(--bg-surface-elevated);
  border-radius: var(--radius-sm);
  border: 1px solid var(--border-subtle);
}

.toggle-label {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: var(--text-main);
  cursor: pointer;
}

/* Preview Area */
.preview-section {
  display: flex;
  flex-direction: column;
  background: var(--bg-input);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-sm);
  overflow: hidden;
  height: 200px;
}

.preview-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 6px 12px;
  background: var(--bg-surface-elevated);
  border-bottom: 1px solid var(--border-subtle);
}

.preview-title {
  font-size: 10px;
  font-family: var(--font-mono);
  font-weight: 600;
  color: var(--text-muted);
  letter-spacing: 0.05em;
  text-transform: uppercase;
}

.preview-zip-badge {
  font-size: 10px;
  color: var(--accent-hover);
  font-weight: 500;
}

.copy-btn {
  display: flex;
  align-items: center;
  gap: 4px;
  background: transparent;
  border: 1px solid var(--border-subtle);
  color: var(--text-muted);
  font-size: 10px;
  cursor: pointer;
  padding: 2px 8px;
  border-radius: var(--radius-pill);
  transition: all var(--dur-fast) var(--ease-out);
}

.copy-btn:hover {
  color: var(--text-main);
  background: var(--bg-surface);
  border-color: var(--border-medium);
}

.preview-content {
  margin: 0;
  padding: 10px 12px;
  font-family: var(--font-mono);
  font-size: 11px;
  line-height: 1.45;
  color: var(--text-main);
  overflow: auto;
  white-space: pre;
  flex: 1;
}

/* Modal Footer */
.modal-footer {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 10px;
  padding: 12px 18px;
  border-top: 1px solid var(--border-subtle);
  background: var(--bg-surface-elevated);
}

@keyframes fade-in {
  from { opacity: 0; }
  to { opacity: 1; }
}

@keyframes scale-up {
  from { transform: scale(0.97); opacity: 0; }
  to { transform: scale(1); opacity: 1; }
}
</style>
