<template>
  <div v-if="visible" class="modal-backdrop" @click="handleBackdropClick">
    <div class="update-modal glass-panel" @click.stop>
      <!-- Header -->
      <div class="modal-header">
        <div class="header-titles">
          <div class="title-with-icon">
            <Sparkles v-if="dialogMode === 'app_update'" :size="18" class="text-accent" />
            <Cpu v-else-if="dialogMode === 'aligner_init'" :size="18" class="text-accent" />
            <Layers v-else :size="18" class="text-accent" />
            <h3 class="modal-title">{{ modalTitle }}</h3>
          </div>
          <span class="modal-subtitle">{{ modalSubtitle }}</span>
        </div>
        <button 
          v-if="!isBusy || isDone" 
          class="btn-icon close-btn" 
          @click="close" 
          title="Close"
        >
          <X :size="16" />
        </button>
      </div>

      <!-- App Update Version Diff Badge Row -->
      <div v-if="dialogMode === 'app_update'" class="version-banner">
        <div class="version-pill current-pill">
          <span class="ver-label">Current:</span>
          <span class="ver-val">v{{ versionService.currentVersion.value }}</span>
        </div>
        <ArrowRight :size="14" class="arrow-icon" />
        <div class="version-pill latest-pill">
          <span class="ver-label">New:</span>
          <span class="ver-val">v{{ versionService.latestVersion.value }}</span>
        </div>
      </div>

      <!-- Release Notes / Changelog for App Update -->
      <div v-if="dialogMode === 'app_update'" class="changelog-container">
        <span class="changelog-label">What's New in this Release:</span>
        <div class="changelog-content">
          <pre class="changelog-text">{{ versionService.changelog.value || 'Bug fixes, performance optimizations, and stability improvements.' }}</pre>
        </div>
      </div>

      <!-- Component Checklist for Setup Modes -->
      <div v-if="dialogMode !== 'app_update'" class="setup-checklist">
        <div class="checklist-item" :class="{ 'done': currentProgress >= 30, 'active': currentProgress < 30 }">
          <div class="check-bullet">
            <CheckCircle2 v-if="currentProgress >= 30" :size="13" class="text-success" />
            <div v-else class="bullet-dot"></div>
          </div>
          <span class="check-label">{{ dialogMode === 'app_init' ? 'Portable Python 3.14 Runtime (~10MB)' : 'Core Acoustic Aligner Libraries' }}</span>
        </div>
        <div class="checklist-item" :class="{ 'done': currentProgress >= 70, 'active': currentProgress >= 30 && currentProgress < 70 }">
          <div class="check-bullet">
            <CheckCircle2 v-if="currentProgress >= 70" :size="13" class="text-success" />
            <div v-else class="bullet-dot"></div>
          </div>
          <span class="check-label">{{ dialogMode === 'app_init' ? 'UI Engine & Media Server Packages' : 'Silero Voice Activity Detector' }}</span>
        </div>
        <div class="checklist-item" :class="{ 'done': isDone, 'active': currentProgress >= 70 && !isDone }">
          <div class="check-bullet">
            <CheckCircle2 v-if="isDone" :size="13" class="text-success" />
            <div v-else class="bullet-dot"></div>
          </div>
          <span class="check-label">{{ dialogMode === 'app_init' ? 'Workspace Environment Ready' : 'Zipformer Arabic ONNX Acoustic Model (~72MB)' }}</span>
        </div>
      </div>

      <!-- Dynamic Progress Section -->
      <div v-if="isBusy || isDone" class="progress-section">
        <div class="progress-info-row">
          <span class="progress-status-text">{{ currentStatusText }}</span>
          <span class="progress-percent-text">{{ currentProgress }}%</span>
        </div>
        <div class="progress-bar-track">
          <div 
            class="progress-bar-fill" 
            :class="{ 'done-bar': isDone }"
            :style="{ width: `${currentProgress}%` }"
          ></div>
        </div>
      </div>

      <!-- Error Box -->
      <div v-if="errorMessage" class="error-box">
        <AlertTriangle :size="14" />
        <span>{{ errorMessage }}</span>
      </div>

      <!-- Modal Footer -->
      <div class="modal-footer">
        <button 
          v-if="!isDone" 
          class="btn btn-secondary" 
          @click="handleCancel" 
          :disabled="isDone"
        >
          {{ isBusy ? 'Cancel' : 'Later' }}
        </button>

        <button 
          v-if="isDone" 
          class="btn btn-primary btn-done" 
          @click="close"
        >
          <CheckCircle2 :size="14" />
          <span>Done</span>
        </button>

        <button 
          v-else-if="dialogMode === 'app_update'" 
          class="btn btn-primary btn-update" 
          @click="startUpdate" 
          :disabled="isBusy"
        >
          <Loader2 v-if="isBusy" class="animate-spin" :size="14" />
          <DownloadCloud v-else :size="14" />
          <span>{{ updateButtonText }}</span>
        </button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue';
import { versionService } from '../services/VersionService';
import { getApiBaseUrl } from '../services/api';
import { 
  X, 
  Sparkles, 
  ArrowRight, 
  DownloadCloud, 
  Loader2, 
  AlertTriangle, 
  CheckCircle2, 
  Cpu, 
  Layers 
} from 'lucide-vue-next';

export type DialogMode = 'app_init' | 'aligner_init' | 'app_update';

const visible = ref(false);
const dialogMode = ref<DialogMode>('app_update');
const setupProgress = ref(0);
const setupStatusMessage = ref('');
const errorMessage = ref('');
const isDone = ref(false);

let abortController: AbortController | null = null;
let unlistenFn: (() => void) | null = null;

const isBusy = computed(() => {
  if (dialogMode.value === 'app_update') {
    return versionService.updateState.value === 'downloading' || versionService.updateState.value === 'installing';
  }
  return !isDone.value && setupProgress.value > 0 && setupProgress.value < 100;
});

const modalTitle = computed(() => {
  if (dialogMode.value === 'app_init') return 'Initializing Quran Recite Studio';
  if (dialogMode.value === 'aligner_init') return 'Preparing Quran Recite Aligner';
  return 'New Update Available';
});

const modalSubtitle = computed(() => {
  if (dialogMode.value === 'app_init') return 'Preparing portable Python runtime & workspace components';
  if (dialogMode.value === 'aligner_init') return 'Downloading AI acoustic speech models & aligner libraries';
  return 'A newer version of Quran Recite2Text is ready to install';
});

const currentProgress = computed(() => {
  if (dialogMode.value === 'app_update') {
    return versionService.downloadProgress.value;
  }
  return setupProgress.value;
});

const currentStatusText = computed(() => {
  if (dialogMode.value === 'app_update') {
    if (versionService.updateState.value === 'installing') return 'Installing update package...';
    if (versionService.updateState.value === 'done') return 'Update ready. Relaunching application...';
    return 'Downloading update package...';
  }
  return setupStatusMessage.value || (isDone.value ? 'Ready!' : 'Preparing components...');
});

const updateButtonText = computed(() => {
  if (versionService.updateState.value === 'downloading') return `Downloading (${versionService.downloadProgress.value}%)`;
  if (versionService.updateState.value === 'installing') return 'Installing & Restarting...';
  if (versionService.updateState.value === 'done') return 'Relaunching...';
  return 'Update Now';
});

function handleBackdropClick() {
  if (!isBusy.value || isDone.value) {
    close();
  }
}

function handleCancel() {
  if (abortController) {
    abortController.abort();
    abortController = null;
  }
  close();
}

function open(mode: DialogMode = 'app_update') {
  dialogMode.value = mode;
  visible.value = true;
  errorMessage.value = '';
  isDone.value = false;
  setupProgress.value = 0;
  setupStatusMessage.value = '';

  if (mode === 'app_init') {
    startAppInitListening();
  } else if (mode === 'aligner_init') {
    startAlignerSetup();
  }
}

function close() {
  if (unlistenFn) {
    unlistenFn();
    unlistenFn = null;
  }
  visible.value = false;
}

async function startUpdate() {
  await versionService.downloadAndInstall();
}

/**
 * App Init: Listens to install-status emitted from Tauri Rust during first-run setup.
 */
async function startAppInitListening() {
  setupStatusMessage.value = 'Preparing portable Python 3.11 environment...';
  setupProgress.value = 10;

  try {
    const isTauri = typeof window !== 'undefined' && (('__TAURI__' in (window as any)) || ('__TAURI_INTERNALS__' in (window as any)));
    if (isTauri) {
      const { listen } = await import('@tauri-apps/api/event');
      unlistenFn = await listen<{ message: string; progress?: number; ready?: boolean }>('install-status', (event) => {
        setupStatusMessage.value = event.payload.message || 'Installing...';
        if (typeof event.payload.progress === 'number') {
          setupProgress.value = event.payload.progress;
        }
        if (event.payload.ready || event.payload.progress === 100) {
          isDone.value = true;
          setupProgress.value = 100;
          setupStatusMessage.value = 'Quran Recite Studio is ready!';
          setTimeout(() => {
            close();
            // Automatically check for app updates right after initial setup (QuranCaption pattern)
            versionService.checkForUpdates();
          }, 1200);
        }
      });
    } else {
      // In web dev mode, already ready
      setupProgress.value = 100;
      isDone.value = true;
      setupStatusMessage.value = 'Environment active in dev mode';
      setTimeout(() => close(), 800);
    }
  } catch (err: any) {
    errorMessage.value = err.message || 'Setup listener failed';
  }
}

/**
 * Aligner Init: Connects to backend /api/engine/aligner/setup to download models and packages.
 */
async function startAlignerSetup() {
  abortController = new AbortController();
  setupProgress.value = 5;
  setupStatusMessage.value = 'Connecting to Aligner engine...';

  try {
    const base = getApiBaseUrl();
    const res = await fetch(`${base}/api/engine/aligner/setup`, {
      signal: abortController.signal,
    });

    if (!res.ok || !res.body) {
      throw new Error('Failed to initiate aligner setup');
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n\n');
      buffer = lines.pop() || '';

      for (const block of lines) {
        const line = block.trim();
        if (line.startsWith('data:')) {
          try {
            const data = JSON.parse(line.slice(5).trim());
            if (typeof data.progress === 'number') {
              setupProgress.value = data.progress;
            }
            if (data.message) {
              setupStatusMessage.value = data.message;
            }
            if (data.step === 'done' || data.progress === 100) {
              isDone.value = true;
              setupProgress.value = 100;
              setupStatusMessage.value = 'Quran Recite Aligner is ready!';
            }
          } catch {}
        }
      }
    }
  } catch (err: any) {
    if (err.name !== 'AbortError') {
      errorMessage.value = err.message || 'Aligner setup failed';
    }
  } finally {
    abortController = null;
  }
}

defineExpose({
  open,
  close,
});
</script>

<style scoped>
.modal-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.78);
  backdrop-filter: blur(10px);
  z-index: 10000;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 16px;
}

.update-modal {
  width: 100%;
  max-width: 500px;
  background: rgba(15, 23, 42, 0.98);
  border: 1px solid rgba(255, 255, 255, 0.12);
  border-radius: 14px;
  box-shadow: 0 24px 56px rgba(0, 0, 0, 0.75);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.modal-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  padding: 20px 24px 16px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
}

.header-titles {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.title-with-icon {
  display: flex;
  align-items: center;
  gap: 8px;
}

.modal-title {
  margin: 0;
  font-size: 1.05rem;
  font-weight: 700;
  color: #f8fafc;
}

.modal-subtitle {
  font-size: 0.8rem;
  color: #94a3b8;
}

.close-btn {
  background: transparent;
  border: none;
  color: #94a3b8;
  cursor: pointer;
  padding: 4px;
  border-radius: 6px;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.15s ease;
}

.close-btn:hover {
  background: rgba(255, 255, 255, 0.1);
  color: #ffffff;
}

.version-banner {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 12px;
  padding: 16px 24px;
  background: rgba(255, 255, 255, 0.02);
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
}

.version-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  border-radius: 9999px;
  font-size: 0.8rem;
  font-weight: 600;
}

.current-pill {
  background: rgba(148, 163, 184, 0.12);
  color: #cbd5e1;
}

.latest-pill {
  background: rgba(56, 189, 248, 0.15);
  color: #38bdf8;
  border: 1px solid rgba(56, 189, 248, 0.3);
}

.arrow-icon {
  color: #64748b;
}

.changelog-container {
  padding: 16px 24px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.changelog-label {
  font-size: 0.75rem;
  font-weight: 600;
  color: #94a3b8;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.changelog-content {
  background: rgba(0, 0, 0, 0.35);
  border: 1px solid rgba(255, 255, 255, 0.06);
  border-radius: 8px;
  padding: 12px;
  max-height: 140px;
  overflow-y: auto;
}

.changelog-text {
  margin: 0;
  font-family: inherit;
  font-size: 0.8rem;
  color: #cbd5e1;
  white-space: pre-wrap;
  word-break: break-word;
  line-height: 1.5;
}

.setup-checklist {
  padding: 18px 24px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.checklist-item {
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 0.85rem;
  color: #64748b;
  transition: color 0.2s ease;
}

.checklist-item.active {
  color: #f1f5f9;
  font-weight: 500;
}

.checklist-item.done {
  color: #38bdf8;
}

.check-bullet {
  width: 18px;
  height: 18px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.bullet-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #475569;
}

.checklist-item.active .bullet-dot {
  background: #38bdf8;
  box-shadow: 0 0 8px #38bdf8;
}

.progress-section {
  padding: 16px 24px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  background: rgba(0, 0, 0, 0.25);
  border-top: 1px solid rgba(255, 255, 255, 0.06);
}

.progress-info-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 0.78rem;
}

.progress-status-text {
  color: #cbd5e1;
  font-weight: 500;
  max-width: 80%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.progress-percent-text {
  color: #38bdf8;
  font-weight: 700;
}

.progress-bar-track {
  height: 6px;
  background: rgba(255, 255, 255, 0.08);
  border-radius: 9999px;
  overflow: hidden;
}

.progress-bar-fill {
  height: 100%;
  background: linear-gradient(90deg, #0284c7, #38bdf8);
  transition: width 0.2s ease;
  border-radius: 9999px;
}

.progress-bar-fill.done-bar {
  background: #10b981;
}

.error-box {
  margin: 12px 24px 0;
  padding: 10px 14px;
  background: rgba(239, 68, 68, 0.15);
  border: 1px solid rgba(239, 68, 68, 0.3);
  border-radius: 8px;
  color: #fca5a5;
  font-size: 0.8rem;
  display: flex;
  align-items: center;
  gap: 8px;
}

.modal-footer {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 10px;
  padding: 16px 24px 20px;
}

.btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 8px 16px;
  font-size: 0.82rem;
  font-weight: 600;
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.15s ease;
  border: none;
}

.btn-secondary {
  background: rgba(255, 255, 255, 0.08);
  color: #cbd5e1;
}

.btn-secondary:hover:not(:disabled) {
  background: rgba(255, 255, 255, 0.14);
  color: #ffffff;
}

.btn-primary {
  background: #0284c7;
  color: #ffffff;
}

.btn-primary:hover:not(:disabled) {
  background: #0369a1;
}

.btn-done {
  background: #10b981;
}

.btn-done:hover {
  background: #059669;
}

.btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.text-accent {
  color: #38bdf8;
}

.text-success {
  color: #10b981;
}
</style>
