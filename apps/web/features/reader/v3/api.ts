import { normalizeReaderPreferences, parseReadiumLocatorEnvelope, publicationFingerprintsMatch, type PublicationFingerprint, type ReaderLocation, type ReaderNavigationEntry, type ReaderSource, type ReflowableFormat } from '@shuku/reader-core';
import { withBasePath } from '../../../lib/base-path';
import { parseReaderV4ProgressSnapshot, v4LocationToDomain, type ReaderProgressSnapshot } from '../../../lib/reader';
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
  schemaVersion: 4;
  userId: string;
  readerType: VisualReaderType;
  sourceFormat: ReflowableFormat | null;
  contentFingerprint: string;
  publicationFingerprint: PublicationFingerprint;
  book: Readonly<{ id: string; title: string; author: string | null; coverUrl: string | null }>;
  mediaVersion: Readonly<{ id: string; workId: string; mediaKind: MediaKind; completed: boolean }>;
  volume: ReaderVolume;
  availableVolumes: ReaderVolume[];
  files: ReadonlyArray<Readonly<{ id: string; kind: string; mimeType: string; sizeBytes: number; contentHash: string | null; durationMs: number | null; discNumber: number | null; trackNumber: number | null; sortOrder: number; url: string }>>;
  units: ReaderUnit[];
  pages: ReaderPage[];
  fileUrl: string;
  capabilities: import('@shuku/reader-core').ReaderCapabilities;
  resumeFingerprintMismatch: boolean;
  progressPercent: number;
  serverProgressSnapshot: ReaderProgressSnapshot | null;
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

function publicationFingerprint(value: unknown): PublicationFingerprint | null {
  const item = record(value);
  const originalFileHash = stringValue(item.originalFileHash).trim();
  const parser = stringValue(item.parser).trim();
  const normalization = stringValue(item.normalization).trim();
  return /^(?:sha256:)?[a-f\d]{64}$/iu.test(originalFileHash) && parser && normalization
    ? { originalFileHash: `sha256:${originalFileHash.replace(/^sha256:/iu, '').toLowerCase()}`, parser, normalization }
    : null;
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

export async function fetchReaderBootstrap(volumeId: string, signal: AbortSignal): Promise<ReaderBootstrap> {
  const response = await fetch(`/api/reader/v4/volumes/${encodeURIComponent(volumeId)}/bootstrap`, { credentials: 'same-origin', cache: 'no-store', signal });
  const payload: unknown = await response.json().catch(() => null);
  const envelope = record(payload);
  if (!response.ok || envelope.ok !== true) {
    const error = record(payload) as ReaderErrorResponse;
    throw new Error(error.error?.message ?? error.detail ?? `读取阅读器启动信息失败（${response.status}）`);
  }
  const data = record(envelope.data);
  if (data.schemaVersion !== 4) throw new Error('当前客户端不支持该阅读协议');
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
  const publicationAccess = record(data.publication);
  const files = (Array.isArray(data.files) ? data.files : []).flatMap((raw) => {
    const file = record(raw);
    const id = stringValue(file.id).trim();
    if (!id) return [];
    return [{ id, kind: stringValue(file.kind), mimeType: stringValue(file.mimeType), sizeBytes: numberValue(file.sizeBytes), contentHash: nullableString(file.contentHash), durationMs: nullableNumber(file.durationMs), discNumber: nullableNumber(file.discNumber), trackNumber: nullableNumber(file.trackNumber), sortOrder: numberValue(file.sortOrder), url: withBasePath(stringValue(file.url)) }];
  });
  const fileUrl = stringValue(data.fileUrl).trim();
  if (!fileUrl) throw new Error('阅读器启动信息缺少内容文件');
  const capabilities = record(data.capabilities);
  const fingerprint = publicationFingerprint(data.publicationFingerprint);
  if (readerType === 'reflowable' && !fingerprint) throw new Error('阅读器启动信息缺少 Publication 指纹');
  const contentFingerprint = fingerprint
    ? [fingerprint.originalFileHash, fingerprint.parser, fingerprint.normalization].join('\u0000')
    : 'non-reflowable';
  const serverProgressSnapshot = data.progressSnapshot === null || data.progressSnapshot === undefined
    ? null
    : parseReaderV4ProgressSnapshot(data.progressSnapshot);
  if (data.progressSnapshot !== null && data.progressSnapshot !== undefined && !serverProgressSnapshot) {
    throw new Error('阅读器启动信息包含无效的 Reader v4 进度快照');
  }
  const publicationManifestUrl = readerType === 'reflowable'
    ? nullableString(publicationAccess.manifestUrl)
    : null;
  if (readerType === 'reflowable' && !publicationManifestUrl) {
    throw new Error('READIUM_PUBLICATION_ENDPOINT_UNAVAILABLE');
  }
  const source: ReaderSource = readerType === 'reflowable'
    ? { workId, volumeId: volume.id, kind: 'reflowable', sourceFormat: format ?? 'epub', contentUrl: withBasePath(fileUrl), contentFingerprint, ...(fingerprint ? { publicationFingerprint: fingerprint } : {}), ...(publicationManifestUrl ? { publicationManifestUrl: withBasePath(publicationManifestUrl) } : {}), navigation: serverNavigation(units), totalPages: volume.pageCount }
    : { workId, volumeId: volume.id, kind: readerType, contentUrl: withBasePath(fileUrl), contentFingerprint, totalPages: volume.pageCount };
  const locationMatchesPublication = Boolean(serverProgressSnapshot && fingerprint
    && publicationFingerprintsMatch(serverProgressSnapshot.locator.publication, fingerprint));
  return {
    schemaVersion: 4,
    userId: stringValue(data.userId),
    readerType,
    sourceFormat: format,
    contentFingerprint,
    publicationFingerprint: fingerprint ?? {
      originalFileHash: '0'.repeat(64), parser: 'non-reflowable', normalization: 'non-reflowable-v1'
    },
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
    progressPercent: serverProgressSnapshot?.displayPercent ?? 0,
    serverProgressSnapshot,
    source,
    initialLocation: v4LocationToDomain(
      locationMatchesPublication ? serverProgressSnapshot?.locator ?? null : null,
      volume.id,
      format
    ),
    serverPreferences: { settings: normalizeReaderPreferences({}), updatedAt: null }
  };
}

export function readerBookmarkFromWire(
  value: unknown,
  volumeId: string,
  format: ReflowableFormat | null
): ReaderBookmark | null {
  const item = record(value);
  const id = stringValue(item.id).trim();
  const label = stringValue(item.label);
  const createdAt = stringValue(item.createdAt);
  const percent = Math.max(0, Math.min(100, numberValue(item.percent)));
  const wireLocation = record(item.location);
  const resourceKey = stringValue(wireLocation.resourceKey).trim();
  const resourceProgression = typeof wireLocation.progression === 'number'
    && Number.isFinite(wireLocation.progression)
    && wireLocation.progression >= 0
    && wireLocation.progression <= 1
    ? wireLocation.progression
    : undefined;
  const location: ReaderLocation | null = wireLocation.kind === 'reflow' && resourceKey && format
    ? {
        kind: 'reflowable',
        format,
        href: resourceKey,
        ...(resourceProgression !== undefined ? { resourceProgression } : {})
      }
    : null;
  if (!id || !createdAt || !location) return null;
  return { id, label, createdAt, location, percent };
}

export function readerBookmarkToWire(entry: ReaderBookmark) {
  const exact = entry.location.kind === 'reflowable' ? entry.location.exactLocator : null;
  const resourceKey = entry.location.kind === 'reflowable'
    ? entry.location.href ?? exact?.payload.href
    : null;
  const progression = entry.location.kind === 'reflowable'
    ? entry.location.resourceProgression ?? exact?.payload.locations.progression
    : null;
  if (!resourceKey) throw new Error('书签缺少可同步的位置锚点');
  return {
    ...entry,
    location: {
      kind: 'reflow' as const,
      resourceKey,
      ...(typeof progression === 'number' ? { progression } : {})
    }
  };
}

export async function fetchReaderBookmarks(volumeId: string, contentFingerprint: string, format: ReflowableFormat | null, signal?: AbortSignal): Promise<ReaderBookmark[]> {
  const query = new URLSearchParams({ contentFingerprint });
  const response = await fetch(`/api/reader/v4/volumes/${encodeURIComponent(volumeId)}/bookmarks?${query}`, { credentials: 'same-origin', cache: 'no-store', signal });
  const payload: unknown = await response.json().catch(() => null);
  const root = record(payload);
  const data = record(root.data);
  if (!response.ok || root.ok !== true || !Array.isArray(data.bookmarks)) throw new Error(stringValue(record(root.error).message, '读取书签失败'));
  return data.bookmarks.map((item) => readerBookmarkFromWire(item, volumeId, format)).filter((item): item is ReaderBookmark => item !== null);
}

export async function saveReaderBookmarks(volumeId: string, contentFingerprint: string, format: ReflowableFormat | null, bookmarks: ReaderBookmark[]): Promise<ReaderBookmark[]> {
  const wireBookmarks = bookmarks.map(readerBookmarkToWire);
  const response = await fetch(`/api/reader/v4/volumes/${encodeURIComponent(volumeId)}/bookmarks`, { method: 'PUT', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ contentFingerprint, bookmarks: wireBookmarks }) });
  const payload: unknown = await response.json().catch(() => null);
  const root = record(payload);
  const data = record(root.data);
  if (!response.ok || root.ok !== true || !Array.isArray(data.bookmarks)) throw new Error(stringValue(record(root.error).message, '保存书签失败'));
  return data.bookmarks.map((item) => readerBookmarkFromWire(item, volumeId, format)).filter((item): item is ReaderBookmark => item !== null);
}
