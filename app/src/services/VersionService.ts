/**
 * Version & Auto-Updater Service
 * Directly adapted from QuranCaption's VersionService architecture.
 * Supports both Tauri v2 native updater and GitHub Releases API polling.
 */

import { ref } from 'vue';

export interface UpdateInfo {
  hasUpdate: boolean;
  latestVersion: string;
  currentVersion: string;
  changelog: string;
  downloadUrl?: string;
  releaseDate?: string;
}

export type UpdateState = 'idle' | 'checking' | 'available' | 'downloading' | 'installing' | 'done' | 'error';

const REPO_OWNER = 'Iam-Muslim';
const REPO_NAME = 'QuranReciteToText';
const APP_VERSION = '1.0.0';

class VersionService {
  public currentVersion = ref(APP_VERSION);
  public latestVersion = ref(APP_VERSION);
  public hasUpdate = ref(false);
  public changelog = ref('');
  public downloadUrl = ref('');
  public releaseDate = ref('');

  public updateState = ref<UpdateState>('idle');
  public downloadProgress = ref(0); // 0 - 100
  public downloadedBytes = ref(0);
  public totalBytes = ref(0);
  public updateError = ref('');

  private tauriUpdateInstance: any = null;

  /**
   * Initializes the version service on app mount and checks for updates.
   */
  public async init() {
    await this.resolveCurrentVersion();
    await this.checkForUpdates();
  }

  /**
   * Resolves current application version (from Tauri runtime or package version).
   */
  public async resolveCurrentVersion(): Promise<string> {
    try {
      if ((window as any).__TAURI_INTERNALS__) {
        const { getVersion } = await import('@tauri-apps/api/app');
        const ver = await getVersion();
        if (ver) {
          this.currentVersion.value = ver;
          return ver;
        }
      }
    } catch (e) {
      console.debug('Tauri app version check fallback:', e);
    }
    return this.currentVersion.value;
  }

  /**
   * Normalizes version strings ("v1.2.3" -> "1.2.3").
   */
  private normalizeVersion(v: string): string {
    if (!v) return '0.0.0';
    const s = v
      .trim()
      .replace(/^v/i, '')
      .replace(/^qc[-_]?/i, '');
    const parts = s
      .split(/[^0-9]+/)
      .filter(Boolean)
      .map((p) => p.replace(/^0+(?=\d)|^$/, (m) => m));
    if (parts.length >= 3) return parts.slice(0, 3).join('.');
    if (parts.length === 2) return ['0', parts[0], parts[1]].join('.');
    if (parts.length === 1) return ['0', '0', parts[0]].join('.');
    return '0.0.0';
  }

  /**
   * Compares two semantic version strings (-1 if a < b, 0 if equal, 1 if a > b).
   */
  private compareSemver(a: string, b: string): number {
    const pa = this.normalizeVersion(a).split('.').map(Number);
    const pb = this.normalizeVersion(b).split('.').map(Number);
    for (let i = 0; i < 3; i++) {
      if (pa[i] > pb[i]) return 1;
      if (pa[i] < pb[i]) return -1;
    }
    return 0;
  }

  /**
   * Checks for updates from Tauri updater plugin or GitHub Releases API.
   */
  public async checkForUpdates(): Promise<UpdateInfo> {
    this.updateState.value = 'checking';
    this.updateError.value = '';

    // 1. Try Tauri v2 native updater if running in Tauri
    try {
      if ((window as any).__TAURI_INTERNALS__) {
        // Dynamic import to support both web and desktop environments
        const updaterModule = await import('@tauri-apps/plugin-updater' as any);
        if (updaterModule && updaterModule.check) {
          const update = await updaterModule.check();
          if (update && update.available) {
            this.tauriUpdateInstance = update;
            this.hasUpdate.value = true;
            this.latestVersion.value = update.version;
            this.changelog.value = update.body || 'New improvements and bug fixes.';
            this.releaseDate.value = update.date || '';
            this.updateState.value = 'available';
            return {
              hasUpdate: true,
              latestVersion: update.version,
              currentVersion: this.currentVersion.value,
              changelog: this.changelog.value,
              releaseDate: this.releaseDate.value,
            };
          }
        }
      }
    } catch (err) {
      console.debug('Tauri native updater check skipped:', err);
    }

    // 2. Direct GitHub Releases API check (works everywhere)
    try {
      const res = await fetch(`https://api.github.com/repos/${REPO_OWNER}/${REPO_NAME}/releases/latest`, {
        headers: { Accept: 'application/vnd.github.v3+json' },
      });

      if (res.ok) {
        const release = await res.json();
        const tag = (release.tag_name || '').trim();
        const isNewer = this.compareSemver(tag, this.currentVersion.value) > 0;

        if (isNewer) {
          this.hasUpdate.value = true;
          this.latestVersion.value = tag.replace(/^v/i, '');
          this.changelog.value = release.body || 'New improvements and bug fixes.';
          this.downloadUrl.value = release.html_url || `https://github.com/${REPO_OWNER}/${REPO_NAME}/releases`;
          this.releaseDate.value = release.published_at || '';
          this.updateState.value = 'available';

          return {
            hasUpdate: true,
            latestVersion: this.latestVersion.value,
            currentVersion: this.currentVersion.value,
            changelog: this.changelog.value,
            downloadUrl: this.downloadUrl.value,
            releaseDate: this.releaseDate.value,
          };
        }
      }
    } catch (err: any) {
      console.warn('GitHub releases poll failed:', err);
    }

    this.hasUpdate.value = false;
    this.updateState.value = 'idle';
    return {
      hasUpdate: false,
      latestVersion: this.currentVersion.value,
      currentVersion: this.currentVersion.value,
      changelog: '',
    };
  }

  /**
   * Downloads and installs the update.
   * If running inside Tauri: downloads NSIS package silently and relaunches.
   * If in browser: opens the GitHub release download page.
   */
  public async downloadAndInstall(): Promise<void> {
    if (this.tauriUpdateInstance) {
      try {
        this.updateState.value = 'downloading';
        this.downloadProgress.value = 0;
        this.downloadedBytes.value = 0;
        this.totalBytes.value = 0;

        await this.tauriUpdateInstance.downloadAndInstall((event: any) => {
          if (event.event === 'Started') {
            this.totalBytes.value = event.data?.contentLength || 0;
            this.downloadedBytes.value = 0;
          } else if (event.event === 'Progress') {
            this.downloadedBytes.value += event.data?.chunkLength || 0;
            if (this.totalBytes.value > 0) {
              this.downloadProgress.value = Math.min(
                100,
                Math.round((this.downloadedBytes.value / this.totalBytes.value) * 100)
              );
            }
          } else if (event.event === 'Finished') {
            this.downloadProgress.value = 100;
            this.updateState.value = 'installing';
          }
        });

        this.updateState.value = 'done';

        // Seamless auto-restart after install
        setTimeout(async () => {
          try {
            const { relaunch } = await import('@tauri-apps/plugin-process' as any);
            await relaunch();
          } catch {
            window.location.reload();
          }
        }, 1200);
        return;
      } catch (err: any) {
        console.error('Tauri download and install error:', err);
        this.updateState.value = 'error';
        this.updateError.value = err?.message || 'Failed to download update.';
        return;
      }
    }

    // Fallback: open GitHub Release URL in browser
    const url = this.downloadUrl.value || `https://github.com/${REPO_OWNER}/${REPO_NAME}/releases/latest`;
    window.open(url, '_blank');
  }
}

export const versionService = new VersionService();
