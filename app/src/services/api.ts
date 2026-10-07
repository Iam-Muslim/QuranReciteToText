/**
 * Unified IPC & HTTP bridge for Quran Recite Studio.
 *
 * Automatically detects environment:
 * 1. Tauri Desktop App: Direct IPC invoke() — zero HTTP, zero ports (matches QuranCaption).
 * 2. Vite Dev Server / Browser: Automatic HTTP fallback to FastAPI on port 8000.
 */

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
    throw new Error('Not running inside Tauri desktop environment');
  }
  const { invoke } = await import('@tauri-apps/api/core');
  return invoke;
}

// ── Engine ────────────────────────────────────────────────────────────────────

export async function getEngineStatus(): Promise<{ ready: boolean; python: string; message: string }> {
  if (isTauriEnvironment()) {
    try {
      const invoke = await getInvoke();
      return await invoke('get_engine_status');
    } catch (err: any) {
      console.warn('Tauri get_engine_status failed:', err);
    }
  }
  // Browser fallback: check FastAPI /api/status
  try {
    const res = await fetch('/api/engine/status');
    if (res.ok) {
      return { ready: true, python: 'python', message: 'Engine ready' };
    }
  } catch {}
  return { ready: false, python: '', message: 'Engine offline' };
}

export async function isEngineInstalled(): Promise<boolean> {
  if (isTauriEnvironment()) {
    try {
      const invoke = await getInvoke();
      return await invoke('is_engine_installed');
    } catch {
      return false;
    }
  }
  return true;
}

export async function ensureEngine(): Promise<void> {
  if (isTauriEnvironment()) {
    const invoke = await getInvoke();
    await invoke('ensure_engine');
  }
}

// ── Alignment ─────────────────────────────────────────────────────────────────

export interface AlignRequest {
  audio_path?: string;
  dir_path?: string;
  fast?: boolean;
}

/**
 * Starts alignment. In Tauri, progress comes back on the `align-event` channel.
 * In browser, calls the FastAPI alignment endpoint.
 */
export async function runAlign(request: AlignRequest): Promise<void> {
  if (isTauriEnvironment()) {
    const invoke = await getInvoke();
    await invoke('run_align', { request });
    return;
  }
  // Browser fallback
  const res = await fetch('/api/engine/align', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  });
  if (!res.ok) throw new Error(`Alignment failed to start: ${res.statusText}`);
}

export async function stopAlign(): Promise<void> {
  if (isTauriEnvironment()) {
    const invoke = await getInvoke();
    await invoke('stop_align');
    return;
  }
  await fetch('/api/engine/align/stop', { method: 'POST' });
}

// ── Projects ──────────────────────────────────────────────────────────────────

export async function listProjects(): Promise<{ projects: any[] }> {
  if (isTauriEnvironment()) {
    const invoke = await getInvoke();
    return invoke('list_projects');
  }
  const res = await fetch('/api/engine/projects');
  if (!res.ok) throw new Error(`Failed to list projects: ${res.statusText}`);
  return res.json();
}

export async function loadProject(file: string): Promise<any> {
  if (isTauriEnvironment()) {
    const invoke = await getInvoke();
    return invoke('load_project', { file });
  }
  const res = await fetch(`/api/engine/projects/load?file=${encodeURIComponent(file)}`);
  if (!res.ok) throw new Error(`Failed to load project: ${res.statusText}`);
  return res.json();
}

export async function saveProject(file: string, data: any): Promise<void> {
  if (isTauriEnvironment()) {
    const invoke = await getInvoke();
    await invoke('save_project', { request: { file, data } });
    return;
  }
  const payload = { ...data, file_name: file };
  const res = await fetch('/api/engine/projects/save', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(`Failed to save project: ${res.statusText}`);
}

export async function createProject(name: string, data: any): Promise<{ file: string; path: string }> {
  if (isTauriEnvironment()) {
    const invoke = await getInvoke();
    const res: any = await invoke('create_project', { request: { name, data } });
    return {
      file: res.file || res.file_name || `${name}.qproj`,
      path: res.path || '',
    };
  }
  const res = await fetch('/api/engine/projects/create', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      name,
      reciter: data?.reciter || '',
      riwayah: data?.settings?.riwayah || "Hafs 'an 'Asim",
    }),
  });
  if (!res.ok) throw new Error(`Failed to create project: ${res.statusText}`);
  const json = await res.json();
  return {
    file: json.file_name || json.file || `${name}.qproj`,
    path: json.file_path || json.path || '',
  };
}

export async function deleteProject(file: string): Promise<void> {
  if (isTauriEnvironment()) {
    const invoke = await getInvoke();
    await invoke('delete_project', { request: { file } });
    return;
  }
  const res = await fetch('/api/engine/projects/delete', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ file_name: file }),
  });
  if (!res.ok) throw new Error(`Failed to delete project: ${res.statusText}`);
}

export async function duplicateProject(file: string): Promise<{ file: string }> {
  if (isTauriEnvironment()) {
    const invoke = await getInvoke();
    return invoke('duplicate_project', { request: { file } });
  }
  const res = await fetch('/api/engine/projects/duplicate', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ file_name: file }),
  });
  if (!res.ok) throw new Error(`Failed to duplicate project: ${res.statusText}`);
  const json = await res.json();
  return { file: json.file_name || json.file || file };
}

// ── Audio / Files ─────────────────────────────────────────────────────────────

export async function scanAudioDir(dir_path: string): Promise<any> {
  if (isTauriEnvironment()) {
    const invoke = await getInvoke();
    return invoke('scan_audio_dir', { request: { dir_path } });
  }
  const res = await fetch('/api/engine/scan_dir', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ dir_path }),
  });
  if (!res.ok) throw new Error(`Failed to scan audio directory: ${res.statusText}`);
  return res.json();
}

/**
 * Returns an audio stream URL:
 * - In Tauri: uses Tauri asset:// protocol for zero-overhead local file reading.
 * - In Browser: uses FastAPI /api/engine/audio streaming endpoint.
 */
export function getAudioStreamUrl(filePath: string): string {
  if (!filePath) return '';
  if (
    filePath.startsWith('http://') ||
    filePath.startsWith('https://') ||
    filePath.startsWith('blob:') ||
    filePath.startsWith('asset://')
  ) {
    return filePath;
  }
  if (isTauriEnvironment()) {
    try {
      const w = window as any;
      if (w.__TAURI__?.core?.convertFileSrc) {
        return w.__TAURI__.core.convertFileSrc(filePath);
      }
    } catch {}
    const normalized = filePath.replace(/\\/g, '/');
    return `asset://localhost/${encodeURIComponent(normalized).replace(/%2F/g, '/')}`;
  }
  return `/api/engine/audio/stream?path=${encodeURIComponent(filePath.replace(/\\/g, '/'))}`;
}

// ── System ────────────────────────────────────────────────────────────────────

export async function revealInExplorer(path: string): Promise<void> {
  if (isTauriEnvironment()) {
    const invoke = await getInvoke();
    await invoke('reveal_in_explorer', { request: { path } });
    return;
  }
  await fetch('/api/engine/system/reveal', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ path }),
  });
}

// ── Legacy compatibility shims ────────────────────────────────────────────────

/** @deprecated No-op compatibility shim. */
export async function initApiRouting(): Promise<string> {
  return '';
}

/** @deprecated Compatibility shim. */
export function getApiBaseUrl(): string {
  return isTauriEnvironment() ? '' : '';
}
