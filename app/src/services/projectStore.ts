import { reactive, computed, ref } from 'vue';
import type { 
  AlignerProject, 
  SurahItem, 
  AyahItem, 
  AyahSegment,
  TimelineSegmentItem,
  AlignedWord, 
  ConfidenceIssue, 
  HistoryAction,
  StudioViewMode,
  StudioLoopMode
} from '../types/aligner';
import { QURAN_SURAHS } from '../data/quranMetadata';

const EMPTY_PROJECT: AlignerProject = {
  project_name: 'مشروع جديد',
  app_version: '2.0.0',
  created_at: new Date().toISOString(),
  updated_at: new Date().toISOString(),
  settings: {
    snapping_tolerance_ms: 25,
    confidence_warning_threshold: 0.85,
    auto_save_interval_s: 30,
  },
  surahs: [],
};

import { 
  getApiBaseUrl, 
  getAudioStreamUrl, 
  saveProject, 
  createProject, 
  loadProject, 
  deleteProject, 
  duplicateProject 
} from './api';
import { auditSurah } from './auditorEngine';
export { getApiBaseUrl, getAudioStreamUrl };

class ProjectStore {
  // Main Project Document (Starts empty, 0 demo surahs)
  public project = reactive<AlignerProject>(JSON.parse(JSON.stringify(EMPTY_PROJECT)));

  // Global View Tab ('projects' or 'studio')
  public currentTab = ref<'projects' | 'studio'>('projects');

  // Active Navigation & Playback State
  public activeSurahNumber = ref<number | null>(null);
  public activeAyahNumber = ref<number | null>(null);
  public activeWordLocation = ref<string | null>(null);
  public currentTime = ref<number>(0);
  public currentKaraokeLocation = ref<string | null>(null);
  public isPlaying = ref<boolean>(false);
  public playbackRate = ref<number>(1.0);
  public zoomPxPerSec = ref<number>(120);
  public activeAudioUrl = ref<string | null>(null);
  public activeAudioFilePath = ref<string | null>(null);
  public volume = ref<number>(1.0);
  public isMuted = ref<boolean>(false);
  
  // UI & View Mode States
  public viewMode = ref<StudioViewMode>('mushaf_page');
  public loopMode = ref<StudioLoopMode>('none');
  public autoScrollMushaf = ref<boolean>(true);
  public issuesDrawerOpen = ref<boolean>(false);
  public isAuditing = ref<boolean>(true);
  public resolvedIssueIds = ref<Set<string>>(new Set());

  // Undo / Redo Stack & Auto-Save
  private historyStack: HistoryAction[] = [];
  private redoStack: HistoryAction[] = [];
  public canUndo = ref<boolean>(false);
  public canRedo = ref<boolean>(false);
  public isDirty = ref<boolean>(false);
  public isSaving = ref<boolean>(false);
  public lastSavedAt = ref<Date | null>(null);
  public saveStatus = ref<'saved' | 'saving' | 'unsaved' | 'error'>('saved');

  // QuranCaption Lightweight Autosave Engine Constants & Handles
  private static readonly AUTOSAVE_CHECK_INTERVAL_MS = 15000; // 15 seconds
  private static readonly AUTOSAVE_RETRY_DELAY_MS = 5000;     // 5 seconds
  private saveIdleHandle?: number;
  private saveRetryTimeout?: any;
  private isAutosaveScheduled: boolean = false;

  constructor() {
    if (typeof window !== 'undefined') {
      // Periodic check: zero work/CPU/disk if isDirty is false
      setInterval(() => {
        if (this.isDirty.value && !this.isSaving.value && this.project.surahs.length > 0) {
          this.scheduleAutosave();
        }
      }, ProjectStore.AUTOSAVE_CHECK_INTERVAL_MS);

      // Protect against accidental tab close if unsaved edits exist
      window.addEventListener('beforeunload', (e) => {
        if (this.isDirty.value) {
          e.preventDefault();
          e.returnValue = '';
        }
      });
    }
  }

  /**
   * Plans the next autosave attempt off the UI hot path via requestIdleCallback.
   */
  public scheduleAutosave(): void {
    if (this.isAutosaveScheduled || !this.isDirty.value) return;
    this.isAutosaveScheduled = true;
    this.saveStatus.value = 'unsaved';

    if (typeof window !== 'undefined' && 'requestIdleCallback' in window) {
      this.saveIdleHandle = (window as any).requestIdleCallback(() => void this.flushAutosave(), {
        timeout: ProjectStore.AUTOSAVE_RETRY_DELAY_MS
      });
      return;
    }

    this.saveRetryTimeout = setTimeout(() => void this.flushAutosave(), 100);
  }

  public clearScheduledAutosave(): void {
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

  /**
   * Executes the autosave if dirty, deferring if audio is currently playing or dialog is open.
   */
  public async flushAutosave(): Promise<void> {
    this.clearScheduledAutosave();

    // 1. Fast zero-cost bail if clean or already saving (0 CPU, 0 disk I/O)
    if (!this.isDirty.value || this.isSaving.value || !this.project || !this.project.project_name) {
      return;
    }

    // 2. QuranCaption deferral: do not write to disk while audio is playing or modal is open
    const isModalOpen = typeof document !== 'undefined' && 
      document.querySelector('.modal-wrapper, [role="dialog"], .dialog-overlay, .modal-backdrop, .alignment-modal, .modal-overlay') !== null;

    if (this.isPlaying.value || isModalOpen) {
      this.saveRetryTimeout = setTimeout(() => this.scheduleAutosave(), ProjectStore.AUTOSAVE_RETRY_DELAY_MS);
      return;
    }

    // 3. Save project state to disk
    await this.saveActiveProject();
  }

  public async saveActiveProject(): Promise<boolean> {
    if (!this.project || !this.project.project_name) return false;
    this.isSaving.value = true;
    this.saveStatus.value = 'saving';

    try {
      const fileName = this.project.file_name || `${this.project.project_name}.qproj`;
      await saveProject(fileName, this.project);
      this.isDirty.value = false;
      this.lastSavedAt.value = new Date();
      this.saveStatus.value = 'saved';
      return true;
    } catch (err) {
      console.error('Auto-save failed:', err);
      this.saveStatus.value = 'error';
    } finally {
      this.isSaving.value = false;
    }
    return false;
  }

  // Active Surah getter
  public activeSurah = computed<SurahItem | undefined>(() => {
    return this.project.surahs.find(s => s.surah_number === this.activeSurahNumber.value);
  });

  // Active Ayah getter
  public activeAyah = computed<AyahItem | undefined>(() => {
    if (!this.activeSurah.value || this.activeAyahNumber.value === null) return undefined;
    return this.activeSurah.value.ayahs.find(a => a.ayah === this.activeAyahNumber.value);
  });

  // Flat list of words in active Ayah (or intro)
  public activeAyahWords = computed<AlignedWord[]>(() => {
    if (!this.activeSurah.value) return [];
    if (this.activeAyahNumber.value === null || this.activeAyahNumber.value === 0) {
      if (this.activeSurah.value.intro && this.activeSurah.value.intro.words) {
        return this.activeSurah.value.intro.words;
      }
    }
    const a = this.activeAyah.value;
    if (!a) return [];
    return a.segments.flatMap(s => s.words);
  });

  // Flat list of words in active Surah
  public activeWords = computed<AlignedWord[]>(() => {
    if (!this.activeSurah.value) return [];
    const list: AlignedWord[] = [];
    if (this.activeSurah.value.intro && this.activeSurah.value.intro.words) {
      list.push(...this.activeSurah.value.intro.words);
    }
    for (const a of this.activeSurah.value.ayahs) {
      for (const seg of a.segments) {
        list.push(...seg.words);
      }
    }
    return list;
  });

  // Structured list of Timeline Segments in active Surah (matching QuranCaption segment/repetition model)
  public activeSegments = computed<TimelineSegmentItem[]>(() => {
    const surah = this.activeSurah.value;
    if (!surah) return [];

    const list: TimelineSegmentItem[] = [];

    // Intro (Isti'adha / Basmalah)
    if (surah.intro && surah.intro.words && surah.intro.words.length > 0) {
      const introWords = surah.intro.words;
      const start = surah.intro.start || introWords[0].start;
      const end = surah.intro.end || introWords[introWords.length - 1].end;
      list.push({
        id: `seg_intro_${surah.surah_number}`,
        surahNumber: surah.surah_number,
        ayahNumber: 0,
        segmentIndex: 0,
        type: 'intro',
        label: 'الاستعاذة والبسملة',
        start,
        end,
        duration: Math.max(0.1, end - start),
        isRepetition: false,
        transcribedText: surah.intro.text,
        connectedUthmaniText: introWords.map(w => w.word).join(' ') || surah.intro.text || '',
        words: introWords,
        hasIssues: false,
      });
    }

    // Ayahs & their individual segments (breath groups / repeated takes)
    for (const a of surah.ayahs) {
      const segs = a.segments || [];
      const hasMultipleSegs = segs.length > 1;

      for (let sIdx = 0; sIdx < segs.length; sIdx++) {
        const seg = segs[sIdx];
        const segWords = seg.words || [];
        let start = seg.start;
        let end = seg.end;
        if ((start === 0 && end === 0) || end <= start) {
          if (segWords.length > 0) {
            start = segWords[0].start;
            end = segWords[segWords.length - 1].end;
          }
        }

        const isRepetition = !!seg.is_repetition;
        const label = hasMultipleSegs ? `آية ${a.ayah} (${seg.segment || (sIdx + 1)})` : `آية ${a.ayah}`;

        const hasIssues = segWords.some(w => w.score < 0.85);

        list.push({
          id: `seg_${surah.surah_number}_${a.ayah}_${seg.segment || sIdx}`,
          surahNumber: surah.surah_number,
          ayahNumber: a.ayah,
          segmentIndex: seg.segment || sIdx,
          type: 'segment',
          label,
          start,
          end,
          duration: Math.max(0.1, end - start),
          isRepetition,
          transcribedText: seg.transcribed_text,
          connectedUthmaniText: segWords.map(w => w.word).join(' '),
          words: segWords,
          hasIssues,
        });
      }
    }

    return list;
  });

  public findSegmentForWord(target: AlignedWord | string): TimelineSegmentItem | undefined {
    if (typeof target === 'string') {
      return this.activeSegments.value.find(seg => seg.words.some(w => w.location === target));
    }
    return this.activeSegments.value.find(seg => seg.words.some(w => w === target));
  }

  // Active Word based on current audio time (Optimized to avoid re-evaluating 60 times/sec)
  public currentWordAtPlayhead = computed<AlignedWord | undefined>(() => {
    if (!this.currentKaraokeLocation.value) return undefined;
    return this.findWordByLocation(this.currentKaraokeLocation.value);
  });

  // High performance playback updater (only changes reactive karaoke when crossing word boundaries)
  public updateCurrentTime(t: number) {
    this.currentTime.value = t;

    // Fast path: still in current word?
    if (this.currentKaraokeLocation.value) {
      const cur = this.findWordByLocation(this.currentKaraokeLocation.value);
      if (cur && t >= cur.start && t <= cur.end) {
        return;
      }
    }

    // Slow path (runs only once per word, every ~0.8s):
    const words = this.activeWords.value;
    let foundLoc: string | null = null;
    for (let i = 0; i < words.length; i++) {
      const w = words[i];
      if (t >= w.start && t <= w.end) {
        foundLoc = w.location;
        break;
      }
    }

    if (this.currentKaraokeLocation.value !== foundLoc) {
      this.currentKaraokeLocation.value = foundLoc;
      if (foundLoc) {
        const [, aStr] = foundLoc.split(':');
        if (aStr) {
          const aNum = parseInt(aStr);
          if (!isNaN(aNum) && aNum !== this.activeAyahNumber.value) {
            this.activeAyahNumber.value = aNum;
          }
        }
      }
    }
  }

  // Surah Health Stats
  public surahStats = computed(() => {
    const words = this.activeWords.value;
    const allIssues = this.issues.value;
    const unresolvedIssues = allIssues.filter(i => !i.resolved);
    const criticalCount = unresolvedIssues.filter(i => i.severity === 'critical').length;
    const warningCount = unresolvedIssues.filter(i => i.severity === 'warning').length;

    if (words.length === 0) {
      return {
        totalWords: 0,
        avgConfidence: 100,
        cleanWords: 0,
        warningWords: 0,
        criticalWords: 0,
        totalIssues: 0,
        unresolvedIssues: 0,
        resolvedIssues: 0,
      };
    }

    const cleanWords = Math.max(0, words.length - unresolvedIssues.length);
    const cleanPercent = Math.round((cleanWords / words.length) * 100);

    return {
      totalWords: words.length,
      avgConfidence: cleanPercent,
      cleanWords,
      warningWords: warningCount,
      criticalWords: criticalCount,
      totalIssues: allIssues.length,
      unresolvedIssues: unresolvedIssues.length,
      resolvedIssues: allIssues.length - unresolvedIssues.length,
    };
  });

  // Automated Confidence Auditor Issues (Pure-TS Engine)
  public issues = computed<ConfidenceIssue[]>(() => {
    if (!this.activeSurah.value) return [];
    const threshold = this.project.settings.confidence_warning_threshold || 0.85;
    return auditSurah(this.activeSurah.value, this.resolvedIssueIds.value, threshold);
  });

  // Manual Verification & Auditor Actions
  public toggleIssueVerified(issueId: string) {
    const nextSet = new Set(this.resolvedIssueIds.value);
    const isNowResolved = !nextSet.has(issueId);
    if (isNowResolved) {
      nextSet.add(issueId);
    } else {
      nextSet.delete(issueId);
    }
    this.resolvedIssueIds.value = nextSet;

    // Persist on word object so verification survives in project JSON
    const issue = this.issues.value.find(i => i.id === issueId);
    if (issue) {
      const word = this.findWordByLocation(issue.location, issue.timestamp);
      if (word) {
        word.is_verified = isNowResolved;
        this.isDirty.value = true;
      }
    }
  }

  public markIssueResolved(issueId: string, resolved: boolean = true) {
    const nextSet = new Set(this.resolvedIssueIds.value);
    if (resolved) {
      nextSet.add(issueId);
    } else {
      nextSet.delete(issueId);
    }
    this.resolvedIssueIds.value = nextSet;

    const issue = this.issues.value.find(i => i.id === issueId);
    if (issue) {
      const word = this.findWordByLocation(issue.location, issue.timestamp);
      if (word) {
        word.is_verified = resolved;
        this.isDirty.value = true;
      }
    }
  }

  // Update State & History
  private recordHistory(action: HistoryAction) {
    this.historyStack.push(action);
    this.redoStack = [];
    this.isDirty.value = true;
    this.updateHistoryFlags();
    this.scheduleAutosave();
  }

  private updateHistoryFlags() {
    this.canUndo.value = this.historyStack.length > 0;
    this.canRedo.value = this.redoStack.length > 0;
  }

  public undo() {
    const action = this.historyStack.pop();
    if (action) {
      action.undo();
      this.redoStack.push(action);
      this.updateHistoryFlags();
      this.isDirty.value = true;
      this.scheduleAutosave();
    }
  }

  public redo() {
    const action = this.redoStack.pop();
    if (action) {
      action.redo();
      this.historyStack.push(action);
      this.updateHistoryFlags();
      this.isDirty.value = true;
      this.scheduleAutosave();
    }
  }

  // Navigation
  public selectSurah(surahNum: number) {
    this.activeSurahNumber.value = surahNum;
    const s = this.project.surahs.find(item => item.surah_number === surahNum);
    if (s) {
      const effectiveAudioUrl = s.audio_url || (s.audio_file ? getAudioStreamUrl(s.audio_file) : null);
      if (effectiveAudioUrl) {
        s.audio_url = effectiveAudioUrl;
        this.activeAudioUrl.value = effectiveAudioUrl;
      }
      if (s.audio_file) {
        this.activeAudioFilePath.value = s.audio_file;
      }

      if (s.ayahs && s.ayahs.length > 0) {
        this.activeAyahNumber.value = s.ayahs[0].ayah;
        this.currentTime.value = s.ayahs[0].start;
      } else if (s.intro && s.intro.words && s.intro.words.length > 0) {
        this.activeAyahNumber.value = 0;
        this.currentTime.value = s.intro.words[0].start;
      } else {
        this.activeAyahNumber.value = null;
        this.currentTime.value = 0;
      }
    } else {
      this.activeAyahNumber.value = null;
      this.currentTime.value = 0;
    }
    this.activeWordLocation.value = null;
  }

  public selectAyah(ayahNum: number) {
    this.activeAyahNumber.value = ayahNum;
    const a = this.activeAyah.value;
    if (a) {
      this.currentTime.value = a.start;
    }
  }

  public selectWord(location: string, seekAudio: boolean = true, targetTimestamp?: number) {
    this.activeWordLocation.value = location;
    const word = this.findWordByLocation(location, targetTimestamp);
    if (word) {
      if (seekAudio) {
        this.currentTime.value = targetTimestamp !== undefined ? targetTimestamp : word.start;
      }
      // Also update active ayah if different
      const [, aStr] = location.split(':');
      if (aStr) {
        this.activeAyahNumber.value = parseInt(aStr);
      }
    }
  }

  public findWordByLocation(location: string, nearTime?: number): AlignedWord | undefined {
    const matches = this.activeWords.value.filter(w => w.location === location);
    if (matches.length === 0) return undefined;
    if (nearTime === undefined || matches.length === 1) return matches[0];

    let closest = matches[0];
    let minDiff = Math.abs(matches[0].start - nearTime);
    for (let i = 1; i < matches.length; i++) {
      const diff = Math.abs(matches[i].start - nearTime);
      if (diff < minDiff) {
        minDiff = diff;
        closest = matches[i];
      }
    }
    return closest;
  }

  public setLoadedAudio(filePath: string, url: string, duration?: number) {
    this.activeAudioFilePath.value = filePath;
    this.activeAudioUrl.value = url;
    if (this.activeSurah.value) {
      this.activeSurah.value.audio_file = filePath;
      this.activeSurah.value.audio_url = url;
      if (duration && duration > 0) {
        this.activeSurah.value.audio_duration_seconds = duration;
      }
      this.isDirty.value = true;
    }
  }


  public jumpToPrevAyah() {
    if (!this.activeSurah.value || this.activeAyahNumber.value === null) return;
    const curAyah = this.activeAyahNumber.value;
    const ayahs = this.activeSurah.value.ayahs;
    const idx = ayahs.findIndex(a => a.ayah === curAyah);
    if (idx > 0) {
      this.selectAyah(ayahs[idx - 1].ayah);
    }
  }

  public jumpToNextAyah() {
    if (!this.activeSurah.value || this.activeAyahNumber.value === null) return;
    const curAyah = this.activeAyahNumber.value;
    const ayahs = this.activeSurah.value.ayahs;
    const idx = ayahs.findIndex(a => a.ayah === curAyah);
    if (idx !== -1 && idx < ayahs.length - 1) {
      this.selectAyah(ayahs[idx + 1].ayah);
    }
  }

  public jumpToNextIssue() {
    const allList = this.issues.value;
    if (allList.length === 0) return;
    const pending = allList.filter(i => !i.resolved);
    const targetList = pending.length > 0 ? pending : allList;
    const curLoc = this.activeWordLocation.value;
    const curTime = this.currentTime.value;

    let idx = -1;
    if (curLoc) {
      idx = targetList.findIndex(i => i.location === curLoc && Math.abs(i.timestamp - curTime) < 1.0);
      if (idx === -1) {
        idx = targetList.findIndex(i => i.location === curLoc);
      }
    }

    const nextIssue = (idx === -1 || idx === targetList.length - 1) ? targetList[0] : targetList[idx + 1];
    this.selectWord(nextIssue.location, true, nextIssue.timestamp);
  }

  // History Commit on MouseUp for Shared Dividers (Prevents flood during mousemove)
  public recordDividerHistory(
    leftWord: AlignedWord,
    rightWord: AlignedWord,
    oldLeftEnd: number,
    oldRightStart: number,
    newTime: number
  ) {
    const apply = (timeVal: number) => {
      leftWord.end = timeVal;
      rightWord.start = timeVal;
      leftWord.is_edited = true;
      rightWord.is_edited = true;
      this.updateAyahBounds(leftWord.location);
      this.updateAyahBounds(rightWord.location);
    };

    this.recordHistory({
      description: `Adjusted divider between "${leftWord.word}" and "${rightWord.word}" to ${newTime.toFixed(2)}s`,
      timestamp: Date.now(),
      undo: () => {
        leftWord.end = oldLeftEnd;
        rightWord.start = oldRightStart;
        this.updateAyahBounds(leftWord.location);
        this.updateAyahBounds(rightWord.location);
      },
      redo: () => apply(newTime),
    });
  }

  // History Commit on MouseUp for Word Outer Boundaries (Prevents flood during mousemove)
  public recordWordBoundaryHistory(
    word: AlignedWord,
    edge: 'start' | 'end',
    oldTime: number,
    newTime: number
  ) {
    const apply = (timeVal: number) => {
      if (edge === 'start') {
        word.start = timeVal;
      } else {
        word.end = timeVal;
      }
      word.is_edited = true;
      this.updateAyahBounds(word.location);
    };

    this.recordHistory({
      description: `Adjusted ${edge} boundary of "${word.word}" to ${newTime.toFixed(2)}s`,
      timestamp: Date.now(),
      undo: () => apply(oldTime),
      redo: () => apply(newTime),
    });
  }

  // Contiguous Shared-Vertex Boundary Update (QuranCaption Model)
  public updateSharedBoundary(leftTarget: AlignedWord | string, rightTarget: AlignedWord | string, newTime: number) {
    const leftWord = typeof leftTarget === 'string' ? this.findWordByLocation(leftTarget) : leftTarget;
    const rightWord = typeof rightTarget === 'string' ? this.findWordByLocation(rightTarget) : rightTarget;
    if (!leftWord || !rightWord) return;

    const oldLeftEnd = leftWord.end;
    const oldRightStart = rightWord.start;

    // Minimum word duration: 40ms
    const minTime = leftWord.start + 0.04;
    const maxTime = rightWord.end - 0.04;
    const clampedTime = Math.max(minTime, Math.min(maxTime, Number(newTime.toFixed(2))));

    const apply = (timeVal: number, edited: boolean) => {
      leftWord.end = timeVal;
      rightWord.start = timeVal;
      leftWord.is_edited = edited;
      rightWord.is_edited = edited;
      this.updateAyahBounds(leftWord.location);
      this.updateAyahBounds(rightWord.location);
    };

    apply(clampedTime, true);

    this.recordHistory({
      description: `Adjusted shared divider between "${leftWord.word}" and "${rightWord.word}" to ${clampedTime}s`,
      timestamp: Date.now(),
      undo: () => {
        leftWord.end = oldLeftEnd;
        rightWord.start = oldRightStart;
        this.updateAyahBounds(leftWord.location);
        this.updateAyahBounds(rightWord.location);
      },
      redo: () => apply(clampedTime, true),
    });
  }

  // Core Word Timing Adjustments (with Undo/Redo)
  public updateWordBoundary(target: AlignedWord | string, newStart: number, newEnd: number) {
    const word = typeof target === 'string' ? this.findWordByLocation(target) : target;
    if (!word) return;

    const oldStart = word.start;
    const oldEnd = word.end;
    const oldEdited = word.is_edited;

    const validStart = Math.max(0, Number(newStart.toFixed(2)));
    const validEnd = Math.max(validStart + 0.04, Number(newEnd.toFixed(2)));

    const apply = (s: number, e: number, ed: boolean) => {
      word.start = s;
      word.end = e;
      word.is_edited = ed;
      this.updateAyahBounds(word.location);
    };

    apply(validStart, validEnd, true);

    this.recordHistory({
      description: `Adjusted boundary of "${word.word}" to [${validStart}s - ${validEnd}s]`,
      timestamp: Date.now(),
      undo: () => apply(oldStart, oldEnd, !!oldEdited),
      redo: () => apply(validStart, validEnd, true),
    });
  }

  // Adjust Start Boundary of Word (Segment-aware: boundary words NEVER merge across segments!)
  public updateWordStart(target: AlignedWord | string, newStart: number) {
    const word = typeof target === 'string' ? this.findWordByLocation(target) : target;
    if (!word) return;

    const oldStart = word.start;
    const seg = this.findSegmentForWord(word);
    if (!seg) return;

    const sWords = seg.words;
    const wIdx = sWords.findIndex(w => w === word);
    if (wIdx === -1) return;

    // FIRST word of segment: Adjust start directly into preceding silence (NEVER merge with previous segment!)
    if (wIdx === 0) {
      let prevLimit = 0;
      for (const s of this.activeSegments.value) {
        if (s.id !== seg.id && s.end < oldStart) {
          if (s.end > prevLimit) prevLimit = s.end;
        }
      }
      const minTime = prevLimit;
      const maxTime = word.end - 0.02; // minimum duration 20ms
      const clampedStart = Math.max(minTime, Math.min(maxTime, Number(newStart.toFixed(3))));

      const apply = (s: number) => {
        word.start = s;
        word.is_edited = true;
        this.updateAyahBounds(word.location);
      };

      apply(clampedStart);

      this.recordHistory({
        description: `Adjusted segment start boundary of "${word.word}" to ${clampedStart}s`,
        timestamp: Date.now(),
        undo: () => apply(oldStart),
        redo: () => apply(clampedStart),
      });
      return;
    }

    // INTERMEDIATE word within the SAME segment:
    // Adjust start independently up to preceding word's end (zero gap-snapping, authentic aligner data)
    const minTime = sWords[wIdx - 1].end;
    const maxTime = word.end - 0.02;
    const clampedStart = Math.max(minTime, Math.min(maxTime, Number(newStart.toFixed(3))));

    const apply = (s: number) => {
      word.start = s;
      word.is_edited = true;
      this.updateAyahBounds(word.location);
    };

    apply(clampedStart);

    this.recordHistory({
      description: `Adjusted start boundary of "${word.word}" to ${clampedStart}s`,
      timestamp: Date.now(),
      undo: () => apply(oldStart),
      redo: () => apply(clampedStart),
    });
  }

  // Adjust End Boundary of Word (Segment-aware: boundary words NEVER merge across segments!)
  public updateWordEnd(target: AlignedWord | string, newEnd: number) {
    const word = typeof target === 'string' ? this.findWordByLocation(target) : target;
    if (!word) return;

    const oldEnd = word.end;
    const seg = this.findSegmentForWord(word);
    if (!seg) return;

    const sWords = seg.words;
    const wIdx = sWords.findIndex(w => w === word);
    if (wIdx === -1) return;

    // LAST word of segment: Adjust end directly into following silence (NEVER merge with next segment!)
    if (wIdx === sWords.length - 1) {
      let nextLimit = this.activeSurah.value?.audio_duration_seconds || 999999;
      for (const s of this.activeSegments.value) {
        if (s.id !== seg.id && s.start > oldEnd) {
          if (s.start < nextLimit) nextLimit = s.start;
        }
      }

      const minTime = word.start + 0.02; // minimum duration 20ms
      const maxTime = nextLimit;
      const clampedEnd = Math.max(minTime, Math.min(maxTime, Number(newEnd.toFixed(3))));

      const apply = (e: number) => {
        word.end = e;
        word.is_edited = true;
        this.updateAyahBounds(word.location);
      };

      apply(clampedEnd);

      this.recordHistory({
        description: `Adjusted segment end boundary of "${word.word}" to ${clampedEnd}s`,
        timestamp: Date.now(),
        undo: () => apply(oldEnd),
        redo: () => apply(clampedEnd),
      });
      return;
    }

    // INTERMEDIATE word within the SAME segment:
    // Adjust end independently down to next word's start (zero gap-snapping, authentic aligner data)
    const minTime = word.start + 0.02;
    const maxTime = sWords[wIdx + 1].start;
    const clampedEnd = Math.max(minTime, Math.min(maxTime, Number(newEnd.toFixed(3))));

    const apply = (e: number) => {
      word.end = e;
      word.is_edited = true;
      this.updateAyahBounds(word.location);
    };

    apply(clampedEnd);

    this.recordHistory({
      description: `Adjusted end boundary of "${word.word}" to ${clampedEnd}s`,
      timestamp: Date.now(),
      undo: () => apply(oldEnd),
      redo: () => apply(clampedEnd),
    });
  }

  // Segment Outer Boundary Timing Adjustments
  public updateSegmentStart(segmentId: string, newStart: number) {
    const seg = this.activeSegments.value.find(s => s.id === segmentId);
    if (!seg || seg.words.length === 0) return;
    this.updateWordStart(seg.words[0].location, newStart);
  }

  public updateSegmentEnd(segmentId: string, newEnd: number) {
    const seg = this.activeSegments.value.find(s => s.id === segmentId);
    if (!seg || seg.words.length === 0) return;
    this.updateWordEnd(seg.words[seg.words.length - 1].location, newEnd);
  }

  // Ayah / Verse Outer Boundary Timing Adjustments
  public updateAyahStart(ayahNumber: number, newStart: number) {
    if (!this.activeSurah.value) return;
    const surah = this.activeSurah.value;

    if (ayahNumber === 0 && surah.intro && surah.intro.words && surah.intro.words.length > 0) {
      this.updateWordStart(surah.intro.words[0].location, newStart);
      return;
    }

    const ayah = surah.ayahs.find(a => a.ayah === ayahNumber);
    if (!ayah) return;

    const allWords = ayah.segments.flatMap(s => s.words);
    if (allWords.length > 0) {
      this.updateWordStart(allWords[0].location, newStart);
    } else {
      ayah.start = Math.max(0, Number(newStart.toFixed(2)));
    }
  }

  public updateAyahEnd(ayahNumber: number, newEnd: number) {
    if (!this.activeSurah.value) return;
    const surah = this.activeSurah.value;

    if (ayahNumber === 0 && surah.intro && surah.intro.words && surah.intro.words.length > 0) {
      const lastWord = surah.intro.words[surah.intro.words.length - 1];
      this.updateWordEnd(lastWord.location, newEnd);
      return;
    }

    const ayah = surah.ayahs.find(a => a.ayah === ayahNumber);
    if (!ayah) return;

    const allWords = ayah.segments.flatMap(s => s.words);
    if (allWords.length > 0) {
      this.updateWordEnd(allWords[allWords.length - 1].location, newEnd);
    } else {
      ayah.end = Math.max(ayah.start + 0.1, Number(newEnd.toFixed(2)));
    }
  }

  // Segment Split (QuranCaption Pattern)
  public splitSegmentAtWord(location: string) {
    if (!this.activeSurah.value) return;
    for (const ayah of this.activeSurah.value.ayahs) {
      for (let sIdx = 0; sIdx < ayah.segments.length; sIdx++) {
        const seg = ayah.segments[sIdx];
        const wIdx = seg.words.findIndex(w => w.location === location);
        if (wIdx > 0) {
          const leftWords = seg.words.slice(0, wIdx);
          const rightWords = seg.words.slice(wIdx);

          const newSeg: AyahSegment = {
            segment: ayah.segments.length + 1,
            start: rightWords[0].start,
            end: rightWords[rightWords.length - 1].end,
            words: rightWords,
            transcribed_text: rightWords.map(w => w.word).join(' '),
          };

          seg.words = leftWords;
          seg.end = leftWords[leftWords.length - 1].end;
          seg.transcribed_text = leftWords.map(w => w.word).join(' ');

          ayah.segments.splice(sIdx + 1, 0, newSeg);
          this.updateAyahBounds(location);

          this.recordHistory({
            description: `Split segment in Ayah ${ayah.ayah} at word "${rightWords[0].word}"`,
            timestamp: Date.now(),
            undo: () => {
              seg.words = [...leftWords, ...rightWords];
              seg.end = rightWords[rightWords.length - 1].end;
              ayah.segments.splice(sIdx + 1, 1);
              this.updateAyahBounds(location);
            },
            redo: () => {
              this.splitSegmentAtWord(location);
            }
          });
          return;
        }
      }
    }
  }

  // Merge Adjacent Segments in Ayah (QuranCaption Pattern)
  public mergeSegmentsInAyah(ayahNumber: number, segmentIndex: number) {
    if (!this.activeSurah.value) return;
    const ayah = this.activeSurah.value.ayahs.find(a => a.ayah === ayahNumber);
    if (!ayah || segmentIndex < 0 || segmentIndex >= ayah.segments.length - 1) return;

    const segA = ayah.segments[segmentIndex];
    const segB = ayah.segments[segmentIndex + 1];

    const backupWordsA = [...segA.words];
    const backupWordsB = [...segB.words];
    const backupEndA = segA.end;

    segA.words = [...segA.words, ...segB.words];
    segA.end = segB.end;
    segA.transcribed_text = segA.words.map(w => w.word).join(' ');
    ayah.segments.splice(segmentIndex + 1, 1);

    this.recordHistory({
      description: `Merged segments in Ayah ${ayah.ayah}`,
      timestamp: Date.now(),
      undo: () => {
        segA.words = backupWordsA;
        segA.end = backupEndA;
        ayah.segments.splice(segmentIndex + 1, 0, {
          segment: segmentIndex + 2,
          start: backupWordsB[0].start,
          end: backupWordsB[backupWordsB.length - 1].end,
          words: backupWordsB,
        });
      },
      redo: () => {
        this.mergeSegmentsInAyah(ayahNumber, segmentIndex);
      }
    });
  }

  public nudgeWord(target: AlignedWord | string, deltaSeconds: number, edge: 'start' | 'end' | 'both' = 'both') {
    const word = typeof target === 'string' ? this.findWordByLocation(target) : target;
    if (!word) return;

    if (edge === 'start') {
      this.updateWordStart(word, word.start + deltaSeconds);
      return;
    }
    if (edge === 'end') {
      this.updateWordEnd(word, word.end + deltaSeconds);
      return;
    }

    let targetStart = Math.max(0, Number((word.start + deltaSeconds).toFixed(2)));
    let targetEnd = Math.max(targetStart + 0.04, Number((word.end + deltaSeconds).toFixed(2)));
    this.updateWordBoundary(word, targetStart, targetEnd);
  }

  // Split Word
  public splitWord(target: AlignedWord | string) {
    if (!this.activeSurah.value) return;
    for (const a of this.activeSurah.value.ayahs) {
      for (const seg of a.segments) {
        const idx = seg.words.findIndex(w => (typeof target === 'string' ? w.location === target : w === target));
        if (idx !== -1) {
          const original = seg.words[idx];
          const midTime = Number(((original.start + original.end) / 2).toFixed(2));
          const oldEnd = original.end;

          const cloneWord: AlignedWord = {
            ...JSON.parse(JSON.stringify(original)),
            location: original.location,
            start: midTime,
            end: oldEnd,
            is_edited: true,
          };

          original.end = midTime;
          original.is_edited = true;
          seg.words.splice(idx + 1, 0, cloneWord);

          this.recordHistory({
            description: `Split word "${original.word}"`,
            timestamp: Date.now(),
            undo: () => {
              original.end = oldEnd;
              seg.words.splice(idx + 1, 1);
            },
            redo: () => {
              original.end = midTime;
              seg.words.splice(idx + 1, 0, cloneWord);
            }
          });
          return;
        }
      }
    }
  }

  // Merge Word with Next
  public mergeWordWithNext(location: string) {
    if (!this.activeSurah.value) return;
    for (const a of this.activeSurah.value.ayahs) {
      for (const seg of a.segments) {
        const idx = seg.words.findIndex(w => w.location === location);
        if (idx !== -1 && idx < seg.words.length - 1) {
          const cur = seg.words[idx];
          const nxt = seg.words[idx + 1];
          const oldCurEnd = cur.end;
          const oldCurText = cur.word;

          cur.end = nxt.end;
          cur.word = `${cur.word} ${nxt.word}`;
          cur.is_edited = true;
          seg.words.splice(idx + 1, 1);

          this.recordHistory({
            description: `Merged "${oldCurText}" with "${nxt.word}"`,
            timestamp: Date.now(),
            undo: () => {
              cur.end = oldCurEnd;
              cur.word = oldCurText;
              seg.words.splice(idx + 1, 0, nxt);
            },
            redo: () => {
              cur.end = nxt.end;
              cur.word = `${cur.word} ${nxt.word}`;
              seg.words.splice(idx + 1, 1);
            }
          });
          return;
        }
      }
    }
  }

  // Delete Phantom Word
  public deleteWord(target: AlignedWord | string) {
    if (!this.activeSurah.value) return;
    for (const a of this.activeSurah.value.ayahs) {
      for (const seg of a.segments) {
        const idx = seg.words.findIndex(w => (typeof target === 'string' ? w.location === target : w === target));
        if (idx !== -1) {
          const deleted = seg.words[idx];
          seg.words.splice(idx, 1);

          this.recordHistory({
            description: `Deleted word "${deleted.word}"`,
            timestamp: Date.now(),
            undo: () => seg.words.splice(idx, 0, deleted),
            redo: () => seg.words.splice(idx, 1),
          });
          return;
        }
      }
    }
  }

  // Manual Text / Timing Edit
  public editWord(location: string, newText: string, newScore: number) {
    const word = this.findWordByLocation(location);
    if (!word) return;

    const oldText = word.word;
    const oldScore = word.score;

    word.word = newText;
    word.score = newScore;
    word.is_edited = true;

    this.recordHistory({
      description: `Edited "${oldText}" to "${newText}"`,
      timestamp: Date.now(),
      undo: () => {
        word.word = oldText;
        word.score = oldScore;
      },
      redo: () => {
        word.word = newText;
        word.score = newScore;
      }
    });
  }

  // Rebind Word Location and Uthmani Text from Quranic Reference
  public rebindWordLocation(wordObj: AlignedWord, newLocation: string, newText: string) {
    const oldLocation = wordObj.location;
    const oldText = wordObj.word;

    const apply = (loc: string, txt: string) => {
      wordObj.location = loc;
      wordObj.word = txt;
      wordObj.is_edited = true;
      this.updateAyahBounds(loc);
    };

    apply(newLocation, newText);

    this.recordHistory({
      description: `Rebound word location from ${oldLocation} ("${oldText}") to ${newLocation} ("${newText}")`,
      timestamp: Date.now(),
      undo: () => apply(oldLocation, oldText),
      redo: () => apply(newLocation, newText),
    });
  }

  public updateAyahBounds(location: string) {
    const word = this.findWordByLocation(location);
    if (!word || !this.activeSurah.value) return;

    const [, aStr] = location.split(':');
    const ayahNum = parseInt(aStr);

    if (ayahNum === 0 && this.activeSurah.value.intro && this.activeSurah.value.intro.words) {
      const introWords = this.activeSurah.value.intro.words;
      if (introWords.length > 0) {
        this.activeSurah.value.intro.start = Math.min(...introWords.map(w => w.start));
        this.activeSurah.value.intro.end = Math.max(...introWords.map(w => w.end));
      }
      return;
    }

    const ayah = this.activeSurah.value.ayahs.find(a => a.ayah === ayahNum);
    if (!ayah) return;

    for (const seg of ayah.segments) {
      if (seg.words.length > 0) {
        seg.start = Math.min(...seg.words.map(w => w.start));
        seg.end = Math.max(...seg.words.map(w => w.end));
      }
    }

    const allStarts = ayah.segments.flatMap(s => s.words.map(w => w.start));
    const allEnds = ayah.segments.flatMap(s => s.words.map(w => w.end));
    if (allStarts.length > 0 && allEnds.length > 0) {
      ayah.start = Math.min(...allStarts);
      ayah.end = Math.max(...allEnds);
    }
  }

  // Mark Surah as Verified
  public toggleSurahVerified(surahNum: number) {
    const s = this.project.surahs.find(item => item.surah_number === surahNum);
    if (s) {
      s.status = s.status === 'verified' ? 'needs_review' : 'verified';
    }
  }

  // Ingest Canonical Pipeline Output JSON Directly (Supports Multi-Surah Recitations)
  public loadAlignedSurah(canonicalOutput: any, audioPath?: string, audioUrl?: string) {
    if (!canonicalOutput) return;

    let surahList: any[] = [];
    if (Array.isArray(canonicalOutput.surahs)) {
      surahList = canonicalOutput.surahs;
    } else if (canonicalOutput.surah && Array.isArray(canonicalOutput.ayahs)) {
      surahList = [canonicalOutput];
    } else if (Array.isArray(canonicalOutput)) {
      surahList = canonicalOutput;
    }

    if (surahList.length === 0) return;

    let firstAddedSurahNum: number | null = null;

    for (const sData of surahList) {
      const rawNum = sData.surah ?? sData.surah_number;
      const sNum = typeof rawNum === 'number' ? rawNum : parseInt(rawNum, 10);
      if (isNaN(sNum) || sNum <= 0) continue;

      const meta = QURAN_SURAHS.find(m => m.surah_number === sNum);

      // Compute total duration from last ayah
      let totalDur = 42.0;
      if (sData.ayahs && sData.ayahs.length > 0) {
        const lastAyah = sData.ayahs[sData.ayahs.length - 1];
        totalDur = Math.ceil(lastAyah.end) + 1.0;
      }

      const effectiveUrl = audioUrl || (audioPath ? getAudioStreamUrl(audioPath) : undefined);

      const newSurahObj: SurahItem = {
        surah_number: sNum,
        surah_name_arabic: meta ? meta.surah_name_arabic : `سورة ${sNum}`,
        surah_name_english: meta ? meta.surah_name_english : `Surah ${sNum}`,
        audio_file: audioPath,
        audio_url: effectiveUrl,
        audio_duration_seconds: totalDur,
        status: 'needs_review',
        intro: sData.intro,
        ayahs: sData.ayahs || [],
      };

      const existingIdx = this.project.surahs.findIndex(s => s.surah_number === sNum);
      if (existingIdx !== -1) {
        this.project.surahs[existingIdx] = newSurahObj;
      } else {
        this.project.surahs.push(newSurahObj);
      }

      if (firstAddedSurahNum === null) {
        firstAddedSurahNum = sNum;
      }
    }

    if (firstAddedSurahNum !== null) {
      this.selectSurah(firstAddedSurahNum);
      const firstSurah = this.project.surahs.find(s => s.surah_number === firstAddedSurahNum);
      if (firstSurah) {
        const effectiveUrl = firstSurah.audio_url || (firstSurah.audio_file ? getAudioStreamUrl(firstSurah.audio_file) : null);
        if (effectiveUrl) {
          this.activeAudioUrl.value = effectiveUrl;
        }
        if (firstSurah.audio_file) {
          this.activeAudioFilePath.value = firstSurah.audio_file;
        }
      }
      this.currentTab.value = 'studio';
    }

    this.isDirty.value = true;
  }

  // Delete a single surah from project (works even if it's the only one!)
  public deleteSurah(surahNum: number) {
    const idx = this.project.surahs.findIndex(s => s.surah_number === surahNum);
    if (idx !== -1) {
      this.project.surahs.splice(idx, 1);
      if (this.project.surahs.length > 0) {
        this.selectSurah(this.project.surahs[0].surah_number);
      } else {
        this.activeSurahNumber.value = null;
        this.activeAyahNumber.value = null;
        this.activeWordLocation.value = null;
        this.activeAudioUrl.value = null;
        this.activeAudioFilePath.value = null;
        this.currentTime.value = 0;
      }
    }
  }

  // Create New Project via Tauri IPC and open it
  public async createNewProject(name: string, reciter?: string, riwayah?: string, retries = 2): Promise<boolean> {
    try {
      const projectData: Partial<AlignerProject> = {
        project_name: name,
        reciter: reciter || '',
        app_version: '2.0.0',
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
        settings: {
          snapping_tolerance_ms: 25,
          confidence_warning_threshold: 0.85,
          auto_save_interval_s: 30,
          riwayah: riwayah || 'Hafs',
        },
        surahs: [],
      };
      const result = await createProject(name, projectData);
      if (result?.file) {
        projectData.file_name = result.file;
        this.loadProject(projectData as AlignerProject);
        this.currentTab.value = 'studio';
        return true;
      }
    } catch (err) {
      if (retries > 0) {
        await new Promise(r => setTimeout(r, 600));
        return this.createNewProject(name, reciter, riwayah, retries - 1);
      }
      console.error('Failed to create project:', err);
    }
    return false;
  }

  // Open Project by file name (.qproj)
  public async openProjectByFileName(fileName: string): Promise<boolean> {
    try {
      const data = await loadProject(fileName);
      if (data) {
        data.file_name = fileName;
        this.loadProject(data);
        this.currentTab.value = 'studio';
        return true;
      }
    } catch (err) {
      console.error('Failed to open project file:', err);
    }
    return false;
  }

  // Delete project file on disk
  public async deleteProjectFile(fileName: string): Promise<boolean> {
    try {
      await deleteProject(fileName);
      return true;
    } catch (err) {
      console.error('Failed to delete project file:', err);
      return false;
    }
  }

  // Duplicate project file cleanly (QuranCaption ProjectService.duplicate)
  public async duplicateProjectFile(fileName: string): Promise<boolean> {
    try {
      await duplicateProject(fileName);
      return true;
    } catch (err) {
      console.error('Failed to duplicate project file:', err);
      return false;
    }
  }

  // Load Entire Project
  public loadProject(newProject: AlignerProject) {
    Object.assign(this.project, JSON.parse(JSON.stringify(newProject)));
    this.historyStack = [];
    this.redoStack = [];
    this.updateHistoryFlags();
    this.clearScheduledAutosave();
    this.isDirty.value = false;
    this.saveStatus.value = 'saved';

    // Hydrate verified issue IDs from words marked verified
    const verified = new Set<string>();
    if (this.project.surahs) {
      for (const s of this.project.surahs) {
        for (const a of s.ayahs || []) {
          for (const seg of a.segments || []) {
            for (const w of seg.words || []) {
              if (w.is_verified && w.location) {
                // Match common issue ID prefixes
                verified.add(`trunc_${w.location}`);
                verified.add(`short_${w.location}`);
                verified.add(`collapse_${w.location}`);
                verified.add(`vad_cut_${w.location}`);
                verified.add(`absorbed_${w.location}`);
                verified.add(`low_conf_${w.location}`);
              }
            }
          }
        }
      }
    }
    this.resolvedIssueIds.value = verified;

    if (this.project.file_name) {
      try {
        localStorage.setItem('quran_last_project_file', this.project.file_name);
      } catch {}
    }

    if (this.project.surahs && this.project.surahs.length > 0) {
      const firstSurah = this.project.surahs[0];
      this.selectSurah(firstSurah.surah_number);
      if (firstSurah.audio_url) {
        this.activeAudioUrl.value = firstSurah.audio_url;
      } else if (firstSurah.audio_file) {
        this.activeAudioUrl.value = getAudioStreamUrl(firstSurah.audio_file);
      }
      if (firstSurah.audio_file) {
        this.activeAudioFilePath.value = firstSurah.audio_file;
      }
    } else {
      this.activeSurahNumber.value = null;
      this.activeAyahNumber.value = null;
      this.activeWordLocation.value = null;
      this.activeAudioUrl.value = null;
      this.activeAudioFilePath.value = null;
      this.currentTime.value = 0;
    }
  }
}

export const projectStore = new ProjectStore();
