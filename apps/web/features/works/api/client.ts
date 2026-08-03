import type { ClassificationSource, MediaKind, MediaVersionResource, ReaderType, VolumeFormat, VolumeResource, WorkDetailTab, WorkDetailTabKey, WorkView } from '../../../types/work';
import type { ChapterDetailUnit, EbookChapterDetail } from '../model/chapter-detail';

function record(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function stringValue(value: unknown, fallback = ''): string {
  return typeof value === 'string' ? value : fallback;
}

function nullableString(value: unknown): string | null {
  return typeof value === 'string' && value.trim() ? value : null;
}

function finiteNumber(value: unknown, fallback = 0): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : fallback;
}

function nullableNumber(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function positiveInteger(value: unknown, fallback: number): number {
  return typeof value === 'number' && Number.isInteger(value) && value > 0 ? value : fallback;
}

function mediaKind(value: unknown): MediaKind | null {
  return value === 'EBOOK' || value === 'COMIC' || value === 'AUDIOBOOK' ? value : null;
}

function detailTabKey(value: unknown): WorkDetailTabKey | null {
  return mediaKind(value) ?? (value === 'STRUCTURE' ? value : null);
}

function parseAvailableMediaKinds(value: unknown, mediaVersions: readonly MediaVersionResource[]): MediaKind[] {
  const parsed = Array.isArray(value) ? value.map(mediaKind).filter((kind): kind is MediaKind => kind !== null) : [];
  const fallback = mediaVersions.map((mediaVersion) => mediaVersion.mediaKind);
  return [...new Set(parsed.length ? parsed : fallback)];
}

function parseDetailTabs(value: unknown): WorkDetailTab[] {
  if (!Array.isArray(value)) return [];
  const seen = new Set<WorkDetailTabKey>();
  return value.flatMap((entry, index) => {
    const item = record(entry);
    const key = detailTabKey(item.key);
    if (!key || seen.has(key)) return [];
    seen.add(key);
    return [{ key, label: stringValue(item.label, key), sortOrder: finiteNumber(item.sortOrder, index) }];
  });
}

function volumeFormat(value: unknown): VolumeFormat | null {
  return value === 'COMIC' || value === 'CBZ' || value === 'CBR' || value === 'RAR' || value === 'ZIP' || value === 'EPUB' || value === 'PDF' || value === 'AUDIO' || value === 'MP3' || value === 'M4A' || value === 'M4B' || value === 'MOBI' || value === 'AZW' || value === 'AZW3' || value === 'PRC' || value === 'FB2' || value === 'TXT' ? value : null;
}

function readerType(value: unknown, format: VolumeFormat): ReaderType {
  if (value === 'reflowable' || value === 'comic' || value === 'pdf' || value === 'audio') return value;
  if (format === 'PDF') return 'pdf';
  if (format === 'COMIC' || format === 'CBZ' || format === 'CBR' || format === 'RAR' || format === 'ZIP') return 'comic';
  if (format === 'AUDIO' || format === 'MP3' || format === 'M4A' || format === 'M4B') return 'audio';
  return 'reflowable';
}

function classificationSource(value: unknown): ClassificationSource {
  return value === 'AUTO' || value === 'MONITOR_FOLDER' || value === 'USER' || value === 'INHERITED' || value === 'LEGACY' ? value : 'LEGACY';
}

function mapVolume(value: unknown): VolumeResource | null {
  const item = record(value);
  const id = stringValue(item.id).trim();
  const mediaVersionId = stringValue(item.mediaVersionId).trim();
  const format = volumeFormat(item.format);
  if (!id || !mediaVersionId || !format) return null;
  const files = (Array.isArray(item.files) ? item.files : []).flatMap((rawFile) => {
    const file = record(rawFile);
    const fileId = stringValue(file.id).trim();
    if (!fileId) return [];
    return [{
      id: fileId,
      volumeId: id,
      path: stringValue(file.path),
      mimeType: stringValue(file.mimeType),
      kind: stringValue(file.kind),
      sortOrder: finiteNumber(file.sortOrder),
      sizeBytes: finiteNumber(file.sizeBytes),
      size: stringValue(file.size),
      durationMs: nullableNumber(file.durationMs),
      codec: nullableString(file.codec),
      bitrate: nullableNumber(file.bitrate),
      sampleRate: nullableNumber(file.sampleRate),
      channels: nullableNumber(file.channels),
      discNumber: nullableNumber(file.discNumber),
      trackNumber: nullableNumber(file.trackNumber),
      url: nullableString(file.url) ?? undefined
    }];
  });
  const classification = record(item.classification);
  return {
    id,
    mediaVersionId,
    title: stringValue(item.title, id),
    volumeIndex: nullableNumber(item.volumeIndex),
    sortOrder: finiteNumber(item.sortOrder),
    format,
    readerType: readerType(item.readerType, format),
    classification: {
      source: classificationSource(classification.source),
      reason: stringValue(classification.reason, 'LEGACY'),
      suggestedMediaKind: mediaKind(classification.suggestedMediaKind)
    },
    derivedFromVolumeId: nullableString(item.derivedFromVolumeId),
    publisher: nullableString(item.publisher),
    publishedAt: nullableString(item.publishedAt),
    language: nullableString(item.language),
    isbn: nullableString(item.isbn),
    identifier: nullableString(item.identifier),
    narrator: nullableString(item.narrator),
    abridged: typeof item.abridged === 'boolean' ? item.abridged : null,
    importStatus: stringValue(item.importStatus),
    importError: nullableString(item.importError),
    coverUrl: stringValue(item.coverUrl),
    sizeBytes: finiteNumber(item.sizeBytes),
    pageCount: nullableNumber(item.pageCount),
    chapterCount: nullableNumber(item.chapterCount),
    durationMs: nullableNumber(item.durationMs),
    trackCount: nullableNumber(item.trackCount),
    progress: Math.max(0, Math.min(100, finiteNumber(item.progress))),
    lastReadAt: nullableString(item.lastReadAt),
    hidden: item.hidden === true,
    readable: item.readable !== false,
    conversionAvailable: item.conversionAvailable === true,
    kindleSendAvailable: item.kindleSendAvailable === true,
    files
  };
}

function mapMediaVersion(value: unknown): MediaVersionResource | null {
  const item = record(value);
  const id = stringValue(item.id).trim();
  const kind = mediaKind(item.mediaKind);
  if (!id || !kind) return null;
  return {
    id,
    mediaKind: kind,
    completed: item.completed === true,
    volumeCount: Math.max(0, finiteNumber(item.volumeCount, Array.isArray(item.volumes) ? item.volumes.length : 0)),
    sizeBytes: Math.max(0, finiteNumber(item.sizeBytes)),
    volumes: (Array.isArray(item.volumes) ? item.volumes : []).map(mapVolume).filter((volume): volume is VolumeResource => volume !== null)
  };
}

export type MediaVersionVolumePage = Readonly<{
  mediaVersionId: string;
  mediaKind: MediaKind;
  volumes: VolumeResource[];
  page: number;
  pageSize: number;
  total: number;
  totalPages: number;
}>;

export type WorkTransferTarget = Readonly<{
  id: string;
  title: string;
  author: string;
}>;

export function mapWorkView(value: unknown): WorkView {
  const root = record(value);
  const id = stringValue(root.id).trim();
  if (!id || !Array.isArray(root.mediaVersions)) throw new Error('作品响应缺少媒介版本结构');
  const recentMediaKind = mediaKind(root.recentMediaKind);
  const mediaVersions = root.mediaVersions.map(mapMediaVersion).filter((item): item is MediaVersionResource => item !== null);
  const publicationStatus = root.publicationStatus === 'ONGOING' || root.publicationStatus === 'COMPLETED' || root.publicationStatus === 'HIATUS' || root.publicationStatus === 'CANCELLED' ? root.publicationStatus : 'UNKNOWN';
  const trackingStatus = root.trackingStatus === 'TRACKING' || root.trackingStatus === 'PAUSED' || root.trackingStatus === 'IGNORED' ? root.trackingStatus : 'NOT_TRACKING';
  return {
    id,
    title: stringValue(root.title, '未命名作品'),
    author: stringValue(root.author, '未知作者'),
    description: stringValue(root.description),
    seriesName: nullableString(root.seriesName),
    seriesIndex: nullableNumber(root.seriesIndex),
    tags: Array.isArray(root.tags) ? root.tags.filter((tag): tag is string => typeof tag === 'string') : [],
    publicationStatus,
    trackingStatus,
    ignored: root.ignored === true,
    organized: root.organized === true,
    metadataQuality: finiteNumber(root.metadataQuality),
    addedAt: stringValue(root.addedAt),
    updatedAt: stringValue(root.updatedAt),
    coverUrl: stringValue(root.coverUrl),
    coverStatus: stringValue(root.coverStatus),
    gradient: stringValue(root.gradient),
    recentMediaKind,
    continueVolumeId: nullableString(root.continueVolumeId),
    availableMediaKinds: parseAvailableMediaKinds(root.availableMediaKinds, mediaVersions),
    detailTabs: parseDetailTabs(root.detailTabs),
    selectedDetailTab: detailTabKey(root.selectedDetailTab),
    completed: root.completed === true,
    mediaVersions
  };
}

async function apiJson(path: string, init?: RequestInit): Promise<unknown> {
  const response = await fetch(path, { credentials: 'same-origin', cache: 'no-store', ...init });
  const payload: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    const error = record(payload);
    const nestedError = record(error.error);
    throw new Error(stringValue(nestedError.message) || stringValue(error.detail) || `请求失败（${response.status}）`);
  }
  const envelope = record(payload);
  return envelope.ok === true && 'data' in envelope ? envelope.data : payload;
}

export async function fetchWork(workId: string, signal?: AbortSignal): Promise<WorkView> {
  const data = record(await apiJson(`/api/works/${encodeURIComponent(workId)}`, { signal }));
  return mapWorkView(data.book ?? data.work ?? data);
}

export async function fetchMediaVersionVolumes(
  workId: string,
  mediaVersionId: string,
  page: number,
  pageSize: number,
  signal?: AbortSignal
): Promise<MediaVersionVolumePage> {
  const query = new URLSearchParams({ page: String(page), pageSize: String(pageSize) });
  const data = record(await apiJson(`/api/works/${encodeURIComponent(workId)}/media-versions/${encodeURIComponent(mediaVersionId)}/volumes?${query}`, { signal }));
  const kind = mediaKind(data.mediaKind);
  if (stringValue(data.mediaVersionId) !== mediaVersionId || !kind) throw new Error('卷册分页响应与请求不匹配');
  const resolvedPageSize = positiveInteger(data.pageSize, pageSize);
  const total = Math.max(0, finiteNumber(data.total));
  return {
    mediaVersionId,
    mediaKind: kind,
    volumes: (Array.isArray(data.volumes) ? data.volumes : []).map(mapVolume).filter((volume): volume is VolumeResource => volume !== null),
    page: positiveInteger(data.page, page),
    pageSize: resolvedPageSize,
    total,
    totalPages: positiveInteger(data.totalPages, Math.max(1, Math.ceil(total / resolvedPageSize)))
  };
}

export async function fetchAllMediaVersionVolumes(
  workId: string,
  mediaVersionId: string,
  signal?: AbortSignal
): Promise<VolumeResource[]> {
  const firstPage = await fetchMediaVersionVolumes(workId, mediaVersionId, 1, 100, signal);
  const volumes = [...firstPage.volumes];
  for (let page = 2; page <= firstPage.totalPages; page += 1) {
    const nextPage = await fetchMediaVersionVolumes(workId, mediaVersionId, page, 100, signal);
    volumes.push(...nextPage.volumes);
  }
  return volumes;
}

export async function searchWorkTransferTargets(
  search: string,
  excludedWorkId: string,
  signal?: AbortSignal
): Promise<WorkTransferTarget[]> {
  const query = new URLSearchParams({
    page: '1',
    pageSize: '20',
    view: 'bookshelf',
    visibility: 'active',
    search: search.trim()
  });
  const data = record(await apiJson(`/api/works?${query}`, { signal }));
  if (!Array.isArray(data.books)) throw new Error('目标图书搜索响应无效');
  return data.books.flatMap((value) => {
    const item = record(value);
    const id = stringValue(item.id).trim();
    if (!id || id === excludedWorkId) return [];
    return [{
      id,
      title: stringValue(item.title, id),
      author: stringValue(item.author)
    }];
  });
}

function mapChapterUnit(value: unknown): ChapterDetailUnit | null {
  const item = record(value);
  const id = stringValue(item.id).trim();
  if (!id) return null;
  const metadata = record(item.metadataJson);
  return {
    id,
    title: nullableString(item.title) ?? '',
    href: nullableString(item.href),
    sortOrder: finiteNumber(item.sortOrder),
    unitType: stringValue(item.unitType, 'chapter'),
    pageNumber: nullableNumber(metadata.pageNumber)
  };
}

export async function fetchEbookChapterDetail(
  workId: string,
  volumeId: string,
  page: number,
  pageSize: number,
  signal?: AbortSignal
): Promise<EbookChapterDetail> {
  const query = new URLSearchParams({ page: String(page), pageSize: String(pageSize) });
  const data = record(await apiJson(`/api/works/${encodeURIComponent(workId)}/volumes/${encodeURIComponent(volumeId)}/reading-units?${query}`, { signal }));
  const pageData = record(data.page);
  const pageSizeValue = positiveInteger(pageData.pageSize, pageSize);
  const total = Math.max(0, finiteNumber(pageData.total));
  return {
    units: (Array.isArray(data.units) ? data.units : []).map(mapChapterUnit).filter((unit): unit is ChapterDetailUnit => unit !== null),
    page: {
      page: positiveInteger(pageData.page, page),
      pageSize: pageSizeValue,
      total,
      totalPages: positiveInteger(pageData.totalPages, Math.max(1, Math.ceil(total / pageSizeValue)))
    },
    currentHref: nullableString(data.currentHref),
    currentChapterSortOrder: nullableNumber(data.currentChapterSortOrder),
    currentPageNumber: nullableNumber(data.currentPageNumber),
    progress: Math.max(0, Math.min(100, finiteNumber(data.progress)))
  };
}

export async function updateVolume(workId: string, volumeId: string, body: Record<string, unknown>): Promise<void> {
  await apiJson(`/api/works/${encodeURIComponent(workId)}/volumes/${encodeURIComponent(volumeId)}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  });
}

export async function runVolumeAction(workId: string, volumeId: string, action: 'convert' | 'split' | 'move' | 'move-to', body?: Record<string, unknown>): Promise<void> {
  await apiJson(`/api/works/${encodeURIComponent(workId)}/volumes/${encodeURIComponent(volumeId)}/${action}`, {
    method: 'POST',
    headers: body ? { 'Content-Type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined
  });
}

export async function reclassifyVolume(
  workId: string,
  volumeId: string,
  targetMediaKind: MediaKind,
  applyTo: 'VOLUME' | 'MEDIA_VERSION'
): Promise<string | null> {
  const data = record(await apiJson(`/api/works/${encodeURIComponent(workId)}/volumes/${encodeURIComponent(volumeId)}/reclassify`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ targetMediaKind, applyTo })
  }));
  return nullableString(record(data.operation).id);
}

export async function undoLibraryOperation(operationId: string): Promise<void> {
  await apiJson(`/api/library/operations/${encodeURIComponent(operationId)}/undo`, { method: 'POST' });
}

export async function deleteVolume(workId: string, volumeId: string): Promise<void> {
  await apiJson(`/api/works/${encodeURIComponent(workId)}/volumes/${encodeURIComponent(volumeId)}`, { method: 'DELETE' });
}

export async function updateWorkReadingStatus(workId: string, status: 'UNREAD' | 'FINISHED'): Promise<void> {
  await apiJson('/api/works/bulk', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ids: [workId], action: 'reading_status', status })
  });
}

export type WorkMetadataInput = Readonly<{
  title: string;
  author: string;
  description: string;
  seriesName: string | null;
  seriesIndex: number | null;
  tags: string[];
}>;

export async function updateWorkMetadata(workId: string, input: WorkMetadataInput): Promise<WorkView> {
  const data = record(await apiJson(`/api/works/${encodeURIComponent(workId)}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ...input, organized: true })
  }));
  return mapWorkView(data.book ?? data.work ?? data);
}

export async function uploadWorkCover(workId: string, file: File): Promise<void> {
  const body = new FormData();
  body.append('cover', file);
  await apiJson(`/api/works/${encodeURIComponent(workId)}/cover/upload`, { method: 'POST', body });
}

export async function regenerateWorkCover(workId: string): Promise<void> {
  await apiJson(`/api/works/${encodeURIComponent(workId)}/cover/regenerate`, { method: 'POST' });
}

export type DeletedWorkResult = Readonly<{
  deletedSourceFiles: number;
  failedFileDeletes: ReadonlyArray<Readonly<{ path: string; message: string }>>;
}>;

export async function deleteWorkRecord(workId: string): Promise<DeletedWorkResult> {
  const data = record(await apiJson(`/api/works/${encodeURIComponent(workId)}`, {
    method: 'DELETE',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ deleteSource: false })
  }));
  return {
    deletedSourceFiles: Math.max(0, finiteNumber(data.deletedSourceFiles)),
    failedFileDeletes: (Array.isArray(data.failedFileDeletes) ? data.failedFileDeletes : []).flatMap((entry) => {
      const item = record(entry);
      const path = nullableString(item.path);
      const message = nullableString(item.message);
      return path && message ? [{ path, message }] : [];
    })
  };
}
