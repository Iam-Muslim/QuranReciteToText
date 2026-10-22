<template>
  <div class="waveform-editor glass-panel">
    <!-- Overview Minimap Track -->
    <div class="minimap-container" v-show="hasAudioLoaded || timelineSegments.length > 0">
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

      <input
        type="file"
        ref="fileInput"
        accept="audio/*,video/*"
        style="display: none"
        @change="handleFileUpload"
      />

      <!-- No Audio Empty State -->
      <div v-if="!hasAudioLoaded && timelineSegments.length === 0" class="empty-audio-dropzone" @click="triggerFileInput">
        <Loader2 v-if="isUploadingAudio" :size="28" class="drop-icon animate-spin" />
        <FileAudio v-else :size="26" class="drop-icon" />
        <span class="empty-title">
          {{ isUploadingAudio ? 'Uploading & generating FFmpeg waveform peaks...' : 'Select or drop recitation audio to begin' }}
        </span>
        <span class="empty-formats">Supports MP3, WAV, M4A, FLAC, OGG, AAC, OPUS</span>
      </div>

      <!-- WaveSurfer Waveform Mount (Peaks Layer Only, Zero Memory Allocation) -->
      <div id="waveform-mount" ref="waveformMount" v-show="hasAudioLoaded || timelineSegments.length > 0"></div>

      <!-- Track 1: Segments Lane (QuranCaption Multi-Segment Architecture) -->
      <div 
        class="track-viewport ayah-track-viewport" 
        ref="ayahTrackViewport"
        v-show="hasAudioLoaded || timelineSegments.length > 0"
        @scroll.passive="onTrackViewportScroll"
      >
        <span class="lane-header-pill">VERSES</span>
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
              'ayah-active': isSegmentPlaying(seg)
            }"
            :style="{
              left: `${seg.start * zoomLevel}px`,
              width: `${Math.max(30, (seg.end - seg.start) * zoomLevel)}px`
            }"
            @click="handleSegmentClick(seg)"
            :title="`${seg.label}: [${seg.start.toFixed(2)}s - ${seg.end.toFixed(2)}s]`"
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
              <span v-if="seg.isRepetition" class="badge-repetition" title="تكرار مقطع صوتي">إعادة</span>
              <span 
                v-if="seg.hasIssues" 
                class="badge-issue" 
                :class="seg.issueSeverity || 'warning'" 
                :title="seg.issueTooltip || 'ملاحظات تدقيق صوتية وتجويدية'"
              >
                ⚠️ {{ seg.issueBadgeLabel || 'ملاحظة' }}
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
        v-show="hasAudioLoaded || timelineSegments.length > 0"
        @scroll.passive="onTrackViewportScroll"
      >
        <span class="lane-header-pill">WORDS</span>
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
                'word-edited': w.is_edited
              }"
              :style="{
                left: `${w.start * zoomLevel}px`,
                width: `${Math.max(22, (w.end - w.start) * zoomLevel)}px`,
              }"
              @click="handleWordClick(w)"
              @contextmenu.prevent="handleContextMenu($event, w)"
              :title="`Word: ${w.word} | [${w.start.toFixed(2)}s - ${w.end.toFixed(2)}s]`"
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
              <span v-if="w.score < 0.85 && !w.is_verified" class="word-low-conf-dot" :title="`شك صوتي (${(w.score * 100).toFixed(0)}%)`"></span>

              <!-- Phoneme Timing Layer (Every phoneme has its exact acoustic time directly from the Aligner) -->
              <div v-if="w.phonemes && w.phonemes.length > 0 && zoomLevel >= 80" class="word-phonemes-layer">
                <div
                  v-for="(p, pIdx) in w.phonemes"
                  :key="`ph_${pIdx}_${p.start}`"
                  class="phoneme-tick-cell"
                  :style="{
                    left: `${Math.max(0, (p.start - w.start) * zoomLevel)}px`,
                    width: `${Math.max(4, (p.end - p.start) * zoomLevel)}px`,
                  }"
                  :title="`Phoneme: ${p.phoneme} | [${p.start.toFixed(3)}s - ${p.end.toFixed(3)}s]`"
                >
                  <span class="phoneme-tick-char">{{ p.phoneme }}</span>
                </div>
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
        v-show="(hasAudioLoaded || timelineSegments.length > 0) && totalTimelineWidth > viewportClientWidth"
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

    <!-- Unified Static Control Bar (Fixed below timeline, zero floating overlap, zero empty gap) -->
    <div class="timeline-control-bar" v-show="hasAudioLoaded || timelineSegments.length > 0">
      <!-- Left: Playback Transport & Timecode -->
      <div class="control-bar-left">
        <button
          class="bar-btn"
          @click="projectStore.jumpToPrevAyah()"
          title="Previous Ayah ([)"
          :disabled="!hasAudioLoaded && timelineSegments.length === 0"
        >
          <ChevronLeft :size="15" />
        </button>

        <button
          class="bar-play-btn"
          @click="togglePlay"
          :title="isPlaying ? 'Pause (Space)' : 'Play (Space)'"
          :disabled="!hasAudioLoaded && timelineSegments.length === 0"
        >
          <Pause v-if="isPlaying" :size="14" />
          <Play v-else :size="14" />
        </button>

        <button
          class="bar-btn"
          @click="projectStore.jumpToNextAyah()"
          title="Next Ayah (])"
          :disabled="!hasAudioLoaded && timelineSegments.length === 0"
        >
          <ChevronRight :size="15" />
        </button>

        <div class="bar-divider"></div>

        <button
          class="bar-btn loop-btn"
          :class="{ 'loop-active': projectStore.loopMode.value !== 'none' }"
          @click="cycleLoopMode"
          :title="`Loop: ${projectStore.loopMode.value.toUpperCase()}`"
        >
          <Repeat :size="13" />
          <span v-if="projectStore.loopMode.value !== 'none'" class="loop-indicator">
            {{ projectStore.loopMode.value === 'word' ? '1w' : '1v' }}
          </span>
        </button>

        <div class="time-readout">
          <span class="current-time">{{ formatAccurateTime(currentTime) }}</span>
          <span class="time-sep">/</span>
          <span class="total-time">{{ formatAccurateTime(duration) }}</span>
        </div>
      </div>

      <!-- Center: View Mode Switcher (Fixed in playback bar, zero floating overlap) -->
      <div class="control-bar-center" v-if="projectStore.activeSurah.value">
        <div class="view-toggle-pill">
          <button 
            class="toggle-btn" 
            :class="{ 'active': projectStore.viewMode.value === 'mushaf_page' }"
            @click="projectStore.viewMode.value = 'mushaf_page'"
            title="Medina Mushaf Sacred Page"
          >
            <BookOpen :size="12" />
            <span>Mushaf</span>
          </button>

          <button 
            class="toggle-btn" 
            :class="{ 'active': projectStore.viewMode.value === 'ayah_studio' }"
            @click="projectStore.viewMode.value = 'ayah_studio'"
            title="Verses Studio Cards"
          >
            <ListTree :size="12" />
            <span>Verses</span>
          </button>

          <button 
            class="toggle-btn" 
            :class="{ 'active': projectStore.viewMode.value === 'phoneme_inspector' }"
            @click="projectStore.viewMode.value = 'phoneme_inspector'"
            title="Phoneme Atoms Inspector"
          >
            <Layers :size="12" />
            <span>Phonemes</span>
          </button>
        </div>
      </div>

      <!-- Right: Font Stepper, Zoom & Speed -->
      <div class="control-bar-right">
        <!-- Font Size Stepper (Mushaf Page Mode) -->
        <div class="font-stepper-group" v-if="projectStore.viewMode.value === 'mushaf_page' && projectStore.activeSurah.value" title="Adjust Quran Font Size">
          <button 
            class="stepper-btn" 
            @click="projectStore.setMushafFontSize(projectStore.mushafFontSize.value - 0.15)"
            title="Decrease Font Size"
            :disabled="projectStore.mushafFontSize.value <= 1.3"
          >
            <span>A-</span>
          </button>
          <span class="stepper-val">{{ Math.round((projectStore.mushafFontSize.value / 1.95) * 100) }}%</span>
          <button 
            class="stepper-btn" 
            @click="projectStore.setMushafFontSize(projectStore.mushafFontSize.value + 0.15)"
            title="Increase Font Size"
            :disabled="projectStore.mushafFontSize.value >= 3.2"
          >
            <span>A+</span>
          </button>
        </div>

        <div class="bar-divider" v-if="projectStore.viewMode.value === 'mushaf_page' && projectStore.activeSurah.value"></div>

        <div class="zoom-cluster">
          <input
            type="range"
            min="40"
            max="320"
            step="10"
            v-model.number="zoomLevel"
            @input="updateZoom"
            class="zoom-slider"
            title="Timeline Zoom (Ctrl + Wheel)"
          />
        </div>

        <div class="bar-divider"></div>

        <select v-model="playbackRate" @change="changePlaybackRate" class="speed-select" title="Playback Speed">
          <option :value="0.75">0.75×</option>
          <option :value="1.0">1.0×</option>
          <option :value="1.25">1.25×</option>
          <option :value="1.5">1.5×</option>
        </select>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted, watch, computed, nextTick } from 'vue';
import { projectStore } from '../services/projectStore';
import { isTauriEnvironment, getAudioStreamUrl, resolveAudioSourceUrl } from '../services/api';
import type { AlignedWord, TimelineSegmentItem } from '../types/aligner';
import { 
  Play, 
  Pause, 
  ChevronLeft, 
  ChevronRight, 
  UploadCloud, 
  Repeat, 
  FileAudio, 
  Loader2,
  BookOpen,
  ListTree,
  Layers
} from 'lucide-vue-next';
import { usePlaybackTransport } from '../composables/usePlaybackTransport';
import { useTimelineDrag, type SharedDivider } from '../composables/useTimelineDrag';

const emit = defineEmits<{
  (e: 'word-context-menu', event: MouseEvent, word: AlignedWord): void;
}>();

const waveformMount = ref<HTMLElement | null>(null);
const minimapMount = ref<HTMLElement | null>(null);
const ayahTrackViewport = ref<HTMLElement | null>(null);
const wordTrackViewport = ref<HTMLElement | null>(null);
const scrollbarTrack = ref<HTMLElement | null>(null);
const fileInput = ref<HTMLInputElement | null>(null);
const segmentPlayheadLine = ref<HTMLElement | null>(null);
const wordPlayheadLine = ref<HTMLElement | null>(null);
const isDraggingFile = ref(false);
const isUploadingAudio = ref(false);
const selectedWordStartTime = ref<number | null>(null);
let resizeObserver: ResizeObserver | null = null;

const selectedWord = computed<AlignedWord | undefined>(() => {
  if (!projectStore.activeWordLocation.value) return undefined;
  return projectStore.findWordByLocation(projectStore.activeWordLocation.value);
});

function handleLoopCheck(t: number) {
  const ws = transport.getWaveSurfer();
  if (!ws || !transport.isPlaying.value) return;

  if (projectStore.loopMode.value === 'word' && selectedWord.value) {
    const w = selectedWord.value;
    if (t >= w.end) {
      ws.setTime(w.start);
    }
  } else if (projectStore.loopMode.value === 'ayah' && projectStore.activeAyah.value) {
    const a = projectStore.activeAyah.value;
    if (t >= a.end) {
      ws.setTime(a.start);
    }
  }
}

const transport = usePlaybackTransport(
  waveformMount,
  minimapMount,
  segmentPlayheadLine,
  wordPlayheadLine,
  ayahTrackViewport,
  wordTrackViewport,
  handleLoopCheck
);

const {
  isPlaying,
  currentTime,
  duration,
  zoomLevel,
  playbackRate,
  hasAudioLoaded,
  currentScrollLeft,
  viewportClientWidth,
  initWaveSurfer,
  loadAudioUrl,
  togglePlay,
  skipBackward,
  skipForward,
  adjustZoom,
  updateZoom,
  changePlaybackRate,
  auditionSelectedWord,
  syncTrackScroll,
  onTrackViewportScroll,
  updateViewportDimensions,
  updatePlayheadDirect,
  handleThemeChanged,
  destroy: destroyTransport,
} = transport;

// Timeline Segments
const timelineSegments = computed<TimelineSegmentItem[]>(() => {
  return projectStore.activeSegments.value;
});

// Total timeline canvas width in pixels
const totalTimelineWidth = computed(() => {
  let dur = duration.value;
  if (!dur || dur <= 0) {
    const segments = timelineSegments.value;
    if (segments.length > 0) {
      dur = segments[segments.length - 1].end + 1.0;
    }
  }
  return Math.max(800, Math.ceil(dur * zoomLevel.value));
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

// Compute contiguous magnetic dividers between adjacent words ONLY within the SAME segment when actually contiguous
const wordDividers = computed<SharedDivider[]>(() => {
  const segments = timelineSegments.value;
  const dividers: SharedDivider[] = [];
  for (const seg of segments) {
    const words = seg.words;
    for (let i = 0; i < words.length - 1; i++) {
      const left = words[i];
      const right = words[i + 1];

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

const {
  isPanning,
  activeDraggingDividerId,
  activeDraggingBoundary,
  startDragDivider,
  isWordBoundaryStart,
  isWordBoundaryEnd,
  startDragWordBoundary,
  startDragSegmentBoundary,
  handleTimelineMouseDown,
  handleScrollbarTrackClick,
  startDragScrollbarThumb,
  handleTimelineWheel: handleWheelRaw,
} = useTimelineDrag(
  transport.getWaveSurfer,
  zoomLevel,
  duration,
  totalTimelineWidth,
  viewportClientWidth,
  scrollbarThumbWidth,
  scrollbarTrack,
  syncTrackScroll,
  adjustZoom
);

function handleTimelineWheel(e: WheelEvent) {
  handleWheelRaw(e, hasAudioLoaded.value);
}

function formatAccurateTime(secs: number): string {
  if (isNaN(secs) || secs < 0) secs = 0;
  const m = Math.floor(secs / 60);
  const s = Math.floor(secs % 60);
  const ms = Math.floor((secs % 1) * 100);
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}.${String(ms).padStart(2, '0')}`;
}

function resolveSurahAudioUrl(s: { audio_file?: string | null; audio_url?: string | null }): string | null {
  return resolveAudioSourceUrl(s) || null;
}

function handleSegmentClick(seg: TimelineSegmentItem) {
  projectStore.selectAyah(seg.ayahNumber);
  const ws = transport.getWaveSurfer();
  if (ws) {
    ws.setTime(seg.start);
    updatePlayheadDirect(seg.start);
  }
}

function handleWordClick(w: AlignedWord) {
  selectedWordStartTime.value = w.start;
  projectStore.selectWord(w.location, false);
  const ws = transport.getWaveSurfer();
  if (ws) {
    ws.setTime(w.start);
    updatePlayheadDirect(w.start);
  }
}

function isTimelineWordActive(w: AlignedWord): boolean {
  return projectStore.currentKaraokeLocation.value === w.location;
}

function isTimelineWordSelected(w: AlignedWord): boolean {
  if (isPlaying.value) return false;
  if (projectStore.activeWordLocation.value !== w.location) return false;
  if (selectedWordStartTime.value === null) return true;
  return Math.abs(selectedWordStartTime.value - w.start) < 0.001;
}

function isSegmentPlaying(seg: TimelineSegmentItem): boolean {
  return projectStore.activeAyahNumber.value === seg.ayahNumber;
}

const WBW_DISPLAY_STRIP_MARKERS = /[۟۠]/g;
function formatTimelineWord(text: string): string {
  return (text || '').replace(WBW_DISPLAY_STRIP_MARKERS, '');
}

function handleContextMenu(e: MouseEvent, w: AlignedWord) {
  emit('word-context-menu', e, w);
}

function cycleLoopMode() {
  const modes: ('none' | 'ayah' | 'word')[] = ['none', 'ayah', 'word'];
  const curIdx = modes.indexOf(projectStore.loopMode.value);
  projectStore.loopMode.value = modes[(curIdx + 1) % modes.length];
}

function triggerFileInput() {
  fileInput.value?.click();
}

function handleFileUpload(event: Event) {
  const target = event.target as HTMLInputElement;
  const file = target.files?.[0];
  if (!file) return;
  loadLocalFile(file);
  target.value = '';
}

function handleFileDrop(e: DragEvent) {
  isDraggingFile.value = false;
  const file = e.dataTransfer?.files?.[0];
  if (file && (file.type.startsWith('audio/') || file.type.startsWith('video/'))) {
    loadLocalFile(file);
  }
}

async function loadLocalFile(file: File) {
  isUploadingAudio.value = true;
  hasAudioLoaded.value = false;

  try {
    const nativePath: string = (file as any).path || '';
    if (nativePath && isTauriEnvironment()) {
      const assetUrl = getAudioStreamUrl(nativePath);
      projectStore.setLoadedAudio(nativePath, assetUrl);
      const ws = transport.getWaveSurfer();
      if (ws) ws.load(assetUrl);
    } else {
      const localBlobUrl = URL.createObjectURL(file);
      projectStore.setLoadedAudio(file.name, localBlobUrl);
      const ws = transport.getWaveSurfer();
      if (ws) ws.load(localBlobUrl);
    }
  } catch (err: any) {
    console.warn('Audio load error, using blob fallback:', err);
    const localBlobUrl = URL.createObjectURL(file);
    projectStore.setLoadedAudio(file.name, localBlobUrl);
    const ws = transport.getWaveSurfer();
    if (ws) ws.load(localBlobUrl);
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

  const ws = transport.getWaveSurfer();

  if (e.code === 'Space') {
    e.preventDefault();
    if (e.shiftKey) {
      auditionSelectedWord(selectedWord.value);
    } else {
      togglePlay();
    }
    return;
  }

  if ((e.key === 'p' || e.key === 'P') && !e.ctrlKey && !e.metaKey && !e.altKey) {
    e.preventDefault();
    auditionSelectedWord(selectedWord.value);
    return;
  }

  if ((e.key === 'j' || e.key === 'J') && !e.ctrlKey && !e.metaKey && !e.altKey) {
    e.preventDefault();
    skipBackward(2);
    return;
  }
  if ((e.key === 'k' || e.key === 'K') && !e.ctrlKey && !e.metaKey && !e.altKey) {
    e.preventDefault();
    togglePlay();
    return;
  }
  if ((e.key === 'l' || e.key === 'L') && !e.ctrlKey && !e.metaKey && !e.altKey) {
    e.preventDefault();
    skipForward(2);
    return;
  }

  if (e.altKey && (e.key === 'ArrowLeft' || e.key === 'ArrowRight') && projectStore.activeWordLocation.value) {
    e.preventDefault();
    const nudgeAmount = (e.key === 'ArrowLeft' ? -1 : 1) * (e.shiftKey ? 0.05 : 0.025);
    projectStore.nudgeWord(projectStore.activeWordLocation.value, nudgeAmount, 'end');
    return;
  }

  if ((e.key === 'w' || e.key === 'W') && !e.ctrlKey && !e.metaKey && !e.altKey && projectStore.activeWordLocation.value) {
    e.preventDefault();
    const curTime = ws ? ws.getCurrentTime() : currentTime.value;
    projectStore.updateWordStart(projectStore.activeWordLocation.value, curTime);
    return;
  }
  if ((e.key === 'e' || e.key === 'E') && !e.ctrlKey && !e.metaKey && !e.altKey && projectStore.activeWordLocation.value) {
    e.preventDefault();
    const curTime = ws ? ws.getCurrentTime() : currentTime.value;
    projectStore.updateWordEnd(projectStore.activeWordLocation.value, curTime);
    return;
  }

  if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
    e.preventDefault();
    const step = e.shiftKey ? 0.2 : 0.05;
    const direction = e.key === 'ArrowLeft' ? -1 : 1;
    if (ws) {
      const cur = ws.getCurrentTime() || currentTime.value;
      const newT = Math.max(0, Math.min(duration.value, cur + direction * step));
      ws.setTime(newT);
      currentTime.value = newT;
      projectStore.updateCurrentTime(newT);
      updatePlayheadDirect(newT);
    }
  }

  if (e.key === 'PageUp' || e.key === 'PageDown') {
    e.preventDefault();
    const curT = ws?.getCurrentTime() || currentTime.value;
    const segments = projectStore.activeSegments.value;
    if (segments.length > 0) {
      if (e.key === 'PageDown') {
        const nextSeg = segments.find(s => s.start > curT + 0.1);
        if (nextSeg && ws) {
          ws.setTime(nextSeg.start);
          currentTime.value = nextSeg.start;
          projectStore.updateCurrentTime(nextSeg.start);
          updatePlayheadDirect(nextSeg.start);
        }
      } else {
        const prevSegs = segments.filter(s => s.start < curT - 0.1);
        const prevSeg = prevSegs.length > 0 ? prevSegs[prevSegs.length - 1] : null;
        if (prevSeg && ws) {
          ws.setTime(prevSeg.start);
          currentTime.value = prevSeg.start;
          projectStore.updateCurrentTime(prevSeg.start);
          updatePlayheadDirect(prevSeg.start);
        }
      }
    }
  }

  if (e.key === 'Home' || ((e.key === 'i' || e.key === 'I') && !e.ctrlKey && !e.metaKey)) {
    e.preventDefault();
    if (ws) {
      ws.setTime(0);
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

  if ((e.key === 'v' || e.key === 'V') && !e.ctrlKey && !e.metaKey && !e.altKey && projectStore.activeWordLocation.value) {
    const loc = projectStore.activeWordLocation.value;
    const curTime = ws ? ws.getCurrentTime() : currentTime.value;
    let issue = projectStore.issues.value.find(i => i.location === loc && Math.abs(i.timestamp - curTime) < 1.0);
    if (!issue) {
      issue = projectStore.issues.value.find(i => i.location === loc);
    }
    if (issue) {
      e.preventDefault();
      projectStore.toggleIssueVerified(issue.id);
    }
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

onMounted(() => {
  initWaveSurfer();
  window.addEventListener('keydown', handleKeydown);
  window.addEventListener('quran-theme-changed', handleThemeChanged);

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

  watch(
    () => projectStore.activeSurah.value,
    (s) => {
      if (s) {
        const url = resolveSurahAudioUrl(s);
        if (url) {
          loadAudioUrl(url, s.audio_file);
        }
      }
    },
    { immediate: true }
  );

  watch(
    () => projectStore.currentTab.value,
    (tab) => {
      if (tab === 'studio') {
        nextTick(() => {
          updateViewportDimensions();
          syncTrackScroll();
          const ws = transport.getWaveSurfer();
          if (ws) {
            try {
              ws.setOptions({ minPxPerSec: zoomLevel.value });
            } catch {}
          }
          if (projectStore.activeSurah.value) {
            const s = projectStore.activeSurah.value;
            const url = resolveSurahAudioUrl(s);
            if (url) {
              loadAudioUrl(url, s.audio_file);
            }
          }
        });
      }
    }
  );
});

onUnmounted(() => {
  window.removeEventListener('keydown', handleKeydown);
  window.removeEventListener('quran-theme-changed', handleThemeChanged);
  if (resizeObserver) {
    resizeObserver.disconnect();
  }
  destroyTransport();
});

watch(() => projectStore.currentTime.value, (newT) => {
  const ws = transport.getWaveSurfer();
  if (ws && Math.abs(ws.getCurrentTime() - newT) > 0.15) {
    ws.setTime(newT);
  }
});

watch(() => projectStore.activeWordLocation.value, (loc) => {
  const ws = transport.getWaveSurfer();
  if (!loc || !ws) return;
  const word = projectStore.findWordByLocation(loc, projectStore.currentTime.value);
  if (!word) return;

  selectedWordStartTime.value = word.start;
  const wordPx = word.start * zoomLevel.value;
  const currentScroll = ws.getScroll();
  const vpWidth = viewportClientWidth.value;

  if (wordPx < currentScroll || wordPx > (currentScroll + vpWidth - 120)) {
    const targetScroll = Math.max(0, wordPx - vpWidth / 3);
    ws.setScroll(targetScroll);
    syncTrackScroll();
  }
});
</script>

<style scoped src="./waveform/waveformEditor.css"></style>
