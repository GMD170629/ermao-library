'use client';

import type { MouseEvent as ReactMouseEvent } from 'react';
import { useCallback, useEffect, useRef, useState } from 'react';
import { applyResourceSelectionMode, contextResourceSelection, pruneResourceSelection, toggleResourceSelection, type ResourceSelectionMode } from '../model/resource-selection';

type DragState = {
  active: boolean;
  startId: string;
  mode: ResourceSelectionMode;
  modified: boolean;
  moved: boolean;
  visited: Set<string>;
};

const idleDrag = (): DragState => ({ active: false, startId: '', mode: 'select', modified: false, moved: false, visited: new Set() });

function isEditableTarget(target: EventTarget | null): boolean {
  return target instanceof HTMLElement && Boolean(target.closest('input, textarea, select, [contenteditable="true"], [role="dialog"], [role="menu"]'));
}

export function useResourceWallSelection({ enabled, scopeKey, resourceIds }: { enabled: boolean; scopeKey: string; resourceIds: readonly string[] }) {
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
    const next = pruneResourceSelection(selectedRef.current, resourceIds);
    if (next.size !== selectedRef.current.size || [...next].some((resourceId) => !selectedRef.current.has(resourceId))) commit(next);
  }, [commit, resourceIds]);

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
      commit(new Set(resourceIds));
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
  }, [commit, enabled, resourceIds]);

  const beginCardSelection = useCallback((event: ReactMouseEvent<HTMLButtonElement>, resourceId: string) => {
    if (!enabled || event.button !== 0) return;
    event.preventDefault();
    const modified = event.ctrlKey || event.metaKey;
    const mode: ResourceSelectionMode = selectedRef.current.has(resourceId) ? 'deselect' : 'select';
    dragRef.current = { active: true, startId: resourceId, mode, modified, moved: false, visited: new Set([resourceId]) };
    document.body.style.userSelect = 'none';
    if (modified) commit(toggleResourceSelection(selectedRef.current, resourceId));
  }, [commit, enabled]);

  const enterCard = useCallback((resourceId: string) => {
    const drag = dragRef.current;
    if (!drag.active || drag.visited.has(resourceId)) return;
    let next = new Set(selectedRef.current);
    if (!drag.moved && !drag.modified) next = applyResourceSelectionMode(next, drag.startId, drag.mode);
    next = applyResourceSelectionMode(next, resourceId, drag.mode);
    drag.moved = true;
    drag.visited.add(resourceId);
    commit(next);
  }, [commit]);

  const selectForContextMenu = useCallback((resourceId: string) => {
    commit(contextResourceSelection(selectedRef.current, resourceId));
  }, [commit]);

  const toggle = useCallback((resourceId: string) => {
    if (!enabled) return;
    commit(toggleResourceSelection(selectedRef.current, resourceId));
  }, [commit, enabled]);

  return { selectedIds, clear, beginCardSelection, enterCard, selectForContextMenu, toggle };
}
