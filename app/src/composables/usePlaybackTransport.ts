import { ref, type Ref } from 'vue';
import WaveSurfer from 'wavesurfer.js';
import MinimapPlugin from 'wavesurfer.js/dist/plugins/minimap.esm.js';
import { projectStore } from '../services/projectStore';
import { isTauriEnvironment, getAudioStreamUrl, getAudioWaveform, getDuration } from '../services/api';
import type { AlignedWord } from '../types/aligner';

// In-Memory Waveform Peaks Cache
const peaksCache = new Map<string, { peaks: number[]; duration: number; url?: string }>();

export function usePlaybackTransport(
  waveformMount: Ref<HTMLElement | null>,
  minimapMount: Ref<HTMLElement | null>,
  segmentPlayheadLine: Ref<HTMLElement | null>,
  wordPlayheadLine: Ref<HTMLElement | null>,
  ayahTrackViewport: Ref<HTMLElement | null>,
  wordTrackViewport: Ref<HTMLElement | null>,
  onLoopCheck?: (t: number) => void
) {
  let wavesurfer: WaveSurfer | null = null;
  let minimapPlugin: any = null;
  let currentlyLoadedAudioUrl: string | null = null;
  let playbackRafId: number | null = null;
  let lastTimecodeUpdate = 0;

  const isPlaying = ref(false);
  const currentTime = ref(0);
  const duration = ref(0);
  const zoomLevel = ref(120);
  const playbackRate = ref(1.0);
  const hasAudioLoaded = ref(false);
  const currentScrollLeft = ref(0);
  const viewportClientWidth = ref(800);

  function updatePlayheadDirect(t: number) {
    const px = t * zoomLevel.value;
    if (segmentPlayheadLine.value) {
      segmentPlayheadLine.value.style.transform = `translateX(${px}px)`;
    }
    if (wordPlayheadLine.value) {
      wordPlayheadLine.value.style.transform = `translateX(${px}px)`;
    }
  }

  function startPlaybackClock() {
    if (playbackRafId !== null) return;
    const tick = (now: number) => {
      if (!wavesurfer || !isPlaying.value) {
        playbackRafId = null;
        return;
      }
      const t = wavesurfer.getCurrentTime();
      updatePlayheadDirect(t);
      projectStore.updateCurrentTime(t);
      if (onLoopCheck) onLoopCheck(t);

      if (now - lastTimecodeUpdate >= 100) {
        currentTime.value = t;
        lastTimecodeUpdate = now;
      }

      playbackRafId = requestAnimationFrame(tick);
    };
    playbackRafId = requestAnimationFrame(tick);
  }

  function stopPlaybackClock() {
    if (playbackRafId !== null) {
      cancelAnimationFrame(playbackRafId);
      playbackRafId = null;
    }
    if (wavesurfer) {
      const t = wavesurfer.getCurrentTime();
      currentTime.value = t;
      updatePlayheadDirect(t);
    }
  }

  function handleThemeChanged() {
    if (!wavesurfer) return;
    const cs = getComputedStyle(document.documentElement);
    const read = (name: string, fallback: string) => cs.getPropertyValue(name).trim() || fallback;
    const next = {
      accent: read('--accent-primary', '#2e7ce4'),
      wave: read('--wave-base', '#4a4a50'),
      waveDim: read('--wave-base-dim', '#333338'),
      cursor: read('--playhead-color', '#ffffff'),
    };
    try { wavesurfer.setOptions({ waveColor: next.wave, progressColor: next.accent, cursorColor: next.cursor }); } catch {}
    try { (minimapPlugin as unknown as { setOptions: (o: object) => void } | null)?.setOptions?.({ waveColor: next.waveDim, progressColor: next.accent, cursorColor: next.cursor }); } catch {}
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

  function initWaveSurfer() {
    if (!waveformMount.value) return;

    const cs = getComputedStyle(document.documentElement);
    const read = (name: string, fallback: string) => cs.getPropertyValue(name).trim() || fallback;
    const tokens = {
      accent: read('--accent-primary', '#2e7ce4'),
      wave: read('--wave-base', '#4a4a50'),
      waveDim: read('--wave-base-dim', '#333338'),
      cursor: read('--playhead-color', '#ffffff'),
    };

    minimapPlugin = MinimapPlugin.create({
      container: minimapMount.value || undefined,
      height: 22,
      waveColor: tokens.waveDim,
      progressColor: tokens.accent,
      cursorColor: tokens.cursor,
    });

    wavesurfer = WaveSurfer.create({
      container: waveformMount.value,
      waveColor: tokens.wave,
      progressColor: tokens.accent,
      cursorColor: tokens.cursor,
      cursorWidth: 1.5,
      height: 105,
      minPxPerSec: zoomLevel.value,
      autoScroll: true,
      autoCenter: true,
      hideScrollbar: true,
      plugins: [minimapPlugin],
    });

    wavesurfer.on('play', () => {
      hasAudioLoaded.value = true;
      isPlaying.value = true;
      projectStore.isPlaying.value = true;
      startPlaybackClock();
    });

    wavesurfer.on('pause', () => {
      isPlaying.value = false;
      projectStore.isPlaying.value = false;
      stopPlaybackClock();
    });

    wavesurfer.on('timeupdate', (t: number) => {
      if (!isPlaying.value) {
        updatePlayheadDirect(t);
        currentTime.value = t;
        projectStore.updateCurrentTime(t);
      }
      if (onLoopCheck) onLoopCheck(t);
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

    wavesurfer.on('decode', (dur: number) => {
      if (dur > 0) {
        duration.value = dur;
        hasAudioLoaded.value = true;
        updateViewportDimensions();
        syncTrackScroll();
      }
    });

    wavesurfer.on('error', (err) => {
      console.error('WaveSurfer audio load error:', err, 'for streamUrl:', currentlyLoadedAudioUrl);
    });

    wavesurfer.on('scroll', () => {
      syncTrackScroll();
    });
  }

  async function loadAudioUrl(url: string, filePath?: string | null) {
    if (!wavesurfer) return;

    const effectivePath = filePath || projectStore.activeAudioFilePath.value || url;
    let streamUrl = url;

    if (/^(blob:|data:)/.test(url)) {
      streamUrl = url;
    } else if (isTauriEnvironment()) {
      streamUrl = getAudioStreamUrl(effectivePath || url);
    } else {
      if (url && (url.startsWith('http://') || url.startsWith('https://') || url.startsWith('/api') || url.startsWith('blob:'))) {
        streamUrl = url;
      } else if (effectivePath) {
        streamUrl = getAudioStreamUrl(effectivePath);
      }
    }

    if (currentlyLoadedAudioUrl === streamUrl && hasAudioLoaded.value) return;
    currentlyLoadedAudioUrl = streamUrl;

    if (peaksCache.has(effectivePath)) {
      const cached = peaksCache.get(effectivePath)!;
      try {
        duration.value = cached.duration;
        wavesurfer.load(cached.url || streamUrl, [cached.peaks], cached.duration);
        return;
      } catch {}
    }

    let peaksData: number[] | null = null;
    let dur: number | null = null;

    if (isTauriEnvironment() && effectivePath && (effectivePath.includes(':') || effectivePath.startsWith('/'))) {
      try {
        const exactDurationMs = await getDuration(effectivePath);
        if (exactDurationMs > 0) {
          dur = exactDurationMs / 1000.0;
          duration.value = dur;
        }
      } catch (e) {
        console.debug('ffprobe exact duration fallback:', e);
      }

      try {
        const backendPeaks = await getAudioWaveform(effectivePath);
        if (backendPeaks && backendPeaks.length > 0) {
          peaksData = backendPeaks;
          const pcmDuration = backendPeaks.length / 100.0;
          dur = pcmDuration;
          duration.value = dur;
          peaksCache.set(effectivePath, { peaks: backendPeaks, duration: dur, url: streamUrl });
        }
      } catch (e) {
        console.debug('Fast peaks extraction fallback to client WebAudio:', e);
      }
    }

    try {
      if (peaksData && dur) {
        wavesurfer.load(streamUrl, [peaksData], dur);
      } else {
        wavesurfer.load(streamUrl);
      }
    } catch (loadErr) {
      console.error('Failed to load streamUrl into WaveSurfer:', loadErr);
    }
  }

  function togglePlay() {
    if (!wavesurfer) return;
    if (!hasAudioLoaded.value && wavesurfer.getDuration() > 0) {
      hasAudioLoaded.value = true;
    }
    if (!hasAudioLoaded.value) {
      console.warn('Playback paused: audio is still loading or URL failed to load:', currentlyLoadedAudioUrl);
      return;
    }
    wavesurfer.playPause();
  }

  function skipBackward(amount: number) {
    if (!wavesurfer) return;
    if (!hasAudioLoaded.value && wavesurfer.getDuration() > 0) hasAudioLoaded.value = true;
    if (!hasAudioLoaded.value) return;
    wavesurfer.setTime(Math.max(0, wavesurfer.getCurrentTime() - amount));
  }

  function skipForward(amount: number) {
    if (!wavesurfer) return;
    if (!hasAudioLoaded.value && wavesurfer.getDuration() > 0) hasAudioLoaded.value = true;
    if (!hasAudioLoaded.value) return;
    wavesurfer.setTime(Math.min(duration.value, wavesurfer.getCurrentTime() + amount));
  }

  function adjustZoom(delta: number, clientX?: number) {
    if (!wavesurfer) return;
    const oldZoom = zoomLevel.value;
    const newZoom = Math.max(40, Math.min(320, oldZoom + delta));
    if (newZoom === oldZoom) return;

    const currentScroll = wavesurfer.getScroll();
    const vpWidth = viewportClientWidth.value;

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

    const targetScroll = Math.max(0, focalTime * newZoom - focalOffset);
    wavesurfer.setScroll(targetScroll);
    syncTrackScroll();
  }

  function updateZoom() {
    if (!wavesurfer) return;
    wavesurfer.zoom(zoomLevel.value);
    projectStore.zoomPxPerSec.value = zoomLevel.value;
    syncTrackScroll();
  }

  const SPEED_PRESETS = [0.5, 0.65, 0.75, 0.85, 1.0, 1.15, 1.25, 1.5, 1.75, 2.0];

  function changePlaybackRate() {
    if (!wavesurfer) return;
    wavesurfer.setPlaybackRate(playbackRate.value);
    projectStore.playbackRate.value = playbackRate.value;
  }

  function stepPlaybackRate(delta: number) {
    const current = playbackRate.value;
    let idx = SPEED_PRESETS.findIndex((s) => Math.abs(s - current) < 0.02);
    if (idx === -1) {
      idx = SPEED_PRESETS.findIndex((s) => s >= current);
      if (idx === -1) idx = SPEED_PRESETS.length - 1;
    }
    const nextIdx = Math.max(0, Math.min(SPEED_PRESETS.length - 1, idx + delta));
    playbackRate.value = SPEED_PRESETS[nextIdx];
    changePlaybackRate();
  }

  function auditionSelectedWord(word: AlignedWord | undefined | null) {
    if (!wavesurfer || !word) return;

    wavesurfer.setTime(word.start);
    currentTime.value = word.start;
    projectStore.updateCurrentTime(word.start);
    updatePlayheadDirect(word.start);
    wavesurfer.play();

    const targetEnd = word.end;
    const onAuditionUpdate = (t: number) => {
      if (t >= targetEnd) {
        wavesurfer?.pause();
        wavesurfer?.un('timeupdate', onAuditionUpdate);
      }
    };
    wavesurfer.on('timeupdate', onAuditionUpdate);
  }

  function destroy() {
    stopPlaybackClock();
    if (wavesurfer) {
      wavesurfer.destroy();
      wavesurfer = null;
    }
  }

  return {
    getWaveSurfer: () => wavesurfer,
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
    stepPlaybackRate,
    SPEED_PRESETS,
    auditionSelectedWord,
    syncTrackScroll,
    onTrackViewportScroll,
    updateViewportDimensions,
    updatePlayheadDirect,
    handleThemeChanged,
    stopPlaybackClock,
    destroy,
  };
}
