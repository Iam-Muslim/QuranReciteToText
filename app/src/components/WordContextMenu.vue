<template>
  <div 
    v-if="visible" 
    class="word-context-menu glass-panel" 
    :style="{ top: `${position.y}px`, left: `${position.x}px` }"
    @click.stop
  >
    <div class="menu-header" v-if="targetWord">
      <span class="menu-word">{{ targetWord.word }}</span>
      <span class="menu-loc">{{ targetWord.location }} • [{{ targetWord.start.toFixed(2) }}s - {{ targetWord.end.toFixed(2) }}s]</span>
    </div>

    <div class="menu-items">
      <!-- Fine Nudging -->
      <div class="menu-submenu">
        <span class="submenu-label">Nudge Boundary</span>
        <div class="nudge-buttons-row">
          <button class="nudge-btn" @click="nudgeStart(-0.01)" title="Shift start -10ms">Start −10ms</button>
          <button class="nudge-btn" @click="nudgeStart(0.01)" title="Shift start +10ms">Start +10ms</button>
          <button class="nudge-btn" @click="nudgeEnd(-0.01)" title="Shift end -10ms">End −10ms</button>
          <button class="nudge-btn" @click="nudgeEnd(0.01)" title="Shift end +10ms">End +10ms</button>
        </div>
      </div>

      <div class="menu-divider"></div>

      <!-- Split -->
      <button class="menu-action-item" @click="handleSplit">
        <Scissors :size="13" />
        <span>Split Word</span>
      </button>

      <!-- Edit Word -->
      <button class="menu-action-item" @click="handleEdit">
        <Edit3 :size="13" />
        <span>Edit Location</span>
      </button>

      <div class="menu-divider"></div>

      <!-- Delete Word -->
      <div v-if="confirmingDelete" class="delete-confirm-box">
        <span class="confirm-prompt">Delete "{{ targetWord?.word }}"?</span>
        <div class="confirm-actions">
          <button class="confirm-btn-danger" @click="confirmDelete">Delete</button>
          <button class="confirm-btn-cancel" @click="confirmingDelete = false">Cancel</button>
        </div>
      </div>
      <button v-else class="menu-action-item danger" @click="confirmingDelete = true">
        <Trash2 :size="13" />
        <span>Delete Word</span>
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue';
import type { AlignedWord } from '../types/aligner';
import { projectStore } from '../services/projectStore';
import { 
  Scissors, 
  Edit3, 
  Trash2
} from 'lucide-vue-next';

const emit = defineEmits<{
  (e: 'open-edit-word', word: AlignedWord): void;
}>();

const visible = ref(false);
const position = ref({ x: 0, y: 0 });
const targetWord = ref<AlignedWord | null>(null);
const confirmingDelete = ref(false);

function open(e: MouseEvent, word: AlignedWord) {
  targetWord.value = word;
  confirmingDelete.value = false;
  
  // Guard window bounds
  const menuWidth = 260;
  const menuHeight = 280;
  const x = Math.min(window.innerWidth - menuWidth - 10, Math.max(10, e.clientX));
  const y = Math.min(window.innerHeight - menuHeight - 10, Math.max(10, e.clientY));

  position.value = { x, y };
  visible.value = true;
}

function close() {
  visible.value = false;
  targetWord.value = null;
  confirmingDelete.value = false;
}

function nudgeStart(delta: number) {
  if (targetWord.value) {
    projectStore.nudgeWord(targetWord.value, delta, 'start');
  }
}

function nudgeEnd(delta: number) {
  if (targetWord.value) {
    projectStore.nudgeWord(targetWord.value, delta, 'end');
  }
}

function handleSplit() {
  if (targetWord.value) {
    projectStore.splitWord(targetWord.value);
    close();
  }
}



function handleEdit() {
  if (!targetWord.value) return;
  const word = targetWord.value;
  close();
  emit('open-edit-word', word);
}

function confirmDelete() {
  if (targetWord.value) {
    projectStore.deleteWord(targetWord.value);
    close();
  }
}

function handleClickOutside(_e: MouseEvent) {
  if (visible.value) {
    close();
  }
}

function handleKey(e: KeyboardEvent) {
  if (e.key === 'Escape' && visible.value) {
    close();
  }
}

onMounted(() => {
  window.addEventListener('click', handleClickOutside);
  window.addEventListener('keydown', handleKey);
});

onUnmounted(() => {
  window.removeEventListener('click', handleClickOutside);
  window.removeEventListener('keydown', handleKey);
});

defineExpose({
  open,
  close,
});
</script>

<style scoped>
.word-context-menu {
  position: fixed;
  z-index: 100;
  width: 250px;
  background: var(--glass-bg);
  backdrop-filter: blur(12px) saturate(1.4);
  -webkit-backdrop-filter: blur(12px) saturate(1.4);
  border: 1px solid var(--glass-border);
  border-radius: var(--radius-md);
  padding: 4px;
  box-shadow: var(--shadow-e4);
  animation: scale-in var(--dur-fast) var(--ease-spring) both;
}

@keyframes scale-in {
  from { opacity: 0; transform: scale(0.95); }
  to { opacity: 1; transform: scale(1); }
}

.menu-header {
  padding: 8px 10px 6px;
  border-bottom: 1px solid var(--border-subtle);
  margin-bottom: 4px;
}
.menu-word {
  font-family: var(--font-arabic);
  font-size: 1.25rem;
  color: var(--text-main);
  display: block;
}
.menu-loc {
  font-family: var(--font-mono);
  font-size: 0.68rem;
  color: var(--text-dim);
}

.menu-submenu {
  padding: 6px 8px;
}
.submenu-label {
  font-size: 0.65rem;
  font-weight: 700;
  color: var(--text-dim);
  letter-spacing: 0.05em;
  display: block;
  margin-bottom: 5px;
}

.nudge-buttons-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 4px;
}
.nudge-btn {
  background: var(--bg-surface-elevated);
  border: 1px solid var(--border-subtle);
  color: var(--text-main);
  border-radius: var(--radius-xs);
  padding: 3px 5px;
  font-size: 0.68rem;
  font-family: var(--font-mono);
  cursor: pointer;
  transition: background var(--dur-fast) var(--ease-out),
              border-color var(--dur-fast) var(--ease-out);
}
.nudge-btn:hover {
  background: var(--bg-surface-hover);
  border-color: var(--accent-primary);
  color: var(--text-main);
}

.menu-divider {
  height: 1px;
  background: var(--border-subtle);
  margin: 4px 0;
}

.menu-action-item {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 8px;
  background: transparent;
  border: none;
  color: var(--text-muted);
  border-radius: var(--radius-xs);
  padding: 7px 10px;
  font-size: 0.78rem;
  font-weight: 500;
  cursor: pointer;
  text-align: left;
  transition: background var(--dur-fast) var(--ease-out),
              color var(--dur-fast) var(--ease-out);
}
.menu-action-item:hover {
  background: var(--bg-surface-elevated);
  color: var(--text-main);
}
.menu-action-item.danger:hover {
  background: var(--ruby-bg);
  color: var(--ruby-primary);
}

/* Standalone In-Menu Confirmation Box */
.delete-confirm-box {
  padding: 8px 10px;
  background: var(--ruby-bg);
  border: 1px solid var(--ruby-border);
  border-radius: var(--radius-sm);
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin: 2px 0;
  animation: rise-in var(--dur-fast) var(--ease-spring) both;
}

.confirm-prompt {
  font-size: 0.72rem;
  color: var(--ruby-primary);
  font-weight: 600;
  text-align: center;
}

.confirm-actions {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
}

.confirm-btn-danger {
  background: var(--ruby-primary);
  border: none;
  color: #fff;
  border-radius: var(--radius-xs);
  padding: 3px 10px;
  font-size: 0.7rem;
  font-weight: 700;
  cursor: pointer;
  transition: background var(--dur-fast) var(--ease-out);
}
.confirm-btn-danger:hover {
  background: var(--ruby-primary);
}

.confirm-btn-cancel {
  background: var(--bg-surface-elevated);
  border: 1px solid var(--border-subtle);
  color: var(--text-secondary);
  border-radius: var(--radius-xs);
  padding: 3px 10px;
  font-size: 0.7rem;
  cursor: pointer;
  transition: background var(--dur-fast) var(--ease-out),
              border-color var(--dur-fast) var(--ease-out),
              color var(--dur-fast) var(--ease-out);
}
.confirm-btn-cancel:hover {
  background: var(--bg-surface-hover);
  color: var(--text-main);
}
</style>
