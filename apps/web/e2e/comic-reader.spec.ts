import { expect, test, type Page, type Route } from '@playwright/test';

test.beforeEach(async ({ context }) => {
  await context.addCookies([{ name: 'shuku_session', value: 'comic-e2e-session', domain: '127.0.0.1', path: '/' }]);
});

const comicPage = (label: string) => `
  <svg xmlns="http://www.w3.org/2000/svg" width="600" height="900">
    <rect width="600" height="900" fill="#eee8df"/>
    <text x="300" y="450" text-anchor="middle" font-size="48">${label}</text>
  </svg>
`;

function bootstrap() {
  const resource = {
    id: 'comic-resource', bookId: 'comic-book', title: '全本', resourceIndex: null,
    sortOrder: 0, format: 'CBZ', readerType: 'comic', pageCount: 2,
    chapterCount: null, durationMs: null, trackCount: null, progress: 0,
    resourceCompleted: false, lastReadAt: null
  };
  return { ok: true, data: {
    schemaVersion: 4, userId: 'user-e2e', readerType: 'comic', sourceFormat: 'cbz',
    publication: {
      kind: 'comic',
      manifestUrl: '/api/reader/v4/resources/comic-resource/comic/manifest',
      pageUrlTemplate: '/api/reader/v4/resources/comic-resource/comic/pages/{pageIndex}',
      imageVariants: ['original', 'data-saver']
    },
    book: { id: 'comic-book', title: 'Comic E2E', author: 'Test', coverUrl: null },
    resourceCompleted: false,
    resource,
    availableResources: [resource],
    assets: [{
      id: 'comic-asset', kind: 'CONTENT', mimeType: 'application/vnd.comicbook+zip',
      sizeBytes: 100, durationMs: null, discNumber: null, trackNumber: null,
      sortOrder: 0, url: '/api/assets/comic-asset'
    }],
    units: [],
    capabilities: {
      canGoNext: true, canGoPrevious: false, canJumpToProgress: true,
      canJumpToHref: false, canJumpToIndex: true, canZoom: true,
      canSelectText: false, supportsPagination: true, supportsScrolling: true,
      supportsSpreads: true
    },
    progressSnapshot: null,
    progressPercent: 0
  } };
}

function manifest() {
  return { ok: true, data: {
    schemaVersion: 1, kind: 'comic', resourceId: 'comic-resource', sourceFormat: 'cbz',
    pageCount: 2,
    readingOrder: [0, 1].map((pageIndex) => ({
      pageIndex, resourceHref: `pages/${pageIndex}`, title: `Page ${pageIndex + 1}`,
      mediaType: 'image/svg+xml', width: 600, height: 900, sizeBytes: 100
    }))
  } };
}

async function installRoutes(page: Page) {
  const writes: unknown[] = [];
  let releaseSecondPage!: () => void;
  const secondPageReleased = new Promise<void>((resolve) => { releaseSecondPage = resolve; });
  await page.route('**/api/**', async (route: Route) => {
    const request = route.request();
    const pathname = new URL(request.url()).pathname;
    if (pathname.endsWith('/bootstrap')) return route.fulfill({ json: bootstrap() });
    if (pathname.endsWith('/comic/manifest')) return route.fulfill({ json: manifest() });
    if (pathname.endsWith('/comic/pages/0')) {
      return route.fulfill({ contentType: 'image/svg+xml', body: comicPage('1') });
    }
    if (pathname.endsWith('/comic/pages/1')) {
      await secondPageReleased;
      return route.fulfill({ contentType: 'image/svg+xml', body: comicPage('2') });
    }
    if (pathname.endsWith('/progress')) {
      if (request.method() === 'GET') {
        return route.fulfill({ json: { ok: true, data: { schemaVersion: 4, progressSnapshot: null } } });
      }
      const body: unknown = request.postDataJSON();
      writes.push(body);
      const item = body as { clientId: string; locator: Record<string, unknown>; baseRevision: number };
      return route.fulfill({ json: { ok: true, data: {
        schemaVersion: 4, clientId: item.clientId, revision: item.baseRevision + 1,
        locator: item.locator, displayPercent: 100, receivedAtEpochMillis: Date.now()
      } } });
    }
    if (pathname === '/api/auth/me') {
      return route.fulfill({ json: { ok: true, data: {
        user: { id: 'user-e2e', email: 'e2e@example.com', name: 'E2E', role: 'admin' },
        authorization: {
          isAdmin: true, canManageSystem: true, allLibraryScopes: true,
          libraryIds: [], canViewManualImports: true, authzVersion: 1
        }
      } } });
    }
    return route.fulfill({ json: { ok: true, data: {} } });
  });
  return { writes, releaseSecondPage };
}

test('comic paging does not wait for the native image load event', async ({ page }) => {
  const { writes, releaseSecondPage } = await installRoutes(page);
  await page.goto('/reader/comic-resource', { waitUntil: 'domcontentloaded' });
  await expect(page.locator('[data-reader-shell="v3"]')).toBeVisible();
  await expect(page.locator('[data-comic-view="true"] [data-comic-page-index="0"]')).toBeVisible();

  await page.keyboard.press('ArrowRight');

  const currentPage = page.locator('[data-comic-view="true"] [data-comic-page-index="1"]');
  await expect(currentPage).toBeVisible();
  await expect(currentPage.locator('[data-comic-page-placeholder="1"]')).toHaveText('加载中');
  await expect.poll(() => writes.length, { timeout: 10_000 }).toBeGreaterThan(0);
  const write = writes.at(-1) as { locator: { kind: string; pageIndex: number; resourceHref: string } };
  expect(write.locator).toMatchObject({ kind: 'comic', pageIndex: 1, resourceHref: 'pages/1' });

  releaseSecondPage();
  await expect(currentPage.locator('img')).toHaveCSS('visibility', 'visible');
  await expect(currentPage.locator('[data-comic-page-placeholder="1"]')).toHaveCount(0);
});
