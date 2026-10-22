<template>
  <div v-if="visible" class="cheatsheet-backdrop" @click.self="close">
    <div class="cheatsheet glass-float anim-scale" role="dialog" aria-label="Keyboard Shortcuts">
      <div class="cheatsheet-header">
        <Keyboard :size="16" class="cheatsheet-icon" />
        <span class="cheatsheet-title">Keyboard Shortcuts</span>
        <button class="btn-icon" @click="close" aria-label="Close">
          <X :size="15" />
        </button>
      </div>

      <div class="cheatsheet-columns">
        <div v-for="group in groups" :key="group.title" class="cheatsheet-group">
          <span class="group-title">{{ group.title }}</span>
          <div v-for="row in group.rows" :key="row.label" class="cheatsheet-row">
            <span class="row-label">{{ row.label }}</span>
            <span class="row-keys">
              <span v-for="k in row.keys" :key="k" class="kbd-hint">{{ k }}</span>
            </span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue';
import { Keyboard, X } from 'lucide-vue-next';

const visible = ref(false);

const groups = [
  {
    title: 'Transport',
    rows: [
      { label: 'Play / Pause', keys: ['Space'] },
      { label: 'Previous / Next Ayah', keys: ['[', ']'] },
      { label: 'Cycle Loop (Off/1v/1w)', keys: ['L'] },
      { label: 'Rewind / Scrub Back', keys: ['←'] },
      { label: 'Forward / Scrub Ahead', keys: ['→'] },
      { label: 'Jump to Beginning', keys: ['Home'] },
    ],
  },
  {
    title: 'Precision Editing',
    rows: [
      { label: 'Snap Start to Playhead', keys: ['W'] },
      { label: 'Snap End to Playhead', keys: ['E'] },
      { label: 'Undo Edit', keys: ['Ctrl', 'Z'] },
      { label: 'Redo Edit', keys: ['Ctrl', 'Y'] },
      { label: 'Fast Aligner', keys: ['Ctrl', 'Shift', 'A'] },
      { label: 'Verify Ayah / Issue', keys: ['V'] },
    ],
  },
  {
    title: 'Workspace & Views',
    rows: [
      { label: 'Toggle Sidebar', keys: ['Ctrl', 'B'] },
      { label: 'Command Palette', keys: ['Ctrl', 'P'] },
      { label: 'Confidence Auditor', keys: ['Tab'] },
      { label: 'Zoom Timeline', keys: ['Ctrl', 'Wheel'] },
      { label: 'This Cheatsheet', keys: ['?'] },
    ],
  },
];

function open() { visible.value = true; }
function close() { visible.value = false; }

function isTypingTarget(e: Event): boolean {
  const t = e.target as HTMLElement | null;
  if (!t) return false;
  const tag = t.tagName;
  return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || t.isContentEditable;
}

function handleKey(e: KeyboardEvent) {
  if (isTypingTarget(e)) {
    if (e.key === 'Escape' && visible.value) close();
    return;
  }
  if (e.key === '?' || (e.key === '/' && e.shiftKey)) {
    e.preventDefault();
    if (visible.value) close();
    else open();
  } else if (e.key === 'Escape' && visible.value) {
    close();
  }
}

onMounted(() => window.addEventListener('keydown', handleKey));
onUnmounted(() => window.removeEventListener('keydown', handleKey));

defineExpose({ open, close });
</script>

<style scoped>
.cheatsheet-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(5, 6, 10, 0.55);
  backdrop-filter: blur(6px);
  -webkit-backdrop-filter: blur(6px);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 2000;
  animation: fade-in var(--dur-fast) var(--ease-out) both;
}

.cheatsheet {
  width: min(640px, calc(100vw - 28px));
  max-width: 92vw;
  max-height: 80vh;
  overflow-y: auto;
  border-radius: var(--radius-lg);
  animation: rise-in var(--dur-rise) var(--ease-spring) both;
}

.cheatsheet-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 14px 16px;
  border-bottom: 1px solid var(--border-subtle);
}
.cheatsheet-icon { color: var(--accent-hover); }
.cheatsheet-title {
  flex: 1;
  font-size: var(--text-md);
  font-weight: 700;
  color: var(--text-main);
}

.cheatsheet-columns {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
  gap: 18px;
  padding: 16px;
}

.cheatsheet-group {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.group-title {
  font-size: 0.68rem;
  font-weight: 700;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--text-dim);
  margin-bottom: 4px;
}

.cheatsheet-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 3px 0;
}

.row-label {
  font-size: var(--text-xs);
  color: var(--text-secondary);
}

.row-keys {
  display: inline-flex;
  gap: 4px;
  flex-shrink: 0;
}
</style>
