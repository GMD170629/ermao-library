import assert from 'node:assert/strict';
import test from 'node:test';

import type {
  ApiRequest,
  ApiTransport,
  ApiTransportResult,
} from '../../../shared/api/public';
import { parseServerAddress } from '../../server-connection/public';
import { DEFAULT_BOOKS_QUERY } from '../model/library';
import { AbortLibraryCancellationFactory } from './abort-library-cancellation';
import { LibraryClient } from './library-client';

class QueueTransport implements ApiTransport {
  readonly requests: ApiRequest[] = [];

  constructor(private readonly responses: ApiTransportResult[]) {}

  async request(request: ApiRequest): Promise<ApiTransportResult> {
    this.requests.push(request);
    const response = this.responses.shift();
    if (response === undefined) throw new Error('Missing queued response');
    return response;
  }
}

function json(status: number, body: unknown): ApiTransportResult {
  return {
    ok: true,
    responseType: 'json',
    status,
    headers: { contentType: 'application/json', etag: null, lastModified: null },
    body,
  };
}

function server() {
  const parsed = parseServerAddress('https://books.example/subpath');
  if (!parsed.ok) throw new Error('Test server address must be valid');
  return parsed.baseUrl;
}

function cancellation() {
  return new AbortLibraryCancellationFactory().create().token;
}

function staticShelfEnvelope(name: string) {
  return {
    ok: true,
    data: {
      shelf: {
        id: 'shelf-1',
        ownerUserId: 'user-1',
        name,
        description: null,
        kind: 'STATIC',
        rulesJson: '{}',
        pinned: false,
        createdAt: '2026-08-09T10:00:00Z',
        updatedAt: '2026-08-09T10:00:00Z',
        rules: {},
        rulesStatus: 'VALID',
        unsupportedRuleFields: [],
        bookCount: 0,
        books: [],
        collectionIds: [],
      },
    },
  };
}

test('builds fixed bookshelf pagination and server-side shelf filters', async () => {
  const transport = new QueueTransport([
    json(200, {
      ok: true,
      data: { books: [], page: 2, pageSize: 24, total: 25, totalPages: 2 },
    }),
  ]);
  const client = new LibraryClient(transport);
  const result = await client.loadBooks(
    server(),
    {
      ...DEFAULT_BOOKS_QUERY,
      search: '银河',
      status: 'READING',
      mediaKind: 'EBOOK',
      shelfId: 'shelf/one',
    },
    2,
    cancellation(),
  );

  assert.equal(result.outcome, 'loaded');
  const requestUrl = new URL(transport.requests[0]?.url ?? '');
  assert.equal(requestUrl.pathname, '/subpath/api/works');
  assert.equal(requestUrl.searchParams.get('page'), '2');
  assert.equal(requestUrl.searchParams.get('pageSize'), '24');
  assert.equal(requestUrl.searchParams.get('view'), 'bookshelf');
  assert.equal(requestUrl.searchParams.get('status'), 'READING');
  assert.equal(requestUrl.searchParams.get('mediaKind'), 'EBOOK');
  assert.deepEqual(JSON.parse(requestUrl.searchParams.get('filters') ?? ''), {
    combinator: 'ALL',
    conditions: [{ field: 'shelf', operator: 'equals', value: 'shelf/one' }],
  });
});

test('loads collection members from the bounded shelf detail endpoint', async () => {
  const transport = new QueueTransport([
    json(200, {
      ok: true,
      data: {
        shelf: {
          id: 'collection-1',
          ownerUserId: 'user-1',
          name: '阅读计划',
          description: null,
          kind: 'COLLECTION',
          rulesJson: '{}',
          pinned: false,
          createdAt: '2026-08-09T10:00:00Z',
          updatedAt: '2026-08-09T10:00:00Z',
          rules: {},
          rulesStatus: 'VALID',
          unsupportedRuleFields: [],
          shelfCount: 0,
          shelves: [],
          memberShelfIds: [],
        },
      },
    }),
  ]);
  const result = await new LibraryClient(transport).loadCollection(
    server(), 'collection/one', cancellation(),
  );
  assert.equal(result.outcome, 'loaded');
  const url = new URL(transport.requests[0]?.url ?? '');
  assert.equal(url.pathname, '/subpath/api/shelves/collection%2Fone');
  assert.equal(url.searchParams.get('pageSize'), '100');
  assert.equal(url.searchParams.get('includeBookIds'), 'false');
});

test('loads home sections independently and returns partial data', async () => {
  const transport = new QueueTransport([
    json(200, {
      ok: true,
      data: {
        totalBooks: 12,
        ebookBooks: 8,
        comicBooks: 3,
        audiobookBooks: 1,
        storageUsedBytes: 0,
        monitorFolderCount: 1,
        lastImportAt: null,
        latestSyncAt: null,
      },
    }),
    json(200, {
      ok: true,
      data: {
        books: [
          {
            id: 'work-1',
            title: '局外人',
            author: '阿尔贝·加缪',
            gradient: 'warm',
            coverStatus: 'READY',
            coverUrl: '/api/works/work-1/cover',
            seriesName: null,
            tags: [],
            availableMediaKinds: ['EBOOK'],
            statusValue: 'UNREAD',
            lastReadAt: null,
            importedAt: '2026-08-09T10:00:00Z',
          },
        ],
        page: 1,
        pageSize: 1,
        total: 3,
        totalPages: 3,
      },
    }),
    json(503, { ok: false, error: { message: 'busy', code: 'BUSY' } }),
    json(200, { ok: true, data: { books: [] } }),
    json(200, { ok: true, data: { books: [] } }),
  ]);
  const result = await new LibraryClient(transport).loadHome(
    server(),
    cancellation(),
  );

  assert.equal(result.outcome, 'loaded');
  if (result.outcome !== 'loaded') return;
  assert.equal(result.value.summary?.unreadBooks, 3);
  assert.deepEqual(result.value.unavailableSections, ['continue-reading']);
  assert.equal(
    new URL(transport.requests[3]?.url ?? '').pathname,
    '/subpath/api/dashboard/recent-reading',
  );
  assert.equal(
    new URL(transport.requests[1]?.url ?? '').searchParams.get('view'),
    'management',
  );
});

test('classifies 401 as a named session-expired outcome', async () => {
  const transport = new QueueTransport([
    json(401, { ok: false, error: { message: 'expired', code: 'AUTH_REQUIRED' } }),
  ]);
  const result = await new LibraryClient(transport).loadShelves(
    server(),
    cancellation(),
  );
  assert.deepEqual(result, {
    outcome: 'failed',
    failure: {
      operation: 'load-shelves',
      reason: 'session-expired',
      status: 401,
      code: 'AUTH_REQUIRED',
    },
  });
});

test('uses bounded static shelf create, rename, and delete commands', async () => {
  const transport = new QueueTransport([
    json(201, staticShelfEnvelope('待读清单')),
    json(200, staticShelfEnvelope('稍后阅读')),
    json(200, { ok: true, data: { deleted: true, id: 'shelf-1' } }),
  ]);
  const client = new LibraryClient(transport);
  const created = await client.createShelf(
    server(), '待读清单', cancellation(),
  );
  const renamed = await client.renameShelf(
    server(), 'shelf-1', '稍后阅读', cancellation(),
  );
  const deleted = await client.deleteShelf(
    server(), 'shelf-1', cancellation(),
  );
  assert.equal(created.outcome, 'loaded');
  assert.equal(renamed.outcome, 'loaded');
  assert.equal(deleted.outcome, 'loaded');
  assert.deepEqual(transport.requests[0]?.body, {
    kind: 'json', value: { name: '待读清单', kind: 'STATIC' },
  });
  assert.deepEqual(transport.requests[1]?.body, {
    kind: 'json', value: { name: '稍后阅读' },
  });
  assert.equal(transport.requests[2]?.method, 'DELETE');
  assert.equal(transport.requests[2]?.body, undefined);
});

test('uses FormData without a manual content type for imports', async () => {
  const transport = new QueueTransport([
    json(200, {
      ok: true,
      data: {
        results: [
          {
            sourcePath: '/library/book.epub',
            file: 'book.epub',
            sizeBytes: 4,
            monitoringStatus: 'WATCHING',
          },
        ],
        saved: 1,
        autoImport: true,
      },
    }),
  ]);
  const result = await new LibraryClient(transport).importFiles(
    server(),
    [{ name: 'book.epub', content: new Blob(['book']) }],
    '/library',
    cancellation(),
  );
  assert.equal(result.outcome, 'loaded');
  const request = transport.requests[0];
  assert.equal(request?.body?.kind, 'form-data');
  assert.equal(request?.headers?.['Content-Type'], undefined);
});

test('bounds authenticated cover bytes, validates MIME, and caches per server', async () => {
  const transport = new QueueTransport([
    {
      ok: true,
      responseType: 'bytes',
      status: 200,
      headers: { contentType: 'image/jpeg; charset=binary', etag: null, lastModified: null },
      body: new Uint8Array([1, 2, 3]),
    },
  ]);
  const client = new LibraryClient(transport);
  const first = await client.loadCover(
    server(), '/api/works/work-1/cover', cancellation(),
  );
  const second = await client.loadCover(
    server(), '/api/works/work-1/cover', cancellation(),
  );
  assert.equal(first.outcome, 'loaded');
  assert.deepEqual(second, first);
  assert.equal(transport.requests.length, 1);
  assert.equal(transport.requests[0]?.responseType, 'bytes');
  assert.equal(transport.requests[0]?.maximumResponseBytes, 8 * 1024 * 1024);
  assert.equal(
    transport.requests[0]?.url,
    'https://books.example/subpath/api/works/work-1/cover',
  );
});

test('rejects cover URLs outside the connected server scope', async () => {
  const transport = new QueueTransport([]);
  const result = await new LibraryClient(transport).loadCover(
    server(), 'https://cdn.example/cover.jpg', cancellation(),
  );
  assert.equal(result.outcome, 'failed');
  if (result.outcome === 'failed') assert.equal(result.failure.reason, 'invalid-request');
  assert.equal(transport.requests.length, 0);
});
