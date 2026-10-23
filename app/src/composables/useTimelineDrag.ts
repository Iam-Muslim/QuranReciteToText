import { ref, type Ref } from 'vue';
import type WaveSurfer from 'wavesurfer.js';
import { projectStore } from '../services/projectStore';
import type { AlignedWord, TimelineSegmentItem } from '../types/aligner';

export interface SharedDivider {
  id: string;
  segmentId: string;
  leftIndex: number;
  rightIndex: number;
  leftWord: AlignedWord;
  rightWord: AlignedWord;
  time: number;
}

export function useTimelineDrag(
  getWaveSurfer: () => WaveSurfer | null,
  zoomLevel: Ref<number>,
  duration: Ref<number>,
  totalTimelineWidth: Ref<number>,
  viewportClientWidth: Ref<number>,
  scrollbarThumbWidth: Ref<number>,
  scrollbarTrack: Ref<HTMLElement | null>,
  syncTrackScroll: () => void,
  adjustZoom: (delta: number, clientX?: number) => void
) {
  const isPanning = ref(false);
  const activeDraggingDividerId = ref<string | null>(null);
  const activeDraggingBoundary = ref<{ id: string; edge: 'start' | 'end'; time: number } | null>(null);

  function getClientX(e: MouseEvent | TouchEvent): number {
    if ('touches' in e && e.touches.length > 0) return e.touches[0].clientX;
    if ('changedTouches' in e && e.changedTouches.length > 0) return e.changedTouches[0].clientX;
    return (e as MouseEvent).clientX ?? 0;
  }

  function listenDrag(onMove: (clientX: number) => void, onEnd: () => void) {
    function moveHandler(evt: MouseEvent | TouchEvent) {
      onMove(getClientX(evt));
    }
    function endHandler() {
      window.removeEventListener('mousemove', moveHandler as any);
      window.removeEventListener('touchmove', moveHandler as any);
      window.removeEventListener('mouseup', endHandler);
      window.removeEventListener('touchend', endHandler);
      window.removeEventListener('touchcancel', endHandler);
      onEnd();
    }
    window.addEventListener('mousemove', moveHandler as any);
    window.addEventListener('touchmove', moveHandler as any, { passive: true });
    window.addEventListener('mouseup', endHandler);
    window.addEventListener('touchend', endHandler);
    window.addEventListener('touchcancel', endHandler);
  }

  // Shared-Vertex Divider Drag Handler (Mouse & Touch)
  function startDragDivider(divider: SharedDivider, e: MouseEvent | TouchEvent) {
    activeDraggingDividerId.value = divider.id;
    const startX = getClientX(e);
    const initialTime = divider.time;
    const leftStart = divider.leftWord.start;
    const rightEnd = divider.rightWord.end;

    let minTime = Number((leftStart + 0.02).toFixed(3));
    let maxTime = Number((rightEnd - 0.02).toFixed(3));

    if (minTime > initialTime) minTime = initialTime;
    if (maxTime < initialTime) maxTime = initialTime;
    if (maxTime < minTime) maxTime = minTime;

    listenDrag(
      (currentX) => {
        const deltaPx = currentX - startX;
        const deltaTime = deltaPx / zoomLevel.value;
        const rawTime = initialTime + deltaTime;
        const clampedTime = Number(Math.max(minTime, Math.min(maxTime, rawTime)).toFixed(3));

        divider.leftWord.end = clampedTime;
        divider.rightWord.start = clampedTime;
        divider.leftWord.is_edited = true;
        divider.rightWord.is_edited = true;
        divider.time = clampedTime;
      },
      () => {
        activeDraggingDividerId.value = null;
        projectStore.updateAyahBounds(divider.leftWord.location);

        const finalTime = divider.leftWord.end;
        if (Math.abs(finalTime - initialTime) > 0.001) {
          projectStore.recordDividerHistory(
            divider.leftWord,
            divider.rightWord,
            initialTime,
            initialTime,
            finalTime
          );
        }
      }
    );
  }

  function isWordBoundaryStart(_seg: TimelineSegmentItem, w: AlignedWord, wIdx: number): boolean {
    if (wIdx === 0) return true;
    const prev = _seg.words[wIdx - 1];
    return (w.start - prev.end) > 0.01;
  }

  function isWordBoundaryEnd(seg: TimelineSegmentItem, w: AlignedWord, wIdx: number): boolean {
    if (wIdx === seg.words.length - 1) return true;
    const next = seg.words[wIdx + 1];
    return (next.start - w.end) > 0.01;
  }

  function startDragWordBoundary(
    seg: TimelineSegmentItem,
    w: AlignedWord,
    wIdx: number,
    edge: 'start' | 'end',
    e: MouseEvent | TouchEvent
  ) {
    const boundaryId = `${seg.id}_${wIdx}`;
    const startX = getClientX(e);
    const initialTime = edge === 'start' ? w.start : w.end;
    activeDraggingBoundary.value = { id: boundaryId, edge, time: initialTime };

    let minTime: number;
    let maxTime: number;

    if (edge === 'start') {
      maxTime = Number((w.end - 0.02).toFixed(3));
      if (wIdx === 0) {
        let prevLimit = 0;
        for (const s of projectStore.activeSegments.value) {
          if (s.id !== seg.id && s.end < initialTime) {
            if (s.end > prevLimit) prevLimit = s.end;
          }
        }
        minTime = Number(prevLimit.toFixed(3));
      } else {
        minTime = Number(seg.words[wIdx - 1].end.toFixed(3));
      }

      if (minTime > initialTime) minTime = initialTime;
      if (maxTime < minTime) maxTime = minTime;
    } else {
      minTime = Number((w.start + 0.02).toFixed(3));
      if (wIdx === seg.words.length - 1) {
        let nextLimit = duration.value > 0 ? duration.value : 999999;
        for (const s of projectStore.activeSegments.value) {
          if (s.id !== seg.id && s.start > initialTime) {
            if (s.start < nextLimit) nextLimit = s.start;
          }
        }
        maxTime = Number(nextLimit.toFixed(3));
      } else {
        maxTime = Number(seg.words[wIdx + 1].start.toFixed(3));
      }

      if (maxTime < initialTime) maxTime = initialTime;
      if (minTime > maxTime) minTime = maxTime;
    }

    listenDrag(
      (currentX) => {
        const deltaPx = currentX - startX;
        const deltaTime = deltaPx / zoomLevel.value;
        const rawTime = initialTime + deltaTime;
        const clampedTime = Number(Math.max(minTime, Math.min(maxTime, rawTime)).toFixed(3));

        if (edge === 'start') {
          w.start = clampedTime;
          if (wIdx === 0) {
            seg.start = clampedTime;
          }
        } else {
          w.end = clampedTime;
          if (wIdx === seg.words.length - 1) {
            seg.end = clampedTime;
          }
        }
        w.is_edited = true;
        if (activeDraggingBoundary.value) {
          activeDraggingBoundary.value.time = clampedTime;
        }
      },
      () => {
        activeDraggingBoundary.value = null;
        projectStore.updateAyahBounds(w.location);

        const finalTime = edge === 'start' ? w.start : w.end;
        if (Math.abs(finalTime - initialTime) > 0.001) {
          projectStore.recordWordBoundaryHistory(w, edge, initialTime, finalTime);
        }
      }
    );
  }

  function startDragSegmentBoundary(seg: TimelineSegmentItem, edge: 'start' | 'end', e: MouseEvent | TouchEvent) {
    if (!seg.words || seg.words.length === 0) return;
    const targetWord = edge === 'start' ? seg.words[0] : seg.words[seg.words.length - 1];
    const initialTime = edge === 'start' ? targetWord.start : targetWord.end;
    activeDraggingBoundary.value = { id: seg.id, edge, time: initialTime };

    let minTime: number;
    let maxTime: number;

    if (edge === 'start') {
      maxTime = Number((targetWord.end - 0.02).toFixed(3));
      let prevLimit = 0;
      for (const s of projectStore.activeSegments.value) {
        if (s.id !== seg.id && s.end < initialTime) {
          if (s.end > prevLimit) prevLimit = s.end;
        }
      }
      minTime = Number(prevLimit.toFixed(3));
      if (minTime > initialTime) minTime = initialTime;
      if (maxTime < minTime) maxTime = minTime;
    } else {
      minTime = Number((targetWord.start + 0.02).toFixed(3));
      let nextLimit = duration.value > 0 ? duration.value : 999999;
      for (const s of projectStore.activeSegments.value) {
        if (s.id !== seg.id && s.start > initialTime) {
          if (s.start < nextLimit) nextLimit = s.start;
        }
      }
      maxTime = Number(nextLimit.toFixed(3));
      if (maxTime < initialTime) maxTime = initialTime;
      if (minTime > maxTime) minTime = maxTime;
    }

    const startX = getClientX(e);

    listenDrag(
      (currentX) => {
        const deltaPx = currentX - startX;
        const deltaTime = deltaPx / zoomLevel.value;
        const rawTime = initialTime + deltaTime;
        const clampedTime = Number(Math.max(minTime, Math.min(maxTime, rawTime)).toFixed(3));

        if (edge === 'start') {
          targetWord.start = clampedTime;
          seg.start = clampedTime;
        } else {
          targetWord.end = clampedTime;
          seg.end = clampedTime;
        }
        targetWord.is_edited = true;
        if (activeDraggingBoundary.value) {
          activeDraggingBoundary.value.time = clampedTime;
        }
      },
      () => {
        activeDraggingBoundary.value = null;
        projectStore.updateAyahBounds(targetWord.location);

        const finalTime = edge === 'start' ? targetWord.start : targetWord.end;
        if (Math.abs(finalTime - initialTime) > 0.001) {
          projectStore.recordWordBoundaryHistory(targetWord, edge, initialTime, finalTime);
        }
      }
    );
  }

  function handleTimelineMouseDown(e: MouseEvent) {
    if (e.button === 1 || (e.button === 0 && e.altKey)) {
      e.preventDefault();
      isPanning.value = true;
      const startX = e.clientX;
      const ws = getWaveSurfer();
      const initialScroll = ws ? ws.getScroll() : 0;
      const maxScroll = Math.max(0, totalTimelineWidth.value - viewportClientWidth.value);

      function onPanMove(moveEvt: MouseEvent) {
        const deltaX = moveEvt.clientX - startX;
        const targetScroll = Math.max(0, Math.min(maxScroll, initialScroll - deltaX));
        ws?.setScroll(targetScroll);
        syncTrackScroll();
      }

      function onPanUp() {
        isPanning.value = false;
        window.removeEventListener('mousemove', onPanMove);
        window.removeEventListener('mouseup', onPanUp);
      }

      window.addEventListener('mousemove', onPanMove);
      window.addEventListener('mouseup', onPanUp);
    }
  }

  function handleScrollbarTrackClick(e: MouseEvent) {
    const ws = getWaveSurfer();
    if (!scrollbarTrack.value || !ws) return;
    const rect = scrollbarTrack.value.getBoundingClientRect();
    const clickX = e.clientX - rect.left;
    const trackW = rect.width;
    const thumbW = scrollbarThumbWidth.value;
    const maxThumbLeft = trackW - thumbW;
    if (maxThumbLeft <= 0) return;

    const targetThumbLeft = Math.max(0, Math.min(maxThumbLeft, clickX - thumbW / 2));
    const progress = targetThumbLeft / maxThumbLeft;
    const maxScroll = Math.max(0, totalTimelineWidth.value - viewportClientWidth.value);
    ws.setScroll(progress * maxScroll);
    syncTrackScroll();
  }

  function startDragScrollbarThumb(e: MouseEvent | TouchEvent) {
    const ws = getWaveSurfer();
    if (!scrollbarTrack.value || !ws) return;
    const startX = getClientX(e);
    const startScroll = ws.getScroll();
    const trackW = scrollbarTrack.value.clientWidth;
    const thumbW = scrollbarThumbWidth.value;
    const maxThumbLeft = trackW - thumbW;
    const maxScroll = Math.max(0, totalTimelineWidth.value - viewportClientWidth.value);
    if (maxThumbLeft <= 0) return;

    listenDrag(
      (currentX) => {
        const deltaX = currentX - startX;
        const scrollDelta = (deltaX / maxThumbLeft) * maxScroll;
        const targetScroll = Math.max(0, Math.min(maxScroll, startScroll + scrollDelta));
        ws?.setScroll(targetScroll);
        syncTrackScroll();
      },
      () => {}
    );
  }

  function handleTimelineWheel(event: WheelEvent, hasAudio: boolean) {
    const ws = getWaveSurfer();
    if (!ws || !hasAudio) return;

    if (event.ctrlKey || event.metaKey) {
      event.preventDefault();
      const zoomDelta = event.deltaY < 0 ? 15 : -15;
      adjustZoom(zoomDelta, event.clientX);
      return;
    }

    event.preventDefault();
    const delta = event.deltaX !== 0 ? event.deltaX : event.deltaY;
    const scrollMultiplier = event.shiftKey ? 2.5 : 1.2;
    const currentScroll = ws.getScroll();
    const maxScroll = Math.max(0, totalTimelineWidth.value - viewportClientWidth.value);
    const targetScroll = Math.max(0, Math.min(maxScroll, currentScroll + (delta * scrollMultiplier)));

    ws.setScroll(targetScroll);
    syncTrackScroll();
  }

  let initialPinchDistance = 0;
  let initialZoomOnPinch = 0;

  function getDistance(t1: Touch, t2: Touch): number {
    return Math.hypot(t1.clientX - t2.clientX, t1.clientY - t2.clientY);
  }

  function handleTimelineTouchStart(e: TouchEvent) {
    if (e.touches.length === 2) {
      initialPinchDistance = getDistance(e.touches[0], e.touches[1]);
      initialZoomOnPinch = zoomLevel.value;
    }
  }

  function handleTimelineTouchMove(e: TouchEvent) {
    if (e.touches.length === 2 && initialPinchDistance > 0) {
      e.preventDefault();
      const currentDist = getDistance(e.touches[0], e.touches[1]);
      const ratio = currentDist / initialPinchDistance;
      const midX = (e.touches[0].clientX + e.touches[1].clientX) / 2;
      const targetZoom = Math.round(initialZoomOnPinch * ratio);
      const delta = targetZoom - zoomLevel.value;
      if (Math.abs(delta) >= 2) {
        adjustZoom(delta, midX);
      }
    }
  }

  function handleTimelineTouchEnd(e: TouchEvent) {
    if (e.touches.length < 2) {
      initialPinchDistance = 0;
    }
  }

  return {
    isPanning,
    activeDraggingDividerId,
    activeDraggingBoundary,
    startDragDivider,
    isWordBoundaryStart,
    isWordBoundaryEnd,
    startDragWordBoundary,
    startDragSegmentBoundary,
    handleTimelineMouseDown,
    handleScrollbarTrackClick,
    startDragScrollbarThumb,
    handleTimelineWheel,
    handleTimelineTouchStart,
    handleTimelineTouchMove,
    handleTimelineTouchEnd,
  };
}
