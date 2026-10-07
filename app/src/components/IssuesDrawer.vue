<template>
  <aside class="issues-drawer glass-panel" :class="{ 'drawer-open': projectStore.issuesDrawerOpen.value }">
    <!-- Header -->
    <div class="drawer-header">
      <div class="header-left">
        <AlertCircle :size="15" class="text-accent" />
        <span class="drawer-title">Auditor</span>
        <span class="issue-count" :class="{ 'all-resolved': pendingCount === 0 }" v-if="totalCount > 0">
          {{ pendingCount > 0 ? pendingCount : '✓ Done' }}
        </span>
      </div>
      <button class="btn-icon" @click="projectStore.issuesDrawerOpen.value = false" title="Close Drawer">
        <X :size="15" />
      </button>
    </div>

    <!-- Review Progress & Quick Jump (QuranCaption Pattern) -->
    <div class="review-status-box" v-if="projectStore.activeSurah.value">
      <div class="progress-info-row">
        <span class="progress-label">Surah Health</span>
        <span class="progress-val" :class="{ 'val-perfect': cleanPercent === 100 }">{{ cleanPercent }}% Clean</span>
      </div>
      <div class="progress-track">
        <div class="progress-fill" :style="{ width: `${cleanPercent}%` }" :class="{ 'fill-perfect': cleanPercent === 100 }"></div>
      </div>
      <div class="progress-sub-row">
        <span>{{ cleanAndVerifiedCount }} / {{ projectStore.surahStats.value.totalWords }} verified & clean</span>
        <span v-if="pendingCount > 0" class="text-pending-stat">{{ pendingCount }} pending</span>
        <span v-else class="text-done-stat">All reviewed ✓</span>
      </div>

      <!-- Quick Jump Button -->
      <button 
        class="jump-next-btn" 
        @click="projectStore.jumpToNextIssue()" 
        :disabled="totalCount === 0"
        :title="pendingCount > 0 ? 'Jump to next unverified issue (Tab key)' : 'Loop through issues (Tab key)'"
      >
        <Sparkles :size="12" />
        <span>{{ pendingCount > 0 ? 'Next Issue (Tab)' : 'Review Next (Tab)' }}</span>
        <ChevronRight :size="13" />
      </button>
    </div>

    <!-- Filter Pills -->
    <div class="filter-row" v-if="totalCount > 0">
      <button 
        class="filter-pill" 
        :class="{ 'active': activeFilter === 'pending' }"
        @click="activeFilter = 'pending'"
      >
        Pending ({{ pendingCount }})
      </button>
      <button 
        class="filter-pill" 
        :class="{ 'active': activeFilter === 'tajweed' }"
        @click="activeFilter = 'tajweed'"
        v-if="tajweedCount > 0"
        title="Tajweed merged boundaries (Iqlab, Idgham Mutamathilayn, Idgham Ghunnah)"
      >
        Tajweed ({{ tajweedCount }})
      </button>
      <button 
        class="filter-pill" 
        :class="{ 'active': activeFilter === 'twin' }"
        @click="activeFilter = 'twin'"
        v-if="twinCount > 0"
        title="Al-Buruj style leaps and sequence inversions"
      >
        Twins/Leap ({{ twinCount }})
      </button>
      <button 
        class="filter-pill" 
        :class="{ 'active': activeFilter === 'short' }"
        @click="activeFilter = 'short'"
        v-if="shortCount > 0"
        title="Abnormally short words, truncated phonemes, or VAD cuts"
      >
        Short/Cut ({{ shortCount }})
      </button>
      <button 
        class="filter-pill" 
        :class="{ 'active': activeFilter === 'gap' }"
        @click="activeFilter = 'gap'"
        v-if="gapCount > 0"
        title="Coverage gaps and absorbed silence"
      >
        Gaps ({{ gapCount }})
      </button>
      <button 
        class="filter-pill" 
        :class="{ 'active': activeFilter === 'resolved' }"
        @click="activeFilter = 'resolved'"
        v-if="resolvedCount > 0"
      >
        Done ({{ resolvedCount }})
      </button>
      <button 
        class="filter-pill" 
        :class="{ 'active': activeFilter === 'all' }"
        @click="activeFilter = 'all'"
      >
        All ({{ totalCount }})
      </button>
    </div>

    <!-- Issues List -->
    <div class="issues-list">
      <div 
        v-for="issue in filteredIssues" 
        :key="issue.id"
        class="issue-card"
        :class="{
          'card-selected': projectStore.activeWordLocation.value === issue.location,
          'card-verified': issue.resolved,
          'card-critical': !issue.resolved && issue.severity === 'critical',
          'card-warning': !issue.resolved && issue.severity === 'warning'
        }"
        @click="jumpToIssue(issue)"
      >
        <!-- Top bar: Word + Type Badge + Score/Verification indicator -->
        <div class="issue-card-top">
          <div class="word-group">
            <span class="word-arabic" :class="{ 'text-verified-word': issue.resolved }">{{ issue.word }}</span>
            <span class="location-badge">آية {{ issue.ayah_number }}</span>
          </div>

          <div class="top-status-pills">
            <span 
              class="issue-type-badge" 
              :class="getIssueBadgeClass(issue.type)"
            >
              {{ getIssueBadgeLabel(issue.type) }}
            </span>
          </div>
        </div>

        <!-- Issue message -->
        <div class="issue-msg" :class="{ 'msg-verified': issue.resolved }">
          {{ issue.message }}
        </div>

        <!-- Diagnostic Metrics Chips -->
        <div class="issue-metrics" v-if="issue.coverage !== undefined || issue.duration !== undefined || issue.ref">
          <span class="metric-chip" v-if="issue.coverage !== undefined" :class="issue.coverage < 0.70 ? 'metric-bad' : 'metric-warn'">
            Cov: {{ Math.round(issue.coverage * 100) }}%
          </span>
          <span class="metric-chip" v-if="issue.duration !== undefined">
            Dur: {{ issue.duration.toFixed(2) }}s
          </span>
          <span class="metric-chip" v-if="issue.expected_duration !== undefined">
            Exp: ~{{ issue.expected_duration.toFixed(2) }}s
          </span>
          <span class="metric-chip metric-ref" v-if="issue.ref" :title="`Canonical: ${issue.ref}`">
            {{ issue.ref }}
          </span>
        </div>

        <!-- Bottom bar: Timestamp + Fast Verification Action Button -->
        <div class="issue-card-footer">
          <span class="timestamp-label">{{ issue.timestamp.toFixed(2) }}s</span>

          <button 
            type="button"
            class="verify-btn" 
            :class="{ 'btn-is-verified': issue.resolved }"
            @click.stop="toggleVerify(issue)"
            :title="issue.resolved ? 'Click to mark unverified' : 'Mark as verified / reviewed (Key: V)'"
          >
            <CheckCheck :size="12" v-if="issue.resolved" />
            <Check :size="12" v-else />
            <span>{{ issue.resolved ? 'Verified' : 'Verify' }}</span>
          </button>
        </div>
      </div>

      <!-- Empty state when no issues match filter -->
      <div v-if="filteredIssues.length === 0" class="empty-state">
        <CheckCircle2 :size="28" class="text-green" />
        <span class="empty-title">{{ activeFilter === 'pending' && totalCount > 0 ? 'All Issues Verified!' : 'All Words Verified' }}</span>
        <span class="empty-desc">
          {{ activeFilter === 'pending' && totalCount > 0 
            ? 'All flagged anomalies in this Surah have been manually reviewed and resolved.' 
            : 'No confidence anomalies or acoustic mismatches detected in this filter.' 
          }}
        </span>
      </div>
    </div>
  </aside>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue';
import { projectStore } from '../services/projectStore';
import type { ConfidenceIssue, IssueType } from '../types/aligner';
import { 
  AlertCircle, 
  X, 
  CheckCircle2, 
  ChevronRight, 
  Sparkles, 
  Check, 
  CheckCheck 
} from 'lucide-vue-next';

type FilterType = 'pending' | 'tajweed' | 'twin' | 'short' | 'gap' | 'resolved' | 'all';
const activeFilter = ref<FilterType>('pending');

const totalCount = computed(() => projectStore.issues.value.length);
const pendingCount = computed(() => projectStore.issues.value.filter(i => !i.resolved).length);
const resolvedCount = computed(() => projectStore.issues.value.filter(i => i.resolved).length);

const tajweedCount = computed(() => {
  return projectStore.issues.value.filter(i => i.type === 'tajweed_bridge').length;
});

const twinCount = computed(() => {
  return projectStore.issues.value.filter(i => i.type === 'sequence_inversion' || i.type === 'interleaved_twin').length;
});

const shortCount = computed(() => {
  return projectStore.issues.value.filter(i => 
    i.type === 'abnormally_short' || 
    i.type === 'duration_collapse' || 
    i.type === 'truncated_phonemes' || 
    i.type === 'vad_boundary_cut'
  ).length;
});

const gapCount = computed(() => {
  return projectStore.issues.value.filter(i => 
    i.type === 'coverage_gap' || 
    i.type === 'large_gap' || 
    i.type === 'absorbed_silence'
  ).length;
});

const cleanAndVerifiedCount = computed(() => {
  const stats = projectStore.surahStats.value;
  return Math.min(stats.totalWords, stats.cleanWords + stats.resolvedIssues);
});

const cleanPercent = computed(() => {
  const stats = projectStore.surahStats.value;
  if (!stats.totalWords) return 100;
  return Math.min(100, Math.round((cleanAndVerifiedCount.value / stats.totalWords) * 100));
});

const filteredIssues = computed(() => {
  const all = projectStore.issues.value;
  switch (activeFilter.value) {
    case 'pending':
      return all.filter(i => !i.resolved);
    case 'tajweed':
      return all.filter(i => i.type === 'tajweed_bridge');
    case 'twin':
      return all.filter(i => i.type === 'sequence_inversion' || i.type === 'interleaved_twin');
    case 'short':
      return all.filter(i => 
        i.type === 'abnormally_short' || 
        i.type === 'duration_collapse' || 
        i.type === 'truncated_phonemes' || 
        i.type === 'vad_boundary_cut'
      );
    case 'gap':
      return all.filter(i => 
        i.type === 'coverage_gap' || 
        i.type === 'large_gap' || 
        i.type === 'absorbed_silence'
      );
    case 'resolved':
      return all.filter(i => i.resolved);
    case 'all':
    default:
      return all;
  }
});

function jumpToIssue(issue: ConfidenceIssue) {
  projectStore.selectWord(issue.location, true, issue.timestamp);
}

function toggleVerify(issue: ConfidenceIssue) {
  projectStore.toggleIssueVerified(issue.id);
}

function getIssueBadgeLabel(type: IssueType): string {
  switch (type) {
    case 'sequence_inversion':
      return 'Leap / Inversion';
    case 'tajweed_bridge':
      return 'Tajweed Merge';
    case 'interleaved_twin':
      return 'Twin Interleaved';
    case 'duration_collapse':
      return 'Collapsed (<0.08s)';
    case 'abnormally_short':
      return 'Abnormally Short';
    case 'truncated_phonemes':
      return 'Truncated Cut';
    case 'vad_boundary_cut':
      return 'VAD Boundary Cut';
    case 'absorbed_silence':
      return 'Absorbed Silence';
    case 'coverage_gap':
      return 'Missing Word';
    case 'large_gap':
      return 'Silence Gap';
    default:
      return 'Low Confidence';
  }
}

function getIssueBadgeClass(type: IssueType): string {
  switch (type) {
    case 'sequence_inversion':
      return 'badge-danger';
    case 'tajweed_bridge':
      return 'badge-indigo';
    case 'interleaved_twin':
      return 'badge-purple';
    case 'duration_collapse':
      return 'badge-danger';
    case 'abnormally_short':
    case 'truncated_phonemes':
      return 'badge-warn';
    case 'vad_boundary_cut':
      return 'badge-indigo';
    case 'absorbed_silence':
      return 'badge-blue';
    case 'coverage_gap':
      return 'badge-danger';
    case 'large_gap':
      return 'badge-muted';
    default:
      return 'badge-warn';
  }
}
</script>

<style scoped>
.issues-drawer {
  width: 290px;
  height: calc(100vh - var(--header-height));
  position: fixed;
  right: 0;
  top: var(--header-height);
  background: var(--bg-surface);
  border-left: 1px solid var(--border-subtle);
  display: flex;
  flex-direction: column;
  z-index: 40;
  transform: translateX(100%);
  transition: transform 0.2s cubic-bezier(0.16, 1, 0.3, 1);
  box-shadow: -8px 0 25px rgba(0, 0, 0, 0.5);
}

.issues-drawer.drawer-open {
  transform: translateX(0);
}

.drawer-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 14px;
  border-bottom: 1px solid var(--border-subtle);
  background: rgba(15, 23, 42, 0.4);
}

.header-left {
  display: flex;
  align-items: center;
  gap: 6px;
}

.drawer-title {
  font-size: 0.82rem;
  font-weight: 600;
  color: #fff;
}

.issue-count {
  background: #ef4444;
  color: white;
  font-size: 0.65rem;
  font-weight: 700;
  padding: 1px 6px;
  border-radius: 8px;
}

.issue-count.all-resolved {
  background: #10b981;
}

/* QuranCaption Review Status Box */
.review-status-box {
  padding: 10px 12px;
  background: rgba(10, 15, 26, 0.6);
  border-bottom: 1px solid var(--border-subtle);
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.progress-info-row {
  display: flex;
  justify-content: space-between;
  font-size: 11px;
}

.progress-label {
  color: var(--text-muted);
}

.progress-val {
  color: #10b981;
  font-weight: 600;
}

.progress-val.val-perfect {
  color: #34d399;
}

.progress-track {
  width: 100%;
  height: 5px;
  background: rgba(255, 255, 255, 0.08);
  border-radius: 3px;
  overflow: hidden;
}

.progress-fill {
  height: 100%;
  background: linear-gradient(90deg, #10b981, #34d399);
  transition: width 0.3s ease;
}

.progress-fill.fill-perfect {
  background: linear-gradient(90deg, #10b981, #6ee7b7);
}

.progress-sub-row {
  display: flex;
  justify-content: space-between;
  font-size: 10px;
  color: var(--text-muted);
}

.text-pending-stat {
  color: #f87171;
  font-weight: 600;
}

.text-done-stat {
  color: #34d399;
  font-weight: 600;
}

.jump-next-btn {
  margin-top: 4px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: rgba(94, 106, 210, 0.15);
  border: 1px solid rgba(94, 106, 210, 0.35);
  color: var(--accent-primary);
  border-radius: 6px;
  padding: 6px 10px;
  font-size: 11px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.12s ease;
}

.jump-next-btn:hover:not(:disabled) {
  background: rgba(94, 106, 210, 0.28);
  border-color: var(--accent-primary);
  color: #fff;
}

.jump-next-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.filter-row {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  padding: 6px 10px;
  border-bottom: 1px solid var(--border-subtle);
  background: rgba(15, 23, 42, 0.2);
}

.filter-pill {
  background: transparent;
  border: 1px solid var(--border-subtle);
  color: var(--text-muted);
  border-radius: 12px;
  padding: 2px 7px;
  font-size: 0.65rem;
  cursor: pointer;
  transition: all 0.1s ease;
}

.filter-pill:hover {
  border-color: rgba(255, 255, 255, 0.2);
  color: #e2e8f0;
}

.filter-pill.active {
  background: rgba(94, 106, 210, 0.2);
  border-color: var(--accent-primary);
  color: #fff;
}

.issues-list {
  flex: 1;
  overflow-y: auto;
  padding: 8px 10px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.issue-card {
  background: rgba(15, 23, 42, 0.45);
  border-radius: 6px;
  padding: 8px 10px;
  border: 1px solid var(--border-subtle);
  cursor: pointer;
  transition: all 0.15s ease;
  position: relative;
}

.issue-card:hover {
  background: rgba(15, 23, 42, 0.75);
  border-color: rgba(255, 255, 255, 0.22);
}

.card-selected {
  border-color: #38bdf8 !important;
  background: rgba(56, 189, 248, 0.12) !important;
}

.card-critical {
  border-left: 3px solid #ef4444;
}

.card-warning {
  border-left: 3px solid #f59e0b;
}

/* User-Verified State (Turns Green & Marked As Done) */
.card-verified {
  background: rgba(16, 185, 129, 0.08) !important;
  border-color: rgba(16, 185, 129, 0.35) !important;
  border-left: 3px solid #10b981 !important;
  opacity: 0.88;
}

.card-verified:hover {
  opacity: 1;
  background: rgba(16, 185, 129, 0.15) !important;
  border-color: rgba(16, 185, 129, 0.5) !important;
}

.text-verified-word {
  color: #6ee7b7 !important;
}

.issue-card-top {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 4px;
}

.word-group {
  display: flex;
  align-items: baseline;
  gap: 6px;
}

.word-arabic {
  font-family: 'Amiri Quran', 'Scheherazade New', serif;
  font-size: 1.15rem;
  color: #fff;
  line-height: 1.2;
}

.location-badge {
  font-size: 0.65rem;
  color: var(--text-muted);
}

.top-status-pills {
  display: flex;
  align-items: center;
  gap: 4px;
}

.issue-type-badge {
  font-size: 0.62rem;
  font-weight: 600;
  padding: 1px 5px;
  border-radius: 4px;
  font-family: var(--font-mono);
  letter-spacing: -0.2px;
}

.badge-danger {
  background: rgba(239, 68, 68, 0.18);
  color: #f87171;
  border: 1px solid rgba(239, 68, 68, 0.35);
}

.badge-warn {
  background: rgba(245, 158, 11, 0.18);
  color: #fbbf24;
  border: 1px solid rgba(245, 158, 11, 0.35);
}

.badge-purple {
  background: rgba(168, 85, 247, 0.18);
  color: #c084fc;
  border: 1px solid rgba(168, 85, 247, 0.35);
}

.badge-indigo {
  background: rgba(99, 102, 241, 0.18);
  color: #818cf8;
  border: 1px solid rgba(99, 102, 241, 0.35);
}

.badge-blue {
  background: rgba(59, 130, 246, 0.18);
  color: #60a5fa;
  border: 1px solid rgba(59, 130, 246, 0.35);
}

.badge-muted {
  background: rgba(148, 163, 184, 0.15);
  color: #94a3b8;
  border: 1px solid rgba(148, 163, 184, 0.3);
}

.issue-msg {
  font-size: 10px;
  color: #cbd5e1;
  margin-bottom: 5px;
  line-height: 1.35;
}

.msg-verified {
  color: var(--text-muted);
}

/* Diagnostic Metrics Chips */
.issue-metrics {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-bottom: 6px;
}

.metric-chip {
  font-family: var(--font-mono);
  font-size: 0.6rem;
  padding: 1px 4px;
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 3px;
  color: #94a3b8;
}

.metric-bad {
  color: #f87171;
  border-color: rgba(239, 68, 68, 0.25);
  background: rgba(239, 68, 68, 0.1);
}

.metric-warn {
  color: #fbbf24;
  border-color: rgba(245, 158, 11, 0.25);
  background: rgba(245, 158, 11, 0.1);
}

.metric-ref {
  direction: rtl;
  font-family: 'Amiri Quran', serif;
  color: #cbd5e1;
}

/* Footer & Verify Action Button */
.issue-card-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: 2px;
  padding-top: 4px;
  border-top: 1px solid rgba(255, 255, 255, 0.05);
}

.timestamp-label {
  font-family: var(--font-mono);
  font-size: 0.65rem;
  color: var(--text-muted);
}

.verify-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 0.66rem;
  font-weight: 600;
  padding: 2px 8px;
  border-radius: 4px;
  cursor: pointer;
  background: rgba(255, 255, 255, 0.06);
  border: 1px solid rgba(255, 255, 255, 0.14);
  color: #cbd5e1;
  transition: all 0.12s ease;
}

.verify-btn:hover {
  background: rgba(16, 185, 129, 0.18);
  border-color: rgba(16, 185, 129, 0.4);
  color: #34d399;
}

.verify-btn.btn-is-verified {
  background: rgba(16, 185, 129, 0.22);
  border-color: #10b981;
  color: #34d399;
}

.verify-btn.btn-is-verified:hover {
  background: rgba(239, 68, 68, 0.18);
  border-color: rgba(239, 68, 68, 0.4);
  color: #f87171;
}

.empty-state {
  text-align: center;
  padding: 36px 16px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
}

.text-green { color: #10b981; }
.empty-title { font-size: 0.85rem; font-weight: 600; color: #fff; }
.empty-desc { font-size: 0.72rem; color: var(--text-muted); line-height: 1.35; }
</style>
