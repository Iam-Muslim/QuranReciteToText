<template>
  <aside class="issues-drawer glass-panel" :class="{ 'drawer-open': projectStore.issuesDrawerOpen.value }">
    <!-- Header -->
    <div class="drawer-header">
      <div class="header-left">
        <AlertCircle :size="15" class="text-accent" />
        <span class="drawer-title">Auditor</span>
        <span class="issue-count" v-if="projectStore.issues.value.length > 0">
          {{ projectStore.issues.value.length }}
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
        <span class="progress-val">{{ cleanPercent }}% Clean</span>
      </div>
      <div class="progress-track">
        <div class="progress-fill" :style="{ width: `${cleanPercent}%` }"></div>
      </div>
      <div class="progress-sub-row">
        <span>{{ projectStore.surahStats.value.cleanWords }} clean</span>
        <span>{{ projectStore.issues.value.length }} flagged</span>
      </div>

      <!-- Quick Jump Button -->
      <button 
        class="jump-next-btn" 
        @click="projectStore.jumpToNextIssue()" 
        :disabled="projectStore.issues.value.length === 0"
        title="Jump to next flagged word (Tab key)"
      >
        <Sparkles :size="12" />
        <span>Next Issue (Tab)</span>
        <ChevronRight :size="13" />
      </button>
    </div>

    <!-- Filter Pills -->
    <div class="filter-row" v-if="projectStore.issues.value.length > 0">
      <button 
        class="filter-pill" 
        :class="{ 'active': activeFilter === 'all' }"
        @click="activeFilter = 'all'"
      >
        All ({{ projectStore.issues.value.length }})
      </button>
      <button 
        class="filter-pill" 
        :class="{ 'active': activeFilter === 'critical' }"
        @click="activeFilter = 'critical'"
        v-if="criticalCount > 0"
      >
        Low Score ({{ criticalCount }})
      </button>
      <button 
        class="filter-pill" 
        :class="{ 'active': activeFilter === 'gap' }"
        @click="activeFilter = 'gap'"
        v-if="gapCount > 0"
      >
        Gaps ({{ gapCount }})
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
          'card-critical': issue.severity === 'critical',
          'card-warning': issue.severity === 'warning'
        }"
        @click="jumpToIssue(issue)"
      >
        <div class="issue-card-top">
          <span class="word-arabic">{{ issue.word }}</span>
          <span class="score-pill" :class="issue.score < 0.80 ? 'score-bad' : 'score-mid'">
            {{ (issue.score * 100).toFixed(0) }}%
          </span>
        </div>

        <div class="issue-msg">{{ issue.message }}</div>

        <div class="issue-meta">
          <span>آية {{ issue.ayah_number }}</span>
          <span>{{ issue.timestamp.toFixed(2) }}s</span>
        </div>
      </div>

      <div v-if="filteredIssues.length === 0" class="empty-state">
        <CheckCircle2 :size="28" class="text-green" />
        <span class="empty-title">All Words Verified</span>
        <span class="empty-desc">No confidence issues or acoustic anomalies detected.</span>
      </div>
    </div>
  </aside>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue';
import { projectStore } from '../services/projectStore';
import type { ConfidenceIssue } from '../types/aligner';
import { AlertCircle, X, CheckCircle2, ChevronRight, Sparkles } from 'lucide-vue-next';

const activeFilter = ref<'all' | 'critical' | 'gap'>('all');

const cleanPercent = computed(() => {
  const stats = projectStore.surahStats.value;
  if (!stats.totalWords) return 100;
  return Math.round((stats.cleanWords / stats.totalWords) * 100);
});

const criticalCount = computed(() => {
  return projectStore.issues.value.filter(i => i.type === 'low_confidence').length;
});

const gapCount = computed(() => {
  return projectStore.issues.value.filter(i => i.type === 'large_gap' || i.type === 'coverage_gap').length;
});

const filteredIssues = computed(() => {
  if (activeFilter.value === 'all') return projectStore.issues.value;
  if (activeFilter.value === 'critical') return projectStore.issues.value.filter(i => i.type === 'low_confidence' || i.type === 'coverage_gap');
  if (activeFilter.value === 'gap') return projectStore.issues.value.filter(i => i.type === 'large_gap' || i.type === 'coverage_gap');
  return projectStore.issues.value;
});

function jumpToIssue(issue: ConfidenceIssue) {
  projectStore.selectWord(issue.location, true);
}
</script>

<style scoped>
.issues-drawer {
  width: 270px;
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

.progress-sub-row {
  display: flex;
  justify-content: space-between;
  font-size: 10px;
  color: var(--text-muted);
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
  gap: 4px;
  padding: 8px 12px;
  border-bottom: 1px solid var(--border-subtle);
  background: rgba(15, 23, 42, 0.2);
}

.filter-pill {
  background: transparent;
  border: 1px solid var(--border-subtle);
  color: var(--text-muted);
  border-radius: 12px;
  padding: 2px 8px;
  font-size: 0.68rem;
  cursor: pointer;
  transition: all 0.1s ease;
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
  background: rgba(15, 23, 42, 0.4);
  border-radius: 6px;
  padding: 8px 10px;
  border: 1px solid var(--border-subtle);
  cursor: pointer;
  transition: all 0.12s ease;
}

.issue-card:hover {
  background: rgba(15, 23, 42, 0.7);
  border-color: rgba(255, 255, 255, 0.25);
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

.issue-card-top {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 4px;
}

.word-arabic {
  font-family: 'Amiri Quran', 'Scheherazade New', serif;
  font-size: 1.15rem;
  color: #fff;
}

.score-pill {
  font-size: 0.65rem;
  font-weight: 700;
  padding: 1px 6px;
  border-radius: 4px;
  font-family: var(--font-mono);
}

.score-bad { background: rgba(239, 68, 68, 0.2); color: #f87171; border: 1px solid rgba(239, 68, 68, 0.3); }
.score-mid { background: rgba(245, 158, 11, 0.2); color: #fbbf24; border: 1px solid rgba(245, 158, 11, 0.3); }

.issue-msg {
  font-size: 10px;
  color: var(--text-muted);
  margin-bottom: 4px;
}

.issue-meta {
  display: flex;
  justify-content: space-between;
  font-family: var(--font-mono);
  font-size: 0.68rem;
  color: var(--text-muted);
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
.empty-desc { font-size: 0.72rem; color: var(--text-muted); }
</style>
