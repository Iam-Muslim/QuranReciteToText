/**
 * Direct Tauri IPC Bridge for Quran Recite Studio.
 *
 * All commands are executed directly through native Rust IPC without HTTP or port bindings.
 */

import { convertFileSrc } from '@tauri-apps/api/core';

export function isTauriEnvironment(): boolean {
  if (typeof window === 'undefined') return false;
  const w = window as any;
  return Boolean(
    w.__TAURI_INTERNALS__ ||
    w.__TAURI__ ||
    (window.location && (window.location.protocol === 'tauri:' || window.location.hostname === 'tauri.localhost'))
  );
}

async function getInvoke() {
  if (!isTauriEnvironment()) {
    throw new Error('This action requires running inside the Quran Recite Studio desktop application.');
  }
  const { invoke } = await import('@tauri-apps/api/core');
  return invoke;
}

// ── Alignment ─────────────────────────────────────────────────────────────────

interface AlignRequest {
  audio_path?: string;
  dir_path?: string;
  fast?: boolean;
  qiraat?: string;
}

/**
 * Starts recitation alignment via Rust native process execution.
 * Real-time progress is streamed via the `align-event` Tauri channel.
 */
export async function runAlign(request: AlignRequest): Promise<void> {
  const invoke = await getInvoke();
  await invoke('run_align', { request });
}

export async function stopAlign(): Promise<void> {
  const invoke = await getInvoke();
  await invoke('stop_align');
}

/**
 * True when the local alignment engine (Python + models) is installed.
 * Import-Timing workflows work fully without it.
 */
export async function isEngineInstalled(): Promise<boolean> {
  const invoke = await getInvoke();
  return invoke('is_engine_installed');
}

// ── Projects ──────────────────────────────────────────────────────────────────

export async function listProjects(): Promise<{ projects: any[] }> {
  const invoke = await getInvoke();
  return invoke('list_projects');
}

export async function loadProject(file: string): Promise<any> {
  const invoke = await getInvoke();
  return invoke('load_project', { file });
}

export async function saveProject(file: string, data: any): Promise<void> {
  const invoke = await getInvoke();
  await invoke('save_project', { request: { file, data } });
}

export async function createProject(name: string, data: any): Promise<{ file: string; path: string }> {
  const invoke = await getInvoke();
  const res: any = await invoke('create_project', { request: { name, data } });
  return {
    file: res.file || res.file_name || `${name}.qproj`,
    path: res.path || '',
  };
}

export async function deleteProject(file: string): Promise<void> {
  const invoke = await getInvoke();
  await invoke('delete_project', { request: { file } });
}

export async function duplicateProject(file: string): Promise<{ file: string }> {
  const invoke = await getInvoke();
  return invoke('duplicate_project', { request: { file } });
}

// ── Audio / Media ─────────────────────────────────────────────────────────────

export async function scanAudioDir(dir_path: string): Promise<any> {
  const invoke = await getInvoke();
  return invoke('scan_audio_dir', { request: { dir_path } });
}

/**
 * Fast FFmpeg peak extraction (QuranCaption WaveformService model).
 * Extracts 100 normalized peaks/sec downsampled at 4kHz in ~20ms with 0MB WebAudio RAM.
 */
export async function getAudioWaveform(filePath: string): Promise<number[]> {
  if (!isTauriEnvironment() || !filePath) return [];
  try {
    const invoke = await getInvoke();
    return await invoke('get_audio_waveform', { filePath });
  } catch (err) {
    console.debug('get_audio_waveform fallback:', err);
    return [];
  }
}

/**
 * Checks if audio container duration drifts from decoded PCM duration.
 * Returns stretch in milliseconds. Stretch > 500ms indicates MP3/M4A PTS drift.
 */
export async function audioTimestampStretchMs(filePath: string): Promise<number> {
  if (!isTauriEnvironment() || !filePath) return 0;
  try {
    const invoke = await getInvoke();
    return await invoke('audio_timestamp_stretch_ms', { filePath });
  } catch (err) {
    console.debug('audioTimestampStretchMs error:', err);
    return 0;
  }
}

/**
 * In-place audio timestamp normalization (PTS = real audio content time).
 * Fixes cumulative subtitle / word timing drift on long recitations.
 */
export async function normalizeAudioTimestamps(filePath: string): Promise<void> {
  if (!isTauriEnvironment() || !filePath) return;
  const invoke = await getInvoke();
  await invoke('normalize_audio_timestamps', { filePath });
}

/**
 * Returns exact duration of audio/video file in milliseconds via ffprobe (matches QuranCaption commands::media::get_duration).
 */
export async function getDuration(filePath: string): Promise<number> {
  if (!isTauriEnvironment() || !filePath) return -1;
  try {
    const invoke = await getInvoke();
    return await invoke('get_duration', { filePath });
  } catch (err) {
    console.warn('getDuration IPC failed:', err);
    return -1;
  }
}

/**
 * Fast lossless audio cut via FFmpeg stream copy (matches QuranCaption commands::media::cut_audio).
 */
export async function cutAudio(  sourcePath: string,
  startMs: number,
  endMs: number,
  outputPath: string
): Promise<void> {
  const invoke = await getInvoke();
  await invoke('cut_audio', {
    sourcePath,
    startMs: Math.round(startMs),
    endMs: Math.round(endMs),
    outputPath,
  });
}

export interface BinaryDiagnosticResult {
  name: string;
  resolvedPath?: string | null;
  available: boolean;
  versionOutput?: string | null;
  error?: string | null;
}

/**
 * Checks system health of media binaries (FFmpeg & FFprobe).
 */
export async function diagnoseMediaBinaries(): Promise<BinaryDiagnosticResult[]> {
  if (!isTauriEnvironment()) return [];
  try {
    const invoke = await getInvoke();
    return await invoke('diagnose_media_binaries');
  } catch (err) {
    console.warn('diagnoseMediaBinaries IPC failed:', err);
    return [];
  }
}

/**
 * Picks the best playable audio source for a surah-like record.
 * - Session URLs (blob:/data:/https:) win — they already resolve this session.
 * - Real filesystem paths go through the native asset protocol.
 * - A bare "name.ext" is NOT a filesystem path (browser-imported sessions)
 *   and must not shadow a working URL.
 */
export function resolveAudioSourceUrl(source: {
  audio_file?: string | null;
  audio_url?: string | null;
}): string {
  const fileRef = source.audio_file || '';
  const urlRef = source.audio_url || '';
  const sessionUrl = /^(blob|data|https?):/.test(urlRef) ? urlRef : '';
  const isRealPath = !!(fileRef && /[\\/:]/.test(fileRef));
  return (
    sessionUrl
    || (isRealPath ? getAudioStreamUrl(fileRef) : '')
    || (urlRef ? getAudioStreamUrl(urlRef) : '')
    || ''
  );
}

/**
 * Returns an audio stream URL using the zero-overhead native Tauri asset protocol.
 * Conforms 1:1 to QuranCaption asset protocol standards.
 */
export function getAudioStreamUrl(filePath: string): string {
  if (!filePath) return '';

  // Already a valid asset.localhost, HTTPS, blob, or data URL?
  if (
    filePath.startsWith('http://asset.localhost') ||
    filePath.startsWith('https://') ||
    filePath.startsWith('blob:') ||
    filePath.startsWith('data:')
  ) {
    return filePath;
  }
  if (filePath.startsWith('http://') && !filePath.includes('localhost')) {
    return filePath;
  }

  // Strip broken / legacy "asset://localhost/" or "asset://" prefix
  let rawPath = filePath;
  if (rawPath.startsWith('asset://localhost/')) {
    rawPath = decodeURIComponent(rawPath.replace('asset://localhost/', ''));
  } else if (rawPath.startsWith('asset://')) {
    rawPath = decodeURIComponent(rawPath.replace('asset://', ''));
  }

  // In Tauri Desktop: convert via official @tauri-apps/api/core convertFileSrc
  if (isTauriEnvironment()) {
    try {
      return convertFileSrc(rawPath);
    } catch (err) {
      console.warn('convertFileSrc direct invocation error, trying fallback:', err);
      const w = window as any;
      if (w.__TAURI_INTERNALS__?.convertFileSrc) {
        return w.__TAURI_INTERNALS__.convertFileSrc(rawPath, 'asset');
      }
      if (w.__TAURI__?.core?.convertFileSrc) {
        return w.__TAURI__.core.convertFileSrc(rawPath, 'asset');
      }
    }
  }

  return rawPath;
}

// ── System ────────────────────────────────────────────────────────────────────

export async function revealInExplorer(path: string): Promise<void> {
  const invoke = await getInvoke();
  await invoke('reveal_in_explorer', { request: { path } });
}

/**
 * Opens native file explorer highlighting the file (matches QuranCaption open_explorer_with_file_selected).
 */
export async function openExplorerWithFileSelected(filePath: string): Promise<void> {
  const invoke = await getInvoke();
  await invoke('open_explorer_with_file_selected', { filePath });
}

// ── Compatibility Shims ───────────────────────────────────────────────────────

/** @deprecated No-op compatibility shim. */
export async function initApiRouting(): Promise<string> {
  return '';
}

/** @deprecated Compatibility shim. */
export function getApiBaseUrl(): string {
  return '';
}
