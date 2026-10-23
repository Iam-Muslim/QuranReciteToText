export interface PhonemeItem {
  phoneme: string;
  start: number;
  end: number;
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
  is_verified?: boolean;
  phonemes?: PhonemeItem[];
  is_repetition?: boolean;
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
  issueSeverity?: 'critical' | 'warning' | 'info';
  issueBadgeLabel?: string;
  issueTooltip?: string;
  issueCount?: number;
}


export interface AyahItem {
  ayah: number;
  start: number;
  end: number;
  matched_ref?: string;
  segments: AyahSegment[];
  repeated_ranges?: string[];
  repeated_text?: string[];
  is_repetition?: boolean;
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
  waveform_url?: string;
  peaks?: number[];
  audio_duration_seconds?: number;
  /** Audio embedded as base64 inside exported .qproj files (portable/cloud transfer). Not persisted by autosave. */
  audio_embedded?: { name: string; mime: string; base64: string };
  status: SurahStatus;
  intro?: SurahIntro;
  ayahs: AyahItem[];
}

export interface CloudReciterProject {
  id: string;
  project_name: string;
  reciter: string;
  reciter_english?: string;
  riwayah: string;
  status?: SurahStatus;
  folder: string;
  audio_format?: string;
  available_surahs?: number[];
  total_surahs?: number;
  description?: string;
  updated_at?: string;
}

export interface CloudProjectItem {
  id: string;
  project_name: string;
  reciter: string;
  reciter_english?: string;
  riwayah: string;
  surah_number?: number;
  surah_name_arabic?: string;
  surah_name_english?: string;
  duration_seconds?: number;
  total_ayahs?: number;
  status?: SurahStatus;
  folder?: string;
  audio_format?: string;
  available_surahs?: number[];
  project_url?: string;
  audio_url?: string;
  waveform_url?: string;
  description?: string;
  size_bytes?: number;
}

export interface ProjectSettings {
  snapping_tolerance_ms: number;
  confidence_warning_threshold: number;
  auto_save_interval_s: number;
  reciter_name?: string;
  riwayah?: string;
  cloud_repo?: string;
  cloud_folder?: string;
  cloud_id?: string;
  cloud_origin?: boolean;
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
  cloud_origin?: boolean;
  cloud_repo?: string;
}

export type IssueSeverity = 'critical' | 'warning' | 'info';
export type IssueType = 
  | 'low_confidence'
  | 'sequence_inversion'
  | 'interleaved_twin'
  | 'coverage_gap'
  | 'duration_collapse'
  | 'abnormally_short'
  | 'truncated_phonemes'
  | 'vad_boundary_cut'
  | 'absorbed_silence'
  | 'large_gap'
  | 'tajweed_bridge'
  | 'repetition_pass';

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
  coverage?: number;
  duration?: number;
  expected_duration?: number;
  ref?: string;
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
