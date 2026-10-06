<template>
  <div v-if="visible" class="modal-overlay" @click.self="close">
    <div class="export-modal glass-panel">
      <!-- Modal Header -->
      <div class="modal-header">
        <div class="header-left">
          <Download :size="16" class="text-accent" />
          <h3 class="modal-title">Export Subtitles & Production Data</h3>
        </div>
        <button class="btn-icon" @click="close">
          <X :size="16" />
        </button>
      </div>

      <!-- Format Selection Grid -->
      <div class="modal-body">
        <div class="format-grid">
          <button 
            v-for="fmt in formats" 
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
              PREVIEW ({{ selectedFormat.toUpperCase() }} — Surah {{ projectStore.activeSurah.value?.surah_name_english }})
            </span>
            <button class="copy-btn" @click="copyToClipboard">
              <Copy :size="12" />
              <span>{{ copied ? 'Copied!' : 'Copy to Clipboard' }}</span>
            </button>
          </div>
          <pre class="preview-content">{{ previewContent }}</pre>
        </div>
      </div>

      <!-- Modal Footer -->
      <div class="modal-footer">
        <button class="btn-secondary" @click="close">Cancel</button>
        <button class="btn-primary" @click="handleDownload">
          <Download :size="15" />
          <span>Download {{ currentFilename }}</span>
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
  downloadFile 
} from '../services/exporters';
import { Download, X, Copy } from 'lucide-vue-next';

const visible = ref(false);
const selectedFormat = ref<'json' | 'qproj' | 'srt' | 'vtt' | 'ass' | 'qurancaption'>('json');
const srtWordLevel = ref(false);
const previewContent = ref('');
const copied = ref(false);

const formats = [
  {
    id: 'json',
    ext: '.JSON',
    badge: 'Canonical',
    title: 'output.json',
    description: 'Canonical Medina Mushaf hierarchy matching pipeline output exactly.',
  },
  {
    id: 'qproj',
    ext: '.QPROJ',
    badge: 'Studio Project',
    title: 'Quran Studio Project',
    description: 'Complete project file with all boundary edits, verified states, and metadata.',
  },
  {
    id: 'srt',
    ext: '.SRT',
    badge: 'Universal',
    title: 'Universal Subtitles',
    description: 'SubRip format for YouTube, VLC, Premiere Pro, and DaVinci Resolve.',
  },
  {
    id: 'vtt',
    ext: '.VTT',
    badge: 'Web Standard',
    title: 'WebVTT Subtitles',
    description: 'HTML5 video subtitle track format with high browser compatibility.',
  },
  {
    id: 'ass',
    ext: '.ASS',
    badge: 'Karaoke Timings',
    title: 'Word-by-Word Karaoke',
    description: 'SubStation Alpha with \\k centisecond tags for animated video titles.',
  },
  {
    id: 'qurancaption',
    ext: '.JSON',
    badge: 'Video Tool',
    title: 'QuranCaption Format',
    description: 'Direct 1-click import into QuranCaption video creator.',
  },
];

const currentFilename = computed(() => {
  const s = projectStore.activeSurah.value;
  const num = s ? String(s.surah_number).padStart(3, '0') : '001';
  switch (selectedFormat.value) {
    case 'json': return `surah_${num}_output.json`;
    case 'qproj': return `${(projectStore.project.project_name || 'quran_project').replace(/\s+/g, '_')}.qproj`;
    case 'srt': return `surah_${num}.srt`;
    case 'vtt': return `surah_${num}.vtt`;
    case 'ass': return `surah_${num}_karaoke.ass`;
    case 'qurancaption': return `surah_${num}_qurancaption.json`;
  }
});

function open() {
  visible.value = true;
  generatePreview();
}

function close() {
  visible.value = false;
}

function selectFormat(fmtId: any) {
  selectedFormat.value = fmtId;
  generatePreview();
}

function generatePreview() {
  const surah = projectStore.activeSurah.value;
  if (!surah) {
    previewContent.value = '// No active Surah loaded';
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
  }
}

function handleDownload() {
  let mime = 'application/json';
  if (selectedFormat.value === 'srt' || selectedFormat.value === 'vtt' || selectedFormat.value === 'ass') {
    mime = 'text/plain';
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

@keyframes fade-in {
  from { opacity: 0; }
  to { opacity: 1; }
}

.export-modal {
  width: 820px;
  max-width: 95vw;
  max-height: 90vh;
  display: flex;
  flex-direction: column;
  background: var(--bg-surface);
  border: 1px solid var(--border-medium);
  border-radius: 8px;
  box-shadow: var(--shadow-modal);
  overflow: hidden;
}

.modal-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 20px;
  border-bottom: 1px solid var(--border-subtle);
}
.header-left {
  display: flex;
  align-items: center;
  gap: 10px;
}
.modal-title {
  margin: 0;
  font-size: 1.1rem;
  font-weight: 600;
  color: #fff;
}

.modal-body {
  flex: 1;
  overflow-y: auto;
  padding: 20px;
}

.format-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 10px;
  margin-bottom: 14px;
}

.format-card {
  background: var(--bg-surface-elevated);
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  padding: 10px 12px;
  text-align: left;
  cursor: pointer;
  transition: all 0.15s ease;
}
.format-card:hover {
  border-color: rgba(255, 255, 255, 0.3);
  background: var(--bg-surface-hover);
}
.format-card.selected {
  background: var(--accent-subtle);
  border-color: var(--accent-primary);
  box-shadow: none;
}

.format-card-top {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 4px;
}
.fmt-ext {
  font-family: var(--font-mono);
  font-weight: 600;
  font-size: 0.8rem;
  color: var(--accent-primary);
}
.fmt-badge {
  font-size: 0.65rem;
  font-weight: 600;
  background: rgba(255, 255, 255, 0.08);
  padding: 1px 5px;
  border-radius: 4px;
  color: var(--text-dim);
}
.fmt-title {
  font-size: 0.85rem;
  font-weight: 600;
  color: #fff;
  display: block;
}
.fmt-desc {
  font-size: 0.72rem;
  color: var(--text-muted);
  margin: 4px 0 0;
  line-height: 1.3;
}

.format-options {
  margin-bottom: 12px;
  padding: 8px 12px;
  background: var(--bg-base);
  border-radius: 6px;
  border: 1px solid var(--border-subtle);
}
.toggle-label {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 0.78rem;
  color: var(--text-muted);
  cursor: pointer;
}

.preview-section {
  background: var(--bg-base);
  border: 1px solid var(--border-subtle);
  border-radius: 6px;
  overflow: hidden;
}
.preview-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 12px;
  background: var(--bg-surface-elevated);
  border-bottom: 1px solid var(--border-subtle);
}
.preview-title {
  font-size: 0.7rem;
  font-family: var(--font-mono);
  color: var(--text-dim);
  font-weight: 600;
}
.copy-btn {
  display: flex;
  align-items: center;
  gap: 4px;
  background: transparent;
  border: 1px solid var(--border-subtle);
  color: var(--text-muted);
  border-radius: 4px;
  padding: 3px 8px;
  font-size: 0.7rem;
  cursor: pointer;
}
.copy-btn:hover {
  color: #fff;
  background: var(--bg-surface-elevated);
}

.preview-content {
  margin: 0;
  padding: 12px;
  max-height: 220px;
  overflow-y: auto;
  font-family: var(--font-mono);
  font-size: 0.75rem;
  line-height: 1.5;
  color: #cbd5e1;
}

.modal-footer {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  padding: 14px 20px;
  border-top: 1px solid var(--border-subtle);
  background: var(--bg-base);
}
</style>
