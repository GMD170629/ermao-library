export type ResourceSelectionMode = 'select' | 'deselect';

export function toggleResourceSelection(current: ReadonlySet<string>, resourceId: string): Set<string> {
  const next = new Set(current);
  if (next.has(resourceId)) next.delete(resourceId);
  else next.add(resourceId);
  return next;
}

export function applyResourceSelectionMode(current: ReadonlySet<string>, resourceId: string, mode: ResourceSelectionMode): Set<string> {
  const next = new Set(current);
  if (mode === 'select') next.add(resourceId);
  else next.delete(resourceId);
  return next;
}

export function contextResourceSelection(current: ReadonlySet<string>, resourceId: string): Set<string> {
  return current.has(resourceId) ? new Set(current) : new Set([resourceId]);
}

export function pruneResourceSelection(current: ReadonlySet<string>, availableIds: readonly string[]): Set<string> {
  const available = new Set(availableIds);
  return new Set([...current].filter((resourceId) => available.has(resourceId)));
}
