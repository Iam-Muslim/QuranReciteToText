import { describe, it, expect, vi } from 'vitest';
import { projectStore } from '../projectStore';
import { AutosaveService } from '../autosaveService';

describe('ProjectStore and AutosaveService verification', () => {
  it('correctly builds a persistent snapshot with toRaw without reactive traps', () => {
    projectStore.project.project_name = 'Test Multi-Surah';
    projectStore.project.surahs = [
      {
        surah_number: 1,
        surah_name_arabic: 'الفاتحة',
        surah_name_english: 'Al-Faatiha',
        status: 'aligned',
        audio_url: 'blob:http://localhost/12345',
        audio_duration_seconds: 42,
        ayahs: [],
      },
      {
        surah_number: 2,
        surah_name_arabic: 'البقرة',
        surah_name_english: 'Al-Baqarah',
        status: 'verified',
        audio_url: 'https://example.com/audio.mp3',
        audio_duration_seconds: 180,
        ayahs: [],
      }
    ];

    const snapshot = projectStore.buildPersistentSnapshot();

    expect(snapshot.project_name).toBe('Test Multi-Surah');
    expect(snapshot.surahs.length).toBe(2);
    // blob URL must be stripped
    expect(snapshot.surahs[0].audio_url).toBe('');
    // external or valid URL must be preserved
    expect(snapshot.surahs[1].audio_url).toBe('https://example.com/audio.mp3');
  });

  it('AutosaveService debounces saves cleanly and flushes immediately when requested', async () => {
    let saveCount = 0;
    const saveMock = vi.fn().mockImplementation(async () => {
      saveCount++;
      return true;
    });

    const autosave = new AutosaveService({
      debounceMs: 50,
      saveFn: saveMock,
      canSavePredicate: () => true,
    });

    expect(autosave.isDirty.value).toBe(false);
    expect(autosave.saveStatus.value).toBe('saved');

    // Trigger rapid edits
    autosave.markDirty();
    autosave.markDirty();
    autosave.markDirty();

    expect(autosave.isDirty.value).toBe(true);
    expect(autosave.saveStatus.value).toBe('unsaved');
    expect(saveCount).toBe(0);

    // Explicit immediate flush (e.g. tab switch or alignment completion)
    await autosave.flush();

    expect(saveCount).toBe(1);
    expect(autosave.isDirty.value).toBe(false);
    expect(autosave.saveStatus.value).toBe('saved');

    autosave.destroy();
  });
});
