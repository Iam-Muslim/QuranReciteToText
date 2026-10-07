<template>
  <div>
    <!-- Main Modal Overlay -->
    <div v-if="visible" class="modal-overlay" @click.self="close">
      <div class="alignment-modal glass-panel" :class="{ 'modal-completed': isComplete }">
        <!-- Header with Mode Selector -->
        <div class="modal-header">
          <div class="header-left">
            <Activity :size="15" class="modal-icon text-accent" />
            <h3 class="modal-title">Neural Recitation Aligner</h3>
          </div>

          <!-- Mode Tabs -->
          <div class="modal-tabs" v-if="!isRunning && !isComplete">
            <button 
              class="tab-btn" 
              :class="{ active: activeMode === 'files' }" 
              @click="activeMode = 'files'"
            >
              <Files :size="12" />
              <span>Audio Files</span>
              <span v-if="filesQueue.length > 0" class="badge-count">{{ filesQueue.length }}</span>
            </button>
            <button 
              class="tab-btn" 
              :class="{ active: activeMode === 'dir' }" 
              @click="activeMode = 'dir'"
            >
              <FolderTree :size="12" />
              <span>Folder Batch (--dir)</span>
            </button>
          </div>

          <div class="header-actions">
            <!-- Minimize to Background Button -->
            <button 
              v-if="isRunning" 
              class="btn-icon btn-minimize" 
              @click="minimize" 
              title="Minimize & Process in Background"
            >
              <Minimize2 :size="14" />
            </button>

            <button class="btn-icon" @click="close" :disabled="isRunning">
              <X :size="15" />
            </button>
          </div>
        </div>

      <!-- Body -->
      <div class="modal-body">
        <!-- MODE 1: Audio Files & Multi-File Queue -->
        <div v-if="activeMode === 'files' && !isRunning && !isComplete" class="input-form">
          <!-- Multi-File Dropzone / Browse -->
          <div 
            class="file-dropzone" 
            :class="{ 'dropzone-active': isDragging }"
            @dragover.prevent="isDragging = true"
            @dragleave.prevent="isDragging = false"
            @drop.prevent="onDropFiles"
            @click="triggerFilePick"
          >
            <UploadCloud :size="24" class="dropzone-icon" />
            <div class="dropzone-text">
              <span class="drop-title">Click to browse or drop audio files here</span>
              <span class="drop-sub">Select one or multiple recitations (MP3, WAV, M4A, OGG, OPUS)</span>
            </div>
            <button class="btn-secondary drop-browse-btn" @click.stop="triggerFilePick" type="button">
              <Upload :size="13" />
              <span>Browse Audio Files</span>
            </button>
            <input 
              type="file" 
              ref="fileInput" 
              multiple 
              accept="audio/*,video/*" 
              style="display:none" 
              @change="onFilesChosen" 
            />
          </div>

          <!-- Selected Files Queue Table -->
          <div class="queue-section" v-if="filesQueue.length > 0">
            <div class="queue-header">
              <span class="queue-title">Selected Recitations ({{ filesQueue.length }})</span>
              <button class="btn-subtle btn-xs" @click="clearQueue">Clear All</button>
            </div>

            <div class="queue-list">
              <div 
                v-for="(item, idx) in filesQueue" 
                :key="item.id" 
                class="queue-item"
              >
                <div class="item-left">
                  <span class="item-index">{{ idx + 1 }}</span>
                  <div class="item-meta">
                    <span class="item-name" :title="item.file.name">{{ item.file.name }}</span>
                    <span class="item-size">{{ formatBytes(item.file.size) }}</span>
                  </div>
                </div>

                <div class="item-right">
                  <span class="item-status" :class="item.status">
                    {{ getStatusText(item.status) }}
                  </span>
                  <button 
                    class="btn-icon btn-xs text-muted" 
                    @click.stop="removeQueueItem(idx)" 
                    title="Remove from queue"
                  >
                    <Trash2 :size="12" />
                  </button>
                </div>
              </div>
            </div>
          </div>

        </div>

        <!-- MODE 2: Folder Batch Mode (--dir) -->
        <div v-if="activeMode === 'dir' && !isRunning && !isComplete" class="input-form">
          <div class="dir-input-row">
            <input 
              v-model="dirPath" 
              type="text" 
              placeholder="Select folder or enter path (e.g. D:/Quran/Surahs/)..." 
              class="form-input"
              @keydown.enter="scanDirectory"
            />
            <button class="btn-secondary" @click="pickDirectory" type="button" title="Browse for folder">
              <FolderOpen :size="13" />
              <span>Browse Folder</span>
            </button>
            <button class="btn-primary" @click="scanDirectory" :disabled="isScanningDir || !dirPath" type="button">
              <Search :size="13" />
              <span>{{ isScanningDir ? 'Scanning...' : 'Scan Folder' }}</span>
            </button>
          </div>

          <!-- Scanned Directory Results -->
          <div v-if="scannedFiles.length > 0" class="dir-scan-results">
            <div class="dir-results-header">
              <span class="text-emerald font-semibold">Found {{ scannedFiles.length }} audio recitations ready for batch alignment</span>
              <span class="text-dim">{{ formatBytes(scannedTotalBytes) }}</span>
            </div>
            <div class="dir-files-preview">
              <div v-for="f in scannedFiles.slice(0, 15)" :key="f.full_path || f.name" class="dir-file-row">
                <FileAudio :size="12" class="text-accent" />
                <span class="dir-file-name">{{ f.name || f.rel_path }}</span>
                <span class="dir-file-size">{{ formatBytes(f.size) }}</span>
              </div>
              <div v-if="scannedFiles.length > 15" class="dir-files-more">
                + {{ scannedFiles.length - 15 }} more files in directory
              </div>
            </div>
          </div>

          <div v-else-if="dirScanError" class="error-banner">
            <AlertTriangle :size="14" />
            <span>{{ dirScanError }}</span>
          </div>

          <div class="dir-help-box">
            <p class="dir-help-title">Batch Directory Mode (--dir):</p>
            <p class="dir-help-sub">
              Transcribes and forced-aligns all audio files in the folder recursively. Perfect for complete Quran reciters or Juz archives.
            </p>
          </div>
        </div>

        <!-- Real-Time Progress Terminal -->
        <div class="progress-display" v-if="isRunning || isComplete">
          <!-- Active File in Queue Indicator -->
          <div class="queue-progress-header" v-if="filesQueue.length > 1">
            <span class="queue-counter">
              Processing Recitation {{ currentQueueIndex + 1 }} of {{ filesQueue.length }}
            </span>
            <span class="current-file-badge">{{ currentProcessingFileName }}</span>
          </div>

          <div class="minimal-steps">
            <span :class="getStepClass('vad')">1. VAD</span>
            <span class="step-arrow">→</span>
            <span :class="getStepClass('transcribing')">2. ASR</span>
            <span class="step-arrow">→</span>
            <span :class="getStepClass('aligning')">3. Aligning</span>
            <span class="step-arrow">→</span>
            <span :class="getStepClass('matching')">4. Matching</span>
          </div>

          <div class="progress-bar-wrap">
            <div class="progress-bar-fill" :style="{ width: `${progressPercent}%` }"></div>
          </div>

          <div class="status-stats">
            <span class="status-msg">{{ statusMessage }}</span>
            <span class="speed-stat" v-if="speedX > 0">{{ speedX.toFixed(1) }}x RTF</span>
          </div>

          <!-- Completion Banner when Finished -->
          <div v-if="isComplete" class="completion-banner">
            <div class="completion-icon-wrapper">
              <CheckCircle2 :size="24" class="text-emerald" />
            </div>
            <div class="completion-details">
              <span class="completion-title">تمت المحاذاة بنجاح! Alignment Succeeded</span>
              <span class="completion-sub">
                Loaded {{ projectStore.project.surahs.length }} recitation surah(s) into project.
              </span>
            </div>
          </div>

          <!-- Compact Console -->
          <div class="console-box" ref="consoleBoxRef">
            <div v-for="(log, idx) in consoleLogs" :key="idx" class="console-line">
              <span :class="log.type">{{ log.text }}</span>
            </div>
          </div>
        </div>

        <!-- Error Alert -->
        <div v-if="errorMessage" class="error-banner">
          <AlertTriangle :size="15" />
          <span>{{ errorMessage }}</span>
        </div>
      </div>

      <!-- Modal Footer -->
      <div class="modal-footer">
        <!-- While Running: Stop Batch & Background Mode -->
        <template v-if="isRunning">
          <button class="btn-danger btn-stop" @click="stopBatch">
            <Square :size="12" />
            <span>Stop Batch (إيقاف العملية)</span>
          </button>
          <button class="btn-secondary" @click="minimize">
            <Minimize2 :size="12" />
            <span>Run in Background (تشغيل في الخلفية)</span>
          </button>
        </template>

        <!-- When Complete: Continue to Studio Primary Button -->
        <template v-else-if="isComplete">
          <button class="btn-secondary" @click="close">
            <span>Close (إغلاق)</span>
          </button>
          <button class="btn-primary btn-continue-pulse" @click="handleContinueToStudio">
            <Check :size="14" />
            <span>Continue to Studio (الانتقال إلى المحرر) →</span>
          </button>
        </template>

        <!-- Idle Mode: Cancel & Start Buttons -->
        <template v-else>
          <button class="btn-secondary" @click="close">
            Cancel
          </button>

          <!-- Start Files Mode Button -->
          <button 
            v-if="activeMode === 'files'" 
            class="btn-primary" 
            @click="startFilesAlignmentQueue" 
            :disabled="filesQueue.length === 0"
          >
            <Play :size="13" />
            <span>{{ filesQueue.length > 1 ? `Start Aligning ${filesQueue.length} Files` : 'Start Alignment' }}</span>
          </button>

          <!-- Start Directory Mode Button -->
          <button 
            v-if="activeMode === 'dir'" 
            class="btn-primary" 
            @click="startDirAlignment" 
            :disabled="!dirPath || scannedFiles.length === 0"
          >
            <Play :size="13" />
            <span>Start Batch ({{ scannedFiles.length }} Files)</span>
          </button>
        </template>
      </div>
    </div>
  </div>

  <!-- Floating Background Alignment Dock / Tray -->
  <div 
    v-if="isMinimized && (isRunning || isComplete)" 
    class="floating-dock-tray glass-panel"
    :class="{ 'dock-complete': isComplete }"
    @click="restoreModal"
  >
    <div class="dock-left">
      <div class="dock-indicator">
        <Loader2 v-if="isRunning" :size="15" class="spin-icon text-accent" />
        <CheckCircle2 v-else :size="15" class="text-emerald" />
      </div>
      <div class="dock-info">
        <span class="dock-title">
          {{ isComplete ? 'Alignment Completed' : (currentProcessingFileName || 'Processing recitations...') }}
        </span>
        <span class="dock-status">
          {{ isComplete ? `${projectStore.project.surahs.length} surah(s) ready` : `${currentStageLabel} • ${progressPercent.toFixed(0)}%` }}
        </span>
      </div>
    </div>

    <div class="dock-right" @click.stop>
      <div v-if="isRunning" class="dock-mini-progress">
        <div class="dock-mini-bar" :style="{ width: `${progressPercent}%` }"></div>
      </div>

      <button 
        v-if="isRunning" 
        class="dock-btn dock-btn-stop" 
        @click="stopBatch" 
        title="Stop entire batch"
      >
        <Square :size="11" />
        <span>Stop</span>
      </button>

      <button 
        v-if="isComplete" 
        class="dock-btn dock-btn-open" 
        @click="handleContinueToStudio"
      >
        <Check :size="11" />
        <span>Open Studio</span>
      </button>

      <button 
        class="btn-icon btn-xs" 
        @click="restoreModal" 
        title="Restore full window"
      >
        <Maximize2 :size="12" />
      </button>
    </div>
  </div>
</div>
</template>

<script setup lang="ts">
import { ref, computed, nextTick, onUnmounted } from 'vue';
import { projectStore } from '../services/projectStore';
import { runAlign, stopAlign, scanAudioDir, getAudioStreamUrl, isTauriEnvironment } from '../services/api';
import { open as openDialog } from '@tauri-apps/plugin-dialog';
import { 
  Activity, 
  X, 
  Upload, 
  UploadCloud,
  Play, 
  AlertTriangle,
  Files,
  FolderTree,
  FolderOpen,
  Trash2,
  Search,
  FileAudio,
  CheckCircle2,
  Minimize2,
  Maximize2,
  Square,
  Check,
  Loader2
} from 'lucide-vue-next';

interface QueueItem {
  id: string;
  file: File;
  status: 'pending' | 'uploading' | 'aligning' | 'completed' | 'error';
  uploadedPath?: string;
  uploadedUrl?: string;
  errorMessage?: string;
}

interface ScannedAudioFile {
  name: string;
  rel_path: string;
  full_path: string;
  size: number;
  ext?: string;
  file?: File;
}

interface LogEntry {
  text: string;
  type: 'info' | 'success' | 'warn' | 'error';
}

const visible = ref(false);
const isMinimized = ref(false);
const activeMode = ref<'files' | 'dir'>('files');
const isDragging = ref(false);
const fastMode = ref(true);
const isRunning = ref(false);
const isComplete = ref(false);
const isAborted = ref(false);
const errorMessage = ref('');
let alignEventUnlisten: (() => void) | null = null;

onUnmounted(() => {
  if (alignEventUnlisten) { alignEventUnlisten(); alignEventUnlisten = null; }
});

// Files Queue State
const filesQueue = ref<QueueItem[]>([]);
const currentQueueIndex = ref(0);

// Directory Batch State
const dirPath = ref('');
const isScanningDir = ref(false);
const dirScanError = ref('');
const scannedFiles = ref<ScannedAudioFile[]>([]);

// Real-Time Progress State
const currentStage = ref<'idle' | 'vad' | 'transcribing' | 'aligning' | 'matching' | 'completed'>('idle');
const progressPercent = ref(0);
const speedX = ref(0);
const statusMessage = ref('Ready');

const fileInput = ref<HTMLInputElement | null>(null);
const consoleBoxRef = ref<HTMLElement | null>(null);
const consoleLogs = ref<LogEntry[]>([]);

const currentProcessingFileName = computed(() => {
  if (filesQueue.value.length > 0 && filesQueue.value[currentQueueIndex.value]) {
    return filesQueue.value[currentQueueIndex.value].file.name;
  }
  return '';
});

const currentStageLabel = computed(() => {
  switch (currentStage.value) {
    case 'vad': return 'Voice Detection';
    case 'transcribing': return `ASR Transcription ${speedX.value > 0 ? '(' + speedX.value.toFixed(1) + 'x)' : ''}`;
    case 'aligning': return 'Neural Alignment';
    case 'matching': return 'Medina Matching';
    case 'completed': return 'Completed';
    default: return 'Processing';
  }
});

const scannedTotalBytes = computed(() => {
  return scannedFiles.value.reduce((acc, f) => acc + (f.size || 0), 0);
});

function open() {
  visible.value = true;
  isMinimized.value = false;
  isRunning.value = false;
  isComplete.value = false;
  isAborted.value = false;
  errorMessage.value = '';
  progressPercent.value = 0;
  consoleLogs.value = [];
  // Reset queue on new session so previous completed items do not linger
  filesQueue.value = [];
}

function close() {
  if (!isRunning.value) {
    if (isComplete.value) {
      projectStore.currentTab.value = 'studio';
    }
    visible.value = false;
    isMinimized.value = false;
    filesQueue.value = [];
  }
}

function minimize() {
  if (isRunning.value || isComplete.value) {
    visible.value = false;
    isMinimized.value = true;
  }
}

function restoreModal() {
  isMinimized.value = false;
  visible.value = true;
}

function handleContinueToStudio() {
  projectStore.currentTab.value = 'studio';
  visible.value = false;
  isMinimized.value = false;
  filesQueue.value = [];
}

function stopBatch() {
  isAborted.value = true;
  stopAlign().catch(() => {});
  if (alignEventUnlisten) { alignEventUnlisten(); alignEventUnlisten = null; }
  if (activeEventSource) { activeEventSource.close(); activeEventSource = null; }

  // Mark current and pending items as cancelled
  for (let i = currentQueueIndex.value; i < filesQueue.value.length; i++) {
    const item = filesQueue.value[i];
    if (item.status === 'pending' || item.status === 'aligning' || item.status === 'uploading') {
      item.status = 'error';
      item.errorMessage = 'Stopped by user';
    }
  }
  isRunning.value = false;
  statusMessage.value = 'Batch alignment stopped by user.';
  addLog('Batch alignment stopped by user.', 'warn');
}

async function triggerFilePick() {
  if (isTauriEnvironment()) {
    try {
      const selected = await openDialog({
        directory: false,
        multiple: true,
        title: 'Select Recitation Audio Files',
        filters: [
          { name: 'Audio Files', extensions: ['mp3', 'wav', 'm4a', 'ogg', 'flac', 'aac', 'opus'] }
        ]
      });
      if (selected) {
        const paths = Array.isArray(selected) ? selected : [selected];
        for (const p of paths) {
          const name = p.split(/[\\/]/).pop() || p;
          filesQueue.value.push({
            id: `${name}_${Date.now()}_${Math.random().toString(36).substring(2, 7)}`,
            file: { name, path: p } as any,
            uploadedPath: p,
            uploadedUrl: getAudioStreamUrl(p),
            status: 'pending',
          });
        }
        return;
      }
      if (selected !== undefined) return; // User cancelled dialog
    } catch (err) {
      console.warn('Tauri openDialog error, falling back to input:', err);
    }
  }
  fileInput.value?.click();
}

function onFilesChosen(e: Event) {
  const target = e.target as HTMLInputElement;
  if (!target.files || target.files.length === 0) return;
  addFilesToQueue(Array.from(target.files));
  target.value = '';
}

function onDropFiles(e: DragEvent) {
  isDragging.value = false;
  if (!e.dataTransfer || !e.dataTransfer.files || e.dataTransfer.files.length === 0) return;
  addFilesToQueue(Array.from(e.dataTransfer.files));
}

function addFilesToQueue(files: File[]) {
  for (const f of files) {
    filesQueue.value.push({
      id: `${f.name}_${Date.now()}_${Math.random().toString(36).substring(2, 7)}`,
      file: f,
      status: 'pending',
    });
  }
}

function removeQueueItem(index: number) {
  filesQueue.value.splice(index, 1);
}

function clearQueue() {
  filesQueue.value = [];
}

async function pickDirectory() {
  isScanningDir.value = true;
  dirScanError.value = '';
  try {
    // Tier 1: If running inside Tauri desktop application, use Tauri native dialog plugin
    const isTauri = typeof window !== 'undefined' && (('__TAURI__' in (window as any)) || ('__TAURI_INTERNALS__' in (window as any)));
    if (isTauri) {
      try {
        const selected = await openDialog({
          directory: true,
          multiple: false,
          title: 'Select Folder Containing Quran Recitations',
        });
        if (selected && typeof selected === 'string') {
          dirPath.value = selected;
          await scanDirectory();
          return;
        }
        if (selected !== undefined) return; // User cancelled
      } catch (tErr) {
        console.warn('Tauri dialog error, trying browser picker:', tErr);
      }
    }

    // Tier 2: Modern Chromium Browser (Chrome / Edge / Opera) native File System Access API
    // Opens the genuine Windows folder picker without any browser "upload confirmation" prompt
    if (typeof window !== 'undefined' && 'showDirectoryPicker' in window) {
      try {
        const dirHandle = await (window as any).showDirectoryPicker({
          id: 'quran-recitations-folder',
          mode: 'read',
        });
        if (dirHandle) {
          dirPath.value = dirHandle.name;
          const audioExts = ['.mp3', '.wav', '.m4a', '.ogg', '.flac', '.aac', '.opus'];
          const files: ScannedAudioFile[] = [];
          for await (const entry of dirHandle.values()) {
            if (entry.kind === 'file') {
              const fileObj = await entry.getFile();
              if (audioExts.some(ext => fileObj.name.toLowerCase().endsWith(ext))) {
                files.push({
                  name: fileObj.name,
                  rel_path: fileObj.name,
                  full_path: fileObj.name,
                  size: fileObj.size,
                  file: fileObj,
                });
              }
            }
          }
          scannedFiles.value = files.sort((a, b) => a.name.localeCompare(b.name));
          if (scannedFiles.value.length === 0) {
            dirScanError.value = 'No audio files found in directory.';
          }
          return;
        }
      } catch (pickerErr: any) {
        if (pickerErr.name === 'AbortError') {
          // User cancelled folder picker
          return;
        }
        console.warn('showDirectoryPicker error, trying input fallback:', pickerErr);
      }
    }

    // Tier 3: Universal fallback: programmatic directory input
    const input = document.createElement('input');
    input.type = 'file';
    input.webkitdirectory = true;
    (input as any).directory = true;
    input.style.display = 'none';
    input.onchange = (e: Event) => {
      const target = e.target as HTMLInputElement;
      if (target.files && target.files.length > 0) {
        const audioExts = ['.mp3', '.wav', '.m4a', '.ogg', '.flac', '.aac', '.opus'];
        const audioFiles = Array.from(target.files).filter(f => audioExts.some(ext => f.name.toLowerCase().endsWith(ext)));
        scannedFiles.value = audioFiles.map(f => ({
          name: f.name,
          rel_path: f.webkitRelativePath || f.name,
          full_path: f.name,
          size: f.size,
          file: f,
        }));
        const first = target.files[0];
        const rel = first.webkitRelativePath || '';
        const folder = rel.split('/')[0] || '';
        if (folder) {
          dirPath.value = folder;
        }
        if (scannedFiles.value.length === 0) {
          dirScanError.value = 'No audio files found in directory.';
        }
      }
      input.remove();
    };
    document.body.appendChild(input);
    input.click();

  } catch (err: any) {
    if (err.name !== 'AbortError') {
      dirScanError.value = err.message || 'Failed to select folder';
    }
  } finally {
    isScanningDir.value = false;
  }
}

async function scanDirectory() {
  if (!dirPath.value.trim()) return;
  isScanningDir.value = true;
  dirScanError.value = '';
  scannedFiles.value = [];

  try {
    // Direct Tauri command — no HTTP server needed
    const data = await scanAudioDir(dirPath.value.trim());
    const files = data.audio_files || data.files || [];
    scannedFiles.value = files.map((f: any) => ({
      name: f.name || f.rel_path,
      rel_path: f.rel_path || f.name,
      full_path: f.path || f.full_path || '',
      size: f.size || f.size_bytes || 0,
      ext: f.ext || '',
    }));
    if (scannedFiles.value.length === 0) {
      dirScanError.value = 'No audio files found in directory.';
    }
  } catch (err: any) {
    dirScanError.value = err.message || err || 'Directory scan failed';
  } finally {
    isScanningDir.value = false;
  }
}

// ==========================================
// Sequential Alignment Queue Execution
// ==========================================
async function startFilesAlignmentQueue() {
  if (filesQueue.value.length === 0) return;

  isRunning.value = true;
  isComplete.value = false;
  isAborted.value = false;
  errorMessage.value = '';
  consoleLogs.value = [];
  currentQueueIndex.value = 0;

  for (let i = 0; i < filesQueue.value.length; i++) {
    if (isAborted.value) break;

    currentQueueIndex.value = i;
    const item = filesQueue.value[i];

    try {
      let audioPath = item.uploadedPath;
      let audioUrl = item.uploadedUrl;

      // 1. In Tauri: if item.file has native .path, use it directly!
      const nativePath: string = (item.file as any)?.path || '';
      if (nativePath && (nativePath.includes(':') || nativePath.startsWith('/'))) {
        audioPath = nativePath;
        audioUrl = getAudioStreamUrl(nativePath);
      }

      // 2. If not already a full path on disk, upload to save it to disk
      const isAbsolutePath = audioPath && (audioPath.includes(':') || audioPath.startsWith('/'));
      if (!isAbsolutePath) {
        if (!item.file || !(item.file instanceof File)) {
          throw new Error('No valid file to upload');
        }

        item.status = 'uploading';
        statusMessage.value = `Uploading ${item.file.name}...`;
        progressPercent.value = 5;

        const formData = new FormData();
        formData.append('file', item.file);

        const upRes = await fetch('/api/engine/audio/upload?extract_peaks=false', {
          method: 'POST',
          body: formData,
        });

        if (!upRes.ok) {
          throw new Error(`Upload failed: ${upRes.statusText}`);
        }

        const upData = await upRes.json();
        audioPath = upData.filePath || upData.path;
        audioUrl = upData.url || (audioPath ? getAudioStreamUrl(audioPath) : '');
        item.uploadedPath = audioPath;
        item.uploadedUrl = audioUrl;
      }

      if (!audioPath) {
        throw new Error('No valid audio file path');
      }

      if (isAborted.value) break;

      item.status = 'aligning';
      statusMessage.value = `Aligning ${item.file?.name || audioPath}...`;
      addLog(`Processing [${i + 1}/${filesQueue.value.length}] ${item.file?.name || audioPath}`, 'info');

      // Direct Tauri IPC in desktop, SSE streaming in browser
      await executeAlignment(audioPath, audioUrl);
      item.status = 'completed';

    } catch (err: any) {
      if (isAborted.value) {
        item.status = 'error';
        item.errorMessage = 'Aborted';
        addLog(`Stopped ${item.file.name}`, 'warn');
        break;
      }
      item.status = 'error';
      item.errorMessage = err.message || String(err);
      addLog(`Error processing ${item.file.name}: ${item.errorMessage}`, 'error');
    }
  }

  isRunning.value = false;
  if (!isAborted.value) {
    isComplete.value = true;
    statusMessage.value = `Batch alignment finished! Processed ${filesQueue.value.length} recitation(s).`;
  }
}

async function startDirAlignment() {
  if (!dirPath.value.trim() && scannedFiles.value.length === 0) return;

  const targetDir = dirPath.value.trim();
  if (!targetDir) {
    // Browser file objects picked — fall back to queue mode
    const browserFiles = scannedFiles.value.filter(f => f.file instanceof File);
    if (browserFiles.length > 0) {
      filesQueue.value = browserFiles.map(bf => ({
        id: `${bf.name}_${Date.now()}_${Math.random().toString(36).substring(2, 7)}`,
        file: bf.file!,
        status: 'pending',
      }));
      activeMode.value = 'files';
      await startFilesAlignmentQueue();
    }
    return;
  }

  isRunning.value = true;
  isComplete.value = false;
  isAborted.value = false;
  errorMessage.value = '';
  consoleLogs.value = [];
  statusMessage.value = 'Starting batch directory transcription pipeline...';

  try {
    // Dual-mode alignment execution
    await executeAlignment(undefined, undefined, targetDir);
    if (!isAborted.value) {
      isComplete.value = true;
    }
  } catch (err: any) {
    if (!isAborted.value) {
      errorMessage.value = err.message || String(err);
      addLog(`Batch error: ${errorMessage.value}`, 'error');
    }
  } finally {
    isRunning.value = false;
  }
}

let activeEventSource: EventSource | null = null;

function runAlignmentBrowser(
  audioPath?: string,
  audioUrl?: string,
  dirPathArg?: string,
): Promise<void> {
  return new Promise((resolve, reject) => {
    if (activeEventSource) {
      activeEventSource.close();
      activeEventSource = null;
    }
    let url = `/api/engine/align?fast=${fastMode.value}`;
    if (audioPath) url += `&audio_path=${encodeURIComponent(audioPath)}`;
    if (dirPathArg) url += `&dir_path=${encodeURIComponent(dirPathArg)}`;

    const es = new EventSource(url);
    activeEventSource = es;
    let hasCompleted = false;

    es.onmessage = (e) => {
      try {
        const data = JSON.parse(e.data);
        handleAlignEvent(data, audioPath, audioUrl);
        if (data.type === 'complete') {
          hasCompleted = true;
          es.close();
          activeEventSource = null;
          resolve();
        } else if (data.type === 'error') {
          es.close();
          activeEventSource = null;
          reject(new Error(data.message || 'Alignment error'));
        }
      } catch {
        addLog(e.data, 'info');
      }
    };

    es.onerror = () => {
      es.close();
      activeEventSource = null;
      if (hasCompleted || isComplete.value) {
        resolve();
      } else {
        reject(new Error(errorMessage.value || 'Alignment stream ended'));
      }
    };
  });
}

function executeAlignment(
  audioPath?: string,
  audioUrl?: string,
  dirPathArg?: string,
): Promise<void> {
  if (isTauriEnvironment()) {
    return runAlignmentTauri(audioPath, audioUrl, dirPathArg);
  } else {
    return runAlignmentBrowser(audioPath, audioUrl, dirPathArg);
  }
}

/**
 * Core alignment function using Tauri IPC (QuranCaption pattern).
 * run.py is spawned directly by Rust. Progress arrives as 'align-event' Tauri events.
 */
function runAlignmentTauri(
  audioPath?: string,
  audioUrl?: string,
  dirPathArg?: string,
): Promise<void> {
  return new Promise(async (resolve, reject) => {
    if (alignEventUnlisten) { alignEventUnlisten(); alignEventUnlisten = null; }

    const { listen } = await import('@tauri-apps/api/event');

    alignEventUnlisten = await listen<any>('align-event', (event) => {
      handleAlignEvent(event.payload, audioPath, audioUrl);
      if (event.payload.type === 'complete') {
        cleanup();
        resolve();
      } else if (event.payload.type === 'error') {
        cleanup();
        reject(new Error(event.payload.message || 'Alignment error'));
      }
    });

    function cleanup() {
      if (alignEventUnlisten) { alignEventUnlisten(); alignEventUnlisten = null; }
    }

    try {
      await runAlign({
        audio_path: audioPath,
        dir_path: dirPathArg,
        fast: fastMode.value,
      });
    } catch (err) {
      cleanup();
      reject(err);
    }
  });
}

function handleAlignEvent(event: any, fallbackAudioPath?: string, fallbackAudioUrl?: string) {
  if (event.type === 'start') {
    addLog(event.message, 'info');
  } else if (event.type === 'stdout') {
    addLog(event.text, 'info');
  } else if (event.type === 'stderr') {
    addLog(event.text, 'warn');
  } else if (event.type === 'progress') {
    const p = event.data;
    if (p.stage === 'vad') {
      currentStage.value = 'vad';
      progressPercent.value = 15;
      statusMessage.value = `VAD (${p.elapsed}s)`;
    } else if (p.stage === 'transcribing') {
      currentStage.value = 'transcribing';
      progressPercent.value = Math.min(80, 15 + (p.percent * 0.65));
      speedX.value = p.speed_x || 0;
      statusMessage.value = `ASR: ${p.percent.toFixed(0)}%`;
    } else if (p.stage === 'aligning') {
      currentStage.value = 'aligning';
      progressPercent.value = 85;
      statusMessage.value = p.message || 'CTC Trellis Alignment...';
    } else if (p.stage === 'matching') {
      currentStage.value = 'matching';
      progressPercent.value = 93;
      statusMessage.value = p.message || 'Medina Quran Matching...';
    } else if (p.stage === 'batch_file_start') {
      statusMessage.value = `[${p.index}/${p.total}] Aligning ${p.file}...`;
      addLog(`Batch File [${p.index}/${p.total}]: ${p.file}`, 'info');
    } else if (p.stage === 'batch_file_done') {
      statusMessage.value = `[${p.index}/${p.total}] Done: ${p.file}`;
      addLog(`Completed: ${p.file}`, 'success');
    } else if (p.stage === 'completed' || p.stage === 'batch_completed') {
      currentStage.value = 'completed';
      progressPercent.value = 100;
      statusMessage.value = `Done (${p.real_time_factor || 1.0}x RTF)`;
    }
  } else if (event.type === 'complete') {
    currentStage.value = 'completed';
    progressPercent.value = 100;
    statusMessage.value = 'Alignment complete!';

    if (event.result) {
      const effPath = event.audio_path || fallbackAudioPath;
      const effUrl = event.audio_url || fallbackAudioUrl;
      projectStore.loadAlignedSurah(event.result, effPath, effUrl);
      projectStore.currentTab.value = 'studio';
    }
  } else if (event.type === 'error') {
    errorMessage.value = event.message;
    addLog(`Alignment error: ${event.message}`, 'error');
  }
}

function addLog(text: string, type: 'info' | 'success' | 'warn' | 'error' = 'info') {
  consoleLogs.value.push({ text, type });
  nextTick(() => {
    if (consoleBoxRef.value) {
      consoleBoxRef.value.scrollTop = consoleBoxRef.value.scrollHeight;
    }
  });
}

function getStepClass(stage: string) {
  const order = ['vad', 'transcribing', 'aligning', 'matching', 'completed'];
  const curIdx = order.indexOf(currentStage.value);
  const targetIdx = order.indexOf(stage);

  if (curIdx > targetIdx || isComplete.value) return 'step-done';
  if (curIdx === targetIdx && isRunning.value) return 'step-active';
  return 'step-pending';
}

function getStatusText(status: QueueItem['status']): string {
  switch (status) {
    case 'pending': return 'Queued';
    case 'uploading': return 'Uploading';
    case 'aligning': return 'Aligning';
    case 'completed': return 'Complete';
    case 'error': return 'Failed';
  }
}

function formatBytes(bytes: number): string {
  if (!bytes || bytes === 0) return '0 B';
  const k = 1024;
  const sizes = ['B', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return `${(bytes / Math.pow(k, i)).toFixed(1)} ${sizes[i]}`;
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
  background: rgba(0, 0, 0, 0.75);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
  backdrop-filter: blur(4px);
}

.alignment-modal {
  width: 580px;
  max-width: 94vw;
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
  padding: 10px 16px;
  border-bottom: 1px solid var(--border-subtle);
  background: var(--bg-base);
}
.header-left {
  display: flex;
  align-items: center;
  gap: 8px;
}
.modal-title {
  margin: 0;
  font-size: 0.92rem;
  font-weight: 600;
  color: #fff;
}

.modal-tabs {
  display: flex;
  align-items: center;
  gap: 4px;
  background: rgba(255, 255, 255, 0.04);
  padding: 2px;
  border-radius: 6px;
  border: 1px solid var(--border-subtle);
}
.tab-btn {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  background: transparent;
  border: none;
  color: var(--text-muted);
  font-size: 0.72rem;
  font-weight: 500;
  padding: 4px 9px;
  border-radius: 4px;
  cursor: pointer;
  transition: all 0.12s ease;
}
.tab-btn.active {
  background: var(--bg-surface-elevated);
  color: #fff;
  border: 1px solid var(--border-medium);
}
.badge-count {
  background: var(--accent-primary);
  color: #fff;
  font-size: 0.6rem;
  font-weight: 700;
  padding: 1px 5px;
  border-radius: 9999px;
}

.modal-body {
  padding: 16px;
}

/* File Dropzone */
.file-dropzone {
  border: 1.5px dashed var(--border-medium);
  border-radius: 8px;
  padding: 20px 16px;
  text-align: center;
  cursor: pointer;
  background: rgba(255, 255, 255, 0.015);
  transition: all 0.15s ease;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  margin-bottom: 14px;
}
.file-dropzone:hover, .file-dropzone.dropzone-active {
  border-color: var(--accent-primary);
  background: var(--accent-subtle);
}
.dropzone-icon {
  color: var(--accent-primary);
}
.dropzone-text {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.drop-title {
  font-size: 0.82rem;
  font-weight: 600;
  color: var(--text-main);
}
.drop-sub {
  font-size: 0.7rem;
  color: var(--text-dim);
}
.drop-browse-btn {
  margin-top: 4px;
}

/* Selected Queue */
.queue-section {
  background: var(--bg-base);
  border: 1px solid var(--border-subtle);
  border-radius: 6px;
  padding: 10px;
  margin-bottom: 14px;
}
.queue-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}
.queue-title {
  font-size: 0.74rem;
  font-weight: 600;
  color: var(--text-main);
}
.queue-list {
  max-height: 140px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 5px;
}
.queue-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 5px 8px;
  background: var(--bg-surface);
  border: 1px solid var(--border-subtle);
  border-radius: 4px;
  font-size: 0.72rem;
}
.item-left {
  display: flex;
  align-items: center;
  gap: 8px;
  overflow: hidden;
}
.item-index {
  color: var(--text-dim);
  font-family: var(--font-mono);
  font-size: 0.68rem;
  min-width: 14px;
}
.item-meta {
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.item-name {
  color: var(--text-main);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 320px;
}
.item-size {
  color: var(--text-dim);
  font-size: 0.64rem;
}
.item-right {
  display: flex;
  align-items: center;
  gap: 6px;
}
.item-status {
  font-size: 0.65rem;
  font-weight: 600;
  padding: 2px 6px;
  border-radius: 4px;
}
.item-status.pending { background: rgba(255, 255, 255, 0.08); color: var(--text-dim); }
.item-status.uploading { background: rgba(96, 165, 250, 0.2); color: #60a5fa; }
.item-status.aligning { background: rgba(129, 140, 248, 0.2); color: #818cf8; }
.item-status.completed { background: rgba(52, 211, 153, 0.2); color: #34d399; }
.item-status.error { background: rgba(248, 113, 113, 0.2); color: #f87171; }

/* Cached Chips */
.cached-chips-row {
  margin-bottom: 12px;
}
.cached-chips-scroll {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  max-height: 60px;
  overflow-y: auto;
  margin-top: 5px;
}
.subtle-label {
  font-size: 0.68rem;
  color: var(--text-dim);
}
.audio-pill {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  background: var(--bg-surface-elevated);
  border: 1px solid var(--border-subtle);
  color: var(--text-main);
  border-radius: 4px;
  padding: 2px 7px;
  font-size: 0.67rem;
  cursor: pointer;
  transition: all 0.1s ease;
}
.audio-pill:hover {
  border-color: var(--accent-primary);
  background: var(--accent-subtle);
}

.quick-load-wrap {
  text-align: center;
  padding-top: 8px;
  border-top: 1px dashed rgba(255, 255, 255, 0.08);
}
.btn-subtle {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  background: transparent;
  border: 1px solid var(--border-subtle);
  color: var(--text-muted);
  border-radius: 5px;
  padding: 4px 10px;
  font-size: 0.72rem;
  cursor: pointer;
}
.btn-subtle:hover {
  color: #fff;
  border-color: rgba(255, 255, 255, 0.25);
}
.btn-xs {
  padding: 2px 6px;
  font-size: 0.65rem;
}

/* Directory Mode */
.dir-input-row {
  display: flex;
  gap: 6px;
  margin-bottom: 12px;
}
.form-input {
  flex: 1;
  background: var(--bg-base);
  border: 1px solid var(--border-subtle);
  border-radius: 6px;
  padding: 7px 10px;
  color: #fff;
  font-size: 0.78rem;
  outline: none;
}
.form-input:focus {
  border-color: var(--accent-primary);
}

.dir-scan-results {
  background: var(--bg-base);
  border: 1px solid var(--border-subtle);
  border-radius: 6px;
  padding: 10px;
  margin-bottom: 12px;
}
.dir-results-header {
  display: flex;
  justify-content: space-between;
  font-size: 0.74rem;
  font-weight: 600;
  margin-bottom: 8px;
}
.dir-files-preview {
  display: flex;
  flex-direction: column;
  gap: 4px;
  max-height: 120px;
  overflow-y: auto;
}
.dir-file-row {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 0.69rem;
  color: var(--text-muted);
}
.dir-file-name {
  flex: 1;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.dir-file-size {
  color: var(--text-dim);
  font-family: var(--font-mono);
  font-size: 0.64rem;
}
.dir-files-more {
  font-size: 0.68rem;
  color: var(--text-dim);
  text-align: center;
  margin-top: 4px;
}

.dir-help-box {
  background: rgba(255, 255, 255, 0.02);
  border: 1px solid var(--border-subtle);
  border-radius: 6px;
  padding: 8px 12px;
  font-size: 0.7rem;
}
.dir-help-title {
  font-weight: 600;
  color: var(--text-main);
  margin-bottom: 2px;
}
.dir-help-sub {
  color: var(--text-dim);
}

/* Progress & Queue Header */
.queue-progress-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: var(--bg-base);
  padding: 5px 10px;
  border-radius: 4px;
  border: 1px solid var(--border-subtle);
  margin-bottom: 10px;
  font-size: 0.72rem;
}
.queue-counter {
  color: var(--accent-primary);
  font-weight: 600;
}
.current-file-badge {
  color: var(--text-muted);
  font-family: var(--font-mono);
  font-size: 0.68rem;
}

/* Minimal Steps */
.minimal-steps {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  font-size: 0.72rem;
  color: var(--text-dim);
  margin-bottom: 12px;
}
.step-arrow {
  color: var(--border-subtle);
}
.step-active {
  color: var(--accent-primary);
  font-weight: 600;
}
.step-done {
  color: var(--emerald-primary);
}

.step-setup-badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  color: #38bdf8;
  font-weight: 600;
}

.model-setup-banner {
  display: flex;
  align-items: center;
  gap: 10px;
  background: rgba(14, 165, 233, 0.1);
  border: 1px solid rgba(14, 165, 233, 0.25);
  border-radius: 6px;
  padding: 8px 12px;
  margin-bottom: 12px;
}
.model-setup-text {
  display: flex;
  flex-direction: column;
  gap: 2px;
  text-align: left;
}
.setup-title {
  font-size: 0.76rem;
  font-weight: 600;
  color: #38bdf8;
}
.setup-desc {
  font-size: 0.69rem;
  color: var(--text-secondary);
  font-family: var(--font-mono);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 480px;
}

.progress-bar-wrap {
  width: 100%;
  height: 4px;
  background: var(--bg-base);
  border-radius: 2px;
  overflow: hidden;
  margin-bottom: 8px;
}
.progress-bar-fill {
  height: 100%;
  background: var(--accent-primary);
  transition: width 0.2s ease;
}

.status-stats {
  display: flex;
  justify-content: space-between;
  font-size: 0.74rem;
  color: var(--text-main);
  margin-bottom: 10px;
}
.status-msg {
  color: var(--accent-primary);
}
.speed-stat {
  font-family: var(--font-mono);
  color: #38bdf8;
}

.console-box {
  background: var(--bg-base);
  border: 1px solid var(--border-subtle);
  border-radius: 5px;
  padding: 8px;
  height: 110px;
  overflow-y: auto;
  font-family: var(--font-mono);
  font-size: 0.68rem;
}
.console-line {
  line-height: 1.5;
}
.success { color: #34d399; }
.warn { color: #fbbf24; }
.error { color: #ef4444; }

.error-banner {
  margin-top: 10px;
  background: rgba(239, 68, 68, 0.15);
  border: 1px solid rgba(239, 68, 68, 0.4);
  color: #f87171;
  padding: 6px 10px;
  border-radius: 5px;
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 0.72rem;
}

.modal-footer {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  padding: 10px 16px;
  border-top: 1px solid var(--border-subtle);
  background: var(--bg-base);
}

/* Completion Styling */
.modal-completed {
  border-color: rgba(16, 185, 129, 0.5) !important;
  box-shadow: 0 0 35px rgba(16, 185, 129, 0.15), var(--shadow-modal) !important;
  transition: all 0.3s ease;
}

.completion-banner {
  display: flex;
  align-items: center;
  gap: 12px;
  background: rgba(16, 185, 129, 0.08);
  border: 1px solid rgba(16, 185, 129, 0.25);
  border-radius: 6px;
  padding: 10px 14px;
  margin-bottom: 12px;
}
.completion-icon-wrapper {
  display: flex;
  align-items: center;
  justify-content: center;
}
.completion-details {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.completion-title {
  font-size: 0.8rem;
  font-weight: 600;
  color: #34d399;
}
.completion-sub {
  font-size: 0.72rem;
  color: var(--text-muted);
}

.btn-continue-pulse {
  background: linear-gradient(135deg, #059669 0%, #10b981 100%) !important;
  color: #ffffff !important;
  border: none !important;
  font-weight: 600 !important;
  padding: 6px 14px !important;
  box-shadow: 0 0 16px rgba(16, 185, 129, 0.35);
  transition: transform 0.15s ease, box-shadow 0.15s ease;
}
.btn-continue-pulse:hover {
  transform: translateY(-1px);
  box-shadow: 0 0 20px rgba(16, 185, 129, 0.5);
}

.btn-danger.btn-stop {
  background: rgba(239, 68, 68, 0.2);
  border: 1px solid rgba(239, 68, 68, 0.45);
  color: #fca5a5;
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 5px 12px;
  border-radius: 4px;
  font-size: 0.72rem;
  cursor: pointer;
}
.btn-danger.btn-stop:hover {
  background: rgba(239, 68, 68, 0.35);
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 6px;
}
.btn-minimize {
  color: var(--text-muted);
}
.btn-minimize:hover {
  color: var(--accent-primary);
}

/* Floating Background Dock Tray */
.floating-dock-tray {
  position: fixed;
  bottom: 24px;
  right: 28px;
  z-index: 9999;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  min-width: 380px;
  max-width: 460px;
  background: rgba(13, 19, 33, 0.94);
  border: 1px solid var(--border-medium);
  border-radius: 30px;
  padding: 8px 16px;
  box-shadow: 0 10px 30px rgba(0, 0, 0, 0.6), 0 0 1px rgba(255, 255, 255, 0.1);
  backdrop-filter: blur(12px);
  cursor: pointer;
  transition: all 0.2s ease;
  user-select: none;
}
.floating-dock-tray:hover {
  transform: translateY(-2px);
  border-color: var(--accent-primary);
  box-shadow: 0 12px 35px rgba(0, 0, 0, 0.7), 0 0 15px rgba(99, 102, 241, 0.2);
}
.floating-dock-tray.dock-complete {
  border-color: rgba(16, 185, 129, 0.5);
  box-shadow: 0 10px 30px rgba(0, 0, 0, 0.6), 0 0 20px rgba(16, 185, 129, 0.25);
}

.dock-left {
  display: flex;
  align-items: center;
  gap: 10px;
  flex: 1;
  min-width: 0;
}
.dock-indicator {
  display: flex;
  align-items: center;
  justify-content: center;
}
.spin-icon {
  animation: spin 1s linear infinite;
}
@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

.dock-info {
  display: flex;
  flex-direction: column;
  min-width: 0;
  flex: 1;
}
.dock-title {
  font-size: 0.74rem;
  font-weight: 600;
  color: var(--text-main);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.dock-status {
  font-size: 0.68rem;
  color: var(--text-dim);
}

.dock-right {
  display: flex;
  align-items: center;
  gap: 8px;
}
.dock-mini-progress {
  width: 55px;
  height: 4px;
  background: var(--bg-base);
  border-radius: 2px;
  overflow: hidden;
}
.dock-mini-bar {
  height: 100%;
  background: var(--accent-primary);
  transition: width 0.2s ease;
}

.dock-btn {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 0.68rem;
  padding: 4px 10px;
  border-radius: 14px;
  cursor: pointer;
  border: none;
}
.dock-btn-stop {
  background: rgba(239, 68, 68, 0.2);
  color: #fca5a5;
  border: 1px solid rgba(239, 68, 68, 0.4);
}
.dock-btn-stop:hover {
  background: rgba(239, 68, 68, 0.35);
}
.dock-btn-open {
  background: linear-gradient(135deg, #059669 0%, #10b981 100%);
  color: #ffffff;
  font-weight: 600;
}
.dock-btn-open:hover {
  box-shadow: 0 0 10px rgba(16, 185, 129, 0.4);
}
</style>
