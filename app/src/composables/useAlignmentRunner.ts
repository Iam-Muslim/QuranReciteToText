import { ref, computed, nextTick, type Ref } from 'vue';
import { projectStore } from '../services/projectStore';
import { 
  runAlign, 
  stopAlign, 
  scanAudioDir, 
  getAudioStreamUrl, 
  isTauriEnvironment,
  audioTimestampStretchMs,
  normalizeAudioTimestamps
} from '../services/api';
import { normalizeRiwayahKey } from '../services/RiwayahProvider';
import { open as openDialog } from '@tauri-apps/plugin-dialog';

export interface QueueItem {
  id: string;
  file: File;
  status: 'pending' | 'uploading' | 'aligning' | 'completed' | 'error';
  uploadedPath?: string;
  uploadedUrl?: string;
  errorMessage?: string;
}

export interface ScannedAudioFile {
  name: string;
  rel_path: string;
  full_path: string;
  size: number;
  ext?: string;
  file?: File;
}

export interface LogEntry {
  text: string;
  type: 'info' | 'success' | 'warn' | 'error';
}

export function useAlignmentRunner(
  isRunning: Ref<boolean>,
  isComplete: Ref<boolean>,
  isAborted: Ref<boolean>,
  errorMessage: Ref<string>,
  selectedRiwayah: Ref<string>,
  fastMode: Ref<boolean>,
  consoleBoxRef: Ref<HTMLElement | null>,
  fileInput: Ref<HTMLInputElement | null>,
  onSingleSuccessCallback?: () => void
) {
  let alignEventUnlisten: (() => void) | null = null;
  let alignPrepUnlisten: (() => void) | null = null;
  let elapsedTimer: ReturnType<typeof setInterval> | null = null;

  const currentStage = ref<'idle' | 'loading' | 'vad' | 'transcribing' | 'aligning' | 'matching' | 'completed'>('idle');
  const progressPercent = ref(0);
  const speedX = ref(0);
  const statusMessage = ref('Ready');
  const runStartedAt = ref(0);
  const elapsedSeconds = ref(0);

  const consoleLogs = ref<LogEntry[]>([]);
  const showLogs = ref(false);

  // Files Queue State
  const filesQueue = ref<QueueItem[]>([]);
  const currentQueueIndex = ref(0);

  // Directory Batch State
  const dirPath = ref('');
  const isScanningDir = ref(false);
  const dirScanError = ref('');
  const scannedFiles = ref<ScannedAudioFile[]>([]);

  const elapsedLabel = computed(() => {
    if (!isRunning.value || elapsedSeconds.value <= 0) return '';
    const total = elapsedSeconds.value;
    if (total < 60) return `${total}s`;
    const m = Math.floor(total / 60);
    const s = total % 60;
    return `${m}:${s.toString().padStart(2, '0')}`;
  });

  const progressIndeterminate = computed(() =>
    isRunning.value
    && (currentStage.value === 'idle' || currentStage.value === 'loading' || currentStage.value === 'vad')
  );

  const currentProcessingFileName = computed(() => {
    if (filesQueue.value.length > 0 && filesQueue.value[currentQueueIndex.value]) {
      return filesQueue.value[currentQueueIndex.value].file.name;
    }
    return '';
  });

  const currentStageLabel = computed(() => {
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

  function addLog(text: string, type: 'info' | 'success' | 'warn' | 'error' = 'info') {
    consoleLogs.value.push({ text, type });
    if (type === 'error') showLogs.value = true;
    nextTick(() => {
      if (consoleBoxRef.value) {
        consoleBoxRef.value.scrollTop = consoleBoxRef.value.scrollHeight;
      }
    });
  }

  async function pickDirectory() {
    isScanningDir.value = true;
    dirScanError.value = '';
    try {
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
          }
          return;
        } catch (tErr) {
          console.warn('Tauri dialog error, trying browser picker:', tErr);
        }
      }

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
          if (pickerErr.name === 'AbortError') return;
          console.warn('showDirectoryPicker error, trying input fallback:', pickerErr);
        }
      }

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
          if (folder) dirPath.value = folder;
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
        return;
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

  function stopBatch() {
    isAborted.value = true;
    stopAlign().catch(() => {});
    if (alignEventUnlisten) { alignEventUnlisten(); alignEventUnlisten = null; }
    if (alignPrepUnlisten) { alignPrepUnlisten(); alignPrepUnlisten = null; }

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

        const nativePath: string = (item.file as any)?.path || '';
        if (nativePath && (nativePath.includes(':') || nativePath.startsWith('/'))) {
          audioPath = nativePath;
          audioUrl = getAudioStreamUrl(nativePath);
        }

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
      if (filesQueue.value.length === 1 && !errorMessage.value && onSingleSuccessCallback) {
        setTimeout(() => {
          if (!isAborted.value && isComplete.value) {
            onSingleSuccessCallback();
          }
        }, 700);
      }
    }
  }

  async function startDirAlignment() {
    if (!dirPath.value.trim() && scannedFiles.value.length === 0) return;

    const targetDir = dirPath.value.trim();
    if (!targetDir) {
      const browserFiles = scannedFiles.value.filter(f => f.file instanceof File);
      if (browserFiles.length > 0) {
        filesQueue.value = browserFiles.map(bf => ({
          id: `${bf.name}_${Date.now()}_${Math.random().toString(36).substring(2, 7)}`,
          file: bf.file!,
          status: 'pending',
        }));
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

  function cleanup() {
    if (alignEventUnlisten) { alignEventUnlisten(); alignEventUnlisten = null; }
    if (alignPrepUnlisten) { alignPrepUnlisten(); alignPrepUnlisten = null; }
    stopElapsedTimer();
  }

  return {
    currentStage,
    progressPercent,
    speedX,
    statusMessage,
    elapsedSeconds,
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
    addLog,
    pickDirectory,
    scanDirectory,
    triggerFilePick,
    onFilesChosen,
    onDropFiles,
    addFilesToQueue,
    removeQueueItem,
    clearQueue,
    stopBatch,
    startFilesAlignmentQueue,
    startDirAlignment,
    cleanup,
  };
}
