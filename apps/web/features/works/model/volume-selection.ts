export type VolumeSelectionMode = 'select' | 'deselect';

export function toggleVolumeSelection(current: ReadonlySet<string>, volumeId: string): Set<string> {
  const next = new Set(current);
  if (next.has(volumeId)) next.delete(volumeId);
  else next.add(volumeId);
  return next;
}

export function applyVolumeSelectionMode(current: ReadonlySet<string>, volumeId: string, mode: VolumeSelectionMode): Set<string> {
  const next = new Set(current);
  if (mode === 'select') next.add(volumeId);
  else next.delete(volumeId);
  return next;
}

export function contextVolumeSelection(current: ReadonlySet<string>, volumeId: string): Set<string> {
  return current.has(volumeId) ? new Set(current) : new Set([volumeId]);
}

export function pruneVolumeSelection(current: ReadonlySet<string>, availableIds: readonly string[]): Set<string> {
  const available = new Set(availableIds);
  return new Set([...current].filter((volumeId) => available.has(volumeId)));
}
