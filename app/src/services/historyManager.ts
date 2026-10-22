import { ref } from 'vue';
import type { HistoryAction } from '../types/aligner';

export class HistoryManager {
  private historyStack: HistoryAction[] = [];
  private redoStack: HistoryAction[] = [];
  private maxDepth: number = 60;

  public canUndo = ref<boolean>(false);
  public canRedo = ref<boolean>(false);

  constructor(maxDepth: number = 60) {
    this.maxDepth = maxDepth;
  }

  public record(action: HistoryAction, onDirty?: () => void): void {
    this.historyStack.push(action);
    if (this.historyStack.length > this.maxDepth) {
      this.historyStack.shift();
    }
    this.redoStack = [];
    this.updateFlags();
    if (onDirty) onDirty();
  }

  public undo(onDirty?: () => void): boolean {
    const action = this.historyStack.pop();
    if (!action) return false;
    
    try {
      action.undo();
      this.redoStack.push(action);
    } catch (e) {
      console.error('Failed to undo action:', e);
    }
    
    this.updateFlags();
    if (onDirty) onDirty();
    return true;
  }

  public redo(onDirty?: () => void): boolean {
    const action = this.redoStack.pop();
    if (!action) return false;

    try {
      action.redo();
      this.historyStack.push(action);
    } catch (e) {
      console.error('Failed to redo action:', e);
    }

    this.updateFlags();
    if (onDirty) onDirty();
    return true;
  }

  public clear(): void {
    this.historyStack = [];
    this.redoStack = [];
    this.updateFlags();
  }

  public getDepth(): number {
    return this.historyStack.length;
  }

  public getRedoDepth(): number {
    return this.redoStack.length;
  }

  private updateFlags(): void {
    this.canUndo.value = this.historyStack.length > 0;
    this.canRedo.value = this.redoStack.length > 0;
  }
}

export const historyManager = new HistoryManager();
