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
  let wakeLockSentinel: any = null;

  async function requestWakeLock() {
    if (typeof navigator !== 'undefined' && 'wakeLock' in navigator) {
      try {
        wakeLockSentinel = await (navigator as any).wakeLock.request('screen');
      } catch {}
    }
  }

  function releaseWakeLock() {
    if (wakeLockSentinel) {
      try {
        wakeLockSentinel.release();
      } catch {}
      wakeLockSentinel = null;
    }
  }

  function syncMediaSessionPosition() {
    if (typeof navigator === 'undefined' || !('mediaSession' in navigator) || !navigator.mediaSession.setPositionState) return;
    if (!duration.value || duration.value <= 0) return;
    try {
      navigator.mediaSession.setPositionState({
        duration: Math.max(0, duration.value),
        playbackRate: playbackRate.value || 1.0,
        position: Math.min(duration.value, Math.max(0, currentTime.value)),
      });
    } catch {}
  }

  function updateMediaSession() {
    if (typeof navigator === 'undefined' || !('mediaSession' in navigator)) return;
    const s = projectStore.activeSurah.value;
    const proj = projectStore.project;
    const reciter = proj?.reciter || proj?.settings?.reciter_name || 'Quran Reciter';
    const surahName = s ? `${s.surah_name_arabic || ''} · ${s.surah_name_english || ''}`.trim() : 'Quran Recitation';

    try {
      navigator.mediaSession.metadata = new MediaMetadata({
        title: surahName || 'Quran Recite2Text',
        artist: reciter,
        album: proj?.project_name || 'Quran Recitations',
        artwork: [
          { src: '/logo.png', sizes: '512x512', type: 'image/png' }
        ]
      });

      navigator.mediaSession.setActionHandler('play', () => { togglePlay(); });
      navigator.mediaSession.setActionHandler('pause', () => { togglePlay(); });
      navigator.mediaSession.setActionHandler('seekbackward', (details) => { skipBackward(details?.seekOffset || 3); });
      navigator.mediaSession.setActionHandler('seekforward', (details) => { skipForward(details?.seekOffset || 3); });
      navigator.mediaSession.setActionHandler('seekto', (details) => {
        if (details.seekTime !== undefined && wavesurfer) {
          wavesurfer.setTime(details.seekTime);
          currentTime.value = details.seekTime;
          projectStore.updateCurrentTime(details.seekTime);
          updatePlayheadDirect(details.seekTime);
          syncMediaSessionPosition();
        }
      });
      navigator.mediaSession.setActionHandler('previoustrack', () => { projectStore.jumpToPrevAyah(); });
      navigator.mediaSession.setActionHandler('nexttrack', () => { projectStore.jumpToNextAyah(); });
      syncMediaSessionPosition();
    } catch {}
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
      dragToSeek: true,
      plugins: [minimapPlugin],
    });

    wavesurfer.on('play', () => {
      hasAudioLoaded.value = true;
      isPlaying.value = true;
      projectStore.isPlaying.value = true;
      startPlaybackClock();
      updateMediaSession();
      if (typeof navigator !== 'undefined' && 'mediaSession' in navigator) {
        try { navigator.mediaSession.playbackState = 'playing'; } catch {}
      }
      syncMediaSessionPosition();
      void requestWakeLock();
    });

    wavesurfer.on('pause', () => {
      isPlaying.value = false;
      projectStore.isPlaying.value = false;
      stopPlaybackClock();
      releaseWakeLock();
      if (typeof navigator !== 'undefined' && 'mediaSession' in navigator) {
        try { navigator.mediaSession.playbackState = 'paused'; } catch {}
      }
      syncMediaSessionPosition();
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

  let inFlightLoadUrl: string | null = null;

  async function loadAudioUrl(
    url: string, 
    filePath?: string | null, 
    waveformUrl?: string | null, 
    knownDuration?: number | null,
    precomputedPeaks?: number[] | null
  ) {
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

    if (!streamUrl) return;

    // Prevent duplicate concurrent loads of the same URL that would cancel WaveSurfer
    if (currentlyLoadedAudioUrl === streamUrl && hasAudioLoaded.value) return;
    if (inFlightLoadUrl === streamUrl) return;
    inFlightLoadUrl = streamUrl;
    currentlyLoadedAudioUrl = streamUrl;

    try {
      // 0. Instant Zero-Bandwidth: Use precomputed peaks from active Surah or argument if available
      const directPeaks = (precomputedPeaks && precomputedPeaks.length > 0) 
        ? precomputedPeaks 
        : projectStore.activeSurah.value?.peaks;

      if (directPeaks && directPeaks.length > 0) {
        const explicitDur = knownDuration || projectStore.activeSurah.value?.audio_duration_seconds || 0;
        if (explicitDur > 0) duration.value = explicitDur;
        peaksCache.set(streamUrl, { peaks: directPeaks, duration: explicitDur, url: streamUrl });
        try {
          await wavesurfer.load(streamUrl, [directPeaks], explicitDur > 0 ? explicitDur : undefined);
          hasAudioLoaded.value = true;
          return;
        } catch (err) {
          console.debug('Direct precomputed peaks load fallback:', err);
        }
      }

      // 1. Fetch remote precomputed peaks if provided and not yet cached (Bandwidth Saver)
      if (waveformUrl && !peaksCache.has(waveformUrl) && !peaksCache.has(streamUrl)) {
        try {
          const res = await fetch(waveformUrl);
          if (res.ok) {
            const json = await res.json();
            const remotePeaks: number[] = Array.isArray(json) 
              ? json 
              : (Array.isArray(json.data) ? json.data : (Array.isArray(json.peaks) ? json.peaks : []));
            const remoteDur = Number(json.duration) || knownDuration || 0;
            if (remotePeaks.length > 0) {
              peaksCache.set(streamUrl, { peaks: remotePeaks, duration: remoteDur, url: streamUrl });
              peaksCache.set(waveformUrl, { peaks: remotePeaks, duration: remoteDur, url: streamUrl });
            }
          }
        } catch (e) {
          console.debug('Failed to fetch remote waveform peaks:', e);
        }
      }

      // 2. Check if peaks exist in in-memory cache
      const cached = peaksCache.get(effectivePath) || peaksCache.get(streamUrl) || (waveformUrl ? peaksCache.get(waveformUrl) : null);
      if (cached) {
        try {
          duration.value = cached.duration;
          await wavesurfer.load(cached.url || streamUrl, [cached.peaks], cached.duration);
          hasAudioLoaded.value = true;
          return;
        } catch {}
      }

      let peaksData: number[] | null = null;
      let dur: number | null = knownDuration || null;

      // 3. In Tauri: Resolve actual local disk path (stripping asset:// or asset.localhost if present)
      let diskPath = effectivePath;
      if (diskPath.startsWith('http://asset.localhost/')) {
        diskPath = decodeURIComponent(diskPath.replace('http://asset.localhost/', ''));
      } else if (diskPath.startsWith('asset://localhost/')) {
        diskPath = decodeURIComponent(diskPath.replace('asset://localhost/', ''));
      } else if (diskPath.startsWith('asset://')) {
        diskPath = decodeURIComponent(diskPath.replace('asset://', ''));
      }

      const isLocalDiskFile = isTauriEnvironment() && 
        diskPath && 
        !diskPath.startsWith('http://') && 
        !diskPath.startsWith('https://') && 
        !diskPath.startsWith('blob:') && 
        !diskPath.startsWith('data:') && 
        (diskPath.includes(':') || diskPath.startsWith('/'));

      if (isLocalDiskFile) {
        try {
          const exactDurationMs = await getDuration(diskPath);
          if (exactDurationMs > 0) {
            dur = exactDurationMs / 1000.0;
            duration.value = dur;
          }
        } catch (e) {
          console.debug('ffprobe exact duration fallback:', e);
        }

        try {
          const backendPeaks = await getAudioWaveform(diskPath);
          if (backendPeaks && backendPeaks.length > 0) {
            peaksData = backendPeaks;
            const pcmDuration = backendPeaks.length / 100.0;
            dur = pcmDuration;
            duration.value = dur;
            peaksCache.set(effectivePath, { peaks: backendPeaks, duration: dur, url: streamUrl });
            peaksCache.set(diskPath, { peaks: backendPeaks, duration: dur, url: streamUrl });
          }
        } catch (e) {
          console.debug('Fast peaks extraction fallback to client WebAudio:', e);
        }
      }

      if (peaksData && dur) {
        await wavesurfer.load(streamUrl, [peaksData], dur);
      } else {
        await wavesurfer.load(streamUrl);
      }
      hasAudioLoaded.value = true;
    } catch (loadErr: any) {
      if (loadErr?.name !== 'AbortError') {
        console.error('Failed to load streamUrl into WaveSurfer:', loadErr);
      }
    } finally {
      if (inFlightLoadUrl === streamUrl) {
        inFlightLoadUrl = null;
      }
    }
  }

  function togglePlay() {
    if (!wavesurfer) return;
    const media = (wavesurfer as any).getMediaElement?.();
    const hasSource = !!(media?.src || currentlyLoadedAudioUrl);
    if (!hasSource) {
      console.warn('Playback paused: no audio source loaded');
      return;
    }

    if (!hasAudioLoaded.value && (wavesurfer.getDuration() > 0 || duration.value > 0)) {
      hasAudioLoaded.value = true;
    }

    try {
      wavesurfer.playPause();
    } catch (err) {
      console.warn('Playback playPause failed:', err);
    }
  }

  function skipBackward(amount: number) {
    if (!wavesurfer) return;
    wavesurfer.setTime(Math.max(0, wavesurfer.getCurrentTime() - amount));
  }

  function skipForward(amount: number) {
    if (!wavesurfer) return;
    wavesurfer.setTime(Math.min(duration.value || wavesurfer.getDuration() || 0, wavesurfer.getCurrentTime() + amount));
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

  let activeRangeListener: ((t: number) => void) | null = null;

  function stopTimeRange() {
    if (!wavesurfer) return;
    if (activeRangeListener) {
      wavesurfer.un('timeupdate', activeRangeListener);
      activeRangeListener = null;
    }
  }

  /**
   * Plays ONLY the precise slice from startTime to endTime and halts immediately.
   * Prevents wasteful forward buffering on large cloud audio files.
   */
  function playTimeRange(startTime: number, endTime: number, onComplete?: () => void) {
    if (!wavesurfer) return;
    stopTimeRange();

    const clampStart = Math.max(0, startTime);
    const clampEnd = Math.max(clampStart, endTime);

    wavesurfer.setTime(clampStart);
    currentTime.value = clampStart;
    projectStore.updateCurrentTime(clampStart);
    updatePlayheadDirect(clampStart);
    wavesurfer.play();

    activeRangeListener = (t: number) => {
      if (t >= clampEnd) {
        wavesurfer?.pause();
        stopTimeRange();
        if (onComplete) onComplete();
      }
    };
    wavesurfer.on('timeupdate', activeRangeListener);
  }

  function auditionSelectedWord(word: AlignedWord | undefined | null) {
    if (!wavesurfer || !word) return;
    playTimeRange(word.start, word.end);
  }

  function auditionAyah(ayahNumber: number) {
    const s = projectStore.activeSurah.value;
    const ayah = s?.ayahs.find(a => a.ayah === ayahNumber);
    if (!ayah) return;
    playTimeRange(ayah.start, ayah.end);
  }

  function destroy() {
    stopTimeRange();
    releaseWakeLock();
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
    auditionAyah,
    playTimeRange,
    stopTimeRange,
    syncTrackScroll,
    onTrackViewportScroll,
    updateViewportDimensions,
    updatePlayheadDirect,
    handleThemeChanged,
    stopPlaybackClock,
    destroy,
  };
}
