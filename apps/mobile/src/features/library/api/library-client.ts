import type {
  ApiRequest,
  ApiTransport,
  ApiTransportResult,
} from '../../../shared/api/public';
import {
  serverApiUrl,
  type CancellationToken,
  type ServerBaseUrl,
} from '../../server-connection/public';
import type {
  BooksPage,
  HomeLoadResult,
  LibraryGateway,
  LibraryImportFile,
  LibraryResult,
} from '../application/ports';
import type {
  BooksQuery,
  CollectionDetail,
  HomeSection,
  ImportSuccess,
  ImportTargets,
  LibraryCover,
  LibraryFailure,
  LibraryPreferences,
  ShelfOverviewData,
  ShelfSummary,
} from '../model/library';
import {
  decodeBooksPage,
  decodeCollectionDetail,
  decodeContinueReading,
  decodeDashboardSummary,
  decodeDeletedShelf,
  decodeImportSuccess,
  decodeImportTargets,
  decodeLibraryErrorCode,
  decodePreferences,
  decodeRecentBooks,
  decodeShelf,
  decodeShelves,
  decodeUnreadTotal,
} from './library-schema';

const JSON_TIMEOUT_MS = 15_000;
const IMPORT_TIMEOUT_MS = 120_000;
const JSON_MAXIMUM_RESPONSE_BYTES = 512 * 1024;
const COVER_MAXIMUM_RESPONSE_BYTES = 8 * 1024 * 1024;
const COVER_MEMORY_CACHE_BUDGET_BYTES = 32 * 1024 * 1024;
const PAGE_SIZE = 24;
const COVER_CONTENT_TYPES = new Set([
  'image/jpeg', 'image/png', 'image/webp',
]);

type Operation = LibraryFailure['operation'];
type JsonSuccess = Extract<
  ApiTransportResult,
  Readonly<{ ok: true; responseType: 'json' }>
>;
type InvalidDecodedValue = Readonly<{ ok: false; reason: string }>;

function invalidDecodedValue(reason: string): InvalidDecodedValue {
  return { ok: false, reason };
}

function failure(
  operation: Operation,
  reason: LibraryFailure['reason'],
  details?: Readonly<{ status?: number; code?: string }>,
): LibraryFailure {
  return {
    operation,
    reason,
    ...(details?.status === undefined ? {} : { status: details.status }),
    ...(details?.code === undefined ? {} : { code: details.code }),
  };
}

function transportFailure(
  operation: Operation,
  result: Exclude<ApiTransportResult, Readonly<{ ok: true }>>,
): LibraryFailure {
  switch (result.reason) {
    case 'aborted':
    case 'network':
    case 'timeout':
      return failure(operation, result.reason === 'aborted' ? 'cancelled' : result.reason);
    case 'response-too-large':
      return failure(operation, 'response-too-large', { status: result.status });
    case 'invalid-json':
      return failure(operation, 'incompatible-response', { status: result.status });
  }
}

function statusFailure(operation: Operation, response: JsonSuccess): LibraryFailure {
  const code = decodeLibraryErrorCode(response.body);
  const details = {
    status: response.status,
    ...(code === undefined ? {} : { code }),
  };
  if (response.status === 401) return failure(operation, 'session-expired', details);
  if (response.status === 403) return failure(operation, 'forbidden', details);
  if (response.status === 404) return failure(operation, 'not-found', details);
  if (response.status === 400 || response.status === 409 || response.status === 422) {
    return failure(operation, 'invalid-request', details);
  }
  return failure(operation, 'unknown', details);
}

function queryUrl(baseUrl: ServerBaseUrl, query: BooksQuery, page: number): string {
  const parameters = new URLSearchParams({
    page: String(page),
    pageSize: String(PAGE_SIZE),
    view: 'bookshelf',
    sort: query.sort,
    sortDirection: query.direction,
  });
  if (query.search.length > 0) parameters.set('search', query.search);
  if (query.status !== null) parameters.set('status', query.status);
  if (query.mediaKind !== null) parameters.set('mediaKind', query.mediaKind);
  if (query.shelfId !== null) {
    parameters.set('filters', JSON.stringify({
      combinator: 'ALL',
      conditions: [
        { field: 'shelf', operator: 'equals', value: query.shelfId },
      ],
    }));
  }
  return `${serverApiUrl(baseUrl, '/api/works')}?${parameters.toString()}`;
}

function resolvedCoverUrl(
  baseUrl: ServerBaseUrl,
  coverUrl: string,
): string | null {
  const normalized = coverUrl.trim();
  if (isApiPath(normalized)) {
    return serverApiUrl(baseUrl, normalized);
  }
  let candidate: URL;
  let server: URL;
  try {
    candidate = new URL(normalized);
    server = new URL(`${baseUrl.value}/`);
  } catch {
    return null;
  }
  const serverPath = server.pathname.replace(/\/+$/, '');
  if (
    candidate.protocol !== server.protocol || candidate.host !== server.host ||
    candidate.username.length > 0 || candidate.password.length > 0 ||
    candidate.hash.length > 0 ||
    !candidate.pathname.startsWith(`${serverPath}/api/`)
  ) {
    return null;
  }
  return candidate.toString();
}

function isApiPath(value: string): value is `/api/${string}` {
  return value.startsWith('/api/') && !value.includes('#');
}

export class LibraryClient implements LibraryGateway {
  private readonly coverCache = new Map<string, LibraryCover>();
  private coverCacheBytes = 0;

  constructor(private readonly transport: ApiTransport) {}

  async loadHome(
    baseUrl: ServerBaseUrl,
    cancellation: CancellationToken,
  ): Promise<HomeLoadResult> {
    const requests = await Promise.all([
      this.get(baseUrl, '/api/dashboard/summary', 'load-home', cancellation),
      this.get(
        baseUrl,
        '/api/works?page=1&pageSize=1&view=management&status=UNREAD',
        'load-home',
        cancellation,
      ),
      this.get(
        baseUrl,
        '/api/dashboard/continue-reading',
        'load-home',
        cancellation,
      ),
      this.get(
        baseUrl,
        '/api/dashboard/recent-books?limit=5',
        'load-home',
        cancellation,
      ),
    ]);
    const directFailure = requests.find(
      (result) => result.outcome === 'failed' &&
        (result.failure.reason === 'session-expired' ||
          result.failure.reason === 'cancelled'),
    );
    if (directFailure?.outcome === 'failed') return directFailure;

    const summary = requests[0]?.outcome === 'loaded'
      ? decodeDashboardSummary(requests[0].value.body)
      : invalidDecodedValue('SUMMARY_REQUEST_FAILED');
    const unread = requests[1]?.outcome === 'loaded'
      ? decodeUnreadTotal(requests[1].value.body)
      : invalidDecodedValue('UNREAD_REQUEST_FAILED');
    const continuing = requests[2]?.outcome === 'loaded'
      ? decodeContinueReading(requests[2].value.body)
      : invalidDecodedValue('CONTINUE_REQUEST_FAILED');
    const recent = requests[3]?.outcome === 'loaded'
      ? decodeRecentBooks(requests[3].value.body)
      : invalidDecodedValue('RECENT_REQUEST_FAILED');
    const unavailableSections: HomeSection[] = [];
    if (!summary.ok) unavailableSections.push('summary');
    if (!unread.ok) unavailableSections.push('unread');
    if (!continuing.ok) unavailableSections.push('continue-reading');
    if (!recent.ok) unavailableSections.push('recent-books');
    if (unavailableSections.length === 4) {
      const firstFailure = requests.find((result) => result.outcome === 'failed');
      return firstFailure?.outcome === 'failed'
        ? firstFailure
        : { outcome: 'failed', failure: failure('load-home', 'incompatible-response') };
    }
    return {
      outcome: 'loaded',
      value: {
        summary: summary.ok && unread.ok
          ? { ...summary.value, unreadBooks: unread.value }
          : null,
        continueReading: continuing.ok ? continuing.value : null,
        recentBooks: recent.ok ? recent.value : [],
        unavailableSections,
      },
    };
  }

  async loadShelves(
    baseUrl: ServerBaseUrl,
    cancellation: CancellationToken,
  ): Promise<LibraryResult<ShelfOverviewData>> {
    return this.decodedRequest(
      baseUrl, '/api/shelves', 'GET', 'load-shelves', cancellation,
      decodeShelves,
    );
  }

  async loadCollection(
    baseUrl: ServerBaseUrl,
    collectionId: string,
    cancellation: CancellationToken,
  ): Promise<LibraryResult<CollectionDetail>> {
    return this.decodedRequest(
      baseUrl,
      `/api/shelves/${encodeURIComponent(collectionId)}?page=1&pageSize=100&includeBookIds=false`,
      'GET',
      'load-collection',
      cancellation,
      decodeCollectionDetail,
    );
  }

  async loadBooks(
    baseUrl: ServerBaseUrl,
    query: BooksQuery,
    page: number,
    cancellation: CancellationToken,
  ): Promise<LibraryResult<BooksPage>> {
    return this.decodedAbsoluteRequest(
      queryUrl(baseUrl, query, page), 'GET', 'load-books', cancellation,
      decodeBooksPage,
    );
  }

  async loadPreferences(
    baseUrl: ServerBaseUrl,
    cancellation: CancellationToken,
  ): Promise<LibraryResult<LibraryPreferences>> {
    return this.decodedRequest(
      baseUrl, '/api/auth/preferences', 'GET', 'load-preferences', cancellation,
      decodePreferences,
    );
  }

  async savePreferences(
    baseUrl: ServerBaseUrl,
    preferences: LibraryPreferences,
    cancellation: CancellationToken,
  ): Promise<LibraryResult<LibraryPreferences>> {
    return this.decodedRequest(
      baseUrl,
      '/api/auth/preferences',
      'PATCH',
      'save-preferences',
      cancellation,
      decodePreferences,
      {
        preferences: {
          'library.view': preferences.view,
          'library.sort': preferences.sort,
          'library.sortDirection': preferences.direction,
        },
      },
    );
  }

  async createShelf(
    baseUrl: ServerBaseUrl,
    name: string,
    cancellation: CancellationToken,
  ): Promise<LibraryResult<ShelfSummary>> {
    return this.decodedRequest(
      baseUrl, '/api/shelves', 'POST', 'create-shelf', cancellation,
      decodeShelf, { name, kind: 'STATIC' },
    );
  }

  async renameShelf(
    baseUrl: ServerBaseUrl,
    shelfId: string,
    name: string,
    cancellation: CancellationToken,
  ): Promise<LibraryResult<ShelfSummary>> {
    return this.decodedRequest(
      baseUrl,
      `/api/shelves/${encodeURIComponent(shelfId)}`,
      'PATCH',
      'rename-shelf',
      cancellation,
      decodeShelf,
      { name },
    );
  }

  async deleteShelf(
    baseUrl: ServerBaseUrl,
    shelfId: string,
    cancellation: CancellationToken,
  ): Promise<LibraryResult<Readonly<{ id: string }>>> {
    return this.decodedRequest(
      baseUrl,
      `/api/shelves/${encodeURIComponent(shelfId)}`,
      'DELETE',
      'delete-shelf',
      cancellation,
      decodeDeletedShelf,
    );
  }

  async loadImportTargets(
    baseUrl: ServerBaseUrl,
    cancellation: CancellationToken,
  ): Promise<LibraryResult<ImportTargets>> {
    return this.decodedRequest(
      baseUrl,
      '/api/monitor-folders?purpose=upload',
      'GET',
      'load-import-targets',
      cancellation,
      decodeImportTargets,
    );
  }

  async importFiles(
    baseUrl: ServerBaseUrl,
    files: readonly LibraryImportFile[],
    targetPath: string,
    cancellation: CancellationToken,
  ): Promise<LibraryResult<ImportSuccess>> {
    const form = new FormData();
    for (const file of files) form.append('files', file.content, file.name);
    form.append('targetPath', targetPath);
    const controller = new AbortController();
    if (cancellation.isCancellationRequested()) controller.abort();
    const unsubscribe = cancellation.subscribe(() => controller.abort());
    try {
      const response = await this.transport.request({
        method: 'POST',
        url: serverApiUrl(baseUrl, '/api/works/import'),
        timeoutMs: IMPORT_TIMEOUT_MS,
        maximumResponseBytes: JSON_MAXIMUM_RESPONSE_BYTES,
        responseType: 'json',
        signal: controller.signal,
        body: { kind: 'form-data', value: form },
      });
      return this.decodeResponse('import-files', response, decodeImportSuccess);
    } finally {
      unsubscribe();
    }
  }

  async loadCover(
    baseUrl: ServerBaseUrl,
    coverUrl: string,
    cancellation: CancellationToken,
  ): Promise<LibraryResult<LibraryCover>> {
    const sourceUrl = resolvedCoverUrl(baseUrl, coverUrl);
    if (sourceUrl === null) {
      return { outcome: 'failed', failure: failure('load-cover', 'invalid-request') };
    }
    const cacheKey = `${baseUrl.value}\n${sourceUrl}`;
    const cached = this.coverCache.get(cacheKey);
    if (cached !== undefined) {
      this.coverCache.delete(cacheKey);
      this.coverCache.set(cacheKey, cached);
      return { outcome: 'loaded', value: cached };
    }
    const controller = new AbortController();
    if (cancellation.isCancellationRequested()) controller.abort();
    const unsubscribe = cancellation.subscribe(() => controller.abort());
    try {
      const response = await this.transport.request({
        method: 'GET',
        url: sourceUrl,
        timeoutMs: JSON_TIMEOUT_MS,
        maximumResponseBytes: COVER_MAXIMUM_RESPONSE_BYTES,
        responseType: 'bytes',
        signal: controller.signal,
        headers: { Accept: 'image/jpeg, image/png, image/webp' },
      });
      if (!response.ok) {
        return { outcome: 'failed', failure: transportFailure('load-cover', response) };
      }
      if (response.status === 401) {
        return {
          outcome: 'failed',
          failure: failure('load-cover', 'session-expired', { status: 401 }),
        };
      }
      const contentType = response.headers.contentType?.split(';')[0]?.trim() ?? '';
      if (
        response.status !== 200 || response.responseType !== 'bytes' ||
        !COVER_CONTENT_TYPES.has(contentType) || response.body.byteLength === 0
      ) {
        return {
          outcome: 'failed',
          failure: failure('load-cover', 'incompatible-response', {
            status: response.status,
          }),
        };
      }
      const normalizedType = contentType === 'image/jpeg'
        ? 'image/jpeg'
        : contentType === 'image/png'
        ? 'image/png'
        : 'image/webp';
      const cover: LibraryCover = {
        cacheKey,
        sourceUrl,
        contentType: normalizedType,
        bytes: response.body,
      };
      this.cacheCover(cover);
      return { outcome: 'loaded', value: cover };
    } finally {
      unsubscribe();
    }
  }

  clearCoverCache(baseUrl?: ServerBaseUrl): void {
    if (baseUrl === undefined) {
      this.coverCache.clear();
      this.coverCacheBytes = 0;
      return;
    }
    const prefix = `${baseUrl.value}\n`;
    for (const key of this.coverCache.keys()) {
      if (key.startsWith(prefix)) this.removeCachedCover(key);
    }
  }

  private cacheCover(cover: LibraryCover): void {
    this.removeCachedCover(cover.cacheKey);
    this.coverCache.set(cover.cacheKey, cover);
    this.coverCacheBytes += cover.bytes.byteLength;
    while (this.coverCacheBytes > COVER_MEMORY_CACHE_BUDGET_BYTES) {
      const oldestKey = this.coverCache.keys().next().value;
      if (typeof oldestKey !== 'string') break;
      this.removeCachedCover(oldestKey);
    }
  }

  private removeCachedCover(cacheKey: string): void {
    const cached = this.coverCache.get(cacheKey);
    if (cached === undefined) return;
    this.coverCache.delete(cacheKey);
    this.coverCacheBytes -= cached.bytes.byteLength;
  }

  private async get(
    baseUrl: ServerBaseUrl,
    path: `/api/${string}`,
    operation: Operation,
    cancellation: CancellationToken,
  ): Promise<LibraryResult<JsonSuccess>> {
    const response = await this.requestJson(
      serverApiUrl(baseUrl, path), 'GET', cancellation,
    );
    if (!response.ok) {
      return { outcome: 'failed', failure: transportFailure(operation, response) };
    }
    if (response.responseType !== 'json') {
      return { outcome: 'failed', failure: failure(operation, 'incompatible-response') };
    }
    if (response.status < 200 || response.status >= 300) {
      return { outcome: 'failed', failure: statusFailure(operation, response) };
    }
    return { outcome: 'loaded', value: response };
  }

  private async decodedRequest<Value>(
    baseUrl: ServerBaseUrl,
    path: `/api/${string}`,
    method: ApiRequest['method'],
    operation: Operation,
    cancellation: CancellationToken,
    decode: (value: unknown) => Readonly<
      { ok: true; value: Value } | { ok: false; reason: string }
    >,
    body?: unknown,
  ): Promise<LibraryResult<Value>> {
    return this.decodedAbsoluteRequest(
      serverApiUrl(baseUrl, path), method, operation, cancellation, decode, body,
    );
  }

  private async decodedAbsoluteRequest<Value>(
    url: string,
    method: ApiRequest['method'],
    operation: Operation,
    cancellation: CancellationToken,
    decode: (value: unknown) => Readonly<
      { ok: true; value: Value } | { ok: false; reason: string }
    >,
    body?: unknown,
  ): Promise<LibraryResult<Value>> {
    const response = await this.requestJson(url, method, cancellation, body);
    return this.decodeResponse(operation, response, decode);
  }

  private async requestJson(
    url: string,
    method: ApiRequest['method'],
    cancellation: CancellationToken,
    body?: unknown,
  ): Promise<ApiTransportResult> {
    const controller = new AbortController();
    if (cancellation.isCancellationRequested()) controller.abort();
    const unsubscribe = cancellation.subscribe(() => controller.abort());
    try {
      return await this.transport.request({
        method,
        url,
        timeoutMs: JSON_TIMEOUT_MS,
        maximumResponseBytes: JSON_MAXIMUM_RESPONSE_BYTES,
        responseType: 'json',
        signal: controller.signal,
        ...(body === undefined ? {} : { body: { kind: 'json', value: body } }),
      });
    } finally {
      unsubscribe();
    }
  }

  private decodeResponse<Value>(
    operation: Operation,
    response: ApiTransportResult,
    decode: (value: unknown) => Readonly<
      { ok: true; value: Value } | { ok: false; reason: string }
    >,
  ): LibraryResult<Value> {
    if (!response.ok) {
      return { outcome: 'failed', failure: transportFailure(operation, response) };
    }
    if (response.responseType !== 'json') {
      return { outcome: 'failed', failure: failure(operation, 'incompatible-response') };
    }
    if (response.status < 200 || response.status >= 300) {
      return { outcome: 'failed', failure: statusFailure(operation, response) };
    }
    const decoded = decode(response.body);
    return decoded.ok
      ? { outcome: 'loaded', value: decoded.value }
      : {
          outcome: 'failed',
          failure: failure(operation, 'incompatible-response', {
            status: response.status,
            code: decoded.reason,
          }),
        };
  }
}
