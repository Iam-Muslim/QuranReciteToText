import { reactive, computed, ref, toRaw } from 'vue';
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
  StudioLoopMode,
  SurahStatus
} from '../types/aligner';

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
  resolveAudioSourceUrl,
  isTauriEnvironment,
  saveProject, 
  createProject, 
  loadProject, 
  deleteProject, 
  duplicateProject 
} from './api';
import { vaultSave, vaultLoad, vaultDelete, vaultDuplicate, persistProjectAudio, safeProjectFileName } from './projectVault';
import { auditSurah } from './auditorEngine';
import { historyManager } from './historyManager';
import { AutosaveService, type SaveStatus } from './autosaveService';
import { isIntroSegment, parseQuranCaptionSegments, parseCanonicalSurahs } from './segmentIngest';
import type { Ref } from 'vue';

export { getApiBaseUrl, getAudioStreamUrl, isIntroSegment };

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
  public sidebarCollapsed = ref<boolean>(false);
  public isAuditing = ref<boolean>(true);
  public resolvedIssueIds = ref<Set<string>>(new Set());

  // Typography Sizing
  public mushafFontSize = ref<number>(
    typeof localStorage !== 'undefined' ? (Number(localStorage.getItem('quran_mushaf_font_size')) || 1.95) : 1.95
  );

  public setMushafFontSize(size: number) {
    const clamped = Math.max(1.3, Math.min(3.2, Number(size.toFixed(2))));
    this.mushafFontSize.value = clamped;
    try { localStorage.setItem('quran_mushaf_font_size', String(clamped)); } catch {}
  }

  // Undo / Redo Stack & Auto-Save
  public history = historyManager;
  public canUndo = historyManager.canUndo;
  public canRedo = historyManager.canRedo;
  public autosave: AutosaveService;
  public isDirty: Ref<boolean>;
  public isSaving: Ref<boolean>;
  public lastSavedAt: Ref<Date | null>;
  public saveStatus: Ref<SaveStatus>;

  constructor() {
    this.autosave = new AutosaveService({
      saveFn: () => this.saveActiveProject(),
      canSavePredicate: () => {
        return !this.isPlaying.value;
      }
    });
    this.isDirty = this.autosave.isDirty;
    this.isSaving = this.autosave.isSaving;
    this.lastSavedAt = this.autosave.lastSavedAt;
    this.saveStatus = this.autosave.saveStatus;
  }

  public scheduleAutosave(): void {
    this.autosave.schedule();
  }

  public clearScheduledAutosave(): void {
    this.autosave.clearSchedule();
  }

  public async flushAutosave(): Promise<void> {
    await this.autosave.flush();
  }

  public async saveActiveProject(): Promise<boolean> {
    if (!this.project || !this.project.project_name) return false;
    this.isSaving.value = true;
    this.saveStatus.value = 'saving';

    try {
      if (isTauriEnvironment()) {
        if (!this.project.file_name) {
          this.project.file_name = `${this.project.project_name}.qproj`;
        }
        const fileName = this.project.file_name;
        await saveProject(fileName, this.buildPersistentSnapshot());
      } else {
        // Browser vault: same snapshot shape, audio blobs stored beside it
        if (!this.project.file_name) {
          this.project.file_name = await this.uniqueWebFileName(safeProjectFileName(this.project.project_name));
        }
        const fileName = this.project.file_name;
        await vaultSave(fileName, this.buildPersistentSnapshot());
        await persistProjectAudio(fileName, this.project.surahs || []);
      }
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

  /**
   * A name in the vault is only taken if a DIFFERENT project (different
   * created_at) already owns it — so repeat autosaves keep their key while
   * unrelated projects with identical names never clobber each other.
   */
  private async uniqueWebFileName(preferred: string): Promise<string> {
    try {
      const existing = await vaultLoad(preferred);
      if (existing && existing.project.created_at !== this.project.created_at) {
        const base = preferred.replace(/\.qproj$/i, '');
        let n = 2;
        let candidate = `${base} (${n}).qproj`;
        let clash = await vaultLoad(candidate);
        while (clash && clash.project.created_at !== this.project.created_at) {
          candidate = `${base} (${++n}).qproj`;
          clash = await vaultLoad(candidate);
        }
        return candidate;
      }
    } catch { /* vault unreadable — fall through to preferred */ }
    return preferred;
  }

  /**
   * Disk-safe copy of the project: strips runtime-only audio sources
   * (blob:/data: URLs die with the session) and embedded audio payloads
   * (kept for explicit portable exports, not for autosave).
   * Uses toRaw to prevent recursive Proxy getter evaluation.
   */
  public buildPersistentSnapshot(): AlignerProject {
    const raw = toRaw(this.project);
    const surahs = (raw.surahs || []).map(s => {
      const rawS = toRaw(s);
      const isCustomUrl = typeof rawS.audio_url === 'string' && /^(blob|data):/.test(rawS.audio_url);
      const hasEmbedded = 'audio_embedded' in rawS;
      if (!isCustomUrl && !hasEmbedded) {
        return rawS;
      }
      const sCopy = { ...rawS };
      if (isCustomUrl) sCopy.audio_url = '';
      if (hasEmbedded) delete (sCopy as any).audio_embedded;
      return sCopy;
    });

    return {
      ...raw,
      surahs,
    };
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
    const surahIssues = this.issues.value.filter(i => !i.resolved);

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

        // Cross-match unresolved auditor issues to this segment
        const segWordLocations = new Set(segWords.map(w => w.location).filter(Boolean));
        const matchingIssues = surahIssues.filter(iss => {
          if (iss.location && segWordLocations.has(iss.location)) return true;
          if (iss.ayah_number === a.ayah) {
            if (iss.timestamp >= start - 0.25 && iss.timestamp <= end + 0.25) return true;
            if (iss.type === 'coverage_gap') return true;
          }
          return false;
        });

        const hasIssues = matchingIssues.length > 0 || segWords.some(w => w.score < 0.85);
        const issueCount = matchingIssues.length;
        const hasCritical = matchingIssues.some(i => i.severity === 'critical');
        const issueSeverity: 'critical' | 'warning' | 'info' = hasCritical ? 'critical' : (hasIssues ? 'warning' : 'info');

        let issueBadgeLabel = '';
        if (matchingIssues.length > 0) {
          const first = matchingIssues[0];
          switch (first.type) {
            case 'tajweed_bridge': issueBadgeLabel = 'تجويد'; break;
            case 'interleaved_twin': issueBadgeLabel = 'قفز توأم'; break;
            case 'sequence_inversion': issueBadgeLabel = 'انقلاب ترتيب'; break;
            case 'coverage_gap': issueBadgeLabel = 'كلمة ناقصة'; break;
            case 'truncated_phonemes': issueBadgeLabel = 'بتر صوتي'; break;
            case 'large_gap': issueBadgeLabel = 'فجوة صمت'; break;
            case 'low_confidence': issueBadgeLabel = 'شك صوتي'; break;
            case 'duration_collapse': issueBadgeLabel = 'قصر مدة'; break;
            case 'abnormally_short': issueBadgeLabel = 'مدة خاطفة'; break;
            default: issueBadgeLabel = 'تنبيه'; break;
          }
          if (matchingIssues.length > 1) {
            issueBadgeLabel += ` (+${matchingIssues.length - 1})`;
          }
        } else if (hasIssues) {
          issueBadgeLabel = 'شك صوتي';
        }

        const issueTooltip = matchingIssues.length > 0
          ? matchingIssues.map(i => `• ${i.message}`).join('\n')
          : (hasIssues ? 'دقة المحاذاة أقل من 85%' : undefined);

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
          issueSeverity,
          issueBadgeLabel,
          issueTooltip,
          issueCount,
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
      const cur = this.findWordByLocation(this.currentKaraokeLocation.value, t);
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
    const threshold = this.project.settings?.confidence_warning_threshold || 0.85;
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
    this.history.record(action, () => {
      this.autosave.markDirty();
    });
  }

  public undo() {
    this.history.undo(() => {
      this.autosave.markDirty();
    });
  }

  public redo() {
    this.history.redo(() => {
      this.autosave.markDirty();
    });
  }

  // Navigation
  public selectSurah(surahNum: number) {
    this.activeSurahNumber.value = surahNum;
    const s = this.project.surahs.find(item => item.surah_number === surahNum);
    if (s) {
      const effectiveAudioUrl = resolveAudioSourceUrl(s);
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

  /**
   * Review toggle for a whole project from the Projects hub — the hub-side
   * twin of the sidebar's per-surah ✓ button: one click marks every surah
   * reviewed (or sends everything back to review). Works on both desktop
   * files and browser-vault projects; returns true when the project ended
   * up verified.
   */
  public async toggleProjectReview(fileName: string): Promise<boolean> {
    const applyTarget = (surahs: any[]): boolean => {
      const allDone = surahs.length > 0 && surahs.every(s => s.status === 'verified');
      const target = allDone ? 'needs_review' : 'verified';
      surahs.forEach(s => { s.status = target; });
      return target === 'verified';
    };
    try {
      if (!isTauriEnvironment()) {
        const vaultData = await vaultLoad(fileName);
        if (!vaultData?.project) return false;
        const nowVerified = applyTarget(vaultData.project.surahs || []);
        vaultData.project.updated_at = new Date().toISOString();
        await vaultSave(fileName, vaultData.project);
        return nowVerified;
      }
      const data = await loadProject(fileName);
      if (!data) return false;
      const nowVerified = applyTarget(data.surahs || []);
      (data as any).updated_at = new Date().toISOString();
      await saveProject(fileName, data);
      return nowVerified;
    } catch (err) {
      console.error('Failed to toggle project review state:', err);
      return false;
    } finally {
      // If this project is open in the studio, mirror the change live
      if (this.project.file_name === fileName && this.project.surahs?.length) {
        const src = await this.readProjectStatuses(fileName);
        if (src) this.project.surahs.forEach(s => { s.status = src; });
        this.isDirty.value = true;
        this.scheduleAutosave();
      }
    }
  }

  /** Status of every surah in a stored project ('verified' | 'needs_review'). */
  private async readProjectStatuses(fileName: string): Promise<SurahStatus | null> {
    try {
      if (!isTauriEnvironment()) {
        const vaultData = await vaultLoad(fileName);
        if (!vaultData?.project) return null;
        return vaultData.project.surahs?.[0]?.status ?? null;
      }
      const data = await loadProject(fileName);
      return data?.surahs?.[0]?.status ?? null;
    } catch {
      return null;
    }
  }

  // Ingest Canonical Pipeline Output JSON Directly (Supports Multi-Surah Recitations)
  public loadAlignedSurah(canonicalOutput: any, audioPath?: string, audioUrl?: string) {
    if (!canonicalOutput) return;

    const { surahs, firstAddedSurahNum } = parseCanonicalSurahs(canonicalOutput, audioPath, audioUrl);
    if (surahs.length === 0) return;

    for (const newSurahObj of surahs) {
      const existingIdx = this.project.surahs.findIndex(s => s.surah_number === newSurahObj.surah_number);
      if (existingIdx !== -1) {
        this.project.surahs[existingIdx] = newSurahObj;
      } else {
        this.project.surahs.push(newSurahObj);
      }
    }

    if (firstAddedSurahNum !== null) {
      this.activeSurahNumber.value = null;
      this.selectSurah(firstAddedSurahNum);
      const firstSurah = this.project.surahs.find(s => s.surah_number === firstAddedSurahNum);
      if (firstSurah) {
        const effectiveUrl = resolveAudioSourceUrl(firstSurah);
        if (effectiveUrl) {
          firstSurah.audio_url = effectiveUrl;
          this.activeAudioUrl.value = effectiveUrl;
        }
        if (firstSurah.audio_file) {
          this.activeAudioFilePath.value = firstSurah.audio_file;
        }
      }
      this.currentTab.value = 'studio';
    }

    this.isDirty.value = true;
    this.scheduleAutosave();
    this.flushAutosave().catch(() => {});
  }

  /**
   * Ingests QuranCaption timeline segments directly, decomposing breath groups
   * into canonical Surahs and Ayahs, normalizing relative word timestamps into absolute
   * seconds matching the WaveformEditor coordinate space.
   */
  public ingestQuranCaptionSegments(segments: any[], audioPath?: string, audioUrl?: string) {
    if (!segments || segments.length === 0) return;

    const { surahs, firstAddedSurahNum } = parseQuranCaptionSegments(segments, audioPath, audioUrl);
    if (surahs.length === 0) return;

    for (const newSurahObj of surahs) {
      const existingIdx = this.project.surahs.findIndex(s => s.surah_number === newSurahObj.surah_number);
      if (existingIdx !== -1) {
        this.project.surahs[existingIdx] = newSurahObj;
      } else {
        this.project.surahs.push(newSurahObj);
      }
    }

    if (firstAddedSurahNum !== null) {
      this.activeSurahNumber.value = null;
      this.selectSurah(firstAddedSurahNum);
      const firstSurah = this.project.surahs.find(s => s.surah_number === firstAddedSurahNum);
      if (firstSurah) {
        const urlToUse = resolveAudioSourceUrl(firstSurah);
        if (urlToUse) {
          firstSurah.audio_url = urlToUse;
          this.activeAudioUrl.value = urlToUse;
        }
        if (firstSurah.audio_file) {
          this.activeAudioFilePath.value = firstSurah.audio_file;
        }
      }
      this.currentTab.value = 'studio';
    }

    this.isDirty.value = true;
    this.scheduleAutosave();
    this.flushAutosave().catch(() => {});
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

  // Create New Project — desktop writes via Tauri IPC, browser via the vault
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
      if (!isTauriEnvironment()) {
        projectData.file_name = safeProjectFileName(name);
        await vaultSave(projectData.file_name, projectData as AlignerProject);
        this.loadProject(projectData as AlignerProject);
        this.currentTab.value = 'studio';
        return true;
      }
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

  // Open Project by file name (.qproj) — desktop disk or browser vault
  public async openProjectByFileName(fileName: string): Promise<boolean> {
    try {
      if (!isTauriEnvironment()) {
        const vaultData = await vaultLoad(fileName);
        if (vaultData?.project) {
          const data = vaultData.project;
          data.file_name = fileName;
          this.loadProject(data);
          // Session audio lives in the vault — rebuild blob URLs for surahs
          // that have no session/embedded source.
          for (const s of this.project.surahs || []) {
            if (!vaultData.audio.has(s.surah_number)) continue;
            const custom = typeof s.audio_url === 'string' && /^(blob|data):/.test(s.audio_url);
            if (custom) continue;
            const blob = vaultData.audio.get(s.surah_number);
            if (blob) {
              s.audio_url = URL.createObjectURL(blob);
              if (this.activeSurah.value === s) {
                this.activeAudioUrl.value = s.audio_url;
              }
            }
          }
          this.currentTab.value = 'studio';
          return true;
        }
        return false;
      }
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

  // Delete project file on disk (desktop) or in the browser vault
  public async deleteProjectFile(fileName: string): Promise<boolean> {
    try {
      if (!isTauriEnvironment()) await vaultDelete(fileName);
      else await deleteProject(fileName);
      return true;
    } catch (err) {
      console.error('Failed to delete project file:', err);
      return false;
    }
  }

  // Duplicate project file cleanly (QuranCaption ProjectService.duplicate)
  public async duplicateProjectFile(fileName: string): Promise<boolean> {
    try {
      if (!isTauriEnvironment()) {
        const newName = await vaultDuplicate(fileName);
        return !!newName;
      }
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
    this.history.clear();

    // Hydrate embedded (portable) audio: data URLs are valid everywhere,
    // and getAudioStreamUrl passes them through untouched.
    for (const s of this.project.surahs || []) {
      const emb = (s as any).audio_embedded;
      if (emb?.base64 && !(typeof s.audio_url === 'string' && /^(blob|data):/.test(s.audio_url))) {
        s.audio_url = `data:${emb.mime || 'audio/mpeg'};base64,${emb.base64}`;
      }
    }

    this.autosave.markClean();

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
      // Session-custom sources (data:/blob: — e.g. embedded portable audio) win over paths;
      // a bare "name.ext" in audio_file is not a real path (browser-imported sessions).
      const effUrl = resolveAudioSourceUrl(firstSurah);
      if (effUrl) {
        firstSurah.audio_url = effUrl;
        this.activeAudioUrl.value = effUrl;
      }
      if (firstSurah.audio_file) {
        this.activeAudioFilePath.value = firstSurah.audio_file;
      }
      this.activeSurahNumber.value = null;
      this.selectSurah(firstSurah.surah_number);
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
