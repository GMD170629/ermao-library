import type { MediaVersionResource, VolumeResource, WorkDetailTab, WorkDetailTabKey, WorkView } from '../../types/work';

export const DEFAULT_WORK_DETAIL_TAB_ORDER: readonly WorkDetailTabKey[] = [
  'EBOOK',
  'COMIC',
  'AUDIOBOOK',
  'STRUCTURE'
];

export const WORK_DETAIL_TAB_LABELS: Record<WorkDetailTabKey, string> = {
  EBOOK: '电子书',
  COMIC: '漫画',
  AUDIOBOOK: '有声书',
  STRUCTURE: '内容结构'
};

export function isWorkDetailTabKey(value: unknown): value is WorkDetailTabKey {
  return typeof value === 'string' && DEFAULT_WORK_DETAIL_TAB_ORDER.includes(value as WorkDetailTabKey);
}

export function workDetailTabHref(workId: string, tab: WorkDetailTabKey, volumeId?: string | null): string {
  const query = new URLSearchParams({ detailTab: tab });
  if (volumeId) query.set('volumeId', volumeId);
  return `/works/${encodeURIComponent(workId)}?${query}`;
}

export function normalizeWorkDetailTabOrder(value: unknown): WorkDetailTabKey[] {
  let candidate: unknown = value;
  if (typeof candidate === 'string') {
    try {
      candidate = JSON.parse(candidate);
    } catch {
      candidate = [];
    }
  }
  const normalized = Array.isArray(candidate) ? candidate.filter(isWorkDetailTabKey) : [];
  return [...new Set([...normalized, ...DEFAULT_WORK_DETAIL_TAB_ORDER])];
}

export function detailTabsForBook(_work: WorkView): WorkDetailTab[] {
  const available = new Set(_work.availableMediaKinds);
  const supplied = _work.detailTabs.length ? _work.detailTabs : DEFAULT_WORK_DETAIL_TAB_ORDER.map((key, sortOrder) => ({ key, label: WORK_DETAIL_TAB_LABELS[key], sortOrder }));
  const visible = supplied.filter((tab) => tab.key === 'STRUCTURE' || available.has(tab.key));
  const missing = DEFAULT_WORK_DETAIL_TAB_ORDER
    .filter((key) => (key === 'STRUCTURE' || available.has(key)) && !visible.some((tab) => tab.key === key))
    .map((key, sortOrder) => ({ key, label: WORK_DETAIL_TAB_LABELS[key], sortOrder: supplied.length + sortOrder }));
  return [...visible, ...missing]
    .sort((left, right) => left.sortOrder - right.sortOrder || left.key.localeCompare(right.key));
}

export function resolvedDetailTab(work: WorkView, requested?: WorkDetailTabKey | null): WorkDetailTabKey {
  const visible = new Set(detailTabsForBook(work).map((tab) => tab.key));
  const candidates: Array<WorkDetailTabKey | null | undefined> = [
    requested,
    work.selectedDetailTab,
    work.recentMediaKind,
    'STRUCTURE'
  ];
  return candidates.find((candidate): candidate is WorkDetailTabKey => Boolean(candidate && visible.has(candidate))) ?? 'STRUCTURE';
}

export function mediaVersionForDetailTab(work: WorkView, tab: WorkDetailTabKey): MediaVersionResource | null {
  if (tab === 'STRUCTURE') return null;
  return work.mediaVersions.find((mediaVersion) => mediaVersion.mediaKind === tab) ?? null;
}

export function volumesForDetailTab(work: WorkView, tab: WorkDetailTabKey): VolumeResource[] {
  return (mediaVersionForDetailTab(work, tab)?.volumes ?? [])
    .filter((volume) => !volume.hidden)
    .sort((left, right) => left.sortOrder - right.sortOrder || left.id.localeCompare(right.id));
}

export function displayVolumeNumber(volume: VolumeResource, position: number): number {
  return volume.volumeIndex ?? position + 1;
}

export function selectedVolumeForDetailTab(
  work: WorkView,
  tab: WorkDetailTabKey,
  requestedVolumeId?: string | null
): VolumeResource | null {
  const volumes = volumesForDetailTab(work, tab);
  return volumes.find((volume) => volume.id === requestedVolumeId)
    ?? volumes.find((volume) => volume.id === work.continueVolumeId)
    ?? volumes[0]
    ?? null;
}

export function moveWorkDetailTab(
  order: readonly WorkDetailTabKey[],
  key: WorkDetailTabKey,
  direction: -1 | 1
): WorkDetailTabKey[] {
  const normalized = normalizeWorkDetailTabOrder(order);
  const index = normalized.indexOf(key);
  const target = index + direction;
  if (index < 0 || target < 0 || target >= normalized.length) return normalized;
  const next = [...normalized];
  [next[index], next[target]] = [next[target], next[index]];
  return next;
}

export function placeWorkDetailTab(
  order: readonly WorkDetailTabKey[],
  source: WorkDetailTabKey,
  target: WorkDetailTabKey
): WorkDetailTabKey[] {
  const normalized = normalizeWorkDetailTabOrder(order);
  const sourceIndex = normalized.indexOf(source);
  const targetIndex = normalized.indexOf(target);
  if (sourceIndex < 0 || targetIndex < 0 || sourceIndex === targetIndex) return normalized;
  const next = [...normalized];
  const [moved] = next.splice(sourceIndex, 1);
  if (!moved) return normalized;
  next.splice(targetIndex, 0, moved);
  return next;
}

export function formatDuration(durationMs: number | null | undefined): string {
  if (!durationMs || durationMs <= 0) return '';
  const totalSeconds = Math.round(durationMs / 1000);
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  return hours > 0
    ? `${hours}:${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`
    : `${minutes}:${String(seconds).padStart(2, '0')}`;
}
