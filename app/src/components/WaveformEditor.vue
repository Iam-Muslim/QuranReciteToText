<template>
  <div class="waveform-editor glass-panel">
    <!-- Top Toolbar Controls -->
    <div class="editor-toolbar">
      <!-- Left: Transport Controls -->
      <div class="transport-controls">
        <button 
          class="btn-icon play-btn" 
          @click="togglePlay" 
          :title="isPlaying ? 'Pause (Space)' : 'Play (Space)'"
          :disabled="!hasAudioLoaded"
        >
          <Pause v-if="isPlaying" :size="16" />
          <Play v-else :size="16" />
        </button>

        <button 
          class="btn-icon" 
          @click="projectStore.jumpToPrevAyah()" 
          title="Previous Ayah ([)"
          :disabled="!hasAudioLoaded"
        >
          <ChevronLeft :size="15" />
        </button>

        <button 
          class="btn-icon" 
          @click="skipBackward(2)" 
          title="Rewind 2s"
          :disabled="!hasAudioLoaded"
        >
          <RotateCcw :size="13" />
        </button>

        <button 
          class="btn-icon" 
          @click="skipForward(2)" 
          title="Forward 2s"
          :disabled="!hasAudioLoaded"
        >
          <RotateCw :size="13" />
        </button>

        <button 
          class="btn-icon" 
          @click="projectStore.jumpToNextAyah()" 
          title="Next Ayah (])"
          :disabled="!hasAudioLoaded"
        >
          <ChevronRight :size="15" />
        </button>

        <!-- Time Readout (MM:SS / MM:SS) -->
        <div class="time-readout">
          <span class="current-time">{{ formatAccurateTime(currentTime) }}</span>
          <span class="time-sep">/</span>
          <span class="total-time">{{ formatAccurateTime(duration) }}</span>
        </div>

        <!-- Loop Mode Toggle -->
        <button 
          class="btn-icon loop-btn" 
          :class="{ 'loop-active': projectStore.loopMode.value !== 'none' }"
          @click="cycleLoopMode"
          :title="`Loop: ${projectStore.loopMode.value.toUpperCase()}`"
        >
          <Repeat :size="13" />
          <span v-if="projectStore.loopMode.value !== 'none'" class="loop-indicator">
            {{ projectStore.loopMode.value === 'word' ? '1w' : '1v' }}
          </span>
        </button>

        <!-- Active Ayah Badge -->
        <div class="active-verse-badge" v-if="projectStore.activeAyahNumber.value">
          <span>آية {{ projectStore.activeAyahNumber.value }}</span>
        </div>
      </div>

      <!-- Right: Speed, Zoom, Audio Loading -->
      <div class="timeline-tools">
        <!-- Speed Dropdown -->
        <select v-model="playbackRate" @change="changePlaybackRate" class="speed-select" title="Playback Speed">
          <option :value="0.75">0.75x</option>
          <option :value="1.0">1.0x</option>
          <option :value="1.25">1.25x</option>
          <option :value="1.5">1.5x</option>
        </select>

        <div class="divider"></div>

        <!-- Zoom Slider -->
        <div class="tool-group">
          <ZoomOut :size="13" class="zoom-icon" @click="adjustZoom(-25)" />
          <input 
            type="range" 
            min="40" 
            max="320" 
            step="10" 
            v-model.number="zoomLevel" 
            @input="updateZoom"
            class="zoom-slider"
            title="Zoom (or Ctrl + Mouse Wheel)"
          />
          <ZoomIn :size="13" class="zoom-icon" @click="adjustZoom(25)" />
        </div>

        <div class="divider"></div>

        <!-- Load Audio File Button -->
        <input 
          type="file" 
          ref="fileInput" 
          accept="audio/*,video/*" 
          style="display: none" 
          @change="handleFileUpload" 
        />
        <button class="btn-icon load-btn" @click="triggerFileInput" title="Load Audio File">
          <UploadCloud :size="15" />
        </button>
      </div>
    </div>

    <!-- Overview Minimap Track -->
    <div class="minimap-container" v-show="hasAudioLoaded">
      <div id="waveform-minimap" ref="minimapMount"></div>
    </div>

    <!-- Main Waveform & Multi-Track Container (QuranCaption Model) -->
    <div 
      class="waveform-container" 
      :class="{ 'drop-active': isDraggingFile, 'is-panning': isPanning }"
      @dragover.prevent="isDraggingFile = true"
      @dragleave.prevent="isDraggingFile = false"
      @drop.prevent="handleFileDrop"
      @wheel="handleTimelineWheel"
      @mousedown="handleTimelineMouseDown"
    >
      <!-- Drop Overlay -->
      <div v-if="isDraggingFile" class="drag-drop-overlay">
        <UploadCloud :size="30" class="drop-icon" />
        <span class="drop-text">Drop recitation audio here</span>
      </div>

      <!-- No Audio Empty State -->
      <div v-if="!hasAudioLoaded" class="empty-audio-dropzone" @click="triggerFileInput">
        <Loader2 v-if="isUploadingAudio" :size="28" class="drop-icon animate-spin" />
        <FileAudio v-else :size="26" class="drop-icon" />
        <span class="empty-title">
          {{ isUploadingAudio ? 'Uploading & generating FFmpeg waveform peaks...' : 'Select or drop recitation audio to begin' }}
        </span>
        <span class="empty-formats">Supports MP3, WAV, M4A, FLAC, OGG, AAC, OPUS</span>
      </div>

      <!-- Timeline Ruler -->
      <div id="timeline-ruler" ref="timelineContainer" v-show="hasAudioLoaded"></div>
      
      <!-- WaveSurfer Waveform Mount (Peaks Layer Only, Zero Memory Allocation) -->
      <div id="waveform-mount" ref="waveformMount" v-show="hasAudioLoaded"></div>

      <!-- Track 1: Segments Lane (QuranCaption Multi-Segment Architecture) -->
      <div 
        class="track-viewport ayah-track-viewport" 
        ref="ayahTrackViewport"
        v-show="hasAudioLoaded"
        @scroll.passive="onTrackViewportScroll"
      >
        <div 
          class="track-canvas" 
          :style="{ width: `${totalTimelineWidth}px` }"
        >
          <!-- Contiguous Segment Blocks Across Entire Recitation -->
          <div
            v-for="seg in timelineSegments"
            :key="seg.id"
            class="timeline-ayah-block"
            :class="{
              'ayah-selected': projectStore.activeAyahNumber.value === seg.ayahNumber,
              'ayah-active': isSegmentPlaying(seg),
              'ayah-has-issues': seg.hasIssues,
              'ayah-coverage-gap': seg.hasCoverageGap
            }"
            :style="{
              left: `${seg.start * zoomLevel}px`,
              width: `${Math.max(30, (seg.end - seg.start) * zoomLevel)}px`
            }"
            @click="handleSegmentClick(seg)"
            :title="`${seg.label}: [${seg.start.toFixed(2)}s - ${seg.end.toFixed(2)}s] ${seg.gapWarning ? ' - ' + seg.gapWarning : ''}`"
          >
            <!-- Left Segment Boundary Handle (Stretches Start into Silence) -->
            <div
              class="ayah-edge-handle edge-left"
              :class="{ 'is-dragging': activeDraggingBoundary?.id === seg.id && activeDraggingBoundary?.edge === 'start' }"
              @mousedown.stop.prevent="startDragSegmentBoundary(seg, 'start', $event)"
              title="Drag segment start boundary into silence"
            >
              <div class="edge-grip-bar"></div>
            </div>

            <div class="segment-badges-row">
              <span class="ayah-label-badge">{{ seg.label }}</span>
              <span v-if="seg.hasCoverageGap" class="coverage-gap-badge" :title="seg.gapWarning">
                ⚠️ فجوة تلاوة
              </span>
            </div>
            <span v-if="seg.connectedUthmaniText" class="ayah-snippet-text">{{ seg.connectedUthmaniText }}</span>

            <!-- Right Segment Boundary Handle (Stretches End into Silence) -->
            <div
              class="ayah-edge-handle edge-right"
              :class="{ 'is-dragging': activeDraggingBoundary?.id === seg.id && activeDraggingBoundary?.edge === 'end' }"
              @mousedown.stop.prevent="startDragSegmentBoundary(seg, 'end', $event)"
              title="Drag segment end boundary into silence"
            >
              <div class="edge-grip-bar"></div>
            </div>

            <!-- Floating tooltip while dragging Segment edge -->
            <div 
              v-if="activeDraggingBoundary?.id === seg.id" 
              class="boundary-time-tooltip"
            >
              {{ activeDraggingBoundary.time.toFixed(2) }}s
            </div>
          </div>

          <!-- Playhead Line across Segment lane (Direct GPU translation, zero Vue diffing lag) -->
          <div 
            ref="segmentPlayheadLine"
            class="track-playhead-line"
          ></div>
        </div>
      </div>

      <!-- Track 2: Word Alignment Track (Grouped by Segment, Independent Boundary Handles) -->
      <div 
        class="track-viewport word-track-viewport" 
        ref="wordTrackViewport"
        v-show="hasAudioLoaded"
        @scroll.passive="onTrackViewportScroll"
      >
        <div 
          class="track-canvas" 
          :style="{ width: `${totalTimelineWidth}px` }"
        >
          <!-- Words grouped per Segment with O(1) Boundary Handles -->
          <div
            v-for="seg in timelineSegments"
            :key="`words_${seg.id}`"
            class="segment-words-group"
          >
            <div
              v-for="(w, wIdx) in seg.words"
              :key="`tl_${seg.id}_w_${wIdx}`"
              class="timeline-word-block"
              :class="{
                'word-karaoke-active': isTimelineWordActive(w),
                'word-selected': isTimelineWordSelected(w),
                'word-warning': w.score < 0.85 && w.score >= 0.80,
                'word-critical': w.score < 0.80,
                'word-edited': w.is_edited
              }"
              :style="{
                left: `${w.start * zoomLevel}px`,
                width: `${Math.max(22, (w.end - w.start) * zoomLevel)}px`,
              }"
              @click="handleWordClick(w)"
              @contextmenu.prevent="handleContextMenu($event, w)"
              :title="`Word: ${w.word} | Score: ${(w.score * 100).toFixed(0)}% | [${w.start.toFixed(2)}s - ${w.end.toFixed(2)}s]`"
            >
              <!-- Left Outer Boundary Handle (First word of segment or facing silence) -->
              <div
                v-if="isWordBoundaryStart(seg, w, wIdx)"
                class="word-boundary-handle handle-start"
                :class="{ 'is-dragging': activeDraggingBoundary?.id === `${seg.id}_${wIdx}` && activeDraggingBoundary?.edge === 'start' }"
                @mousedown.stop.prevent="startDragWordBoundary(seg, w, wIdx, 'start', $event)"
                title="Drag word start boundary into silence"
              >
                <div class="boundary-bracket">[</div>
                <div class="boundary-line"></div>
              </div>

              <span class="word-uthmani-text">{{ formatTimelineWord(w.word) }}</span>
              <div v-if="w.score < 0.85" class="word-meta-row">
                <span class="word-score-pill" :class="w.score < 0.80 ? 'critical' : 'warning'">
                  {{ (w.score * 100).toFixed(0) }}%
                </span>
              </div>

              <!-- Right Outer Boundary Handle (Last word of segment or facing silence) -->
              <div
                v-if="isWordBoundaryEnd(seg, w, wIdx)"
                class="word-boundary-handle handle-end"
                :class="{ 'is-dragging': activeDraggingBoundary?.id === `${seg.id}_${wIdx}` && activeDraggingBoundary?.edge === 'end' }"
                @mousedown.stop.prevent="startDragWordBoundary(seg, w, wIdx, 'end', $event)"
                title="Drag word end boundary into silence"
              >
                <div class="boundary-line"></div>
                <div class="boundary-bracket">]</div>
              </div>

              <!-- Floating tooltip while dragging Word boundary edge -->
              <div 
                v-if="activeDraggingBoundary?.id === `${seg.id}_${wIdx}`" 
                class="boundary-time-tooltip"
              >
                {{ activeDraggingBoundary.time.toFixed(2) }}s
              </div>
            </div>
          </div>

          <!-- Magnetic Shared-Vertex Vertical Dividers (Between Adjacent Words in SAME Segment) -->
          <div
            v-for="divider in wordDividers"
            :key="divider.id"
            class="shared-divider-handle"
            :class="{ 'is-dragging': activeDraggingDividerId === divider.id }"
            :style="{ left: `${divider.time * zoomLevel}px` }"
            @mousedown.stop.prevent="startDragDivider(divider, $event)"
            title="Drag shared boundary (Adjusts both adjacent words atomically)"
          >
            <div class="divider-line"></div>
            <div class="divider-grabber">
              <span class="divider-grip-dot"></span>
            </div>
            <!-- Real-time seconds pill when dragging -->
            <div v-if="activeDraggingDividerId === divider.id" class="divider-time-tooltip">
              {{ divider.time.toFixed(2) }}s
            </div>
          </div>

          <!-- Playhead Line across Word lane (Direct GPU translation, zero Vue diffing lag) -->
          <div 
            ref="wordPlayheadLine"
            class="track-playhead-line"
          ></div>
        </div>
      </div>

      <!-- Interactive DAW Timeline Scrollbar (QuranCaption Pattern) -->
      <div 
        class="timeline-scrollbar-track" 
        ref="scrollbarTrack"
        v-show="hasAudioLoaded && totalTimelineWidth > viewportClientWidth"
        @mousedown="handleScrollbarTrackClick"
      >
        <div 
          class="timeline-scrollbar-thumb"
          :style="{
            left: `${scrollbarThumbLeft}px`,
            width: `${scrollbarThumbWidth}px`
          }"
          @mousedown.stop.prevent="startDragScrollbarThumb"
        ></div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted, watch, computed } from 'vue';
import WaveSurfer from 'wavesurfer.js';
import TimelinePlugin from 'wavesurfer.js/dist/plugins/timeline.esm.js';
import MinimapPlugin from 'wavesurfer.js/dist/plugins/minimap.esm.js';
import { projectStore } from '../services/projectStore';
import type { AlignedWord, TimelineSegmentItem } from '../types/aligner';
import { 
  Play, 
  Pause, 
  ChevronLeft, 
  ChevronRight, 
  RotateCcw, 
  RotateCw, 
  ZoomIn, 
  ZoomOut, 
  UploadCloud, 
  Repeat, 
  FileAudio,
  Loader2 
} from 'lucide-vue-next';

const emit = defineEmits<{
  (e: 'word-context-menu', event: MouseEvent, word: AlignedWord): void;
}>();

const waveformMount = ref<HTMLElement | null>(null);
const timelineContainer = ref<HTMLElement | null>(null);
const minimapMount = ref<HTMLElement | null>(null);
const ayahTrackViewport = ref<HTMLElement | null>(null);
const wordTrackViewport = ref<HTMLElement | null>(null);
const scrollbarTrack = ref<HTMLElement | null>(null);
const fileInput = ref<HTMLInputElement | null>(null);
const segmentPlayheadLine = ref<HTMLElement | null>(null);
const wordPlayheadLine = ref<HTMLElement | null>(null);
let lastThrottledTime = 0;

let wavesurfer: WaveSurfer | null = null;
let minimapPlugin: any = null;
let isInternalTimeUpdate = false;
let currentlyLoadedAudioUrl: string | null = null;
let resizeObserver: ResizeObserver | null = null;

const isPlaying = ref(false);
const currentTime = ref(0);
const duration = ref(0);
const zoomLevel = ref(120);
const playbackRate = ref(1.0);
const isDraggingFile = ref(false);
const hasAudioLoaded = ref(false);
const isPanning = ref(false);
const currentScrollLeft = ref(0);
const viewportClientWidth = ref(800);
const activeDraggingDividerId = ref<string | null>(null);

const selectedWord = computed<AlignedWord | undefined>(() => {
  if (!projectStore.activeWordLocation.value) return undefined;
  return projectStore.findWordByLocation(projectStore.activeWordLocation.value);
});

// Total timeline canvas width in pixels
const totalTimelineWidth = computed(() => {
  return Math.max(800, Math.ceil(duration.value * zoomLevel.value));
});

// Timeline Segments (matching QuranCaption segment/repetition multi-track architecture)
const timelineSegments = computed<TimelineSegmentItem[]>(() => {
  return projectStore.activeSegments.value;
});

interface SharedDivider {
  id: string;
  segmentId: string;
  leftIndex: number;
  rightIndex: number;
  leftWord: AlignedWord;
  rightWord: AlignedWord;
  time: number;
}

// Compute contiguous magnetic dividers between adjacent words ONLY within the SAME segment when actually contiguous
const wordDividers = computed<SharedDivider[]>(() => {
  const segments = timelineSegments.value;
  const dividers: SharedDivider[] = [];
  for (const seg of segments) {
    const words = seg.words;
    for (let i = 0; i < words.length - 1; i++) {
      const left = words[i];
      const right = words[i + 1];

      // ONLY create shared divider if adjacent words touch (<= 10ms gap).
      // If there is silence between them, each word has its own independent boundary handles!
      if (Math.abs(right.start - left.end) <= 0.01) {
        dividers.push({
          id: `div_${seg.id}_${i}_${i + 1}`,
          segmentId: seg.id,
          leftIndex: i,
          rightIndex: i + 1,
          leftWord: left,
          rightWord: right,
          time: left.end,
        });
      }
    }
  }
  return dividers;
});

// Scrollbar calculations
const scrollbarThumbWidth = computed(() => {
  if (totalTimelineWidth.value <= 0 || viewportClientWidth.value <= 0) return 0;
  const ratio = viewportClientWidth.value / totalTimelineWidth.value;
  if (ratio >= 1) return 0;
  const trackW = scrollbarTrack.value?.clientWidth || viewportClientWidth.value;
  return Math.max(32, Math.round(ratio * trackW));
});

const scrollbarThumbLeft = computed(() => {
  if (totalTimelineWidth.value <= viewportClientWidth.value) return 0;
  const maxScroll = totalTimelineWidth.value - viewportClientWidth.value;
  const trackW = scrollbarTrack.value?.clientWidth || viewportClientWidth.value;
  const maxThumbLeft = trackW - scrollbarThumbWidth.value;
  const progress = Math.max(0, Math.min(1, currentScrollLeft.value / maxScroll));
  return Math.round(progress * maxThumbLeft);
});

function updatePlayheadDirect(t: number) {
  const px = t * zoomLevel.value;
  if (segmentPlayheadLine.value) {
    segmentPlayheadLine.value.style.transform = `translateX(${px}px)`;
  }
  if (wordPlayheadLine.value) {
    wordPlayheadLine.value.style.transform = `translateX(${px}px)`;
  }
}

function formatAccurateTime(secs: number): string {
  if (isNaN(secs) || secs < 0) secs = 0;
  const m = Math.floor(secs / 60);
  const s = Math.floor(secs % 60);
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
}

onMounted(() => {
  initWaveSurfer();
  window.addEventListener('keydown', handleKeydown);

  if (waveformMount.value) {
    resizeObserver = new ResizeObserver(() => {
      updateViewportDimensions();
      syncTrackScroll();
    });
    resizeObserver.observe(waveformMount.value);
  }

  if (projectStore.activeAudioUrl.value) {
    loadAudioUrl(projectStore.activeAudioUrl.value, projectStore.activeAudioFilePath.value);
  }

  watch(() => projectStore.activeAudioUrl.value, (newUrl) => {
    if (newUrl) {
      loadAudioUrl(newUrl, projectStore.activeAudioFilePath.value);
    }
  });
});

onUnmounted(() => {
  window.removeEventListener('keydown', handleKeydown);
  if (resizeObserver) {
    resizeObserver.disconnect();
  }
  if (wavesurfer) {
    wavesurfer.destroy();
  }
});

function initWaveSurfer() {
  if (!waveformMount.value) return;

  minimapPlugin = MinimapPlugin.create({
    container: minimapMount.value || undefined,
    height: 22,
    waveColor: '#1e2533',
    progressColor: '#5e6ad2',
    cursorColor: '#f3f4f6',
  });

  wavesurfer = WaveSurfer.create({
    container: waveformMount.value,
    waveColor: '#2b3345',
    progressColor: '#5e6ad2',
    cursorColor: '#ffffff',
    cursorWidth: 1.5,
    height: 105,
    minPxPerSec: zoomLevel.value,
    autoScroll: true,
    autoCenter: true,
    hideScrollbar: true, // We provide the DAW custom interactive scrollbar
    plugins: [
      minimapPlugin,
      TimelinePlugin.create({
        container: timelineContainer.value || undefined,
        primaryLabelInterval: 5,
        secondaryLabelInterval: 1,
      }),
    ],
  });

  wavesurfer.on('play', () => {
    isPlaying.value = true;
    projectStore.isPlaying.value = true;
  });

  wavesurfer.on('pause', () => {
    isPlaying.value = false;
    projectStore.isPlaying.value = false;
  });

  wavesurfer.on('timeupdate', (t: number) => {
    // 1. Hardware accelerated direct GPU translation (60 FPS fluid, 0ms latency)
    updatePlayheadDirect(t);

    // 2. Throttled store update for timestamp clocks and karaoke boundaries (~10 FPS)
    if (Math.abs(t - lastThrottledTime) >= 0.08) {
      lastThrottledTime = t;
      currentTime.value = t;
      projectStore.updateCurrentTime(t);
    }

    handleLoopCheck(t);
  });

  wavesurfer.on('seeking', (t: number) => {
    currentTime.value = t;
    projectStore.updateCurrentTime(t);
    updatePlayheadDirect(t);
  });

  wavesurfer.on('ready', () => {
    hasAudioLoaded.value = true;
    duration.value = wavesurfer?.getDuration() || 0;
    updateViewportDimensions();
    syncTrackScroll();
    updatePlayheadDirect(currentTime.value);
  });

  // 1:1 Scroll Synchronization between WaveSurfer, Ayah lane, and Word lane
  wavesurfer.on('scroll', () => {
    syncTrackScroll();
  });
}

function updateViewportDimensions() {
  if (waveformMount.value) {
    viewportClientWidth.value = waveformMount.value.clientWidth || 800;
  }
}

function syncTrackScroll() {
  if (!wavesurfer) return;
  const scrollLeft = wavesurfer.getScroll();
  currentScrollLeft.value = scrollLeft;
  if (wordTrackViewport.value && Math.abs(wordTrackViewport.value.scrollLeft - scrollLeft) > 1) {
    wordTrackViewport.value.scrollLeft = scrollLeft;
  }
  if (ayahTrackViewport.value && Math.abs(ayahTrackViewport.value.scrollLeft - scrollLeft) > 1) {
    ayahTrackViewport.value.scrollLeft = scrollLeft;
  }
}

function onTrackViewportScroll(event: Event) {
  const el = event.target as HTMLElement;
  if (!el || !wavesurfer) return;
  if (Math.abs(wavesurfer.getScroll() - el.scrollLeft) > 1) {
    wavesurfer.setScroll(el.scrollLeft);
    syncTrackScroll();
  }
}

// Master Mouse Wheel Handler (QuranCaption Pattern)
// Converts vertical mouse wheel (deltaY) to horizontal timeline scroll,
// and Ctrl + Wheel to smooth zoom centered at the cursor!
function handleTimelineWheel(event: WheelEvent) {
  if (!wavesurfer || !hasAudioLoaded.value) return;

  // 1. Zoom with Ctrl or Cmd + Wheel
  if (event.ctrlKey || event.metaKey) {
    event.preventDefault();
    const zoomDelta = event.deltaY < 0 ? 15 : -15;
    adjustZoom(zoomDelta, event.clientX);
    return;
  }

  // 2. Horizontal Scrolling with standard Mouse Wheel or Trackpad
  event.preventDefault();
  const delta = event.deltaX !== 0 ? event.deltaX : event.deltaY;
  const scrollMultiplier = event.shiftKey ? 2.5 : 1.2;
  const currentScroll = wavesurfer.getScroll();
  const maxScroll = Math.max(0, totalTimelineWidth.value - viewportClientWidth.value);
  const targetScroll = Math.max(0, Math.min(maxScroll, currentScroll + (delta * scrollMultiplier)));

  wavesurfer.setScroll(targetScroll);
  syncTrackScroll();
}

// Interactive Scrollbar Track Click & Drag
function handleScrollbarTrackClick(e: MouseEvent) {
  if (!scrollbarTrack.value || !wavesurfer) return;
  const rect = scrollbarTrack.value.getBoundingClientRect();
  const clickX = e.clientX - rect.left;
  const trackW = rect.width;
  const thumbW = scrollbarThumbWidth.value;
  const maxThumbLeft = trackW - thumbW;
  if (maxThumbLeft <= 0) return;

  const targetThumbLeft = Math.max(0, Math.min(maxThumbLeft, clickX - thumbW / 2));
  const progress = targetThumbLeft / maxThumbLeft;
  const maxScroll = Math.max(0, totalTimelineWidth.value - viewportClientWidth.value);
  wavesurfer.setScroll(progress * maxScroll);
  syncTrackScroll();
}

function startDragScrollbarThumb(e: MouseEvent) {
  if (!scrollbarTrack.value || !wavesurfer) return;
  const startX = e.clientX;
  const startScroll = wavesurfer.getScroll();
  const trackW = scrollbarTrack.value.clientWidth;
  const thumbW = scrollbarThumbWidth.value;
  const maxThumbLeft = trackW - thumbW;
  const maxScroll = Math.max(0, totalTimelineWidth.value - viewportClientWidth.value);
  if (maxThumbLeft <= 0) return;

  function onMouseMove(moveEvt: MouseEvent) {
    const deltaX = moveEvt.clientX - startX;
    const scrollDelta = (deltaX / maxThumbLeft) * maxScroll;
    const targetScroll = Math.max(0, Math.min(maxScroll, startScroll + scrollDelta));
    wavesurfer?.setScroll(targetScroll);
    syncTrackScroll();
  }

  function onMouseUp() {
    window.removeEventListener('mousemove', onMouseMove);
    window.removeEventListener('mouseup', onMouseUp);
  }

  window.addEventListener('mousemove', onMouseMove);
  window.addEventListener('mouseup', onMouseUp);
}

// Middle Click or Alt+Drag Timeline Pan Handler (DAW & QuranCaption Standard)
function handleTimelineMouseDown(e: MouseEvent) {
  if (e.button === 1 || (e.button === 0 && e.altKey)) {
    e.preventDefault();
    isPanning.value = true;
    const startX = e.clientX;
    const initialScroll = wavesurfer ? wavesurfer.getScroll() : 0;
    const maxScroll = Math.max(0, totalTimelineWidth.value - viewportClientWidth.value);

    function onPanMove(moveEvt: MouseEvent) {
      const deltaX = moveEvt.clientX - startX;
      const targetScroll = Math.max(0, Math.min(maxScroll, initialScroll - deltaX));
      wavesurfer?.setScroll(targetScroll);
      syncTrackScroll();
    }

    function onPanUp() {
      isPanning.value = false;
      window.removeEventListener('mousemove', onPanMove);
      window.removeEventListener('mouseup', onPanUp);
    }

    window.addEventListener('mousemove', onPanMove);
    window.addEventListener('mouseup', onPanUp);
  }
}

// In-Memory Waveform Peaks Cache (Mirrors QuranCaption WaveformService.svelte.ts)
const peaksCache = new Map<string, { peaks: number[]; duration: number; url?: string }>();

// Precomputed Peak Loading (Fast, 0MB WebAudio Memory Allocation - QuranCaption Model)
async function loadAudioUrl(url: string, filePath?: string | null) {
  if (!wavesurfer || currentlyLoadedAudioUrl === url) return;
  currentlyLoadedAudioUrl = url;
  hasAudioLoaded.value = false;

  const effectivePath = filePath || projectStore.activeAudioFilePath.value || url;
  
  // 1. Instant Cache hit (0ms latency)
  if (peaksCache.has(effectivePath)) {
    const cached = peaksCache.get(effectivePath)!;
    wavesurfer.load(cached.url || url, [cached.peaks], cached.duration);
    return;
  }

  let peaksData: number[] | null = null;
  let dur: number | null = null;
  let streamUrl = url;

  try {
    const targetQuery = effectivePath 
      ? `path=${encodeURIComponent(effectivePath)}` 
      : `path=${encodeURIComponent(url)}`;

    // 2. First attempt to load metadata & peaks from /api/engine/audio/load
    const res = await fetch(`/api/engine/audio/load?${targetQuery}`);
    if (res.ok) {
      const d = await res.json();
      if (d.success && d.peaks && d.peaks.length > 0) {
        peaksData = d.peaks;
        dur = d.duration;
        if (d.url) streamUrl = d.url;
        peaksCache.set(effectivePath, { peaks: d.peaks, duration: d.duration, url: d.url });
      }
    } else {
      // 3. Fallback to /api/engine/audio/peaks
      const pRes = await fetch(`/api/engine/audio/peaks?${targetQuery}`);
      if (pRes.ok) {
        const pd = await pRes.json();
        if (pd.peaks && pd.peaks.length > 0) {
          peaksData = pd.peaks;
          dur = pd.duration;
          peaksCache.set(effectivePath, { peaks: pd.peaks, duration: pd.duration });
        }
      }
    }
  } catch (err) {
    console.warn('Precomputed peaks not available, falling back to standard decode:', err);
  }

  if (peaksData && dur) {
    wavesurfer.load(streamUrl, [peaksData], dur);
  } else {
    // Resilient fallback: render via browser WebAudio decoder without blocking alert modal
    console.warn('Precomputed waveform peaks unavailable, rendering via WebAudio decode:', streamUrl);
    wavesurfer.load(streamUrl);
  }
}

// Shared-Vertex Divider Drag Handler (Contiguous Words Only, Safe Clamping, MouseUp History Commit)
function startDragDivider(divider: SharedDivider, e: MouseEvent) {
  activeDraggingDividerId.value = divider.id;
  const startX = e.clientX;
  const initialTime = divider.time;
  const leftStart = divider.leftWord.start;
  const rightEnd = divider.rightWord.end;

  // Safe clamp limits: leave at least 20ms for each word
  // Invariant: minTime <= initialTime <= maxTime (never jump!)
  let minTime = Number((leftStart + 0.02).toFixed(3));
  let maxTime = Number((rightEnd - 0.02).toFixed(3));

  if (minTime > initialTime) minTime = initialTime;
  if (maxTime < initialTime) maxTime = initialTime;
  if (maxTime < minTime) maxTime = minTime;

  function onMouseMove(moveEvent: MouseEvent) {
    const deltaPx = moveEvent.clientX - startX;
    const deltaTime = deltaPx / zoomLevel.value;
    const rawTime = initialTime + deltaTime;
    const clampedTime = Number(Math.max(minTime, Math.min(maxTime, rawTime)).toFixed(3));

    divider.leftWord.end = clampedTime;
    divider.rightWord.start = clampedTime;
    divider.leftWord.is_edited = true;
    divider.rightWord.is_edited = true;
    divider.time = clampedTime;
  }

  function onMouseUp() {
    activeDraggingDividerId.value = null;
    window.removeEventListener('mousemove', onMouseMove);
    window.removeEventListener('mouseup', onMouseUp);

    projectStore.updateAyahBounds(divider.leftWord.location);

    const finalTime = divider.leftWord.end;
    if (Math.abs(finalTime - initialTime) > 0.001) {
      projectStore.recordDividerHistory(
        divider.leftWord,
        divider.rightWord,
        initialTime,
        initialTime,
        finalTime
      );
    }
  }

  window.addEventListener('mousemove', onMouseMove);
  window.addEventListener('mouseup', onMouseUp);
}

const activeDraggingBoundary = ref<{ id: string; edge: 'start' | 'end'; time: number } | null>(null);

function isWordBoundaryStart(_seg: TimelineSegmentItem, w: AlignedWord, wIdx: number): boolean {
  if (wIdx === 0) return true;
  const prev = _seg.words[wIdx - 1];
  // Word has independent start handle if facing silence or separated from previous word
  return (w.start - prev.end) > 0.01;
}

function isWordBoundaryEnd(seg: TimelineSegmentItem, w: AlignedWord, wIdx: number): boolean {
  if (wIdx === seg.words.length - 1) return true;
  const next = seg.words[wIdx + 1];
  // Word has independent end handle if facing silence or separated from next word
  return (next.start - w.end) > 0.01;
}

function startDragWordBoundary(
  seg: TimelineSegmentItem,
  w: AlignedWord,
  wIdx: number,
  edge: 'start' | 'end',
  e: MouseEvent
) {
  const boundaryId = `${seg.id}_${wIdx}`;
  const startX = e.clientX;
  const initialTime = edge === 'start' ? w.start : w.end;
  activeDraggingBoundary.value = { id: boundaryId, edge, time: initialTime };

  let minTime: number;
  let maxTime: number;

  if (edge === 'start') {
    // Word start can NEVER exceed its end minus 20ms
    maxTime = Number((w.end - 0.02).toFixed(3));

    if (wIdx === 0) {
      // First word of segment: can be stretched to left into silence up to previous segment's end (or 0)
      let prevLimit = 0;
      for (const s of projectStore.activeSegments.value) {
        if (s.id !== seg.id && s.end < initialTime) {
          if (s.end > prevLimit) prevLimit = s.end;
        }
      }
      minTime = Number(prevLimit.toFixed(3));
    } else {
      // Preceding word in the same segment: cannot overlap previous word's end
      minTime = Number(seg.words[wIdx - 1].end.toFixed(3));
    }

    // Safety invariant: minTime must never push beyond initialTime
    if (minTime > initialTime) minTime = initialTime;
    if (maxTime < minTime) maxTime = minTime;
  } else {
    // Word end can NEVER precede its start plus 20ms
    minTime = Number((w.start + 0.02).toFixed(3));

    if (wIdx === seg.words.length - 1) {
      // Last word of segment: can be stretched to right into silence up to next segment's start (or duration)
      let nextLimit = duration.value > 0 ? duration.value : 999999;
      for (const s of projectStore.activeSegments.value) {
        if (s.id !== seg.id && s.start > initialTime) {
          if (s.start < nextLimit) nextLimit = s.start;
        }
      }
      maxTime = Number(nextLimit.toFixed(3));
    } else {
      // Next word in the same segment: cannot overlap next word's start
      maxTime = Number(seg.words[wIdx + 1].start.toFixed(3));
    }

    // Safety invariant: maxTime must never push before initialTime
    if (maxTime < initialTime) maxTime = initialTime;
    if (minTime > maxTime) minTime = maxTime;
  }

  function onMouseMove(moveEvent: MouseEvent) {
    const deltaPx = moveEvent.clientX - startX;
    const deltaTime = deltaPx / zoomLevel.value;
    const rawTime = initialTime + deltaTime;
    const clampedTime = Number(Math.max(minTime, Math.min(maxTime, rawTime)).toFixed(3));

    if (edge === 'start') {
      w.start = clampedTime;
      if (wIdx === 0) {
        seg.start = clampedTime;
      }
    } else {
      w.end = clampedTime;
      if (wIdx === seg.words.length - 1) {
        seg.end = clampedTime;
      }
    }
    w.is_edited = true;
    if (activeDraggingBoundary.value) {
      activeDraggingBoundary.value.time = clampedTime;
    }
  }

  function onMouseUp() {
    activeDraggingBoundary.value = null;
    window.removeEventListener('mousemove', onMouseMove);
    window.removeEventListener('mouseup', onMouseUp);

    projectStore.updateAyahBounds(w.location);

    const finalTime = edge === 'start' ? w.start : w.end;
    if (Math.abs(finalTime - initialTime) > 0.001) {
      projectStore.recordWordBoundaryHistory(w, edge, initialTime, finalTime);
    }
  }

  window.addEventListener('mousemove', onMouseMove);
  window.addEventListener('mouseup', onMouseUp);
}

function startDragSegmentBoundary(seg: TimelineSegmentItem, edge: 'start' | 'end', e: MouseEvent) {
  if (!seg.words || seg.words.length === 0) return;
  const targetWord = edge === 'start' ? seg.words[0] : seg.words[seg.words.length - 1];
  const initialTime = edge === 'start' ? targetWord.start : targetWord.end;
  activeDraggingBoundary.value = { id: seg.id, edge, time: initialTime };

  let minTime: number;
  let maxTime: number;

  if (edge === 'start') {
    maxTime = Number((targetWord.end - 0.02).toFixed(3));
    let prevLimit = 0;
    for (const s of projectStore.activeSegments.value) {
      if (s.id !== seg.id && s.end < initialTime) {
        if (s.end > prevLimit) prevLimit = s.end;
      }
    }
    minTime = Number(prevLimit.toFixed(3));
    if (minTime > initialTime) minTime = initialTime;
    if (maxTime < minTime) maxTime = minTime;
  } else {
    minTime = Number((targetWord.start + 0.02).toFixed(3));
    let nextLimit = duration.value > 0 ? duration.value : 999999;
    for (const s of projectStore.activeSegments.value) {
      if (s.id !== seg.id && s.start > initialTime) {
        if (s.start < nextLimit) nextLimit = s.start;
      }
    }
    maxTime = Number(nextLimit.toFixed(3));
    if (maxTime < initialTime) maxTime = initialTime;
    if (minTime > maxTime) minTime = maxTime;
  }

  const startX = e.clientX;

  function onMouseMove(moveEvent: MouseEvent) {
    const deltaPx = moveEvent.clientX - startX;
    const deltaTime = deltaPx / zoomLevel.value;
    const rawTime = initialTime + deltaTime;
    const clampedTime = Number(Math.max(minTime, Math.min(maxTime, rawTime)).toFixed(3));

    if (edge === 'start') {
      targetWord.start = clampedTime;
      seg.start = clampedTime;
    } else {
      targetWord.end = clampedTime;
      seg.end = clampedTime;
    }
    targetWord.is_edited = true;
    if (activeDraggingBoundary.value) {
      activeDraggingBoundary.value.time = clampedTime;
    }
  }

  function onMouseUp() {
    activeDraggingBoundary.value = null;
    window.removeEventListener('mousemove', onMouseMove);
    window.removeEventListener('mouseup', onMouseUp);

    projectStore.updateAyahBounds(targetWord.location);

    const finalTime = edge === 'start' ? targetWord.start : targetWord.end;
    if (Math.abs(finalTime - initialTime) > 0.001) {
      projectStore.recordWordBoundaryHistory(targetWord, edge, initialTime, finalTime);
    }
  }

  window.addEventListener('mousemove', onMouseMove);
  window.addEventListener('mouseup', onMouseUp);
}

function handleSegmentClick(seg: TimelineSegmentItem) {
  projectStore.selectAyah(seg.ayahNumber);
  if (wavesurfer) {
    wavesurfer.setTime(seg.start);
    updatePlayheadDirect(seg.start);
  }
}

const selectedWordStartTime = ref<number | null>(null);

function handleWordClick(w: AlignedWord) {
  selectedWordStartTime.value = w.start;
  projectStore.selectWord(w.location, false);
  if (wavesurfer) {
    wavesurfer.setTime(w.start);
    updatePlayheadDirect(w.start);
  }
}

function isTimelineWordActive(w: AlignedWord): boolean {
  const t = currentTime.value;
  return t >= w.start && t <= w.end;
}

function isTimelineWordSelected(w: AlignedWord): boolean {
  // When playing, the moving playhead/karaoke is the sole active highlight.
  // The clicked blue box is NOT stuck while the playhead moves!
  if (isPlaying.value) return false;
  if (projectStore.activeWordLocation.value !== w.location) return false;
  if (selectedWordStartTime.value === null) return true;
  return Math.abs(selectedWordStartTime.value - w.start) < 0.001;
}

function isSegmentPlaying(seg: TimelineSegmentItem): boolean {
  const t = currentTime.value;
  return t >= seg.start && t <= seg.end;
}

// QuranCaption display pattern: strip silent-alif round zero markers (U+06DF / U+06E0) on miniature timeline chips
const WBW_DISPLAY_STRIP_MARKERS = /[۟۠]/g;
function formatTimelineWord(text: string): string {
  return (text || '').replace(WBW_DISPLAY_STRIP_MARKERS, '');
}

function handleContextMenu(e: MouseEvent, w: AlignedWord) {
  emit('word-context-menu', e, w);
}

function handleLoopCheck(t: number) {
  if (!wavesurfer || !isPlaying.value) return;

  if (projectStore.loopMode.value === 'word' && selectedWord.value) {
    const w = selectedWord.value;
    if (t >= w.end) {
      wavesurfer.setTime(w.start);
    }
  } else if (projectStore.loopMode.value === 'ayah' && projectStore.activeAyah.value) {
    const a = projectStore.activeAyah.value;
    if (t >= a.end) {
      wavesurfer.setTime(a.start);
    }
  }
}

function cycleLoopMode() {
  const modes: ('none' | 'ayah' | 'word')[] = ['none', 'ayah', 'word'];
  const curIdx = modes.indexOf(projectStore.loopMode.value);
  projectStore.loopMode.value = modes[(curIdx + 1) % modes.length];
}

watch(() => projectStore.activeAudioUrl.value, (newUrl) => {
  if (newUrl) {
    loadAudioUrl(newUrl, projectStore.activeAudioFilePath.value);
  }
});

watch(() => projectStore.currentTime.value, (newT) => {
  if (isInternalTimeUpdate) return;
  if (wavesurfer && Math.abs(wavesurfer.getCurrentTime() - newT) > 0.15) {
    wavesurfer.setTime(newT);
  }
});

// Auto-scroll timeline when a word is selected externally (e.g. from Auditor drawer or Tab key)
watch(() => projectStore.activeWordLocation.value, (loc) => {
  if (!loc || !wavesurfer) return;
  const word = projectStore.findWordByLocation(loc);
  if (!word) return;

  const wordPx = word.start * zoomLevel.value;
  const currentScroll = wavesurfer.getScroll();
  const vpWidth = viewportClientWidth.value;

  if (wordPx < currentScroll || wordPx > (currentScroll + vpWidth - 120)) {
    const targetScroll = Math.max(0, wordPx - vpWidth / 3);
    wavesurfer.setScroll(targetScroll);
    syncTrackScroll();
  }
});

function togglePlay() {
  if (!wavesurfer || !hasAudioLoaded.value) return;
  wavesurfer.playPause();
}

function skipBackward(amount: number) {
  if (!wavesurfer || !hasAudioLoaded.value) return;
  wavesurfer.setTime(Math.max(0, wavesurfer.getCurrentTime() - amount));
}

function skipForward(amount: number) {
  if (!wavesurfer || !hasAudioLoaded.value) return;
  wavesurfer.setTime(Math.min(duration.value, wavesurfer.getCurrentTime() + amount));
}

function updateZoom() {
  if (!wavesurfer) return;
  wavesurfer.zoom(zoomLevel.value);
  projectStore.zoomPxPerSec.value = zoomLevel.value;
  syncTrackScroll();
}

function adjustZoom(delta: number, clientX?: number) {
  if (!wavesurfer) return;
  const oldZoom = zoomLevel.value;
  const newZoom = Math.max(40, Math.min(320, oldZoom + delta));
  if (newZoom === oldZoom) return;

  const currentScroll = wavesurfer.getScroll();
  const vpWidth = viewportClientWidth.value;

  // Preserve focal anchor point under mouse cursor or center of viewport
  let focalOffset = vpWidth / 2;
  if (clientX !== undefined && waveformMount.value) {
    const rect = waveformMount.value.getBoundingClientRect();
    const relX = clientX - rect.left;
    if (relX >= 0 && relX <= vpWidth) {
      focalOffset = relX;
    }
  }

  const focalTime = (currentScroll + focalOffset) / oldZoom;

  zoomLevel.value = newZoom;
  wavesurfer.zoom(newZoom);
  projectStore.zoomPxPerSec.value = newZoom;

  // Restore scroll so focal time remains anchored
  const targetScroll = Math.max(0, focalTime * newZoom - focalOffset);
  wavesurfer.setScroll(targetScroll);
  syncTrackScroll();
}

function changePlaybackRate() {
  if (!wavesurfer) return;
  wavesurfer.setPlaybackRate(playbackRate.value);
  projectStore.playbackRate.value = playbackRate.value;
}

function triggerFileInput() {
  fileInput.value?.click();
}

function handleFileUpload(event: Event) {
  const target = event.target as HTMLInputElement;
  const file = target.files?.[0];
  if (!file) return;
  loadLocalFile(file);
}

function handleFileDrop(e: DragEvent) {
  isDraggingFile.value = false;
  const file = e.dataTransfer?.files?.[0];
  if (file && (file.type.startsWith('audio/') || file.type.startsWith('video/'))) {
    loadLocalFile(file);
  }
}

const isUploadingAudio = ref(false);

async function loadLocalFile(file: File) {
  isUploadingAudio.value = true;
  hasAudioLoaded.value = false;

  // Immediate local client-side Blob URL (QuranCaption resilient audio loading)
  const localBlobUrl = URL.createObjectURL(file);

  try {
    const formData = new FormData();
    formData.append('file', file);

    const res = await fetch('/api/engine/audio/upload', {
      method: 'POST',
      body: formData,
    });

    if (res.ok) {
      const data = await res.json();
      if (data.success) {
        projectStore.setLoadedAudio(data.filePath, data.url, data.duration);
        currentlyLoadedAudioUrl = data.url;

        if (wavesurfer) {
          if (data.peaks && data.peaks.length > 0) {
            wavesurfer.load(data.url, [data.peaks], data.duration);
          } else {
            wavesurfer.load(data.url);
          }
        }
        return;
      }
    }

    // Backend returned non-200 or unexpected structure: fallback seamlessly
    console.warn('Backend peak extraction endpoint returned non-OK. Loading local audio directly.');
    projectStore.setLoadedAudio(file.name, localBlobUrl);
    currentlyLoadedAudioUrl = localBlobUrl;
    if (wavesurfer) {
      wavesurfer.load(localBlobUrl);
    }
  } catch (err: any) {
    console.warn('Backend audio upload unavailable, falling back to instant client decode:', err);
    projectStore.setLoadedAudio(file.name, localBlobUrl);
    currentlyLoadedAudioUrl = localBlobUrl;
    if (wavesurfer) {
      wavesurfer.load(localBlobUrl);
    }
  } finally {
    isUploadingAudio.value = false;
  }
}

function isTypingTarget(target: EventTarget | null): boolean {
  if (!target || !(target instanceof HTMLElement)) return false;
  return (
    target.tagName === 'INPUT' ||
    target.tagName === 'TEXTAREA' ||
    target.tagName === 'SELECT' ||
    target.isContentEditable ||
    !!target.closest('input, textarea, select, [contenteditable="true"]')
  );
}

function handleKeydown(e: KeyboardEvent) {
  if (isTypingTarget(e.target)) return;

  if (e.code === 'Space') {
    e.preventDefault();
    togglePlay();
  }

  // QuranCaption Hotkeys: Snap Selected Word Boundaries to Current Playhead
  // 'W' snaps start boundary to playhead, 'E' snaps end boundary to playhead
  if ((e.key === 'w' || e.key === 'W') && !e.ctrlKey && !e.metaKey && !e.altKey && projectStore.activeWordLocation.value) {
    e.preventDefault();
    const curTime = wavesurfer ? wavesurfer.getCurrentTime() : currentTime.value;
    projectStore.updateWordStart(projectStore.activeWordLocation.value, curTime);
    return;
  }
  if ((e.key === 'e' || e.key === 'E') && !e.ctrlKey && !e.metaKey && !e.altKey && projectStore.activeWordLocation.value) {
    e.preventDefault();
    const curTime = wavesurfer ? wavesurfer.getCurrentTime() : currentTime.value;
    projectStore.updateWordEnd(projectStore.activeWordLocation.value, curTime);
    return;
  }

  // Micro-scrubbing ArrowLeft / ArrowRight (QuranCaption standard)
  if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
    e.preventDefault();
    const step = e.shiftKey ? 0.2 : 0.05; // 50ms default or 200ms with Shift
    const direction = e.key === 'ArrowLeft' ? -1 : 1;
    if (wavesurfer) {
      const cur = wavesurfer.getCurrentTime() || currentTime.value;
      const newT = Math.max(0, Math.min(duration.value, cur + direction * step));
      wavesurfer.setTime(newT);
      currentTime.value = newT;
      projectStore.updateCurrentTime(newT);
      updatePlayheadDirect(newT);
    }
  }

  // PageUp / PageDown: Jump to previous / next segment (QuranCaption standard)
  if (e.key === 'PageUp' || e.key === 'PageDown') {
    e.preventDefault();
    const curT = wavesurfer?.getCurrentTime() || currentTime.value;
    const segments = projectStore.activeSegments.value;
    if (segments.length > 0) {
      if (e.key === 'PageDown') {
        const nextSeg = segments.find(s => s.start > curT + 0.1);
        if (nextSeg && wavesurfer) {
          wavesurfer.setTime(nextSeg.start);
          currentTime.value = nextSeg.start;
          projectStore.updateCurrentTime(nextSeg.start);
          updatePlayheadDirect(nextSeg.start);
        }
      } else {
        const prevSegs = segments.filter(s => s.start < curT - 0.1);
        const prevSeg = prevSegs.length > 0 ? prevSegs[prevSegs.length - 1] : null;
        if (prevSeg && wavesurfer) {
          wavesurfer.setTime(prevSeg.start);
          currentTime.value = prevSeg.start;
          projectStore.updateCurrentTime(prevSeg.start);
          updatePlayheadDirect(prevSeg.start);
        }
      }
    }
  }

  // Home or 'i' to jump to beginning (QuranCaption standard: GO_TO_START)
  if (e.key === 'Home' || ((e.key === 'i' || e.key === 'I') && !e.ctrlKey && !e.metaKey)) {
    e.preventDefault();
    if (wavesurfer) {
      wavesurfer.setTime(0);
      currentTime.value = 0;
      projectStore.updateCurrentTime(0);
      updatePlayheadDirect(0);
    }
  }

  if (e.key === '[' && projectStore.activeWordLocation.value) {
    e.preventDefault();
    projectStore.nudgeWord(projectStore.activeWordLocation.value, e.shiftKey ? -0.05 : -0.01, 'end');
  }
  if (e.key === ']' && projectStore.activeWordLocation.value) {
    e.preventDefault();
    projectStore.nudgeWord(projectStore.activeWordLocation.value, e.shiftKey ? 0.05 : 0.01, 'end');
  }
  if (e.key === 'Tab') {
    e.preventDefault();
    projectStore.jumpToNextIssue();
  }

  if (e.ctrlKey && e.key.toLowerCase() === 'z') {
    e.preventDefault();
    if (e.shiftKey) {
      projectStore.redo();
    } else {
      projectStore.undo();
    }
  }
  if (e.ctrlKey && e.key.toLowerCase() === 'y') {
    e.preventDefault();
    projectStore.redo();
  }
}
</script>

<style scoped>
.waveform-editor {
  display: flex;
  flex-direction: column;
  background: var(--bg-surface);
  border-bottom: 1px solid var(--border-subtle);
  user-select: none;
}

.editor-toolbar {
  height: 40px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 14px;
  background: rgba(15, 23, 42, 0.4);
  border-bottom: 1px solid var(--border-subtle);
}

.transport-controls, .timeline-tools {
  display: flex;
  align-items: center;
  gap: 6px;
}

.play-btn {
  background: var(--accent-primary) !important;
  color: #ffffff !important;
  border-radius: 6px;
  width: 28px;
  height: 28px;
}

.active-verse-badge {
  padding: 2px 8px;
  background: rgba(94, 106, 210, 0.15);
  border: 1px solid rgba(94, 106, 210, 0.3);
  border-radius: 4px;
  font-size: 11px;
  color: var(--accent-primary);
  font-weight: 600;
}

.time-readout {
  display: flex;
  align-items: center;
  gap: 4px;
  font-family: var(--font-mono);
  font-size: 12px;
  padding: 0 6px;
  color: var(--text-secondary);
}

.current-time {
  color: var(--text-primary);
  font-weight: 600;
}

.speed-select {
  background: transparent;
  border: 1px solid var(--border-subtle);
  color: var(--text-secondary);
  border-radius: 4px;
  padding: 2px 6px;
  font-size: 11px;
  outline: none;
  cursor: pointer;
}

.zoom-slider {
  width: 80px;
  height: 4px;
  accent-color: var(--accent-primary);
  cursor: pointer;
}

.minimap-container {
  height: 24px;
  background: rgba(10, 15, 26, 0.9);
  border-bottom: 1px solid var(--border-subtle);
  overflow: hidden;
}

/* Master Timeline Container */
.waveform-container {
  position: relative;
  display: flex;
  flex-direction: column;
  background: #0b0f19;
  min-height: 220px;
  cursor: default;
}

.waveform-container.is-panning {
  cursor: grab;
}

#timeline-ruler {
  height: 24px;
  background: rgba(15, 23, 42, 0.75);
  border-bottom: 1px solid rgba(255, 255, 255, 0.05);
}

#waveform-mount {
  height: 105px;
  position: relative;
}

/* Base Track Viewport (Synced Horizontal Scrolling) */
.track-viewport {
  position: relative;
  overflow-x: auto;
  overflow-y: hidden;
  scrollbar-width: none;
}
.track-viewport::-webkit-scrollbar {
  display: none;
}

.track-canvas {
  height: 100%;
  position: relative;
  contain: layout style;
}

/* Track 1: Ayah / Verse Lane (QuranCaption Style) */
.ayah-track-viewport {
  height: 32px;
  background: rgba(13, 20, 36, 0.95);
  border-top: 1px solid rgba(255, 255, 255, 0.08);
}

.timeline-ayah-block {
  position: absolute;
  top: 3px;
  bottom: 3px;
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 0 8px;
  background: rgba(56, 189, 248, 0.08);
  border: 1px solid rgba(56, 189, 248, 0.22);
  border-radius: 4px;
  cursor: pointer;
  overflow: hidden;
  transition: all 0.12s ease;
  user-select: none;
}

.timeline-ayah-block:hover {
  background: rgba(56, 189, 248, 0.16);
  border-color: rgba(56, 189, 248, 0.45);
}

.timeline-ayah-block.ayah-active {
  background: rgba(56, 189, 248, 0.22);
  border-color: #38bdf8;
  box-shadow: 0 0 10px rgba(56, 189, 248, 0.3);
}

.timeline-ayah-block.ayah-selected {
  border-color: #a78bfa;
  background: rgba(167, 139, 250, 0.18);
}

.timeline-ayah-block.ayah-has-issues {
  border-right: 3px solid #f59e0b;
}

.timeline-ayah-block.ayah-coverage-gap {
  background: rgba(239, 68, 68, 0.12) !important;
  border-color: rgba(239, 68, 68, 0.5) !important;
  border-right: 3px solid #ef4444 !important;
}

.coverage-gap-badge {
  font-size: 9px;
  font-weight: 700;
  padding: 1px 5px;
  border-radius: 3px;
  background: rgba(239, 68, 68, 0.25);
  border: 1px solid rgba(239, 68, 68, 0.6);
  color: #fca5a5;
  white-space: nowrap;
}

.empty-audio-dropzone {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 32px 16px;
  border: 1.5px dashed rgba(255, 255, 255, 0.12);
  border-radius: 8px;
  margin: 20px;
  cursor: pointer;
  background: rgba(15, 23, 42, 0.4);
  transition: all 0.2s ease;
}

.empty-audio-dropzone:hover {
  border-color: var(--accent-primary);
  background: rgba(94, 106, 210, 0.08);
}

.empty-audio-dropzone .drop-icon {
  color: var(--accent-primary);
}

.empty-title {
  font-size: 13px;
  font-weight: 500;
  color: var(--text-primary);
}

.empty-formats {
  font-size: 11px;
  color: var(--text-muted);
}

.ayah-label-badge {
  font-size: 11px;
  font-weight: 700;
  color: #38bdf8;
  white-space: nowrap;
}

.ayah-duration-badge {
  font-size: 9px;
  font-family: var(--font-mono);
  color: var(--text-muted);
  white-space: nowrap;
}

.ayah-snippet-text {
  font-family: 'Amiri Quran', 'Scheherazade New', serif;
  font-size: 12px;
  color: var(--text-secondary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  direction: rtl;
  opacity: 0.75;
}

/* Track 2: Word Alignment Track */
.word-track-viewport {
  height: 52px;
  background: rgba(15, 23, 42, 0.88);
  border-top: 1px solid rgba(255, 255, 255, 0.06);
}

.timeline-word-block {
  position: absolute;
  top: 4px;
  bottom: 4px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  background: rgba(94, 106, 210, 0.12);
  border: 1px solid rgba(94, 106, 210, 0.28);
  border-radius: 4px;
  padding: 0 4px;
  cursor: pointer;
  overflow: hidden;
  transition: background 0.08s ease, border-color 0.08s ease;
  user-select: none;
}

.timeline-word-block:hover {
  background: rgba(94, 106, 210, 0.22);
  border-color: rgba(94, 106, 210, 0.5);
}

.word-uthmani-text {
  font-family: 'Amiri Quran', 'Scheherazade New', serif;
  font-size: 15px;
  line-height: 1.2;
  color: var(--text-primary);
  white-space: nowrap;
  pointer-events: none;
}

.word-meta-row {
  display: flex;
  align-items: center;
  gap: 4px;
  line-height: 1;
  pointer-events: none;
}

.word-duration-pill {
  font-size: 9px;
  font-family: var(--font-mono);
  color: var(--text-muted);
}

.word-score-pill {
  font-size: 8px;
  font-family: var(--font-mono);
  padding: 1px 3px;
  border-radius: 2px;
  font-weight: 600;
}
.word-score-pill.warning {
  background: rgba(245, 158, 11, 0.25);
  color: #f59e0b;
}
.word-score-pill.critical {
  background: rgba(239, 68, 68, 0.25);
  color: #ef4444;
}

/* Sacred Radiant Karaoke Illumination (Harmonized with Phoneme Inspector: Emerald Green) */
.word-karaoke-active {
  background: rgba(16, 185, 129, 0.22) !important;
  border-color: #10b981 !important;
  box-shadow: none !important;
}

.word-karaoke-active .word-uthmani-text {
  color: #ffffff !important;
  font-weight: 500;
}

.word-selected {
  border-color: #10b981 !important;
  background: rgba(16, 185, 129, 0.18) !important;
  box-shadow: none !important;
}

.word-warning {
  border-color: rgba(245, 158, 11, 0.4);
}

.word-critical {
  border-color: rgba(239, 68, 68, 0.5);
  background: rgba(239, 68, 68, 0.12);
}

.word-edited {
  border-bottom: 2px solid #10b981;
}

/* Vertical Playhead Cursor across tracks */
.track-playhead-line {
  position: absolute;
  top: 0;
  bottom: 0;
  left: 0;
  width: 1.5px;
  background: #ffffff;
  box-shadow: 0 0 6px rgba(255, 255, 255, 0.8);
  pointer-events: none;
  z-index: 25;
  will-change: transform;
}

/* Shared-Vertex Magnetic Vertical Dividers */
.shared-divider-handle {
  position: absolute;
  top: 0;
  bottom: 0;
  width: 14px;
  margin-left: -7px;
  display: flex;
  justify-content: center;
  cursor: col-resize;
  z-index: 20;
}

.divider-line {
  width: 2px;
  height: 100%;
  background: rgba(255, 255, 255, 0.35);
  transition: background 0.1s ease, width 0.1s ease;
}

.divider-grabber {
  position: absolute;
  top: 2px;
  width: 10px;
  height: 8px;
  border-radius: 2px;
  background: rgba(255, 255, 255, 0.4);
  display: flex;
  align-items: center;
  justify-content: center;
  transition: background 0.1s ease;
}

.divider-grip-dot {
  width: 4px;
  height: 2px;
  background: #000;
  border-radius: 1px;
}

.shared-divider-handle:hover .divider-line,
.shared-divider-handle.is-dragging .divider-line {
  background: #38bdf8;
  width: 2.5px;
  box-shadow: 0 0 8px rgba(56, 189, 248, 0.6);
}

.shared-divider-handle:hover .divider-grabber,
.shared-divider-handle.is-dragging .divider-grabber {
  background: #38bdf8;
}

.divider-time-tooltip {
  position: absolute;
  bottom: 100%;
  left: 50%;
  transform: translateX(-50%);
  background: #0f172a;
  color: #38bdf8;
  font-family: var(--font-mono);
  font-size: 10px;
  font-weight: 700;
  padding: 2px 6px;
  border-radius: 4px;
  border: 1px solid rgba(56, 189, 248, 0.4);
  white-space: nowrap;
  pointer-events: none;
  z-index: 30;
  box-shadow: 0 4px 10px rgba(0, 0, 0, 0.5);
}

/* Custom Interactive Timeline Scrollbar (QuranCaption & DAW pattern) */
.timeline-scrollbar-track {
  height: 12px;
  background: rgba(10, 15, 26, 0.95);
  border-top: 1px solid rgba(255, 255, 255, 0.05);
  position: relative;
  cursor: pointer;
}

.timeline-scrollbar-thumb {
  position: absolute;
  top: 2px;
  bottom: 2px;
  background: rgba(255, 255, 255, 0.2);
  border-radius: 4px;
  cursor: grab;
  transition: background 0.1s ease;
}

.timeline-scrollbar-thumb:hover,
.timeline-scrollbar-thumb:active {
  background: rgba(56, 189, 248, 0.55);
}

.empty-audio-dropzone {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 170px;
  gap: 8px;
  color: var(--text-muted);
  cursor: pointer;
}

.empty-audio-dropzone:hover {
  color: var(--text-secondary);
}

.drag-drop-overlay {
  position: absolute;
  inset: 0;
  background: rgba(94, 106, 210, 0.35);
  backdrop-filter: blur(4px);
  z-index: 50;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  color: #fff;
  border: 2px dashed var(--accent-primary);
}
/* Word Outer Boundary Handles (First word / Last word / Facing silence) */
.word-boundary-handle {
  position: absolute;
  top: 0;
  bottom: 0;
  width: 14px;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: col-resize;
  z-index: 24;
  user-select: none;
}

.word-boundary-handle.handle-start {
  left: -7px;
}

.word-boundary-handle.handle-end {
  right: -7px;
}

.boundary-line {
  width: 2.5px;
  height: 100%;
  background: #10b981; /* Emerald green for outer boundaries */
  box-shadow: 0 0 6px rgba(16, 185, 129, 0.4);
  transition: all 0.1s ease;
}

.boundary-bracket {
  font-family: var(--font-mono);
  font-size: 11px;
  font-weight: 800;
  color: #10b981;
  line-height: 1;
  text-shadow: 0 0 6px rgba(16, 185, 129, 0.6);
  pointer-events: none;
}

.word-boundary-handle:hover .boundary-line,
.word-boundary-handle.is-dragging .boundary-line {
  background: #34d399;
  width: 3.5px;
  box-shadow: 0 0 10px rgba(52, 211, 153, 0.8);
}

.word-boundary-handle:hover .boundary-bracket,
.word-boundary-handle.is-dragging .boundary-bracket {
  color: #34d399;
  transform: scale(1.15);
}

/* Ayah Lane Edge Handles */
.ayah-edge-handle {
  position: absolute;
  top: 0;
  bottom: 0;
  width: 10px;
  cursor: col-resize;
  z-index: 20;
  display: flex;
  align-items: center;
  justify-content: center;
}

.ayah-edge-handle.edge-left {
  left: 0;
}

.ayah-edge-handle.edge-right {
  right: 0;
}

.edge-grip-bar {
  width: 2.5px;
  height: 60%;
  background: rgba(56, 189, 248, 0.5);
  border-radius: 1px;
  transition: all 0.1s ease;
}

.ayah-edge-handle:hover .edge-grip-bar,
.ayah-edge-handle.is-dragging .edge-grip-bar {
  background: #38bdf8;
  height: 90%;
  box-shadow: 0 0 8px rgba(56, 189, 248, 0.8);
}

/* Boundary Drag Time Tooltip */
.boundary-time-tooltip {
  position: absolute;
  bottom: 100%;
  left: 50%;
  transform: translateX(-50%);
  background: #064e3b;
  color: #a7f3d0;
  font-family: var(--font-mono);
  font-size: 10px;
  font-weight: 700;
  padding: 2px 6px;
  border-radius: 4px;
  border: 1px solid rgba(52, 211, 153, 0.4);
  white-space: nowrap;
  pointer-events: none;
  z-index: 35;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.6);
  margin-bottom: 2px;
}
</style>
