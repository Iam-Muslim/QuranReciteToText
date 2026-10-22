<template>
  <div v-if="visible" class="modal-backdrop" @click.self="handleBackdropClick">
    <div class="update-modal glass-panel anim-scale" @click.stop>
      <!-- Header — title + close only -->
      <div class="modal-header">
        <span v-if="!isBusy || isDone" class="update-badge">
          <Layers :size="13" />
          {{ dialogMode === 'app_update' ? 'Update' : 'Setup' }}
        </span>
        <span v-else class="update-badge badge-busy">{{ modalTitle }}</span>
        <button 
          v-if="!isBusy || isDone" 
          class="btn-icon close-btn" 
          @click="close" 
          title="Close"
        >
          <X :size="15" />
        </button>
      </div>

      <!-- Big title -->
      <h3 class="modal-title">{{ modalTitle }}</h3>
      <span class="modal-subtitle">{{ modalSubtitle }}</span>

      <!-- App Update Version Row -->
      <div v-if="dialogMode === 'app_update'" class="version-banner">
        <span class="ver-val">{{ versionService.currentVersion.value }}</span>
        <ArrowRight :size="14" class="arrow-icon" />
        <span class="ver-val ver-new">v{{ versionService.latestVersion.value }}</span>
      </div>

      <!-- Release Notes / Changelog for App Update -->
      <div v-if="dialogMode === 'app_update'" class="changelog-content">
        <pre class="changelog-text">{{ versionService.changelog.value || 'Bug fixes, performance optimizations, and stability improvements.' }}</pre>
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
          v-if="errorMessage && dialogMode === 'app_init' && !isDone" 
          class="btn btn-primary" 
          @click="retryAppInit"
        >
          <RefreshCw :size="14" />
          <span>Retry Setup</span>
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
import { ref, computed, onMounted, onUnmounted } from 'vue';
import { versionService } from '../services/VersionService';
import { 
  X, 
  ArrowRight, 
  DownloadCloud, 
  Loader2, 
  AlertTriangle, 
  CheckCircle2, 
  Layers,
  RefreshCw 
} from 'lucide-vue-next';

export type DialogMode = 'app_init' | 'app_update';

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
  return 'New Update Available';
});

const modalSubtitle = computed(() => {
  if (dialogMode.value === 'app_init') return 'Preparing portable Python runtime, dependencies & speech models';
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

function handleKeydown(e: KeyboardEvent) {
  if (!visible.value) return;
  if (e.key === 'Escape' && (!isBusy.value || isDone.value)) {
    close();
  }
}

onMounted(() => window.addEventListener('keydown', handleKeydown));
onUnmounted(() => {
  window.removeEventListener('keydown', handleKeydown);
  if (unlistenFn) {
    unlistenFn();
    unlistenFn = null;
  }
});

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
  setupStatusMessage.value = 'Preparing portable Python environment...';
  setupProgress.value = 5;

  try {
    const isTauri = typeof window !== 'undefined' && (('__TAURI__' in (window as any)) || ('__TAURI_INTERNALS__' in (window as any)));
    if (isTauri) {
      const { listen } = await import('@tauri-apps/api/event');
      unlistenFn = await listen<{ message: string; progress?: number; ready?: boolean; error?: string }>('install-status', (event) => {
        if (event.payload.error) {
          errorMessage.value = event.payload.error;
          setupStatusMessage.value = 'Setup encountered an error. Please check internet connection.';
          return;
        }
        setupStatusMessage.value = event.payload.message || 'Installing...';
        if (typeof event.payload.progress === 'number') {
          // Strictly monotonic: progress only increases, never goes backward
          setupProgress.value = Math.max(setupProgress.value, event.payload.progress);
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

async function retryAppInit() {
  errorMessage.value = '';
  setupStatusMessage.value = 'Retrying engine setup...';
  setupProgress.value = 5;
  try {
    const { invoke } = await import('@tauri-apps/api/core');
    await invoke('ensure_engine');
  } catch (err: any) {
    errorMessage.value = err?.message || String(err);
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
  background: rgba(4, 5, 9, 0.64);
  backdrop-filter: blur(12px);
  z-index: 10000;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 16px;
  animation: fade-in var(--dur-base) var(--ease-out) both;
}

.update-modal {
  width: 100%;
  max-width: 460px;
  background: var(--bg-surface);
  border: 1px solid var(--border-medium);
  border-radius: var(--radius-xl);
  box-shadow: var(--shadow-e4);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.modal-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 18px 0;
}

.update-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 0.68rem;
  font-weight: 700;
  letter-spacing: 0.05em;
  text-transform: uppercase;
  color: var(--accent-primary);
  background: var(--accent-subtle);
  border: 1px solid var(--accent-border);
  border-radius: var(--radius-pill);
  padding: 3px 10px;
}
.update-badge.badge-busy {
  color: var(--text-secondary);
  background: rgba(255, 255, 255, 0.04);
  border-color: var(--border-subtle);
}

.modal-title {
  margin: 10px 18px 0;
  font-size: 1.1rem;
  font-weight: 700;
  letter-spacing: -0.01em;
  color: var(--text-main);
}

.modal-subtitle {
  display: block;
  font-size: var(--text-xs);
  color: var(--text-muted);
  padding: 3px 18px 0;
}

.close-btn {
  background: transparent;
  border: none;
  color: var(--text-muted);
  cursor: pointer;
  padding: 4px;
  border-radius: var(--radius-xs);
  display: flex;
  align-items: center;
  justify-content: center;
  transition: color var(--dur-fast) var(--ease-out),
              background var(--dur-fast) var(--ease-out);
}

.close-btn:hover {
  background: var(--bg-surface-hover);
  color: var(--text-main);
}

/* Version row — single quiet mono line */
.version-banner {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  padding: 14px 18px 4px;
  font-family: var(--font-mono);
}
.ver-val {
  font-size: 0.88rem;
  font-weight: 600;
  color: var(--text-muted);
}
.ver-val.ver-new {
  color: var(--accent-primary);
  text-shadow: var(--shadow-e1);
}
.arrow-icon {
  color: var(--text-dim);
}

.changelog-content {
  margin: 12px 18px;
  background: rgba(0, 0, 0, 0.3);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-md);
  padding: 12px;
  max-height: 140px;
  overflow-y: auto;
}

.changelog-text {
  margin: 0;
  font-family: inherit;
  font-size: 0.8rem;
  color: var(--text-secondary);
  white-space: pre-wrap;
  word-break: break-word;
  line-height: 1.5;
}

.setup-checklist {
  padding: 16px 18px 4px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.checklist-item {
  display: flex;
  align-items: center;
  gap: 11px;
  font-size: 0.82rem;
  color: var(--text-dim);
  transition: color var(--dur-base) var(--ease-out);
}

.checklist-item.active {
  color: var(--text-main);
  font-weight: 500;
}

.checklist-item.done {
  color: var(--accent-primary);
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
  background: var(--text-dim);
}

.checklist-item.active .bullet-dot {
  background: var(--accent-primary);
  box-shadow: var(--shadow-e1);
}

.progress-section {
  padding: 14px 18px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.progress-info-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 0.78rem;
}

.progress-status-text {
  color: var(--text-secondary);
  font-weight: 500;
  max-width: 80%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.progress-percent-text {
  color: var(--accent-primary);
  font-weight: 700;
  font-family: var(--font-mono);
}

.progress-bar-track {
  height: 5px;
  background: rgba(255, 255, 255, 0.07);
  border-radius: var(--radius-pill);
  overflow: hidden;
}

.progress-bar-fill {
  height: 100%;
  background: var(--accent-primary);
  transition: width var(--dur-base) var(--ease-out);
  border-radius: var(--radius-pill);
}

.progress-bar-fill.done-bar {
  background: var(--emerald-primary);
  box-shadow: var(--shadow-e1);
}

.error-box {
  margin: 10px 18px 0;
  padding: 10px 14px;
  background: var(--ruby-bg);
  border: 1px solid var(--ruby-border);
  border-radius: var(--radius-md);
  color: #fda4af;
  font-size: var(--text-xs);
  display: flex;
  align-items: center;
  gap: 8px;
  animation: rise-in var(--dur-rise) var(--ease-spring) both;
}

.modal-footer {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 10px;
  padding: 16px 18px 18px;
}

.btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 8px 16px;
  font-size: var(--text-xs);
  font-weight: 600;
  border-radius: var(--radius-sm);
  cursor: pointer;
  transition: filter var(--dur-fast) var(--ease-out),
              box-shadow var(--dur-fast) var(--ease-out);
  border: none;
}

.btn-secondary {
  background: var(--bg-surface-elevated);
  color: var(--text-secondary);
  border: 1px solid var(--border-subtle);
}

.btn-secondary:hover:not(:disabled) {
  background: var(--bg-surface-hover);
  color: var(--text-main);
  border-color: var(--border-medium);
}

.btn-primary {
  background: var(--accent-primary);
  color: #ffffff;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.18),
              var(--shadow-e2);
}

.btn-primary:hover:not(:disabled) {
  filter: brightness(1.1);
  box-shadow: var(--shadow-e2);
}

.btn-done {
  background: var(--emerald-primary);
}

.btn-done:hover:not(:disabled) {
  filter: brightness(1.1);
}

.btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.text-success {
  color: var(--emerald-primary);
}
</style>
