import type { CloudReciterProject, CloudProjectItem, AlignerProject, AyahItem, SurahItem, AlignedWord, AyahSegment } from '../types/aligner';
import { projectStore } from './projectStore';
import { isTauriEnvironment, createProject, saveProject, resolveAudioSourceUrl } from './api';
import { vaultSave, safeProjectFileName } from './projectVault';
import { uploadFiles } from '@huggingface/hub';
import { exportCanonicalJson } from './exporters';

const STORAGE_KEY_REPO = 'quran_hf_dataset_repo';
const STORAGE_KEY_TOKEN = 'quran_hf_access_token';
const STORAGE_KEY_CATALOG = 'quran_hf_catalog_cache';
export const DEFAULT_HF_REPO = 'TheGreatQuran/Quran-recite2text';

import { getSurahMeta } from '../data/quranMetadata';
export { getSurahMeta };

/** Normalizes full URLs or raw "username/repo" inputs */
export function normalizeHfRepoInput(input: string): string {
  let cleaned = input.trim();
  if (!cleaned) return DEFAULT_HF_REPO;
  cleaned = cleaned.replace(/\/+$/, '');
  const urlMatch = cleaned.match(/huggingface\.co\/datasets\/([^/?#]+\/[^/?#]+)/i);
  if (urlMatch && urlMatch[1]) return urlMatch[1];
  const genericMatch = cleaned.match(/huggingface\.co\/([^/?#]+\/[^/?#]+)/i);
  if (genericMatch && genericMatch[1]) return genericMatch[1];
  return cleaned;
}

export function getHfRepo(): string {
  try {
    const val = localStorage.getItem(STORAGE_KEY_REPO);
    if (!val || !val.trim() || val === 'Iam-Muslim/Quran-Recitations-Dataset' || val === 'Iam-Muslim/QuranReciteToText') {
      return DEFAULT_HF_REPO;
    }
    return val.trim();
  } catch {
    return DEFAULT_HF_REPO;
  }
}

export function setHfRepo(repo: string): void {
  try {
    const normalized = normalizeHfRepoInput(repo);
    localStorage.setItem(STORAGE_KEY_REPO, normalized);
  } catch {}
}

export function getHfToken(): string {
  try {
    return localStorage.getItem(STORAGE_KEY_TOKEN) || '';
  } catch {
    return '';
  }
}

export function setHfToken(token: string): void {
  try {
    localStorage.setItem(STORAGE_KEY_TOKEN, token.trim());
  } catch {}
}

export function getHfHeaders(): HeadersInit {
  const token = getHfToken();
  const headers: Record<string, string> = {};
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }
  return headers;
}

export function getHfBaseUrl(): string {
  const repo = getHfRepo();
  return `https://huggingface.co/datasets/${repo}/resolve/main`;
}

/**
 * Fetches the list of Reciter Projects from the Hugging Face dataset.
 *
 * Priority 1: Reads `projects.json` (or `manifest.json` / `catalog.json`) at repository root.
 * Priority 2: Auto-discovers reciter directories matching `<folder>/json/<surah>.json` via Tree API.
 * Priority 3: Cached projects from localStorage.
 * Note: Never returns deceptive hardcoded dummy data.
 */
export async function fetchCloudProjects(repoOverride?: string): Promise<CloudReciterProject[]> {
  const repo = normalizeHfRepoInput(repoOverride || getHfRepo());
  if (!repo) return [];
  const baseUrl = `https://huggingface.co/datasets/${repo}/resolve/main`;
  const headers = getHfHeaders();

  // 1. Try reading projects.json or manifest.json or catalog.json directly
  const manifestCandidates = ['projects.json', 'manifest.json', 'catalog.json'];
  for (const candidate of manifestCandidates) {
    try {
      const res = await fetch(`${baseUrl}/${candidate}`, { cache: 'no-cache', headers });
      if (res.ok) {
        const data = await res.json();
        if (Array.isArray(data) && data.length > 0) {
          const projects: CloudReciterProject[] = data.map((item, idx) => {
            const folder = item.folder || item.reciter_folder || item.id || `reciters/${item.reciter || idx}`;
            const reciterName = item.reciter || item.project_name || 'Reciter';
            return {
              id: item.id || `proj_${idx}`,
              project_name: item.project_name || reciterName,
              reciter: reciterName,
              reciter_english: item.reciter_english || item.reciter,
              riwayah: item.riwayah || 'Hafs',
              status: item.status === 'verified' ? 'verified' : 'needs_review',
              folder: folder.replace(/^\/+|\/+$/g, ''),
              audio_format: item.audio_format || 'mp3',
              available_surahs: Array.isArray(item.available_surahs) ? item.available_surahs : (item.surah_number ? [item.surah_number] : undefined),
              total_surahs: item.total_surahs || (Array.isArray(item.available_surahs) ? item.available_surahs.length : undefined),
              description: item.description || '',
              updated_at: item.updated_at,
            };
          });

          try {
            localStorage.setItem(STORAGE_KEY_CATALOG, JSON.stringify(projects));
          } catch {}
          return projects;
        }
      }
    } catch (err) {
      console.debug(`Manifest ${candidate} fetch skipped:`, err);
    }
  }

  // 2. Auto-Discovery: query Hugging Face Tree API to discover reciter folders
  try {
    const treeApiUrl = `https://huggingface.co/api/datasets/${repo}/tree/main?recursive=true`;
    const treeRes = await fetch(treeApiUrl, { headers });
    if (treeRes.ok) {
      const files: Array<{ path: string; type: string; size?: number }> = await treeRes.json();

      // Group files by reciter directory: looks for pattern "<folder>/json/<surah>.json"
      const reciterMap = new Map<string, { surahs: Set<number>; audioExt: string }>();

      for (const file of files) {
        if (file.type !== 'file') continue;
        const p = file.path.replace(/\\/g, '/');

        // Check if inside a json/ folder: e.g. "Mishary_Alafasy/json/001.json" or "reciters/Husary/json/112.json"
        const jsonMatch = p.match(/^(?:reciters\/)?([^/]+)\/json\/(\d+)\.json$/i);
        if (jsonMatch) {
          const reciterKey = jsonMatch[1];
          const surahNum = parseInt(jsonMatch[2], 10);
          if (!reciterMap.has(reciterKey)) {
            reciterMap.set(reciterKey, { surahs: new Set(), audioExt: 'mp3' });
          }
          if (surahNum >= 1 && surahNum <= 114) {
            reciterMap.get(reciterKey)!.surahs.add(surahNum);
          }
        }

        // Check audio extension
        const audioMatch = p.match(/^(?:reciters\/)?([^/]+)\/audio\/\d+\.([a-z0-9]+)$/i);
        if (audioMatch) {
          const reciterKey = audioMatch[1];
          const ext = audioMatch[2].toLowerCase();
          if (reciterMap.has(reciterKey)) {
            reciterMap.get(reciterKey)!.audioExt = ext;
          }
        }
      }

      if (reciterMap.size > 0) {
        const discovered: CloudReciterProject[] = [];
        for (const [folderName, info] of reciterMap.entries()) {
          const cleanReciter = folderName.replace(/[-_]+/g, ' ');
          const surahList = Array.from(info.surahs).sort((a, b) => a - b);
          discovered.push({
            id: folderName,
            project_name: cleanReciter,
            reciter: cleanReciter,
            reciter_english: cleanReciter,
            riwayah: 'Hafs',
            status: 'verified',
            folder: files.some(f => f.path.startsWith(`reciters/${folderName}/`)) ? `reciters/${folderName}` : folderName,
            audio_format: info.audioExt || 'mp3',
            available_surahs: surahList,
            total_surahs: surahList.length,
            description: `Auto-discovered dataset project with ${surahList.length} surahs.`,
          });
        }
        if (discovered.length > 0) return discovered;
      }
    }
  } catch (treeErr) {
    console.debug('HF tree API discovery error:', treeErr);
  }

  // 3. Fallback to cached catalog in localStorage if offline
  try {
    const cached = localStorage.getItem(STORAGE_KEY_CATALOG);
    if (cached) {
      const parsed = JSON.parse(cached);
      if (Array.isArray(parsed) && parsed.length > 0) return parsed;
    }
  } catch {}

  // 4. Return empty array - do NOT show fake data from EveryAyah
  return [];
}

/** Backward compatibility shim for legacy callers */
export async function fetchCloudCatalog(): Promise<CloudProjectItem[]> {
  const reciters = await fetchCloudProjects();
  return reciters.map(r => ({
    ...r,
    surah_number: r.available_surahs?.[0] || 1,
    surah_name_arabic: getSurahMeta(r.available_surahs?.[0] || 1).arabic,
    surah_name_english: getSurahMeta(r.available_surahs?.[0] || 1).english,
    duration_seconds: 0,
    total_ayahs: getSurahMeta(r.available_surahs?.[0] || 1).totalAyahs,
    project_url: `${getHfBaseUrl()}/${r.folder}/json/001.json`,
    audio_url: `${getHfBaseUrl()}/${r.folder}/audio/001.${r.audio_format || 'mp3'}`,
  }));
}

/**
 * Builds the URL for a Surah JSON and its corresponding audio file in the dataset.
 */
export function getCloudSurahUrls(project: CloudReciterProject | CloudProjectItem, surahNumber: number) {
  const baseUrl = getHfBaseUrl();
  const folder = (project.folder || project.id || 'reciters').replace(/^\/+|\/+$/g, '');
  const padded = String(surahNumber).padStart(3, '0');
  const format = project.audio_format || 'mp3';
  const token = getHfToken();
  const tokenQuery = token ? `?token=${encodeURIComponent(token)}` : '';

  return {
    jsonUrl: `${baseUrl}/${folder}/json/${padded}.json`,
    audioUrl: `${baseUrl}/${folder}/audio/${padded}.${format}${tokenQuery}`,
    fallbackJsonUrl: `${baseUrl}/${folder}/json/${surahNumber}.json`,
    fallbackAudioUrl: `${baseUrl}/${folder}/audio/${surahNumber}.${format}${tokenQuery}`,
  };
}

export function normalizeRawAyahsToStudio(rawAyahs: any[], surahNumber: number): AyahItem[] {
  if (!Array.isArray(rawAyahs)) return [];
  return rawAyahs.map((a: any) => {
    if (Array.isArray(a.segments) && a.segments.length > 0) {
      return a as AyahItem;
    }

    const phrasesSource: any[] | null = Array.isArray(a.phrases) && a.phrases.length > 0 ? a.phrases : null;

    if (phrasesSource) {
      const segments: AyahSegment[] = phrasesSource.map((p: any, pIdx: number) => {
        const pWords: any[] = Array.isArray(p.words) ? p.words : [];
        const words: AlignedWord[] = pWords.map((w: any, idx: number) => ({
          word: w.text || w.word || '',
          location: `${surahNumber}:${a.ayah || 1}:${w.w || idx + 1}`,
          start: typeof w.start === 'number' ? w.start : 0,
          end: typeof w.end === 'number' ? w.end : 0,
          score: typeof w.score === 'number' ? w.score : 1,
          is_repetition: !!(w.is_repetition || p.is_repetition),
          phonemes: w.phonemes || [],
        }));
        const pStart = words.length > 0 ? words[0].start : (p.start ?? 0);
        const pEnd = words.length > 0 ? words[words.length - 1].end : (p.end ?? 0);
        return {
          segment: p.phrase || p.segment || pIdx + 1,
          start: pStart,
          end: pEnd,
          is_repetition: !!p.is_repetition,
          words,
        };
      });

      const aStart = segments.length > 0 ? segments[0].start : (a.start ?? 0);
      const aEnd = segments.length > 0 ? segments[segments.length - 1].end : (a.end ?? 0);

      return {
        ayah: a.ayah || 1,
        start: aStart,
        end: aEnd,
        is_repetition: !!a.is_repetition,
        repeated_ranges: a.repeated_ranges,
        repeated_text: a.repeated_text,
        segments,
      };
    }

    const rawWords: any[] = Array.isArray(a.words) ? a.words : [];
    const words: AlignedWord[] = rawWords.map((w: any, idx: number) => ({
      word: w.text || w.word || '',
      location: `${surahNumber}:${a.ayah || 1}:${w.w || idx + 1}`,
      start: typeof w.start === 'number' ? w.start : 0,
      end: typeof w.end === 'number' ? w.end : 0,
      score: typeof w.score === 'number' ? w.score : 1,
      is_repetition: !!w.is_repetition,
      phonemes: w.phonemes || [],
    }));

    const aStart = words.length > 0 ? words[0].start : (a.start ?? 0);
    const aEnd = words.length > 0 ? words[words.length - 1].end : (a.end ?? 0);

    return {
      ayah: a.ayah || 1,
      start: aStart,
      end: aEnd,
      is_repetition: !!a.is_repetition,
      repeated_ranges: a.repeated_ranges,
      repeated_text: a.repeated_text,
      segments: [
        {
          segment: 1,
          start: aStart,
          end: aEnd,
          is_repetition: !!a.is_repetition,
          words,
        },
      ],
    };
  });
}

/**
 * Opens a Cloud Project in Studio mode for a specific Surah.
 * Fetches ONLY the Surah's tiny JSON (~10-30 KB) which includes precomputed waveform peaks.
 * Zero audio bytes are downloaded upfront for waveform rendering.
 */
export async function openCloudSurahInStudio(
  project: CloudReciterProject | CloudProjectItem, 
  surahNumber: number = 1
): Promise<boolean> {
  try {
    const urls = getCloudSurahUrls(project, surahNumber);
    const headers = getHfHeaders();

    let rawData: any = null;

    // 1. Fetch JSON (try padded 001.json then unpadded 1.json)
    try {
      let res = await fetch(urls.jsonUrl, { headers });
      if (!res.ok) {
        res = await fetch(urls.fallbackJsonUrl, { headers });
      }
      if (res.ok) {
        rawData = await res.json();
      }
    } catch (fetchErr) {
      console.warn('Failed to fetch surah JSON directly:', fetchErr);
    }

    const meta = getSurahMeta(surahNumber);
    const reciterName = project.reciter || project.project_name || 'Reciter';
    const riwayah = project.riwayah || 'Hafs';

    let alignerProject: AlignerProject;

    if (rawData && Array.isArray(rawData.surahs) && rawData.surahs.length > 0) {
      // The file is already a full AlignerProject export
      alignerProject = rawData;
      if (!alignerProject.surahs[0].audio_url) {
        alignerProject.surahs[0].audio_url = urls.audioUrl;
      }
    } else {
      // Clean standard Surah timing structure
      const ayahs: AyahItem[] = normalizeRawAyahsToStudio(rawData?.ayahs, surahNumber);
      const peaks: number[] = Array.isArray(rawData?.peaks) ? rawData.peaks : [];
      const duration = Number(rawData?.duration || rawData?.duration_seconds) || 0;

      alignerProject = {
        project_name: (project.project_name || reciterName).trim(),
        reciter: reciterName,
        app_version: '2.0.0',
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
        settings: {
          snapping_tolerance_ms: 25,
          confidence_warning_threshold: 0.85,
          auto_save_interval_s: 30,
          reciter_name: reciterName,
          riwayah,
          cloud_origin: true,
          cloud_repo: getHfRepo(),
          cloud_folder: (project.folder || project.id || '').replace(/^\/+|\/+$/g, ''),
          cloud_id: project.id,
        },
        surahs: [
          {
            surah_number: surahNumber,
            surah_name_arabic: rawData?.surah_name_arabic || meta.arabic,
            surah_name_english: rawData?.surah_name_english || meta.english,
            audio_url: urls.audioUrl,
            waveform_url: rawData?.waveform_url || '',
            peaks: peaks.length > 0 ? peaks : undefined,
            audio_duration_seconds: duration,
            status: rawData?.status || project.status || 'verified',
            intro: rawData?.intro || undefined,
            ayahs,
          }
        ]
      };
    }

    projectStore.loadProject(alignerProject);
    projectStore.currentTab.value = 'studio';
    return true;
  } catch (err) {
    console.error('Failed to open cloud surah in studio:', err);
    return false;
  }
}

/** Backward compatibility shim for legacy callers */
export async function openCloudProjectInStudio(item: CloudProjectItem): Promise<boolean> {
  const surahNum = item.surah_number || item.available_surahs?.[0] || 1;
  return openCloudSurahInStudio(item, surahNum);
}

/**
 * Imports a Cloud Reciter Surah into the user's Local Projects workspace
 * (IndexedDB vault on Web, or local .qproj on Desktop Tauri)
 */
export async function importCloudSurahToLocal(
  project: CloudReciterProject | CloudProjectItem, 
  surahNumber: number = 1
): Promise<boolean> {
  try {
    const urls = getCloudSurahUrls(project, surahNumber);
    const headers = getHfHeaders();
    let rawData: any = null;

    try {
      let res = await fetch(urls.jsonUrl, { headers });
      if (!res.ok) res = await fetch(urls.fallbackJsonUrl, { headers });
      if (res.ok) rawData = await res.json();
    } catch {}

    const meta = getSurahMeta(surahNumber);
    const reciterName = project.reciter || project.project_name || 'Reciter';
    const riwayah = project.riwayah || 'Hafs';

    const projectData: AlignerProject = (rawData && Array.isArray(rawData.surahs)) ? rawData : {
      project_name: (project.project_name || reciterName).trim(),
      reciter: reciterName,
      app_version: '2.0.0',
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
      settings: {
        snapping_tolerance_ms: 25,
        confidence_warning_threshold: 0.85,
        auto_save_interval_s: 30,
        reciter_name: reciterName,
        riwayah,
        cloud_origin: true,
        cloud_repo: getHfRepo(),
        cloud_folder: (project.folder || project.id || '').replace(/^\/+|\/+$/g, ''),
        cloud_id: project.id,
      },
      surahs: [
        {
          surah_number: surahNumber,
          surah_name_arabic: rawData?.surah_name_arabic || meta.arabic,
          surah_name_english: rawData?.surah_name_english || meta.english,
          audio_url: urls.audioUrl,
          waveform_url: rawData?.waveform_url || '',
          peaks: rawData?.peaks || undefined,
          audio_duration_seconds: Number(rawData?.duration || rawData?.duration_seconds) || 0,
          status: rawData?.status || project.status || 'verified',
          intro: rawData?.intro || undefined,
          ayahs: normalizeRawAyahsToStudio(rawData?.ayahs, surahNumber),
        }
      ]
    };

    const fileName = safeProjectFileName(projectData.project_name);
    projectData.file_name = fileName;

    if (isTauriEnvironment()) {
      await createProject(projectData.project_name, projectData);
      await saveProject(fileName, projectData);
    } else {
      await vaultSave(fileName, projectData);
    }

    return true;
  } catch (err) {
    console.error('Failed to import cloud surah to local:', err);
    return false;
  }
}

/**
 * Opens a Hugging Face Reciter Project:
 * 1. Automatically copies/saves the project to the user's Local Projects vault (or desktop .qproj)
 * 2. Populates all available surahs from the dataset manifest
 * 3. Immediately streams audio and loads the word timings
 * 4. Navigates into Studio mode with Surah selection ready
 */
export async function openAndImportHfProject(
  project: CloudReciterProject | CloudProjectItem
): Promise<boolean> {
  try {
    const item = project as any;
    const rawSurahs: number[] = Array.isArray(item.available_surahs) && item.available_surahs.length > 0
      ? item.available_surahs.map((n: any) => Number(n))
      : (typeof item.surah_number === 'number' ? [Number(item.surah_number)] : [1]);

    const availableSurahs: number[] = Array.from(new Set<number>(rawSurahs)).sort((a: number, b: number) => a - b);
    const firstSurahNum: number = availableSurahs[0] || 1;

    const reciterName = project.reciter || project.project_name || 'Reciter';
    const riwayah = project.riwayah || 'Hafs';
    const folder = (project.folder || project.id || '').replace(/^\/+|\/+$/g, '');

    // 1. Fetch timing JSON for active surah
    const firstUrls = getCloudSurahUrls(project, firstSurahNum);
    const headers = getHfHeaders();
    let firstRawData: any = null;

    try {
      let res = await fetch(firstUrls.jsonUrl, { headers });
      if (!res.ok) res = await fetch(firstUrls.fallbackJsonUrl, { headers });
      if (res.ok) firstRawData = await res.json();
    } catch (e) {
      console.warn('Initial surah timing fetch warning:', e);
    }

    const firstMeta = getSurahMeta(firstSurahNum);
    const rawAyahsSource = Array.isArray(firstRawData) 
      ? firstRawData 
      : (firstRawData?.ayahs || firstRawData?.surahs?.[0]?.ayahs || []);
    const firstAyahs: AyahItem[] = normalizeRawAyahsToStudio(rawAyahsSource, firstSurahNum);
    const firstPeaks: number[] = Array.isArray(firstRawData?.peaks) 
      ? firstRawData.peaks 
      : (Array.isArray(firstRawData?.waveform) ? firstRawData.waveform : []);
    const firstDuration = Number(firstRawData?.duration || firstRawData?.duration_seconds || firstRawData?.total_duration) || 0;

    const surahItems: SurahItem[] = [
      {
        surah_number: firstSurahNum,
        surah_name_arabic: firstRawData?.surah_name_arabic || firstMeta.arabic,
        surah_name_english: firstRawData?.surah_name_english || firstMeta.english,
        audio_url: firstUrls.audioUrl,
        waveform_url: firstRawData?.waveform_url || '',
        peaks: firstPeaks.length > 0 ? firstPeaks : undefined,
        audio_duration_seconds: firstDuration,
        status: firstRawData?.status || project.status || 'verified',
        intro: firstRawData?.intro || undefined,
        ayahs: firstAyahs,
      }
    ];

    // Add entries for all other available surahs in the dataset
    for (const sNum of availableSurahs.slice(1)) {
      const sUrls = getCloudSurahUrls(project, sNum);
      const meta = getSurahMeta(sNum);
      surahItems.push({
        surah_number: sNum,
        surah_name_arabic: meta.arabic,
        surah_name_english: meta.english,
        audio_url: sUrls.audioUrl,
        waveform_url: '',
        peaks: undefined,
        audio_duration_seconds: 0,
        status: project.status || 'verified',
        ayahs: [],
      });
    }

    const displayName = (project.project_name || reciterName).trim();
    const projectData: AlignerProject = {
      project_name: displayName,
      reciter: reciterName,
      app_version: '2.0.0',
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
      settings: {
        snapping_tolerance_ms: 25,
        confidence_warning_threshold: 0.85,
        auto_save_interval_s: 30,
        reciter_name: reciterName,
        riwayah,
        cloud_origin: true,
        cloud_repo: getHfRepo(),
        cloud_folder: folder,
        cloud_id: project.id,
      },
      surahs: surahItems,
    };

    const fileName = safeProjectFileName(projectData.project_name);
    projectData.file_name = fileName;

    // Automatically copy into local projects
    if (isTauriEnvironment()) {
      await createProject(projectData.project_name, projectData);
      await saveProject(fileName, projectData);
    } else {
      await vaultSave(fileName, projectData);
    }

    // Load into studio workspace
    projectStore.loadProject(projectData);
    projectStore.selectSurah(firstSurahNum);
    projectStore.currentTab.value = 'studio';
    return true;
  } catch (err) {
    console.error('Failed to open and import Hugging Face project:', err);
    return false;
  }
}

/** Backward compatibility shim */
export async function importCloudProjectToLocal(item: CloudProjectItem): Promise<boolean> {
  const surahNum = item.surah_number || item.available_surahs?.[0] || 1;
  return importCloudSurahToLocal(item, surahNum);
}

export interface UploadCloudResult {
  success: boolean;
  folder: string;
  collision?: boolean;
  existingProject?: CloudReciterProject;
  suggestedFolder?: string;
  error?: string;
  uploadedFiles?: string[];
}

/**
 * Checks if a project folder already exists on the Hugging Face dataset.
 * Returns suggested unique folder name if collision occurs.
 */
export async function checkCloudProjectCollision(
  folder: string,
  repoName?: string
): Promise<{ collision: boolean; existing?: CloudReciterProject; suggestedFolder: string }> {
  const repo = normalizeHfRepoInput(repoName || getHfRepo());
  const cleanFolder = folder.replace(/^\/+|\/+$/g, '');
  try {
    const projects = await fetchCloudProjects(repo);
    const match = projects.find(p => p.folder?.toLowerCase() === cleanFolder.toLowerCase() || p.id?.toLowerCase() === cleanFolder.toLowerCase());

    if (!match) {
      return { collision: false, suggestedFolder: cleanFolder };
    }

    let n = 2;
    let candidate = `${cleanFolder}_${n}`;
    while (projects.some(p => p.folder?.toLowerCase() === candidate.toLowerCase())) {
      n++;
      candidate = `${cleanFolder}_${n}`;
    }

    return { collision: true, existing: match, suggestedFolder: candidate };
  } catch {
    return { collision: false, suggestedFolder: cleanFolder };
  }
}

/**
 * Resolves the audio Blob for a Surah whether stored in memory, session blob URL,
 * embedded base64, or local asset path.
 */
export async function getSurahAudioBlob(
  surah: SurahItem
): Promise<{ blob: Blob; ext: string; size: number } | null> {
  // 1. Embedded base64
  if (surah.audio_embedded?.base64) {
    try {
      const mime = surah.audio_embedded.mime || 'audio/mpeg';
      const ext = mime.includes('mp4') || mime.includes('m4a') ? 'm4a' : 'mp3';
      const binary = atob(surah.audio_embedded.base64);
      const bytes = new Uint8Array(binary.length);
      for (let i = 0; i < binary.length; i++) {
        bytes[i] = binary.charCodeAt(i);
      }
      const blob = new Blob([bytes], { type: mime });
      return { blob, ext, size: blob.size };
    } catch {}
  }

  // 2. Fetch via resolved URL
  const fetchUrl = resolveAudioSourceUrl(surah);
  if (!fetchUrl) return null;

  try {
    const res = await fetch(fetchUrl);
    if (!res.ok) return null;
    const blob = await res.blob();
    if (!blob.size) return null;
    const type = (blob.type || '').toLowerCase();
    const ext = type.includes('m4a') || type.includes('mp4')
      ? 'm4a'
      : type.includes('wav')
      ? 'wav'
      : type.includes('ogg')
      ? 'ogg'
      : 'mp3';
    return { blob, ext, size: blob.size };
  } catch {
    return null;
  }
}

/**
 * Checks how many Surahs in a project have local/reachable audio ready for upload.
 */
export async function inspectProjectAudioReachability(project: AlignerProject): Promise<{
  reachableCount: number;
  totalBytes: number;
  surahsWithAudio: number[];
}> {
  let reachableCount = 0;
  let totalBytes = 0;
  const surahsWithAudio: number[] = [];

  for (const s of project.surahs || []) {
    if (s.audio_embedded?.base64) {
      reachableCount++;
      const estBytes = Math.round((s.audio_embedded.base64.length * 3) / 4);
      totalBytes += estBytes;
      surahsWithAudio.push(s.surah_number);
      continue;
    }

    const url = resolveAudioSourceUrl(s);
    if (
      url &&
      (url.startsWith('blob:') ||
        url.startsWith('data:') ||
        url.startsWith('http://asset.localhost') ||
        url.startsWith('http://127.0.0.1') ||
        url.startsWith('http://localhost'))
    ) {
      reachableCount++;
      surahsWithAudio.push(s.surah_number);
    }
  }

  return { reachableCount, totalBytes, surahsWithAudio };
}

export interface UploadHfProjectOptions {
  overwrite?: boolean;
  targetFolder?: string;
  commitMessage?: string;
  repo?: string;
  token?: string;
  uploadAudio?: boolean;
  onProgress?: (status: string) => void;
}

/**
 * Uploads a local recitation project to the Hugging Face dataset.
 *
 * Rules:
 * 1. If project was imported from Cloud (has settings.cloud_origin and matching cloud_folder),
 *    it updates/overwrites that reciter's project folder in the cloud dataset.
 * 2. If it is a new project, it checks if a project with the same folder already exists.
 *    If there is a collision and `overwrite` is false, it returns collision details and a suggested unique folder.
 * 3. Commits all Surah JSON files (`<folder>/json/<surah>.json`) and updates `projects.json` atomically.
 * 4. Optionally uploads audio files (`<folder>/audio/<surah>.mp3`) if requested.
 */
export async function uploadProjectToHfDataset(
  project: AlignerProject,
  options: UploadHfProjectOptions = {}
): Promise<UploadCloudResult> {
  const repo = normalizeHfRepoInput(options.repo || getHfRepo());
  const token = (options.token || getHfToken()).trim();

  if (!token) {
    return {
      success: false,
      folder: '',
      error: 'Hugging Face Access Token (with Write permission) is required. Please provide a token in Dataset Settings.',
    };
  }

  options.onProgress?.('Verifying destination repository...');

  // 1. Determine target folder
  let folder = options.targetFolder;
  const isCloudOrigin = Boolean(project.settings?.cloud_origin && project.settings?.cloud_folder);

  if (!folder) {
    if (isCloudOrigin && project.settings?.cloud_folder) {
      folder = project.settings.cloud_folder;
    } else {
      const rawName = project.reciter || project.settings?.reciter_name || project.project_name || 'Reciter';
      const sanitized = rawName.replace(/[^a-zA-Z0-9_\u0600-\u06FF\s-]/g, '').trim().replace(/\s+/g, '_');
      folder = `reciters/${sanitized || 'Reciter'}`;
    }
  }
  folder = folder.replace(/^\/+|\/+$/g, '');

  // 2. Collision Check: If new project and not explicit overwrite
  if (!options.overwrite && !isCloudOrigin) {
    options.onProgress?.('Checking project name availability...');
    const col = await checkCloudProjectCollision(folder, repo);
    if (col.collision) {
      return {
        success: false,
        collision: true,
        folder,
        existingProject: col.existing,
        suggestedFolder: col.suggestedFolder,
        error: `A recitation project already exists in folder "${folder}".`,
      };
    }
  }

  // 3. Prepare files for commit
  try {
    const filesToUpload: Array<{ path: string; content: Blob }> = [];

    // A. Surah timing JSON files
    options.onProgress?.('Serializing canonical Surah JSON timings...');
    for (const s of project.surahs || []) {
      const padded = String(s.surah_number).padStart(3, '0');
      const jsonStr = exportCanonicalJson(s, true);
      const surahBlob = new Blob([jsonStr], { type: 'application/json' });
      filesToUpload.push({
        path: `${folder}/json/${padded}.json`,
        content: surahBlob,
      });

      // B. Optional Audio File Upload
      if (options.uploadAudio) {
        options.onProgress?.(`Extracting audio for Surah ${padded}...`);
        const audioInfo = await getSurahAudioBlob(s);
        if (audioInfo && audioInfo.blob.size > 0) {
          filesToUpload.push({
            path: `${folder}/audio/${padded}.${audioInfo.ext}`,
            content: audioInfo.blob,
          });
          // Update surah audio_url to the new cloud resolve URL
          s.audio_url = `https://huggingface.co/datasets/${repo}/resolve/main/${folder}/audio/${padded}.${audioInfo.ext}`;
        }
      }
    }

    // C. Root Manifest (projects.json)
    options.onProgress?.('Fetching repository manifest (projects.json)...');
    let currentManifest: CloudReciterProject[] = [];
    try {
      const manifestUrl = `https://huggingface.co/datasets/${repo}/resolve/main/projects.json`;
      const res = await fetch(manifestUrl, { headers: { Authorization: `Bearer ${token}` } });
      if (res.ok) {
        const data = await res.json();
        if (Array.isArray(data)) currentManifest = data;
      }
    } catch {}

    const reciterName = project.reciter || project.settings?.reciter_name || project.project_name || 'Reciter';
    const surahNumbers = (project.surahs || []).map(s => s.surah_number).sort((a, b) => a - b);
    const existingIdx = currentManifest.findIndex(
      p => p.folder?.toLowerCase() === folder.toLowerCase() || p.id?.toLowerCase() === folder.toLowerCase()
    );

    const hasAudioUploaded = filesToUpload.some(f => f.path.startsWith(`${folder}/audio/`));
    const audioExt = hasAudioUploaded ? 'mp3' : (existingIdx >= 0 ? currentManifest[existingIdx].audio_format || 'mp3' : 'mp3');

    const updatedEntry: CloudReciterProject = {
      id: folder.replace(/^reciters\//, ''),
      project_name: project.project_name,
      reciter: reciterName,
      reciter_english: project.settings?.reciter_name || reciterName,
      riwayah: project.settings?.riwayah || 'Hafs',
      folder,
      audio_format: audioExt,
      available_surahs: surahNumbers,
      total_surahs: surahNumbers.length,
      description: `Aligned via QuranRecite Studio with millisecond word boundaries.`,
      updated_at: new Date().toISOString(),
    };

    if (existingIdx >= 0) {
      currentManifest[existingIdx] = { ...currentManifest[existingIdx], ...updatedEntry };
    } else {
      currentManifest.push(updatedEntry);
    }

    const manifestBlob = new Blob([JSON.stringify(currentManifest, null, 2)], { type: 'application/json' });
    filesToUpload.push({
      path: 'projects.json',
      content: manifestBlob,
    });

    // 4. Commit to Hugging Face
    const commitMsg =
      options.commitMessage ||
      (isCloudOrigin
        ? `Update ${project.project_name} [QuranRecite Studio]`
        : `Add ${project.project_name} [QuranRecite Studio]`);

    options.onProgress?.(`Uploading ${filesToUpload.length} files to Hugging Face...`);

    await uploadFiles({
      repo: { type: 'dataset', name: repo },
      accessToken: token,
      commitTitle: commitMsg,
      files: filesToUpload,
    });

    // 5. Update project settings to mark as cloud origin so subsequent saves update it
    options.onProgress?.('Updating local sync metadata...');
    if (!project.settings) {
      project.settings = {
        snapping_tolerance_ms: 25,
        confidence_warning_threshold: 0.85,
        auto_save_interval_s: 30,
      };
    }
    project.settings.cloud_origin = true;
    project.settings.cloud_folder = folder;
    project.settings.cloud_repo = repo;
    project.settings.cloud_id = updatedEntry.id;
    projectStore.scheduleAutosave();

    return {
      success: true,
      folder,
      uploadedFiles: filesToUpload.map(f => f.path),
    };
  } catch (err: any) {
    console.error('Hugging Face upload error:', err);
    return {
      success: false,
      folder,
      error: err?.message || String(err) || 'Failed to upload files to Hugging Face.',
    };
  }
}

