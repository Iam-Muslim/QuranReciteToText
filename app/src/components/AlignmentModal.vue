<template>
  <div>
    <!-- Alignment Dialog -->
    <div v-if="visible" class="align-overlay" @click.self="close">
      <section
        class="align-dialog alignment-modal"
        :class="{ 'is-running': isRunning, 'is-complete': isComplete }"
        role="dialog"
        aria-modal="true"
        aria-labelledby="alignment-dialog-title"
      >
        <div class="dialog-aura" aria-hidden="true"></div>

        <!-- Header -->
        <header class="align-header">
          <div class="brand">
            <div class="brand-mark">
              <AudioWaveform :size="19" />
            </div>
            <div class="brand-text">
              <h2 id="alignment-dialog-title">Add Recitation</h2>
            </div>
          </div>

          <div class="header-controls">
            <div v-if="!isRunning && !isComplete" class="mode-switch" role="tablist" aria-label="Input mode">
              <button
                type="button"
                role="tab"
                class="mode-tab"
                :class="{ active: activeMode === 'align' }"
                :aria-selected="activeMode === 'align'"
                @click="activeMode = 'align'"
              >
                <ListMusic :size="13" />
                <span>Align</span>
                <span v-if="filesQueue.length + scannedFiles.length > 0" class="mode-count">
                  {{ filesQueue.length + scannedFiles.length }}
                </span>
              </button>
              <button
                type="button"
                role="tab"
                class="mode-tab"
                :class="{ active: activeMode === 'timings' }"
                :aria-selected="activeMode === 'timings'"
                @click="activeMode = 'timings'"
              >
                <FileJson :size="13" />
                <span>Import Timing</span>
                <span v-if="timingPairs.length > 0" class="mode-count">{{ timingPairs.length }}</span>
              </button>
            </div>

            <button
              v-if="!isRunning"
              type="button"
              class="icon-btn close-btn"
              aria-label="Close dialog"
              title="Close"
              @click="close"
            >
              <X :size="16" />
            </button>
          </div>
        </header>

        <!-- Body -->
        <div class="align-body">
          <!-- Session configuration -->
          <div v-if="!isRunning && !isComplete" class="settings-row">
            <label class="setting-field">
              <span class="setting-label">Riwayah</span>
              <div class="select-shell">
                <select
                  v-model="selectedRiwayah"
                  class="riwayah-select"
                  :disabled="isRunning"
                  aria-label="Recitation tradition"
                >
                  <option value="Hafs">حفص عن عاصم · Hafs</option>
                  <option value="Warsh">ورش عن نافع · Warsh</option>
                  <option value="Qaloon">قالون عن نافع · Qalun</option>
                  <option value="Shouba">شعبة عن عاصم · Shu'bah</option>
                  <option value="Doori">الدوري عن أبي عمرو · Al-Duri</option>
                  <option value="Soosi">السوسي عن أبي عمرو · Al-Susi</option>
                  <option value="Bazzi">البزي عن ابن كثير · Al-Bazzi</option>
                  <option value="Qumbul">قنبل عن ابن كثير · Qunbul</option>
                </select>
                <ChevronDown :size="14" class="select-chevron" aria-hidden="true" />
              </div>
            </label>

            <span class="setting-sep" aria-hidden="true"></span>

            <button
              type="button"
              class="engine-toggle"
              :class="{ active: fastMode }"
              role="switch"
              :aria-checked="fastMode"
              title="Use all available hardware threads"
              @click="fastMode = !fastMode"
            >
              <span class="engine-icon">
                <Zap :size="15" />
              </span>
              <span class="engine-copy">
                <span class="setting-label">Fast engine</span>
                <span class="engine-state">{{ fastMode ? 'Multi-threaded' : 'Standard' }}</span>
              </span>
              <span class="toggle-track" aria-hidden="true">
                <span class="toggle-thumb"></span>
              </span>
            </button>
          </div>

          <!-- Align: Individual MP3s / Batch folder -->
          <div v-if="activeMode === 'align' && !isRunning && !isComplete" class="pane-option-bar">
            <div class="opt-tabs" role="tablist" aria-label="Alignment input">
              <button
                type="button"
                role="tab"
                class="opt-tab"
                :class="{ active: alignInput === 'files' }"
                @click="alignInput = 'files'"
              >
                <Files :size="12" />
                <span>Individual MP3s</span>
              </button>
              <button
                type="button"
                role="tab"
                class="opt-tab"
                :class="{ active: alignInput === 'dir' }"
                @click="alignInput = 'dir'"
              >
                <FolderTree :size="12" />
                <span>Batch folder</span>
              </button>
            </div>
          </div>

          <!-- Engine missing: calm notice, Import Timing still works -->
          <div v-if="missingEngineBanner" class="engine-note">
            <TriangleAlert :size="14" />
            <p>
              Alignment needs the local engine (Python + models) and it is not installed yet.
              <strong>Import Timing works fully without it.</strong>
            </p>
            <button type="button" class="text-btn" @click="requestEngineSetup">
              <Settings :size="12" />
              <span>Setup</span>
            </button>
          </div>

          <!-- Idle: Files -->
          <div v-if="activeMode === 'align' && alignInput === 'files' && !isRunning && !isComplete" class="mode-pane">
            <div
              class="dropzone"
              :class="{ 'dropzone-active': isDragging, compact: filesQueue.length > 0 }"
              @dragenter.prevent="isDragging = true"
              @dragover.prevent="isDragging = true"
              @dragleave.prevent="isDragging = false"
              @drop.prevent="onDropFiles"
              @click="triggerFilePick"
            >
              <div class="drop-icon">
                <AudioWaveform :size="26" />
              </div>
              <div class="drop-copy">
                <h3>{{ filesQueue.length > 0 ? 'Add more recitations' : 'Drop recitations here' }}</h3>
                <p><span class="browse-link">Browse files</span> or drag and drop</p>
                <span class="formats">MP3 · WAV · M4A · FLAC · OGG</span>
              </div>
              <input
                ref="fileInput"
                type="file"
                multiple
                accept="audio/*,video/*"
                class="visually-hidden"
                @change="onFilesChosen"
              />
            </div>

            <div v-if="filesQueue.length > 0" class="queue">
              <div class="queue-heading">
                <div>
                  <h3>{{ filesQueue.length }} {{ filesQueue.length === 1 ? 'recitation' : 'recitations' }}</h3>
                  <p v-if="queueTotalBytes > 0">{{ formatBytes(queueTotalBytes) }} total</p>
                  <p v-else>Ready to align</p>
                </div>
                <button type="button" class="text-btn" @click="clearQueue">Clear all</button>
              </div>

              <div class="queue-list">
                <div v-for="(item, idx) in filesQueue" :key="item.id" class="file-row">
                  <div class="file-icon">
                    <FileAudio :size="15" />
                  </div>
                  <div class="file-copy">
                    <span class="file-name" :title="item.file.name">{{ item.file.name }}</span>
                    <span class="file-meta">
                      <span v-if="item.file.size">{{ formatBytes(item.file.size) }}</span>
                      <span v-if="item.file.size" class="meta-dot">·</span>
                      <span class="status-text" :class="item.status">{{ getStatusText(item.status) }}</span>
                    </span>
                  </div>
                  <span class="status-dot" :class="item.status" :title="getStatusText(item.status)"></span>
                  <button
                    type="button"
                    class="row-action"
                    :aria-label="`Remove ${item.file.name}`"
                    title="Remove"
                    @click.stop="removeQueueItem(idx)"
                  >
                    <X :size="13" />
                  </button>
                </div>
              </div>
            </div>
          </div>

          <!-- Import Timing: Individual / Batch folder -->
          <div v-if="activeMode === 'timings' && !isRunning && !isComplete" class="pane-option-bar">
            <div class="opt-tabs" role="tablist" aria-label="Import format">
              <button
                type="button"
                role="tab"
                class="opt-tab"
                :class="{ active: timingInput === 'single' }"
                @click="timingInput = 'single'"
              >
                <Files :size="12" />
                <span>Individual</span>
              </button>
              <button
                type="button"
                role="tab"
                class="opt-tab"
                :class="{ active: timingInput === 'batch' }"
                @click="timingInput = 'batch'"
              >
                <FolderTree :size="12" />
                <span>Batch folder</span>
              </button>
            </div>
          </div>

          <!-- Idle: Timings (JSON + audio) -->
          <div v-if="activeMode === 'timings' && !isRunning && !isComplete" class="mode-pane">
            <!-- Individual: pair audio + json by hand -->
            <div
              v-if="timingInput === 'single'"
              class="dropzone timing-dropzone"
              :class="{ 'dropzone-active': isDragging }"
              @dragenter.prevent="isDragging = true"
              @dragover.prevent="isDragging = true"
              @dragleave.prevent="isDragging = false"
              @drop.prevent="onDropTiming"
              @click="triggerTimingPick"
            >
              <div class="drop-icon">
                <FileJson :size="24" />
              </div>
              <div class="drop-copy">
                <h3>{{ timingPairs.length > 0 ? `${timingPairs.length} pair${timingPairs.length === 1 ? '' : 's'} ready to import` : 'Drop timings JSON (audio optional)' }}</h3>
                <p><span class="browse-link">Browse files</span> — add a timings JSON, its same-named audio is optional</p>
                <span class="formats">JSON · MP3 · WAV · M4A · FLAC · OGG</span>
              </div>
            </div>

            <!-- Batch: pick a folder -->
            <div
              v-else
              class="dropzone timing-dropzone"
              @click="pickTimingFolder"
            >
              <div class="drop-icon">
                <FolderTree :size="24" />
              </div>
              <div class="drop-copy">
                <h3>Import every pair in a folder</h3>
                <p><span class="browse-link">Choose a folder</span> — each audio file needs a same-named JSON next to it</p>
                <span class="formats">001.mp3 + 001.json · 002.mp3 + 002.json · …</span>
              </div>
            </div>

            <div class="timing-actions">
              <button type="button" class="btn-soft" :class="{ 'help-open': showFormatHelp }" @click="showFormatHelp = !showFormatHelp" title="Show the accepted JSON format">
                <BookOpen :size="13" />
                <span>Format guide</span>
                <ChevronDown :size="12" :class="{ 'chev-rotated': showFormatHelp }" />
              </button>
            </div>

            <!-- Accepted schema guide -->
            <div v-if="showFormatHelp" class="format-help">
              <h4>Timings JSON — accepted format</h4>
              <ul>
                <li v-for="(rule, i) in TIMING_RULES" :key="i">{{ rule }}</li>
              </ul>
              <pre class="format-code">{{ EXAMPLE_TIMINGS_STRING }}</pre>
              <div class="format-help-actions">
                <button type="button" class="text-btn" @click="saveExampleJson"><Save :size="12" /><span>Save example</span></button>
                <button type="button" class="text-btn" @click="copyExampleJson"><ClipboardCopy :size="12" /><span>Copy example</span></button>
              </div>
            </div>

            <!-- Pair list -->
            <div v-if="timingPairs.length > 0" class="queue">
              <div class="queue-heading">
                <div>
                  <h3>{{ timingPairs.length }} {{ timingPairs.length === 1 ? 'pair' : 'pairs' }}</h3>
                  <p>Same-named audio + JSON — audio is optional</p>
                </div>
                <button type="button" class="text-btn" @click="timingPairs = []">Clear all</button>
              </div>

              <div class="queue-list">
                <div v-for="pair in timingPairs" :key="pair.id" class="file-row">
                  <div class="file-icon">
                    <FileJson :size="15" />
                  </div>
                  <div class="file-copy">
                    <span class="file-name" :title="pair.audio?.name || `${pair.base}.json`">{{ pair.audio?.name || `${pair.base}.json` }}</span>
                    <span class="file-meta">
                      <span v-if="pair.json" class="json-ok">JSON ✓</span>
                      <span v-else class="json-missing">JSON missing — pair by file name</span>
                      <span v-if="pairNeedsAudio(pair)" class="no-audio-chip">No audio — attach later</span>
                      <span v-if="pair.wordCount" class="meta-dot">·</span>
                      <span v-if="pair.wordCount">{{ pair.wordCount }} words</span>
                      <template v-if="pair.errorMessage">
                        <span class="meta-dot">·</span>
                        <span class="status-text error" :title="pair.errorMessage">{{ pair.errorMessage }}</span>
                      </template>
                    </span>
                  </div>
                  <span class="status-dot" :class="pair.status === 'importing' ? 'aligning' : pair.status"></span>
                  <button
                    type="button"
                    class="row-action"
                    :aria-label="`Remove ${pair.base}`"
                    title="Remove"
                    @click.stop="removeTimingPair(pair.id)"
                  >
                    <X :size="13" />
                  </button>
                </div>
              </div>
            </div>
          </div>

          <!-- Idle: Folder -->
          <div v-if="activeMode === 'align' && alignInput === 'dir' && !isRunning && !isComplete" class="mode-pane">
            <div class="path-shell">
              <button type="button" class="path-browse" :disabled="isScanningDir" @click="pickDirectory">
                <FolderOpen :size="15" />
                <span>Choose folder</span>
              </button>
              <span class="path-divider" aria-hidden="true"></span>
              <input
                v-model="dirPath"
                type="text"
                class="path-input"
                placeholder="or paste a folder path…"
                aria-label="Folder path"
                @keydown.enter="scanDirectory"
              />
              <button
                v-if="dirPath.trim()"
                type="button"
                class="path-scan"
                :disabled="isScanningDir"
                title="Scan folder"
                aria-label="Scan folder"
                @click="scanDirectory"
              >
                <Search :size="15" :class="{ 'spin-icon': isScanningDir }" />
              </button>
            </div>
            <p class="path-hint">
              Recursively finds every audio file in the folder.
              <span v-if="isScanningDir" class="scanning-label">Scanning…</span>
            </p>

            <div v-if="scannedFiles.length > 0" class="scan-card">
              <div class="scan-summary">
                <div class="scan-icon">
                  <FolderTree :size="17" />
                </div>
                <div class="scan-copy">
                  <h3>{{ scannedFiles.length }} audio {{ scannedFiles.length === 1 ? 'file' : 'files' }}</h3>
                  <p>{{ formatBytes(scannedTotalBytes) }} · ready for batch alignment</p>
                </div>
                <span class="scan-ready">
                  <span class="status-dot completed"></span>
                  Ready
                </span>
              </div>
              <div class="scan-list">
                <div v-for="f in scannedFiles.slice(0, 15)" :key="f.full_path || f.name" class="scan-row">
                  <FileAudio :size="12" />
                  <span class="scan-name">{{ f.name || f.rel_path }}</span>
                  <span class="scan-size">{{ formatBytes(f.size) }}</span>
                </div>
                <div v-if="scannedFiles.length > 15" class="scan-more">
                  +{{ scannedFiles.length - 15 }} more files
                </div>
              </div>
            </div>

            <div v-else-if="dirScanError" class="inline-error">
              <AlertTriangle :size="15" />
              <span>{{ dirScanError }}</span>
            </div>
          </div>

          <!-- Running -->
          <div v-if="isRunning" class="run-pane">
            <div class="run-top">
              <div class="run-eyebrow">
                <span class="live-dot" aria-hidden="true"></span>
                <span>{{ currentStageLabel }}</span>
                <span v-if="filesQueue.length > 1" class="run-queue">
                  {{ currentQueueIndex + 1 }} / {{ filesQueue.length }}
                </span>
                <span v-else-if="activeMode === 'timings' && importTotal > 0" class="run-queue">
                  {{ importIndex + 1 }} / {{ importTotal }}
                </span>
                <span v-if="elapsedLabel" class="run-elapsed">{{ elapsedLabel }}</span>
              </div>
              <div class="run-percent">
                {{ progressPercent.toFixed(0) }}<span>%</span>
              </div>
            </div>

            <h3 class="run-title" :title="currentProcessingFileName || importCurrentName || 'Folder batch'">
              {{ currentProcessingFileName || importCurrentName || (alignInput === 'dir' && activeMode === 'align' ? 'Folder batch' : 'Preparing alignment…') }}
            </h3>
            <p class="run-status" aria-live="polite">{{ statusMessage }}</p>

            <div
              class="progress-track"
              :class="{ indeterminate: progressIndeterminate }"
              role="progressbar"
              :aria-valuenow="Math.round(progressPercent)"
              aria-valuemin="0"
              aria-valuemax="100"
              :aria-busy="progressIndeterminate || undefined"
            >
              <div class="progress-fill" :style="{ width: `${progressPercent}%` }">
                <span class="progress-sheen" aria-hidden="true"></span>
              </div>
            </div>

            <div v-if="activeMode !== 'timings'" class="stage-rail">
              <div class="stage" :class="getStepClass('vad')">
                <span class="stage-dot">
                  <Check v-if="getStepClass('vad') === 'step-done'" :size="8" />
                </span>
                <span class="stage-name">Voice</span>
              </div>
              <span class="stage-link" :class="{ done: getStepClass('vad') === 'step-done' }"></span>
              <div class="stage" :class="getStepClass('transcribing')">
                <span class="stage-dot">
                  <Check v-if="getStepClass('transcribing') === 'step-done'" :size="8" />
                </span>
                <span class="stage-name">Speech</span>
              </div>
              <span class="stage-link" :class="{ done: getStepClass('transcribing') === 'step-done' }"></span>
              <div class="stage" :class="getStepClass('aligning')">
                <span class="stage-dot">
                  <Check v-if="getStepClass('aligning') === 'step-done'" :size="8" />
                </span>
                <span class="stage-name">Align</span>
              </div>
              <span class="stage-link" :class="{ done: getStepClass('aligning') === 'step-done' }"></span>
              <div class="stage" :class="getStepClass('matching')">
                <span class="stage-dot">
                  <Check v-if="getStepClass('matching') === 'step-done'" :size="8" />
                </span>
                <span class="stage-name">Match</span>
              </div>
            </div>

            <div class="run-meta">
              <span v-if="speedX > 0" class="meta-chip">
                <Gauge :size="12" />
                {{ speedX.toFixed(1) }}× realtime
              </span>
              <span v-if="filesQueue.length > 1" class="meta-chip">
                <ListMusic :size="12" />
                {{ filesQueue.length }} in queue
              </span>
              <span v-else-if="activeMode === 'timings' && importTotal > 1" class="meta-chip">
                <FileJson :size="12" />
                {{ importTotal }} pairs
              </span>
              <button
                type="button"
                class="log-toggle"
                :aria-expanded="showLogs"
                @click="showLogs = !showLogs"
              >
                <Terminal :size="12" />
                <span>Activity</span>
                <ChevronDown :size="12" :class="{ rotated: showLogs }" />
              </button>
            </div>

            <div v-show="showLogs" class="console" ref="consoleBoxRef">
              <div v-if="consoleLogs.length === 0" class="console-empty">Waiting for engine output…</div>
              <div v-for="(log, idx) in consoleLogs" :key="idx" class="console-line" :class="log.type">
                <span>{{ log.text }}</span>
              </div>
            </div>
          </div>

          <!-- Complete -->
          <div v-if="isComplete" class="complete-pane">
            <div class="success-orbit" aria-hidden="true">
              <div class="success-mark">
                <Check :size="28" />
              </div>
            </div>
            <span class="eyebrow">Alignment complete</span>
            <h3>Timings are ready for review</h3>
            <p class="complete-copy">{{ statusMessage }}</p>
            <div class="complete-stats">
              <div class="stat">
                <strong>{{ projectStore.project.surahs.length }}</strong>
                <span>{{ projectStore.project.surahs.length === 1 ? 'Surah loaded' : 'Surahs loaded' }}</span>
              </div>
              <span class="stat-divider" aria-hidden="true"></span>
              <div class="stat">
                <strong>{{ alignedWordsCount.toLocaleString() }}</strong>
                <span>Words aligned</span>
              </div>
            </div>
          </div>

          <!-- Error -->
          <div v-if="errorMessage" class="inline-error">
            <AlertTriangle :size="15" />
            <span>{{ errorMessage }}</span>
          </div>
        </div>

        <!-- Footer -->
        <footer class="align-footer">
          <template v-if="isRunning">
            <button type="button" class="btn-danger-ghost" @click="stopBatch">
              <Square :size="11" />
              <span>Stop</span>
            </button>
            <div class="footer-spacer"></div>
            <button type="button" class="btn-soft" @click="minimize">
              <Minimize2 :size="13" />
              <span>Run in background</span>
            </button>
          </template>

          <template v-else-if="isComplete">
            <span class="footer-note">Your project has been updated.</span>
            <div class="footer-spacer"></div>
            <button type="button" class="btn-run" @click="handleContinueToStudio">
              <span>Open studio</span>
              <ArrowRight :size="14" />
            </button>
          </template>

          <template v-else>
            <span class="footer-note">
              <template v-if="activeMode === 'timings'">
                {{ importablePairs.length > 0
                  ? `${importablePairs.length} ready to import${importablePairs.some(p => !p.audio) ? ' · audio can be attached later' : ''}`
                  : 'Add a timings JSON to import' }}
              </template>
              <template v-else-if="activeMode === 'align' && alignInput === 'files'">
                {{ filesQueue.length > 0 ? `${filesQueue.length} ready to align` : 'Select audio to begin' }}
              </template>
              <template v-else>
                {{ scannedFiles.length > 0 ? `${scannedFiles.length} ready to align` : 'Choose a folder to begin' }}
              </template>
            </span>
            <div class="footer-spacer"></div>

            <button
              v-if="activeMode === 'timings'"
              type="button"
              class="btn-run"
              :disabled="importablePairs.length === 0"
              @click="startTimingImport"
            >
              <span>{{ importablePairs.length > 1 ? `Import ${importablePairs.length} recitations` : 'Import' }}</span>
            </button>

            <button
              v-else-if="activeMode === 'align' && alignInput === 'files'"
              type="button"
              class="btn-run"
              :disabled="filesQueue.length === 0"
              @click="startFilesAlignmentQueue"
            >
              <span>{{ filesQueue.length > 1 ? `Align ${filesQueue.length} files` : 'Start alignment' }}</span>
            </button>

            <button
              v-else
              type="button"
              class="btn-run"
              :disabled="!dirPath || scannedFiles.length === 0"
              @click="startDirAlignment"
            >
              <span>{{ scannedFiles.length > 1 ? `Align ${scannedFiles.length} files` : 'Start alignment' }}</span>
            </button>
          </template>
        </footer>
      </section>
    </div>

    <!-- Minimized dock -->
    <div
      v-if="isMinimized && (isRunning || isComplete)"
      class="dock"
      :class="{ complete: isComplete }"
      role="status"
      @click="restoreModal"
    >
      <div class="dock-ring" :style="{ '--progress': `${progressPercent}%` }">
        <div class="dock-ring-inner">
          <Check v-if="isComplete" :size="14" />
          <span v-else class="dock-spinner"></span>
        </div>
      </div>

      <div class="dock-copy">
        <span class="dock-title">
          {{ isComplete ? 'Alignment complete' : (currentProcessingFileName || (alignInput === 'dir' && activeMode === 'align' ? 'Folder batch' : 'Aligning recitation')) }}
        </span>
        <span class="dock-sub">
          {{ isComplete ? `${projectStore.project.surahs.length} surah(s) ready` : `${currentStageLabel} · ${progressPercent.toFixed(0)}%` }}
        </span>
      </div>

      <div class="dock-actions" @click.stop>
        <button
          v-if="isRunning"
          type="button"
          class="dock-icon danger"
          title="Stop batch"
          aria-label="Stop batch"
          @click="stopBatch"
        >
          <Square :size="11" />
        </button>

        <button
          v-if="isComplete"
          type="button"
          class="dock-open"
          @click="handleContinueToStudio"
        >
          <span>Open</span>
          <ArrowRight :size="12" />
        </button>

        <button
          type="button"
          class="dock-icon"
          title="Expand"
          aria-label="Expand alignment dialog"
          @click="restoreModal"
        >
          <Maximize2 :size="13" />
        </button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, nextTick, onMounted, onUnmounted, watch } from 'vue';
import { projectStore } from '../services/projectStore';
import { 
  runAlign, 
  stopAlign, 
  scanAudioDir, 
  getAudioStreamUrl, 
  getDuration,
  isEngineInstalled,
  isTauriEnvironment,
  audioTimestampStretchMs,
  normalizeAudioTimestamps
} from '../services/api';
import { normalizeRiwayahKey } from '../services/RiwayahProvider';
import {
  normalizeTimedJson,
  surahNumberFromStem,
  validateAgainstReference,
  hydrateWordTextsFromReference,
  EXAMPLE_TIMINGS_STRING,
  TIMING_RULES
} from '../services/timingsImport';
import { open as openDialog } from '@tauri-apps/plugin-dialog';
import { 
  AudioWaveform,
  Files,
  FolderTree,
  FolderOpen,
  Search,
  FileAudio,
  FileJson,
  BookOpen,
  ChevronDown,
  Zap,
  Gauge,
  ListMusic,
  Terminal,
  AlertTriangle,
  TriangleAlert,
  Settings,
  Check,
  X,
  Square,
  Minimize2,
  Maximize2,
  ArrowRight,
  ClipboardCopy,
  Save
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
const activeMode = ref<'align' | 'timings'>('align');
const alignInput = ref<'files' | 'dir'>('files');
const timingInput = ref<'single' | 'batch'>('single');
const isDragging = ref(false);
const fastMode = ref(true);
const selectedRiwayah = ref<string>(projectStore.project?.settings?.riwayah || 'Hafs');
const isRunning = ref(false);
const isComplete = ref(false);
const isAborted = ref(false);
const errorMessage = ref('');
let alignEventUnlisten: (() => void) | null = null;
let alignPrepUnlisten: (() => void) | null = null;

function handleEscape(e: KeyboardEvent) {
  if (e.key === 'Escape' && visible.value && !isRunning.value) close();
}

onMounted(() => {
  window.addEventListener('keydown', handleEscape);
});

onUnmounted(() => {
  window.removeEventListener('keydown', handleEscape);
  if (alignEventUnlisten) { alignEventUnlisten(); alignEventUnlisten = null; }
  if (alignPrepUnlisten) { alignPrepUnlisten(); alignPrepUnlisten = null; }
  stopElapsedTimer();
});

// Files Queue State
const filesQueue = ref<QueueItem[]>([]);
const currentQueueIndex = ref(0);

// Directory Batch State
const dirPath = ref('');
const isScanningDir = ref(false);
const dirScanError = ref('');
const scannedFiles = ref<ScannedAudioFile[]>([]);

// Timings (JSON + audio) Import State
interface TimingPair {
  id: string;
  base: string;                      // shared name, extension stripped
  audio?: { name: string; size: number; path?: string; file?: File };
  json?: { name: string; size: number; path?: string; file?: File };
  status: 'pending' | 'importing' | 'completed' | 'error';
  errorMessage?: string;
  surah?: number;
  wordCount?: number;
}
const timingPairs = ref<TimingPair[]>([]);
const showFormatHelp = ref(false);
const importIndex = ref(-1);
const importTotal = ref(0);
const engineMissing = ref(false);
const importCurrentName = computed(() => {
  const p = timingPairs.value[importIndex.value];
  return p?.audio?.name || (p ? `${p.base}.json` : '');
});

// Real-Time Progress State
const currentStage = ref<'idle' | 'loading' | 'vad' | 'transcribing' | 'aligning' | 'matching' | 'completed'>('idle');
const progressPercent = ref(0);
const speedX = ref(0);
const statusMessage = ref('Ready');

// Elapsed-time ticker for the running pane (engine init + decode have no %
// of their own, so a live stopwatch keeps the phase visibly alive).
const runStartedAt = ref(0);
const elapsedSeconds = ref(0);
let elapsedTimer: ReturnType<typeof setInterval> | null = null;

const elapsedLabel = computed(() => {
  if (!isRunning.value || elapsedSeconds.value <= 0) return '';
  const total = elapsedSeconds.value;
  if (total < 60) return `${total}s`;
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${m}:${s.toString().padStart(2, '0')}`;
});

function startElapsedTimer() {
  stopElapsedTimer();
  runStartedAt.value = Date.now();
  elapsedSeconds.value = 0;
  elapsedTimer = setInterval(() => {
    elapsedSeconds.value = Math.floor((Date.now() - runStartedAt.value) / 1000);
  }, 1000);
}

function stopElapsedTimer() {
  if (elapsedTimer) {
    clearInterval(elapsedTimer);
    elapsedTimer = null;
  }
}

watch(isRunning, (running) => {
  if (running) startElapsedTimer();
  else stopElapsedTimer();
});

// Engine initialization / audio decoding have no incremental percentage —
// show an animated sweep instead of a frozen bar.
const progressIndeterminate = computed(() =>
  isRunning.value
  && (currentStage.value === 'idle' || currentStage.value === 'loading' || currentStage.value === 'vad')
);

const fileInput = ref<HTMLInputElement | null>(null);
const consoleBoxRef = ref<HTMLElement | null>(null);
const consoleLogs = ref<LogEntry[]>([]);
const showLogs = ref(false);

const currentProcessingFileName = computed(() => {
  if (filesQueue.value.length > 0 && filesQueue.value[currentQueueIndex.value]) {
    return filesQueue.value[currentQueueIndex.value].file.name;
  }
  return '';
});

const currentStageLabel = computed(() => {
  if (isRunning.value && activeMode.value === 'timings') return 'Importing timings';
  switch (currentStage.value) {
    case 'loading': return 'Initializing engine';
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

const queueTotalBytes = computed(() => {
  return filesQueue.value.reduce((acc, item) => acc + (item.file?.size || 0), 0);
});

const alignedWordsCount = computed(() => {
  return projectStore.project.surahs.reduce((total, surah) => {
    return total + surah.ayahs.reduce((ayahSum, ayah) => {
      return ayahSum + ayah.segments.reduce((segSum, seg) => segSum + seg.words.length, 0);
    }, 0);
  }, 0);
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
  showLogs.value = false;
  isDragging.value = false;
  currentStage.value = 'idle';
  speedX.value = 0;
  statusMessage.value = 'Ready';
  elapsedSeconds.value = 0;
  stopElapsedTimer();
  selectedRiwayah.value = projectStore.project?.settings?.riwayah || 'Hafs';
  // Reset queue on new session so previous completed items do not linger
  filesQueue.value = [];
  timingPairs.value = [];
  showFormatHelp.value = false;

  // Soft engine check (Tauri only): warn early instead of failing mid-run
  engineMissing.value = false;
  if (isTauriEnvironment()) {
    isEngineInstalled()
      .then((ok) => { engineMissing.value = !ok; })
      .catch(() => { /* engine check unavailable — ignore */ });
  }
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
  if (alignPrepUnlisten) { alignPrepUnlisten(); alignPrepUnlisten = null; }

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
// Timings Import (external JSON + audio)
// ==========================================

const AUDIO_EXTS = ['mp3', 'wav', 'm4a', 'ogg', 'flac', 'aac', 'opus'];

function baseName(name: string): string {
  return name.replace(/\.[^.]+$/, '').trim().toLowerCase();
}

function extOf(name: string): string {
  const m = name.match(/\.([a-z0-9]+)$/i);
  return m ? m[1].toLowerCase() : '';
}

/** Group loose audio/json entries into pairs by shared base name. */
function groupTimingEntries(entries: Array<{ name: string; size: number; path?: string; file?: File }>): void {
  for (const e of entries) {
    const base = baseName(e.name);
    if (!base) continue;
    let pair = timingPairs.value.find(p => p.base === base);
    if (!pair) {
      pair = { id: `${base}_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`, base, status: 'pending' };
      timingPairs.value.push(pair);
    }
    if (AUDIO_EXTS.includes(extOf(e.name))) {
      pair.audio = { name: e.name, size: e.size, path: e.path, file: e.file };
    } else if (extOf(e.name) === 'json') {
      pair.json = { name: e.name, size: e.size, path: e.path, file: e.file };
    }
  }
}

async function triggerTimingPick() {
  if (isTauriEnvironment()) {
    try {
      const selected = await openDialog({
        directory: false,
        multiple: true,
        title: 'Select Audio Files and Timings JSON',
        filters: [
          { name: 'Audio', extensions: AUDIO_EXTS },
          { name: 'Timings JSON', extensions: ['json'] }
        ]
      });
      if (selected) {
        const paths = Array.isArray(selected) ? selected : [selected];
        const entries = paths.map((p: string) => {
          const name = p.split(/[\\/]/).pop() || p;
          return { name, size: 0, path: p };
        });
        groupTimingEntries(entries);
        return;
      }
      if (selected !== undefined) return;
    } catch (err) {
      console.warn('Tauri openDialog error, falling back to input:', err);
    }
  }
  const input = document.createElement('input');
  input.type = 'file';
  input.multiple = true;
  input.accept = '.json,audio/*,video/*';
  input.onchange = () => {
    if (input.files && input.files.length > 0) groupTimingEntries(Array.from(input.files).map(f => ({ name: f.name, size: f.size, file: f })));
    input.remove();
  };
  document.body.appendChild(input);
  input.click();
}

function onDropTiming(e: DragEvent) {
  isDragging.value = false;
  if (!e.dataTransfer || !e.dataTransfer.files) return;
  groupTimingEntries(Array.from(e.dataTransfer.files).map(f => ({ name: f.name, size: f.size, file: f })));
}

/** Folder scan for batch pairs: audio + same-name .json. */
async function pickTimingFolder() {
  if (isTauriEnvironment()) {
    try {
      const selected = await openDialog({ directory: true, multiple: false, title: 'Select Folder With Audio + JSON Pairs' });
      if (selected && typeof selected === 'string') {
        const data = await scanAudioDir(selected);
        const audioFiles: any[] = data.audio_files || data.files || [];
        const missing: string[] = [];
        const candidates = audioFiles.map((f: any) => {
          const full = f.path || f.full_path || '';
          const name = f.name || f.rel_path || '';
          return { audioName: name, audioPath: full, jsonPath: full.replace(/\.[^.]+$/, '.json') };
        });
        if (candidates.length === 0) {
          errorMessage.value = 'No audio files found in this folder.';
          return;
        }
        // Keep only pairs whose JSON exists — verify via a cheap fetch of the asset URL.
        const checked = await Promise.all(candidates.map(async (c) => {
          try {
            const res = await fetch(getAudioStreamUrl(c.jsonPath), { method: 'HEAD' });
            return { c, ok: res.ok };
          } catch {
            return { c, ok: false };
          }
        }));
        const entries: Array<{ name: string; size: number; path?: string }> = [];
        for (const { c, ok } of checked) {
          if (ok) {
            entries.push({ name: c.audioName, size: 0, path: c.audioPath });
            entries.push({ name: c.audioName.replace(/\.[^.]+$/, '.json'), size: 0, path: c.jsonPath });
          } else {
            missing.push(c.audioName);
          }
        }
        groupTimingEntries(entries);
        if (missing.length > 0) {
          addLog(`${missing.length} audio file(s) skipped — no matching JSON: ${missing.slice(0, 3).join(', ')}${missing.length > 3 ? '…' : ''}`, 'warn');
        }
        return;
      }
      if (selected !== undefined) return;
    } catch (err) {
      console.warn('Tauri folder scan failed, trying browser fallback:', err);
    }
  }
  // Browser fallback: folder picker returns every file, pair by base name.
  if (typeof window !== 'undefined' && 'showDirectoryPicker' in window) {
    try {
      const handle = await (window as any).showDirectoryPicker({ id: 'quran-timings-folder', mode: 'read' });
      if (handle) {
        const entries: Array<{ name: string; size: number; file?: File }> = [];
        for await (const entry of handle.values()) {
          if (entry.kind !== 'file') continue;
          const f = await entry.getFile();
          if (AUDIO_EXTS.includes(extOf(f.name)) || extOf(f.name) === 'json') {
            entries.push({ name: f.name, size: f.size, file: f });
          }
        }
        groupTimingEntries(entries);
        return;
      }
      return; // cancelled
    } catch (pErr: any) {
      if (pErr.name === 'AbortError') return;
      console.warn('showDirectoryPicker error:', pErr);
    }
  }
  const input = document.createElement('input');
  input.type = 'file';
  input.multiple = true;
  (input as any).webkitdirectory = true;
  input.onchange = () => {
    if (input.files && input.files.length > 0) groupTimingEntries(Array.from(input.files).map(f => ({ name: f.name, size: f.size, file: f })));
    input.remove();
  };
  document.body.appendChild(input);
  input.click();
}

async function readJsonText(pair: TimingPair): Promise<string> {
  if (pair.json?.file) return pair.json.file.text();
  if (pair.json?.path) {
    const res = await fetch(getAudioStreamUrl(pair.json.path));
    if (!res.ok) throw new Error(`JSON file could not be read (${res.status}).`);
    return res.text();
  }
  throw new Error('No JSON file attached to this pair.');
}

function removeTimingPair(id: string) {
  timingPairs.value = timingPairs.value.filter(p => p.id !== id);
}

const importablePairs = computed(() =>
  timingPairs.value.filter(p => p.json && p.status !== 'completed')
);

/** True when a pair has only a JSON file — importable, audio can be attached later. */
function pairNeedsAudio(p: TimingPair): boolean {
  return !p.audio;
}

function requestEngineSetup() {
  window.dispatchEvent(new CustomEvent('quran-open-setup'));
}

const missingEngineBanner = computed(() => engineMissing.value && activeMode.value === 'align');

async function startTimingImport() {
  const pairs = importablePairs.value;
  if (pairs.length === 0) return;

  isRunning.value = true;
  isComplete.value = false;
  errorMessage.value = '';
  statusMessage.value = 'Importing timings…';
  currentStage.value = 'loading';
  currentQueueIndex.value = 0;
  progressPercent.value = 0;
  importTotal.value = pairs.length;
  addLog(`Importing ${pairs.length} timing pair(s).`, 'info');

  let ok = 0;
  for (let i = 0; i < pairs.length; i++) {
    const pair = pairs[i];
    importIndex.value = i;
    pair.status = 'importing';
    statusMessage.value = `Importing ${pair.base}…`;
    try {
      const text = await readJsonText(pair);
      let parsed: any;
      try {
        parsed = JSON.parse(text);
      } catch {
        throw new Error('The JSON file could not be parsed (invalid syntax).');
      }

      // Audio path/url for the studio player
      let audioPath: string | undefined;
      let audioUrl: string | undefined;
      if (pair.audio?.path) {
        audioPath = pair.audio.path;
        audioUrl = getAudioStreamUrl(audioPath);
      } else if (pair.audio?.file) {
        audioUrl = URL.createObjectURL(pair.audio.file);
      }

      // Audio duration improves ms/seconds detection
      let durSec: number | undefined;
      try {
        if (audioPath && isTauriEnvironment()) durSec = await getDuration(audioPath);
        else if (audioUrl) durSec = await probeBlobDuration(audioUrl);
      } catch { /* heuristic fallback */ }

      const timings = normalizeTimedJson(parsed, durSec, pair.base);
      // Position-based entries get their Arabic text from the bundled mushaf
      try {
        for (const warn of await hydrateWordTextsFromReference(timings)) {
          addLog(`${pair.base}: ${warn}`, 'warn');
        }
      } catch { /* hydrate is best-effort; inline-text imports are unaffected */ }
      projectStore.loadAlignedSurah(timings as any, audioPath, audioUrl);
      pair.status = 'completed';
      pair.wordCount = timings.wordCount;
      try { pair.surah = timings.surahs[0]?.surah; } catch { /* ignore */ }
      ok++;
      addLog(`Imported ${pair.base} → Surah ${pair.surah ?? '?'} · ${timings.wordCount} words`, 'success');
      for (const warn of timings.warnings) addLog(`${pair.base}: ${warn}`, 'warn');
      if (!pair.audio) {
        addLog(`${pair.base}: no audio attached — drop the audio file on the timeline to attach it.`, 'warn');
      }
      try {
        const refWarnings = await validateAgainstReference(timings);
        for (const warn of refWarnings) addLog(`${pair.base}: ${warn}`, 'warn');
      } catch { /* reference check is best-effort */ }
    } catch (err: any) {
      pair.status = 'error';
      pair.errorMessage = err?.message || String(err);
      addLog(`${pair.base}: ${pair.errorMessage}`, 'error');
    }
    progressPercent.value = Math.round(((i + 1) / pairs.length) * 100);
  }

  isRunning.value = false;
  importIndex.value = -1;
  if (ok > 0 && ok === pairs.length) {
    currentStage.value = 'completed';
    progressPercent.value = 100;
    statusMessage.value = `Imported timings for ${ok} recitation(s).`;
    isComplete.value = true;
    // For a single recitation, go straight into the studio
    if (pairs.length === 1 && !errorMessage.value) {
      setTimeout(() => {
        if (!isAborted.value && isComplete.value) {
          projectStore.currentTab.value = 'studio';
          visible.value = false;
          isMinimized.value = false;
          timingPairs.value = [];
        }
      }, 600);
    }
  } else if (ok > 0) {
    progressPercent.value = Math.round((ok / pairs.length) * 100);
    errorMessage.value = `Imported ${ok} of ${pairs.length}. Check the status of the remaining pairs.`;
  } else {
    errorMessage.value = 'Nothing was imported. Check the format guide and the JSON files.';
  }
}

function probeBlobDuration(url: string): Promise<number> {
  return new Promise((resolve, reject) => {
    const a = document.createElement('audio');
    a.preload = 'metadata';
    a.onloadedmetadata = () => {
      const d = a.duration;
      a.src = '';
      isFinite(d) && d > 0 ? resolve(d) : reject(new Error('duration unavailable'));
    };
    a.onerror = () => reject(new Error('duration unavailable'));
    a.src = url;
  });
}

function saveExampleJson() {
  const blob = new Blob([EXAMPLE_TIMINGS_STRING], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = 'timings-example.json';
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

async function copyExampleJson() {
  try {
    await navigator.clipboard.writeText(EXAMPLE_TIMINGS_STRING);
  } catch (e) {
    console.debug('clipboard copy failed', e);
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
  currentStage.value = 'loading';
  progressPercent.value = 0;
  speedX.value = 0;
  statusMessage.value = 'Preparing alignment…';

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

      // 2. Validate disk path
      const isAbsolutePath = audioPath && (audioPath.includes(':') || audioPath.startsWith('/'));
      if (!isAbsolutePath) {
        throw new Error('Please select an audio file directly from your local disk.');
      }

      if (!audioPath) {
        throw new Error('No valid audio file path');
      }

      if (isAborted.value) break;

      item.status = 'aligning';
      currentStage.value = 'loading';
      progressPercent.value = 0;
      speedX.value = 0;
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
    // For single recitation, smoothly transition directly into Studio Workstation
    if (filesQueue.value.length === 1 && !errorMessage.value) {
      setTimeout(() => {
        if (!isAborted.value && isComplete.value) {
          handleContinueToStudio();
        }
      }, 700);
    }
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
      activeMode.value = 'align';
      alignInput.value = 'files';
      await startFilesAlignmentQueue();
    }
    return;
  }

  isRunning.value = true;
  isComplete.value = false;
  isAborted.value = false;
  errorMessage.value = '';
  consoleLogs.value = [];
  statusMessage.value = 'Preparing folder batch…';
  currentStage.value = 'loading';
  progressPercent.value = 0;
  speedX.value = 0;

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

function executeAlignment(
  audioPath?: string,
  audioUrl?: string,
  dirPathArg?: string,
): Promise<void> {
  if (isTauriEnvironment()) {
    return runAlignmentTauri(audioPath, audioUrl, dirPathArg);
  } else {
    return Promise.reject(new Error('Alignment is only available inside the Quran Recite Studio desktop application.'));
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
    cleanupListeners();

    const { listen } = await import('@tauri-apps/api/event');

    alignEventUnlisten = await listen<any>('align-event', (event) => {
      handleAlignEvent(event.payload, audioPath, audioUrl);
      if (event.payload.type === 'complete') {
        cleanupListeners();
        resolve();
      } else if (event.payload.type === 'error') {
        cleanupListeners();
        reject(new Error(event.payload.message || 'Alignment error'));
      }
    });

    // Live percentage while the PTS normalizer re-encodes the audio file.
    alignPrepUnlisten = await listen<any>('align-prep', (event) => {
      const d = event.payload || {};
      if (d.stage === 'normalize') {
        const pct = Math.max(0, Math.min(100, Number(d.percent) || 0));
        currentStage.value = 'loading';
        statusMessage.value = (typeof d.message === 'string' && d.message)
          ? d.message
          : `Normalizing audio timestamps… ${pct.toFixed(0)}%`;
        progressPercent.value = Math.max(progressPercent.value, 2 + pct * 0.13);
      }
    });

    function cleanupListeners() {
      if (alignEventUnlisten) { alignEventUnlisten(); alignEventUnlisten = null; }
      if (alignPrepUnlisten) { alignPrepUnlisten(); alignPrepUnlisten = null; }
    }

    try {
      if (audioPath) {
        try {
          currentStage.value = 'loading';
          statusMessage.value = 'Checking audio timestamps…';
          progressPercent.value = Math.max(progressPercent.value, 2);
          const stretchMs = await audioTimestampStretchMs(audioPath);
          if (stretchMs > 500) {
            addLog(`Audio PTS container stretch detected (${stretchMs}ms). Normalizing timestamps to prevent drift...`, 'warn');
            statusMessage.value = 'Normalizing audio timestamps…';
            await normalizeAudioTimestamps(audioPath);
            addLog(`Audio timestamps normalized successfully.`, 'success');
          }
        } catch (normErr) {
          console.debug('PTS stretch check non-fatal error:', normErr);
        }
      }

      // The user may have pressed Stop while the PTS preflight was running —
      // in that case don't launch the engine at all.
      if (isAborted.value) {
        cleanupListeners();
        resolve();
        return;
      }

      statusMessage.value = 'Launching alignment engine…';
      await runAlign({
        audio_path: audioPath,
        dir_path: dirPathArg,
        fast: fastMode.value,
        qiraat: normalizeRiwayahKey(selectedRiwayah.value).toLowerCase(),
      });
    } catch (err) {
      cleanupListeners();
      reject(err);
    }
  });
}

function handleAlignEvent(event: any, fallbackAudioPath?: string, fallbackAudioUrl?: string) {
  if (event.type === 'start') {
    currentStage.value = 'loading';
    progressPercent.value = Math.max(progressPercent.value, 2);
    statusMessage.value = 'Starting alignment engine…';
    addLog(event.audio ? `Engine starting: ${event.audio}` : 'Engine starting…', 'info');
  } else if (event.type === 'stdout') {
    addLog(event.text, 'info');
  } else if (event.type === 'stderr') {
    addLog(event.text, 'warn');
  } else if (event.type === 'progress') {
    const p = event.data || {};

    // Prefer the engine's human-readable message when it sends one.
    if (typeof p.message === 'string' && p.message) {
      statusMessage.value = p.message;
    }

    if (p.stage === 'loading' || p.step === 'loading') {
      currentStage.value = 'loading';
      progressPercent.value = Math.max(progressPercent.value, Math.min(12, Number(p.progress) || 4));
      if (!p.message) statusMessage.value = 'Initializing engine & models…';
    } else if (p.stage === 'vad' || p.stage === 'preparing') {
      currentStage.value = 'vad';
      progressPercent.value = Math.max(progressPercent.value, 15);
      if (!p.message) {
        statusMessage.value = typeof p.elapsed === 'number' && p.elapsed > 0
          ? `Voice detection finished in ${p.elapsed.toFixed(1)}s`
          : 'Decoding audio…';
      }
    } else if (p.stage === 'transcribing') {
      currentStage.value = 'transcribing';
      if (typeof p.percent === 'number') {
        progressPercent.value = Math.max(progressPercent.value, Math.min(80, 15 + p.percent * 0.65));
      }
      if (typeof p.speed_x === 'number' && p.speed_x > 0) speedX.value = p.speed_x;
      if (!p.message) statusMessage.value = `ASR: ${(Number(p.percent) || 0).toFixed(0)}%`;
    } else if (p.stage === 'aligning') {
      currentStage.value = 'aligning';
      progressPercent.value = Math.max(progressPercent.value, 85);
      if (!p.message) statusMessage.value = 'CTC Trellis Alignment…';
    } else if (p.stage === 'matching') {
      currentStage.value = 'matching';
      progressPercent.value = Math.max(progressPercent.value, 93);
      if (!p.message) statusMessage.value = 'Medina Quran Matching…';
    } else if (p.stage === 'batch_file_start') {
      statusMessage.value = `[${p.index}/${p.total}] Aligning ${p.file}…`;
      addLog(`Batch File [${p.index}/${p.total}]: ${p.file}`, 'info');
    } else if (p.stage === 'batch_file_done') {
      statusMessage.value = `[${p.index}/${p.total}] Done: ${p.file}`;
      addLog(`Completed: ${p.file}`, 'success');
    } else if (p.stage === 'completed' || p.stage === 'batch_completed') {
      currentStage.value = 'completed';
      progressPercent.value = 100;
      statusMessage.value = p.message || `Done (${p.real_time_factor || 1.0}x RTF)`;
    }
  } else if (event.type === 'complete') {
    currentStage.value = 'completed';
    progressPercent.value = 100;
    statusMessage.value = 'Alignment complete!';

    if (event.result) {
      const effPath = event.audio_path || fallbackAudioPath;
      const effUrl = effPath ? getAudioStreamUrl(effPath) : (event.audio_url ? getAudioStreamUrl(event.audio_url) : fallbackAudioUrl);
      if (projectStore.project?.settings) {
        projectStore.project.settings.riwayah = selectedRiwayah.value;
      }
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
  if (type === 'error') showLogs.value = true;
  nextTick(() => {
    if (consoleBoxRef.value) {
      consoleBoxRef.value.scrollTop = consoleBoxRef.value.scrollHeight;
    }
  });
}

function getStepClass(stage: string) {
  const order = ['loading', 'vad', 'transcribing', 'aligning', 'matching', 'completed'];
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
/* ============================================================
   2026 Alignment Dialog — Linear/Raycast-inspired surface
   ============================================================ */

.align-overlay {
  position: fixed;
  inset: 0;
  z-index: 1000;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 20px;
  background: var(--backdrop-bg);
  animation: fade-in var(--dur-base) var(--ease-out) both;
}

.align-dialog {
  position: relative;
  width: min(780px, calc(100vw - 32px));
  max-height: min(880px, calc(100vh - 40px));
  display: flex;
  flex-direction: column;
  overflow: hidden;
  border-radius: var(--radius-xl);
  border: 1px solid var(--border-medium);
  background: var(--bg-surface);
  box-shadow: var(--shadow-e4);
  animation: dialog-in var(--dur-over) var(--ease-out) both;
  isolation: isolate;
}

.dialog-aura {
  display: none;
}

/* ---------- Header ---------- */

.align-header {
  position: relative;
  z-index: 1;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 18px;
  padding: 18px 22px 14px;
}

.brand {
  display: flex;
  align-items: center;
  gap: 12px;
  min-width: 0;
}

.brand-mark {
  width: 34px;
  height: 34px;
  flex: none;
  display: grid;
  place-items: center;
  border-radius: var(--radius-md);
  color: #fff;
  background: var(--accent-primary);
}

.brand-text {
  min-width: 0;
}

.brand-text h2 {
  margin: 0;
  font-size: 15px;
  font-weight: 600;
  letter-spacing: -0.01em;
  color: var(--text-main);
  line-height: 1.25;
}

.brand-text p {
  margin: 2px 0 0;
  font-size: 12px;
  font-weight: 400;
  color: var(--text-muted);
  line-height: 1.4;
}

.header-controls {
  display: flex;
  align-items: center;
  gap: 10px;
  flex: none;
}

.mode-switch {
  display: flex;
  align-items: center;
  gap: 2px;
  padding: 3px;
  border-radius: 11px;
  background: rgba(0, 0, 0, 0.28);
  border: 1px solid rgba(255, 255, 255, 0.06);
  box-shadow: inset 0 1px 2px rgba(0, 0, 0, 0.28);
}

.mode-tab {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 11px;
  border: 0;
  border-radius: 8px;
  background: transparent;
  color: var(--text-muted);
  font-family: var(--font-ui);
  font-size: 12px;
  font-weight: 500;
  line-height: 1;
  cursor: pointer;
  transition:
    color var(--dur-fast) var(--ease-out),
    background var(--dur-fast) var(--ease-out),
    box-shadow var(--dur-fast) var(--ease-out);
}

.mode-tab:hover {
  color: var(--text-main);
}

.mode-tab.active {
  color: var(--text-main);
  background: var(--bg-surface-elevated);
  box-shadow: inset 0 0 0 1px var(--border-subtle);
}

.mode-count {
  min-width: 17px;
  padding: 2px 5px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.09);
  color: var(--text-secondary);
  font-family: var(--font-mono);
  font-size: 9.5px;
  font-weight: 600;
  text-align: center;
  line-height: 1.1;
}

/* Input option switch (inside a tab) */
.pane-option-bar {
  margin: 2px 0 0;
}

.opt-tabs {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  padding: 2px;
  background: var(--bg-input);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-sm);
}

.opt-tab {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 4px 10px;
  border: 0;
  border-radius: var(--radius-xs);
  background: transparent;
  color: var(--text-muted);
  font-family: var(--font-ui);
  font-size: 11.5px;
  font-weight: 500;
  line-height: 1.4;
  cursor: pointer;
  transition:
    color var(--dur-fast) var(--ease-out),
    background var(--dur-fast) var(--ease-out);
}

.opt-tab:hover {
  color: var(--text-main);
}

.opt-tab.active {
  color: var(--text-main);
  background: var(--bg-surface-elevated);
  box-shadow: inset 0 0 0 1px var(--border-subtle);
}

.mode-tab.active .mode-count {
  background: rgba(var(--accent-rgb), 0.42);
  color: #fff;
}

.icon-btn {
  width: 32px;
  height: 32px;
  display: grid;
  place-items: center;
  border: 1px solid transparent;
  border-radius: 9px;
  background: transparent;
  color: var(--text-muted);
  cursor: pointer;
  transition:
    color var(--dur-fast) var(--ease-out),
    background var(--dur-fast) var(--ease-out),
    border-color var(--dur-fast) var(--ease-out),
    transform var(--dur-fast) var(--ease-out);
}

.icon-btn:hover {
  color: #fff;
  background: rgba(255, 255, 255, 0.07);
  border-color: rgba(255, 255, 255, 0.06);
}

.icon-btn:active {
  transform: scale(0.94);
}

/* ---------- Layout ---------- */

.align-body {
  position: relative;
  z-index: 1;
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 0 24px 22px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.mode-pane {
  display: flex;
  flex-direction: column;
  gap: 14px;
  animation: rise-in var(--dur-rise) var(--ease-spring) both;
}

.visually-hidden {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}

/* ---------- Session configuration ---------- */

.settings-row {
  display: flex;
  align-items: center;
  gap: 18px;
  padding: 11px 14px;
  border-radius: var(--radius-md);
  border: 1px solid var(--border-subtle);
  background: var(--bg-input);
}

.setting-field {
  display: flex;
  align-items: center;
  gap: 12px;
  flex: 1;
  min-width: 0;
}

.setting-label {
  flex: none;
  font-size: 9.5px;
  font-weight: 600;
  letter-spacing: 0.11em;
  text-transform: uppercase;
  color: var(--text-dim);
  white-space: nowrap;
}

.select-shell {
  position: relative;
  flex: 1;
  min-width: 0;
  display: flex;
  align-items: center;
}

.riwayah-select {
  appearance: none;
  -webkit-appearance: none;
  width: 100%;
  min-width: 0;
  padding: 3px 24px 3px 0;
  border: 0;
  outline: none;
  background: transparent;
  color: var(--text-main);
  font-family: var(--font-ui);
  font-size: 12.5px;
  font-weight: 500;
  line-height: 1.4;
  cursor: pointer;
  text-overflow: ellipsis;
}

.riwayah-select option {
  background: #151821;
  color: #f3f4f6;
}

.riwayah-select:focus-visible {
  border-radius: 5px;
  box-shadow: 0 var(--shadow-e1);
}

.select-chevron {
  position: absolute;
  right: 0;
  top: 50%;
  transform: translateY(-50%);
  color: var(--text-dim);
  pointer-events: none;
  transition: color var(--dur-fast) var(--ease-out);
}

.select-shell:hover .select-chevron {
  color: var(--text-muted);
}

.setting-sep {
  width: 1px;
  height: 28px;
  flex: none;
  background: rgba(255, 255, 255, 0.07);
}

.engine-toggle {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 0;
  border: 0;
  background: transparent;
  color: inherit;
  font-family: var(--font-ui);
  cursor: pointer;
  user-select: none;
}

.engine-icon {
  width: 31px;
  height: 31px;
  flex: none;
  display: grid;
  place-items: center;
  border-radius: 9px;
  color: var(--text-muted);
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid rgba(255, 255, 255, 0.055);
  transition:
    color var(--dur-base) var(--ease-out),
    background var(--dur-base) var(--ease-out),
    border-color var(--dur-base) var(--ease-out);
}

.engine-toggle.active .engine-icon {
  color: var(--amber-primary);
  background: rgba(245, 158, 11, 0.1);
  border-color: rgba(245, 158, 11, 0.22);
}

.engine-copy {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 1px;
  min-width: 0;
}

.engine-copy .setting-label {
  color: var(--text-muted);
}

.engine-state {
  font-size: 11.5px;
  font-weight: 400;
  color: var(--text-dim);
  white-space: nowrap;
  transition: color var(--dur-fast) var(--ease-out);
}

.engine-toggle.active .engine-state {
  color: var(--text-secondary);
}

.toggle-track {
  position: relative;
  width: 34px;
  height: 20px;
  flex: none;
  border-radius: 999px;
  background: #222634;
  border: 1px solid rgba(255, 255, 255, 0.08);
  transition:
    background var(--dur-base) var(--ease-out),
    border-color var(--dur-base) var(--ease-out);
}

.toggle-thumb {
  position: absolute;
  top: 2px;
  left: 2px;
  width: 14px;
  height: 14px;
  border-radius: 50%;
  background: #8b93a7;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.4);
  transition:
    transform var(--dur-base) var(--ease-spring),
    background var(--dur-base) var(--ease-out);
}

.engine-toggle.active .toggle-track {
  background: var(--accent-primary);
  border-color: rgba(var(--accent-rgb), 0.65);
}

.engine-toggle.active .toggle-thumb {
  transform: translateX(14px);
  background: #fff;
}

/* ---------- Dropzone ---------- */

.dropzone {
  position: relative;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 13px;
  min-height: 208px;
  padding: 26px;
  border-radius: var(--radius-lg);
  border: 1px dashed var(--border-medium);
  background: var(--bg-input);
  text-align: center;
  cursor: pointer;
  transition:
    border-color var(--dur-base) var(--ease-out),
    background var(--dur-base) var(--ease-out);
}

.dropzone:hover,
.dropzone.dropzone-active {
  border-color: var(--accent-primary);
  background: var(--accent-subtle);
}

.dropzone.dropzone-active {
  transform: none;
}

.drop-icon {
  position: relative;
  width: 48px;
  height: 48px;
  flex: none;
  display: grid;
  place-items: center;
  border-radius: var(--radius-md);
  color: var(--text-secondary);
  background: var(--bg-surface-elevated);
  border: 1px solid var(--border-medium);
  transition: transform var(--dur-rise) var(--ease-out);
}

.dropzone:hover .drop-icon {
  transform: translateY(-2px);
  color: var(--accent-hover);
}

.drop-icon::after {
  content: none;
}

.drop-copy {
  position: relative;
  z-index: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 3px;
}

.drop-copy h3 {
  margin: 0;
  font-size: 15px;
  font-weight: 600;
  letter-spacing: -0.012em;
  color: var(--text-main);
}

.drop-copy p {
  margin: 0;
  font-size: 12.5px;
  color: var(--text-muted);
}

.browse-link {
  color: var(--accent-hover);
  font-weight: 500;
  text-decoration: underline;
  text-decoration-color: rgba(var(--accent-rgb), 0.28);
  text-underline-offset: 3px;
  transition: color var(--dur-fast) var(--ease-out);
}

.dropzone:hover .browse-link {
  color: var(--accent-hover);
  text-decoration-color: rgba(var(--accent-rgb), 0.5);
}

.formats {
  margin-top: 7px;
  font-family: var(--font-mono);
  font-size: 9.5px;
  font-weight: 500;
  letter-spacing: 0.13em;
  color: var(--text-dim);
}

/* Compact dropzone when a queue exists */
.dropzone.compact {
  min-height: auto;
  flex-direction: row;
  justify-content: flex-start;
  gap: 16px;
  padding: 16px 18px;
  text-align: left;
}

.dropzone.compact .drop-icon {
  width: 44px;
  height: 44px;
  border-radius: 13px;
}

.dropzone.compact .drop-icon svg {
  width: 20px;
  height: 20px;
}

.dropzone.compact .drop-copy {
  align-items: flex-start;
}

.dropzone.compact .drop-copy h3 {
  font-size: 13.5px;
}

.dropzone.compact .formats {
  display: none;
}

/* ---------- File queue ---------- */

.queue {
  display: flex;
  flex-direction: column;
  gap: 9px;
  animation: rise-in var(--dur-rise) var(--ease-spring) both;
}

.queue-heading {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 12px;
  padding: 0 2px;
}

.queue-heading h3 {
  margin: 0;
  font-size: 13px;
  font-weight: 600;
  color: var(--text-main);
}

.queue-heading p {
  margin: 2px 0 0;
  font-size: 11px;
  color: var(--text-dim);
  font-family: var(--font-mono);
}

.text-btn {
  padding: 4px 7px;
  border: 0;
  border-radius: 6px;
  background: transparent;
  color: var(--text-muted);
  font-family: var(--font-ui);
  font-size: 11px;
  cursor: pointer;
  transition:
    color var(--dur-fast) var(--ease-out),
    background var(--dur-fast) var(--ease-out);
}

.text-btn:hover {
  color: var(--ruby-primary);
  background: rgba(239, 68, 68, 0.08);
}

.queue-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
  max-height: 236px;
  overflow-y: auto;
  padding-right: 2px;
}

.file-row {
  display: flex;
  align-items: center;
  gap: 11px;
  padding: 9px 10px 9px 11px;
  border-radius: var(--radius-md);
  border: 1px solid var(--border-subtle);
  background: var(--bg-input);
  transition:
    background var(--dur-fast) var(--ease-out),
    border-color var(--dur-fast) var(--ease-out);
}

.file-row:hover {
  border-color: var(--border-medium);
  background: var(--bg-surface-hover);
}

.file-icon {
  width: 32px;
  height: 32px;
  flex: none;
  display: grid;
  place-items: center;
  border-radius: 9px;
  color: var(--accent-hover);
  background: rgba(var(--accent-rgb), 0.12);
  border: 1px solid rgba(var(--accent-rgb), 0.18);
}

.file-copy {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.file-name {
  font-size: 12.5px;
  font-weight: 500;
  color: var(--text-main);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  user-select: text;
}

.file-meta {
  display: flex;
  align-items: center;
  gap: 5px;
  font-family: var(--font-mono);
  font-size: 10px;
  color: var(--text-dim);
}

.meta-dot {
  opacity: 0.55;
}

.status-text.pending { color: var(--text-muted); }
.status-text.aligning { color: var(--accent-hover); }
.status-text.completed { color: var(--emerald-primary); }
.status-text.error { color: var(--ruby-primary); }
.status-text.uploading { color: var(--sky-primary); }

.status-dot {
  width: 7px;
  height: 7px;
  flex: none;
  border-radius: 50%;
  background: var(--text-dim);
  transition: background var(--dur-fast) var(--ease-out);
}

.status-dot.pending { background: #4b5563; }
.status-dot.uploading { background: var(--sky-primary); }
.status-dot.aligning {
  background: var(--accent-primary);
  box-shadow: var(--shadow-e1);
}
.status-dot.completed {
  background: var(--emerald-primary);
  box-shadow: var(--shadow-e1);
}
.status-dot.error { background: var(--ruby-primary); }

.row-action {
  width: 26px;
  height: 26px;
  flex: none;
  display: grid;
  place-items: center;
  border: 0;
  border-radius: 7px;
  background: transparent;
  color: var(--text-dim);
  cursor: pointer;
  opacity: 0;
  transition:
    opacity var(--dur-fast) var(--ease-out),
    color var(--dur-fast) var(--ease-out),
    background var(--dur-fast) var(--ease-out);
}

.file-row:hover .row-action,
.row-action:focus-visible {
  opacity: 1;
}

.row-action:hover {
  color: var(--ruby-primary);
  background: rgba(239, 68, 68, 0.1);
}

/* ---------- Folder mode ---------- */

.path-shell {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 9px 10px 9px 12px;
  border-radius: var(--radius-md);
  border: 1px solid var(--border-subtle);
  background: var(--bg-input);
  transition:
    border-color var(--dur-base) var(--ease-out),
    box-shadow var(--dur-base) var(--ease-out);
}

.path-shell:focus-within {
  border-color: rgba(var(--accent-rgb), 0.55);
  box-shadow: 0 var(--shadow-e1);
}

.path-browse {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  flex: none;
  padding: 8px 11px;
  border-radius: 9px;
  border: 1px solid rgba(255, 255, 255, 0.075);
  background: rgba(255, 255, 255, 0.045);
  color: var(--text-main);
  font-family: var(--font-ui);
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  white-space: nowrap;
  transition:
    background var(--dur-fast) var(--ease-out),
    border-color var(--dur-fast) var(--ease-out);
}

.path-browse:hover:not(:disabled) {
  background: rgba(255, 255, 255, 0.085);
  border-color: rgba(255, 255, 255, 0.14);
}

.path-browse:disabled {
  opacity: 0.5;
  cursor: wait;
}

.path-divider {
  width: 1px;
  height: 22px;
  flex: none;
  background: rgba(255, 255, 255, 0.07);
}

.path-input {
  flex: 1;
  min-width: 0;
  padding: 5px 0;
  border: 0;
  outline: none;
  background: transparent;
  color: var(--text-main);
  font-family: var(--font-mono);
  font-size: 11.5px;
}

.path-input::placeholder {
  color: var(--text-dim);
  font-family: var(--font-ui);
  font-size: 12px;
}

.path-scan {
  width: 32px;
  height: 32px;
  flex: none;
  display: grid;
  place-items: center;
  border-radius: 8px;
  border: 1px solid rgba(var(--accent-rgb), 0.3);
  background: rgba(var(--accent-rgb), 0.15);
  color: var(--accent-hover);
  cursor: pointer;
  transition:
    background var(--dur-fast) var(--ease-out),
    border-color var(--dur-fast) var(--ease-out);
}

.path-scan:hover:not(:disabled) {
  background: rgba(var(--accent-rgb), 0.26);
  border-color: rgba(var(--accent-rgb), 0.55);
}

.path-scan:disabled {
  opacity: 0.5;
  cursor: wait;
}

.path-hint {
  margin: -5px 2px 0;
  font-size: 11.5px;
  color: var(--text-dim);
  line-height: 1.45;
}

.scanning-label {
  color: var(--accent-hover);
}

.spin-icon {
  animation: spin 1s linear infinite;
}

.scan-card {
  overflow: hidden;
  border-radius: var(--radius-lg);
  border: 1px solid var(--emerald-border);
  background: var(--emerald-bg);
  animation: rise-in var(--dur-rise) var(--ease-out) both;
}

.scan-summary {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 13px 14px;
}

.scan-icon {
  width: 36px;
  height: 36px;
  flex: none;
  display: grid;
  place-items: center;
  border-radius: 10px;
  color: var(--emerald-primary);
  background: rgba(52, 211, 153, 0.1);
  border: 1px solid rgba(52, 211, 153, 0.2);
}

.scan-copy {
  min-width: 0;
  flex: 1;
}

.scan-copy h3 {
  margin: 0;
  font-size: 13px;
  font-weight: 600;
  color: var(--text-main);
}

.scan-copy p {
  margin: 2px 0 0;
  font-size: 11px;
  color: var(--text-muted);
}

.scan-ready {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  flex: none;
  padding: 3px 8px;
  border-radius: 999px;
  border: 1px solid rgba(52, 211, 153, 0.16);
  background: rgba(52, 211, 153, 0.08);
  color: var(--emerald-primary);
  font-size: 10px;
  font-weight: 500;
}

.scan-ready .status-dot {
  width: 5px;
  height: 5px;
}

.scan-list {
  display: flex;
  flex-direction: column;
  gap: 3px;
  max-height: 156px;
  overflow-y: auto;
  padding: 8px 14px 10px;
  border-top: 1px solid rgba(255, 255, 255, 0.05);
}

.scan-row {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  font-family: var(--font-mono);
  font-size: 10.5px;
  color: var(--text-muted);
}

.scan-row svg {
  flex: none;
  color: var(--text-dim);
}

.scan-name {
  flex: 1;
  min-width: 0;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  user-select: text;
}

.scan-size {
  flex: none;
  font-size: 9.5px;
  color: var(--text-dim);
}

.scan-more {
  padding: 5px 0 2px;
  text-align: center;
  font-size: 10px;
  color: var(--text-dim);
}

/* ---------- Errors ---------- */

.inline-error {
  display: flex;
  align-items: flex-start;
  gap: 9px;
  padding: 10px 12px;
  border-radius: 11px;
  border: 1px solid rgba(239, 68, 68, 0.22);
  background: rgba(239, 68, 68, 0.075);
  color: var(--ruby-primary);
  font-size: 11.5px;
  line-height: 1.5;
  animation: rise-in var(--dur-base) var(--ease-out) both;
}

.inline-error svg {
  flex: none;
  margin-top: 1px;
}

/* ---------- Running ---------- */

.run-pane {
  display: flex;
  flex-direction: column;
  padding-top: 4px;
  animation: rise-in var(--dur-rise) var(--ease-spring) both;
}

.run-top {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}

.run-eyebrow {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  padding-top: 4px;
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: var(--accent-hover);
}

.live-dot {
  width: 6px;
  height: 6px;
  flex: none;
  border-radius: 50%;
  background: var(--accent-primary);
}

.run-queue {
  padding: 1px 7px;
  border-radius: 999px;
  border: 1px solid rgba(255, 255, 255, 0.06);
  background: rgba(255, 255, 255, 0.045);
  color: var(--text-muted);
  font-family: var(--font-mono);
  font-size: 9.5px;
  font-weight: 500;
  letter-spacing: 0;
  text-transform: none;
}

.run-elapsed {
  padding: 1px 7px;
  border-radius: 999px;
  border: 1px solid rgba(var(--accent-rgb), 0.22);
  background: rgba(var(--accent-rgb), 0.08);
  color: var(--accent-hover);
  font-family: var(--font-mono);
  font-size: 9.5px;
  font-weight: 500;
  letter-spacing: 0;
  text-transform: none;
  font-variant-numeric: tabular-nums;
  animation: rise-in var(--dur-base) var(--ease-out) both;
}

.run-percent {
  display: flex;
  align-items: baseline;
  flex: none;
  font-family: var(--font-mono);
  font-size: 31px;
  font-weight: 500;
  letter-spacing: -0.06em;
  line-height: 1;
  color: var(--text-main);
}

.run-percent span {
  margin-left: 2px;
  font-size: 13px;
  font-weight: 400;
  letter-spacing: 0;
  color: var(--text-dim);
}

.run-title {
  margin: 15px 0 0;
  font-size: 20px;
  font-weight: 600;
  letter-spacing: -0.03em;
  line-height: 1.3;
  color: var(--text-main);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.run-status {
  min-height: 18px;
  margin: 4px 0 17px;
  font-size: 12.5px;
  color: var(--text-muted);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.progress-track {
  position: relative;
  height: 8px;
  overflow: hidden;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.06);
  box-shadow: inset 0 1px 2px rgba(0, 0, 0, 0.3);
}

.progress-track.indeterminate .progress-fill {
  opacity: 0.45;
}

.progress-track.indeterminate::after {
  content: '';
  position: absolute;
  top: 0;
  bottom: 0;
  left: -38%;
  width: 36%;
  border-radius: inherit;
  background: linear-gradient(90deg, transparent, rgba(var(--accent-rgb), 0.9), transparent);
  animation: indeterminate-sweep 1.45s var(--ease-in-out) infinite;
}

.progress-fill {
  position: relative;
  height: 100%;
  overflow: hidden;
  border-radius: inherit;
  background: var(--accent-primary);
  transition: width 0.4s var(--ease-out);
}

.progress-sheen {
  display: none;
}

.stage-rail {
  display: flex;
  align-items: center;
  gap: 7px;
  margin-top: 19px;
  padding: 0 1px;
}

.stage {
  display: flex;
  align-items: center;
  gap: 6px;
  flex: none;
  font-size: 11px;
  font-weight: 500;
  color: var(--text-dim);
  white-space: nowrap;
  transition: color var(--dur-base) var(--ease-out);
}

.stage-dot {
  width: 14px;
  height: 14px;
  flex: none;
  display: grid;
  place-items: center;
  border-radius: 50%;
  border: 1px solid rgba(255, 255, 255, 0.12);
  background: rgba(255, 255, 255, 0.02);
  transition:
    border-color var(--dur-base) var(--ease-out),
    background var(--dur-base) var(--ease-out),
    box-shadow var(--dur-base) var(--ease-out);
}

.stage.step-active {
  color: var(--text-main);
}

.stage.step-active .stage-dot {
  border-color: var(--accent-primary);
  background: var(--accent-subtle);
  box-shadow: var(--shadow-e1);
}

.stage.step-done {
  color: var(--emerald-primary);
}

.stage.step-done .stage-dot {
  border-color: rgba(52, 211, 153, 0.5);
  background: rgba(52, 211, 153, 0.15);
  color: var(--emerald-primary);
}

.stage-link {
  flex: 1;
  min-width: 8px;
  height: 1px;
  background: rgba(255, 255, 255, 0.07);
  transition: background var(--dur-base) var(--ease-out);
}

.stage-link.done {
  background: var(--emerald-border);
}

.run-meta {
  display: flex;
  align-items: center;
  gap: 7px;
  flex-wrap: wrap;
  margin-top: 18px;
}

.meta-chip {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 4px 8px;
  border-radius: 7px;
  border: 1px solid rgba(255, 255, 255, 0.05);
  background: rgba(255, 255, 255, 0.03);
  color: var(--text-muted);
  font-family: var(--font-mono);
  font-size: 10px;
}

.log-toggle {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  margin-left: auto;
  padding: 5px 7px;
  border: 0;
  border-radius: 7px;
  background: transparent;
  color: var(--text-muted);
  font-family: var(--font-ui);
  font-size: 11px;
  cursor: pointer;
  transition:
    color var(--dur-fast) var(--ease-out),
    background var(--dur-fast) var(--ease-out);
}

.log-toggle:hover {
  color: var(--text-main);
  background: rgba(255, 255, 255, 0.05);
}

.log-toggle svg:last-child {
  transition: transform var(--dur-base) var(--ease-out);
}

.log-toggle svg.rotated {
  transform: rotate(180deg);
}

.console {
  max-height: 146px;
  overflow-y: auto;
  margin-top: 11px;
  padding: 9px 12px;
  border-radius: 12px;
  border: 1px solid rgba(255, 255, 255, 0.06);
  background: #07080c;
  font-family: var(--font-mono);
  font-size: 10.5px;
  line-height: 1.65;
  user-select: text;
  animation: console-in var(--dur-base) var(--ease-out) both;
}

.console-empty {
  color: var(--text-dim);
}

.console-line {
  display: flex;
  gap: 8px;
  color: #9ca3af;
  white-space: pre-wrap;
  word-break: break-word;
}

.console-line::before {
  content: '';
  width: 4px;
  height: 4px;
  flex: none;
  margin-top: 7px;
  border-radius: 50%;
  background: #374151;
}

.console-line.success { color: var(--emerald-primary); }
.console-line.success::before { background: var(--emerald-primary); }
.console-line.warn { color: #fcd34d; }
.console-line.warn::before { background: var(--amber-primary); }
.console-line.error { color: var(--ruby-primary); }
.console-line.error::before { background: var(--ruby-primary); }

/* ---------- Complete ---------- */

.complete-pane {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 16px 16px 8px;
  text-align: center;
  animation: rise-in var(--dur-rise) var(--ease-spring) both;
}

.success-orbit {
  position: relative;
  width: 72px;
  height: 72px;
  display: grid;
  place-items: center;
  margin-bottom: 17px;
}

.success-orbit::before,
.success-orbit::after {
  content: none;
}

.eyebrow {
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: var(--emerald-primary);
}

.success-mark {
  width: 56px;
  height: 56px;
  display: grid;
  place-items: center;
  border-radius: var(--radius-lg);
  color: var(--emerald-primary);
  background: var(--emerald-bg);
  border: 1px solid var(--emerald-border);
  animation: check-pop 0.35s var(--ease-out) both;
}

.complete-pane h3 {
  margin: 8px 0 0;
  font-size: 24px;
  font-weight: 600;
  letter-spacing: -0.035em;
  line-height: 1.2;
  color: var(--text-main);
}

.complete-copy {
  max-width: 390px;
  margin: 7px 0 0;
  font-size: 12.5px;
  line-height: 1.5;
  color: var(--text-muted);
}

.complete-stats {
  display: flex;
  align-items: center;
  gap: 22px;
  margin-top: 22px;
  padding: 12px 22px;
  border-radius: 14px;
  border: 1px solid rgba(255, 255, 255, 0.06);
  background: rgba(255, 255, 255, 0.03);
}

.stat {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.stat strong {
  font-family: var(--font-mono);
  font-size: 18px;
  font-weight: 500;
  letter-spacing: -0.03em;
  color: var(--text-main);
}

.stat span {
  font-size: 9.5px;
  font-weight: 500;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--text-dim);
  white-space: nowrap;
}

.stat-divider {
  width: 1px;
  height: 30px;
  background: rgba(255, 255, 255, 0.07);
}

/* ---------- Timings import ---------- */

.timing-actions,
.format-help-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.timing-actions {
  justify-content: center;
}

.text-btn {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  background: transparent;
  border: none;
  color: var(--accent-hover);
  font-size: 11.5px;
  font-weight: 500;
  cursor: pointer;
  padding: 4px 6px;
  border-radius: var(--radius-xs);
  transition: background var(--dur-fast) var(--ease-out);
}

.text-btn:hover {
  background: var(--accent-subtle);
}

.btn-soft.help-open {
  border-color: var(--accent-border);
  color: var(--accent-hover);
}

.chev-rotated {
  transform: rotate(180deg);
}

.format-help {
  padding: 12px 14px;
  border-radius: var(--radius-md);
  border: 1px solid var(--border-subtle);
  background: var(--bg-input);
}

.format-help h4 {
  margin: 0 0 8px;
  font-size: 12px;
  font-weight: 600;
  color: var(--text-main);
}

.format-help ul {
  margin: 0 0 10px;
  padding-left: 18px;
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.format-help li {
  font-size: 11.5px;
  color: var(--text-secondary);
  line-height: 1.45;
}

.format-code {
  margin: 0;
  padding: 10px 12px;
  border-radius: var(--radius-sm);
  border: 1px solid var(--border-subtle);
  background: var(--bg-base);
  font-family: var(--font-mono);
  font-size: 10.5px;
  line-height: 1.5;
  color: var(--text-secondary);
  overflow-x: auto;
  max-height: 180px;
}

.format-help-actions {
  margin-top: 10px;
}

.json-ok {
  color: var(--emerald-primary);
  font-weight: 500;
}

.json-missing {
  color: var(--amber-primary);
}

.no-audio-chip {
  color: var(--text-muted);
}

/* ---------- Engine missing notice ---------- */

.engine-note {
  display: flex;
  align-items: center;
  gap: 10px;
  max-width: 520px;
  margin: 0 auto 12px;
  padding: 8px 12px;
  border: 1px solid var(--border-subtle);
  border-left: 2px solid var(--amber-primary);
  border-radius: var(--radius-md, 8px);
  background: var(--bg-surface);
  color: var(--text-secondary);
}

.engine-note svg {
  flex-shrink: 0;
  color: var(--amber-primary);
}

.engine-note p {
  flex: 1;
  margin: 0;
  font-size: 12px;
  line-height: 1.5;
}

.engine-note strong {
  color: var(--text-primary);
  font-weight: 600;
}

/* ---------- Footer ---------- */

.align-footer {
  position: relative;
  z-index: 1;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 14px 24px 18px;
  border-top: 1px solid var(--border-subtle);
  background: var(--bg-surface);
}

.footer-note {
  min-width: 0;
  font-size: 11.5px;
  color: var(--text-dim);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.footer-spacer {
  flex: 1;
}

.btn-run {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  height: 36px;
  padding: 0 16px;
  border-radius: var(--radius-sm);
  border: none;
  background: var(--accent-primary);
  color: #fff;
  font-family: var(--font-ui);
  font-size: var(--text-sm);
  font-weight: 500;
  line-height: 1;
  white-space: nowrap;
  cursor: pointer;
  transition: background var(--dur-fast) var(--ease-out);
}

.btn-run:hover:not(:disabled) {
  background: var(--accent-hover);
}

.btn-run:active:not(:disabled) {
  background: var(--accent-deep);
}

.btn-run:disabled {
  opacity: 0.38;
  cursor: not-allowed;
}

.btn-soft {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  height: 34px;
  padding: 0 12px;
  border-radius: var(--radius-sm);
  border: 1px solid var(--border-medium);
  background: var(--bg-surface-elevated);
  color: var(--text-main);
  font-family: var(--font-ui);
  font-size: 11.5px;
  font-weight: 500;
  line-height: 1;
  cursor: pointer;
  transition:
    background var(--dur-fast) var(--ease-out),
    border-color var(--dur-fast) var(--ease-out);
}

.btn-soft:hover {
  background: var(--bg-surface-hover);
}

.btn-danger-ghost {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 32px;
  padding: 0 9px;
  border-radius: var(--radius-sm);
  border: 1px solid transparent;
  background: transparent;
  color: var(--ruby-primary);
  font-family: var(--font-ui);
  font-size: 11.5px;
  font-weight: 500;
  cursor: pointer;
  transition:
    background var(--dur-fast) var(--ease-out),
    border-color var(--dur-fast) var(--ease-out);
}

.btn-danger-ghost:hover {
  background: var(--ruby-bg);
  border-color: var(--ruby-border);
}

/* ---------- Minimized dock ---------- */

.dock {
  position: fixed;
  right: 24px;
  bottom: 24px;
  z-index: 9999;
  width: min(420px, calc(100vw - 32px));
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 12px 10px 10px;
  border-radius: var(--radius-lg);
  border: 1px solid var(--border-medium);
  background: var(--glass-bg);
  box-shadow: var(--shadow-e3);
  backdrop-filter: blur(18px) saturate(1.35);
  -webkit-backdrop-filter: blur(18px) saturate(1.35);
  cursor: pointer;
  user-select: none;
  animation: dock-in var(--dur-over) var(--ease-out) both;
  transition:
    border-color var(--dur-base) var(--ease-out),
    box-shadow var(--dur-base) var(--ease-out);
}

.dock:hover {
  border-color: var(--accent-border);
}

.dock.complete {
  border-color: rgba(52, 211, 153, 0.24);
}

.dock-ring {
  position: relative;
  width: 42px;
  height: 42px;
  flex: none;
  display: grid;
  place-items: center;
  border-radius: 50%;
  background: conic-gradient(var(--accent-primary) var(--progress, 0%), rgba(255, 255, 255, 0.07) 0);
}

.dock-ring::before {
  content: '';
  position: absolute;
  inset: 3px;
  border-radius: 50%;
  background: #101218;
}

.dock.complete .dock-ring {
  background: conic-gradient(var(--emerald-primary) 100%, rgba(255, 255, 255, 0.07) 0);
}

.dock-ring-inner {
  position: relative;
  z-index: 1;
  display: grid;
  place-items: center;
  color: var(--accent-hover);
}

.dock.complete .dock-ring-inner {
  color: var(--emerald-primary);
}

.dock-spinner {
  width: 14px;
  height: 14px;
  border-radius: 50%;
  border: 2px solid rgba(var(--accent-rgb), 0.22);
  border-top-color: var(--accent-hover);
  animation: spin 0.8s linear infinite;
}

.dock-copy {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 1px;
  text-align: left;
}

.dock-title {
  font-size: 12.5px;
  font-weight: 600;
  color: var(--text-main);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.dock-sub {
  font-family: var(--font-mono);
  font-size: 10px;
  color: var(--text-dim);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.dock-actions {
  display: flex;
  align-items: center;
  gap: 6px;
  flex: none;
}

.dock-icon {
  width: 30px;
  height: 30px;
  display: grid;
  place-items: center;
  border-radius: 9px;
  border: 1px solid rgba(255, 255, 255, 0.06);
  background: rgba(255, 255, 255, 0.04);
  color: var(--text-muted);
  cursor: pointer;
  transition:
    color var(--dur-fast) var(--ease-out),
    background var(--dur-fast) var(--ease-out);
}

.dock-icon:hover {
  color: #fff;
  background: rgba(255, 255, 255, 0.08);
}

.dock-icon.danger {
  color: var(--ruby-primary);
  border-color: rgba(239, 68, 68, 0.15);
  background: rgba(239, 68, 68, 0.07);
}

.dock-icon.danger:hover {
  background: rgba(239, 68, 68, 0.14);
}

.dock-open {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  height: 30px;
  padding: 0 10px;
  border-radius: 9px;
  border: 1px solid rgba(52, 211, 153, 0.28);
  background: rgba(52, 211, 153, 0.12);
  color: var(--emerald-primary);
  font-family: var(--font-ui);
  font-size: 10.5px;
  font-weight: 600;
  cursor: pointer;
  transition: background var(--dur-fast) var(--ease-out);
}

.dock-open:hover {
  background: rgba(52, 211, 153, 0.2);
}

/* ---------- Motion ---------- */

@keyframes dialog-in {
  from { opacity: 0; transform: translateY(16px) scale(0.975); }
  to { opacity: 1; transform: translateY(0) scale(1); }
}

@keyframes rise-in {
  from { opacity: 0; transform: translateY(7px); }
  to { opacity: 1; transform: translateY(0); }
}

@keyframes live-pulse {
  0% { box-shadow: 0 0 0 0 rgba(var(--accent-rgb), 0.45); }
  70% { box-shadow: 0 var(--shadow-e1); }
  100% { box-shadow: 0 0 0 0 rgba(var(--accent-rgb), 0); }
}

@keyframes soft-pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.4; }
}

@keyframes sheen {
  100% { transform: translateX(100%); }
}

@keyframes indeterminate-sweep {
  0% { left: -38%; }
  100% { left: 104%; }
}

@keyframes orbit-pulse {
  0%, 100% { transform: scale(1); opacity: 0.65; }
  50% { transform: scale(1.07); opacity: 1; }
}

@keyframes check-pop {
  0% { opacity: 0; transform: scale(0.4); }
  60% { transform: scale(1.08); }
  100% { opacity: 1; transform: scale(1); }
}

@keyframes console-in {
  from { opacity: 0; transform: translateY(-4px); }
  to { opacity: 1; transform: translateY(0); }
}

@keyframes dock-in {
  from { opacity: 0; transform: translateY(14px) scale(0.97); }
  to { opacity: 1; transform: translateY(0) scale(1); }
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

/* ---------- Responsive ---------- */

@media (max-width: 680px) {
  .align-overlay {
    padding: 10px;
  }

  .align-dialog {
    width: calc(100vw - 20px);
    max-height: calc(100vh - 20px);
    border-radius: 20px;
  }

  .align-header {
    align-items: flex-start;
    flex-wrap: wrap;
    gap: 12px;
    padding: 17px 16px 13px;
  }

  .brand-text p {
    display: none;
  }

  .header-controls {
    margin-left: auto;
  }

  .align-body {
    padding: 0 16px 17px;
  }

  .settings-row {
    align-items: stretch;
    flex-direction: column;
    gap: 12px;
    padding: 12px;
  }

  .setting-sep {
    width: 100%;
    height: 1px;
  }

  .engine-toggle {
    justify-content: space-between;
  }

  .dropzone {
    min-height: 176px;
    padding: 20px;
  }

  .dropzone.compact {
    flex-direction: column;
    text-align: center;
  }

  .dropzone.compact .drop-copy {
    align-items: center;
  }

  .path-shell {
    flex-wrap: wrap;
    gap: 9px;
  }

  .path-divider {
    display: none;
  }

  .path-input {
    order: 3;
    flex-basis: 100%;
    padding: 4px 2px;
  }

  .path-scan {
    margin-left: auto;
  }

  .stage-name {
    font-size: 10px;
  }

  .run-title {
    font-size: 17px;
  }

  .run-percent {
    font-size: 26px;
  }

  .complete-pane h3 {
    font-size: 21px;
  }

  .align-footer {
    padding: 12px 16px 15px;
  }

  .footer-note {
    display: none;
  }

  .dock {
    right: 12px;
    bottom: 12px;
    width: calc(100vw - 24px);
  }
}

@media (prefers-reduced-motion: reduce) {
  *,
  *::before,
  *::after {
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
  }
}
</style>
