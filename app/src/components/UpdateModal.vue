<template>
  <div v-if="visible" class="modal-backdrop" @click="close">
    <div class="update-modal glass-panel" @click.stop>
      <!-- Header -->
      <div class="modal-header">
        <div class="header-titles">
          <div class="title-with-icon">
            <Sparkles :size="18" class="text-accent" />
            <h3 class="modal-title">New Update Available</h3>
          </div>
          <span class="modal-subtitle">A newer version of Quran Recite2Text is ready to install</span>
        </div>
        <button class="btn-icon close-btn" @click="close" title="Close">
          <X :size="16" />
        </button>
      </div>

      <!-- Version Diff Badge Row -->
      <div class="version-banner">
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

      <!-- Release Notes / Changelog -->
      <div class="changelog-container">
        <span class="changelog-label">What's New in this Release:</span>
        <div class="changelog-content">
          <pre class="changelog-text">{{ versionService.changelog.value || 'Bug fixes, performance optimizations, and stability improvements.' }}</pre>
        </div>
      </div>

      <!-- Progress Section (While Downloading / Installing) -->
      <div v-if="versionService.updateState.value === 'downloading' || versionService.updateState.value === 'installing'" class="progress-section">
        <div class="progress-info-row">
          <span class="progress-status-text">
            {{ versionService.updateState.value === 'installing' ? 'Installing update package...' : 'Downloading update...' }}
          </span>
          <span class="progress-percent-text">{{ versionService.downloadProgress.value }}%</span>
        </div>
        <div class="progress-bar-track">
          <div class="progress-bar-fill" :style="{ width: `${versionService.downloadProgress.value}%` }"></div>
        </div>
      </div>

      <!-- Error Message if failed -->
      <div v-if="versionService.updateError.value" class="error-box">
        <AlertTriangle :size="14" />
        <span>{{ versionService.updateError.value }}</span>
      </div>

      <!-- Footer Buttons -->
      <div class="modal-footer">
        <button class="btn btn-secondary" @click="close" :disabled="isBusy">Later</button>
        <button 
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
import { X, Sparkles, ArrowRight, DownloadCloud, Loader2, AlertTriangle } from 'lucide-vue-next';

const visible = ref(false);

const isBusy = computed(() => {
  return versionService.updateState.value === 'downloading' || versionService.updateState.value === 'installing';
});

const updateButtonText = computed(() => {
  if (versionService.updateState.value === 'downloading') return `Downloading (${versionService.downloadProgress.value}%)`;
  if (versionService.updateState.value === 'installing') return 'Installing & Restarting...';
  if (versionService.updateState.value === 'done') return 'Relaunching...';
  return 'Update Now';
});

function open() {
  visible.value = true;
}

function close() {
  if (isBusy.value) return;
  visible.value = false;
}

async function startUpdate() {
  await versionService.downloadAndInstall();
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
  background: rgba(0, 0, 0, 0.75);
  backdrop-filter: blur(8px);
  z-index: 10000;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 16px;
}

.update-modal {
  width: 100%;
  max-width: 480px;
  background: rgba(15, 23, 42, 0.96);
  border: 1px solid rgba(255, 255, 255, 0.12);
  border-radius: 12px;
  box-shadow: 0 20px 48px rgba(0, 0, 0, 0.65);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.modal-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  padding: 16px 20px 14px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
}

.title-with-icon {
  display: flex;
  align-items: center;
  gap: 8px;
}

.modal-title {
  font-size: 16px;
  font-weight: 700;
  color: #fff;
  margin: 0;
}

.modal-subtitle {
  font-size: 11px;
  color: var(--text-dim);
  margin-top: 3px;
  display: block;
}

.close-btn {
  background: transparent;
  border: none;
  color: var(--text-dim);
  cursor: pointer;
  padding: 4px;
  border-radius: 4px;
  transition: all 0.1s ease;
}
.close-btn:hover {
  color: #fff;
  background: rgba(255, 255, 255, 0.08);
}

.version-banner {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 12px;
  padding: 14px 20px;
  background: rgba(0, 0, 0, 0.25);
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
}

.version-pill {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 12px;
  border-radius: 20px;
  font-size: 12px;
  font-weight: 600;
}

.current-pill {
  background: rgba(255, 255, 255, 0.06);
  border: 1px solid rgba(255, 255, 255, 0.1);
  color: var(--text-dim);
}

.latest-pill {
  background: rgba(56, 189, 248, 0.15);
  border: 1px solid rgba(56, 189, 248, 0.35);
  color: #38bdf8;
}

.arrow-icon {
  color: var(--text-dim);
}

.changelog-container {
  padding: 16px 20px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.changelog-label {
  font-size: 11px;
  font-weight: 600;
  color: var(--text-dim);
}

.changelog-content {
  background: rgba(0, 0, 0, 0.3);
  border: 1px solid rgba(255, 255, 255, 0.06);
  border-radius: 8px;
  padding: 12px;
  max-height: 180px;
  overflow-y: auto;
}

.changelog-text {
  margin: 0;
  font-family: inherit;
  font-size: 12px;
  line-height: 1.6;
  color: var(--text-secondary);
  white-space: pre-wrap;
  word-break: break-word;
}

.progress-section {
  padding: 0 20px 14px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.progress-info-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 11px;
}

.progress-status-text {
  color: #38bdf8;
  font-weight: 500;
}

.progress-percent-text {
  color: var(--text-dim);
  font-family: monospace;
}

.progress-bar-track {
  width: 100%;
  height: 6px;
  background: rgba(255, 255, 255, 0.08);
  border-radius: 999px;
  overflow: hidden;
}

.progress-bar-fill {
  height: 100%;
  background: #38bdf8;
  border-radius: 999px;
  transition: width 0.2s ease;
}

.error-box {
  margin: 0 20px 14px;
  padding: 8px 12px;
  background: rgba(239, 68, 68, 0.15);
  border: 1px solid rgba(239, 68, 68, 0.3);
  border-radius: 6px;
  color: #fca5a5;
  font-size: 12px;
  display: flex;
  align-items: center;
  gap: 8px;
}

.modal-footer {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
  padding: 14px 20px;
  background: rgba(0, 0, 0, 0.2);
  border-top: 1px solid rgba(255, 255, 255, 0.08);
}

.btn {
  padding: 7px 16px;
  font-size: 12px;
  font-weight: 600;
  border-radius: 6px;
  border: none;
  cursor: pointer;
  transition: all 0.15s ease;
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.btn-secondary {
  background: rgba(255, 255, 255, 0.08);
  color: var(--text-secondary);
}
.btn-secondary:hover:not(:disabled) {
  background: rgba(255, 255, 255, 0.12);
  color: #fff;
}

.btn-primary {
  background: #0284c7;
  color: #fff;
}
.btn-primary:hover:not(:disabled) {
  background: #0369a1;
}
.btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
</style>
