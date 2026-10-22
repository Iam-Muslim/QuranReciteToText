/**
 * Browser project vault (IndexedDB).
 *
 * When the app runs as a plain web page (shared link on phone/desktop,
 * no Tauri), projects still need a home so a refresh or a revisit does
 * not lose imported recitation work. This vault stores:
 *
 *   - 'projects': full project JSON (timings + settings, sanitized
 *     exactly like the desktop autosave).
 *   - 'audio': per-surah audio Blobs keyed by "<file>::<surah>" — Blobs
 *     are stored natively, so no base64 bloat.
 *
 * Summaries mirror the Rust `list_projects` shape so ProjectsHub renders
 * the same cards in both environments.
 */
import type { AlignerProject, ProjectSummary, SurahItem } from '../types/aligner';

const DB_NAME = 'quran-studio-vault';
const DB_VERSION = 1;
const PROJECTS = 'projects';
const AUDIO = 'audio';
const KEY_SEP = '::';

let dbPromise: Promise<IDBDatabase> | null = null;
/** Surahs whose session audio is already mirrored into the vault. */
const audioPersisted = new Set<string>();

function available(): boolean {
  try {
    return typeof indexedDB !== 'undefined' && indexedDB !== null;
  } catch {
    return false;
  }
}

function openDb(): Promise<IDBDatabase> {
  if (!available()) return Promise.reject(new Error('IndexedDB unavailable'));
  if (dbPromise) return dbPromise;
  dbPromise = new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, DB_VERSION);
    req.onupgradeneeded = () => {
      const db = req.result;
      if (!db.objectStoreNames.contains(PROJECTS)) db.createObjectStore(PROJECTS, { keyPath: 'file_name' });
      if (!db.objectStoreNames.contains(AUDIO)) db.createObjectStore(AUDIO, { keyPath: 'key' });
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => {
      dbPromise = null;
      reject(req.error || new Error('IndexedDB open failed'));
    };
  });
  return dbPromise;
}

function tx(db: IDBDatabase, store: string, mode: IDBTransactionMode): IDBObjectStore {
  return db.transaction(store, mode).objectStore(store);
}

function asPromise<T>(req: IDBRequest<T>): Promise<T> {
  return new Promise((resolve, reject) => {
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

/** Stable vault key for a project — mirrors desktop `${name}.qproj`. */
export function safeProjectFileName(name: string): string {
  const trimmed = String(name || '').trim().replace(/[\\/:*?"<>|]+/g, ' ').slice(0, 80);
  const base = trimmed || 'Browser Recitations';
  return /\.qproj$/i.test(base) ? base : `${base}.qproj`;
}

function worstStatus(surahs: SurahItem[]): string {
  const set = new Set(surahs.map(s => s.status));
  if (set.has('unaligned')) return 'unaligned';
  if (set.has('needs_review')) return 'needs_review';
  if (set.has('aligned')) return 'aligned';
  return 'verified';
}

function buildSummary(project: AlignerProject, fileName: string, sizeBytes: number): ProjectSummary {
  const surahs = project.surahs || [];
  return {
    file_name: fileName,
    project_name: project.project_name || fileName.replace(/\.qproj$/i, ''),
    reciter: project.reciter || project.settings?.reciter_name || '',
    riwayah: project.settings?.riwayah || 'Hafs',
    status: worstStatus(surahs),
    surahs_count: surahs.length,
    surah_numbers: surahs.map(s => s.surah_number),
    primary_surah: surahs.length > 0
      ? {
          surah_number: surahs[0].surah_number,
          surah_name_arabic: surahs[0].surah_name_arabic,
          surah_name_english: surahs[0].surah_name_english,
        }
      : null,
    total_ayahs: surahs.reduce((n, s) => n + (s.ayahs?.length || 0), 0),
    total_duration: surahs.reduce((n, s) => Math.max(n, s.audio_duration_seconds || 0), 0),
    created_at: project.created_at || new Date().toISOString(),
    updated_at: new Date().toISOString(),
    size_bytes: sizeBytes,
  };
}

/** Stable audio key — the audio blob sits beside its project + surah. */
function audioKey(fileName: string, surahNumber: number): string {
  return `${fileName}${KEY_SEP}${surahNumber}`;
}

// ── Projects ──────────────────────────────────────────────────────────────────

export async function vaultSave(file_name: string, project: AlignerProject): Promise<string> {
  const db = await openDb();
  await asPromise(tx(db, PROJECTS, 'readwrite').put({ file_name, data: project }));
  const json = JSON.stringify(project);
  return json.length;
}

/**
 * Mirrors session audio (blob:/data: URLs) into the audio store so an
 * opened project keeps playing after a page reload. Same-size audio is
 * skipped — only the first appearance of each blob performs a write.
 */
export async function persistProjectAudio(file_name: string, surahs: SurahItem[]): Promise<void> {
  for (const s of surahs || []) {
    const url = typeof s.audio_url === 'string' ? s.audio_url : '';
    if (!/^(blob|data):/.test(url)) continue;
    const key = audioKey(file_name, s.surah_number);
    try {
      const blob = await (await fetch(url)).blob();
      if (!blob.size || blob.size > 512 * 1024 * 1024) continue;
      const sig = `${key}:${blob.size}`;
      if (audioPersisted.has(sig)) continue;
      const db = await openDb();
      await asPromise(tx(db, AUDIO, 'readwrite').put({ key, blob, name: s.audio_file || 'audio', size: blob.size }));
      audioPersisted.add(sig);
    } catch {
      // quota / fetch failure — timings still persist
    }
  }
}

export async function vaultList(): Promise<ProjectSummary[]> {
  const db = await openDb();
  const rows = await asPromise<any[]>(tx(db, PROJECTS, 'readonly').getAll());
  return rows
    .map(row => ({ row, size: (() => { try { return JSON.stringify(row.data).length; } catch { return 0; } })() }))
    .map(({ row, size }) => buildSummary(row.data, row.file_name, size))
    .sort((a, b) => (a.updated_at < b.updated_at ? 1 : -1));
}

export async function vaultLoad(file_name: string): Promise<{ project: AlignerProject; audio: Map<number, Blob> } | null> {
  const db = await openDb();
  const row = await asPromise<any>(tx(db, PROJECTS, 'readonly').get(file_name));
  if (!row || !row.data) return null;
  // Rehydrate per-surah audio blobs stored beside this project
  const audio = new Map<number, Blob>();
  try {
    const all = await asPromise<any[]>(tx(db, AUDIO, 'readonly').getAll());
    const prefix = `${file_name}${KEY_SEP}`;
    for (const r of all) {
      if (typeof r.key !== 'string' || !r.key.startsWith(prefix) || !r.blob) continue;
      const num = parseInt(r.key.slice(prefix.length), 10);
      if (num > 0) audio.set(num, r.blob);
    }
  } catch { /* audio optional */ }
  return { project: row.data as AlignerProject, audio };
}

export async function vaultDelete(file_name: string): Promise<void> {
  const db = await openDb();
  const prefix = `${file_name}${KEY_SEP}`;
  await asPromise(tx(db, PROJECTS, 'readwrite').delete(file_name));
  const all = await asPromise<any[]>(tx(db, AUDIO, 'readonly').getAllKeys());
  for (const k of all) {
    if (typeof k === 'string' && k.startsWith(prefix)) {
      await asPromise(tx(db, AUDIO, 'readwrite').delete(k));
    }
  }
}

export async function vaultDuplicate(file_name: string): Promise<string | null> {
  const db = await openDb();
  const row = await asPromise<any>(tx(db, PROJECTS, 'readonly').get(file_name));
  if (!row?.data) return null;
  const base = (row.file_name || 'project.qproj').replace(/\.qproj$/i, '');
  let target = `${base} Copy.qproj`;
  let n = 2;
  const existing = new Set(await asPromise<any[]>(tx(db, PROJECTS, 'readonly').getAllKeys()));
  while (existing.has(target)) target = `${base} Copy ${n++}.qproj`;
  const copy: AlignerProject = JSON.parse(JSON.stringify(row.data));
  copy.file_name = target;
  copy.project_name = target.replace(/\.qproj$/i, '');
  copy.updated_at = new Date().toISOString();
  await asPromise(tx(db, PROJECTS, 'readwrite').put({ file_name: target, data: copy }));
  return target;
}

export function clearAudioPersistenceCache(): void {
  audioPersisted.clear();
}
