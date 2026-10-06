/**
 * API Service for Quran Recite Studio.
 * 
 * Dynamically resolves the active Python engine port from Tauri IPC
 * to prevent port collisions (no hardcoded ports). In browser development mode,
 * routes through Vite's dev proxy.
 */

let dynamicBaseUrl = '';
let isInitialized = false;

export function isTauriEnvironment(): boolean {
  return (
    typeof window !== 'undefined' &&
    ('__TAURI_INTERNALS__' in (window as unknown as Record<string, unknown>) ||
      '__TAURI__' in (window as unknown as Record<string, unknown>) ||
      window.location.protocol === 'tauri:' ||
      window.location.hostname === 'tauri.localhost')
  );
}

/**
 * Initializes the dynamic API routing by querying the Tauri Rust engine supervisor.
 */
export async function initApiRouting(): Promise<string> {
  if (isInitialized) {
    return dynamicBaseUrl;
  }

  if (isTauriEnvironment()) {
    try {
      const { invoke } = await import('@tauri-apps/api/core');
      const url = await invoke<string>('get_engine_url');
      if (url && url.startsWith('http')) {
        dynamicBaseUrl = url.trim().replace(/\/+$/, '');
      } else {
        const port = await invoke<number>('get_engine_port');
        if (port && port > 0) {
          dynamicBaseUrl = `http://127.0.0.1:${port}`;
        }
      }
    } catch {
      // In dev or fallback mode, keep relative proxy
      dynamicBaseUrl = '';
    }
  } else {
    // In browser/Vite dev mode, Vite proxies /api to the active engine port
    dynamicBaseUrl = '';
  }

  // Globally configure fetch routing if running in Tauri desktop production
  if (isTauriEnvironment() && dynamicBaseUrl) {
    const originalFetch = window.fetch.bind(window);
    (window as unknown as { fetch: typeof window.fetch }).fetch = (
      input: RequestInfo | URL,
      init?: RequestInit
    ): Promise<Response> => {
      let targetInput = input;
      if (typeof input === 'string') {
        if (input.startsWith('/api')) {
          targetInput = `${dynamicBaseUrl}${input}`;
        }
      } else if (input instanceof URL) {
        if (input.pathname.startsWith('/api')) {
          targetInput = new URL(`${dynamicBaseUrl}${input.pathname}${input.search}`);
        }
      }
      return originalFetch(targetInput, init);
    };
  }

  isInitialized = true;
  return dynamicBaseUrl;
}

/**
 * Returns the current active API base URL synchronously.
 */
export function getApiBaseUrl(): string {
  return dynamicBaseUrl;
}

/**
 * Constructs an audio streaming URL compatible with native HTML5 <audio> elements.
 */
export function getAudioStreamUrl(filePath: string): string {
  const base = getApiBaseUrl();
  const normalized = filePath.replace(/\\/g, '/');
  return `${base}/api/engine/audio/stream?path=${encodeURIComponent(normalized)}`;
}
