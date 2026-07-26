import { expect, test, type Page } from '@playwright/test';
import { readFile } from 'node:fs/promises';
import path from 'node:path';

const root = path.resolve(process.cwd(), '../..');
const pdfFixture = path.join(root, 'test-data/library/pdf/reading-notes.pdf');
const epubFixture = path.join(root, 'test-data/library/epub/reader-v2.epub');

const defaultPreferences = {
  schemaVersion: 3,
  appearance: { theme: 'warm' },
  epub: { fontSize: 18, lineHeight: 1.9, pageWidth: 1350, fontFamily: 'pingfang', spreadMode: 'single', pageTurnAnimation: 'slide', flow: 'paginated' },
  comic: { direction: 'ltr', mode: 'single', pageTurnAnimation: 'slide', imageFit: 'width', imageVariant: 'original', zoom: 1 },
  pdf: { zoom: 1, fit: 'width' }
};

function bootstrap(kind: 'epub' | 'comic' | 'pdf', epubUnitCount = 2) {
  const editionId = `${kind}-edition`;
  const volumeId = kind === 'comic' ? 'comic-volume' : null;
  const pageCount = kind === 'comic' ? 3 : kind === 'pdf' ? 7 : null;
  const volumes = volumeId ? [{ id: volumeId, title: '第一卷', index: 1, pageCount: 3, chapterCount: null }] : [];
  return {
    accountId: 'user-e2e',
    target: {
      workId: `work-${kind}`,
      workTitle: `${kind.toUpperCase()} 测试读物`,
      workAuthor: 'Test',
      editionId,
      editionTitle: '默认版本',
      fileId: `${kind}-file`,
      format: kind,
      mediaType: kind === 'pdf' ? 'application/pdf' : kind === 'epub' ? 'application/epub+zip' : 'application/vnd.comicbook+zip',
      resourceUrl: `/api/v2/reading/editions/${editionId}/resource`,
      checksum: `${kind}-fixture-v1`
    },
    progress: null,
    bookmarks: [],
    preference: {
      scope: 'reader',
      targetId: null,
      values: defaultPreferences,
      updatedAt: '2026-07-25T00:00:00Z'
    },
    files: [{
      id: `${kind}-file`,
      editionId,
      volumeId,
      name: `${editionId}.${kind === 'comic' ? 'cbz' : kind}`,
      mediaType: kind === 'pdf' ? 'application/pdf' : kind === 'epub' ? 'application/epub+zip' : 'application/vnd.comicbook+zip',
      sizeBytes: 100,
      sortOrder: 0,
      durationMs: null,
      url: `/api/v2/reading/editions/${editionId}/resource`
    }],
    volumes: volumes.map((volume) => ({
      id: volume.id,
      editionId,
      title: volume.title,
      sortOrder: volume.index - 1,
      pageCount: volume.pageCount,
      durationMs: null
    })),
    units: kind === 'epub' ? Array.from({ length: epubUnitCount }, (_, index) => ({
      index: index + 1,
      title: index === 0 ? '第一章' : index === 1 ? '第二章' : `第 ${index + 1} 章`,
      href: index === 0 ? 'chapter1.xhtml' : index === 1 ? 'chapter2.xhtml' : `chapter${index + 1}.xhtml`
    })) : [],
    pages: kind === 'comic' ? [1, 2, 3].map((pageIndex) => ({
      pageIndex,
      title: `第 ${pageIndex} 页`,
      mimeType: 'image/svg+xml',
      size: 100
    })) : []
  };
}

function progressLocation(body: Record<string, any>) {
  return body.position?.location as Record<string, any> | undefined;
}

async function readerProgressOutbox(page: Page) {
  return page.evaluate(async () => new Promise<Array<Record<string, unknown>>>((resolve, reject) => {
    const request = indexedDB.open('shuku-reader-v2');
    request.onerror = () => reject(request.error ?? new Error('Reader database open failed'));
    request.onsuccess = () => {
      const database = request.result;
      const transaction = database.transaction('progress-outbox', 'readonly');
      const entries = transaction.objectStore('progress-outbox').getAll();
      entries.onerror = () => reject(entries.error ?? new Error('Reader outbox read failed'));
      entries.onsuccess = () => resolve(entries.result as Array<Record<string, unknown>>);
    };
  }));
}

async function mockReaderApi(
  page: Page,
  kind: 'epub' | 'comic' | 'pdf',
  progressBodies: unknown[] = [],
  options: { pdfBody?: Buffer; epubBody?: Buffer; progressStatus?: number; bootstrapDelayMs?: number; epubUnitCount?: number } = {}
) {
  const pdf = kind === 'pdf' ? options.pdfBody ?? await readFile(pdfFixture) : null;
  const epub = kind === 'epub' ? options.epubBody ?? await readFile(epubFixture) : null;
  let sharedEpubLocations: string | null = null;
  await page.route('**/api/**', async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (url.pathname.includes('/api/v2/reading/editions/') && url.pathname.endsWith('/bootstrap')) {
      if (options.bootstrapDelayMs) await new Promise((resolve) => setTimeout(resolve, options.bootstrapDelayMs));
      await route.fulfill({ json: bootstrap(kind, options.epubUnitCount) });
      return;
    }
    if (kind === 'epub' && url.pathname.endsWith('/epub-locations/claim')) {
      await route.fulfill({
        json: sharedEpubLocations
          ? { status: 'ready', serialized: sharedEpubLocations }
          : { status: 'claimed', leaseToken: 'e2e-epub-locations', leaseExpiresAt: Date.now() + 30_000 }
      });
      return;
    }
    if (kind === 'epub' && url.pathname.endsWith('/epub-locations') && request.method() === 'PUT') {
      sharedEpubLocations = request.postDataJSON().serialized;
      await route.fulfill({ json: { status: 'ready', serialized: sharedEpubLocations } });
      return;
    }
    if (url.pathname.includes('/api/v2/reading/editions/') && url.pathname.endsWith('/progress')) {
      const body = request.postDataJSON();
      progressBodies.push(body);
      if (options.progressStatus && options.progressStatus >= 400) {
        await route.fulfill({
          status: options.progressStatus,
          json: {
            type: 'https://shuku.app/problems/unavailable',
            title: 'Service unavailable',
            status: options.progressStatus,
            code: 'SERVICE_UNAVAILABLE',
            detail: '测试中的离线进度暂未同步',
            params: {}
          }
        });
        return;
      }
      await route.fulfill({
        json: {
          editionId: `${kind}-edition`,
          position: body.position,
          percentage: body.percentage,
          version: 1,
          updatedAt: new Date().toISOString()
        }
      });
      return;
    }
    if (url.pathname.endsWith('/resource') && pdf) {
      await route.fulfill({ status: 200, contentType: 'application/pdf', body: pdf });
      return;
    }
    if (url.pathname.endsWith('/resource') && epub) {
      await route.fulfill({ status: 200, contentType: 'application/epub+zip', body: epub });
      return;
    }
    if (/\/api\/v2\/reading\/volumes\/[^/]+\/pages$/.test(url.pathname)) {
      await route.fulfill({
        json: {
          pageCount: 3,
          pages: [1, 2, 3].map((pageIndex) => ({
            pageIndex,
            title: `第 ${pageIndex} 页`,
            mimeType: 'image/svg+xml',
            size: 100
          }))
        }
      });
      return;
    }
    if (/\/api\/v2\/reading\/volumes\/[^/]+\/pages\/\d+$/.test(url.pathname)) {
      const pageNumber = Number(url.pathname.split('/').at(-1));
      const variant = url.searchParams.get('imageVariant') ?? 'original';
      if (variant === 'data-saver') await new Promise((resolve) => setTimeout(resolve, 180));
      await route.fulfill({
        status: 200,
        contentType: 'image/svg+xml',
        body: `<svg xmlns="http://www.w3.org/2000/svg" width="600" height="900"><rect width="100%" height="100%" fill="#eee"/><text x="300" y="450" text-anchor="middle" font-size="60">${pageNumber}-${variant}</text></svg>`
      });
      return;
    }
    if (url.pathname === '/api/v2/account') {
      await route.fulfill({
        json: {
          id: 'user-e2e',
          email: 'e2e@example.com',
          displayName: 'E2E',
          role: 'admin',
          locale: 'zh-CN',
          scopes: ['catalog:read', 'reading:write', 'operations:write'],
          disabled: false,
          monitorFolderIds: [],
          createdAt: '2026-07-25T00:00:00Z'
        }
      });
      return;
    }
    if (url.pathname.endsWith('/bookmarks')) {
      if (request.method() === 'GET') {
        await route.fulfill({ json: { items: [], page: 1, pageSize: 24, total: 0 } });
        return;
      }
      await route.fulfill({
        json: {
          id: 'bookmark-e2e',
          editionId: `${kind}-edition`,
          clientId: request.postDataJSON().clientId,
          label: request.postDataJSON().label ?? null,
          position: request.postDataJSON().position,
          excerpt: null,
          createdAt: '2026-07-25T00:00:00Z',
          updatedAt: '2026-07-25T00:00:00Z'
        }
      });
      return;
    }
    if (url.pathname.includes('/bookmarks/') && request.method() === 'DELETE') {
      await route.fulfill({ status: 204 });
      return;
    }
    await route.fulfill({ json: {} });
  });
}

async function currentEpubIframe(page: Page) {
  await waitForReaderReady(page);
  const epubIframes = page.locator('[data-reader-engine="epub-v2"] iframe');
  await expect(epubIframes.first()).toBeAttached();
  const currentFrameIndex = await epubIframes.evaluateAll((frames) => {
    const viewportCenter = { x: window.innerWidth / 2, y: window.innerHeight / 2 };
    let bestIndex = 0;
    let bestScore = -1;
    frames.forEach((frame, index) => {
      const bounds = frame.getBoundingClientRect();
      const containsCenter = viewportCenter.x >= bounds.left
        && viewportCenter.x <= bounds.right
        && viewportCenter.y >= bounds.top
        && viewportCenter.y <= bounds.bottom;
      const visibleWidth = Math.max(0, Math.min(bounds.right, window.innerWidth) - Math.max(bounds.left, 0));
      const visibleHeight = Math.max(0, Math.min(bounds.bottom, window.innerHeight) - Math.max(bounds.top, 0));
      const score = (containsCenter ? window.innerWidth * window.innerHeight : 0) + visibleWidth * visibleHeight;
      if (score > bestScore) {
        bestScore = score;
        bestIndex = index;
      }
    });
    return bestIndex;
  });
  const epubIframe = epubIframes.nth(currentFrameIndex);
  await expect(epubIframe).toBeVisible();
  return epubIframe;
}

async function showReaderControls(page: Page) {
  await waitForReaderReady(page);
  const shell = page.locator('[data-reader-shell="v2"]');
  const box = await shell.boundingBox();
  if (!box) throw new Error('Reader shell is not visible');
  if (await shell.getAttribute('data-reader-kind') === 'epub') {
    const epubIframe = await currentEpubIframe(page);
    await expect(epubIframe.contentFrame().locator('html')).toHaveAttribute('data-shuku-input-bridge', 'ready');
    const iframeBox = await epubIframe.boundingBox();
    if (!iframeBox) throw new Error('EPUB iframe is not visible');
    const hasTouch = await page.evaluate(() => navigator.maxTouchPoints > 0);
    if (hasTouch) {
      await page.touchscreen.tap(iframeBox.x + iframeBox.width / 2, iframeBox.y + iframeBox.height / 2);
    } else {
      await page.mouse.click(iframeBox.x + iframeBox.width / 2, iframeBox.y + iframeBox.height / 2);
    }
  } else {
    await page.mouse.click(box.x + box.width / 2, box.y + box.height / 2);
  }
  await expect(page.getByRole('button', { name: '阅读设置' })).toBeInViewport();
}

async function expectEpubTextInAnyIframe(page: Page, text: string) {
  await expect.poll(async () => {
    const iframes = page.locator('[data-reader-engine="epub-v2"] iframe');
    const count = await iframes.count();
    for (let index = 0; index < count; index += 1) {
      if (await iframes.nth(index).contentFrame().getByText(text).count()) return true;
    }
    return false;
  }).toBe(true);
}

async function waitForReaderReady(page: Page) {
  await expect.poll(() => page.locator('[data-reader-opening-cover="loading"]').count()).toBe(0);
}

test.beforeEach(async ({ context }) => {
  await context.addCookies([{ name: 'shuku_v2_session', value: 'e2e-session', domain: '127.0.0.1', path: '/' }]);
  await context.addInitScript(() => localStorage.setItem('shuku:pwa:install-dismissed:user-e2e', '1'));
});

test('browser reader uses the dynamic viewport and control overlays keep the canvas stable', async ({ page }) => {
  await mockReaderApi(page, 'comic');
  await page.goto('/reader/comic-edition?volume=comic-volume');
  await expect(page.locator('[data-reader-engine="comic-v2"]')).toBeVisible();
  await expect(page.locator('html')).not.toHaveClass(/pwa-native/);

  const shell = page.locator('[data-reader-shell="v2"]');
  const initialLayout = await shell.evaluate((element) => {
    const shellBounds = element.getBoundingClientRect();
    const viewportElement = element.querySelector<HTMLElement>('[data-reader-viewport="stable"]');
    const viewportBounds = viewportElement?.getBoundingClientRect();
    const paginationContainer = element.querySelector<HTMLElement>('[aria-label$="阅读内容"]');
    const paginationBounds = paginationContainer?.getBoundingClientRect();
    return {
      shell: { top: shellBounds.top, left: shellBounds.left, width: shellBounds.width, height: shellBounds.height },
      viewport: viewportBounds ? { width: viewportBounds.width, height: viewportBounds.height } : null,
      pagination: paginationBounds ? { width: paginationBounds.width, height: paginationBounds.height } : null,
      document: { width: document.documentElement.clientWidth, height: document.documentElement.clientHeight }
    };
  });
  expect(initialLayout.shell).toEqual({ top: 0, left: 0, ...initialLayout.document });
  expect(initialLayout.viewport).not.toBeNull();
  expect(initialLayout.pagination).toEqual(initialLayout.viewport);

  await showReaderControls(page);
  await expect(page.getByRole('button', { name: '阅读设置' })).toBeInViewport();
  const controlsVisibleLayout = await shell.evaluate((element) => {
    const viewportElement = element.querySelector<HTMLElement>('[data-reader-viewport="stable"]');
    const paginationContainer = element.querySelector<HTMLElement>('[aria-label$="阅读内容"]');
    if (!viewportElement || !paginationContainer) return null;
    const viewportBounds = viewportElement.getBoundingClientRect();
    const paginationBounds = paginationContainer.getBoundingClientRect();
    return {
      viewport: { width: viewportBounds.width, height: viewportBounds.height },
      pagination: { width: paginationBounds.width, height: paginationBounds.height }
    };
  });
  expect(controlsVisibleLayout).toEqual({
    viewport: initialLayout.viewport,
    pagination: initialLayout.pagination
  });

  await page.setViewportSize({ width: 900, height: 640 });
  const comicViewport = page.locator('[data-comic-viewport="true"]');
  await expect.poll(() => comicViewport.evaluate((element) => (
    Math.abs(element.scrollLeft - element.clientWidth)
  ))).toBeLessThanOrEqual(1);
  await expect(page.locator('[data-comic-spread-slot="current"]')).toHaveAttribute('data-comic-spread-anchor', '1');
});

test('reader loading and iOS bottom safe area stay on the active warm surface', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await mockReaderApi(page, 'epub', [], { bootstrapDelayMs: 600 });
  await page.goto('/reader/epub-edition');

  const openingCover = page.locator('[data-reader-opening-cover="loading"]');
  await expect(openingCover).toBeVisible();
  await expect(openingCover).toHaveCSS('background-color', 'rgb(253, 246, 234)');
  await expect.poll(() => page.evaluate(() => {
    const themeColors = Array.from(document.querySelectorAll<HTMLMetaElement>('meta[name="theme-color"]')).map((meta) => meta.content);
    return {
      html: getComputedStyle(document.documentElement).backgroundColor,
      body: getComputedStyle(document.body).backgroundColor,
      hasThemeColor: themeColors.length > 0,
      themeColorsMatch: themeColors.every((color) => color === '#FDF6EA')
    };
  })).toEqual({
    html: 'rgb(253, 246, 234)',
    body: 'rgb(253, 246, 234)',
    hasThemeColor: true,
    themeColorsMatch: true
  });

  await waitForReaderReady(page);
  await page.evaluate(() => {
    document.documentElement.style.setProperty('--shuku-safe-area-top', '47px');
    document.documentElement.style.setProperty('--shuku-safe-area-bottom', '34px');
  });
  await showReaderControls(page);
  await page.getByRole('button', { name: '阅读设置' }).click();
  const settingsDialog = page.getByRole('dialog', { name: '阅读设置' });
  await expect(settingsDialog).toBeVisible();
  if (process.env.SHUKU_READER_EPUB_SETTINGS_CAPTURE) {
    await page.screenshot({ path: process.env.SHUKU_READER_EPUB_SETTINGS_CAPTURE });
  }

  const safeAreaCoverage = await settingsDialog.evaluate((element) => {
    const bounds = element.getBoundingClientRect();
    const style = getComputedStyle(element);
    return {
      bottom: bounds.bottom,
      viewportBottom: window.innerHeight,
      cssBottom: style.bottom,
      paddingTop: style.paddingTop,
      paddingBottom: style.paddingBottom,
      maxHeight: style.maxHeight,
      titleInset: element.querySelector<HTMLElement>('#reader-panel-title')!.getBoundingClientRect().top - bounds.top
    };
  });
  expect(safeAreaCoverage.bottom).toBeGreaterThan(safeAreaCoverage.viewportBottom);
  expect(safeAreaCoverage.cssBottom).toBe('-34px');
  expect(safeAreaCoverage.paddingTop).toBe('16px');
  expect(safeAreaCoverage.paddingBottom).toBe('142px');
  expect(safeAreaCoverage.titleInset).toBeGreaterThanOrEqual(15);
  expect(safeAreaCoverage.titleInset).toBeLessThanOrEqual(32);
  expect(Number.parseFloat(safeAreaCoverage.maxHeight)).toBeGreaterThan(844 * 0.82);

  const bottomControls = page.locator('[data-reader-controller="bottom-console"]');
  for (const [triggerName, dialogName] of [
    ['目录', '目录'],
    ['书签', '书签'],
    ['标注与批注', '标注与批注']
  ] as const) {
    await bottomControls.getByRole('button', { name: triggerName, exact: true }).click();
    const dialog = page.getByRole('dialog', { name: dialogName });
    await expect(dialog).toBeVisible();
    await expect.poll(() => dialog.evaluate((element) => getComputedStyle(element).paddingTop)).toBe('16px');
  }
});

test('mobile EPUB controller exposes the complete thumb dock and persists the current bookmark', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await mockReaderApi(page, 'epub', [], { epubUnitCount: 80 });
  await page.goto('/reader/epub-edition');
  await showReaderControls(page);

  const topBar = page.locator('[data-reader-controller="top-minimal"]');
  await expect(topBar.getByRole('button')).toHaveCount(2);
  await expect(topBar).not.toContainText('EPUB 测试读物');
  const topBarBounds = await topBar.locator('[data-reader-top-bar="true"]').boundingBox();
  expect(topBarBounds).not.toBeNull();
  expect(topBarBounds!.width).toBeGreaterThan(350);

  const console = page.locator('[data-reader-controller="bottom-console"]');
  await expect(console).toBeVisible();
  await expect(page.getByRole('button', { name: '目录' })).toBeVisible();
  const bookmarksButton = console.getByRole('button', { name: '书签', exact: true });
  await expect(bookmarksButton).toBeVisible();
  await expect(page.getByRole('button', { name: '进度' })).toBeVisible();
  await expect(page.getByRole('button', { name: '标注与批注' })).toBeVisible();
  await expect(page.getByRole('button', { name: '阅读设置' })).toBeVisible();

  await page.getByRole('button', { name: '目录' }).click();
  const mobileDirectory = page.getByRole('dialog', { name: '目录' });
  await expect(mobileDirectory).toBeVisible();
  await expect(page.getByRole('button', { name: '目录' })).toHaveAttribute('aria-expanded', 'true');
  const mobileDirectoryBounds = await mobileDirectory.boundingBox();
  expect(mobileDirectoryBounds).not.toBeNull();
  expect(mobileDirectoryBounds!.x).toBeLessThanOrEqual(1);
  expect(mobileDirectoryBounds!.width).toBeGreaterThanOrEqual(389);
  expect(mobileDirectoryBounds!.height).toBeLessThanOrEqual(466);
  const directoryScroll = mobileDirectory.locator('[data-pwa-scroll="true"]');
  await expect.poll(() => directoryScroll.evaluate((element) => element.scrollHeight > element.clientHeight)).toBe(true);
  if (process.env.SHUKU_READER_TOC_CAPTURE) await page.screenshot({ path: process.env.SHUKU_READER_TOC_CAPTURE });

  await bookmarksButton.click();
  await expect(mobileDirectory).not.toBeAttached();
  await expect(page.getByRole('button', { name: '目录' })).toHaveAttribute('aria-expanded', 'false');
  const bookmarksDialog = page.getByRole('dialog', { name: '书签' });
  await expect(bookmarksDialog).toBeVisible();
  await expect(bookmarksButton).toHaveAttribute('aria-expanded', 'true');
  await expect(bookmarksDialog.getByText('还没有书签')).toBeVisible();
  await bookmarksDialog.getByRole('button', { name: '添加当前位置书签' }).click();
  await expect(page.getByRole('status')).toHaveText('已添加当前书签');
  await expect(bookmarksButton).toHaveAttribute('aria-pressed', 'true');
  await expect(bookmarksDialog.getByRole('button', { name: /跳转到书签：第一章/ })).toBeVisible();
  await expect.poll(() => page.evaluate(() => Object.keys(localStorage).some((key) => key.startsWith('shuku:reader-bookmarks:v2:user-e2e:epub-edition:')))).toBe(true);

  await page.getByRole('button', { name: '目录' }).click();
  const reopenedDirectory = page.getByRole('dialog', { name: '目录' });
  await reopenedDirectory.getByRole('button', { name: /2.*第二章/ }).click();
  await expect(reopenedDirectory).not.toBeAttached();
  await expectEpubTextInAnyIframe(page, '第二章 翻页验证');

  await bookmarksButton.click();
  await page.getByRole('dialog', { name: '书签' }).getByRole('button', { name: '添加当前位置书签' }).click();
  await expect(page.getByRole('dialog', { name: '书签' }).getByRole('button', { name: /^跳转到书签：/ })).toHaveCount(2);
  if (process.env.SHUKU_READER_BOOKMARKS_CAPTURE) await page.screenshot({ path: process.env.SHUKU_READER_BOOKMARKS_CAPTURE });
  await page.getByRole('dialog', { name: '书签' }).getByRole('button', { name: /跳转到书签：第一章/ }).click();
  await expect(page.getByRole('dialog', { name: '书签' })).not.toBeAttached();
  await expectEpubTextInAnyIframe(page, '第一章 开始阅读');

  await bookmarksButton.click();
  const reopenedBookmarks = page.getByRole('dialog', { name: '书签' });
  await reopenedBookmarks.getByRole('button', { name: /删除书签：第一章/ }).click();
  await expect(reopenedBookmarks.getByRole('button', { name: /^跳转到书签：/ })).toHaveCount(1);

  await page.getByRole('button', { name: '进度' }).click();
  const progressDialog = page.getByRole('dialog', { name: '阅读进度' });
  await expect(progressDialog).toBeVisible();
  await expect(progressDialog.getByRole('slider', { name: '阅读进度' })).toBeVisible();
  await page.keyboard.press('Escape');
  await page.getByRole('button', { name: '标注与批注' }).click();
  const annotationDialog = page.getByRole('dialog', { name: '标注与批注' });
  await expect(annotationDialog.getByRole('tab', { name: '书内注释' })).toHaveAttribute('aria-selected', 'true');
  await annotationDialog.getByRole('tab', { name: '我的标注' }).click();
  await expect(annotationDialog.getByText('还没有划线或批注')).toBeVisible();
});

test('tablet comic controller keeps format-appropriate actions and an inline progress scrubber', async ({ page }) => {
  await page.setViewportSize({ width: 834, height: 1112 });
  await mockReaderApi(page, 'comic');
  await page.goto('/reader/comic-edition?volume=comic-volume');
  await showReaderControls(page);

  const console = page.locator('[data-reader-controller="bottom-console"]');
  const consoleBounds = await console.locator(':scope > div').boundingBox();
  expect(consoleBounds).not.toBeNull();
  expect(consoleBounds!.x).toBeGreaterThan(16);
  expect(consoleBounds!.width).toBeLessThan(834 - 32);
  await expect(page.getByRole('slider', { name: '阅读进度' })).toBeVisible();
  await expect(page.getByRole('button', { name: '进度' })).toBeHidden();
  await expect(page.getByRole('button', { name: '标注与批注' })).toHaveCount(0);
  await expect(page.getByRole('button', { name: '目录' })).toBeVisible();
  await expect(console.getByRole('button', { name: '书签', exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: '阅读设置' })).toBeVisible();

  const directoryButton = page.getByRole('button', { name: '目录' });
  const directoryButtonBounds = await directoryButton.boundingBox();
  await directoryButton.click();
  const directoryDialog = page.getByRole('dialog', { name: '目录' });
  await expect(directoryDialog).toBeVisible();
  await expect(directoryButton).toHaveAttribute('aria-expanded', 'true');
  const directoryBounds = await directoryDialog.boundingBox();
  expect(directoryButtonBounds).not.toBeNull();
  expect(directoryBounds).not.toBeNull();
  expect(directoryBounds!.y + directoryBounds!.height).toBeLessThanOrEqual(directoryButtonBounds!.y - 8);
  expect(directoryButtonBounds!.x + (directoryButtonBounds!.width / 2)).toBeGreaterThanOrEqual(directoryBounds!.x);
  expect(directoryButtonBounds!.x + (directoryButtonBounds!.width / 2)).toBeLessThanOrEqual(directoryBounds!.x + directoryBounds!.width);
  expect(directoryBounds!.x + (directoryBounds!.width / 2)).toBeLessThan(834 / 2);
  const settingsButton = page.getByRole('button', { name: '阅读设置' });
  const settingsButtonBounds = await settingsButton.boundingBox();
  await settingsButton.click();
  await expect(directoryDialog).not.toBeAttached();
  await expect(directoryButton).toHaveAttribute('aria-expanded', 'false');
  const settingsDialog = page.getByRole('dialog', { name: '阅读设置' });
  await expect(settingsDialog).toBeVisible();
  await expect(settingsButton).toHaveAttribute('aria-expanded', 'true');
  await expect(settingsDialog.getByRole('group', { name: '主题' }).getByRole('button')).toHaveCount(4);
  await expect(settingsDialog.getByText('主题', { exact: true })).toHaveCount(0);
  if (process.env.SHUKU_READER_SETTINGS_CAPTURE) {
    await page.screenshot({ path: process.env.SHUKU_READER_SETTINGS_CAPTURE });
  }
  const settingsBounds = await settingsDialog.boundingBox();
  expect(settingsButtonBounds).not.toBeNull();
  expect(settingsBounds).not.toBeNull();
  expect(settingsBounds!.width).toBeLessThanOrEqual(384);
  expect(settingsBounds!.y + settingsBounds!.height).toBeLessThanOrEqual(settingsButtonBounds!.y - 8);
  expect(settingsButtonBounds!.x + (settingsButtonBounds!.width / 2)).toBeGreaterThanOrEqual(settingsBounds!.x);
  expect(settingsButtonBounds!.x + (settingsButtonBounds!.width / 2)).toBeLessThanOrEqual(settingsBounds!.x + settingsBounds!.width);
  if (process.env.SHUKU_READER_SETTINGS_CAPTURE && process.env.SHUKU_READER_SETTINGS_SOURCE && process.env.SHUKU_READER_SETTINGS_COMPARISON) {
    const [sourceVisual, implementation] = await Promise.all([
      readFile(process.env.SHUKU_READER_SETTINGS_SOURCE),
      readFile(process.env.SHUKU_READER_SETTINGS_CAPTURE)
    ]);
    const dataUri = (buffer: Buffer) => `data:image/png;base64,${buffer.toString('base64')}`;
    await page.setViewportSize({ width: 1748, height: 1185 });
    await page.setContent(`
      <style>
        * { box-sizing: border-box; }
        body { margin: 0; background: #f7f3ed; color: #2b2118; font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", sans-serif; }
        h1 { margin: 18px 28px 12px; font-size: 22px; }
        .comparison { display: flex; gap: 24px; padding: 0 28px 28px; }
        figure { margin: 0; width: 834px; }
        img { display: block; width: 834px; height: 1112px; object-fit: cover; box-shadow: 0 10px 30px rgba(43,33,24,.14); }
        figcaption { margin-top: 9px; font-size: 14px; font-weight: 650; }
      </style>
      <h1>阅读设置密度对比</h1>
      <div class="comparison">
        <figure><img src="${dataUri(sourceVisual)}" /><figcaption>调整前：大面积两列选项，选中态贴近控件外沿</figcaption></figure>
        <figure><img src="${dataUri(implementation)}" /><figcaption>调整后：色点主题、三档选择、单行紧凑控件与内缩选中态</figcaption></figure>
      </div>
    `);
    await page.screenshot({ path: process.env.SHUKU_READER_SETTINGS_COMPARISON, fullPage: true });
  }
});

test('an EPUB without alternative editions or volumes shows only its chapter hierarchy', async ({ page }, testInfo) => {
  const consoleErrors: string[] = [];
  page.on('console', (message) => {
    if (message.type() === 'error') consoleErrors.push(message.text());
  });
  const usesAnchoredDesktopPanel = !testInfo.project.name.includes('iphone');
  if (usesAnchoredDesktopPanel) await page.setViewportSize({ width: 1440, height: 900 });
  await mockReaderApi(page, 'epub');
  await page.goto('/reader/epub-edition');
  await showReaderControls(page);
  const directoryButton = page.getByRole('button', { name: '目录' });
  const directoryButtonBounds = await directoryButton.boundingBox();
  const dockSurface = directoryButton.locator('[data-reader-dock-surface="true"]');
  const hoverSurfaceBox = usesAnchoredDesktopPanel ? await (async () => {
    await directoryButton.hover();
    await expect.poll(() => dockSurface.evaluate((element) => getComputedStyle(element).backgroundColor)).not.toBe('rgba(0, 0, 0, 0)');
    await expect(directoryButton).toHaveCSS('background-color', 'rgba(0, 0, 0, 0)');
    return dockSurface.boundingBox();
  })() : null;
  await directoryButton.click();

  const directory = page.getByRole('dialog', { name: '目录' });
  await expect(directory).toBeVisible();
  await expect(directoryButton).toHaveAttribute('aria-expanded', 'true');
  await expect(directoryButton).toHaveCSS('color', 'rgb(180, 83, 9)');
  const selectedSurface = directoryButton.locator('[data-reader-dock-selection-surface="true"]');
  const [directoryButtonBox, selectedSurfaceBox] = await Promise.all([directoryButton.boundingBox(), selectedSurface.boundingBox()]);
  expect(directoryButtonBox).not.toBeNull();
  expect(selectedSurfaceBox).not.toBeNull();
  expect(selectedSurfaceBox!.x - directoryButtonBox!.x).toBeGreaterThanOrEqual(5);
  expect(selectedSurfaceBox!.y - directoryButtonBox!.y).toBeGreaterThanOrEqual(5);
  if (hoverSurfaceBox) {
    expect(selectedSurfaceBox!.width).toBe(hoverSurfaceBox.width);
    expect(selectedSurfaceBox!.height).toBe(hoverSurfaceBox.height);
  }
  const directoryBounds = await directory.boundingBox();
  expect(directoryButtonBounds).not.toBeNull();
  expect(directoryBounds).not.toBeNull();
  if (usesAnchoredDesktopPanel) {
    expect(directoryBounds!.y + directoryBounds!.height).toBeLessThanOrEqual(directoryButtonBounds!.y - 8);
    expect(directoryButtonBounds!.x + (directoryButtonBounds!.width / 2)).toBeGreaterThanOrEqual(directoryBounds!.x);
    expect(directoryButtonBounds!.x + (directoryButtonBounds!.width / 2)).toBeLessThanOrEqual(directoryBounds!.x + directoryBounds!.width);
  } else {
    expect(directoryBounds!.x).toBeLessThanOrEqual(1);
    expect(directoryBounds!.width).toBeGreaterThanOrEqual((page.viewportSize()?.width ?? 390) - 1);
  }
  await expect(directory.getByText('默认版本', { exact: true })).toHaveCount(0);
  await expect(directory.getByText('版本', { exact: true })).toHaveCount(0);
  await expect(directory.getByText('卷册', { exact: true })).toHaveCount(0);
  await expect(directory.getByText('章节', { exact: true })).toBeVisible();
  await expect(directory.getByRole('button', { name: /1.*第一章/ })).toBeVisible();
  await expect(directory.getByRole('button', { name: /2.*第二章/ })).toBeVisible();
  const panelCapturePath = process.env.SHUKU_READER_PANEL_CAPTURE;
  if (panelCapturePath) await page.screenshot({ path: panelCapturePath });
  await page.mouse.click(usesAnchoredDesktopPanel ? 900 : 195, usesAnchoredDesktopPanel ? 500 : 100);
  await expect(directory).not.toBeAttached();
  await expect(directoryButton).toHaveAttribute('aria-expanded', 'false');
  await directoryButton.click();
  await expect(directory).toBeVisible();
  await expect(directoryButton).toHaveAttribute('aria-expanded', 'true');
  await directoryButton.click();
  await expect(directory).not.toBeAttached();
  await expect(directoryButton).toHaveAttribute('aria-expanded', 'false');
  if (panelCapturePath && process.env.SHUKU_READER_PANEL_SOURCE && process.env.SHUKU_READER_PANEL_COMPARISON) {
      const [sourceVisual, implementation] = await Promise.all([
        readFile(process.env.SHUKU_READER_PANEL_SOURCE),
        readFile(panelCapturePath)
      ]);
      const dataUri = (buffer: Buffer) => `data:image/png;base64,${buffer.toString('base64')}`;
      await page.setViewportSize({ width: 1840, height: 900 });
      await page.setContent(`
        <style>
          * { box-sizing: border-box; }
          body { margin: 0; background: #f7f3ed; color: #2b2118; font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", sans-serif; }
          h1 { margin: 20px 28px 14px; font-size: 22px; }
          .comparison { display: flex; align-items: flex-start; gap: 20px; padding: 0 28px 26px; }
          .column { display: flex; flex-direction: column; gap: 10px; }
          .label { font-size: 15px; font-weight: 650; }
          .reference { position: relative; width: 542px; height: 760px; overflow: hidden; background: #fff; box-shadow: 0 10px 30px rgba(43,33,24,.14); }
          .reference img { position: absolute; inset: 0 auto auto 0; width: 1318px; height: auto; }
          .implementation { display: block; width: 1216px; height: 760px; object-fit: cover; box-shadow: 0 10px 30px rgba(43,33,24,.14); }
        </style>
        <h1>按钮锚定面板：参考交互与实现结果</h1>
        <div class="comparison">
          <div class="column">
            <div class="reference"><img src="${dataUri(sourceVisual)}" /></div>
            <div class="label">参考：上下文面板位于触发按钮上方</div>
          </div>
          <div class="column">
            <img class="implementation" src="${dataUri(implementation)}" />
            <div class="label">实现：目录以底部目录按钮为锚点向上展开</div>
          </div>
        </div>
      `);
      await page.screenshot({ path: process.env.SHUKU_READER_PANEL_COMPARISON, fullPage: true });
  }
  expect(consoleErrors).toEqual([]);
});

test('comic navigation, local theme persistence, reset, and V2 progress transport', async ({ page }) => {
  const progressBodies: Array<Record<string, any>> = [];
  await mockReaderApi(page, 'comic', progressBodies);
  await page.goto('/reader/comic-edition?volume=comic-volume');
  await expect(page.locator('[data-reader-engine="comic-v2"]')).toBeVisible();
  await expect(page.getByText('第 1 页 / 共 3 页').first()).toBeVisible();
  await showReaderControls(page);
  const previousButton = page.getByRole('button', { name: '上一页' });
  if (await previousButton.count()) {
    await expect(previousButton).toBeDisabled();
  } else {
    await page.getByRole('button', { name: '进度' }).click();
    await expect(page.getByRole('dialog', { name: '阅读进度' }).getByRole('button', { name: '上一页' })).toBeDisabled();
    await page.keyboard.press('Escape');
  }
  await page.keyboard.press('Escape');

  await page.keyboard.press('ArrowRight');
  await expect(page.getByText('第 2 页 / 共 3 页').first()).toBeVisible();
  await expect.poll(() => progressBodies.some((body) => (
    body.position?.contentFingerprint === 'comic-fixture-v1'
    && progressLocation(body)?.type === 'comic'
    && progressLocation(body)?.volumeId === 'comic-volume'
    && progressLocation(body)?.pageIndex === 2
  )), { timeout: 8_000 }).toBe(true);

  await showReaderControls(page);
  await page.getByRole('button', { name: '阅读设置' }).click();
  const settingsDialog = page.getByRole('dialog', { name: '阅读设置' });
  await expect(settingsDialog).toBeVisible();
  await expect(page.getByRole('button', { name: '关闭面板' })).toBeFocused();
  await page.keyboard.press('Shift+Tab');
  await expect(page.getByRole('button', { name: '恢复本书默认设置' })).toBeFocused();
  await page.keyboard.press('Tab');
  await expect(page.getByRole('button', { name: '关闭面板' })).toBeFocused();
  await page.keyboard.press('ArrowRight');
  const openSettingsBounds = await settingsDialog.boundingBox();
  expect(openSettingsBounds).not.toBeNull();
  const outsidePoint = openSettingsBounds!.x > 12
    ? { x: 8, y: Math.round((page.viewportSize()?.height ?? 720) / 2) }
    : { x: Math.round((page.viewportSize()?.width ?? 390) / 2), y: Math.max(4, Math.round(openSettingsBounds!.y / 2)) };
  if (await page.evaluate(() => navigator.maxTouchPoints > 0)) {
    await page.touchscreen.tap(outsidePoint.x, outsidePoint.y);
  } else {
    await page.mouse.click(outsidePoint.x, outsidePoint.y);
  }
  await expect(settingsDialog).not.toBeAttached();
  await expect(page.getByText('第 2 页 / 共 3 页').first()).toBeVisible();
  await page.getByRole('button', { name: '阅读设置' }).click();
  await expect(page.getByRole('dialog', { name: '阅读设置' })).toBeVisible();
  await page.getByRole('button', { name: '纯黑' }).click();
  await expect(page.locator('[data-reader-shell="v2"]')).toHaveAttribute('data-reader-theme', 'black');
  await page.getByRole('button', { name: '省流', exact: true }).click();
  await page.getByRole('button', { name: '原图', exact: true }).click();
  await expect.poll(async () => {
    const src = await page.locator('[data-comic-spread-slot="current"] img').first().getAttribute('src');
    return src ? page.evaluate(async (url) => fetch(url).then((response) => response.text()), src) : '';
  }).toContain('original');
  await page.getByRole('button', { name: '右至左' }).click();
  await page.keyboard.press('Escape');
  await expect(settingsDialog).not.toBeAttached();
  await expect(page.getByRole('button', { name: '阅读设置' })).toBeFocused();
  await page.keyboard.press('Escape');
  await page.locator('[data-reader-shell="v2"] > div').first().focus();
  await page.keyboard.press('ArrowLeft');
  await expect(page.getByText('第 3 页 / 共 3 页').first()).toBeVisible();
  await showReaderControls(page);
  await page.getByRole('button', { name: '阅读设置' }).click();
  await page.getByRole('button', { name: '双页', exact: true }).click();
  await expect(page.locator('[data-comic-spread-slot="current"] img')).toHaveCount(1);
  await expect(page.locator('[data-comic-spread-slot="current"] img')).toHaveAttribute('alt', '第 3 页');
  await page.getByRole('button', { name: '单页', exact: true }).click();
  await page.keyboard.press('Escape');
  await page.reload();
  await expect(page.locator('[data-reader-engine="comic-v2"]')).toBeVisible();
  await expect(page.locator('[data-reader-shell="v2"]')).toHaveAttribute('data-reader-theme', 'black');
  await showReaderControls(page);
  await page.getByRole('button', { name: '阅读设置' }).click();
  await page.getByRole('button', { name: '恢复本书默认设置' }).click();
  await expect(page.locator('[data-reader-shell="v2"]')).toHaveAttribute('data-reader-theme', 'warm');
});

test('PDF.js renders a bounded canvas and selectable text layer', async ({ page }) => {
  await mockReaderApi(page, 'pdf');
  await page.goto('/reader/pdf-edition');
  await expect(page.locator('[data-reader-engine="pdf-v2"] canvas')).toBeVisible();
  await expect(page.locator('[data-reader-engine="pdf-v2"] .textLayer')).toBeAttached();
  await expect(page.getByText('第 1 页 / 共 1 页').first()).toBeVisible();
  const canvasPixels = await page.locator('[data-reader-engine="pdf-v2"] canvas').evaluate((canvas: HTMLCanvasElement) => canvas.width * canvas.height);
  expect(canvasPixels).toBeLessThanOrEqual(12_000_000);
});

test('corrupted PDF fails safely with retry and library actions', async ({ page }) => {
  await mockReaderApi(page, 'pdf', [], { pdfBody: Buffer.from([0, 1, 2, 3, 4, 5]) });
  await page.goto('/reader/pdf-edition');
  await expect(page.getByText('阅读器加载失败')).toBeVisible({ timeout: 30_000 });
  await expect(page.getByRole('button', { name: '重试' })).toBeVisible();
  await expect(page.getByRole('button', { name: '返回书库' })).toBeVisible();
  await expect(page.locator('[data-reader-engine="pdf-v2"] canvas')).toHaveCount(0);
});

test('legacy mobile reader links return to the responsive web detail page', async ({ page }) => {
  await mockReaderApi(page, 'comic');
  await page.goto('/reader/comic-edition?volume=comic-volume&from=mobile&tab=shelf');
  await expect(page.locator('[data-reader-engine="comic-v2"]')).toBeVisible();
  await showReaderControls(page);
  await page.getByRole('button', { name: '返回详情页' }).click();
  await expect(page).toHaveURL(/\/works\/work-comic$/);
});

test('a comic bookmark target opens the saved page in its requested volume', async ({ page }) => {
  await mockReaderApi(page, 'comic');
  await page.goto('/reader/comic-edition?volume=comic-volume&page=3');
  await expect(page.locator('[data-reader-engine="comic-v2"]')).toBeVisible();
  await expect(page.getByText('第 3 页 / 共 3 页').first()).toBeVisible();
  await expect(page.locator('[data-comic-spread-slot="current"] img')).toHaveAttribute('alt', '第 3 页');
});

test('50 consecutive comic turns keep one engine and a bounded DOM surface', async ({ page }) => {
  test.skip(test.info().project.name !== 'chromium', 'Long-running leak sentinel runs once in Chromium');
  await mockReaderApi(page, 'comic');
  await page.goto('/reader/comic-edition?volume=comic-volume');
  await expect(page.locator('[data-reader-engine="comic-v2"]')).toBeVisible();
  await Promise.all([page.keyboard.press('ArrowRight'), page.keyboard.press('ArrowRight')]);
  await expect(page.getByText('第 3 页 / 共 3 页').first()).toBeVisible();
  await page.keyboard.press('Home');
  await expect(page.getByText('第 1 页 / 共 3 页').first()).toBeVisible();
  for (let index = 0; index < 25; index += 1) {
    await page.keyboard.press('ArrowRight');
    await expect(page.getByText('第 2 页 / 共 3 页').first()).toBeVisible();
    await page.keyboard.press('ArrowLeft');
    await expect(page.getByText('第 1 页 / 共 3 页').first()).toBeVisible();
  }
  await expect(page.locator('[data-reader-engine="comic-v2"]')).toHaveCount(1);
  await expect(page.locator('[data-comic-spread-slot]')).toHaveCount(3);
  await expect(page.locator('[data-comic-spread-slot="current"] img')).toHaveCount(1);
  await expect.poll(() => page.locator('[data-reader-engine="comic-v2"] img').count()).toBeLessThanOrEqual(3);
  await expect(page.locator('[data-reader-engine="comic-v2"] canvas, [data-reader-engine="comic-v2"] iframe')).toHaveCount(0);
});

test('EPUB reload restores the pending local CFI while an explicit href still wins', async ({ page }) => {
  const progressBodies: Array<Record<string, any>> = [];
  await mockReaderApi(page, 'epub', progressBodies, { progressStatus: 503 });

  await page.goto('/reader/epub-edition');
  let iframe = page.locator('[data-reader-engine="epub-v2"] iframe').first();
  await expect(iframe.contentFrame().getByText('第一章 开始阅读')).toBeVisible();
  await waitForReaderReady(page);

  await page.keyboard.press('ArrowRight');
  await expect.poll(() => progressBodies.some((body) => (
    progressLocation(body)?.type === 'epub'
    && typeof progressLocation(body)?.href === 'string'
    && progressLocation(body)!.href.endsWith('chapter2.xhtml')
  )), { timeout: 8_000 }).toBe(true);
  await expect.poll(() => progressBodies.some((body) => (
    progressLocation(body)?.type === 'epub'
    && typeof progressLocation(body)?.cfi === 'string'
    && progressLocation(body)!.cfi.startsWith('epubcfi(')
  )), { timeout: 8_000 }).toBe(true);
  await expect.poll(async () => (await readerProgressOutbox(page)).length).toBeGreaterThan(0);

  await page.reload();
  await waitForReaderReady(page);
  await expect.poll(async () => (await readerProgressOutbox(page)).length).toBeGreaterThan(0);
  await showReaderControls(page);
  await page.getByRole('button', { name: '目录' }).click();
  const restoredDirectory = page.getByRole('dialog', { name: '目录' });
  await expect(restoredDirectory.getByRole('button', { name: /2.*第二章/ })).toHaveAttribute('aria-current', 'location');
  await page.keyboard.press('Escape');

  await page.goto('/reader/epub-edition?href=chapter1.xhtml');
  iframe = await currentEpubIframe(page);
  await expect(iframe.contentFrame().getByText('第一章 开始阅读')).toBeVisible();
});

test('large EPUB location generation reports progress and completes', async ({ page }) => {
  const fixturePath = process.env.SHUKU_EPUB_PERF_FIXTURE;
  test.skip(!fixturePath, 'Set SHUKU_EPUB_PERF_FIXTURE to run the local large-book benchmark');
  const epubBody = await readFile(fixturePath!);
  await mockReaderApi(page, 'epub', [], { epubBody, epubUnitCount: 2000 });
  const startedAt = Date.now();
  await page.goto('/reader/epub-edition');
  let highestProgress = 0;
  let sawIntermediateProgress = false;
  await expect.poll(async () => {
    const progress = await page.locator('[aria-label="全书位置索引进度"]').evaluateAll((elements) => (
      elements.map((element) => Number(element.getAttribute('aria-valuenow') ?? 0))
    ));
    highestProgress = Math.max(highestProgress, ...progress);
    sawIntermediateProgress ||= progress.some((value) => value > 0 && value < 100);
    return page.locator('[data-reader-engine="epub-v2"] iframe').count();
  }, { timeout: 120_000, intervals: [50, 100, 250, 500] }).toBeGreaterThan(0);
  console.log('Large EPUB location benchmark', { elapsedMs: Date.now() - startedAt, highestProgress, sawIntermediateProgress });
  expect(highestProgress).toBeGreaterThan(0);
  expect(sawIntermediateProgress).toBe(true);
});

test('EPUB cross-spine paging uses one EPUB.js step without a custom track or animation', async ({ page }) => {
  await page.addInitScript(() => {
    const state = window as typeof window & { __epubPageTurnAnimations?: number };
    state.__epubPageTurnAnimations = 0;
    const originalAnimate = Element.prototype.animate;
    Element.prototype.animate = function (keyframes, options) {
      if ((this as HTMLElement).dataset.readerEngine === 'epub-v2') {
        state.__epubPageTurnAnimations = (state.__epubPageTurnAnimations ?? 0) + 1;
      }
      return originalAnimate.call(this, keyframes, options);
    };
  });
  const progressBodies: Array<Record<string, any>> = [];
  await mockReaderApi(page, 'epub', progressBodies);
  await page.goto('/reader/epub-edition');
  const iframe = page.locator('[data-reader-engine="epub-v2"] iframe').first();
  await expect(iframe.contentFrame().getByText('第一章 开始阅读')).toBeVisible();
  await expect(iframe.contentFrame().locator('html')).toHaveAttribute('data-shuku-input-bridge', 'ready');
  await waitForReaderReady(page);
  await iframe.contentFrame().locator('body').evaluate((body) => {
    const document = body.ownerDocument;
    body.dispatchEvent(new MouseEvent('click', {
      bubbles: true,
      clientX: document.documentElement.clientWidth * 0.9,
      clientY: document.documentElement.clientHeight * 0.5
    }));
  });
  await expect.poll(() => progressBodies.some((body) => (
    progressLocation(body)?.type === 'epub'
    && typeof progressLocation(body)?.href === 'string'
    && progressLocation(body)!.href.endsWith('chapter2.xhtml')
  )), { timeout: 8_000 }).toBe(true);
  await expect(page.locator('[data-epub-continuous-track], [data-epub-default-track]')).toHaveCount(0);
  await expect.poll(() => page.evaluate(() => (
    window as typeof window & { __epubPageTurnAnimations?: number }
  ).__epubPageTurnAnimations ?? 0)).toBe(0);
});

test('EPUB swipe submits one navigation command without a visual paging track', async ({ page }) => {
  const progressBodies: Array<Record<string, any>> = [];
  await mockReaderApi(page, 'epub', progressBodies);
  await page.goto('/reader/epub-edition');
  const iframe = await currentEpubIframe(page);
  await expect(iframe.contentFrame().getByText('第一章 开始阅读')).toBeVisible();
  const iframeHtml = iframe.contentFrame().locator('html');
  await expect(iframeHtml).toHaveAttribute('data-shuku-input-bridge', 'ready');
  await iframe.contentFrame().locator('body').evaluate((body) => {
    const view = body.ownerDocument.defaultView;
    if (!view?.PointerEvent) throw new Error('PointerEvent is unavailable');
    const width = body.ownerDocument.documentElement.clientWidth;
    const clientY = body.ownerDocument.documentElement.clientHeight * 0.5;
    body.dispatchEvent(new view.PointerEvent('pointerdown', {
      bubbles: true, button: 0, buttons: 1, clientX: width * 0.85, clientY, isPrimary: true, pointerId: 1, pointerType: 'touch'
    }));
    body.dispatchEvent(new view.PointerEvent('pointerup', {
      bubbles: true, button: 0, buttons: 0, clientX: width * 0.15, clientY, isPrimary: true, pointerId: 1, pointerType: 'touch'
    }));
  });
  await expect.poll(() => progressBodies.some((body) => (
    progressLocation(body)?.type === 'epub'
    && typeof progressLocation(body)?.href === 'string'
    && progressLocation(body)!.href.endsWith('chapter2.xhtml')
  )), { timeout: 8_000 }).toBe(true);
  await expect(page.locator('[data-epub-continuous-track], [data-epub-default-track]')).toHaveCount(0);
});

test('EPUB pointer tap navigates only when its click is emitted', async ({ page }) => {
  await page.addInitScript(() => {
    const state = window as typeof window & { __epubNavigationStarts?: number };
    state.__epubNavigationStarts = 0;
    window.addEventListener('shuku:reader-debug', (event) => {
      const detail = (event as CustomEvent<{ message?: string; data?: { kind?: string } }>).detail;
      if (detail.message === '阅读器操作开始' && detail.data?.kind === 'navigation') {
        state.__epubNavigationStarts = (state.__epubNavigationStarts ?? 0) + 1;
      }
    });
  });
  const progressBodies: Array<Record<string, any>> = [];
  await mockReaderApi(page, 'epub', progressBodies);
  await page.goto('/reader/epub-edition');
  const iframe = page.locator('[data-reader-engine="epub-v2"] iframe').first();
  const firstBody = iframe.contentFrame().locator('body');
  await expect(iframe.contentFrame().getByText('第一章 开始阅读')).toBeVisible();
  await expect(iframe.contentFrame().locator('html')).toHaveAttribute('data-shuku-input-bridge', 'ready');
  await waitForReaderReady(page);
  await page.evaluate(() => {
    const state = window as typeof window & {
      __epubTransitionAudit?: {
        placeholderSeen: boolean;
        violations: number;
        stop: () => void;
      };
    };
    const engine = document.querySelector<HTMLElement>('[data-reader-engine="epub-v2"]');
    if (!engine) throw new Error('EPUB engine is unavailable');
    const initialFrames = new Set(engine.querySelectorAll('iframe'));
    const audit = { placeholderSeen: false, violations: 0, stop: () => undefined };
    const sample = () => {
      audit.placeholderSeen ||= Boolean(engine.querySelector('[data-shuku-epub-transition-placeholder="true"]'));
      engine.querySelectorAll<HTMLIFrameElement>('iframe').forEach((frame) => {
        if (initialFrames.has(frame)) return;
        const bounds = frame.getBoundingClientRect();
        const style = getComputedStyle(frame);
        const visible = bounds.width > 0
          && bounds.height > 0
          && style.visibility !== 'hidden'
          && Number.parseFloat(style.opacity || '1') > 0;
        const ready = frame.dataset.shukuEpubTransitionReady === 'true';
        if (visible && !ready) audit.violations += 1;
      });
    };
    const observer = new MutationObserver(sample);
    observer.observe(engine, { subtree: true, childList: true, attributes: true, attributeFilter: ['style'] });
    const timer = window.setInterval(sample, 5);
    audit.stop = () => {
      observer.disconnect();
      window.clearInterval(timer);
      sample();
    };
    state.__epubTransitionAudit = audit;
  });
  await firstBody.evaluate((body) => {
    const view = body.ownerDocument.defaultView;
    if (!view?.PointerEvent) throw new Error('PointerEvent is unavailable');
    const clientX = body.ownerDocument.documentElement.clientWidth * 0.9;
    const clientY = body.ownerDocument.documentElement.clientHeight * 0.5;
    body.dispatchEvent(new view.PointerEvent('pointerdown', {
      bubbles: true, button: 0, buttons: 1, clientX, clientY, isPrimary: true, pointerId: 1, pointerType: 'touch'
    }));
    body.dispatchEvent(new view.PointerEvent('pointerup', {
      bubbles: true, button: 0, buttons: 0, clientX, clientY, isPrimary: true, pointerId: 1, pointerType: 'touch'
    }));
  });
  expect(await page.evaluate(() => (
    window as typeof window & { __epubNavigationStarts?: number }
  ).__epubNavigationStarts ?? 0)).toBe(0);
  await firstBody.evaluate((body) => {
    const document = body.ownerDocument;
    body.dispatchEvent(new MouseEvent('click', {
      bubbles: true,
      clientX: document.documentElement.clientWidth * 0.9,
      clientY: document.documentElement.clientHeight * 0.5
    }));
  });
  await expect.poll(() => page.evaluate(() => (
    window as typeof window & { __epubNavigationStarts?: number }
  ).__epubNavigationStarts ?? 0)).toBe(1);
  await expect.poll(() => progressBodies.some((body) => (
    progressLocation(body)?.type === 'epub'
    && typeof progressLocation(body)?.href === 'string'
    && progressLocation(body)!.href.endsWith('chapter2.xhtml')
  )), { timeout: 8_000 }).toBe(true);
  await expect(page.locator('[data-shuku-epub-transition-placeholder="true"]')).toHaveCount(0);
  const currentFrame = await currentEpubIframe(page);
  await expect(currentFrame.contentFrame().locator('html')).toHaveAttribute('data-shuku-theme-ready', 'ready');
  const transitionAudit = await page.evaluate(() => {
    const audit = (window as typeof window & {
      __epubTransitionAudit?: { placeholderSeen: boolean; violations: number; stop: () => void };
    }).__epubTransitionAudit;
    audit?.stop();
    return audit ? { placeholderSeen: audit.placeholderSeen, violations: audit.violations } : null;
  });
  expect(transitionAudit).toEqual({ placeholderSeen: true, violations: 0 });
  expect(await page.evaluate(() => (
    window as typeof window & { __epubNavigationStarts?: number }
  ).__epubNavigationStarts ?? 0)).toBe(1);
});

test('EPUB iframe is scriptless and receives the selected theme snapshot', async ({ page }) => {
  const progressBodies: unknown[] = [];
  const maliciousRequests: string[] = [];
  page.on('request', (request) => {
    const url = new URL(request.url());
    if (url.pathname === '/api/epub-pwn' || url.hostname === 'attacker.invalid') maliciousRequests.push(request.url());
  });
  await mockReaderApi(page, 'epub', progressBodies);
  await page.goto('/reader/epub-edition?href=chapter2.xhtml');
  let iframe = await currentEpubIframe(page);
  await expect(iframe).toBeVisible();
  await expect(iframe.contentFrame().getByText('第二章 翻页验证')).toBeVisible();
  const sandbox = await iframe.getAttribute('sandbox');
  expect(sandbox ?? '').toContain('allow-same-origin');
  expect(sandbox ?? '').toContain('allow-scripts');
  const csp = await iframe.contentFrame().locator('meta[data-shuku-epub-csp="true"]').getAttribute('content');
  expect(csp ?? '').toContain("script-src 'none'");
  await expect(iframe.contentFrame().locator('script, iframe, object, form')).toHaveCount(0);
  await expect(iframe.contentFrame().locator('meta[http-equiv="refresh"]')).toHaveCount(0);
  const sanitizedDangerousLink = iframe.contentFrame().locator('a', { hasText: '危险链接' });
  await expect(sanitizedDangerousLink).not.toHaveAttribute('href', /.+/);
  await expect(sanitizedDangerousLink).not.toHaveAttribute('onclick', /.+/);
  expect(await page.evaluate(() => ({
    script: document.documentElement.dataset.epubScriptExecuted,
    handler: document.documentElement.dataset.epubHandlerExecuted,
    frame: document.documentElement.dataset.epubFrameExecuted,
    url: document.documentElement.dataset.epubUrlExecuted,
    storage: localStorage.getItem('epub-pwn')
  }))).toEqual({ script: undefined, handler: undefined, frame: undefined, url: undefined, storage: null });
  expect(maliciousRequests).toHaveLength(0);
  await expect(iframe.contentFrame().locator('html')).toHaveAttribute('data-shuku-input-bridge', 'ready');
  const pageLayout = await iframe.contentFrame().locator('body').evaluate((body) => {
    const style = getComputedStyle(body);
    const bounds = body.getBoundingClientRect();
    const viewportWidth = body.ownerDocument.documentElement.clientWidth;
    return {
      layout: body.dataset.shukuPageLayout,
      paddingTop: Number.parseFloat(style.paddingTop),
      paddingBottom: Number.parseFloat(style.paddingBottom),
      columnWidth: Number.parseFloat(style.columnWidth),
      width: bounds.width,
      leftGap: bounds.left,
      rightGap: viewportWidth - bounds.right,
      viewportWidth
    };
  });
  expect(pageLayout.layout).toBe('single-centered');
  expect(pageLayout.paddingTop).toBeGreaterThanOrEqual(32);
  expect(pageLayout.paddingBottom).toBeGreaterThanOrEqual(32);
  const engine = page.locator('[data-reader-engine="epub-v2"]');
  const engineLayout = await engine.evaluate((element) => {
    const bounds = element.getBoundingClientRect();
    const parentBounds = element.parentElement!.getBoundingClientRect();
    return {
      width: bounds.width,
      expectedLeft: parentBounds.left + ((parentBounds.width - bounds.width) / 2),
      actualLeft: bounds.left
    };
  });
  expect(engineLayout.width).toBeLessThanOrEqual(1351);
  expect(Math.abs(engineLayout.actualLeft - engineLayout.expectedLeft)).toBeLessThanOrEqual(2);
  expect(pageLayout.columnWidth).toBeGreaterThan(engineLayout.width * 0.75);
  expect(pageLayout.columnWidth).toBeLessThanOrEqual(engineLayout.width + 1);
  expect(pageLayout.leftGap).toBeLessThanOrEqual(1);

  const initialViewport = page.viewportSize();
  if (initialViewport) {
    await page.setViewportSize({ width: Math.max(320, initialViewport.width - 240), height: initialViewport.height });
    await expect.poll(async () => {
      const resizedEngineWidth = await engine.evaluate((element) => element.getBoundingClientRect().width);
      const resizedIframe = await currentEpubIframe(page);
      return resizedIframe.contentFrame().locator('body').evaluate((body, width) => {
        const style = getComputedStyle(body);
        const bounds = body.getBoundingClientRect();
        const columnWidth = Number.parseFloat(style.columnWidth);
        return {
          isSingleColumn: columnWidth > width * 0.75 && columnWidth <= width + 1,
          startsAtColumnOrigin: bounds.left <= 1
        };
      }, resizedEngineWidth);
    }).toEqual({ isSingleColumn: true, startsAtColumnOrigin: true });
    iframe = await currentEpubIframe(page);
  }

  await showReaderControls(page);
  await expect(page.locator('[data-reader-controller="top-minimal"]')).not.toContainText(/EPUB 阅读|第二章|全书 \d+%/);
  await expect(page.locator('[data-reader-controller="top-minimal"]').getByRole('button')).toHaveCount(2);
  await expect(page.locator('[data-reader-shell="v2"]')).not.toContainText('共 2 页');
  await expect(page.locator('[data-reader-shell="v2"]')).not.toContainText(/第 \d+ \/ 2 章/);
  await page.getByRole('button', { name: '阅读设置' }).click();
  const settingsDialog = page.getByRole('dialog', { name: '阅读设置' });
  await expect(settingsDialog).toBeVisible();
  await expect(settingsDialog.getByRole('group', { name: '页面', exact: true })).toHaveCount(0);
  await page.getByRole('button', { name: '暖色' }).click();
  await expect(page.locator('[data-reader-shell="v2"]')).toHaveAttribute('data-reader-theme', 'warm');
  await expect.poll(async () => iframe.contentFrame().locator('body').evaluate((body) => getComputedStyle(body).backgroundColor)).toBe('rgb(253, 246, 234)');
  const hostileTheme = await iframe.contentFrame().locator('#hostile-theme').evaluate((element) => {
    const style = getComputedStyle(element);
    return { color: style.color, background: style.backgroundColor, font: style.fontFamily, inlineStyle: element.getAttribute('style') };
  });
  expect(hostileTheme.color).toBe('rgb(43, 33, 24)');
  expect(hostileTheme.background).toBe('rgba(0, 0, 0, 0)');
  expect(hostileTheme.font).not.toContain('monospace');
  expect(hostileTheme.inlineStyle ?? '').not.toMatch(/(?:color|background|font-family|line-height)\s*:/i);

  await page.getByRole('button', { name: '行距大' }).click();
  await expect.poll(async () => {
    const lineHeightIframe = await currentEpubIframe(page);
    return lineHeightIframe.contentFrame().locator('body').evaluate((body) => {
      const bodyStyle = getComputedStyle(body);
      const content = body.querySelector<HTMLElement>('#hostile-theme');
      if (!content) return null;
      const contentStyle = getComputedStyle(content);
      return {
        body: Number((Number.parseFloat(bodyStyle.lineHeight) / Number.parseFloat(bodyStyle.fontSize)).toFixed(2)),
        content: Number((Number.parseFloat(contentStyle.lineHeight) / Number.parseFloat(contentStyle.fontSize)).toFixed(2))
      };
    });
  }).toEqual({ body: 2.2, content: 2.2 });
  iframe = await currentEpubIframe(page);

  await iframe.contentFrame().locator('#hostile-theme').evaluate((element) => {
    (element as HTMLElement).style.setProperty('font-size', '1rem', 'important');
  });
  await expect.poll(async () => iframe.contentFrame().locator('html').evaluate((html) => getComputedStyle(html).fontSize)).toBe('18px');
  await page.getByRole('button', { name: '字号大' }).click();
  await expect.poll(async () => {
    const resizedTextIframe = await currentEpubIframe(page);
    return resizedTextIframe.contentFrame().locator('html').evaluate((html) => getComputedStyle(html).fontSize);
  }).toBe('22px');
  iframe = await currentEpubIframe(page);
  await expect.poll(async () => iframe.contentFrame().locator('#hostile-theme').evaluate((element) => getComputedStyle(element).fontSize)).toBe('22px');

  await page.getByRole('button', { name: '滚动', exact: true }).click();
  await expect.poll(async () => {
    const scrolledIframe = await currentEpubIframe(page);
    return scrolledIframe.contentFrame().locator('body').getAttribute('data-shuku-page-layout');
  }).toBe('scrolled-centered');
  iframe = await currentEpubIframe(page);
  await expect.poll(async () => iframe.contentFrame().locator('body').evaluate((body) => Number.parseFloat(getComputedStyle(body).paddingTop))).toBeGreaterThanOrEqual(28);
  await page.getByRole('button', { name: '分页', exact: true }).click();
  await expect.poll(async () => {
    const paginatedIframe = await currentEpubIframe(page);
    return paginatedIframe.contentFrame().locator('body').getAttribute('data-shuku-page-layout');
  }).toBe('single-centered');
  iframe = await currentEpubIframe(page);
  await expect(page.locator('[data-reader-engine="epub-v2"]')).toHaveCount(1);

  for (const [label, expectedFamily] of [
    ['苹方', 'PingFang SC'],
    ['黑体', 'Heiti SC'],
    ['宋体', 'Songti SC'],
    ['微软雅黑', 'Microsoft YaHei'],
    ['楷体', 'Kaiti SC']
  ] as const) {
    await page.getByRole('button', { name: label, exact: true }).click();
    await expect.poll(async () => {
      const fontIframe = await currentEpubIframe(page);
      return fontIframe.contentFrame().locator('body').evaluate((body) => getComputedStyle(body).fontFamily);
    }).toContain(expectedFamily);
    iframe = await currentEpubIframe(page);
  }

  for (const [label, theme, background] of [
    ['夜间', 'night', 'rgb(15, 23, 42)'],
    ['纯黑', 'black', 'rgb(0, 0, 0)'],
    ['白天', 'day', 'rgb(247, 247, 244)']
  ] as const) {
    await page.getByRole('button', { name: label, exact: true }).click();
    await expect(page.locator('[data-reader-shell="v2"]')).toHaveAttribute('data-reader-theme', theme);
    await expect.poll(async () => iframe.contentFrame().locator('body').evaluate((body) => getComputedStyle(body).backgroundColor)).toBe(background);
  }

  await page.waitForTimeout(1_800);
  const progressCountAfterSettings = progressBodies.length;
  await page.waitForTimeout(1_800);
  expect(progressBodies).toHaveLength(progressCountAfterSettings);

  await page.reload();
  await expect(page.locator('[data-reader-engine="epub-v2"] iframe').first()).toBeVisible();
  await expect(page.locator('[data-reader-shell="v2"]')).toHaveAttribute('data-reader-theme', 'day');
  await showReaderControls(page);
  await page.getByRole('button', { name: '阅读设置' }).click();
  await page.getByRole('button', { name: '恢复本书默认设置' }).click();
  await expect(page.locator('[data-reader-shell="v2"]')).toHaveAttribute('data-reader-theme', 'warm');
});
