import { ref, computed, type Ref } from 'vue';
import { projectStore } from '../services/projectStore';
import { getAudioStreamUrl, getDuration, isTauriEnvironment, scanAudioDir } from '../services/api';
import {
  normalizeTimedJson,
  validateAgainstReference,
  hydrateWordTextsFromReference,
  EXAMPLE_TIMINGS_STRING
} from '../services/timingsImport';
import { open as openDialog } from '@tauri-apps/plugin-dialog';

export interface TimingPair {
  id: string;
  base: string;
  audio?: { name: string; size: number; path?: string; file?: File };
  json?: { name: string; size: number; path?: string; file?: File };
  status: 'pending' | 'importing' | 'completed' | 'error';
  errorMessage?: string;
  surah?: number;
  wordCount?: number;
}

export const AUDIO_EXTS = ['mp3', 'wav', 'm4a', 'ogg', 'flac', 'aac', 'opus'];

export function baseName(name: string): string {
  return name.replace(/\.[^.]+$/, '').trim().toLowerCase();
}

export function extOf(name: string): string {
  const m = name.match(/\.([a-z0-9]+)$/i);
  return m ? m[1].toLowerCase() : '';
}

export function useTimingImporter(
  addLog: (text: string, type?: 'info' | 'success' | 'warn' | 'error') => void,
  isRunning: Ref<boolean>,
  isComplete: Ref<boolean>,
  isAborted: Ref<boolean>,
  errorMessage: Ref<string>,
  statusMessage: Ref<string>,
  currentStage: Ref<any>,
  progressPercent: Ref<number>,
  onSingleSuccessCallback?: () => void
) {
  const timingPairs = ref<TimingPair[]>([]);
  const showFormatHelp = ref(false);
  const importIndex = ref(-1);
  const importTotal = ref(0);

  const importCurrentName = computed(() => {
    const p = timingPairs.value[importIndex.value];
    return p?.audio?.name || (p ? `${p.base}.json` : '');
  });

  const importablePairs = computed(() =>
    timingPairs.value.filter(p => p.json && p.status !== 'completed')
  );

  function pairNeedsAudio(p: TimingPair): boolean {
    return !p.audio;
  }

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
        return;
      } catch (err) {
        console.warn('Tauri openDialog error, falling back to input:', err);
      }
    }
    const input = document.createElement('input');
    input.type = 'file';
    input.multiple = true;
    input.accept = '.json,audio/*,video/*';
    input.onchange = () => {
      if (input.files && input.files.length > 0) {
        groupTimingEntries(Array.from(input.files).map(f => ({ name: f.name, size: f.size, file: f })));
      }
      input.remove();
    };
    document.body.appendChild(input);
    input.click();
  }

  function onDropTiming(e: DragEvent) {
    if (!e.dataTransfer || !e.dataTransfer.files) return;
    groupTimingEntries(Array.from(e.dataTransfer.files).map(f => ({ name: f.name, size: f.size, file: f })));
  }

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
        return;
      } catch (err) {
        console.warn('Tauri folder scan failed, trying browser fallback:', err);
      }
    }

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
        return;
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
      if (input.files && input.files.length > 0) {
        groupTimingEntries(Array.from(input.files).map(f => ({ name: f.name, size: f.size, file: f })));
      }
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

  async function startTimingImport(_e?: unknown) {
    const pairs = importablePairs.value;
    if (pairs.length === 0) return;

    isRunning.value = true;
    isComplete.value = false;
    errorMessage.value = '';
    statusMessage.value = 'Importing timings…';
    currentStage.value = 'loading';
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

        let audioPath: string | undefined;
        let audioUrl: string | undefined;
        if (pair.audio?.path) {
          audioPath = pair.audio.path;
          audioUrl = getAudioStreamUrl(audioPath);
        } else if (pair.audio?.file) {
          audioUrl = URL.createObjectURL(pair.audio.file);
        }

        let durSec: number | undefined;
        try {
          if (audioPath && isTauriEnvironment()) durSec = await getDuration(audioPath);
          else if (audioUrl) durSec = await probeBlobDuration(audioUrl);
        } catch { /* heuristic fallback */ }

        const timings = normalizeTimedJson(parsed, durSec, pair.base);
        try {
          for (const warn of await hydrateWordTextsFromReference(timings)) {
            addLog(`${pair.base}: ${warn}`, 'warn');
          }
        } catch {}
        projectStore.loadAlignedSurah(timings as any, audioPath, audioUrl);
        pair.status = 'completed';
        pair.wordCount = timings.wordCount;
        try { pair.surah = timings.surahs[0]?.surah; } catch {}
        ok++;
        addLog(`Imported ${pair.base} → Surah ${pair.surah ?? '?'} · ${timings.wordCount} words`, 'success');
        for (const warn of timings.warnings) addLog(`${pair.base}: ${warn}`, 'warn');
        if (!pair.audio) {
          addLog(`${pair.base}: no audio attached — drop the audio file on the timeline to attach it.`, 'warn');
        }
        try {
          const refWarnings = await validateAgainstReference(timings);
          for (const warn of refWarnings) addLog(`${pair.base}: ${warn}`, 'warn');
        } catch {}
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
      projectStore.saveActiveProject().catch(() => {});
      if (pairs.length === 1 && !errorMessage.value && onSingleSuccessCallback) {
        setTimeout(() => {
          if (!isAborted.value && isComplete.value) {
            onSingleSuccessCallback();
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

  return {
    timingPairs,
    showFormatHelp,
    importIndex,
    importTotal,
    importCurrentName,
    importablePairs,
    pairNeedsAudio,
    groupTimingEntries,
    triggerTimingPick,
    onDropTiming,
    pickTimingFolder,
    removeTimingPair,
    startTimingImport,
    saveExampleJson,
    copyExampleJson,
  };
}
