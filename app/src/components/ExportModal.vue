<template>
  <div v-if="visible" class="modal-overlay" @click.self="close">
    <div class="export-modal glass-panel">
      <!-- Modal Header -->
      <div class="modal-header">
        <div class="header-left">
          <Download :size="18" class="text-accent" />
          <div class="header-titles">
            <h3 class="modal-title">Export Subtitles & Production Data</h3>
            <span class="modal-subtitle">Export synchronized recitation timings in industry-standard formats</span>
          </div>
        </div>
        <button class="btn-icon" @click="close" title="Close">
          <X :size="16" />
        </button>
      </div>

      <!-- Scope Selector Tabs: Current Surah vs All Surahs -->
      <div class="scope-tabs-bar">
        <button 
          class="scope-tab-btn" 
          :class="{ 'active': exportScope === 'current' }"
          @click="setExportScope('current')"
        >
          <FileText :size="14" />
          <span>Current Surah ({{ projectStore.activeSurah.value?.surah_name_english || 'Active' }})</span>
        </button>
        <button 
          class="scope-tab-btn" 
          :class="{ 'active': exportScope === 'all' }"
          @click="setExportScope('all')"
          :disabled="totalSurahsCount <= 1"
          :title="totalSurahsCount <= 1 ? 'Add more surahs to export in batch' : 'Export all project surahs'"
        >
          <Layers :size="14" />
          <span>All Surahs in Project ({{ totalSurahsCount }} {{ totalSurahsCount === 1 ? 'Surah' : 'Surahs' }})</span>
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
import { ref, computed } from 'vue';
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
      title: 'Canonical output.json',
      description: 'Canonical Medina Mushaf hierarchy matching pipeline output specification.',
    },
    {
      id: 'srt' as ExportFormatId,
      ext: '.SRT',
      badge: 'Universal',
      title: 'Universal Subtitles',
      description: 'SubRip format for YouTube, VLC, Premiere Pro, and DaVinci Resolve.',
    },
    {
      id: 'vtt' as ExportFormatId,
      ext: '.VTT',
      badge: 'Web Standard',
      title: 'WebVTT Subtitles',
      description: 'HTML5 video subtitle track format with high web browser compatibility.',
    },
    {
      id: 'ass' as ExportFormatId,
      ext: '.ASS',
      badge: 'Karaoke Timings',
      title: 'Word Karaoke Subtitles',
      description: 'SubStation Alpha with \\k centisecond tags for animated video titles.',
    },
    {
      id: 'qurancaption' as ExportFormatId,
      ext: '.JSON',
      badge: 'Video Tool',
      title: 'QuranCaption Format',
      description: 'Direct 1-click import into QuranCaption video creator timeline.',
    },
    {
      id: 'csv' as ExportFormatId,
      ext: '.CSV',
      badge: 'Data & Excel',
      title: 'Word Timings CSV',
      description: 'Structured spreadsheet table with millisecond durations and confidence scores.',
    },
    {
      id: 'premiere' as ExportFormatId,
      ext: '.CSV',
      badge: 'NLE Markers',
      title: 'Premiere / DaVinci Markers',
      description: 'Timeline markers CSV ready to drag directly into video editing sequences.',
    },
    {
      id: 'qproj' as ExportFormatId,
      ext: '.QPROJ',
      badge: 'Studio Project',
      title: 'Quran Studio Project',
      description: 'Complete project specification with all boundary edits, history, and metadata.',
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
</script>

<style scoped>
.modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.72);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
  animation: fade-in 0.15s ease-out;
}

.export-modal {
  width: 900px;
  max-width: 95vw;
  max-height: 90vh;
  display: flex;
  flex-direction: column;
  background: var(--bg-surface);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-xl);
  box-shadow: var(--shadow-2xl);
  overflow: hidden;
  animation: scale-up 0.2s cubic-bezier(0.16, 1, 0.3, 1);
}

.modal-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 1rem 1.25rem;
  border-bottom: 1px solid var(--border-color);
  background: var(--bg-card);
}

.header-left {
  display: flex;
  align-items: center;
  gap: 0.75rem;
}

.header-titles {
  display: flex;
  flex-direction: column;
  gap: 0.15rem;
}

.modal-title {
  margin: 0;
  font-size: 0.95rem;
  font-weight: 700;
  color: var(--text-main);
}

.modal-subtitle {
  font-size: 0.75rem;
  color: var(--text-muted);
}

/* Scope Tabs Bar */
.scope-tabs-bar {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.65rem 1.25rem;
  background: var(--bg-hover);
  border-bottom: 1px solid var(--border-color);
}

.scope-tab-btn {
  display: flex;
  align-items: center;
  gap: 0.45rem;
  padding: 0.4rem 0.85rem;
  border-radius: var(--radius-md);
  border: 1px solid transparent;
  background: transparent;
  color: var(--text-muted);
  font-size: 0.78rem;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.15s ease;
}

.scope-tab-btn:hover:not(:disabled) {
  color: var(--text-main);
  background: var(--bg-surface);
}

.scope-tab-btn.active {
  background: var(--bg-card);
  color: var(--accent);
  border-color: var(--border-color);
  font-weight: 600;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.15);
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
  padding: 0.55rem 1.25rem;
  background: rgba(94, 106, 210, 0.08);
  border-bottom: 1px solid rgba(94, 106, 210, 0.15);
}

.project-stats-pill {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 0.76rem;
  color: var(--text-main);
}

.stat-item strong {
  color: var(--accent);
}

.stat-dot {
  color: var(--text-muted);
}

.batch-mode-toggle {
  display: flex;
  align-items: center;
  gap: 0.35rem;
  background: var(--bg-card);
  padding: 0.2rem;
  border-radius: var(--radius-md);
  border: 1px solid var(--border-color);
}

.mode-pill-btn {
  display: flex;
  align-items: center;
  gap: 0.35rem;
  padding: 0.25rem 0.6rem;
  border-radius: var(--radius-sm);
  border: none;
  background: transparent;
  color: var(--text-muted);
  font-size: 0.72rem;
  cursor: pointer;
  transition: all 0.15s;
}

.mode-pill-btn:hover {
  color: var(--text-main);
}

.mode-pill-btn.active {
  background: var(--accent);
  color: #ffffff;
  font-weight: 600;
}

.modal-body {
  padding: 1rem 1.25rem;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 0.85rem;
  flex: 1;
}

/* Format Cards Grid */
.format-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 0.55rem;
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
  padding: 0.65rem 0.75rem;
  background: var(--bg-card);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-md);
  cursor: pointer;
  text-align: left;
  transition: all 0.15s ease;
}

.format-card:hover {
  border-color: var(--border-focus);
  background: var(--bg-hover);
}

.format-card.selected {
  border-color: var(--accent);
  background: rgba(94, 106, 210, 0.08);
  box-shadow: 0 0 0 1px var(--accent);
}

.format-card-top {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 0.35rem;
}

.fmt-ext {
  font-family: monospace;
  font-weight: 700;
  font-size: 0.78rem;
  color: var(--accent);
}

.fmt-badge {
  font-size: 0.62rem;
  padding: 0.12rem 0.35rem;
  background: var(--bg-surface);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-sm);
  color: var(--text-muted);
}

.fmt-title {
  font-size: 0.76rem;
  font-weight: 600;
  color: var(--text-main);
  margin-bottom: 0.2rem;
}

.fmt-desc {
  margin: 0;
  font-size: 0.68rem;
  color: var(--text-muted);
  line-height: 1.3;
}

.format-options {
  padding: 0.55rem 0.85rem;
  background: var(--bg-hover);
  border-radius: var(--radius-md);
  border: 1px solid var(--border-color);
}

.toggle-label {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 0.75rem;
  color: var(--text-main);
  cursor: pointer;
}

/* Preview Area */
.preview-section {
  display: flex;
  flex-direction: column;
  background: #090c10;
  border: 1px solid var(--border-color);
  border-radius: var(--radius-md);
  overflow: hidden;
  height: 220px;
}

.preview-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.4rem 0.75rem;
  background: #161b22;
  border-bottom: 1px solid var(--border-color);
}

.preview-title {
  font-size: 0.68rem;
  font-family: monospace;
  font-weight: 600;
  color: var(--text-muted);
  text-transform: uppercase;
}

.preview-zip-badge {
  font-size: 0.68rem;
  color: var(--accent);
  font-weight: 500;
}

.copy-btn {
  display: flex;
  align-items: center;
  gap: 0.35rem;
  background: transparent;
  border: none;
  color: var(--text-muted);
  font-size: 0.68rem;
  cursor: pointer;
  padding: 0.15rem 0.4rem;
  border-radius: var(--radius-sm);
}

.copy-btn:hover {
  color: var(--text-main);
  background: rgba(255, 255, 255, 0.08);
}

.preview-content {
  margin: 0;
  padding: 0.75rem;
  font-family: 'Consolas', 'Monaco', monospace;
  font-size: 0.72rem;
  line-height: 1.4;
  color: #e6edf3;
  overflow: auto;
  white-space: pre;
  flex: 1;
}

/* Modal Footer */
.modal-footer {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 0.75rem;
  padding: 0.85rem 1.25rem;
  border-top: 1px solid var(--border-color);
  background: var(--bg-card);
}

@keyframes fade-in {
  from { opacity: 0; }
  to { opacity: 1; }
}

@keyframes scale-up {
  from { transform: scale(0.96); opacity: 0; }
  to { transform: scale(1); opacity: 1; }
}
</style>
