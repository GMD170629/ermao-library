import { expect, test, type Page } from '@playwright/test';
import { readerV5ProgressKey } from '../lib/reader/v5-storage';

const epubResource = {
  id: 'resource-epub', bookId: 'book-1', sourceNodeId: 'epub-node', title: 'EPUB resource', description: '',
  resourceIndex: 1, sortOrder: 0, format: 'EPUB', readerType: 'reflowable',
  importStatus: 'READY', coverUrl: '', sizeBytes: 1024, progress: 10, hidden: false, readable: true,
  kindleSendAvailable: false, assets: []
};

const secondEpubResource = {
  ...epubResource,
  id: 'resource-epub-2',
  sourceNodeId: 'epub-node-2',
  title: 'Second EPUB resource',
  sortOrder: 1
};

const audioResource = {
  ...epubResource,
  id: 'resource-audio',
  sourceNodeId: 'audio-node',
  title: 'Audio resource',
  format: 'AUDIO',
  readerType: 'audio',
  progress: 0
};

async function mockBookDetailApi(page: Page, resources = [epubResource], directoryAnchors = false) {
  await page.route('**/api/**', async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname.endsWith('/api/auth/me')) {
      await route.fulfill({ json: { ok: true, data: { user: { id: 'detail-user', email: 'detail@example.com', name: 'Detail user', role: 'admin' }, authorization: { isAdmin: true, canManageSystem: true, allLibraryScopes: true, libraryIds: [], canViewManualImports: true, authzVersion: 1 } } } });
      return;
    }
    if (url.pathname.endsWith('/api/shelves')) {
      await route.fulfill({ json: { ok: true, data: { shelves: [] } } });
      return;
    }
    if (url.pathname.endsWith('/api/books/book-1/contents')) {
      const entries = resources.map((resource, index) => ({ sourceNodeId: resource.sourceNodeId, parentSourceNodeId: 'book-node', name: directoryAnchors ? resource.title : `book-${index + 1}.epub`, title: resource.title, kind: directoryAnchors ? 'FOLDER' : 'FILE', physicalKind: directoryAnchors ? 'DIRECTORY' : 'REGULAR_FILE', observedAt: '2026-08-23T00:00:00Z', hasChildren: false, resourceId: resource.id, representativeResourceId: resource.id, coverUrl: null }));
      await route.fulfill({ json: { ok: true, data: { bookId: 'book-1', currentSourceNodeId: 'book-node', currentResourceId: null, currentResourceIds: resources.map((resource) => resource.id), parentSourceNodeId: null, breadcrumbs: [], entries, page: 1, pageSize: 100, total: entries.length, totalPages: 1 } } });
      return;
    }
    if (url.pathname.endsWith('/api/books/book-1/resources/resource-epub/reading-units')) {
      const pageNumber = Number(url.searchParams.get('page') ?? 1);
      const firstIndex = (pageNumber - 1) * 50;
      const count = pageNumber === 1 ? 50 : 1;
      const units = Array.from({ length: count }, (_, offset) => {
        const index = firstIndex + offset + 1;
        return { id: `chapter-${index}`, unitType: 'chapter', title: `Chapter ${index}`, navigationKey: `chapter-${index - 1}`, href: `chapter-${index}.xhtml`, sortOrder: index - 1, assetId: null, pageNumber: null, mediaType: 'application/xhtml+xml', previewUrl: null, level: index === 51 ? 1 : 0, durationMs: null, discNumber: null, trackNumber: null, metadataJson: '{}' };
      });
      await route.fulfill({ json: { ok: true, data: { bookId: 'book-1', resourceId: 'resource-epub', units, page: { page: pageNumber, pageSize: 50, total: 51, totalPages: 2 }, currentHref: 'chapter-2.xhtml', currentChapterIndex: 1, currentChapterTitle: 'Chapter 2', currentChapterSortOrder: 1, chapterCount: 51, currentPageNumber: null, progress: 10 } } });
      return;
    }
    if (url.pathname.endsWith('/api/books/book-1')) {
      await route.fulfill({ json: { ok: true, data: { book: { id: 'book-1', sourceNodeId: 'book-node', title: 'Resource detail book', author: 'Author', resources } } } });
      return;
    }
    await route.fulfill({ json: { ok: true, data: {} } });
  });
}

test.beforeEach(async ({ context, page }) => {
  await context.addCookies([{ name: 'shuku_session', value: 'resource-detail-session', domain: '127.0.0.1', path: '/' }]);
  await mockBookDetailApi(page);
});

test('a single readable resource opens its paginated detail by default and survives refresh', async ({ page }) => {
  await page.goto('/books/book-1?returnTo=%2Flibrary%3Fstatus%3DREADING');
  await expect(page).toHaveURL(/resourceId=resource-epub/);
  await expect(page).toHaveURL(/resourcePage=1/);
  await expect(page.getByRole('heading', { name: '章节', exact: true })).toBeVisible();
  const currentChapter = page.getByRole('button', { name: /^2 Chapter 2 (正在阅读|Reading)$/ });
  await expect(currentChapter).toBeVisible();
  await expect(page.getByRole('button', { name: /^1 Chapter 1 (已读|Read)$/ })).toContainText(/已读|Read/);

  await page.getByRole('button', { name: '下一页' }).click();
  await expect(page).toHaveURL(/resourcePage=2/);
  await expect(page.getByText('Chapter 51', { exact: true })).toBeVisible();
  await page.reload();
  await expect(page).toHaveURL(/resourcePage=2/);
  await expect(page.getByText('Chapter 51', { exact: true })).toBeVisible();

  await expect(page.getByRole('button', { name: '返回图书内容' })).toHaveCount(0);
});

test('local audio progress updates without refetching static reading units', async ({ page }) => {
  await page.unroute('**/api/**');
  await mockBookDetailApi(page, [audioResource]);
  let readingUnitsRequests = 0;
  await page.route(/\/api\/books\/book-1\/resources\/resource-audio\/reading-units(?:\?|$)/, async (route) => {
    readingUnitsRequests += 1;
    if (readingUnitsRequests > 1) {
      await route.abort('internetdisconnected');
      return;
    }
    await route.fulfill({ json: { ok: true, data: {
      bookId: 'book-1',
      resourceId: 'resource-audio',
      units: [{
        id: 'track-1', unitType: 'track', title: 'Track 1', sortOrder: 0,
        assetId: 'audio-asset-1', mediaType: 'audio/mpeg', durationMs: 30_067,
        discNumber: null, trackNumber: 1
      }],
      page: { page: 1, pageSize: 50, total: 1, totalPages: 1 },
      currentHref: '/api/assets/audio-asset-1',
      currentChapterIndex: null,
      currentChapterTitle: null,
      currentChapterSortOrder: null,
      chapterCount: null,
      currentPageNumber: null,
      progress: 0
    } } });
  });

  await page.goto('/books/book-1?resourceId=resource-audio&resourcePage=1');
  await expect(page).toHaveURL(/resourceId=resource-audio/);
  await expect(page).toHaveURL(/resourcePage=1/);
  await expect(page.getByRole('heading', { name: '音轨', exact: true })).toBeVisible();
  await expect(page.getByText('共 1 条音轨', { exact: true })).toBeVisible();
  await expect(page.getByText('Track 1', { exact: true })).toBeVisible();
  expect(readingUnitsRequests).toBe(1);

  const progressIdentity = {
    serverIdentity: new URL(page.url()).origin,
    userId: 'detail-user',
    clientId: 'web_audio-progress-client',
    bookId: 'book-1',
    resourceId: 'resource-audio'
  };
  const progressEvent = {
    ...progressIdentity,
    key: readerV5ProgressKey(progressIdentity),
    schemaVersion: 5,
    mutationId: '2cc96594-e5f0-4775-b293-3b04c7275ce7',
    capturedAtEpochMillis: 1_788_736_454_945,
    position: {
      locator: {
        href: '/api/assets/audio-asset-1',
        type: 'audio/mpeg',
        locations: { position: 1, progression: 0.16629527388831608, time: 5, totalProgression: 0.16629527388831608 }
      },
      presentation: {
        displayPercent: 16.629527388831608,
        totalProgression: 0.16629527388831608,
        currentHref: '/api/assets/audio-asset-1',
        chapter: null,
        page: null,
        playback: { positionMillis: 5_000, durationMillis: 30_067 }
      }
    }
  };
  await page.evaluate((detail) => {
    window.dispatchEvent(new CustomEvent('shuku:reader-v5-progress-changed', { detail }));
  }, progressEvent);

  await expect(page.getByText('17%', { exact: true })).toBeVisible();
  await expect(page.getByText('0:05', { exact: true })).toBeVisible();
  await page.waitForTimeout(100);
  expect(readingUnitsRequests).toBe(1);
  await expect(page.getByText('共 1 条音轨', { exact: true })).toBeVisible();
  await expect(page.getByText('Track 1', { exact: true })).toBeVisible();
  await expect(page.getByText('Failed to fetch', { exact: true })).toHaveCount(0);
  await expect(page).toHaveURL(/resourceId=resource-audio/);
  await expect(page).toHaveURL(/resourcePage=1/);
});

test('detail volume cover requests the small variant and uses compact dimensions', async ({ page }) => {
  const coverRequests: string[] = [];
  page.on('request', (request) => {
    if (new URL(request.url()).pathname.includes('/cover')) coverRequests.push(request.url());
  });

  await page.goto('/books/book-1?resourceId=resource-epub&resourcePage=1');

  const cover = page.locator('[data-book-cover="true"]').first();
  const expectedInitialWidth = await page.evaluate(() => window.innerWidth >= 640 ? '150px' : '96px');
  await expect(cover).toHaveCSS('width', expectedInitialWidth);
  await expect.poll(() => coverRequests.some((url) => url.includes('size=small'))).toBe(true);

  await page.setViewportSize({ width: 390, height: 844 });
  await expect(cover).toHaveCSS('width', '96px');
});

test('multiple readable resources still open from their cards and can return to book contents', async ({ page }) => {
  await page.unroute('**/api/**');
  await mockBookDetailApi(page, [epubResource, secondEpubResource]);
  await page.goto('/books/book-1?returnTo=%2Flibrary%3Fstatus%3DREADING');
  await expect(page).not.toHaveURL(/resourceId=/);
  await page.getByRole('button', { name: /可读资源 1/ }).first().click();
  await expect(page).toHaveURL(/resourceId=resource-epub/);
  await expect(page.getByRole('heading', { name: '章节', exact: true })).toBeVisible();

  await page.getByRole('button', { name: '返回图书内容' }).click();
  await expect(page).not.toHaveURL(/resourceId=/);
  await expect(page).toHaveURL(/returnTo=%2Flibrary%3Fstatus%3DREADING/);
  await expect(page.getByRole('button', { name: /可读资源 1/ }).first()).toBeVisible();
});

test('directory-anchored audiobook resources open directly without a folder drill-down', async ({ page }) => {
  await page.unroute('**/api/**');
  await mockBookDetailApi(page, [epubResource, secondEpubResource], true);
  await page.goto('/books/book-1');

  await expect(page.getByRole('button', { name: /打开来源目录/ })).toHaveCount(0);
  await page.getByRole('button', { name: /可读资源 1/ }).first().click();
  await expect(page).toHaveURL(/resourceId=resource-epub/);
});
