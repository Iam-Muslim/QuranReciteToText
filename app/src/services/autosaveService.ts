import { ref } from 'vue';

export type SaveStatus = 'saved' | 'saving' | 'unsaved' | 'error';

export interface AutosaveOptions {
  checkIntervalMs?: number;
  retryDelayMs?: number;
  debounceMs?: number;
  saveFn: () => Promise<boolean>;
  canSavePredicate?: () => boolean;
}

export class AutosaveService {
  public isDirty = ref<boolean>(false);
  public isSaving = ref<boolean>(false);
  public lastSavedAt = ref<Date | null>(null);
  public saveStatus = ref<SaveStatus>('saved');

  private debounceMs: number;
  private saveFn: () => Promise<boolean>;
  private canSavePredicate?: () => boolean;

  private debounceTimer: ReturnType<typeof setTimeout> | null = null;
  private isFlushing: boolean = false;

  constructor(options: AutosaveOptions) {
    this.debounceMs = options.debounceMs ?? 1500;
    this.saveFn = options.saveFn;
    this.canSavePredicate = options.canSavePredicate;

    this.initLifecycle();
  }

  private initLifecycle(): void {
    if (typeof window === 'undefined') return;

    window.addEventListener('beforeunload', (e) => {
      if (this.isDirty.value) {
        void this.flush();
        e.preventDefault();
        e.returnValue = '';
      }
    });

    document.addEventListener('visibilitychange', () => {
      if (document.visibilityState === 'hidden' && this.isDirty.value) {
        void this.flush();
      }
    });

    window.addEventListener('blur', () => {
      if (this.isDirty.value) {
        void this.flush();
      }
    });

    // iOS Safari / WebKit lifecycle: pagehide is the only reliable teardown event
    window.addEventListener('pagehide', () => {
      if (this.isDirty.value) {
        void this.flush();
      }
    });
  }

  public markDirty(): void {
    this.isDirty.value = true;
    this.saveStatus.value = 'unsaved';
    this.scheduleDebounced();
  }

  public markClean(): void {
    this.isDirty.value = false;
    this.lastSavedAt.value = new Date();
    this.saveStatus.value = 'saved';
    this.clearSchedule();
  }

  public schedule(): void {
    this.markDirty();
  }

  public scheduleDebounced(): void {
    if (this.debounceTimer) {
      clearTimeout(this.debounceTimer);
    }
    this.debounceTimer = setTimeout(() => {
      void this.flush();
    }, this.debounceMs);
  }

  public clearSchedule(): void {
    if (this.debounceTimer) {
      clearTimeout(this.debounceTimer);
      this.debounceTimer = null;
    }
  }

  public async flush(): Promise<void> {
    this.clearSchedule();

    if (!this.isDirty.value || this.isSaving.value || this.isFlushing) {
      return;
    }

    // Predicate check (e.g. not playing audio)
    if (this.canSavePredicate && !this.canSavePredicate()) {
      // Defer until active playback stops
      this.debounceTimer = setTimeout(() => void this.flush(), 1200);
      return;
    }

    this.isFlushing = true;
    this.isSaving.value = true;
    this.saveStatus.value = 'saving';

    try {
      const ok = await this.saveFn();
      if (ok) {
        this.markClean();
      } else {
        this.saveStatus.value = 'error';
      }
    } catch (err) {
      console.error('Autosave flush failed:', err);
      this.saveStatus.value = 'error';
    } finally {
      this.isSaving.value = false;
      this.isFlushing = false;
    }
  }

  public destroy(): void {
    this.clearSchedule();
  }
}

