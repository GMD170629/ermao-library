import type { MediaKind, WorkDetailTab, WorkDetailTabKey, WorkView } from '../../types/work';
import type { AudioPlaybackState } from '../audio/types';

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

export function workDetailTabHref(workId: string, tab: WorkDetailTabKey): string {
  return `/works/${encodeURIComponent(workId)}?detailTab=${tab}`;
}

/**
 * System settings are intentionally forgiving: accept a JSON string or an
 * already parsed array, discard unknown/duplicate values, then append missing
 * tabs in the product default order.
 */
export function normalizeWorkDetailTabOrder(value: unknown): WorkDetailTabKey[] {
  let candidate: unknown = value;
  if (typeof candidate === 'string') {
    try {
      candidate = JSON.parse(candidate);
    } catch {
      candidate = [];
    }
  }

  const normalized = Array.isArray(candidate)
    ? candidate.filter(isWorkDetailTabKey)
    : [];
  return [...new Set([...normalized, ...DEFAULT_WORK_DETAIL_TAB_ORDER])];
}

export function mediaKindForEdition(edition: WorkView['editions'][number]): MediaKind {
  if (edition.mediaKind) return edition.mediaKind;
  if (edition.formatValue === 'COMIC') return 'COMIC';
  if (edition.formatValue === 'AUDIO') return 'AUDIOBOOK';
  return 'EBOOK';
}

export function availableMediaKinds(book: WorkView): MediaKind[] {
  const declared = (book.availableMediaKinds ?? []).filter((kind): kind is MediaKind => (
    kind === 'EBOOK' || kind === 'COMIC' || kind === 'AUDIOBOOK'
  ));
  const inferred = book.editions
    .filter((edition) => !edition.hidden)
    .map(mediaKindForEdition);
  return [...new Set([...declared, ...inferred])];
}

/** Uses the API-provided visibility/order when present and infers legacy data otherwise. */
export function detailTabsForBook(book: WorkView): WorkDetailTab[] {
  const kinds = new Set(availableMediaKinds(book));
  const apiTabs = (book.detailTabs ?? [])
    .filter((tab) => isWorkDetailTabKey(tab.key))
    .filter((tab) => tab.key === 'STRUCTURE' || kinds.has(tab.key))
    .sort((left, right) => left.sortOrder - right.sortOrder)
    .filter((tab, index, tabs) => tabs.findIndex((candidate) => candidate.key === tab.key) === index)
    .map((tab, index) => ({
      key: tab.key,
      label: tab.label || WORK_DETAIL_TAB_LABELS[tab.key],
      sortOrder: index
    }));
  if (apiTabs.length > 0) {
    return apiTabs.some((tab) => tab.key === 'STRUCTURE')
      ? apiTabs
      : [...apiTabs, { key: 'STRUCTURE', label: WORK_DETAIL_TAB_LABELS.STRUCTURE, sortOrder: apiTabs.length }];
  }

  return DEFAULT_WORK_DETAIL_TAB_ORDER
    .filter((key) => key === 'STRUCTURE' || kinds.has(key))
    .map((key, sortOrder) => ({ key, label: WORK_DETAIL_TAB_LABELS[key], sortOrder }));
}

export function resolvedDetailTab(book: WorkView, requested?: WorkDetailTabKey | null): WorkDetailTabKey {
  const tabs = detailTabsForBook(book);
  const visible = new Set(tabs.map((tab) => tab.key));
  const candidates: Array<WorkDetailTabKey | null | undefined> = [requested, book.selectedDetailTab, book.defaultMediaKind, tabs[0]?.key, 'STRUCTURE'];
  return candidates.find((candidate): candidate is WorkDetailTabKey => Boolean(candidate && visible.has(candidate))) ?? 'STRUCTURE';
}

export function editionsForDetailTab(book: WorkView, tab: WorkDetailTabKey): WorkView['editions'] {
  if (tab === 'STRUCTURE') return [];
  const grouped = book.mediaGroups?.find((group) => group.kind === tab)?.editions;
  const editions = grouped?.length ? grouped : book.editions.filter((edition) => mediaKindForEdition(edition) === tab);
  return editions.filter((edition) => !edition.hidden);
}

export function selectedEditionForDetailTab(
  book: WorkView,
  tab: WorkDetailTabKey,
  selectedEditionId?: string | null
): WorkView['editions'][number] | null {
  const editions = editionsForDetailTab(book, tab);
  if (editions.length === 0) return null;
  const group = tab === 'STRUCTURE' ? null : book.mediaGroups?.find((candidate) => candidate.kind === tab);
  const candidates = [selectedEditionId, group?.recentEditionId, group?.primaryEditionId, book.recentEditionId, book.primaryEditionId];
  for (const id of candidates) {
    const edition = editions.find((candidate) => candidate.id === id);
    if (edition) return edition;
  }
  return editions[0] ?? null;
}

export function resolveVolumeIdForSections(
  volumes: ReadonlyArray<{ id: string }>,
  ...preferredVolumeIds: Array<string | null | undefined>
): string | null {
  const availableVolumeIds = new Set(volumes.map((volume) => volume.id));
  return preferredVolumeIds.find((volumeId): volumeId is string => (
    Boolean(volumeId && availableVolumeIds.has(volumeId))
  )) ?? volumes[0]?.id ?? null;
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

export function audioDetailProjection(
  tab: WorkDetailTabKey,
  workId: string,
  editionId: string | null,
  playback: Pick<AudioPlaybackState, 'bootstrap' | 'absolutePositionMs' | 'totalDurationMs' | 'positionMs' | 'track' | 'chapter'>
) {
  const bootstrap = playback.bootstrap;
  if (
    tab !== 'AUDIOBOOK'
    || !editionId
    || bootstrap?.book.id !== workId
    || bootstrap.edition.workId !== workId
    || bootstrap.edition.id !== editionId
  ) return null;

  const totalDurationMs = playback.totalDurationMs || bootstrap.totalDurationMs;
  const progress = totalDurationMs > 0
    ? Math.max(0, Math.min(100, playback.absolutePositionMs / totalDurationMs * 100))
    : bootstrap.progressPercent;
  const title = playback.chapter?.title ?? playback.track?.title ?? '准备播放';
  const position = formatDuration(playback.positionMs);
  return {
    progress,
    positionLabel: position ? `${title} · ${position}` : title,
    currentChapterId: playback.chapter?.id ?? null,
    currentFileId: playback.chapter?.fileId ?? playback.track?.fileId ?? null,
    currentChapterStartMs: playback.chapter?.startMs ?? null
  };
}
