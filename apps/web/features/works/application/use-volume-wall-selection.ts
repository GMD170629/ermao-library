'use client';

import type { MouseEvent as ReactMouseEvent } from 'react';
import { useCallback, useEffect, useRef, useState } from 'react';
import { applyVolumeSelectionMode, contextVolumeSelection, pruneVolumeSelection, toggleVolumeSelection, type VolumeSelectionMode } from '../model/volume-selection';

type DragState = {
  active: boolean;
  startId: string;
  mode: VolumeSelectionMode;
  modified: boolean;
  moved: boolean;
  visited: Set<string>;
};

const idleDrag = (): DragState => ({ active: false, startId: '', mode: 'select', modified: false, moved: false, visited: new Set() });

function isEditableTarget(target: EventTarget | null): boolean {
  return target instanceof HTMLElement && Boolean(target.closest('input, textarea, select, [contenteditable="true"], [role="dialog"], [role="menu"]'));
}

export function useVolumeWallSelection({ enabled, scopeKey, volumeIds }: { enabled: boolean; scopeKey: string; volumeIds: readonly string[] }) {
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const selectedRef = useRef(selectedIds);
  const dragRef = useRef<DragState>(idleDrag());

  const commit = useCallback((next: Set<string>) => {
    selectedRef.current = next;
    setSelectedIds(next);
  }, []);

  const clear = useCallback(() => commit(new Set()), [commit]);

  useEffect(() => {
    clear();
  }, [clear, scopeKey]);

  useEffect(() => {
    const next = pruneVolumeSelection(selectedRef.current, volumeIds);
    if (next.size !== selectedRef.current.size || [...next].some((volumeId) => !selectedRef.current.has(volumeId))) commit(next);
  }, [commit, volumeIds]);

  useEffect(() => {
    const finishDrag = () => {
      const drag = dragRef.current;
      if (!drag.active) return;
      if (!drag.moved && !drag.modified) commit(new Set([drag.startId]));
      dragRef.current = idleDrag();
      document.body.style.removeProperty('user-select');
    };
    const selectAll = (event: KeyboardEvent) => {
      if (!enabled || isEditableTarget(event.target) || document.querySelector('[role="dialog"], [role="menu"]') || !(event.ctrlKey || event.metaKey) || event.key.toLowerCase() !== 'a') return;
      event.preventDefault();
      commit(new Set(volumeIds));
    };
    window.addEventListener('mouseup', finishDrag);
    window.addEventListener('blur', finishDrag);
    document.addEventListener('keydown', selectAll);
    return () => {
      window.removeEventListener('mouseup', finishDrag);
      window.removeEventListener('blur', finishDrag);
      document.removeEventListener('keydown', selectAll);
      document.body.style.removeProperty('user-select');
    };
  }, [commit, enabled, volumeIds]);

  const beginCardSelection = useCallback((event: ReactMouseEvent<HTMLButtonElement>, volumeId: string) => {
    if (!enabled || event.button !== 0) return;
    event.preventDefault();
    const modified = event.ctrlKey || event.metaKey;
    const mode: VolumeSelectionMode = selectedRef.current.has(volumeId) ? 'deselect' : 'select';
    dragRef.current = { active: true, startId: volumeId, mode, modified, moved: false, visited: new Set([volumeId]) };
    document.body.style.userSelect = 'none';
    if (modified) commit(toggleVolumeSelection(selectedRef.current, volumeId));
  }, [commit, enabled]);

  const enterCard = useCallback((volumeId: string) => {
    const drag = dragRef.current;
    if (!drag.active || drag.visited.has(volumeId)) return;
    let next = new Set(selectedRef.current);
    if (!drag.moved && !drag.modified) next = applyVolumeSelectionMode(next, drag.startId, drag.mode);
    next = applyVolumeSelectionMode(next, volumeId, drag.mode);
    drag.moved = true;
    drag.visited.add(volumeId);
    commit(next);
  }, [commit]);

  const selectForContextMenu = useCallback((volumeId: string) => {
    commit(contextVolumeSelection(selectedRef.current, volumeId));
  }, [commit]);

  return { selectedIds, clear, beginCardSelection, enterCard, selectForContextMenu };
}
