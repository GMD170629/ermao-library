import assert from 'node:assert/strict';
import test from 'node:test';

import { parseServerAddress } from '../../server-connection/public';
import { AbortLibraryCancellationFactory } from '../api/abort-library-cancellation';
import type {
  BooksPage,
  HomeLoadResult,
  LibraryCoverStore,
  LibraryCoverStoreResult,
  LibraryFilePicker,
  LibraryGateway,
  LibraryImportFile,
  LibraryResult,
} from './ports';
import type {
  BooksQuery,
  CollectionDetail,
  ImportSuccess,
  ImportTargets,
  LibraryCover,
  LibraryPreferences,
  ShelfOverviewData,
  ShelfSummary,
} from '../model/library';
import { DEFAULT_BOOKS_QUERY } from '../model/library';
import { LibraryController } from './library-controller';

function server() {
  const parsed = parseServerAddress('https://books.example');
  if (!parsed.ok) throw new Error('Test server address must be valid');
  return parsed.baseUrl;
}

function deferred<Value>() {
  let complete: ((value: Value) => void) | undefined;
  const promise = new Promise<Value>((resolve) => {
    complete = resolve;
  });
  return {
    promise,
    resolve(value: Value): void {
      if (complete === undefined) throw new Error('Deferred is not initialized');
      complete(value);
    },
  };
}

const emptyPage: BooksPage = {
  books: [],
  page: 1,
  pageSize: 24,
  total: 0,
  totalPages: 1,
};
const preferences: LibraryPreferences = {
  view: 'grid',
  sort: 'recent_read',
  direction: 'desc',
};
const emptyShelves: ShelfOverviewData = { collections: [], shelves: [] };
const targets: ImportTargets = {
  targets: [
    { folderId: 'folder-1', name: 'Books', rootPath: '/library', enabled: true },
  ],
  selectedTargetPath: '/library',
};

class FakeGateway implements LibraryGateway {
  readonly booksCalls: Readonly<{ query: BooksQuery; page: number }>[] = [];
  booksResults: Promise<LibraryResult<BooksPage>>[] = [];
  coverResults: Promise<LibraryResult<LibraryCover>>[] = [];
  shelvesResult: LibraryResult<ShelfOverviewData> = {
    outcome: 'loaded', value: emptyShelves,
  };
  createShelfResult: Promise<LibraryResult<ShelfSummary>> = Promise.resolve({
    outcome: 'failed',
    failure: { operation: 'create-shelf', reason: 'unknown' },
  });
  renameShelfResult: Promise<LibraryResult<ShelfSummary>> = Promise.resolve({
    outcome: 'failed',
    failure: { operation: 'rename-shelf', reason: 'unknown' },
  });
  deleteShelfResult: Promise<LibraryResult<Readonly<{ id: string }>>> =
    Promise.resolve({
      outcome: 'failed',
      failure: { operation: 'delete-shelf', reason: 'unknown' },
    });
  importCalls = 0;

  async loadHome(): Promise<HomeLoadResult> {
    return {
      outcome: 'loaded',
      value: {
        summary: null,
        continueReading: null,
        recentBooks: [],
        unavailableSections: ['summary', 'unread'],
      },
    };
  }

  async loadShelves(): Promise<LibraryResult<ShelfOverviewData>> {
    return this.shelvesResult;
  }

  async loadCollection(): Promise<LibraryResult<CollectionDetail>> {
    return {
      outcome: 'loaded',
      value: { id: 'collection-1', name: '阅读计划', shelves: [] },
    };
  }

  async loadBooks(
    _baseUrl: ReturnType<typeof server>,
    query: BooksQuery,
    page: number,
  ): Promise<LibraryResult<BooksPage>> {
    this.booksCalls.push({ query, page });
    return this.booksResults.shift() ?? { outcome: 'loaded', value: emptyPage };
  }

  async loadPreferences(): Promise<LibraryResult<LibraryPreferences>> {
    return { outcome: 'loaded', value: preferences };
  }

  async savePreferences(
    _baseUrl: ReturnType<typeof server>,
    value: LibraryPreferences,
  ): Promise<LibraryResult<LibraryPreferences>> {
    return { outcome: 'loaded', value };
  }

  async createShelf(): Promise<LibraryResult<ShelfSummary>> {
    return this.createShelfResult;
  }

  async renameShelf(): Promise<LibraryResult<ShelfSummary>> {
    return this.renameShelfResult;
  }

  async deleteShelf(): Promise<LibraryResult<Readonly<{ id: string }>>> {
    return this.deleteShelfResult;
  }

  async loadImportTargets(): Promise<LibraryResult<ImportTargets>> {
    return { outcome: 'loaded', value: targets };
  }

  async importFiles(
    _baseUrl: ReturnType<typeof server>,
    files: readonly LibraryImportFile[],
  ): Promise<LibraryResult<ImportSuccess>> {
    this.importCalls += 1;
    return {
      outcome: 'loaded',
      value: {
        saved: files.length,
        autoImport: true,
        files: files.map((file) => ({
          name: file.name,
          sourcePath: `/library/${file.name}`,
          sizeBytes: file.sizeBytes ?? 0,
          monitoringStatus: 'WATCHING',
        })),
      },
    };
  }

  async loadCover(): Promise<LibraryResult<LibraryCover>> {
    return this.coverResults.shift() ?? {
      outcome: 'failed',
      failure: { operation: 'load-cover', reason: 'unknown' },
    };
  }

  clearCoverCache(): void {}
}

class MemoryCoverStore implements LibraryCoverStore {
  async store(cover: LibraryCover): Promise<LibraryCoverStoreResult> {
    return {
      outcome: 'stored',
      source: { cacheKey: cover.cacheKey, uri: 'file:///cover' },
    };
  }

  async clearServer(): Promise<void> {}
}

function controller(
  gateway: FakeGateway,
  picker: LibraryFilePicker = { pickFiles: async () => ({ outcome: 'cancelled' }) },
  onSessionExpired: () => void = () => {},
): LibraryController {
  return new LibraryController(
    gateway,
    new AbortLibraryCancellationFactory(),
    {
      context: { baseUrl: server(), canImport: true },
      filePicker: picker,
      coverStore: new MemoryCoverStore(),
      onSessionExpired,
    },
  );
}

test('rejects a late books result after the query changes', async () => {
  const gateway = new FakeGateway();
  const first = deferred<LibraryResult<BooksPage>>();
  const second = deferred<LibraryResult<BooksPage>>();
  gateway.booksResults.push(first.promise, second.promise);
  const subject = controller(gateway);

  const originalLoad = subject.loadBooks();
  const nextQuery = { ...DEFAULT_BOOKS_QUERY, search: '银河' };
  const nextLoad = subject.setBooksQuery(nextQuery);
  second.resolve({
    outcome: 'loaded',
    value: {
      ...emptyPage,
      books: [
        { id: 'new', title: '银河', author: '', coverUrl: '', mediaKinds: ['EBOOK'] },
      ],
      total: 1,
    },
  });
  await nextLoad;
  first.resolve({
    outcome: 'loaded',
    value: {
      ...emptyPage,
      books: [
        { id: 'old', title: '旧结果', author: '', coverUrl: '', mediaKinds: ['EBOOK'] },
      ],
      total: 1,
    },
  });
  await originalLoad;

  const state = subject.getSnapshot().books;
  assert.equal(state.phase, 'ready');
  if (state.phase !== 'ready') return;
  assert.equal(state.query.search, '银河');
  assert.equal(state.books[0]?.id, 'new');
});

test('loads the next page once and de-duplicates repeated work ids', async () => {
  const gateway = new FakeGateway();
  gateway.booksResults.push(
    Promise.resolve({
      outcome: 'loaded',
      value: {
        books: [
          { id: 'one', title: '一', author: '', coverUrl: '', mediaKinds: ['EBOOK'] },
        ],
        page: 1,
        pageSize: 24,
        total: 2,
        totalPages: 2,
      },
    }),
    Promise.resolve({
      outcome: 'loaded',
      value: {
        books: [
          { id: 'one', title: '一', author: '', coverUrl: '', mediaKinds: ['EBOOK'] },
          { id: 'two', title: '二', author: '', coverUrl: '', mediaKinds: ['COMIC'] },
        ],
        page: 2,
        pageSize: 24,
        total: 2,
        totalPages: 2,
      },
    }),
  );
  const subject = controller(gateway);
  await subject.loadBooks();
  await subject.loadNextPage();
  await subject.loadNextPage();
  const state = subject.getSnapshot().books;
  assert.equal(state.phase, 'ready');
  if (state.phase !== 'ready') return;
  assert.deepEqual(state.books.map((book) => book.id), ['one', 'two']);
  assert.equal(gateway.booksCalls.length, 2);
});

test('reports repeated business 401 outcomes to AppFlow only once', async () => {
  const gateway = new FakeGateway();
  gateway.shelvesResult = {
    outcome: 'failed',
    failure: { operation: 'load-shelves', reason: 'session-expired', status: 401 },
  };
  let expiries = 0;
  const subject = controller(gateway, undefined, () => { expiries += 1; });

  await subject.loadShelves();
  await subject.loadShelves();
  assert.equal(expiries, 1);
});

test('loads collection members into a dedicated navigation state', async () => {
  const subject = controller(new FakeGateway());
  await subject.loadCollection('collection-1');
  const state = subject.getSnapshot().collection;
  assert.deepEqual(state, {
    phase: 'ready',
    data: { id: 'collection-1', name: '阅读计划', shelves: [] },
  });
  subject.closeCollection();
  assert.deepEqual(subject.getSnapshot().collection, { phase: 'idle' });
});

test('returns named validation failures without starting shelf mutations', async () => {
  const subject = controller(new FakeGateway());

  assert.deepEqual(await subject.createShelf('   '), {
    outcome: 'failed',
    failure: {
      operation: 'create-shelf',
      reason: 'invalid-request',
      code: 'INVALID_SHELF_NAME',
    },
  });
  assert.deepEqual(await subject.renameShelf('', '新名称'), {
    outcome: 'failed',
    failure: {
      operation: 'rename-shelf',
      reason: 'invalid-request',
      code: 'INVALID_SHELF_ID',
    },
  });
  assert.deepEqual(await subject.deleteShelf('   '), {
    outcome: 'failed',
    failure: {
      operation: 'delete-shelf',
      reason: 'invalid-request',
      code: 'INVALID_SHELF_ID',
    },
  });
});

test('returns shelf failures while preserving the ready state with a warning', async () => {
  const gateway = new FakeGateway();
  gateway.renameShelfResult = Promise.resolve({
    outcome: 'failed',
    failure: {
      operation: 'rename-shelf',
      reason: 'invalid-request',
      code: 'SHELF_NAME_CONFLICT',
    },
  });
  const subject = controller(gateway);
  await subject.loadShelves();

  const outcome = await subject.renameShelf('shelf-1', '重复名称');

  assert.deepEqual(outcome, {
    outcome: 'failed',
    failure: {
      operation: 'rename-shelf',
      reason: 'invalid-request',
      code: 'SHELF_NAME_CONFLICT',
    },
  });
  const state = subject.getSnapshot().shelves;
  assert.equal(state.phase, 'ready');
  if (state.phase !== 'ready') return;
  assert.equal(state.mutatingShelfId, null);
  assert.equal(state.warning?.reason, 'invalid-request');
});

test('returns success only after a shelf mutation is applied to state', async () => {
  const gateway = new FakeGateway();
  gateway.createShelfResult = Promise.resolve({
    outcome: 'loaded',
    value: {
      id: 'shelf-1',
      name: '稍后阅读',
      description: null,
      kind: 'STATIC',
      pinned: false,
      bookCount: 0,
      shelfCount: 0,
      books: [],
      memberShelfIds: [],
      updatedAt: '2026-08-09T00:00:00Z',
    },
  });
  const subject = controller(gateway);
  await subject.loadShelves();

  const outcome = await subject.createShelf(' 稍后阅读 ');

  assert.deepEqual(outcome, { outcome: 'succeeded' });
  const state = subject.getSnapshot().shelves;
  assert.equal(state.phase, 'ready');
  if (state.phase !== 'ready') return;
  assert.equal(state.mutatingShelfId, null);
  assert.deepEqual(state.data.shelves.map((shelf) => shelf.id), ['shelf-1']);
});

test('returns a cancelled shelf outcome when a newer shelves operation supersedes it', async () => {
  const gateway = new FakeGateway();
  const pending = deferred<LibraryResult<Readonly<{ id: string }>>>();
  gateway.deleteShelfResult = pending.promise;
  const subject = controller(gateway);
  await subject.loadShelves();

  const deletion = subject.deleteShelf('shelf-1');
  await subject.loadShelves();
  pending.resolve({ outcome: 'loaded', value: { id: 'shelf-1' } });

  assert.deepEqual(await deletion, {
    outcome: 'failed',
    failure: { operation: 'delete-shelf', reason: 'cancelled' },
  });
});

test('keeps picker cancellation side-effect free and validates selected files', async () => {
  const gateway = new FakeGateway();
  const cancelled = controller(gateway);
  await cancelled.loadImportTargets();
  await cancelled.chooseAndImport('/library');
  assert.equal(gateway.importCalls, 0);

  const selectedFile: LibraryImportFile = {
    name: 'book.epub',
    sizeBytes: 4,
    content: new Blob(['book']),
  };
  const selected = controller(gateway, {
    pickFiles: async () => ({ outcome: 'selected', files: [selectedFile] }),
  });
  await selected.loadImportTargets();
  await selected.chooseAndImport('/library');
  assert.equal(gateway.importCalls, 1);
  const state = selected.getSnapshot().import;
  assert.equal(state.phase, 'ready');
  if (state.phase === 'ready') assert.equal(state.upload.phase, 'succeeded');
});

test('loads different covers concurrently and rejects a late result for the same book', async () => {
  const gateway = new FakeGateway();
  const first = deferred<LibraryResult<LibraryCover>>();
  const second = deferred<LibraryResult<LibraryCover>>();
  const replacement = deferred<LibraryResult<LibraryCover>>();
  gateway.coverResults.push(first.promise, second.promise, replacement.promise);
  const subject = controller(gateway);

  const firstLoad = subject.loadCover('book-1', '/api/works/book-1/cover?old');
  const secondLoad = subject.loadCover('book-2', '/api/works/book-2/cover');
  const replacementLoad = subject.loadCover(
    'book-1',
    '/api/works/book-1/cover?new',
  );
  second.resolve({
    outcome: 'loaded',
    value: {
      cacheKey: 'book-2',
      sourceUrl: 'https://books.example/api/works/book-2/cover',
      contentType: 'image/jpeg',
      bytes: new Uint8Array([2]),
    },
  });
  replacement.resolve({
    outcome: 'loaded',
    value: {
      cacheKey: 'book-1-new',
      sourceUrl: 'https://books.example/api/works/book-1/cover?new',
      contentType: 'image/jpeg',
      bytes: new Uint8Array([3]),
    },
  });
  await Promise.all([secondLoad, replacementLoad]);
  first.resolve({
    outcome: 'loaded',
    value: {
      cacheKey: 'book-1-old',
      sourceUrl: 'https://books.example/api/works/book-1/cover?old',
      contentType: 'image/jpeg',
      bytes: new Uint8Array([1]),
    },
  });
  await firstLoad;

  const covers = subject.getSnapshot().covers;
  assert.equal(covers['book-1']?.phase, 'ready');
  assert.equal(covers['book-2']?.phase, 'ready');
  if (covers['book-1']?.phase === 'ready') {
    assert.equal(covers['book-1'].source.cacheKey, 'book-1-new');
  }
});
