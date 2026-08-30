import {
  READER_SAFETY_BUDGETS,
  READER_SAFETY_FORMATS,
  READER_SAFETY_PROFILES,
  READER_SAFETY_RULE_IDS,
  normalizeReaderPreferences,
  parseSupportedReaderSourceFormat,
  readerSafetyAcceptsMimeType,
  readerSafetyFormatPolicy,
  readerFormatCapability,
  type ReaderLocation,
  type ReaderOriginalResource,
  type ReaderSource,
  type ReflowableFormat,
  type SupportedReaderSourceFormat
} from '@shuku/reader-core';
import { readBoundedResponse, ResponseLimitError } from '../../../shared/api/bounded-response';
import { withBasePath } from '../../../lib/base-path';
import { fetchLibraryResource } from '../../books/public';
import { parseReaderV4ProgressSnapshot, v4LocationToDomain, type ReaderProgressSnapshot } from '../../../lib/reader';
import type { ReaderBookmark } from './bookmarks';
import {
  readerSafetyFailure,
  rejectReaderSafety,
  type ReaderSafetyFailure
} from './security/reader-safety-policy';

type VisualReaderType = 'reflowable' | 'comic' | 'pdf';

export type ReaderResource = Readonly<{
  id: string;
  bookId: string;
  title: string;
  resourceIndex: number | null;
  sortOrder: number;
  format: string;
  readerType: VisualReaderType | 'audio';
  pageCount: number | null;
  chapterCount: number | null;
  durationMs: number | null;
  trackCount: number | null;
  progress: number;
  resourceCompleted: boolean;
  lastReadAt: string | null;
}>;

export type ReaderUnit = Readonly<{
  id: string;
  index: number;
  title: string;
  href: string | null;
  assetId: string | null;
  startMs: number | null;
  endMs: number | null;
  durationMs: number | null;
  metadata: Record<string, unknown>;
}>;

export type ReaderPage = Readonly<{
  pageIndex: number;
  resourceHref: string;
  title: string | null;
  mimeType: string | null;
  width: number | null;
  height: number | null;
  size: number | null;
  safetyError?: ReaderSafetyFailure;
}>;

export type ReaderBootstrap = Readonly<{
  schemaVersion: 4;
  userId: string;
  readerType: VisualReaderType;
  sourceFormat: SupportedReaderSourceFormat;
  book: Readonly<{ id: string; title: string; author: string | null; coverUrl: string | null }>;
  resource: ReaderResource;
  resourceCompleted: boolean;
  availableResources: ReaderResource[];
  assets: ReadonlyArray<Readonly<{ id: string; kind: string; mimeType: string; sizeBytes: number; durationMs: number | null; discNumber: number | null; trackNumber: number | null; sortOrder: number; url: string }>>;
  units: ReaderUnit[];
  pages: ReaderPage[];
  comicRevision: string | null;
  capabilities: import('@shuku/reader-core').ReaderCapabilities;
  progressPercent: number;
  serverProgressSnapshot: ReaderProgressSnapshot | null;
  source: ReaderSource;
  initialLocation: ReaderLocation | null;
  serverPreferences: Readonly<{ settings: import('@shuku/reader-core').ReaderPreferences; updatedAt: string | null }>;
}>;

export class ReaderBootstrapError extends Error {
  constructor(readonly code: string, message: string) {
    super(message);
    this.name = 'ReaderBootstrapError';
  }
}

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

function visualReaderType(value: unknown): VisualReaderType | null {
  return value === 'reflowable' || value === 'comic' || value === 'pdf' ? value : null;
}

function mapResource(value: unknown): ReaderResource | null {
  const item = record(value);
  const id = stringValue(item.id).trim();
  const bookId = stringValue(item.bookId).trim();
  const readerType = item.readerType === 'audio' ? 'audio' : visualReaderType(item.readerType);
  if (!id || !bookId || !readerType) return null;
  return {
    id,
    bookId,
    title: stringValue(item.title, id),
    resourceIndex: nullableNumber(item.resourceIndex),
    sortOrder: numberValue(item.sortOrder),
    format: stringValue(item.format),
    readerType,
    pageCount: nullableNumber(item.pageCount),
    chapterCount: nullableNumber(item.chapterCount),
    durationMs: nullableNumber(item.durationMs),
    trackCount: nullableNumber(item.trackCount),
    progress: Math.max(0, Math.min(100, numberValue(item.progress))),
    resourceCompleted: item.resourceCompleted === true,
    lastReadAt: nullableString(item.lastReadAt)
  };
}

function mapUnits(value: unknown): ReaderUnit[] {
  const units = (Array.isArray(value) ? value : []).map((raw) => {
    const item = record(raw);
    const id = stringValue(item.id).trim();
    const index = numberValue(item.index, -1);
    if (!id || !Number.isInteger(index) || index < 0) {
      throw new ReaderBootstrapError('READER_BOOTSTRAP_INVALID', 'Reader navigation unit is invalid');
    }
    return { id, index, title: stringValue(item.title).trim() || id, href: nullableString(item.href), assetId: nullableString(item.assetId), startMs: nullableNumber(item.startMs), endMs: nullableNumber(item.endMs), durationMs: nullableNumber(item.durationMs), metadata: record(item.metadata) };
  });
  units.sort((left, right) => left.index - right.index);
  if (new Set(units.map((unit) => unit.id)).size !== units.length
    || new Set(units.map((unit) => unit.index)).size !== units.length) {
    throw new ReaderBootstrapError('READER_BOOTSTRAP_INVALID', 'Reader navigation units must be unique');
  }
  return units;
}

function assetVersion(sizeBytes: number, mtimeMs: number): ReaderOriginalResource['assetVersion'] {
  return `${sizeBytes}:${mtimeMs}`;
}

async function originalResourceDescriptor(
  resourceId: string,
  format: ReflowableFormat,
  signal: AbortSignal
): Promise<ReaderOriginalResource> {
  const descriptor = await fetchLibraryResource(resourceId, signal);
  if (descriptor.readerType !== 'reflowable' || descriptor.format.toLowerCase() !== format) {
    throw new ReaderBootstrapError('ORIGINAL_DESCRIPTOR_FORMAT_MISMATCH', 'ORIGINAL_DESCRIPTOR_FORMAT_MISMATCH');
  }
  const exactFormat = format.toUpperCase();
  const asset = descriptor.assets.find((candidate) => (
    candidate.role === 'PRIMARY'
    && candidate.resourceId === resourceId
    && candidate.sourceFormat === exactFormat
  ));
  if (!asset || asset.sizeBytes < 0 || asset.mtimeMs < 0 || !asset.mimeType || !asset.downloadUrl) {
    throw new ReaderBootstrapError('ORIGINAL_DESCRIPTOR_INVALID', 'ORIGINAL_DESCRIPTOR_INVALID');
  }
  return {
    resourceId,
    assetId: asset.id,
    assetVersion: assetVersion(asset.sizeBytes, asset.mtimeMs),
    sourceFormat: format,
    mimeType: asset.mimeType,
    sizeBytes: asset.sizeBytes,
    mtimeMs: asset.mtimeMs,
    downloadUrl: asset.downloadUrl
  };
}

async function fetchComicManifest(
  manifestUrl: string,
  resourceId: string,
  sourceFormat: SupportedReaderSourceFormat,
  signal: AbortSignal
): Promise<Readonly<{ revision: string; pages: ReaderPage[] }>> {
  const response = await fetch(withBasePath(manifestUrl), { credentials: 'same-origin', cache: 'no-cache', signal });
  let bytes: Uint8Array<ArrayBuffer>;
  try {
    bytes = await readBoundedResponse(response, READER_SAFETY_BUDGETS.comicManifestMaxBytes);
  } catch (reason) {
    if (reason instanceof ResponseLimitError && reason.code === 'RESPONSE_TOO_LARGE') {
      rejectReaderSafety(READER_SAFETY_RULE_IDS.COMIC_MANIFEST_MAX_BYTES, { cause: reason });
    }
    throw reason;
  }
  const payload: unknown = (() => {
    try { return JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(bytes)); }
    catch { return null; }
  })();
  const envelope = record(payload);
  const manifest = record(envelope.data);
  const readingOrder = Array.isArray(manifest.readingOrder) ? manifest.readingOrder : [];
  const revision = stringValue(manifest.revision);
  if (!/^sha256:[a-f0-9]{64}$/.test(revision)) {
    rejectReaderSafety(READER_SAFETY_RULE_IDS.COMIC_MANIFEST_REVISION);
  }
  if (!response.ok || envelope.ok !== true
    || manifest.schemaVersion !== 2
    || manifest.kind !== 'comic'
    || manifest.resourceId !== resourceId
    || manifest.sourceFormat !== sourceFormat
    || numberValue(manifest.pageCount, -1) !== readingOrder.length
    || readingOrder.length === 0) {
    throw new ReaderBootstrapError('READER_COMIC_MANIFEST_INVALID', '漫画页面清单无效');
  }
  if (readingOrder.length > READER_SAFETY_BUDGETS.comicPageMaxCount) {
    rejectReaderSafety(READER_SAFETY_RULE_IDS.COMIC_PAGE_MAX_COUNT);
  }
  const allowedPageMimeTypes = new Set<string>(READER_SAFETY_PROFILES.comic.allowedPageMimeTypes);
  const pages = readingOrder.map((raw, index) => {
    const page = record(raw);
    const resourceHref = stringValue(page.resourceHref);
    const mimeType = nullableString(page.mediaType)?.toLowerCase() ?? null;
    const size = nullableNumber(page.sizeBytes);
    if (page.pageIndex !== index || resourceHref !== `pages/${index}`) {
      throw new ReaderBootstrapError('READER_COMIC_INDEX_INVALID', '漫画页面顺序无效');
    }
    if (size === null || !Number.isSafeInteger(size) || size < 0) {
      throw new ReaderBootstrapError('READER_COMIC_MANIFEST_INVALID', '漫画页面清单包含无效的页面大小');
    }
    const safetyError = !mimeType || !allowedPageMimeTypes.has(mimeType)
      ? readerSafetyFailure(READER_SAFETY_RULE_IDS.COMIC_PAGE_MIME)
      : size > READER_SAFETY_BUDGETS.comicPageMaxBytes
        ? readerSafetyFailure(READER_SAFETY_RULE_IDS.COMIC_PAGE_MAX_BYTES)
        : undefined;
    return {
      pageIndex: index,
      resourceHref,
      title: nullableString(page.title),
      mimeType,
      width: nullableNumber(page.width),
      height: nullableNumber(page.height),
      size,
      ...(safetyError ? { safetyError } : {})
    };
  });
  return { revision, pages };
}

export async function fetchReaderBootstrap(resourceId: string, signal: AbortSignal): Promise<ReaderBootstrap> {
  const response = await fetch(`/api/reader/v4/resources/${encodeURIComponent(resourceId)}/bootstrap`, { credentials: 'same-origin', cache: 'no-store', signal });
  const payload: unknown = await response.json().catch(() => null);
  const envelope = record(payload);
  if (!response.ok || envelope.ok !== true) {
    const error = record(envelope.error);
    const code = stringValue(error.code, `READER_BOOTSTRAP_HTTP_${response.status}`);
    throw new ReaderBootstrapError(
      code,
      stringValue(error.message) || stringValue(envelope.detail) || `读取阅读器启动信息失败（${response.status}）`
    );
  }
  const data = record(envelope.data);
  if (data.schemaVersion !== 4) throw new Error('当前客户端不支持该阅读协议');
  const readerType = visualReaderType(data.readerType);
  const resource = mapResource(data.resource);
  const book = record(data.book);
  const bookId = stringValue(book.id).trim();
  if (!readerType || !resource || !bookId) throw new Error('阅读器启动信息不完整');
  const format = parseSupportedReaderSourceFormat(data.sourceFormat);
  if (!format) throw new ReaderBootstrapError('RESOURCE_FORMAT_UNSUPPORTED', '当前文件格式不受阅读器支持');
  if (readerFormatCapability(format).readerKind !== readerType) {
    throw new ReaderBootstrapError('READER_FORMAT_MORPHOLOGY_MISMATCH', '阅读器格式与排版形态不匹配');
  }
  const units = mapUnits(data.units);
  const publicationAccess = record(data.publication);
  const assets = (Array.isArray(data.assets) ? data.assets : []).flatMap((raw) => {
    const asset = record(raw);
    const id = stringValue(asset.id).trim();
    if (!id) return [];
    return [{ id, kind: stringValue(asset.kind), mimeType: stringValue(asset.mimeType), sizeBytes: numberValue(asset.sizeBytes), durationMs: nullableNumber(asset.durationMs), discNumber: nullableNumber(asset.discNumber), trackNumber: nullableNumber(asset.trackNumber), sortOrder: numberValue(asset.sortOrder), url: withBasePath(stringValue(asset.url, `/api/assets/${encodeURIComponent(id)}`)) }];
  });
  if (readerType === 'pdf') {
    const pdfAsset = assets.find((asset) => readerSafetyAcceptsMimeType(READER_SAFETY_FORMATS.PDF, asset.mimeType));
    if (!pdfAsset || pdfAsset.sizeBytes <= 0) {
      throw new ReaderBootstrapError('PDF_INVALID', 'PDF 阅读信息缺少准确大小');
    }
  }
  const sourceFormatPolicy = readerSafetyFormatPolicy(format);
  const contentAsset = readerType === 'pdf'
    ? assets.find((asset) => readerSafetyAcceptsMimeType(READER_SAFETY_FORMATS.PDF, asset.mimeType))
    : readerType === 'comic'
      ? assets.find((asset) => sourceFormatPolicy !== null
        && readerSafetyAcceptsMimeType(sourceFormatPolicy, asset.mimeType))
      : null;
  if (readerType !== 'reflowable' && assets.length > 0 && !contentAsset) {
    rejectReaderSafety(READER_SAFETY_RULE_IDS.COMMON_EXACT_FORMAT_MIME);
  }
  if (readerType !== 'reflowable' && (!contentAsset || !contentAsset.url)) {
    throw new Error('阅读器启动信息缺少内容资产');
  }
  if (contentAsset && readerType !== 'reflowable') {
    if (!Number.isSafeInteger(contentAsset.sizeBytes) || contentAsset.sizeBytes <= 0) {
      throw new ReaderBootstrapError('READER_BOOTSTRAP_INVALID', '阅读资产大小无效');
    }
    if (contentAsset.sizeBytes > READER_SAFETY_BUDGETS.originalMaxBytes) {
      rejectReaderSafety(READER_SAFETY_RULE_IDS.COMMON_ORIGINAL_MAX_BYTES);
    }
    if (!sourceFormatPolicy || !readerSafetyAcceptsMimeType(sourceFormatPolicy, contentAsset.mimeType)) {
      rejectReaderSafety(READER_SAFETY_RULE_IDS.COMMON_EXACT_FORMAT_MIME);
    }
  }
  const capabilities = record(data.capabilities);
  const comicManifestUrl = readerType === 'comic' ? nullableString(publicationAccess.manifestUrl) : null;
  const comicPageUrlTemplate = readerType === 'comic' ? nullableString(publicationAccess.pageUrlTemplate) : null;
  const expectedComicManifestUrl = `/api/reader/v4/resources/${encodeURIComponent(resource.id)}/comic/manifest`;
  const expectedComicPageTemplate = `/api/reader/v4/resources/${encodeURIComponent(resource.id)}/comic/pages/{pageIndex}`;
  if (readerType === 'comic' && (
    publicationAccess.kind !== 'comic'
    || comicManifestUrl !== expectedComicManifestUrl
    || comicPageUrlTemplate !== expectedComicPageTemplate
    || !Array.isArray(publicationAccess.imageVariants)
    || publicationAccess.imageVariants.join(',') !== 'original,data-saver'
  )) {
    throw new ReaderBootstrapError('READER_COMIC_PROTOCOL_INVALID', '漫画流式阅读协议无效');
  }
  const comicManifest = readerType === 'comic'
    ? await fetchComicManifest(comicManifestUrl ?? '', resource.id, format, signal)
    : null;
  const pages = (comicManifest?.pages ?? []).map((page) => ({
    ...page,
    title: page.title
      ?? units.find((unit) => unit.metadata.pageIndex === page.pageIndex)?.title
      ?? String(page.pageIndex + 1)
  }));
  const serverProgressSnapshot = data.progressSnapshot === null || data.progressSnapshot === undefined
    ? null
    : parseReaderV4ProgressSnapshot(data.progressSnapshot);
  if (data.progressSnapshot !== null && data.progressSnapshot !== undefined && !serverProgressSnapshot) {
    throw new Error('阅读器启动信息包含无效的 Reader v4 进度快照');
  }
  let source: ReaderSource;
  if (readerType === 'reflowable') {
    const originalResource = await originalResourceDescriptor(resource.id, format as ReflowableFormat, signal);
    source = {
      bookId,
      resourceId: resource.id,
      kind: 'reflowable',
      sourceFormat: format as ReflowableFormat,
      originalResource,
      navigation: [],
      totalPages: resource.pageCount
    };
  } else if (readerType === 'comic') {
    source = {
      bookId,
      resourceId: resource.id,
      kind: 'comic',
      sourceFormat: format as 'cbz' | 'zip' | 'cbr' | 'rar' | 'image_dir',
      contentUrl: contentAsset?.url ?? '',
      comicManifestUrl: withBasePath(comicManifestUrl ?? ''),
      comicPageUrlTemplate: withBasePath(comicPageUrlTemplate ?? ''),
      totalPages: pages.length
    };
  } else {
    source = {
      bookId,
      resourceId: resource.id,
      kind: 'pdf',
      contentUrl: contentAsset?.url ?? '',
      totalPages: resource.pageCount
    };
  }
  return {
    schemaVersion: 4,
    userId: stringValue(data.userId),
    readerType,
    sourceFormat: format,
    book: { id: stringValue(book.id, bookId), title: stringValue(book.title, '未命名图书'), author: nullableString(book.author), coverUrl: nullableString(book.coverUrl) },
    resource,
    resourceCompleted: resource.resourceCompleted,
    availableResources: (Array.isArray(data.availableResources) ? data.availableResources : []).map(mapResource).filter((item): item is ReaderResource => item !== null),
    assets,
    units,
    pages,
    comicRevision: comicManifest?.revision ?? null,
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
    progressPercent: serverProgressSnapshot?.displayPercent ?? 0,
    serverProgressSnapshot,
    source,
    initialLocation: v4LocationToDomain(
      serverProgressSnapshot?.locator ?? null,
      resource.id,
      readerType === 'reflowable' ? format as ReflowableFormat : null
    ),
    serverPreferences: { settings: normalizeReaderPreferences({}), updatedAt: null }
  };
}

export function readerBookmarkFromWire(
  value: unknown,
  resourceId: string,
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

export async function fetchReaderBookmarks(resourceId: string, format: ReflowableFormat | null, signal?: AbortSignal): Promise<ReaderBookmark[]> {
  const response = await fetch(`/api/reader/v4/resources/${encodeURIComponent(resourceId)}/bookmarks`, { credentials: 'same-origin', cache: 'no-store', signal });
  const payload: unknown = await response.json().catch(() => null);
  const root = record(payload);
  const data = record(root.data);
  if (!response.ok || root.ok !== true || !Array.isArray(data.bookmarks)) throw new Error(stringValue(record(root.error).message, '读取书签失败'));
  return data.bookmarks.map((item) => readerBookmarkFromWire(item, resourceId, format)).filter((item): item is ReaderBookmark => item !== null);
}

export async function saveReaderBookmarks(resourceId: string, format: ReflowableFormat | null, bookmarks: ReaderBookmark[]): Promise<ReaderBookmark[]> {
  const wireBookmarks = bookmarks.map(readerBookmarkToWire);
  const response = await fetch(`/api/reader/v4/resources/${encodeURIComponent(resourceId)}/bookmarks`, { method: 'PUT', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ bookmarks: wireBookmarks }) });
  const payload: unknown = await response.json().catch(() => null);
  const root = record(payload);
  const data = record(root.data);
  if (!response.ok || root.ok !== true || !Array.isArray(data.bookmarks)) throw new Error(stringValue(record(root.error).message, '保存书签失败'));
  return data.bookmarks.map((item) => readerBookmarkFromWire(item, resourceId, format)).filter((item): item is ReaderBookmark => item !== null);
}
