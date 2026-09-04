import type { ReaderType, ReadableResourceView, ResourceFormat, ResourceImportSummary, BookView } from '../../../types/book';
import { withBasePath } from '../../../lib/base-path';
import { updateBulkBookCovers, type BulkBookCoverResult } from '../../library/public';
import type {
  ResourceChapterDetailUnit,
  ResourceDetailPage,
  ResourceDetailUnit,
  ResourcePageDetailUnit,
  ResourceTrackDetailUnit
} from '../model/resource-detail';
import type { BookContentEntry, BookContentsPage, BookContentSort, SourceNodeMetadataCandidate } from '../model/book-contents';
import { bookContentSortQuery } from '../model/book-contents';
import type { MetadataTargetScope, RecognizedMetadataField } from '../model/recognized-metadata';

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

function resourceImportSummary(value: unknown): ResourceImportSummary {
  const summary = record(value);
  return {
    ready: Math.max(0, Math.trunc(finiteNumber(summary.ready))),
    pending: Math.max(0, Math.trunc(finiteNumber(summary.pending))),
    failed: Math.max(0, Math.trunc(finiteNumber(summary.failed)))
  };
}

function nullableNumber(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function nullableInteger(value: unknown): number | null {
  return typeof value === 'number' && Number.isInteger(value) ? value : null;
}

function positiveInteger(value: unknown, fallback: number): number {
  return typeof value === 'number' && Number.isInteger(value) && value > 0 ? value : fallback;
}

function resourceFormat(value: unknown): ResourceFormat | null {
  return value === 'COMIC' || value === 'CBZ' || value === 'CBR' || value === 'RAR' || value === 'ZIP' || value === 'EPUB' || value === 'PDF' || value === 'AUDIO' || value === 'MP3' || value === 'M4A' || value === 'M4B' || value === 'MOBI' || value === 'AZW' || value === 'AZW3' || value === 'PRC' || value === 'FB2' || value === 'TXT' || value === 'IMAGE_DIR' || value === 'AUDIOBOOK_DIR' ? value : null;
}

function readerType(value: unknown, format: ResourceFormat): ReaderType {
  if (value === 'reflowable' || value === 'comic' || value === 'pdf' || value === 'audio') return value;
  if (format === 'PDF') return 'pdf';
  if (format === 'COMIC' || format === 'CBZ' || format === 'CBR' || format === 'RAR' || format === 'ZIP' || format === 'IMAGE_DIR') return 'comic';
  if (format === 'AUDIO' || format === 'MP3' || format === 'M4A' || format === 'M4B' || format === 'AUDIOBOOK_DIR') return 'audio';
  return 'reflowable';
}

export function mapReadableResourceView(value: unknown): ReadableResourceView | null {
  const item = record(value);
  const id = stringValue(item.id).trim();
  const bookId = stringValue(item.bookId).trim();
  const sourceNodeId = stringValue(item.sourceNodeId).trim();
  if (!id || !bookId || !sourceNodeId) return null;
  const format = resourceFormat(item.format);
  if (!format) throw new Error(`Unsupported resource format: ${stringValue(item.format)}`);
  const assets = (Array.isArray(item.assets) ? item.assets : []).flatMap((rawAsset) => {
    const asset = record(rawAsset);
    const assetId = stringValue(asset.id).trim();
    const assetResourceId = stringValue(asset.resourceId).trim();
    const assetSourceNodeId = stringValue(asset.sourceNodeId).trim();
    const role = stringValue(asset.role).trim();
    const url = stringValue(asset.url).trim();
    const downloadUrl = stringValue(asset.downloadUrl).trim();
    if (!assetId || assetResourceId !== id || !assetSourceNodeId || !role || !url || !downloadUrl) return [];
    return [{
      id: assetId,
      title: stringValue(asset.title, assetId),
      path: nullableString(asset.path) ?? undefined,
      resourceId: assetResourceId,
      sourceNodeId: assetSourceNodeId,
      role,
      mimeType: stringValue(asset.mimeType),
      sourceFormat: resourceFormat(asset.sourceFormat),
      sortOrder: finiteNumber(asset.sortOrder),
      sizeBytes: finiteNumber(asset.sizeBytes),
      size: stringValue(asset.size),
      mtimeMs: finiteNumber(asset.mtimeMs),
      durationMs: nullableNumber(asset.durationMs),
      codec: nullableString(asset.codec),
      bitrate: nullableNumber(asset.bitrate),
      sampleRate: nullableNumber(asset.sampleRate),
      channels: nullableNumber(asset.channels),
      discNumber: nullableNumber(asset.discNumber),
      trackNumber: nullableNumber(asset.trackNumber),
      url: withBasePath(url),
      downloadUrl: withBasePath(downloadUrl)
    }];
  });
  return {
    id,
    bookId,
    sourceNodeId,
    title: stringValue(item.title, id),
    description: stringValue(item.description),
    resourceIndex: nullableNumber(item.resourceIndex),
    sortOrder: finiteNumber(item.sortOrder),
    format,
    readerType: readerType(item.readerType, format),
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
    kindleSendAvailable: item.kindleSendAvailable === true,
    assets
  };
}

export type BookResourcePage = Readonly<{
  bookId: string;
  resources: ReadableResourceView[];
  page: number;
  pageSize: number;
  total: number;
  totalPages: number;
}>;

export function mapBookView(value: unknown): BookView {
  const root = record(value);
  const id = stringValue(root.id).trim();
  const sourceNodeId = stringValue(root.sourceNodeId).trim();
  if (!id || !sourceNodeId || !Array.isArray(root.resources)) throw new Error('图书响应缺少资源结构或来源节点身份');
  const resources = root.resources.map(mapReadableResourceView).filter((item): item is ReadableResourceView => item !== null);
  const publicationStatus = root.publicationStatus === 'ONGOING' || root.publicationStatus === 'COMPLETED' || root.publicationStatus === 'HIATUS' || root.publicationStatus === 'CANCELLED' ? root.publicationStatus : 'UNKNOWN';
  const trackingStatus = root.trackingStatus === 'TRACKING' || root.trackingStatus === 'PAUSED' || root.trackingStatus === 'IGNORED' ? root.trackingStatus : 'NOT_TRACKING';
  return {
    id,
    sourceNodeId,
    title: stringValue(root.title, '未命名图书'),
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
    continueResourceId: nullableString(root.continueResourceId),
    continueResourceTitle: nullableString(root.continueResourceTitle),
    continueResourceProgress: Math.max(0, Math.min(100, finiteNumber(root.continueResourceProgress))),
    continueReaderType: root.continueReaderType === 'audio' || root.continueReaderType === 'comic' || root.continueReaderType === 'pdf' || root.continueReaderType === 'reflowable' ? root.continueReaderType : null,
    completed: root.completed === true,
    resourceImportSummary: resourceImportSummary(root.resourceImportSummary),
    resources
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

export async function fetchBook(
  bookId: string,
  signal?: AbortSignal,
  resourceId?: string | null
): Promise<BookView> {
  const query = new URLSearchParams();
  if (resourceId) query.set('resourceId', resourceId);
  const suffix = query.size > 0 ? `?${query}` : '';
  const data = record(await apiJson(`/api/books/${encodeURIComponent(bookId)}${suffix}`, { signal }));
  return mapBookView(data.book ?? data);
}

/** Authoritative Library descriptor used by both details and local-original Reader delivery. */
export async function fetchLibraryResource(
  resourceId: string,
  signal?: AbortSignal
): Promise<ReadableResourceView> {
  const data = record(await apiJson(`/api/resources/${encodeURIComponent(resourceId)}`, { signal }));
  const resource = mapReadableResourceView(data.resource ?? data);
  if (!resource || resource.id !== resourceId) throw new Error('LIBRARY_RESOURCE_DESCRIPTOR_MISMATCH');
  return resource;
}

export async function fetchBookResources(
  bookId: string,
  page: number,
  pageSize: number,
  signal?: AbortSignal
): Promise<BookResourcePage> {
  const query = new URLSearchParams({ page: String(page), pageSize: String(pageSize) });
  const data = record(await apiJson(`/api/books/${encodeURIComponent(bookId)}/resources?${query}`, { signal }));
  if (stringValue(data.bookId) !== bookId) throw new Error('资源分页响应与请求不匹配');
  const resolvedPageSize = positiveInteger(data.pageSize, pageSize);
  const total = Math.max(0, finiteNumber(data.total));
  return {
    bookId,
    resources: (Array.isArray(data.resources) ? data.resources : []).map(mapReadableResourceView).filter((resource): resource is ReadableResourceView => resource !== null),
    page: positiveInteger(data.page, page),
    pageSize: resolvedPageSize,
    total,
    totalPages: positiveInteger(data.totalPages, Math.max(1, Math.ceil(total / resolvedPageSize)))
  };
}

export async function fetchAllBookResources(
  bookId: string,
  signal?: AbortSignal
): Promise<ReadableResourceView[]> {
  const firstPage = await fetchBookResources(bookId, 1, 100, signal);
  const resources = [...firstPage.resources];
  for (let page = 2; page <= firstPage.totalPages; page += 1) {
    const nextPage = await fetchBookResources(bookId, page, 100, signal);
    resources.push(...nextPage.resources);
  }
  return resources;
}

function mapBookContentEntry(value: unknown): BookContentEntry | null {
  const item = record(value);
  const sourceNodeId = stringValue(item.sourceNodeId).trim();
  const kind = item.kind === 'FOLDER' || item.kind === 'FILE' ? item.kind : null;
  const physicalKind = item.physicalKind === 'REGULAR_FILE' || item.physicalKind === 'DIRECTORY' || item.physicalKind === 'SYMLINK' || item.physicalKind === 'OTHER' ? item.physicalKind : null;
  if (!sourceNodeId || !kind || !physicalKind) return null;
  return {
    sourceNodeId,
    parentSourceNodeId: nullableString(item.parentSourceNodeId),
    name: stringValue(item.name, sourceNodeId),
    title: stringValue(item.title, stringValue(item.name, sourceNodeId)),
    description: nullableString(item.description),
    kind,
    physicalKind,
    sizeBytes: nullableNumber(item.sizeBytes),
    observedAt: stringValue(item.observedAt),
    hasChildren: item.hasChildren === true,
    resourceId: nullableString(item.resourceId),
    representativeResourceId: nullableString(item.representativeResourceId),
    coverUrl: nullableString(item.coverUrl)
  };
}

export async function fetchBookContents(
  bookId: string,
  sourceNodeId: string | null,
  sortOption: BookContentSort,
  page: number,
  signal?: AbortSignal
): Promise<BookContentsPage> {
  const sort = bookContentSortQuery(sortOption);
  const query = new URLSearchParams({
    sort: sort.sort,
    direction: sort.direction,
    page: String(page),
    pageSize: '100'
  });
  if (sourceNodeId) query.set('sourceNodeId', sourceNodeId);
  const data = await apiJson(`/api/books/${encodeURIComponent(bookId)}/contents?${query}`, { signal });
  return mapBookContentsPage(bookId, page, data);
}

export function mapBookContentsPage(bookId: string, page: number, value: unknown): BookContentsPage {
  const data = record(value);
  if (stringValue(data.bookId) !== bookId) throw new Error('图书目录响应与请求不匹配');
  const entries = (Array.isArray(data.entries) ? data.entries : []).map(mapBookContentEntry).filter((entry): entry is BookContentEntry => entry !== null);
  const breadcrumbs = (Array.isArray(data.breadcrumbs) ? data.breadcrumbs : []).map(mapBookContentEntry).filter((entry): entry is BookContentEntry => entry !== null);
  const currentNode = mapBookContentEntry(data.currentNode);
  return {
    bookId,
    currentSourceNodeId: nullableString(data.currentSourceNodeId),
    currentResourceId: nullableString(data.currentResourceId),
    currentNode,
    currentResourceIds: (Array.isArray(data.currentResourceIds) ? data.currentResourceIds : []).flatMap((value) => {
      const id = stringValue(value).trim();
      return id ? [id] : [];
    }),
    parentSourceNodeId: nullableString(data.parentSourceNodeId),
    breadcrumbs,
    entries,
    page: positiveInteger(data.page, page),
    pageSize: positiveInteger(data.pageSize, 100),
    total: Math.max(0, finiteNumber(data.total)),
    totalPages: positiveInteger(data.totalPages, 1)
  };
}

export async function updateSourceNodeMetadata(bookId: string, sourceNodeId: string, body: Readonly<{ title: string; description: string | null }>): Promise<void> {
  await apiJson(`/api/books/${encodeURIComponent(bookId)}/source-nodes/${encodeURIComponent(sourceNodeId)}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  });
}

export async function updateSourceNodePresentation(
  bookId: string,
  sourceNodeId: string,
  body: Readonly<{
    title: string;
    description: string | null;
    cover: File | null;
    removeCover: boolean;
  }>
): Promise<void> {
  const form = new FormData();
  form.set('title', body.title);
  if (body.description) form.set('description', body.description);
  form.set('removeCover', String(body.removeCover));
  if (body.cover) form.set('cover', body.cover);
  await apiJson(`/api/books/${encodeURIComponent(bookId)}/source-nodes/${encodeURIComponent(sourceNodeId)}`, {
    method: 'PUT',
    body: form
  });
}

export async function searchSourceNodeMetadata(bookId: string, sourceNodeId: string, providerId: string, query: string, signal?: AbortSignal): Promise<Readonly<{ message: string | null; candidates: SourceNodeMetadataCandidate[] }>> {
  const data = record(await apiJson(`/api/books/${encodeURIComponent(bookId)}/source-nodes/${encodeURIComponent(sourceNodeId)}/metadata/search`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ providerId, query }),
    signal
  }));
  const candidates = (Array.isArray(data.candidates) ? data.candidates : []).flatMap((value) => {
    const item = record(value);
    const id = stringValue(item.id).trim();
    if (!id) return [];
    return [{
      id,
      source: stringValue(item.source, providerId),
      title: nullableString(item.title),
      author: nullableString(item.author),
      description: nullableString(item.description),
      tags: Array.isArray(item.tags) ? item.tags.filter((tag): tag is string => typeof tag === 'string' && Boolean(tag.trim())) : [],
      seriesName: nullableString(item.seriesName),
      seriesIndex: nullableNumber(item.seriesIndex),
      publisher: nullableString(item.publisher),
      publishedAt: nullableString(item.publishedAt),
      language: nullableString(item.language),
      isbn: nullableString(item.isbn),
      identifier: nullableString(item.identifier),
      narrator: nullableString(item.narrator),
      abridged: typeof item.abridged === 'boolean' ? item.abridged : null,
      resourceIndex: nullableNumber(item.resourceIndex),
      coverUrl: nullableString(item.coverUrl),
      confidence: finiteNumber(item.confidence)
    } satisfies SourceNodeMetadataCandidate];
  });
  return { message: nullableString(data.message), candidates };
}

const recognizedMetadataFieldValues = new Set<RecognizedMetadataField>([
  'book.title', 'book.author', 'book.description', 'book.seriesName', 'book.seriesIndex', 'book.tags', 'book.cover',
  'resource.title', 'resource.description', 'resource.publisher', 'resource.publishedAt', 'resource.language',
  'resource.isbn', 'resource.identifier', 'resource.narrator', 'resource.abridged', 'resource.resourceIndex', 'resource.cover'
]);

export async function applyRecognizedMetadata(
  bookId: string,
  input: Readonly<{
    scope: MetadataTargetScope;
    resourceId: string | null;
    candidate: SourceNodeMetadataCandidate;
    fields: readonly RecognizedMetadataField[];
  }>,
  signal?: AbortSignal
): Promise<Readonly<{
  appliedFields: RecognizedMetadataField[];
  skippedFields: RecognizedMetadataField[];
  coverStatus: 'notSelected' | 'applied' | 'failed';
}>> {
  const data = record(await apiJson(`/api/books/${encodeURIComponent(bookId)}/metadata/apply`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
    signal
  }));
  const fields = (value: unknown): RecognizedMetadataField[] => (Array.isArray(value) ? value : []).filter(
    (field): field is RecognizedMetadataField => typeof field === 'string' && recognizedMetadataFieldValues.has(field as RecognizedMetadataField)
  );
  const coverStatus = data.coverStatus;
  if (coverStatus !== 'notSelected' && coverStatus !== 'applied' && coverStatus !== 'failed') {
    throw new Error('元数据应用响应格式不正确');
  }
  return {
    appliedFields: fields(data.appliedFields),
    skippedFields: fields(data.skippedFields),
    coverStatus
  };
}

export type MetadataProviderOption = Readonly<{
  id: string;
  name: string;
  enabled: boolean;
  priority: number;
  mode: string;
}>;

export async function fetchMetadataProviders(
  signal?: AbortSignal,
): Promise<Readonly<{ providers: MetadataProviderOption[] }>> {
  const data = record(await apiJson('/api/metadata/providers', { signal }));
  const providers = (Array.isArray(data.providers) ? data.providers : []).flatMap((value) => {
    const item = record(value);
    const id = stringValue(item.id).trim();
    const name = stringValue(item.name, id);
    if (!id) return [];
    return [{
      id,
      name,
      enabled: item.enabled === true,
      priority: finiteNumber(item.priority, Number.MAX_SAFE_INTEGER),
      mode: stringValue(item.mode)
    }];
  });
  providers.sort((left, right) => left.priority - right.priority || left.name.localeCompare(right.name));
  return { providers };
}

export async function updateMetadataProviderOrder(
  items: ReadonlyArray<Readonly<{ providerId: string; enabled: boolean }>>
): Promise<Readonly<{ providers: MetadataProviderOption[] }>> {
  const data = record(await apiJson('/api/metadata/provider-order', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ items })
  }));
  const providers = (Array.isArray(data.providers) ? data.providers : []).flatMap((value) => {
    const item = record(value);
    const id = stringValue(item.id).trim();
    if (!id) return [];
    return [{
      id,
      name: stringValue(item.name, id),
      enabled: item.enabled === true,
      priority: finiteNumber(item.priority, Number.MAX_SAFE_INTEGER),
      mode: stringValue(item.mode)
    }];
  });
  providers.sort((left, right) => left.priority - right.priority || left.name.localeCompare(right.name));
  return { providers };
}

function mapResourceDetailUnit(value: unknown): ResourceDetailUnit | null {
  const item = record(value);
  const id = stringValue(item.id).trim();
  const unitType = stringValue(item.unitType).trim();
  if (!id || (unitType !== 'chapter' && unitType !== 'page' && unitType !== 'track')) return null;
  const base = {
    id,
    title: nullableString(item.title) ?? '',
    sortOrder: finiteNumber(item.sortOrder),
    assetId: nullableString(item.assetId),
    mediaType: nullableString(item.mediaType)
  };
  if (unitType === 'chapter') {
    const level = nullableInteger(item.level);
    return { ...base, unitType, href: nullableString(item.href), level: level !== null && level >= 0 ? level : null } satisfies ResourceChapterDetailUnit;
  }
  if (unitType === 'page') {
    const pageNumber = nullableInteger(item.pageNumber);
    if (pageNumber === null || pageNumber < 1) return null;
    const previewUrl = nullableString(item.previewUrl);
    return { ...base, unitType, pageNumber, previewUrl: previewUrl ? withBasePath(previewUrl) : null } satisfies ResourcePageDetailUnit;
  }
  return {
    ...base,
    unitType,
    durationMs: nullableNumber(item.durationMs),
    discNumber: nullableInteger(item.discNumber),
    trackNumber: nullableInteger(item.trackNumber)
  } satisfies ResourceTrackDetailUnit;
}

export async function fetchResourceDetail(
  bookId: string,
  resourceId: string,
  page: number,
  pageSize: number,
  signal?: AbortSignal
): Promise<ResourceDetailPage> {
  const query = new URLSearchParams({ page: String(page), pageSize: String(pageSize) });
  const data = record(await apiJson(`/api/books/${encodeURIComponent(bookId)}/resources/${encodeURIComponent(resourceId)}/reading-units?${query}`, { signal }));
  if (stringValue(data.bookId) !== bookId || stringValue(data.resourceId) !== resourceId) throw new Error('资源详情响应与请求不匹配');
  const pageData = record(data.page);
  const pageSizeValue = positiveInteger(pageData.pageSize, pageSize);
  const total = Math.max(0, finiteNumber(pageData.total));
  return {
    units: (Array.isArray(data.units) ? data.units : []).map(mapResourceDetailUnit).filter((unit): unit is ResourceDetailUnit => unit !== null),
    page: {
      page: positiveInteger(pageData.page, page),
      pageSize: pageSizeValue,
      total,
      totalPages: positiveInteger(pageData.totalPages, Math.max(1, Math.ceil(total / pageSizeValue)))
    },
    currentHref: nullableString(data.currentHref),
    currentChapterIndex: nullableNumber(data.currentChapterIndex),
    currentChapterTitle: nullableString(data.currentChapterTitle),
    currentChapterSortOrder: nullableNumber(data.currentChapterSortOrder),
    currentPageNumber: nullableNumber(data.currentPageNumber),
    progress: Math.max(0, Math.min(100, finiteNumber(data.progress)))
  };
}

export async function updateResource(bookId: string, resourceId: string, body: Record<string, unknown>): Promise<void> {
  await apiJson(`/api/books/${encodeURIComponent(bookId)}/resources/${encodeURIComponent(resourceId)}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  });
}

type CoverRegenerationTargetType = 'RESOURCE' | 'SOURCE_NODE' | 'BOOK';

type CoverRegenerationSkipped = Readonly<{
  resourceId: string;
  reason: string;
}>;

type CoverRegenerationResult = Readonly<{
  targetType: CoverRegenerationTargetType;
  targetId: string;
  updatedResourceIds: ReadonlyArray<string>;
  skipped: ReadonlyArray<CoverRegenerationSkipped>;
  sourceNodeUpdated: boolean;
  bookUpdated: boolean;
}>;

function parseCoverRegenerationResult(
  value: unknown,
  expectedTargetType: CoverRegenerationTargetType,
  expectedTargetId: string
): CoverRegenerationResult {
  const data = record(value);
  const targetType = data.targetType;
  if (targetType !== 'RESOURCE' && targetType !== 'SOURCE_NODE' && targetType !== 'BOOK') {
    throw new Error('封面重生成响应格式不正确');
  }
  const targetId = stringValue(data.targetId).trim();
  if (!targetId || targetType !== expectedTargetType || targetId !== expectedTargetId) {
    throw new Error('封面重生成响应与请求不匹配');
  }
  if (!Array.isArray(data.updatedResourceIds) || !Array.isArray(data.skipped)
    || typeof data.sourceNodeUpdated !== 'boolean' || typeof data.bookUpdated !== 'boolean') {
    throw new Error('封面重生成响应格式不正确');
  }
  const updatedResourceIds = data.updatedResourceIds.flatMap((value) => {
    const resourceId = stringValue(value).trim();
    return resourceId ? [resourceId] : [];
  });
  const skipped = data.skipped.map((value) => {
    const item = record(value);
    const resourceId = stringValue(item.resourceId).trim();
    const reason = stringValue(item.reason).trim();
    if (!resourceId || !reason) throw new Error('封面重生成跳过项格式不正确');
    return { resourceId, reason } satisfies CoverRegenerationSkipped;
  });
  return {
    targetType,
    targetId,
    updatedResourceIds,
    skipped,
    sourceNodeUpdated: data.sourceNodeUpdated,
    bookUpdated: data.bookUpdated
  };
}

export async function regenerateResourceCover(bookId: string, resourceId: string): Promise<CoverRegenerationResult> {
  const data = await apiJson(`/api/books/${encodeURIComponent(bookId)}/resources/${encodeURIComponent(resourceId)}/cover/regenerate`, {
    method: 'POST'
  });
  return parseCoverRegenerationResult(data, 'RESOURCE', resourceId);
}

export async function regenerateSourceNodeCover(bookId: string, sourceNodeId: string): Promise<CoverRegenerationResult> {
  const data = await apiJson(`/api/books/${encodeURIComponent(bookId)}/source-nodes/${encodeURIComponent(sourceNodeId)}/cover/regenerate`, {
    method: 'POST'
  });
  return parseCoverRegenerationResult(data, 'SOURCE_NODE', sourceNodeId);
}

export async function uploadResourceCover(bookId: string, resourceId: string, cover: File): Promise<void> {
  const form = new FormData();
  form.set('cover', cover);
  await apiJson(`/api/books/${encodeURIComponent(bookId)}/resources/${encodeURIComponent(resourceId)}/cover`, {
    method: 'PUT',
    body: form
  });
}

export async function deleteResourceSource(bookId: string, resourceId: string, confirmation: string): Promise<void> {
  await apiJson(`/api/books/${encodeURIComponent(bookId)}/resources/${encodeURIComponent(resourceId)}/source`, {
    method: 'DELETE',
    headers: { 'Content-Type': 'application/json', 'Idempotency-Key': crypto.randomUUID() },
    body: JSON.stringify({ confirmation })
  });
}

export function assetDownloadUrl(assetId: string): string {
  return `/api/assets/${encodeURIComponent(assetId)}?download=true`;
}

export async function updateResourceReadingStatus(resourceId: string, status: 'UNREAD' | 'FINISHED'): Promise<void> {
  await apiJson(`/api/reader/v5/resources/${encodeURIComponent(resourceId)}/reading-status`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ status })
  });
}

export type BookMetadataInput = Readonly<{
  title: string;
  author: string;
  description: string;
  seriesName: string | null;
  seriesIndex: number | null;
}>;

export async function updateBookMetadata(bookId: string, input: BookMetadataInput): Promise<BookView> {
  const data = record(await apiJson(`/api/books/${encodeURIComponent(bookId)}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(input)
  }));
  return mapBookView(data.book ?? data);
}

export async function uploadBookCover(book: Pick<BookView, 'id' | 'sourceNodeId' | 'title' | 'description'>, file: File): Promise<void> {
  await updateSourceNodePresentation(book.id, book.sourceNodeId, {
    title: book.title,
    description: book.description || null,
    cover: file,
    removeCover: false
  });
}

export async function removeBookCover(book: Pick<BookView, 'id' | 'sourceNodeId' | 'title' | 'description'>): Promise<void> {
  await updateSourceNodePresentation(book.id, book.sourceNodeId, {
    title: book.title,
    description: book.description || null,
    cover: null,
    removeCover: true
  });
}

export async function replaceBookTags(bookId: string, currentTags: readonly string[], nextTags: readonly string[]): Promise<void> {
  const current = new Map(currentTags.map((tag) => [tag.trim().toLocaleLowerCase(), tag.trim()]));
  const next = new Map(nextTags.map((tag) => [tag.trim().toLocaleLowerCase(), tag.trim()]));
  const addTags = [...next].filter(([key]) => !current.has(key)).map(([, tag]) => tag);
  const removeTags = [...current].filter(([key]) => !next.has(key)).map(([, tag]) => tag);
  if (addTags.length === 0 && removeTags.length === 0) return;
  await apiJson('/api/library/operations/books/metadata', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ids: [bookId], fields: {}, addTags, removeTags })
  });
}

export async function regenerateBookImage(bookId: string): Promise<BulkBookCoverResult> {
  return updateBulkBookCovers({
    ids: [bookId],
    action: 'regenerate',
    ratio: '2:3',
    quality: 82,
    maxDimension: 1600
  });
}

export async function updateBookReadingStatus(bookId: string, status: 'UNREAD' | 'FINISHED'): Promise<void> {
  await apiJson('/api/library/operations/books/reading-status', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ids: [bookId], status })
  });
}

export async function deleteBookSources(bookId: string): Promise<void> {
  await apiJson('/api/library/operations/books/delete-sources', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ids: [bookId], confirmation: 'DELETE_SOURCE_FILES' })
  });
}
