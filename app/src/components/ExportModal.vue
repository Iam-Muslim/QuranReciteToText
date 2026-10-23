<template>
  <div v-if="visible" class="modal-overlay" @click.self="close">
    <div class="export-modal glass-panel anim-scale">
      <!-- Modal Header -->
      <div class="modal-header">
        <div class="header-left">
          <div class="header-icon-orb">
            <UploadCloud v-if="activeMainTab === 'upload'" :size="18" class="text-accent" />
            <Download v-else :size="18" class="text-accent" />
          </div>
          <div class="header-titles">
            <h3 class="modal-title">Export & Cloud Publishing</h3>
            <span class="modal-subtitle">Generate Medina timing JSON or publish directly to Hugging Face</span>
          </div>
        </div>
        <button class="btn-icon" @click="close" title="Close">
          <X :size="15" />
        </button>
      </div>

      <!-- Main Mode Switcher: Download JSON vs Upload to Hugging Face -->
      <div class="main-mode-tabs">
        <button 
          class="main-mode-tab" 
          :class="{ 'active': activeMainTab === 'download' }"
          @click="activeMainTab = 'download'"
        >
          <Download :size="14" />
          <span>Download JSON Files</span>
        </button>
        <button 
          class="main-mode-tab" 
          :class="{ 'active': activeMainTab === 'upload' }"
          @click="activeMainTab = 'upload'; resetUploadState()"
        >
          <Cloud :size="14" />
          <span>Upload to Hugging Face</span>
          <span v-if="isCloudOrigin" class="tab-badge-synced">Synced</span>
        </button>
      </div>

      <!-- ══════════════════════════════════════════════ -->
      <!-- TAB 1: DOWNLOAD JSON FILES                     -->
      <!-- ══════════════════════════════════════════════ -->
      <div v-if="activeMainTab === 'download'" class="tab-content-wrap">
        <!-- Scope Selector: Current Surah vs Whole Project -->
        <div class="scope-tabs-bar">
          <button 
            class="scope-tab-btn" 
            :class="{ 'active': exportScope === 'current' }"
            @click="setExportScope('current')"
          >
            <FileText :size="13" />
            <span>Current Surah ({{ projectStore.activeSurah.value ? `${projectStore.activeSurah.value.surah_name_english} · ${projectStore.activeSurah.value.surah_name_arabic}` : 'Active' }})</span>
          </button>
          <button 
            class="scope-tab-btn" 
            :class="{ 'active': exportScope === 'all' }"
            @click="setExportScope('all')"
          >
            <Layers :size="13" />
            <span>Whole Project ({{ totalSurahsCount }} {{ totalSurahsCount === 1 ? 'Surah' : 'Surahs' }})</span>
          </button>
        </div>

        <!-- Whole Project Package Mode Switcher -->
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
              title="Combined single JSON file with all project surahs"
            >
              <FileSpreadsheet :size="13" />
              <span>Combined Project JSON</span>
            </button>
            <button 
              class="mode-pill-btn" 
              :class="{ 'active': allSurahsMode === 'zip' }"
              @click="setAllSurahsMode('zip')"
              title="ZIP archive with separate JSON for each surah and projects.json manifest"
            >
              <Archive :size="13" />
              <span>Dataset ZIP Archive</span>
            </button>
          </div>
        </div>

        <div class="modal-body">
          <!-- Preview Box -->
          <div class="preview-section">
            <div class="preview-header">
              <span class="preview-title">
                PREVIEW: {{ previewScopeLabel }}
              </span>
              <div class="preview-actions">
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
                  ZIP contains {{ totalSurahsCount }} Surah JSON files + projects.json manifest
                </span>
              </div>
            </div>
            <pre class="preview-content">{{ previewContent }}</pre>
          </div>
        </div>

        <!-- Footer -->
        <div class="modal-footer">
          <button class="btn btn-secondary" @click="close" :disabled="isExporting">Cancel</button>
          <button class="btn btn-primary" @click="handleDownload" :disabled="isExporting">
            <Loader2 v-if="isExporting" :size="15" class="animate-spin" />
            <Download v-else :size="15" />
            <span>{{ downloadButtonLabel }}</span>
          </button>
        </div>
      </div>

      <!-- ══════════════════════════════════════════════ -->
      <!-- TAB 2: UPLOAD DIRECTLY TO HUGGING FACE CLOUD   -->
      <!-- ══════════════════════════════════════════════ -->
      <div v-else class="tab-content-wrap upload-tab-wrap">
        <div class="upload-scrollable-body">
          <!-- 1. Destination Repository Banner -->
          <div class="hf-destination-card">
            <div class="hf-card-left">
              <span class="hf-emoji" style="font-size: 22px;">🤗</span>
              <div class="hf-dest-info">
                <span class="hf-dest-label">Target Dataset Repository:</span>
                <div class="hf-repo-row">
                  <a :href="`https://huggingface.co/datasets/${currentHfRepo}`" target="_blank" rel="noopener" class="hf-repo-link">
                    <span>{{ currentHfRepo }}</span>
                    <ExternalLink :size="11" />
                  </a>
                </div>
              </div>
            </div>

            <div class="hf-card-right">
              <div v-if="hasWriteToken" class="token-status-pill token-active">
                <ShieldCheck :size="12" />
                <span>Write Token Configured</span>
              </div>
              <div v-else class="token-status-pill token-missing">
                <ShieldAlert :size="12" />
                <span>Token Required</span>
              </div>
            </div>
          </div>

          <!-- Token Input (if missing or editing) -->
          <div v-if="!hasWriteToken || showTokenInput" class="token-input-card anim-rise">
            <div class="token-card-header">
              <span class="token-card-title">Hugging Face Access Token (Write Permission)</span>
              <button class="btn-text-sm" @click="showTokenInput = false" v-if="hasWriteToken">Hide</button>
            </div>
            <div class="token-input-row">
              <input 
                type="password" 
                v-model="tokenInputValue" 
                placeholder="hf_xxxxxxxxxxxxxxxxxxxxxxxx (must have Write role)"
                class="token-input"
              />
              <button class="btn btn-secondary btn-sm" @click="saveToken">Save Token</button>
            </div>
            <small class="token-hint">
              Get or create a Write token at <a href="https://huggingface.co/settings/tokens" target="_blank" rel="noopener">huggingface.co/settings/tokens</a>.
            </small>
          </div>

          <!-- 2. Project Cloud Identity Card -->
          <div class="project-identity-card">
            <div class="identity-header">
              <div>
                <span class="identity-label">Project / Reciter:</span>
                <h4 class="identity-name">{{ projectStore.project.project_name }}</h4>
              </div>

              <!-- Cloud Origin Badge -->
              <div v-if="isCloudOrigin" class="cloud-badge badge-synced" title="Imported from Cloud — updates will overwrite">
                <Cloud :size="12" />
                <span>Cloud Synced Project</span>
              </div>
              <div v-else class="cloud-badge badge-new" title="New local project — will not overwrite existing projects">
                <Plus :size="12" />
                <span>New Local Project</span>
              </div>
            </div>

            <div class="identity-meta-grid">
              <div class="identity-meta-item">
                <span class="meta-name">Reciter</span>
                <span class="meta-val">{{ projectStore.project.reciter || projectStore.project.settings?.reciter_name || 'Reciter' }}</span>
              </div>
              <div class="identity-meta-item">
                <span class="meta-name">Riwayah</span>
                <span class="meta-val">{{ projectStore.project.settings?.riwayah || 'Hafs' }}</span>
              </div>
              <div class="identity-meta-item">
                <span class="meta-name">Destination Folder</span>
                <span class="meta-val font-mono">{{ proposedTargetFolder }}</span>
              </div>
              <div class="identity-meta-item">
                <span class="meta-name">Total Surahs</span>
                <span class="meta-val">{{ totalSurahsCount }}</span>
              </div>
            </div>

            <!-- Overwrite / Sync Behavior Notice -->
            <div class="identity-behavior-note" :class="{ 'note-synced': isCloudOrigin, 'note-new': !isCloudOrigin }">
              <span v-if="isCloudOrigin">
                🔄 <strong>Cloud Update:</strong> This project originated from <code>{{ proposedTargetFolder }}</code>. Uploading will update its JSON files in the dataset.
              </span>
              <span v-else>
                🛡️ <strong>Safe Upload:</strong> This is a local project. The app checks for duplicates to prevent overwriting existing dataset files.
              </span>
            </div>
          </div>

          <!-- 3. Optional Audio Upload Card -->
          <div class="audio-upload-config-card">
            <div class="audio-config-header">
              <div class="audio-config-label">
                <Music :size="16" class="text-accent" />
                <div>
                  <div class="audio-config-title">Include Audio Recitations (.mp3)</div>
                  <div class="audio-config-desc">
                    <span v-if="isCloudOrigin">
                      Audio is already hosted in the dataset. Timings-only upload is fastest (1-2s).
                    </span>
                    <span v-else-if="audioReachableCount > 0">
                      Uploads audio files into <code>{{ proposedTargetFolder }}/audio/</code> so anyone can stream your recitations.
                    </span>
                    <span v-else class="text-muted">
                      No local audio files detected in this session. Timings JSON will be uploaded.
                    </span>
                  </div>
                </div>
              </div>

              <label class="switch-toggle" v-if="audioReachableCount > 0 || isCloudOrigin">
                <input type="checkbox" v-model="includeAudioUpload" :disabled="isUploading" />
                <span class="slider"></span>
              </label>
            </div>

            <div v-if="includeAudioUpload && audioReachableCount > 0" class="audio-stats-pill">
              <span class="badge-dot"></span>
              <span>{{ audioReachableCount }}/{{ totalSurahsCount }} audio files ready (~{{ formatTotalAudioSize }})</span>
            </div>
          </div>

          <!-- 4. Collision Detected Resolution Card -->
          <div v-if="collisionDetected" class="collision-card anim-rise">
            <div class="collision-header">
              <AlertTriangle :size="18" class="text-warning" />
              <div>
                <h4 class="collision-title">Folder Name Already Exists</h4>
                <p class="collision-desc">
                  A project in <code>{{ collisionFolder }}</code> already exists in <strong>{{ currentHfRepo }}</strong>.
                </p>
              </div>
            </div>

            <div class="collision-actions">
              <button class="btn btn-warning" @click="executeHfUpload(true, collisionFolder)" :disabled="isUploading">
                <span>Overwrite Existing Cloud Project</span>
              </button>
              <button class="btn btn-primary" @click="executeHfUpload(false, collisionSuggestedFolder)" :disabled="isUploading">
                <span>Upload as New Version ({{ collisionSuggestedFolder }})</span>
              </button>
            </div>
          </div>

          <!-- 5. Upload Status & Result Feedback -->
          <div v-if="uploadSuccess" class="upload-result-card result-success anim-rise">
            <div class="result-header">
              <Check :size="18" class="text-success" />
              <div>
                <h4 class="result-title">Published Successfully to Hugging Face!</h4>
                <p class="result-desc">
                  Committed {{ uploadedFilesList.length }} files to <code>{{ uploadedTargetFolder }}</code>.
                </p>
              </div>
            </div>
            <div class="result-actions">
              <a 
                :href="`https://huggingface.co/datasets/${currentHfRepo}/tree/main/${uploadedTargetFolder}`" 
                target="_blank" 
                rel="noopener" 
                class="btn btn-secondary btn-sm"
              >
                <span>View Files on Hugging Face</span>
                <ExternalLink :size="11" />
              </a>
            </div>
          </div>

          <div v-if="uploadError" class="upload-result-card result-error anim-rise">
            <AlertTriangle :size="18" class="text-danger" />
            <div class="result-body">
              <h4 class="result-title">Upload Failed</h4>
              <p class="result-desc">{{ uploadError }}</p>
            </div>
          </div>
        </div>

        <!-- Upload Footer -->
        <div class="modal-footer">
          <button class="btn btn-secondary" @click="close" :disabled="isUploading">Close</button>
          <button 
            class="btn btn-primary btn-upload-cloud" 
            @click="handleHfUploadInitiate" 
            :disabled="isUploading || totalSurahsCount === 0"
          >
            <Loader2 v-if="isUploading" :size="15" class="animate-spin" />
            <UploadCloud v-else :size="15" />
            <span>{{ isUploading ? (uploadProgressMessage || 'Committing to Hugging Face...') : (isCloudOrigin ? 'Update Cloud Dataset' : 'Publish to Hugging Face') }}</span>
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue';
import { projectStore } from '../services/projectStore';
import { 
  exportCanonicalJson, 
  exportAllCanonicalJson,
  exportSurahsAsZip,
  downloadFile,
  downloadBlob,
  sanitizeBatchExportFileName
} from '../services/exporters';
import { 
  getHfRepo, 
  getHfToken, 
  setHfToken, 
  uploadProjectToHfDataset,
  checkCloudProjectCollision,
  inspectProjectAudioReachability
} from '../services/cloudDataset';
import { 
  Download, 
  X, 
  Copy, 
  Check, 
  FileText, 
  Layers, 
  Archive, 
  FileSpreadsheet, 
  Loader2,
  Cloud,
  UploadCloud,
  ExternalLink,
  ShieldCheck,
  ShieldAlert,
  AlertTriangle,
  Plus,
  Music
} from 'lucide-vue-next';

const visible = ref(false);
const activeMainTab = ref<'download' | 'upload'>('download');

// Download State
const exportScope = ref<'current' | 'all'>('current');
const allSurahsMode = ref<'combined' | 'zip'>('combined');
const previewContent = ref('');
const copied = ref(false);
const isExporting = ref(false);

// Upload State
const currentHfRepo = ref(getHfRepo());
const currentHfToken = ref(getHfToken());
const hasWriteToken = computed(() => Boolean(currentHfToken.value && currentHfToken.value.startsWith('hf_')));
const showTokenInput = ref(false);
const tokenInputValue = ref(getHfToken());

const isUploading = ref(false);
const uploadProgressMessage = ref('');
const uploadSuccess = ref(false);
const uploadError = ref('');
const uploadedFilesList = ref<string[]>([]);
const uploadedTargetFolder = ref('');

// Audio Upload Options
const includeAudioUpload = ref(false);
const audioReachableCount = ref(0);
const audioTotalBytes = ref(0);
const formatTotalAudioSize = computed(() => {
  if (audioTotalBytes.value <= 0) return '0 MB';
  const mb = audioTotalBytes.value / (1024 * 1024);
  return `${mb.toFixed(1)} MB`;
});

const collisionDetected = ref(false);
const collisionFolder = ref('');
const collisionSuggestedFolder = ref('');

const isCloudOrigin = computed(() => {
  return Boolean(projectStore.project.settings?.cloud_origin && projectStore.project.settings?.cloud_folder);
});

const proposedTargetFolder = computed(() => {
  if (isCloudOrigin.value && projectStore.project.settings?.cloud_folder) {
    return projectStore.project.settings.cloud_folder;
  }
  const rawName = projectStore.project.reciter || projectStore.project.settings?.reciter_name || projectStore.project.project_name || 'Reciter';
  const sanitized = rawName.replace(/[^a-zA-Z0-9_\u0600-\u06FF\s-]/g, '').trim().replace(/\s+/g, '_');
  return `reciters/${sanitized || 'Reciter'}`;
});

const totalSurahsCount = computed(() => projectStore.project.surahs?.length || 0);

const totalAyahsCount = computed(() => {
  return (projectStore.project.surahs || []).reduce((sum, s) => sum + (s.ayahs?.length || 0), 0);
});

const totalWordsCount = computed(() => {
  return (projectStore.project.surahs || []).reduce((sum, s) => {
    return sum + (s.ayahs || []).reduce((aSum, a) => {
      return aSum + (a.segments || []).reduce((segSum, seg) => segSum + (seg.words?.length || 0), 0);
    }, 0);
  }, 0);
});

const previewScopeLabel = computed(() => {
  if (exportScope.value === 'current') {
    const s = projectStore.activeSurah.value;
    const num = s ? String(s.surah_number).padStart(3, '0') : '001';
    return `Single Surah (${num}.json)`;
  }
  if (allSurahsMode.value === 'zip') {
    return `ZIP Dataset Package (${totalSurahsCount.value} Surahs + projects.json)`;
  }
  return `Combined Project JSON (${totalSurahsCount.value} Surahs)`;
});

const currentFilename = computed(() => {
  const safeProj = sanitizeBatchExportFileName(projectStore.project.project_name || 'quran_project');

  if (exportScope.value === 'all') {
    if (allSurahsMode.value === 'zip') {
      return `${safeProj}_dataset_package.zip`;
    }
    return `${safeProj}_all_surahs.json`;
  }

  // Single Surah Mode
  const s = projectStore.activeSurah.value;
  const num = s ? String(s.surah_number).padStart(3, '0') : '001';
  return `${num}.json`;
});

const downloadButtonLabel = computed(() => {
  if (isExporting.value) return 'Generating Archive...';
  return `Download ${currentFilename.value}`;
});

async function open() {
  visible.value = true;
  currentHfRepo.value = getHfRepo();
  currentHfToken.value = getHfToken();
  tokenInputValue.value = getHfToken();
  resetUploadState();
  if (totalSurahsCount.value > 1 && !projectStore.activeSurah.value) {
    exportScope.value = 'all';
  }
  generatePreview();

  try {
    const audioStatus = await inspectProjectAudioReachability(projectStore.project);
    audioReachableCount.value = audioStatus.reachableCount;
    audioTotalBytes.value = audioStatus.totalBytes;
    includeAudioUpload.value = isCloudOrigin.value ? false : audioStatus.reachableCount > 0;
  } catch {
    audioReachableCount.value = 0;
    audioTotalBytes.value = 0;
    includeAudioUpload.value = false;
  }
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

function generatePreview() {
  if (exportScope.value === 'all') {
    if (allSurahsMode.value === 'zip') {
      const fileList = (projectStore.project.surahs || []).map((s, idx) => {
        const num = String(s.surah_number).padStart(3, '0');
        return `  ${idx + 1}. reciters/${proposedTargetFolder.value.replace(/^reciters\//, '')}/json/${num}.json`;
      }).join('\n');
      previewContent.value = `// DATASET ZIP PACKAGE LAYOUT:\n\n${fileList}\n  + projects.json (Manifest)\n\nClick Download to package all ${totalSurahsCount.value} Surahs into a standard dataset ZIP file (minified JSON).`;
      return;
    }

    // All Surahs Combined JSON Preview
    previewContent.value = exportAllCanonicalJson(projectStore.project);
    return;
  }

  // Single Surah Preview
  const surah = projectStore.activeSurah.value;
  if (!surah) {
    previewContent.value = '// No active Surah loaded. Select a Surah or switch to "Whole Project" tab.';
    return;
  }

  previewContent.value = exportCanonicalJson(surah);
}

async function handleDownload() {
  if (isExporting.value) return;

  if (exportScope.value === 'all' && allSurahsMode.value === 'zip') {
    isExporting.value = true;
    try {
      const zipBlob = await exportSurahsAsZip(projectStore.project, 'json');
      downloadBlob(zipBlob, currentFilename.value);
      close();
    } catch (err) {
      console.error('Failed to create ZIP export:', err);
    } finally {
      isExporting.value = false;
    }
    return;
  }

  // Single JSON File Download (Current or Combined)
  downloadFile(previewContent.value, currentFilename.value, 'application/json');
  close();
}

function copyToClipboard() {
  if (typeof navigator !== 'undefined' && navigator.clipboard) {
    navigator.clipboard.writeText(previewContent.value);
    copied.value = true;
    setTimeout(() => { copied.value = false; }, 2000);
  }
}

// ── Cloud Upload Logic ────────────────────────────────────────────────────────

function resetUploadState() {
  uploadSuccess.value = false;
  uploadError.value = '';
  collisionDetected.value = false;
  collisionFolder.value = '';
  collisionSuggestedFolder.value = '';
  uploadedFilesList.value = [];
  uploadedTargetFolder.value = '';
}

function saveToken() {
  if (tokenInputValue.value.trim()) {
    setHfToken(tokenInputValue.value.trim());
    currentHfToken.value = getHfToken();
    showTokenInput.value = false;
  }
}

async function handleHfUploadInitiate() {
  resetUploadState();

  if (!hasWriteToken.value) {
    showTokenInput.value = true;
    uploadError.value = 'Please provide a Hugging Face Write Token to publish.';
    return;
  }

  // Pre-check collision if not cloud origin
  if (!isCloudOrigin.value) {
    isUploading.value = true;
    try {
      const col = await checkCloudProjectCollision(proposedTargetFolder.value, currentHfRepo.value);
      if (col.collision) {
        isUploading.value = false;
        collisionDetected.value = true;
        collisionFolder.value = proposedTargetFolder.value;
        collisionSuggestedFolder.value = col.suggestedFolder;
        return;
      }
    } catch {
      // Continue to upload
    } finally {
      isUploading.value = false;
    }
  }

  await executeHfUpload(isCloudOrigin.value, proposedTargetFolder.value);
}

async function executeHfUpload(overwrite: boolean, folderToUse: string) {
  isUploading.value = true;
  uploadProgressMessage.value = 'Initiating upload...';
  uploadError.value = '';
  collisionDetected.value = false;

  try {
    const res = await uploadProjectToHfDataset(projectStore.project, {
      overwrite,
      targetFolder: folderToUse,
      repo: currentHfRepo.value,
      token: currentHfToken.value,
      uploadAudio: includeAudioUpload.value,
      onProgress: (status) => {
        uploadProgressMessage.value = status;
      },
    });

    if (res.success) {
      uploadSuccess.value = true;
      uploadedFilesList.value = res.uploadedFiles || [];
      uploadedTargetFolder.value = res.folder;
    } else if (res.collision) {
      collisionDetected.value = true;
      collisionFolder.value = res.folder;
      collisionSuggestedFolder.value = res.suggestedFolder || `${res.folder}_2`;
    } else {
      uploadError.value = res.error || 'Failed to upload to Hugging Face.';
    }
  } catch (err: any) {
    uploadError.value = err?.message || String(err) || 'Unexpected error during upload.';
  } finally {
    isUploading.value = false;
    uploadProgressMessage.value = '';
  }
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
  background: rgba(5, 6, 10, 0.72);
  backdrop-filter: blur(14px);
  -webkit-backdrop-filter: blur(14px);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
  animation: fade-in var(--dur-fast) var(--ease-out);
}

.export-modal {
  width: 860px;
  max-width: 95vw;
  max-height: 90vh;
  display: flex;
  flex-direction: column;
  background: var(--bg-surface);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-e3);
  overflow: hidden;
}

.modal-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 20px;
  border-bottom: 1px solid var(--border-subtle);
  background: var(--bg-surface-elevated);
}

.header-left {
  display: flex;
  align-items: center;
  gap: 12px;
}

.header-icon-orb {
  width: 34px;
  height: 34px;
  border-radius: var(--radius-md);
  background: var(--accent-subtle);
  display: flex;
  align-items: center;
  justify-content: center;
}

.header-titles {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.modal-title {
  margin: 0;
  font-size: 14.5px;
  font-weight: 700;
  color: var(--text-main);
}

.modal-subtitle {
  font-size: 11px;
  color: var(--text-muted);
}

/* Main Mode Tabs Switcher */
.main-mode-tabs {
  display: flex;
  border-bottom: 1px solid var(--border-subtle);
  background: var(--bg-input);
  padding: 6px 16px 0;
  gap: 8px;
}

.main-mode-tab {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 16px;
  font-size: 12.5px;
  font-weight: 600;
  color: var(--text-muted);
  background: transparent;
  border: none;
  border-bottom: 2px solid transparent;
  cursor: pointer;
  transition: all var(--dur-fast) var(--ease-out);
}

.main-mode-tab:hover {
  color: var(--text-main);
}

.main-mode-tab.active {
  color: var(--accent-primary);
  border-bottom-color: var(--accent-primary);
  background: var(--bg-surface);
  border-top-left-radius: var(--radius-md);
  border-top-right-radius: var(--radius-md);
}

.tab-badge-synced {
  font-size: 10px;
  background: #10b981;
  color: #ffffff;
  padding: 1px 6px;
  border-radius: var(--radius-pill);
}

.tab-content-wrap {
  display: flex;
  flex-direction: column;
  flex: 1;
  overflow: hidden;
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
  padding: 5px 12px;
  border-radius: var(--radius-md);
  background: transparent;
  border: 1px solid transparent;
  color: var(--text-muted);
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  transition: all var(--dur-fast) var(--ease-out);
}

.scope-tab-btn:hover {
  color: var(--text-main);
  background: var(--bg-surface);
}

.scope-tab-btn.active {
  color: var(--accent-primary);
  background: var(--bg-surface);
  border-color: var(--border-subtle);
  box-shadow: var(--shadow-e1);
}

/* All Surahs Banner */
.all-surahs-banner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 18px;
  background: var(--bg-surface-elevated);
  border-bottom: 1px solid var(--border-subtle);
}

.project-stats-pill {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 11px;
  color: var(--text-muted);
}

.stat-dot {
  opacity: 0.5;
}

.batch-mode-toggle {
  display: flex;
  gap: 6px;
}

.mode-pill-btn {
  display: flex;
  align-items: center;
  gap: 5px;
  padding: 4px 10px;
  font-size: 11px;
  font-weight: 500;
  border-radius: var(--radius-pill);
  background: var(--bg-input);
  border: 1px solid var(--border-subtle);
  color: var(--text-muted);
  cursor: pointer;
  transition: all var(--dur-fast) var(--ease-out);
}

.mode-pill-btn.active {
  background: var(--accent-subtle);
  border-color: var(--accent-border);
  color: var(--accent-primary);
}

.modal-body {
  padding: 16px 20px;
  overflow-y: auto;
  flex: 1;
}

/* Preview Section */
.preview-section {
  display: flex;
  flex-direction: column;
  gap: 8px;
  height: 340px;
}

.preview-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.preview-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.preview-title {
  font-size: 11px;
  font-weight: 700;
  color: var(--text-muted);
  letter-spacing: 0.5px;
}

.preview-zip-badge {
  font-size: 11px;
  color: var(--accent-primary);
  font-weight: 500;
}

.copy-btn {
  display: flex;
  align-items: center;
  gap: 5px;
  background: var(--bg-input);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-sm);
  color: var(--text-main);
  font-size: 11px;
  padding: 3px 8px;
  cursor: pointer;
}

.copy-btn:hover {
  border-color: var(--accent-border);
  color: var(--accent-primary);
}

.preview-content {
  flex: 1;
  background: var(--bg-input);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-md);
  padding: 12px;
  font-family: 'JetBrains Mono', 'Fira Code', monospace;
  font-size: 11px;
  color: var(--text-main);
  overflow: auto;
  white-space: pre;
  margin: 0;
  line-height: 1.5;
}

/* Upload Tab Styles */
.upload-scrollable-body {
  padding: 18px 20px;
  overflow-y: auto;
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.hf-destination-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: var(--bg-input);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-md);
  padding: 12px 16px;
}

.hf-card-left {
  display: flex;
  align-items: center;
  gap: 12px;
}

.hf-dest-info {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.hf-dest-label {
  font-size: 11px;
  color: var(--text-muted);
}

.hf-repo-link {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 13.5px;
  font-weight: 600;
  color: var(--accent-primary);
  text-decoration: none;
}

.hf-repo-link:hover {
  text-decoration: underline;
}

.token-status-pill {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 11px;
  font-weight: 600;
  padding: 4px 10px;
  border-radius: var(--radius-pill);
}

.token-active {
  background: rgba(16, 185, 129, 0.15);
  color: #10b981;
  border: 1px solid rgba(16, 185, 129, 0.3);
}

.token-missing {
  background: rgba(245, 158, 11, 0.15);
  color: #f59e0b;
  border: 1px solid rgba(245, 158, 11, 0.3);
}

.token-input-card {
  background: var(--bg-surface-elevated);
  border: 1px solid var(--accent-border);
  border-radius: var(--radius-md);
  padding: 12px 14px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.token-card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.token-card-title {
  font-size: 11.5px;
  font-weight: 600;
  color: var(--text-main);
}

.token-input-row {
  display: flex;
  gap: 8px;
}

.token-input {
  flex: 1;
  background: var(--bg-input);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-sm);
  padding: 6px 10px;
  font-size: 12px;
  color: var(--text-main);
  outline: none;
}

.token-hint {
  font-size: 10.5px;
  color: var(--text-muted);
}

.token-hint a {
  color: var(--accent-primary);
}

/* Project Identity Card */
.project-identity-card {
  background: var(--bg-card);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-lg);
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.identity-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
}

.identity-label {
  font-size: 11px;
  color: var(--text-muted);
}

.identity-name {
  margin: 2px 0 0;
  font-size: 15px;
  font-weight: 700;
  color: var(--text-main);
}

.cloud-badge {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 11px;
  font-weight: 600;
  padding: 4px 10px;
  border-radius: var(--radius-pill);
}

.badge-synced {
  background: rgba(16, 185, 129, 0.15);
  color: #10b981;
  border: 1px solid rgba(16, 185, 129, 0.35);
}

.badge-new {
  background: rgba(46, 124, 228, 0.15);
  color: var(--accent-primary);
  border: 1px solid var(--accent-border);
}

.identity-meta-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 10px;
  background: var(--bg-input);
  border-radius: var(--radius-md);
  padding: 10px 14px;
}

.identity-meta-item {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.meta-name {
  font-size: 10.5px;
  color: var(--text-muted);
}

.meta-val {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-main);
}

.identity-behavior-note {
  font-size: 11.5px;
  line-height: 1.5;
  padding: 8px 12px;
  border-radius: var(--radius-sm);
}

.note-synced {
  background: rgba(16, 185, 129, 0.1);
  color: #10b981;
}

.note-new {
  background: rgba(46, 124, 228, 0.08);
  color: var(--text-main);
}

/* Audio Upload Option Card */
.audio-upload-config-card {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 12px 14px;
  background: var(--bg-surface-elevated);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-md);
}

.audio-config-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.audio-config-label {
  display: flex;
  align-items: flex-start;
  gap: 10px;
}

.audio-config-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-main);
}

.audio-config-desc {
  font-size: 11px;
  color: var(--text-muted);
  margin-top: 2px;
  line-height: 1.4;
}

.audio-stats-pill {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
  color: var(--accent-primary);
  background: var(--accent-subtle);
  padding: 4px 10px;
  border-radius: var(--radius-sm);
  align-self: flex-start;
}

/* Switch Toggle */
.switch-toggle {
  position: relative;
  display: inline-block;
  width: 38px;
  height: 22px;
  flex-shrink: 0;
}

.switch-toggle input {
  opacity: 0;
  width: 0;
  height: 0;
}

.switch-toggle .slider {
  position: absolute;
  cursor: pointer;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background-color: var(--bg-input);
  border: 1px solid var(--border-subtle);
  transition: 0.25s;
  border-radius: 22px;
}

.switch-toggle .slider:before {
  position: absolute;
  content: "";
  height: 14px;
  width: 14px;
  left: 3px;
  bottom: 3px;
  background-color: var(--text-muted);
  transition: 0.25s;
  border-radius: 50%;
}

.switch-toggle input:checked + .slider {
  background-color: var(--accent-primary);
  border-color: var(--accent-primary);
}

.switch-toggle input:checked + .slider:before {
  transform: translateX(16px);
  background-color: #ffffff;
}

/* Collision Card */
.collision-card {
  background: rgba(245, 158, 11, 0.12);
  border: 1px solid rgba(245, 158, 11, 0.4);
  border-radius: var(--radius-md);
  padding: 14px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.collision-header {
  display: flex;
  align-items: flex-start;
  gap: 10px;
}

.collision-title {
  margin: 0;
  font-size: 13px;
  font-weight: 700;
  color: #f59e0b;
}

.collision-desc {
  margin: 2px 0 0;
  font-size: 11.5px;
  color: var(--text-main);
}

.collision-actions {
  display: flex;
  gap: 8px;
  margin-top: 4px;
}

/* Result Cards */
.upload-result-card {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 12px 14px;
  border-radius: var(--radius-md);
}

.result-success {
  background: rgba(16, 185, 129, 0.12);
  border: 1px solid rgba(16, 185, 129, 0.35);
}

.result-error {
  background: rgba(239, 68, 68, 0.12);
  border: 1px solid rgba(239, 68, 68, 0.35);
  display: flex;
  flex-direction: row;
  align-items: flex-start;
  gap: 10px;
}

.result-header {
  display: flex;
  align-items: center;
  gap: 10px;
}

.result-title {
  margin: 0;
  font-size: 13px;
  font-weight: 700;
  color: var(--text-main);
}

.result-desc {
  margin: 2px 0 0;
  font-size: 11.5px;
  color: var(--text-muted);
}

/* Modal Footer */
.modal-footer {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 10px;
  padding: 12px 20px;
  border-top: 1px solid var(--border-subtle);
  background: var(--bg-surface-elevated);
}

.btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 8px 16px;
  font-size: 12.5px;
  font-weight: 600;
  border-radius: var(--radius-md);
  cursor: pointer;
  border: none;
  transition: all var(--dur-fast) var(--ease-out);
}

.btn-primary {
  background: var(--accent-primary);
  color: #ffffff;
}

.btn-primary:hover:not(:disabled) {
  background: var(--accent-hover);
  box-shadow: 0 2px 8px rgba(46, 124, 228, 0.35);
}

.btn-secondary {
  background: var(--bg-input);
  border: 1px solid var(--border-subtle);
  color: var(--text-main);
  text-decoration: none;
}

.btn-secondary:hover:not(:disabled) {
  border-color: var(--accent-border);
  color: var(--accent-primary);
}

.btn-warning {
  background: #f59e0b;
  color: #ffffff;
}

.btn-warning:hover:not(:disabled) {
  background: #d97706;
}

.btn-sm {
  padding: 5px 10px;
  font-size: 11px;
}

.btn-text-sm {
  background: transparent;
  border: none;
  font-size: 11px;
  color: var(--text-muted);
  cursor: pointer;
}

.btn-upload-cloud {
  min-width: 220px;
}

.btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.text-accent { color: var(--accent-primary); }
.text-success { color: #10b981; }
.text-warning { color: #f59e0b; }
.text-danger { color: #ef4444; }
.font-mono { font-family: monospace; }

@media (max-width: 640px) {
  .export-modal {
    width: 100vw;
    max-width: 100vw;
    height: 100dvh;
    max-height: 100dvh;
    border-radius: 0;
    border: none;
  }

  .main-mode-tabs {
    padding: 4px 8px 0;
    overflow-x: auto;
    white-space: nowrap;
    -webkit-overflow-scrolling: touch;
  }

  .main-mode-tab {
    padding: 8px 12px;
    font-size: 12px;
  }

  .scope-tabs-bar {
    padding: 6px 12px;
    overflow-x: auto;
  }

  .all-surahs-banner {
    flex-direction: column;
    align-items: flex-start;
    gap: 8px;
    padding: 10px 14px;
  }

  .preview-section {
    height: 260px;
  }

  .modal-footer {
    flex-direction: column-reverse;
    align-items: stretch;
    gap: 10px;
    padding: 12px 16px;
  }

  .footer-actions {
    flex-direction: column;
    align-items: stretch;
    width: 100%;
  }

  .btn {
    min-height: 44px;
    justify-content: center;
    font-size: 13px;
  }

  .btn-upload-cloud {
    width: 100%;
    min-width: 0;
  }
}
</style>
