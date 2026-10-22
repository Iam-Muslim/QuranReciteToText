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

    <!-- Review Progress & Quick Jump — slim single row -->
    <div class="review-status-box" v-if="projectStore.activeSurah.value">
      <div class="health-row">
        <div class="health-bar">
          <div
            class="health-bar-fill"
            :class="{ 'is-perfect': cleanPercent === 100 }"
            :style="{ width: `${cleanPercent}%` }"
          ></div>
        </div>
        <span class="health-value" :class="{ 'is-perfect': cleanPercent === 100 }">
          {{ cleanPercent }}%
        </span>
        <button 
          class="jump-next-btn" 
          @click="projectStore.jumpToNextIssue()" 
          :disabled="totalCount === 0"
          :title="pendingCount > 0 ? 'Jump to next unverified issue (Tab key)' : 'Loop through issues (Tab key)'"
        >
          <span>{{ pendingCount > 0 ? pendingCount : '✓' }}</span>
          <ChevronRight :size="12" />
        </button>
      </div>
    </div>

    <!-- Filter Pills -->
    <div class="filter-row" v-if="totalCount > 0">
      <button 
        class="filter-pill" 
        :class="{ 'active': activeFilter === 'pending', 'pill-warn': pendingCount > 0 }"
        @click="activeFilter = 'pending'"
      >
        Pending ({{ pendingCount }})
      </button>
      <button 
        class="filter-pill" 
        :class="{ 'active': activeFilter === 'tajweed' }"
        @click="activeFilter = 'tajweed'"
        v-if="tajweedCount > 0"
        title="Tajweed boundary merges"
      >
        Tajweed ({{ tajweedCount }})
      </button>
      <button 
        class="filter-pill" 
        :class="{ 'active': activeFilter === 'twin' }"
        @click="activeFilter = 'twin'"
        v-if="twinCount > 0"
        title="Leaps / Inversions"
      >
        Leap ({{ twinCount }})
      </button>
      <button 
        class="filter-pill" 
        :class="{ 'active': activeFilter === 'short' }"
        @click="activeFilter = 'short'"
        v-if="shortCount > 0"
        title="Short words"
      >
        Short ({{ shortCount }})
      </button>
      <button 
        class="filter-pill" 
        :class="{ 'active': activeFilter === 'gap' }"
        @click="activeFilter = 'gap'"
        v-if="gapCount > 0"
        title="Gaps & silence"
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
        title="All issues"
      >
        All ({{ totalCount }})
      </button>
    </div>

    <!-- Issues List -->
    <div class="issues-list stagger">
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
  width: var(--drawer-width);
  height: calc(100vh - var(--header-height));
  position: fixed;
  right: 0;
  top: var(--header-height);
  background: var(--glass-bg);
  backdrop-filter: blur(12px) saturate(1.4);
  -webkit-backdrop-filter: blur(12px) saturate(1.4);
  border-left: 1px solid var(--glass-border);
  display: flex;
  flex-direction: column;
  z-index: 40;
  transform: translateX(100%);
  transition: transform var(--dur-over) var(--ease-spring);
  box-shadow: -8px 0 32px rgba(0, 0, 0, 0.55);
}

.issues-drawer.drawer-open {
  transform: translateX(0);
}

@media (max-width: 760px) {
  .issues-drawer {
    width: min(92vw, var(--drawer-width));
  }
}

.drawer-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 14px;
  border-bottom: 1px solid var(--border-subtle);
}

.header-left {
  display: flex;
  align-items: center;
  gap: 6px;
}

.drawer-title {
  font-size: 0.82rem;
  font-weight: 600;
  color: var(--text-main);
}

.issue-count {
  background: var(--ruby-primary);
  color: white;
  font-size: 0.65rem;
  font-weight: 700;
  padding: 1px 7px;
  border-radius: var(--radius-pill);
  box-shadow: var(--shadow-e1);
}

.issue-count.all-resolved {
  background: var(--emerald-primary);
  box-shadow: var(--shadow-e1);
}

/* Review Status Box - slim single row */
.review-status-box {
  padding: 8px 12px;
  background: var(--bg-surface);
  border-bottom: 1px solid var(--border-subtle);
}

.health-row {
  display: flex;
  align-items: center;
  gap: 8px;
}

.health-bar {
  flex: 1;
  height: 4px;
  background: var(--border-medium);
  border-radius: var(--radius-pill);
  overflow: hidden;
}

.health-bar-fill {
  height: 100%;
  background: var(--accent-primary);
  border-radius: var(--radius-pill);
  box-shadow: var(--shadow-e1);
  transition: width var(--dur-rise) var(--ease-spring),
              background var(--dur-base) var(--ease-out);
}
.health-bar-fill.is-perfect {
  background: var(--emerald-primary);
  box-shadow: var(--shadow-e1);
}

.health-value {
  font-size: 0.68rem;
  font-weight: 700;
  color: var(--text-secondary);
  font-variant-numeric: tabular-nums;
  min-width: 30px;
  text-align: right;
}
.health-value.is-perfect {
  color: var(--emerald-primary);
}

.jump-next-btn {
  display: flex;
  align-items: center;
  gap: 3px;
  background: var(--accent-subtle);
  border: 1px solid var(--accent-border);
  color: var(--accent-hover);
  border-radius: var(--radius-pill);
  padding: 3px 8px;
  font-size: 0.68rem;
  font-weight: 600;
  cursor: pointer;
  transition: background var(--dur-fast) var(--ease-out),
              border-color var(--dur-fast) var(--ease-out),
              color var(--dur-fast) var(--ease-out);
}

.jump-next-btn:hover:not(:disabled) {
  background: var(--accent-primary);
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
}

.filter-pill {
  background: transparent;
  border: 1px solid var(--border-subtle);
  color: var(--text-muted);
  border-radius: var(--radius-pill);
  padding: 2px 8px;
  font-size: 0.65rem;
  cursor: pointer;
  transition: border-color var(--dur-fast) var(--ease-out),
              color var(--dur-fast) var(--ease-out),
              background var(--dur-fast) var(--ease-out);
}

.filter-pill:hover {
  border-color: var(--border-medium);
  color: var(--text-main);
}

.filter-pill.active {
  background: var(--accent-primary);
  border-color: var(--accent-primary);
  color: #ffffff;
}

.filter-pill.pill-warn:not(.active) {
  color: var(--amber-primary);
  border-color: var(--amber-border);
  font-weight: 700;
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
  background: var(--bg-surface);
  border-radius: var(--radius-sm);
  padding: 8px 10px;
  border: 1px solid var(--border-subtle);
  cursor: pointer;
  transition: all var(--dur-fast) var(--ease-out);
  position: relative;
}

.issue-card:hover {
  background: var(--bg-surface-elevated);
  border-color: var(--border-medium);
  transform: translateY(-1px);
}

.card-selected {
  border-color: var(--accent-primary) !important;
  background: var(--accent-subtle) !important;
  box-shadow: 0 0 0 1px var(--accent-border);
}

.card-critical {
  border-left: 3px solid var(--ruby-primary);
}

.card-warning {
  border-left: 3px solid var(--amber-primary);
}

/* User-Verified State (Turns Green & Marked As Done) */
.card-verified {
  background: rgba(16, 185, 129, 0.05) !important;
  border-color: rgba(16, 185, 129, 0.25) !important;
  border-left: 3px solid var(--emerald-primary) !important;
  opacity: 0.85;
}

.card-verified:hover {
  opacity: 1;
  background: rgba(16, 185, 129, 0.1) !important;
  border-color: rgba(16, 185, 129, 0.4) !important;
}

.text-verified-word {
  color: var(--emerald-primary) !important;
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
  font-family: var(--font-arabic);
  font-size: 1.25rem;
  color: var(--text-main);
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
  padding: 1px 6px;
  border-radius: var(--radius-xs);
  font-family: var(--font-mono);
  letter-spacing: -0.2px;
}

.badge-danger {
  background: var(--ruby-bg);
  color: var(--ruby-primary);
  border: 1px solid var(--ruby-border);
}

.badge-warn {
  background: var(--amber-bg);
  color: var(--amber-primary);
  border: 1px solid var(--amber-border);
}

.badge-purple {
  background: rgba(139, 92, 246, 0.14);
  color: #b79af8;
  border: 1px solid rgba(139, 92, 246, 0.30);
}

.badge-indigo {
  background: var(--accent-subtle);
  color: #a5abeb;
  border: 1px solid var(--accent-border);
}

.badge-blue {
  background: var(--sky-bg);
  color: var(--sky-primary);
  border: 1px solid var(--sky-border, rgba(88, 160, 201, 0.30));
}

.badge-muted {
  background: var(--bg-surface-hover);
  color: var(--text-secondary);
  border: 1px solid var(--border-subtle);
}

.issue-msg {
  font-size: var(--text-xs);
  color: var(--text-secondary);
  margin-bottom: 5px;
  line-height: 1.4;
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
  font-size: 0.62rem;
  padding: 1px 6px;
  background: var(--bg-surface-elevated);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-xs);
  color: var(--text-muted);
}

.metric-bad {
  color: var(--ruby-primary);
  border-color: rgba(239, 68, 68, 0.25);
  background: rgba(239, 68, 68, 0.08);
}

.metric-warn {
  color: var(--amber-primary);
  border-color: rgba(245, 158, 11, 0.25);
  background: rgba(245, 158, 11, 0.08);
}

.metric-ref {
  direction: rtl;
  font-family: var(--font-arabic);
  color: var(--text-secondary);
}

/* Footer & Verify Action Button */
.issue-card-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: 2px;
  padding-top: 4px;
  border-top: 1px solid var(--border-subtle);
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
  font-size: 0.65rem;
  font-weight: 600;
  padding: 2px 8px;
  border-radius: var(--radius-pill);
  cursor: pointer;
  background: var(--bg-surface-elevated);
  border: 1px solid var(--border-subtle);
  color: var(--text-secondary);
  transition: all var(--dur-fast) var(--ease-out);
}

.verify-btn:hover {
  background: rgba(16, 185, 129, 0.15);
  border-color: rgba(16, 185, 129, 0.4);
  color: var(--emerald-primary);
}

.verify-btn.btn-is-verified {
  background: rgba(16, 185, 129, 0.18);
  border-color: var(--emerald-primary);
  color: var(--emerald-primary);
}

.verify-btn.btn-is-verified:hover {
  background: rgba(239, 68, 68, 0.15);
  border-color: rgba(239, 68, 68, 0.4);
  color: var(--ruby-primary);
}

.empty-state {
  text-align: center;
  padding: 36px 16px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  animation: fade-in var(--dur-base) var(--ease-out) both;
}

.text-green { color: var(--emerald-primary); }
.empty-title { font-size: 0.85rem; font-weight: 600; color: var(--text-main); }
.empty-desc { font-size: var(--text-xs); color: var(--text-muted); line-height: 1.4; }

/* Light Theme High-Contrast Badge Colors */
html[data-theme='light'] .badge-danger {
  background: #fee2e2;
  color: #b91c1c;
  border-color: var(--ruby-primary);
}
html[data-theme='light'] .badge-warn {
  background: #fef3c7;
  color: #b45309;
  border-color: #fcd34d;
}
html[data-theme='light'] .badge-purple {
  background: #f3e8ff;
  color: var(--qc-purple);
  border-color: #d8b4fe;
}
html[data-theme='light'] .badge-indigo {
  background: #e0e7ff;
  color: #4338ca;
  border-color: #c7d2fe;
}
html[data-theme='light'] .badge-blue {
  background: #dbeafe;
  color: var(--accent-deep);
  border-color: #93c5fd;
}
html[data-theme='light'] .badge-muted {
  background: #f1f5f9;
  color: #475569;
  border-color: #cbd5e1;
}
html[data-theme='light'] .text-verified-word {
  color: var(--emerald-primary) !important;
}
html[data-theme='light'] .card-verified {
  background: #f0fdf4 !important;
  border-color: #86efac !important;
  border-left: 3px solid var(--emerald-primary) !important;
}
html[data-theme='light'] .verify-btn {
  background: #f0fdf4;
  border-color: #86efac;
  color: var(--emerald-primary);
}
html[data-theme='light'] .verify-btn.btn-is-verified {
  background: #ecfdf5;
  border-color: var(--emerald-primary);
  color: #047857;
}
</style>
