import { readFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { expect, test, type Page, type Route } from '@playwright/test';

type ReflowableFixture = Readonly<{
  format: 'epub' | 'txt' | 'fb2' | 'mobi' | 'azw' | 'azw3' | 'prc';
  mimeType: string;
  path: string;
}>;

const fixtures: readonly ReflowableFixture[] = [
  { format: 'epub', mimeType: 'application/epub+zip', path: 'test-data/library/epub/reader-v2.epub' },
  { format: 'txt', mimeType: 'text/plain', path: 'test-data/library/novels/starship-library.txt' },
  { format: 'fb2', mimeType: 'application/x-fictionbook+xml', path: 'apps/web/e2e/fixtures/reader-contract-valid.fb2' },
  { format: 'mobi', mimeType: 'application/x-mobipocket-ebook', path: 'test-data/library/mobi/01-basic-mobi6.mobi' },
  { format: 'azw', mimeType: 'application/vnd.amazon.ebook', path: 'test-data/library/mobi/13-basic.azw' },
  { format: 'azw3', mimeType: 'application/vnd.amazon.ebook', path: 'test-data/library/mobi/03-css.azw3' },
  { format: 'prc', mimeType: 'application/x-mobipocket-ebook', path: 'test-data/library/mobi/12-basic.prc' }
];

test.beforeEach(async ({ context }) => {
  await context.addCookies([{
    name: 'shuku_session',
    value: 'local-original-e2e',
    domain: '127.0.0.1',
    path: '/'
  }]);
});

function bootstrap(fixture: ReflowableFixture, sizeBytes: number) {
  const resourceId = `${fixture.format}-local-resource`;
  const assetId = `${fixture.format}-local-asset`;
  const format = fixture.format.toUpperCase();
  const resource = {
    id: resourceId,
    bookId: 'local-formats-book',
    title: format,
    resourceIndex: null,
    sortOrder: 0,
    format,
    readerType: 'reflowable',
    pageCount: null,
    chapterCount: null,
    durationMs: null,
    trackCount: null,
    progress: 0,
    resourceCompleted: false,
    lastReadAt: null
  };
  return { ok: true, data: {
    schemaVersion: 4,
    userId: 'local-formats-user',
    readerType: 'reflowable',
    sourceFormat: fixture.format,
    book: { id: 'local-formats-book', title: `Local ${format}`, author: 'Fixture', coverUrl: null },
    resource,
    resourceCompleted: false,
    availableResources: [resource],
    assets: [{
      id: assetId,
      kind: 'CONTENT',
      mimeType: fixture.mimeType,
      sizeBytes,
      durationMs: null,
      discNumber: null,
      trackNumber: null,
      sortOrder: 0,
      url: `/api/assets/${assetId}`
    }],
    units: [],
    capabilities: {
      canGoNext: true,
      canGoPrevious: false,
      canJumpToProgress: false,
      canJumpToHref: true,
      canJumpToIndex: true,
      canZoom: false,
      canSelectText: true,
      supportsPagination: true,
      supportsScrolling: true,
      supportsSpreads: true
    },
    progressSnapshot: null,
    progressPercent: 0
  } };
}

async function installFixtureRoutes(
  page: Page,
  fixture: ReflowableFixture,
  bytes: Buffer,
  requests: string[]
): Promise<void> {
  const resourceId = `${fixture.format}-local-resource`;
  const assetId = `${fixture.format}-local-asset`;
  const version = `${bytes.byteLength}:1234`;
  await page.route('**/api/**', async (route: Route) => {
    const request = route.request();
    const pathname = new URL(request.url()).pathname;
    requests.push(pathname);
    if (pathname.endsWith('/bootstrap')) return route.fulfill({ json: bootstrap(fixture, bytes.byteLength) });
    if (pathname === `/api/resources/${resourceId}`) return route.fulfill({ json: { ok: true, data: { resource: {
      id: resourceId,
      bookId: 'local-formats-book',
      sourceNodeId: `${resourceId}-source`,
      title: fixture.format.toUpperCase(),
      format: fixture.format.toUpperCase(),
      readerType: 'reflowable',
      sortOrder: 0,
      importStatus: 'READY',
      coverUrl: '',
      sizeBytes: bytes.byteLength,
      readable: true,
      kindleSendAvailable: false,
      assets: [{
        id: assetId,
        title: `Original ${fixture.format}`,
        resourceId,
        sourceNodeId: `${assetId}-source`,
        role: 'PRIMARY',
        mimeType: fixture.mimeType,
        sourceFormat: fixture.format.toUpperCase(),
        sizeBytes: bytes.byteLength,
        size: `${bytes.byteLength} B`,
        mtimeMs: 1234,
        sortOrder: 0,
        url: `/api/assets/${assetId}`,
        downloadUrl: `/api/assets/${assetId}?download=true`
      }]
    } } } });
    if (pathname === `/api/assets/${assetId}`) {
      expect(request.headers()['x-asset-version']).toBe(version);
      return route.fulfill({
        status: 200,
        contentType: fixture.mimeType,
        headers: { 'Content-Length': String(bytes.byteLength), 'X-Asset-Version': version },
        body: bytes
      });
    }
    if (pathname.endsWith('/bookmarks')) {
      return route.fulfill({ json: { ok: true, data: { bookmarks: [] } } });
    }
    if (pathname.endsWith('/progress')) {
      return request.method() === 'GET'
        ? route.fulfill({ headers: { ETag: '"reader-progress-0"' }, json: { ok: true, data: { schemaVersion: 4, progressSnapshot: null } } })
        : route.fulfill({ json: { ok: true, data: {
          schemaVersion: 4,
          clientId: 'web-e2e',
          revision: 1,
          locator: request.postDataJSON().locator,
          displayPercent: 0,
          receivedAtEpochMillis: Date.now()
        } } });
    }
    if (pathname === '/api/auth/me') return route.fulfill({ json: { ok: true, data: {
      user: { id: 'local-formats-user', email: 'formats@example.com', name: 'Formats', role: 'admin' },
      authorization: {
        isAdmin: true,
        canManageSystem: true,
        allLibraryScopes: true,
        libraryIds: [],
        canViewManualImports: true,
        authzVersion: 1
      }
    } } });
    return route.fulfill({ json: { ok: true, data: {} } });
  });
}

async function visibleReaderFrame(page: Page) {
  const shell = page.locator('[data-reader-shell="v3"]');
  await expect(shell).toBeVisible();
  const frame = shell.locator('iframe:visible').first();
  const error = shell.locator('[data-reader-error-code]');
  await Promise.race([
    frame.waitFor({ state: 'visible', timeout: 20_000 }),
    error.waitFor({ state: 'visible', timeout: 20_000 })
  ]);
  if (await error.isVisible()) {
    throw new Error(`LOCAL_READER_OPEN_FAILED:${await error.getAttribute('data-reader-error-code') ?? 'UNKNOWN'}`);
  }
  return frame;
}

for (const fixture of fixtures) {
  test(`${fixture.format.toUpperCase()} opens its original locally with TOC, positions and jumps`, async ({ page }) => {
    const bytes = await readFile(resolve(process.cwd(), '../..', fixture.path));
    const requests: string[] = [];
    await installFixtureRoutes(page, fixture, bytes, requests);
    await page.goto(`/reader/${fixture.format}-local-resource`);
    let frame = await visibleReaderFrame(page);
    await expect.poll(async () => frame.contentFrame().locator('body').innerText().then((text) => text.trim().length), {
      timeout: 30_000
    }).toBeGreaterThan(5);

    const frameBounds = await frame.boundingBox();
    if (!frameBounds) throw new Error('LOCAL_READER_FRAME_BOUNDS_MISSING');
    await page.mouse.click(frameBounds.x + frameBounds.width / 2, frameBounds.y + frameBounds.height / 2);
    await page.getByRole('button', { name: '目录' }).click();
    const chapterSection = page.locator('[data-reader-panel-surface="true"] section').filter({ hasText: '章节' }).last();
    const chapterButtons = chapterSection.locator('button');
    await expect(chapterButtons).not.toHaveCount(0);
    await chapterButtons.last().click();

    frame = await visibleReaderFrame(page);
    const updatedBounds = await frame.boundingBox();
    if (!updatedBounds) throw new Error('LOCAL_READER_FRAME_BOUNDS_MISSING');
    await page.mouse.click(updatedBounds.x + updatedBounds.width / 2, updatedBounds.y + updatedBounds.height / 2);
    const progress = page.locator('input[aria-label="阅读进度"]:visible');
    await expect(progress).toHaveAttribute('step', '0.1');
    await progress.fill('67');
    await expect.poll(async () => Number(await progress.inputValue()), { timeout: 10_000 }).toBeGreaterThan(0);

    expect(requests.filter((path) => path === `/api/assets/${fixture.format}-local-asset`)).toHaveLength(1);
    expect(requests.filter((path) => /\/publication\/(?:manifest|positions|chapter)/.test(path))).toEqual([]);
  });
}

for (const invalid of [
  { name: 'corrupt', path: 'test-data/library/mobi/negative-truncated.mobi', expectedCode: /^(?:MOBI|PUBLICATION)_/ },
  { name: 'DRM-protected', path: 'test-data/library/mobi/negative-upstream-drm-v1.mobi', expectedCode: /DRM/ }
] as const) {
  test(`MOBI ${invalid.name} original fails closed without a remote publication fallback`, async ({ page }) => {
    const fixture: ReflowableFixture = {
      format: 'mobi',
      mimeType: 'application/x-mobipocket-ebook',
      path: invalid.path
    };
    const bytes = await readFile(resolve(process.cwd(), '../..', invalid.path));
    const requests: string[] = [];
    await installFixtureRoutes(page, fixture, bytes, requests);
    await page.goto('/reader/mobi-local-resource');

    const shell = page.locator('[data-reader-shell="v3"]');
    const error = shell.locator('[data-reader-error-code]');
    await expect(error).toBeVisible();
    await expect(error).toHaveAttribute('data-reader-error-code', invalid.expectedCode);
    await expect(shell.locator('iframe')).toHaveCount(0);
    expect(requests.filter((path) => path === '/api/assets/mobi-local-asset')).toHaveLength(1);
    expect(requests.filter((path) => /\/publication\/(?:manifest|positions|chapter)/.test(path))).toEqual([]);
  });
}
