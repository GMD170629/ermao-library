import { normalizeReaderPreferences, type ReaderLocation, type ReaderNavigationEntry, type ReaderSource, type ReflowableFormat } from '@shuku/reader-core';
import { withBasePath } from '../../../lib/base-path';
import type { ReaderBookmark } from './bookmarks';

type VisualReaderType = 'reflowable' | 'comic' | 'pdf';
type MediaKind = 'EBOOK' | 'COMIC' | 'AUDIOBOOK';

export type ReaderVolume = Readonly<{
  id: string;
  mediaVersionId: string;
  title: string;
  volumeIndex: number | null;
  sortOrder: number;
  format: string;
  readerType: VisualReaderType | 'audio';
  derivedFromVolumeId: string | null;
  pageCount: number | null;
  chapterCount: number | null;
  durationMs: number | null;
  trackCount: number | null;
  progress: number;
  lastReadAt: string | null;
}>;

export type ReaderUnit = Readonly<{
  id: string;
  index: number;
  title: string;
  href: string | null;
  fileId: string | null;
  startMs: number | null;
  endMs: number | null;
  durationMs: number | null;
  metadata: Record<string, unknown>;
}>;

export type ReaderPage = Readonly<{
  pageIndex: number;
  title: string | null;
  mimeType: string | null;
  width: number | null;
  height: number | null;
  size: number | null;
}>;

export type ReaderBootstrap = Readonly<{
  schemaVersion: 3;
  userId: string;
  readerType: VisualReaderType;
  sourceFormat: ReflowableFormat | null;
  contentFingerprint: string;
  book: Readonly<{ id: string; title: string; author: string | null; coverUrl: string | null }>;
  mediaVersion: Readonly<{ id: string; workId: string; mediaKind: MediaKind; completed: boolean }>;
  volume: ReaderVolume;
  availableVolumes: ReaderVolume[];
  files: ReadonlyArray<Readonly<{ id: string; kind: string; mimeType: string; sizeBytes: number; durationMs: number | null; discNumber: number | null; trackNumber: number | null; sortOrder: number; url: string }>>;
  units: ReaderUnit[];
  pages: ReaderPage[];
  fileUrl: string;
  capabilities: import('@shuku/reader-core').ReaderCapabilities;
  resumeFingerprintMismatch: boolean;
  progressPercent: number;
  source: ReaderSource;
  initialLocation: ReaderLocation | null;
  serverPreferences: Readonly<{ settings: import('@shuku/reader-core').ReaderPreferences; updatedAt: string | null }>;
}>;

type ReaderErrorResponse = Readonly<{ error?: Readonly<{ message?: string }>; detail?: string }>;

function record(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function stringValue(value: unknown, fallback = ''): string {
  return typeof value === 'string' ? value : fallback;
}

function nullableString(value: unknown): string | null {
  return typeof value === 'string' && value.trim() ? value : null;
}

function numberValue(value: unknown, fallback = 0): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : fallback;
}

function nullableNumber(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function sourceFormat(value: unknown): ReflowableFormat | null {
  return value === 'epub' || value === 'mobi' || value === 'azw' || value === 'azw3' || value === 'prc' || value === 'fb2' || value === 'txt' ? value : null;
}

function visualReaderType(value: unknown): VisualReaderType | null {
  return value === 'reflowable' || value === 'comic' || value === 'pdf' ? value : null;
}

function mapVolume(value: unknown): ReaderVolume | null {
  const item = record(value);
  const id = stringValue(item.id).trim();
  const mediaVersionId = stringValue(item.mediaVersionId).trim();
  const readerType = item.readerType === 'audio' ? 'audio' : visualReaderType(item.readerType);
  if (!id || !mediaVersionId || !readerType) return null;
  return {
    id,
    mediaVersionId,
    title: stringValue(item.title, id),
    volumeIndex: nullableNumber(item.volumeIndex),
    sortOrder: numberValue(item.sortOrder),
    format: stringValue(item.format),
    readerType,
    derivedFromVolumeId: nullableString(item.derivedFromVolumeId),
    pageCount: nullableNumber(item.pageCount),
    chapterCount: nullableNumber(item.chapterCount),
    durationMs: nullableNumber(item.durationMs),
    trackCount: nullableNumber(item.trackCount),
    progress: Math.max(0, Math.min(100, numberValue(item.progress))),
    lastReadAt: nullableString(item.lastReadAt)
  };
}

function mapUnits(value: unknown): ReaderUnit[] {
  return (Array.isArray(value) ? value : []).flatMap((raw) => {
    const item = record(raw);
    const id = stringValue(item.id).trim();
    if (!id) return [];
    return [{ id, index: numberValue(item.index), title: stringValue(item.title, id), href: nullableString(item.href), fileId: nullableString(item.fileId), startMs: nullableNumber(item.startMs), endMs: nullableNumber(item.endMs), durationMs: nullableNumber(item.durationMs), metadata: record(item.metadata) }];
  });
}

function serverNavigation(units: ReaderUnit[]): ReaderNavigationEntry[] {
  return units.filter((unit) => unit.href).map((unit) => ({ id: unit.id, navigationKey: unit.id, label: unit.title, href: unit.href ?? undefined, index: unit.index }));
}

function mapPages(units: ReaderUnit[]): ReaderPage[] {
  return units.map((unit) => ({
    pageIndex: Math.max(1, numberValue(unit.metadata.pageIndex, unit.index + 1)),
    title: unit.title || null,
    mimeType: nullableString(unit.metadata.mimeType),
    width: nullableNumber(unit.metadata.width),
    height: nullableNumber(unit.metadata.height),
    size: nullableNumber(unit.metadata.size)
  }));
}

export function wireLocationToDomain(value: unknown, volumeId: string): ReaderLocation | null {
  const location = record(value);
  if (location.type === 'epub') return { kind: 'reflowable', format: 'epub', cfi: nullableString(location.cfi) ?? undefined, href: nullableString(location.href) ?? undefined, progression: nullableNumber(location.progression) ?? undefined };
  if (location.type === 'reflowable') {
    const format = sourceFormat(location.format);
    if (!format) return null;
    return { kind: 'reflowable', format, cfi: nullableString(location.cfi) ?? undefined, href: nullableString(location.href) ?? undefined, progression: nullableNumber(location.progression) ?? undefined };
  }
  if (location.type === 'comic') return { kind: 'comic', volumeId, pageIndex: Math.max(1, numberValue(location.pageIndex, 1)) };
  if (location.type === 'pdf') return { kind: 'pdf', pageNumber: Math.max(1, numberValue(location.pageNumber, 1)) };
  return null;
}

export async function fetchReaderBootstrap(volumeId: string, signal: AbortSignal): Promise<ReaderBootstrap> {
  const response = await fetch(`/api/reader/v3/volumes/${encodeURIComponent(volumeId)}/bootstrap`, { credentials: 'same-origin', cache: 'no-store', signal });
  const payload: unknown = await response.json().catch(() => null);
  const envelope = record(payload);
  if (!response.ok || envelope.ok !== true) {
    const error = record(payload) as ReaderErrorResponse;
    throw new Error(error.error?.message ?? error.detail ?? `读取阅读器启动信息失败（${response.status}）`);
  }
  const data = record(envelope.data);
  if (data.schemaVersion !== 3) throw new Error('当前客户端不支持该阅读协议');
  const readerType = visualReaderType(data.readerType);
  const volume = mapVolume(data.volume);
  const book = record(data.book);
  const mediaVersion = record(data.mediaVersion);
  const workId = stringValue(mediaVersion.workId).trim();
  const mediaKind = mediaVersion.mediaKind;
  if (!readerType || !volume || !workId || (mediaKind !== 'EBOOK' && mediaKind !== 'COMIC' && mediaKind !== 'AUDIOBOOK')) throw new Error('阅读器启动信息不完整');
  const format = sourceFormat(data.sourceFormat);
  if (readerType === 'reflowable' && !format) throw new Error('可重排卷册缺少源格式');
  const units = mapUnits(data.units);
  const files = (Array.isArray(data.files) ? data.files : []).flatMap((raw) => {
    const file = record(raw);
    const id = stringValue(file.id).trim();
    if (!id) return [];
    return [{ id, kind: stringValue(file.kind), mimeType: stringValue(file.mimeType), sizeBytes: numberValue(file.sizeBytes), durationMs: nullableNumber(file.durationMs), discNumber: nullableNumber(file.discNumber), trackNumber: nullableNumber(file.trackNumber), sortOrder: numberValue(file.sortOrder), url: withBasePath(stringValue(file.url)) }];
  });
  const contentFingerprint = stringValue(data.contentFingerprint).trim();
  const fileUrl = stringValue(data.fileUrl).trim();
  if (!contentFingerprint || !fileUrl) throw new Error('阅读器启动信息缺少内容文件');
  const capabilities = record(data.capabilities);
  const source: ReaderSource = readerType === 'reflowable'
    ? { workId, volumeId: volume.id, kind: 'reflowable', sourceFormat: format ?? 'epub', contentUrl: withBasePath(fileUrl), contentFingerprint, navigation: serverNavigation(units), totalPages: volume.pageCount }
    : { workId, volumeId: volume.id, kind: readerType, contentUrl: withBasePath(fileUrl), contentFingerprint, totalPages: volume.pageCount };
  return {
    schemaVersion: 3,
    userId: stringValue(data.userId),
    readerType,
    sourceFormat: format,
    contentFingerprint,
    book: { id: stringValue(book.id, workId), title: stringValue(book.title, '未命名作品'), author: nullableString(book.author), coverUrl: nullableString(book.coverUrl) },
    mediaVersion: { id: stringValue(mediaVersion.id), workId, mediaKind, completed: mediaVersion.completed === true },
    volume,
    availableVolumes: (Array.isArray(data.availableVolumes) ? data.availableVolumes : []).map(mapVolume).filter((item): item is ReaderVolume => item !== null),
    files,
    units,
    pages: readerType === 'comic' ? mapPages(units) : [],
    fileUrl,
    capabilities: {
      canGoNext: capabilities.canGoNext === true,
      canGoPrevious: capabilities.canGoPrevious === true,
      canJumpToProgress: capabilities.canJumpToProgress === true,
      canJumpToHref: capabilities.canJumpToHref === true,
      canJumpToIndex: capabilities.canJumpToIndex === true,
      canZoom: capabilities.canZoom === true,
      canSelectText: capabilities.canSelectText === true,
      supportsPagination: capabilities.supportsPagination === true,
      supportsScrolling: capabilities.supportsScrolling === true,
      supportsSpreads: capabilities.supportsSpreads === true,
      readingDirection: 'ltr'
    },
    resumeFingerprintMismatch: data.resumeFingerprintMismatch === true,
    progressPercent: Math.max(0, Math.min(100, numberValue(data.progressPercent))),
    source,
    initialLocation: wireLocationToDomain(data.resumeLocation, volume.id),
    serverPreferences: { settings: normalizeReaderPreferences({}), updatedAt: null }
  };
}

function bookmark(value: unknown): ReaderBookmark | null {
  const item = record(value);
  const id = stringValue(item.id).trim();
  const label = stringValue(item.label);
  const createdAt = stringValue(item.createdAt);
  const location = wireLocationToDomain(item.location, stringValue(record(item.location).volumeId));
  if (!id || !createdAt || !location) return null;
  return { id, label, createdAt, location, percent: Math.max(0, Math.min(100, numberValue(item.percent))) };
}

export async function fetchReaderBookmarks(volumeId: string, contentFingerprint: string, signal?: AbortSignal): Promise<ReaderBookmark[]> {
  const query = new URLSearchParams({ contentFingerprint });
  const response = await fetch(`/api/reader/v3/volumes/${encodeURIComponent(volumeId)}/bookmarks?${query}`, { credentials: 'same-origin', cache: 'no-store', signal });
  const payload: unknown = await response.json().catch(() => null);
  const root = record(payload);
  const data = record(root.data);
  if (!response.ok || root.ok !== true || !Array.isArray(data.bookmarks)) throw new Error(stringValue(record(root.error).message, '读取书签失败'));
  return data.bookmarks.map(bookmark).filter((item): item is ReaderBookmark => item !== null);
}

export async function saveReaderBookmarks(volumeId: string, contentFingerprint: string, bookmarks: ReaderBookmark[]): Promise<ReaderBookmark[]> {
  const response = await fetch(`/api/reader/v3/volumes/${encodeURIComponent(volumeId)}/bookmarks`, { method: 'PUT', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ contentFingerprint, bookmarks }) });
  const payload: unknown = await response.json().catch(() => null);
  const root = record(payload);
  const data = record(root.data);
  if (!response.ok || root.ok !== true || !Array.isArray(data.bookmarks)) throw new Error(stringValue(record(root.error).message, '保存书签失败'));
  return data.bookmarks.map(bookmark).filter((item): item is ReaderBookmark => item !== null);
}
