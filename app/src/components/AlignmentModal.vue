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
              <h2 id="alignment-dialog-title">{{ isTauri ? 'Add Recitation' : 'Import Recitation Timings' }}</h2>
            </div>
          </div>

          <div class="header-controls">
            <!-- Mode switch only on Desktop Tauri where Alignment speech engine is available -->
            <div v-if="isTauri && !isRunning && !isComplete" class="mode-switch" role="tablist" aria-label="Input mode">
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
          <!-- Session configuration (Desktop Speech Engine only) -->
          <div v-if="isTauri && !isRunning && !isComplete" class="settings-row">
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

          <!-- Engine missing: calm notice, only on Desktop Tauri -->
          <div v-if="isTauri && missingEngineBanner" class="engine-note">
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

          <!-- Import Timing: Individual / Batch folder (Batch only on Desktop) -->
          <div v-if="isTauri && activeMode === 'timings' && !isRunning && !isComplete" class="pane-option-bar">
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
import { ref, computed, onMounted, onUnmounted, watch } from 'vue';
import { projectStore } from '../services/projectStore';
import { isEngineInstalled, isTauriEnvironment } from '../services/api';
import { EXAMPLE_TIMINGS_STRING, TIMING_RULES } from '../services/timingsImport';
import { useAlignmentRunner, type QueueItem } from '../composables/useAlignmentRunner';
import { useTimingImporter } from '../composables/useTimingImporter';
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

const isTauri = isTauriEnvironment();
const visible = ref(false);
const isMinimized = ref(false);
const activeMode = ref<'align' | 'timings'>(isTauri ? 'align' : 'timings');
const alignInput = ref<'files' | 'dir'>('files');
const timingInput = ref<'single' | 'batch'>('single');
const isDragging = ref(false);
const fastMode = ref(true);
const selectedRiwayah = ref<string>(projectStore.project?.settings?.riwayah || 'Hafs');
const isRunning = ref(false);
const isComplete = ref(false);
const isAborted = ref(false);
const errorMessage = ref('');
const engineMissing = ref(false);

const fileInput = ref<HTMLInputElement | null>(null);
const consoleBoxRef = ref<HTMLElement | null>(null);

function handleEscape(e: KeyboardEvent) {
  if (e.key === 'Escape' && visible.value && !isRunning.value) close();
}

onMounted(() => {
  window.addEventListener('keydown', handleEscape);
});

onUnmounted(() => {
  window.removeEventListener('keydown', handleEscape);
  alignment.cleanup();
});

const alignment = useAlignmentRunner(
  isRunning,
  isComplete,
  isAborted,
  errorMessage,
  selectedRiwayah,
  fastMode,
  consoleBoxRef,
  fileInput
);

const {
  currentStage,
  progressPercent,
  speedX,
  statusMessage,
  elapsedLabel,
  progressIndeterminate,
  currentProcessingFileName,
  currentStageLabel,
  consoleLogs,
  showLogs,
  filesQueue,
  currentQueueIndex,
  dirPath,
  isScanningDir,
  dirScanError,
  scannedFiles,
  scannedTotalBytes,
  queueTotalBytes,
  startElapsedTimer,
  stopElapsedTimer,
  pickDirectory,
  scanDirectory,
  triggerFilePick,
  onFilesChosen,
  removeQueueItem,
  clearQueue,
  stopBatch,
  startFilesAlignmentQueue,
  startDirAlignment,
} = alignment;

function onDropFiles(e: DragEvent) {
  isDragging.value = false;
  alignment.onDropFiles(e);
}

const timingImporter = useTimingImporter(
  alignment.addLog,
  isRunning,
  isComplete,
  isAborted,
  errorMessage,
  statusMessage,
  currentStage,
  progressPercent,
  () => {
    projectStore.currentTab.value = 'studio';
    visible.value = false;
    isMinimized.value = false;
    timingImporter.timingPairs.value = [];
  }
);

const {
  timingPairs,
  showFormatHelp,
  importIndex,
  importTotal,
  importCurrentName,
  importablePairs,
  pairNeedsAudio,
  triggerTimingPick,
  pickTimingFolder,
  removeTimingPair,
  startTimingImport,
  saveExampleJson,
  copyExampleJson,
} = timingImporter;

function onDropTiming(e: DragEvent) {
  isDragging.value = false;
  timingImporter.onDropTiming(e);
}

watch(isRunning, (running) => {
  if (running) startElapsedTimer();
  else stopElapsedTimer();
});

const alignedWordsCount = computed(() => {
  return projectStore.project.surahs.reduce((total, surah) => {
    return total + surah.ayahs.reduce((ayahSum, ayah) => {
      return ayahSum + ayah.segments.reduce((segSum, seg) => segSum + seg.words.length, 0);
    }, 0);
  }, 0);
});

const missingEngineBanner = computed(() => engineMissing.value && activeMode.value === 'align');

function requestEngineSetup() {
  window.dispatchEvent(new CustomEvent('quran-open-setup'));
}

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
  stopElapsedTimer();
  selectedRiwayah.value = projectStore.project?.settings?.riwayah || 'Hafs';
  filesQueue.value = [];
  timingPairs.value = [];
  showFormatHelp.value = false;
  if (!isTauri) {
    activeMode.value = 'timings';
  }

  engineMissing.value = false;
  if (isTauri) {
    isEngineInstalled()
      .then((ok) => { engineMissing.value = !ok; })
      .catch(() => {});
  }
}

function close() {
  if (!isRunning.value) {
    if (projectStore.isDirty.value) {
      projectStore.saveActiveProject().catch(() => {});
    }
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
  if (projectStore.isDirty.value) {
    projectStore.saveActiveProject().catch(() => {});
  }
  projectStore.currentTab.value = 'studio';
  visible.value = false;
  isMinimized.value = false;
  filesQueue.value = [];
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

<style scoped src="./alignment/alignmentModal.css"></style>
