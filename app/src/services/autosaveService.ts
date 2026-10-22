import { ref } from 'vue';

export type SaveStatus = 'saved' | 'saving' | 'unsaved' | 'error';

export interface AutosaveOptions {
  checkIntervalMs?: number;
  retryDelayMs?: number;
  saveFn: () => Promise<boolean>;
  canSavePredicate?: () => boolean;
}

export class AutosaveService {
  public isDirty = ref<boolean>(false);
  public isSaving = ref<boolean>(false);
  public lastSavedAt = ref<Date | null>(null);
  public saveStatus = ref<SaveStatus>('saved');

  private checkIntervalMs: number;
  private retryDelayMs: number;
  private saveFn: () => Promise<boolean>;
  private canSavePredicate?: () => boolean;

  private saveIdleHandle?: number;
  private saveRetryTimeout?: any;
  private isAutosaveScheduled: boolean = false;
  private intervalHandle?: any;

  constructor(options: AutosaveOptions) {
    this.checkIntervalMs = options.checkIntervalMs ?? 15000;
    this.retryDelayMs = options.retryDelayMs ?? 5000;
    this.saveFn = options.saveFn;
    this.canSavePredicate = options.canSavePredicate;

    this.initLifecycle();
  }

  private initLifecycle(): void {
    if (typeof window === 'undefined') return;

    this.intervalHandle = setInterval(() => {
      if (this.isDirty.value && !this.isSaving.value) {
        this.schedule();
      }
    }, this.checkIntervalMs);

    window.addEventListener('beforeunload', (e) => {
      if (this.isDirty.value) {
        e.preventDefault();
        e.returnValue = '';
      }
    });
  }

  public markDirty(): void {
    this.isDirty.value = true;
    this.saveStatus.value = 'unsaved';
    this.schedule();
  }

  public markClean(): void {
    this.isDirty.value = false;
    this.lastSavedAt.value = new Date();
    this.saveStatus.value = 'saved';
    this.clearSchedule();
  }

  public schedule(): void {
    if (this.isAutosaveScheduled || !this.isDirty.value) return;
    this.isAutosaveScheduled = true;
    this.saveStatus.value = 'unsaved';

    if (typeof window !== 'undefined' && 'requestIdleCallback' in window) {
      this.saveIdleHandle = (window as any).requestIdleCallback(() => void this.flush(), {
        timeout: this.retryDelayMs,
      });
      return;
    }

    this.saveRetryTimeout = setTimeout(() => void this.flush(), 100);
  }

  public clearSchedule(): void {
    if (typeof window !== 'undefined') {
      if (this.saveIdleHandle !== undefined && 'cancelIdleCallback' in window) {
        (window as any).cancelIdleCallback(this.saveIdleHandle);
        this.saveIdleHandle = undefined;
      }
      if (this.saveRetryTimeout !== undefined) {
        clearTimeout(this.saveRetryTimeout);
        this.saveRetryTimeout = undefined;
      }
    }
    this.isAutosaveScheduled = false;
  }

  public async flush(): Promise<void> {
    this.clearSchedule();

    if (!this.isDirty.value || this.isSaving.value) {
      return;
    }

    // Predicate check (e.g. not playing, modal not open)
    if (this.canSavePredicate && !this.canSavePredicate()) {
      this.saveRetryTimeout = setTimeout(() => this.schedule(), this.retryDelayMs);
      return;
    }

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
    }
  }

  public destroy(): void {
    if (this.intervalHandle) clearInterval(this.intervalHandle);
    this.clearSchedule();
  }
}
