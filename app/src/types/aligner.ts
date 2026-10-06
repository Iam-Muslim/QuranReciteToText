export interface PhonemeItem {
  phoneme: string;
  start: number;
  end: number;
  rule?: string;
  golden_len?: number;
}

export interface AlignedWord {
  word: string;
  location: string;
  ref?: string;
  start: number;
  end: number;
  score: number;
  is_edited?: boolean;
  is_phantom?: boolean;
  phonemes?: PhonemeItem[];
}

export interface AyahSegment {
  segment: number;
  start: number;
  end: number;
  transcribed_text?: string;
  words_range?: string;
  is_repetition?: boolean;
  words: AlignedWord[];
}

export interface TimelineSegmentItem {
  id: string;
  surahNumber: number;
  ayahNumber: number;
  segmentIndex: number;
  type: 'intro' | 'segment';
  label: string;
  start: number;
  end: number;
  duration: number;
  isRepetition: boolean;
  transcribedText?: string;
  connectedUthmaniText: string;
  words: AlignedWord[];
  hasIssues: boolean;
  hasCoverageGap?: boolean;
  gapWarning?: string;
}


export interface AyahItem {
  ayah: number;
  start: number;
  end: number;
  matched_ref?: string;
  segments: AyahSegment[];
  repeated_ranges?: string[];
  repeated_text?: string[];
}

export interface SurahIntro {
  text: string;
  start: number;
  end: number;
  words?: AlignedWord[];
}

export type SurahStatus = 'verified' | 'needs_review' | 'aligned' | 'unaligned';

export interface SurahItem {
  surah_number: number;
  surah_name_arabic: string;
  surah_name_english: string;
  audio_file?: string;
  audio_url?: string;
  audio_duration_seconds?: number;
  status: SurahStatus;
  intro?: SurahIntro;
  ayahs: AyahItem[];
}

export interface ProjectSettings {
  snapping_tolerance_ms: number;
  confidence_warning_threshold: number;
  auto_save_interval_s: number;
  reciter_name?: string;
  riwayah?: string;
}

export interface AlignerProject {
  file_name?: string;
  project_name: string;
  reciter?: string;
  app_version: string;
  created_at: string;
  updated_at: string;
  settings: ProjectSettings;
  surahs: SurahItem[];
}

export interface ProjectSummary {
  file_name: string;
  project_name: string;
  reciter?: string;
  riwayah?: string;
  status?: string;
  surahs_count: number;
  surah_numbers?: number[];
  primary_surah?: {
    surah_number: number;
    surah_name_arabic?: string;
    surah_name_english?: string;
  } | null;
  total_ayahs: number;
  total_duration: number;
  created_at?: string;
  updated_at: string;
  size_bytes: number;
}

export type IssueSeverity = 'critical' | 'warning' | 'info';
export type IssueType = 'low_confidence' | 'large_gap' | 'overlap' | 'coverage_gap';

export interface ConfidenceIssue {
  id: string;
  surah_number: number;
  ayah_number: number;
  location: string;
  word: string;
  timestamp: number;
  score: number;
  type: IssueType;
  message: string;
  severity: IssueSeverity;
  resolved: boolean;
}

export interface HistoryAction {
  description: string;
  timestamp: number;
  undo: () => void;
  redo: () => void;
}

export interface AlignmentProgressEvent {
  stage: 'idle' | 'loading' | 'vad' | 'transcribing' | 'recovering' | 'aligning' | 'matching' | 'completed' | 'error';
  percent?: number;
  elapsed?: number;
  speed_x?: number;
  message?: string;
}

export type StudioViewMode = 'mushaf_page' | 'ayah_studio' | 'phoneme_inspector';
export type StudioLoopMode = 'none' | 'ayah' | 'word';
