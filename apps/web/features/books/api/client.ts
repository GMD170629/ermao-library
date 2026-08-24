import type { ClassificationSource, MediaKind, ReaderType, ReadableResourceView, ResourceFormat, ResourceImportSummary, BookView } from '../../../types/book';
import { withBasePath } from '../../../lib/base-path';
import type {
  ResourceChapterDetailUnit,
  ResourceDetailPage,
  ResourceDetailUnit,
  ResourcePageDetailUnit,
  ResourceTrackDetailUnit
} from '../model/resource-detail';
import type { BookContentEntry, BookContentsPage, BookContentSort, SourceNodeMetadataCandidate } from '../model/book-contents';
import { bookContentSortQuery } from '../model/book-contents';

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

function mediaKind(value: unknown): MediaKind | null {
  return value === 'EBOOK' || value === 'COMIC' || value === 'AUDIOBOOK' ? value : null;
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

function classificationSource(value: unknown): ClassificationSource {
  return value === 'AUTO' || value === 'LIBRARY_RULE' || value === 'USER' ? value : 'AUTO';
}

function mapResource(value: unknown): ReadableResourceView | null {
  const item = record(value);
  const id = stringValue(item.id).trim();
  const bookId = stringValue(item.bookId).trim();
  const sourceNodeId = stringValue(item.sourceNodeId).trim();
  const format = resourceFormat(item.format);
  if (!id || !bookId || !sourceNodeId || !format) return null;
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
      resourceId: assetResourceId,
      sourceNodeId: assetSourceNodeId,
      role,
      mimeType: stringValue(asset.mimeType),
      sortOrder: finiteNumber(asset.sortOrder),
      sizeBytes: finiteNumber(asset.sizeBytes),
      size: stringValue(asset.size),
      durationMs: nullableNumber(asset.durationMs),
      codec: nullableString(asset.codec),
      bitrate: nullableNumber(asset.bitrate),
      sampleRate: nullableNumber(asset.sampleRate),
      channels: nullableNumber(asset.channels),
      discNumber: nullableNumber(asset.discNumber),
      trackNumber: nullableNumber(asset.trackNumber),
      url,
      downloadUrl
    }];
  });
  const classification = record(item.classification);
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
    classification: {
      source: classificationSource(classification.source),
      reason: stringValue(classification.reason, 'FORMAT_DEFAULT'),
      suggestedMediaKind: mediaKind(classification.suggestedMediaKind)
    },
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
  const resources = root.resources.map(mapResource).filter((item): item is ReadableResourceView => item !== null);
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
    resources: (Array.isArray(data.resources) ? data.resources : []).map(mapResource).filter((resource): resource is ReadableResourceView => resource !== null),
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

export async function continueSourceNode(sourceNodeId: string): Promise<void> {
  await apiJson(`/api/source-nodes/${encodeURIComponent(sourceNodeId)}/continue`, { method: 'POST' });
}

export async function searchSourceNodeMetadata(bookId: string, sourceNodeId: string, providerId: string, query: string): Promise<Readonly<{ message: string | null; candidates: SourceNodeMetadataCandidate[] }>> {
  const data = record(await apiJson(`/api/books/${encodeURIComponent(bookId)}/source-nodes/${encodeURIComponent(sourceNodeId)}/metadata/search`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ providerId, query })
  }));
  const candidates = (Array.isArray(data.candidates) ? data.candidates : []).flatMap((value) => {
    const item = record(value);
    const id = stringValue(item.id).trim();
    if (!id) return [];
    return [{
      id,
      source: stringValue(item.source, providerId),
      title: nullableString(item.title),
      description: nullableString(item.description),
      coverUrl: nullableString(item.coverUrl),
      confidence: finiteNumber(item.confidence)
    } satisfies SourceNodeMetadataCandidate];
  });
  return { message: nullableString(data.message), candidates };
}

export type MetadataProviderOption = Readonly<{
  id: string;
  name: string;
  enabled: boolean;
  mediaKinds: string[];
  mode: string;
}>;

export type MetadataProviderPipeline = Readonly<{
  mediaKind: string;
  providers: ReadonlyArray<Readonly<{ providerId: string; enabled: boolean }>>;
}>;

export async function fetchMetadataProviders(
  signal?: AbortSignal,
): Promise<Readonly<{ providers: MetadataProviderOption[]; pipelines: MetadataProviderPipeline[] }>> {
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
      mediaKinds: Array.isArray(item.mediaKinds)
        ? item.mediaKinds.filter((kind): kind is string => typeof kind === 'string')
        : [],
      mode: stringValue(item.mode)
    }];
  });
  const pipelines = (Array.isArray(data.pipelines) ? data.pipelines : []).flatMap((value) => {
    const item = record(value);
    const mediaKind = stringValue(item.mediaKind).trim();
    if (!mediaKind) return [];
    const pipelineProviders = (Array.isArray(item.providers) ? item.providers : []).flatMap((providerValue) => {
      const provider = record(providerValue);
      const providerId = stringValue(provider.providerId).trim();
      return providerId ? [{ providerId, enabled: provider.enabled === true }] : [];
    });
    return [{ mediaKind, providers: pipelineProviders }];
  });
  return { providers, pipelines };
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

async function runResourceAction(bookId: string, resourceId: string, action: 'cover/regenerate'): Promise<void> {
  await apiJson(`/api/books/${encodeURIComponent(bookId)}/resources/${encodeURIComponent(resourceId)}/${action}`, {
    method: 'POST'
  });
}

export async function regenerateResourceCover(bookId: string, resourceId: string): Promise<void> {
  await runResourceAction(bookId, resourceId, 'cover/regenerate');
}

export async function deleteResourceSource(bookId: string, resourceId: string, confirmation: string): Promise<void> {
  await apiJson(`/api/books/${encodeURIComponent(bookId)}/resources/${encodeURIComponent(resourceId)}/source`, {
    method: 'DELETE',
    headers: { 'Content-Type': 'application/json', 'Idempotency-Key': crypto.randomUUID() },
    body: JSON.stringify({ confirmation })
  });
}

export async function reclassifyResource(
  bookId: string,
  resourceId: string,
  targetMediaKind: MediaKind,
  applyTo: 'RESOURCE' | 'SAME_MEDIA_KIND'
): Promise<string | null> {
  const data = record(await apiJson(`/api/books/${encodeURIComponent(bookId)}/resources/${encodeURIComponent(resourceId)}/reclassify`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ targetMediaKind, applyTo })
  }));
  return nullableString(record(data.operation).id);
}

export async function undoLibraryOperation(operationId: string): Promise<void> {
  await apiJson(`/api/library/operations/${encodeURIComponent(operationId)}/undo`, { method: 'POST' });
}

export type ResourceBatchRequest = Readonly<{
  action: 'SET_MEDIA_KIND';
  resourceIds: string[];
  targetMediaKind: MediaKind;
}>;

export type ResourceBatchResult = Readonly<{
  affectedResourceIds: string[];
  operationIds: string[];
}>;

export async function runResourceBatchAction(bookId: string, request: ResourceBatchRequest): Promise<ResourceBatchResult> {
  const data = record(await apiJson(`/api/books/${encodeURIComponent(bookId)}/resources/batch`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request)
  }));
  return {
    affectedResourceIds: Array.isArray(data.affectedResourceIds) ? data.affectedResourceIds.filter((value): value is string => typeof value === 'string') : [],
    operationIds: Array.isArray(data.operationIds) ? data.operationIds.filter((value): value is string => typeof value === 'string') : []
  };
}

export function assetDownloadUrl(assetId: string): string {
  return `/api/assets/${encodeURIComponent(assetId)}?download=true`;
}

export async function updateResourceReadingStatus(resourceId: string, status: 'UNREAD' | 'FINISHED'): Promise<void> {
  await apiJson(`/api/reader/v4/resources/${encodeURIComponent(resourceId)}/reading-status`, {
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

export async function regenerateBookCover(bookId: string, anchoredResourceId: string): Promise<void> {
  await regenerateResourceCover(bookId, anchoredResourceId);
}
