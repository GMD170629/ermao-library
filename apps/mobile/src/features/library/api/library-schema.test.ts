import assert from 'node:assert/strict';
import test from 'node:test';

import {
  decodeBooksPage,
  decodeCollectionDetail,
  decodeContinueReading,
  decodeDashboardSummary,
  decodeImportSuccess,
  decodeImportTargets,
  decodePreferences,
  decodeShelves,
  decodeUnreadTotal,
} from './library-schema';

test('decodes dashboard, continue reading, books, and unread totals', () => {
  assert.deepEqual(
    decodeDashboardSummary({
      ok: true,
      data: {
        totalBooks: 12,
        ebookBooks: 8,
        comicBooks: 3,
        audiobookBooks: 1,
        storageUsedBytes: 1024,
        monitorFolderCount: 2,
        lastImportAt: null,
        latestSyncAt: '2026-08-09T10:00:00Z',
      },
    }),
    {
      ok: true,
      value: { totalBooks: 12, ebookBooks: 8, comicBooks: 3, audiobookBooks: 1 },
    },
  );
  const continuing = decodeContinueReading({
    ok: true,
    data: {
      item: {
        workId: 'work-1',
        title: '局外人',
        author: '阿尔贝·加缪',
        coverUrl: '/api/works/work-1/cover',
        mediaKind: 'EBOOK',
        volumeFormat: 'EPUB',
        readerType: 'reflowable',
        resumeVolumeId: 'volume-1',
        progress: 66,
        chapter: '第 42 页',
        lastReadAt: '2026-08-09T10:00:00Z',
        volumeTitle: null,
        narrator: null,
      },
    },
  });
  assert.equal(continuing.ok, true);
  if (continuing.ok) assert.equal(continuing.value?.progressPercent, 66);

  const booksEnvelope = {
    ok: true,
    data: {
      books: [
        {
          id: 'work-1',
          title: '局外人',
          author: '阿尔贝·加缪',
          coverUrl: '/api/works/work-1/cover',
          availableMediaKinds: ['EBOOK'],
        },
      ],
      page: 1,
      pageSize: 24,
      total: 25,
      totalPages: 2,
    },
  };
  const page = decodeBooksPage(booksEnvelope);
  assert.equal(page.ok, true);
  if (page.ok) assert.equal(page.value.books[0]?.title, '局外人');
  assert.deepEqual(
    decodeUnreadTotal({
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
    { ok: true, value: 3 },
  );
});

test('strictly rejects unknown keys and invalid nested book data', () => {
  const summary = decodeDashboardSummary({
    ok: true,
    data: {
      totalBooks: 0,
      ebookBooks: 0,
      comicBooks: 0,
      audiobookBooks: 0,
      storageUsedBytes: 0,
      monitorFolderCount: 0,
      lastImportAt: null,
      latestSyncAt: null,
      unexpected: true,
    },
  });
  assert.equal(summary.ok, false);

  const page = decodeBooksPage({
    ok: true,
    data: {
      books: [{ id: 'work-1' }],
      page: 1,
      pageSize: 24,
      total: 1,
      totalPages: 1,
    },
  });
  assert.equal(page.ok, false);
});

test('decodes collections and static shelves into separate sections', () => {
  const common = {
    ownerUserId: 'user-1',
    description: null,
    rulesJson: '{}',
    pinned: false,
    createdAt: '2026-08-09T10:00:00Z',
    updatedAt: '2026-08-09T10:00:00Z',
    rules: {},
    rulesStatus: 'VALID',
    unsupportedRuleFields: [],
    books: [],
  };
  const decoded = decodeShelves({
    ok: true,
    data: {
      shelves: [
        {
          ...common,
          id: 'collection-1',
          name: '阅读计划',
          kind: 'COLLECTION',
          shelfCount: 2,
          memberShelfIds: ['shelf-1', 'shelf-2'],
        },
        {
          ...common,
          id: 'shelf-1',
          name: '待读清单',
          kind: 'STATIC',
          bookCount: 18,
          collectionIds: ['collection-1'],
        },
      ],
    },
  });
  assert.equal(decoded.ok, true);
  if (!decoded.ok) return;
  assert.equal(decoded.value.collections[0]?.shelfCount, 2);
  assert.equal(decoded.value.shelves[0]?.bookCount, 18);
});

test('decodes collection detail member shelves for collection navigation', () => {
  const decoded = decodeCollectionDetail({
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
        shelfCount: 1,
        shelves: [
          {
            id: 'shelf-1',
            name: '待读清单',
            description: null,
            kind: 'STATIC',
            pinned: true,
            bookCount: 18,
            books: [],
            collectionIds: ['collection-1'],
            createdAt: '2026-08-09T10:00:00Z',
            updatedAt: '2026-08-09T10:00:00Z',
          },
        ],
        memberShelfIds: ['shelf-1'],
      },
    },
  });
  assert.equal(decoded.ok, true);
  if (!decoded.ok) return;
  assert.equal(decoded.value.shelves[0]?.name, '待读清单');
  assert.equal(decoded.value.shelves[0]?.bookCount, 18);
});

test('selects a valid previous upload target and decodes saved files', () => {
  const targets = decodeImportTargets({
    ok: true,
    data: {
      folders: [
        {
          id: 'folder-1',
          name: 'Books',
          rootPath: '/library',
          shelfId: null,
          enabled: true,
          mediaKindPolicy: 'MIXED',
          ignorePatterns: null,
          ignoreHidden: true,
          minFileSizeBytes: 1,
          description: null,
          createdAt: '2026-08-09T10:00:00Z',
          updatedAt: '2026-08-09T10:00:00Z',
        },
      ],
      monitorRoot: '/library',
      lastUploadTargetPath: '/library/inbox',
      lastDownloadTargetPath: null,
    },
  });
  assert.equal(targets.ok, true);
  if (targets.ok) assert.equal(targets.value.selectedTargetPath, '/library/inbox');

  const imported = decodeImportSuccess({
    ok: true,
    data: {
      saved: 1,
      autoImport: true,
      results: [
        {
          sourcePath: '/library/inbox/book.epub',
          file: 'book.epub',
          sizeBytes: 42,
          monitoringStatus: 'WATCHING',
        },
      ],
    },
  });
  assert.equal(imported.ok, true);
});

test('normalizes absent or invalid optional library preferences', () => {
  assert.deepEqual(
    decodePreferences({
      ok: true,
      data: {
        preferences: {
          locale: 'zh-CN',
          'library.view': null,
          'library.sort': null,
          'library.sortDirection': null,
          'audio.playbackRate': null,
          'kindle.email': null,
        },
      },
    }),
    {
      ok: true,
      value: { view: 'grid', sort: 'recent_read', direction: 'desc' },
    },
  );
});
