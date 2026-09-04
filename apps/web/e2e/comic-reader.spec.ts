import { expect, test, type Page, type Route } from '@playwright/test';
import sharp from 'sharp';

const PAGE_COLORS = [
  { r: 48, g: 96, b: 224, alpha: 1 },
  { r: 240, g: 128, b: 32, alpha: 1 }
] as const;
let comicPages: Buffer[] = [];

test.beforeAll(async () => {
  comicPages = await Promise.all(PAGE_COLORS.map((background) => sharp({
    create: { width: 320, height: 480, channels: 4, background }
  }).png().toBuffer()));
});

test.beforeEach(async ({ context }) => {
  await context.addCookies([{ name: 'shuku_session', value: 'comic-e2e-session', domain: '127.0.0.1', path: '/' }]);
});

function bootstrap() {
  const resource = {
    id: 'comic-resource', bookId: 'comic-book', title: '全本', resourceIndex: null,
    sortOrder: 0, format: 'IMAGE_DIR', readerType: 'comic', pageCount: 2,
    chapterCount: null, durationMs: null, trackCount: null, progress: 0,
    resourceCompleted: false, lastReadAt: null
  };
  return { ok: true, data: {
    schemaVersion: 5, userId: 'user-e2e', readerType: 'comic', sourceFormat: 'image_dir',
    resourceUrl: '/api/reader/v5/resources/comic-resource/publication',
    publication: {
      kind: 'comic',
      manifestUrl: '/api/reader/v5/resources/comic-resource/comic/manifest',
      pageUrlTemplate: '/api/reader/v5/resources/comic-resource/comic/pages/{pageIndex}',
      imageVariants: ['original', 'data-saver']
    },
    book: { id: 'comic-book', title: 'Comic E2E', author: 'Test', coverUrl: null },
    resourceCompleted: false,
    resource,
    availableResources: [resource],
    assets: [0, 1].map((pageIndex) => ({
      id: `page-${pageIndex}`, title: `Page ${pageIndex + 1}`,
      resourceId: 'comic-resource', sourceNodeId: `page-source-${pageIndex}`,
      role: 'PAGE', mimeType: 'image/png', sizeBytes: comicPages[pageIndex].length,
      durationMs: null, discNumber: null, trackNumber: null,
      sortOrder: pageIndex, url: `/api/assets/page-${pageIndex}`
    })),
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
    schemaVersion: 2, kind: 'comic', resourceId: 'comic-resource',
    revision: `sha256:${'b'.repeat(64)}`, sourceFormat: 'image_dir',
    pageCount: 2,
    readingOrder: [0, 1].map((pageIndex) => ({
      pageIndex, resourceHref: `pages/${pageIndex}`, title: `Page ${pageIndex + 1}`,
      mediaType: 'image/png', width: 320, height: 480, sizeBytes: comicPages[pageIndex].length
    }))
  } };
}

async function installRoutes(page: Page) {
  const writes: unknown[] = [];
  const requests: string[] = [];
  let releaseSecondPage!: () => void;
  const secondPageReleased = new Promise<void>((resolve) => { releaseSecondPage = resolve; });
  await page.route('**/api/**', async (route: Route) => {
    const request = route.request();
    const pathname = new URL(request.url()).pathname;
    requests.push(pathname);
    if (pathname.endsWith('/bootstrap')) return route.fulfill({ json: bootstrap() });
    if (pathname.endsWith('/comic/manifest')) return route.fulfill({ json: manifest() });
    if (pathname.endsWith('/comic/pages/0')) {
      return route.fulfill({ contentType: 'image/png', body: comicPages[0] });
    }
    if (pathname.endsWith('/comic/pages/1')) {
      await secondPageReleased;
      return route.fulfill({ contentType: 'image/png', body: comicPages[1] });
    }
    if (pathname.endsWith('/progress')) {
      if (request.method() === 'GET') {
        return route.fulfill({ json: { ok: true, data: { schemaVersion: 5, progressSnapshot: null } } });
      }
      const body: unknown = request.postDataJSON();
      writes.push(body);
      const item = body as { clientId: string; mutationId: string; capturedAtEpochMillis: number; position: Record<string, unknown> };
      return route.fulfill({ json: { ok: true, data: {
        acceptedMutationId: item.mutationId,
        acceptedRevision: 1,
        currentSnapshot: {
          schemaVersion: 5,
          revision: 1,
          clientId: item.clientId,
          mutationId: item.mutationId,
          capturedAtEpochMillis: item.capturedAtEpochMillis,
          receivedAtEpochMillis: Date.now(),
          position: item.position
        }
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
  return { writes, requests, releaseSecondPage };
}

test('IMAGE_DIR comic paging streams PAGE images, avoids assets, and returns from page two to page zero', async ({ page }) => {
  const { writes, requests, releaseSecondPage } = await installRoutes(page);
  await page.goto('/reader/comic-resource', { waitUntil: 'domcontentloaded' });
  await expect(page.locator('[data-reader-shell="v3"]')).toBeVisible();
  await expect(page.locator('[data-comic-view="true"] [data-comic-page-index="0"]')).toBeVisible();
  await expect.poll(() => requests.filter((pathname) => pathname.endsWith('/comic/pages/0')).length).toBeGreaterThan(0);
  await expectComicPixel(page, 0, [48, 96, 224, 255]);

  await page.keyboard.press('ArrowRight');

  const currentPage = page.locator('[data-comic-view="true"] [data-comic-page-index="1"]');
  await expect(currentPage).toBeVisible();
  await expect(currentPage.locator('[data-comic-page-placeholder="1"]')).toHaveText('加载中');
  await expect.poll(() => writes.length, { timeout: 10_000 }).toBeGreaterThan(0);
  const write = writes.at(-1) as { position: { locator: { href: string; locations: { position: number } } } };
  expect(write.position.locator).toMatchObject({ href: 'pages/1', locations: { position: 2 } });

  releaseSecondPage();
  await expect(currentPage.locator('img')).toHaveCSS('visibility', 'visible');
  await expect(currentPage.locator('[data-comic-page-placeholder="1"]')).toHaveCount(0);
  await expectComicPixel(page, 1, [240, 128, 32, 255]);

  await page.keyboard.press('Home');
  const firstPage = page.locator('[data-comic-view="true"] [data-comic-page-index="0"]');
  await expect(firstPage).toBeVisible();
  await expect(firstPage.locator('img')).toHaveCSS('visibility', 'visible');
  await expectComicPixel(page, 0, [48, 96, 224, 255]);
  await expect.poll(
    () => writes.some((body) => (body as { position?: { locator?: { locations?: { position?: number } } } }).position?.locator?.locations?.position === 1)
  ).toBe(true);
  expect(requests.some((pathname) => pathname.includes('/api/assets/'))).toBe(false);
});

async function expectComicPixel(page: Page, pageIndex: number, expected: [number, number, number, number]) {
  const image = page.locator(`[data-comic-view="true"] [data-comic-page-index="${pageIndex}"] img`);
  await expect(image).toHaveJSProperty('naturalWidth', 320);
  await expect(image).toHaveJSProperty('naturalHeight', 480);
  await expect.poll(async () => image.evaluate((element) => {
    const source = element as HTMLImageElement;
    const canvas = document.createElement('canvas');
    canvas.width = 1;
    canvas.height = 1;
    const context = canvas.getContext('2d');
    if (!context || source.naturalWidth !== 320 || source.naturalHeight !== 480) return null;
    context.drawImage(source, 0, 0, 1, 1);
    return Array.from(context.getImageData(0, 0, 1, 1).data);
  })).toEqual(expected);
}
