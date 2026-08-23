import { expect, test, type Page } from '@playwright/test';

const epubResource = {
  id: 'resource-epub', bookId: 'book-1', sourceNodeId: 'epub-node', title: 'EPUB resource', description: '',
  resourceIndex: 1, sortOrder: 0, format: 'EPUB', readerType: 'reflowable',
  classification: { source: 'AUTO', reason: 'FORMAT_DEFAULT', suggestedMediaKind: 'EBOOK' },
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

async function mockBookDetailApi(page: Page, resources = [epubResource]) {
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
      const entries = resources.map((resource, index) => ({ sourceNodeId: resource.sourceNodeId, parentSourceNodeId: 'book-node', name: `book-${index + 1}.epub`, title: resource.title, kind: 'FILE', physicalKind: 'REGULAR_FILE', observedAt: '2026-08-23T00:00:00Z', hasChildren: false, resourceId: resource.id, representativeResourceId: null, coverUrl: null }));
      await route.fulfill({ json: { ok: true, data: { bookId: 'book-1', currentSourceNodeId: 'book-node', currentResourceId: null, currentResourceIds: resources.map((resource) => resource.id), parentSourceNodeId: null, breadcrumbs: [], entries, page: 1, pageSize: 100, total: entries.length, totalPages: 1 } } });
      return;
    }
    if (url.pathname.endsWith('/api/books/book-1/resources/resource-epub/reading-units')) {
      const pageNumber = Number(url.searchParams.get('page') ?? 1);
      const firstIndex = (pageNumber - 1) * 50;
      const count = pageNumber === 1 ? 50 : 1;
      const units = Array.from({ length: count }, (_, offset) => {
        const index = firstIndex + offset + 1;
        return { id: `chapter-${index}`, unitType: 'chapter', title: `Chapter ${index}`, href: `chapter-${index}.xhtml`, sortOrder: index - 1, assetId: null, pageNumber: null, mediaType: 'application/xhtml+xml', previewUrl: null, level: index === 51 ? 1 : 0, durationMs: null, discNumber: null, trackNumber: null, metadataJson: '{}' };
      });
      await route.fulfill({ json: { ok: true, data: { bookId: 'book-1', resourceId: 'resource-epub', units, page: { page: pageNumber, pageSize: 50, total: 51, totalPages: 2 }, currentHref: 'chapter-2.xhtml', currentChapterIndex: null, currentChapterTitle: null, currentChapterSortOrder: null, currentPageNumber: null, progress: 10 } } });
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
  const currentChapter = page.getByText('Chapter 2', { exact: true });
  await expect(currentChapter).toBeVisible();
  await expect(currentChapter.locator('xpath=ancestor::button')).toContainText(/正在阅读|Reading/);
  await expect(page.getByText('Chapter 1', { exact: true }).locator('xpath=ancestor::button')).toContainText(/已读|Read/);

  await page.getByRole('button', { name: '下一页' }).click();
  await expect(page).toHaveURL(/resourcePage=2/);
  await expect(page.getByText('Chapter 51', { exact: true })).toBeVisible();
  await page.reload();
  await expect(page).toHaveURL(/resourcePage=2/);
  await expect(page.getByText('Chapter 51', { exact: true })).toBeVisible();

  await expect(page.getByRole('button', { name: '返回图书内容' })).toHaveCount(0);
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
