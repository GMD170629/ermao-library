import { expect, test, type Locator, type Page } from '@playwright/test';
import { readFile } from 'node:fs/promises';
import path from 'node:path';

const root = path.resolve(process.cwd(), '../..');
const pdfFixture = path.join(root, 'test-data/library/pdf/reading-notes.pdf');
const epubFixture = path.join(root, 'test-data/library/epub/reader-v2.epub'); // Historical fixture content remains valid for Reader v3.

const defaultPreferences = {
  schemaVersion: 3,
  appearance: { theme: 'warm' },
  interaction: { tapZones: 'standard', swipePageTurn: true, keyboardPageTurn: true, volumeKeyPageTurn: false },
  epub: {
    fontSize: 18,
    lineHeight: 1.9,
    pageWidth: 1350,
    fontFamily: 'pingfang',
    spreadMode: 'single',
    pageTurnAnimation: 'slide',
    flow: 'paginated',
    typography: { paragraphIndent: 2, paragraphSpacing: 0, textAlign: 'publisher', preservePublisherStyles: false, allowPublisherColors: false, allowPublisherFonts: false },
    optimization: { enabled: true, deduplicateIndent: true, indentUnindented: true }
  },
  comic: { direction: 'ltr', mode: 'single', pageTurnAnimation: 'slide', imageFit: 'width', imageVariant: 'original', zoom: 1 },
  pdf: { zoom: 1, fit: 'page' }
};

type MockReaderOptions = {
  pdfBody?: Buffer;
  epubBody?: Buffer;
  progressStatus?: number;
  bootstrapDelayMs?: number;
  epubUnitCount?: number;
  epubHrefPrefix?: string;
  resumeLocation?: Record<string, unknown>;
  progressPercent?: number;
};

function bootstrap(kind: 'epub' | 'comic' | 'pdf', options: MockReaderOptions = {}) {
  const epubUnitCount = options.epubUnitCount ?? 2;
  const epubHrefPrefix = options.epubHrefPrefix ?? '';
  const readerType = kind === 'epub' ? 'reflowable' : kind;
  const volumeId = `${kind}-volume`;
  const mediaVersionId = `${kind}-media`;
  const pageCount = kind === 'comic' ? 3 : kind === 'pdf' ? 7 : null;
  const volume = {
    id: volumeId,
    mediaVersionId,
    title: kind === 'comic' ? '第一卷' : '全本',
    volumeIndex: kind === 'comic' ? 1 : null,
    sortOrder: 0,
    format: kind === 'epub' ? 'EPUB' : kind === 'comic' ? 'COMIC' : 'PDF',
    readerType,
    derivedFromVolumeId: null,
    pageCount,
    chapterCount: kind === 'epub' ? 2 : null,
    durationMs: null,
    trackCount: null,
    progress: 0,
    lastReadAt: null
  };
  const units = kind === 'epub'
    ? Array.from({ length: epubUnitCount }, (_, index) => ({ id: `unit-${index + 1}`, index, title: `第${['一', '二', '三', '四'][index] ?? index + 1}章`, href: `${epubHrefPrefix}chapter${index + 1}.xhtml`, fileId: `${kind}-file`, startMs: null, endMs: null, durationMs: null, metadata: {} }))
    : kind === 'comic'
      ? [1, 2, 3].map((pageIndex) => ({ id: `page-${pageIndex}`, index: pageIndex - 1, title: `Page ${pageIndex}`, href: null, fileId: `${kind}-file`, startMs: null, endMs: null, durationMs: null, metadata: { pageIndex, mimeType: 'image/svg+xml', width: 600, height: 900, size: 100 } }))
      : [];
  return {
    ok: true,
    data: {
      schemaVersion: 3,
      userId: 'user-e2e',
      readerType,
      sourceFormat: kind === 'epub' ? 'epub' : null,
      contentFingerprint: `${kind}-fixture-v1`,
      book: { id: `work-${kind}`, title: `${kind.toUpperCase()} 测试读物`, author: 'Test', coverUrl: null },
      mediaVersion: { id: mediaVersionId, workId: `work-${kind}`, mediaKind: kind === 'comic' ? 'COMIC' : 'EBOOK', completed: false },
      volume,
      availableVolumes: [volume],
      files: [{ id: `${kind}-file`, volumeId, kind: 'CONTENT', mimeType: kind === 'epub' ? 'application/epub+zip' : kind === 'pdf' ? 'application/pdf' : 'application/zip', sizeBytes: 100, durationMs: null, discNumber: null, trackNumber: null, sortOrder: 0, url: `/api/volumes/${volumeId}/file` }],
      units,
      fileUrl: `/api/volumes/${volumeId}/file`,
      capabilities: {
        canGoNext: true,
        canGoPrevious: false,
        canJumpToProgress: true,
        canJumpToHref: kind === 'epub',
        canJumpToIndex: true,
        canZoom: kind !== 'epub',
        canSelectText: kind !== 'comic',
        supportsPagination: true,
        supportsScrolling: kind === 'epub',
        supportsSpreads: kind !== 'pdf',
        readingDirection: 'ltr'
      },
      serverPreferences: { schemaVersion: 3, settings: defaultPreferences, updatedAt: null },
      resumeLocation: options.resumeLocation ?? (kind === 'epub' ? { type: 'reflowable', format: 'epub', progression: 0 } : kind === 'comic' ? { type: 'comic', volumeId, pageIndex: 1 } : { type: 'pdf', pageNumber: 1 }),
      resumeFingerprintMismatch: false,
      progressPercent: options.progressPercent ?? 0
    }
  };
}

async function mockReaderApi(
  page: Page,
  kind: 'epub' | 'comic' | 'pdf',
  progressBodies: unknown[] = [],
  options: MockReaderOptions = {}
) {
  const pdf = kind === 'pdf' ? options.pdfBody ?? await readFile(pdfFixture) : null;
  const epub = kind === 'epub' ? options.epubBody ?? await readFile(epubFixture) : null;
  await page.route('**/api/**', async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (url.pathname.includes('/api/reader/v3/volumes/') && url.pathname.endsWith('/bootstrap')) {
      if (options.bootstrapDelayMs) await new Promise((resolve) => setTimeout(resolve, options.bootstrapDelayMs));
      await route.fulfill({ json: bootstrap(kind, options) });
      return;
    }
    if (url.pathname.includes('/api/reader/v3/volumes/') && url.pathname.endsWith('/progress')) {
      const body = request.postDataJSON();
      progressBodies.push(body);
      if (options.progressStatus && options.progressStatus >= 400) {
        await route.fulfill({
          status: options.progressStatus,
          json: { ok: false, error: { message: '测试中的离线进度暂未同步' } }
        });
        return;
      }
      await route.fulfill({ json: { ok: true, data: { mutationId: body.mutationId, applied: true, progress: { ...body, readerType: kind === 'epub' ? 'reflowable' : kind, workId: `work-${kind}`, volumeId: `${kind}-volume`, updatedAt: new Date().toISOString() } } } });
      return;
    }
    if (url.pathname.endsWith('/file') && pdf) {
      await route.fulfill({ status: 200, contentType: 'application/pdf', body: pdf });
      return;
    }
    if (url.pathname.endsWith('/file') && epub) {
      await route.fulfill({ status: 200, contentType: 'application/epub+zip', body: epub });
      return;
    }
    if (/\/api\/volumes\/[^/]+\/pages\/\d+$/.test(url.pathname)) {
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
    if (url.pathname === '/api/auth/me') {
      await route.fulfill({
        json: {
          ok: true,
          data: {
            user: { id: 'user-e2e', email: 'e2e@example.com', name: 'E2E', role: 'admin' },
            authorization: {
              isAdmin: true,
              canManageSystem: true,
              allLibraryScopes: true,
              monitorFolderIds: [],
              canViewManualImports: true,
              authzVersion: 1
            }
          }
        }
      });
      return;
    }
    await route.fulfill({ json: { ok: true, data: {} } });
  });
}

async function currentReflowableEngine(page: Page) {
  await waitForReaderReady(page);
  const engine = page.locator('[data-reader-engine="reflowable-v3"]');
  await expect(engine).toBeVisible();
  await expect(engine).toHaveAttribute('data-reader-content', 'ready');
  return engine;
}

async function currentEpubIframe(page: Page) {
  const engine = await currentReflowableEngine(page);
  const iframe = engine.locator('iframe:visible').first();
  await expect(iframe).toBeVisible();
  return iframe;
}

async function clickVisibleReflowableZone(body: Locator, horizontalFraction: number) {
  await body.evaluate((element, fraction) => {
    const document = element.ownerDocument;
    const frame = document.defaultView?.frameElement;
    const readerViewport = frame?.ownerDocument.querySelector<HTMLElement>('[data-reader-viewport="stable"]');
    if (!frame || !readerViewport) throw new Error('Visible reader geometry is unavailable');
    const frameBounds = frame.getBoundingClientRect();
    const viewportBounds = readerViewport.getBoundingClientRect();
    const clientX = (
      viewportBounds.left + (viewportBounds.width * fraction) - frameBounds.left
    ) * frame.clientWidth / frameBounds.width;
    const clientY = (
      viewportBounds.top + (viewportBounds.height * 0.5) - frameBounds.top
    ) * frame.clientHeight / frameBounds.height;
    element.dispatchEvent(new MouseEvent('click', { bubbles: true, clientX, clientY }));
  }, horizontalFraction);
}

async function showReaderControls(page: Page) {
  await waitForReaderReady(page);
  const shell = page.locator('[data-reader-shell="v3"]');
  const box = await shell.boundingBox();
  if (!box) throw new Error('Reader shell is not visible');
  const settingsButton = page.getByRole('button', { name: '阅读设置' });
  const console = page.locator('[data-reader-controller="bottom-console"]');
  const controlsAreOpen = await console.evaluate((element) => getComputedStyle(element).opacity === '1');
  if (await settingsButton.isVisible() && controlsAreOpen) {
    await settingsButton.hover();
    return;
  }
  if (await shell.getAttribute('data-reader-kind') === 'reflowable') {
    const engine = await currentReflowableEngine(page);
    await expect(engine).toHaveAttribute('data-reader-input-bridge', 'ready');
    const engineBox = await engine.boundingBox();
    if (!engineBox) throw new Error('Novel reader is not visible');
    const hasTouch = await page.evaluate(() => navigator.maxTouchPoints > 0);
    if (hasTouch) {
      await page.touchscreen.tap(engineBox.x + engineBox.width / 2, engineBox.y + engineBox.height / 2);
    } else {
      await page.mouse.click(engineBox.x + engineBox.width / 2, engineBox.y + engineBox.height / 2);
    }
  } else {
    await page.mouse.click(box.x + box.width / 2, box.y + box.height / 2);
  }
  await expect(settingsButton).toBeVisible();
  await expect.poll(() => console.evaluate((element) => getComputedStyle(element).opacity)).toBe('1');
  await console.evaluate(async (element) => {
    await Promise.all(element.getAnimations({ subtree: true }).map(async (animation) => {
      try {
        await animation.finished;
      } catch {
        // A replaced transition is already settled for the current visual state.
      }
    }));
  });
}

async function startReaderControlGeometrySampling(controls: Locator) {
  await controls.evaluate((element) => {
    const readGeometry = () => {
      const bounds = element.getBoundingClientRect();
      const style = getComputedStyle(element);
      return [bounds.top, bounds.bottom, bounds.height, Number(style.opacity)].join(':');
    };
    element.setAttribute('data-reader-geometry-samples', readGeometry());
    let frame = 0;
    const sample = () => {
      const previous = element.getAttribute('data-reader-geometry-samples') ?? '';
      element.setAttribute('data-reader-geometry-samples', `${previous},${readGeometry()}`);
      frame += 1;
      if (frame < 30) window.requestAnimationFrame(sample);
    };
    window.requestAnimationFrame(sample);
  });
}

async function expectReaderControlGeometryStable(controls: Locator) {
  await expect.poll(async () => (
    (await controls.getAttribute('data-reader-geometry-samples'))?.split(',').length ?? 0
  )).toBeGreaterThanOrEqual(20);
  const samples = (await controls.getAttribute('data-reader-geometry-samples'))
    ?.split(',')
    .map((sample) => sample.split(':').map(Number))
    .filter((sample) => sample.length === 4 && sample.every(Number.isFinite)) ?? [];
  expect(samples.length).toBeGreaterThanOrEqual(20);
  const geometryNames = ['top', 'bottom', 'height'] as const;
  const geometrySpreads = geometryNames.map((_, index) => {
    const values = samples.map((sample) => sample[index]);
    return Math.max(...values) - Math.min(...values);
  });
  for (const index of [0, 1, 2]) {
    expect(
      geometrySpreads[index],
      `reader controls ${geometryNames[index]} must remain fixed during panel transitions; spreads=${geometrySpreads.join(',')}`
    ).toBeLessThanOrEqual(1);
  }
  expect(samples.every((sample) => sample[3] === 1)).toBe(true);
}

async function waitForReaderReady(page: Page) {
  await expect.poll(() => page.locator('[data-reader-opening-cover="loading"]').count()).toBe(0);
}

test.beforeEach(async ({ context }) => {
  await context.addCookies([{
    name: 'shuku_session',
    value: 'e2e-session',
    domain: '127.0.0.1',
    path: '/',
    sameSite: 'Lax'
  }]);
  await context.addInitScript(() => {
    localStorage.setItem('shuku:pwa:install-dismissed:user-e2e', '1');
    const attachShadow = Element.prototype.attachShadow;
    Element.prototype.attachShadow = function (init) {
      return attachShadow.call(this, { ...init, mode: 'open' });
    };
  });
});

test('dashboard continue reading navigation commits the reader route without starving the main thread', async ({ page }) => {
  await mockReaderApi(page, 'epub');
  await page.route('**/api/dashboard/**', async (route) => {
    const pathname = new URL(route.request().url()).pathname;
    if (!pathname.endsWith('/continue-reading')) {
      await route.fulfill({ json: { ok: true, data: { books: [], total: 0 } } });
      return;
    }
    await route.fulfill({ json: { ok: true, data: { item: {
      workId: 'work-epub',
      title: 'EPUB 测试读物',
      author: 'Test',
      coverUrl: '',
      mediaKind: 'EBOOK',
      volumeFormat: 'EPUB',
      readerType: 'reflowable',
      resumeVolumeId: 'epub-volume',
      progress: 12,
      lastReadAt: '2026-08-06T03:06:00.000Z',
      chapter: '第一章',
      volumeTitle: '全本',
      narrator: null
    } } } });
  });

  await page.goto('/');
  await page.getByRole('button', { name: '继续阅读' }).click();
  await expect(page).toHaveURL(/\/reader\/epub-volume$/);
  await expect(page.locator('[data-reader-shell="v3"]')).toBeVisible({ timeout: 5_000 });
  await expect(page.getByRole('heading', { name: '主页' })).toHaveCount(0);
});

test('browser reader uses the dynamic viewport and control overlays keep the canvas stable', async ({ page }) => {
  await mockReaderApi(page, 'comic');
  await page.goto('/reader/comic-volume');
  await expect(page.locator('[data-reader-engine="comic-v3"]')).toBeVisible();
  await expect(page.locator('html')).not.toHaveClass(/pwa-native/);

  const shell = page.locator('[data-reader-shell="v3"]');
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
  await page.goto('/reader/epub-volume');
  await expect(page.locator('meta[name="apple-mobile-web-app-capable"]')).toHaveAttribute('content', 'yes');

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
  const topSafeArea = page.locator('[data-reader-top-safe-area="true"]');
  await expect(topSafeArea).toHaveCSS('height', '47px');
  await expect(topSafeArea).toHaveCSS('background-color', 'rgb(253, 246, 234)');
  await showReaderControls(page);
  await page.getByRole('button', { name: '阅读设置' }).click();
  const settingsDialog = page.getByRole('dialog', { name: '设置' });
  await expect(settingsDialog).toBeVisible();
  const toggleCenterOffsets = await Promise.all(['常显时钟', '保持屏幕唤醒', '滑动翻页'].map(async (label) => (
    settingsDialog.getByText(label, { exact: true }).locator('..').locator('..').evaluate((row) => {
      const control = row.querySelector('[data-reader-toggle-control="true"]');
      const knob = row.querySelector('[data-reader-toggle-knob="true"]');
      if (!(control instanceof HTMLElement) || !(knob instanceof HTMLElement)) throw new Error(`Missing toggle control for ${row.textContent ?? ''}`);
      const controlBounds = control.getBoundingClientRect();
      const knobBounds = knob.getBoundingClientRect();
      return Math.abs((controlBounds.top + controlBounds.height / 2) - (knobBounds.top + knobBounds.height / 2));
    })
  )));
  expect(toggleCenterOffsets.every((offset) => offset <= 0.5)).toBe(true);
  await expect.poll(() => settingsDialog.evaluate((element) => element.getBoundingClientRect().height)).toBeGreaterThan(500);
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
      titleInset: element.querySelector<HTMLElement>('#reader-panel-title')!.getBoundingClientRect().top - bounds.top
    };
  });
  expect(safeAreaCoverage.bottom).toBeLessThanOrEqual(safeAreaCoverage.viewportBottom - 10);
  expect(safeAreaCoverage.cssBottom).toBe('0px');
  expect(safeAreaCoverage.paddingTop).toBe('0px');
  expect(safeAreaCoverage.paddingBottom).toBe('0px');
  expect(safeAreaCoverage.titleInset).toBeGreaterThanOrEqual(15);
  expect(safeAreaCoverage.titleInset).toBeLessThanOrEqual(40);
  expect(settingsDialog.getByRole('button', { name: '外观' })).toBeVisible();
  await settingsDialog.getByRole('button', { name: '外观' }).click();
  await page.getByRole('dialog', { name: '外观' }).getByRole('button', { name: '护眼绿' }).click();
  await expect(topSafeArea).toHaveCSS('background-color', 'rgb(232, 240, 227)');
  await expect.poll(() => page.evaluate(() => ({
    statusBarStyle: document.querySelector<HTMLMetaElement>('meta[name="apple-mobile-web-app-status-bar-style"]')?.content,
    themeColors: Array.from(document.querySelectorAll<HTMLMetaElement>('meta[name="theme-color"]')).map((meta) => meta.content)
  }))).toEqual({
    statusBarStyle: 'black-translucent',
    themeColors: ['#E8F0E3', '#E8F0E3']
  });
  await page.getByRole('dialog', { name: '外观' }).getByRole('button', { name: '夜间' }).click();
  await expect(page.getByText('文字外观', { exact: true }).locator('..').locator('..')).toHaveCSS('border-color', 'rgb(51, 65, 85)');
  await page.getByRole('dialog', { name: '外观' }).getByRole('button', { name: '纯黑' }).click();
  await expect(topSafeArea).toHaveCSS('background-color', 'rgb(0, 0, 0)');
  await expect(page.getByText('文字外观', { exact: true }).locator('..').locator('..')).toHaveCSS('border-color', 'rgb(38, 38, 38)');

  const bottomControls = page.locator('[data-reader-controller="bottom-console"]');
  await page.getByRole('dialog', { name: '外观' }).getByRole('button', { name: '关闭面板' }).click();
  for (const [triggerName, dialogName] of [
    ['目录', '目录'],
    ['笔记', '笔记']
  ] as const) {
    await bottomControls.getByRole('button', { name: triggerName, exact: true }).click();
    const dialog = page.getByRole('dialog', { name: dialogName });
    await expect(dialog).toBeVisible();
    await expect.poll(() => dialog.evaluate((element) => getComputedStyle(element).paddingTop)).toBe('0px');
    await dialog.getByRole('button', { name: '关闭面板' }).click();
  }
});

test('mobile EPUB controller exposes the complete thumb dock and persists the current bookmark', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await mockReaderApi(page, 'epub', [], { epubHrefPrefix: 'OEBPS/' });
  await page.goto('/reader/epub-volume');
  await showReaderControls(page);

  const topBar = page.locator('[data-reader-controller="top-minimal"]');
  await expect(topBar.getByRole('button')).toHaveCount(2);
  await expect(topBar).not.toContainText('EPUB 测试读物');
  await expect(topBar).toContainText(/第一章|第 1 页/);
  const topBarBounds = await topBar.locator('[data-reader-top-bar="true"]').boundingBox();
  expect(topBarBounds).not.toBeNull();
  expect(topBarBounds!.width).toBeGreaterThan(350);

  const console = page.locator('[data-reader-controller="bottom-console"]');
  await expect(console).toBeVisible();
  await expect(page.getByRole('button', { name: '目录' })).toBeVisible();
  const notesButton = console.getByRole('button', { name: '笔记', exact: true });
  await expect(notesButton).toBeVisible();
  await expect(page.getByRole('button', { name: '进度' })).toHaveCount(0);
  await expect(console.getByRole('button', { name: '外观' })).toBeVisible();
  await expect(console.getByRole('button', { name: '阅读设置', exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: '阅读设置' })).toBeVisible();
  await expect(console.getByRole('button', { name: '上一章' })).toBeDisabled();
  await expect(console.getByRole('button', { name: '下一章' })).toBeEnabled();
  const consoleSurfaceBounds = await console.locator(':scope > div').boundingBox();
  expect(consoleSurfaceBounds).not.toBeNull();
  expect(consoleSurfaceBounds!.height).toBeGreaterThanOrEqual(120);
  expect(consoleSurfaceBounds!.y + consoleSurfaceBounds!.height).toBeLessThanOrEqual(844 - 10);

  await page.getByRole('button', { name: '目录' }).click();
  const mobileDirectory = page.getByRole('dialog', { name: '目录' });
  await expect(mobileDirectory).toBeVisible();
  await expect.poll(() => mobileDirectory.evaluate((element) => element.getBoundingClientRect().height)).toBeGreaterThan(500);
  await expect(page.getByRole('button', { name: '目录' })).toHaveAttribute('aria-expanded', 'true');
  const mobileDirectoryBounds = await mobileDirectory.boundingBox();
  expect(mobileDirectoryBounds).not.toBeNull();
  expect(mobileDirectoryBounds!.x).toBeGreaterThanOrEqual(10);
  expect(mobileDirectoryBounds!.width).toBeGreaterThanOrEqual(360);
  expect(mobileDirectoryBounds!.height).toBeGreaterThan(500);
  const workspace = page.locator('[data-reader-workspace="true"]');
  await expect(workspace).toHaveAttribute('data-reader-panel', 'toc');
  await expect(workspace).toHaveCount(1);
  await expect(mobileDirectory.getByRole('button', { name: /1.*第一章/ })).toBeVisible();
  await expect(mobileDirectory.getByRole('button', { name: /2.*第二章/ })).toBeVisible();
  if (process.env.SHUKU_READER_TOC_CAPTURE) await page.screenshot({ path: process.env.SHUKU_READER_TOC_CAPTURE });

  await mobileDirectory.getByRole('button', { name: '笔记' }).click();
  await expect(mobileDirectory).not.toBeAttached();
  await expect(workspace).toHaveAttribute('data-reader-panel', 'notes');
  await expect(workspace).toHaveCount(1);
  await expect(page.getByRole('button', { name: '目录' })).toHaveAttribute('aria-expanded', 'false');
  const notesDialog = page.getByRole('dialog', { name: '笔记' });
  await expect(notesDialog).toBeVisible();
  await expect(notesButton).toHaveAttribute('aria-expanded', 'true');
  await expect(notesDialog.getByRole('tab', { name: '书签' })).toHaveAttribute('aria-selected', 'true');
  await expect(notesDialog.getByText('还没有书签')).toBeVisible();
  await notesDialog.getByRole('button', { name: '添加当前位置书签' }).click();
  await expect(page.getByRole('status')).toHaveText('已添加当前书签');
  await expect(notesButton).toHaveAttribute('aria-pressed', 'true');
  await expect(notesDialog.getByRole('button', { name: /^跳转到书签：/ })).toHaveCount(1);
  await expect.poll(() => page.evaluate(() => Object.keys(localStorage).some((key) => key.startsWith('shuku:reader-bookmarks:v3:user-e2e:epub-volume:')))).toBe(true);

  await notesDialog.getByRole('button', { name: '关闭面板' }).click();
  await page.getByRole('button', { name: '目录' }).click();
  const reopenedDirectory = page.getByRole('dialog', { name: '目录' });
  await reopenedDirectory.getByRole('button', { name: /2.*第二章/ }).click();
  await expect(reopenedDirectory).not.toBeAttached();
  await expect.poll(() => page.locator('[data-reader-engine="reflowable-v3"]').getAttribute('data-reader-location-href')).toContain('chapter2.xhtml');

  await notesButton.click();
  await page.getByRole('dialog', { name: '笔记' }).getByRole('button', { name: '添加当前位置书签' }).click();
  await expect(page.getByRole('dialog', { name: '笔记' }).getByRole('button', { name: /^跳转到书签：/ })).toHaveCount(2);
  if (process.env.SHUKU_READER_BOOKMARKS_CAPTURE) await page.screenshot({ path: process.env.SHUKU_READER_BOOKMARKS_CAPTURE });
  await page.getByRole('dialog', { name: '笔记' }).getByRole('button', { name: /^跳转到书签：/ }).first().click();
  await expect(page.getByRole('dialog', { name: '笔记' })).not.toBeAttached();
  await expect.poll(() => page.locator('[data-reader-engine="reflowable-v3"]').getAttribute('data-reader-location-href')).toContain('chapter1.xhtml');

  await notesButton.click();
  const reopenedNotes = page.getByRole('dialog', { name: '笔记' });
  await reopenedNotes.getByRole('button', { name: /^删除书签：/ }).first().click();
  await expect(reopenedNotes.getByRole('button', { name: /^跳转到书签：/ })).toHaveCount(1);

  await reopenedNotes.getByRole('button', { name: '关闭面板' }).click();
  await expect(page.locator('[data-reader-controller="bottom-console"]').getByRole('slider', { name: '阅读进度' })).toBeVisible();
  await notesButton.click();
  const annotationDialog = page.getByRole('dialog', { name: '笔记' });
  await annotationDialog.getByRole('tab', { name: '标注', exact: true }).click();
  await expect(annotationDialog.getByRole('tab', { name: '书内注释' })).toHaveAttribute('aria-selected', 'true');
  await annotationDialog.getByRole('tab', { name: '我的标注' }).click();
  await expect(annotationDialog.getByText('还没有划线或批注')).toBeVisible();
});

test('mobile EPUB progress controls expose chapter arrows without covering the bottom safe gap', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await mockReaderApi(page, 'epub', [], { epubHrefPrefix: 'OEBPS/' });
  await page.goto('/reader/epub-volume');
  await showReaderControls(page);

  const console = page.locator('[data-reader-controller="bottom-console"]');
  const consoleSurface = console.locator(':scope > div');
  const consoleControls = console.locator('[data-reader-console-controls="true"]');
  const mobileProgressControls = console.locator('[data-reader-mobile-progress-controls="true"]');
  const mobileNav = console.locator('[data-reader-console-nav="true"]');
  await expect(consoleSurface).toHaveAttribute('data-reader-console-surface', 'true');
  await expect(consoleControls).toHaveCount(1);
  await expect(mobileProgressControls).toBeVisible();
  await expect(mobileProgressControls).toHaveText('');
  await expect(mobileNav).toBeVisible();
  const compactConsoleBounds = await console.boundingBox();
  expect(compactConsoleBounds).not.toBeNull();
  await expect(console).toHaveCSS('transition-property', /height/);
  await consoleSurface.evaluate((element) => {
    element.setAttribute('data-reader-surface-identity', 'persistent-reader-surface');
  });
  await consoleControls.evaluate((element) => {
    element.setAttribute('data-reader-controls-identity', 'persistent-mobile-controls');
  });
  await mobileNav.evaluate((element) => {
    element.setAttribute('data-reader-nav-identity', 'persistent-mobile-nav');
  });
  const surfaceBounds = await consoleSurface.boundingBox();
  expect(surfaceBounds).not.toBeNull();
  expect(surfaceBounds!.height).toBeGreaterThanOrEqual(120);
  expect(surfaceBounds!.y + surfaceBounds!.height).toBeLessThanOrEqual(834);
  await expect(console.getByRole('button', { name: '字号小' })).toHaveCount(0);
  await expect(console.getByRole('button', { name: '字号大' })).toHaveCount(0);
  await expect(console.getByRole('button', { name: '上一章' })).toBeVisible();
  await expect(console.getByRole('button', { name: '下一章' })).toBeVisible();
  await expect(console.getByRole('button', { name: '笔记' })).toBeVisible();
  const mobilePreviousChapter = console.getByRole('button', { name: '上一章' });
  const mobileNextChapter = console.getByRole('button', { name: '下一章' });
  await expect(mobilePreviousChapter).toBeDisabled();
  await expect(mobileNextChapter).toHaveAttribute('data-reader-chapter-target', /chapter2\.xhtml/);
  await mobileNextChapter.click();
  await expect.poll(() => page.locator('[data-reader-engine="reflowable-v3"]').getAttribute('data-reader-location-href')).toContain('chapter2.xhtml');
  await expect(mobileNextChapter).toBeDisabled();
  await mobilePreviousChapter.click();
  await expect.poll(() => page.locator('[data-reader-engine="reflowable-v3"]').getAttribute('data-reader-location-href')).toContain('chapter1.xhtml');

  await startReaderControlGeometrySampling(mobileNav);
  await console.getByRole('button', { name: '目录', exact: true }).click();
  await expectReaderControlGeometryStable(mobileNav);
  const directoryDialog = page.getByRole('dialog', { name: '目录' });
  await expect(directoryDialog).toBeVisible();
  await expect(mobileProgressControls).toBeHidden();
  await expect(console.getByRole('slider', { name: '阅读进度' })).toBeHidden();
  await expect(mobileNav).toHaveAttribute('data-reader-nav-identity', 'persistent-mobile-nav');
  if (process.env.SHUKU_READER_MOBILE_TOC_CAPTURE) {
    await page.screenshot({ path: process.env.SHUKU_READER_MOBILE_TOC_CAPTURE, fullPage: true });
  }
  await startReaderControlGeometrySampling(mobileNav);
  await directoryDialog.getByRole('button', { name: '关闭面板' }).click();
  await expectReaderControlGeometryStable(mobileNav);
  await expect(mobileProgressControls).toBeVisible();
  await expect(console.getByRole('slider', { name: '阅读进度' })).toBeVisible();

  await startReaderControlGeometrySampling(mobileNav);
  await console.getByRole('button', { name: '阅读设置' }).click();
  await expectReaderControlGeometryStable(mobileNav);
  const settingsDialog = page.getByRole('dialog', { name: '设置' });
  await expect(settingsDialog).toBeVisible();
  await expect.poll(() => console.evaluate((element) => getComputedStyle(element).opacity)).toBe('1');
  await expect(console).toHaveAttribute('data-reader-panel-state', 'settings');
  await expect(settingsDialog).toHaveAttribute('data-reader-workspace', 'true');
  await expect(settingsDialog).toHaveAttribute('data-reader-surface-identity', 'persistent-reader-surface');
  await expect(console.locator('[data-reader-console-surface="true"]')).toHaveCount(1);
  await expect(consoleControls).toHaveCount(1);
  await expect(consoleControls).toHaveAttribute('data-reader-controls-identity', 'persistent-mobile-controls');
  await expect(mobileProgressControls).toBeHidden();
  await expect(console.getByRole('slider', { name: '阅读进度' })).toBeHidden();
  await expect(settingsDialog.getByRole('button', { name: '关闭面板' })).toBeFocused();
  await page.keyboard.press('Shift+Tab');
  await expect(settingsDialog.getByRole('button', { name: '阅读设置', exact: true })).toBeFocused();
  await page.keyboard.press('Tab');
  await expect(settingsDialog.getByRole('button', { name: '进度' })).toHaveCount(0);
  for (const label of ['目录', '笔记', '外观', '阅读设置']) {
    await expect(settingsDialog.getByRole('button', { name: label, exact: true })).toBeVisible();
  }
  const mobileDisplaySection = settingsDialog.getByText('阅读界面', { exact: true }).locator('xpath=ancestor::section');
  const mobilePagingSection = settingsDialog.getByText('翻页设置', { exact: true }).locator('xpath=ancestor::section');
  const [mobileDisplayBox, mobilePagingBox] = await Promise.all([mobileDisplaySection.boundingBox(), mobilePagingSection.boundingBox()]);
  expect(mobileDisplayBox).not.toBeNull();
  expect(mobilePagingBox).not.toBeNull();
  expect(mobilePagingBox!.y).toBeGreaterThan(mobileDisplayBox!.y + mobileDisplayBox!.height - 1);
  const advancedButton = settingsDialog.getByRole('button', { name: '高级设置' });
  await advancedButton.click();
  await expect(advancedButton).toHaveAttribute('aria-expanded', 'true');
  await expect(settingsDialog.locator('#reader-advanced-settings')).toHaveAttribute('data-expanded', 'true');
  await expect(settingsDialog.getByText('段落与内容样式')).toBeVisible();
  await settingsDialog.getByRole('button', { name: '外观' }).click();
  await expect(console).toHaveAttribute('data-reader-panel-state', 'appearance');
  await expect(page.getByRole('dialog', { name: '外观' }).getByRole('group', { name: '主题' })).toBeVisible();
  await page.getByRole('dialog', { name: '外观' }).getByRole('button', { name: '阅读设置', exact: true }).click();
  await expect.poll(() => console.evaluate((element) => element.getBoundingClientRect().height)).toBeGreaterThan(compactConsoleBounds!.height + 200);
  const expandedConsoleBounds = await console.boundingBox();
  expect(expandedConsoleBounds).not.toBeNull();
  expect(expandedConsoleBounds!.height).toBeGreaterThan(compactConsoleBounds!.height + 200);
  await expect(settingsDialog.locator('.shuku-reader-control-workspace')).toHaveCSS('animation-name', 'shuku-reader-workspace-enter');
  await startReaderControlGeometrySampling(mobileNav);
  await page.getByRole('dialog', { name: '设置' }).getByRole('button', { name: '关闭面板' }).click();
  await expectReaderControlGeometryStable(mobileNav);
  await expect(mobileProgressControls).toBeVisible();

  await console.getByRole('button', { name: '笔记' }).click();
  const notesDialog = page.getByRole('dialog', { name: '笔记' });
  await expect(notesDialog.getByRole('tab', { name: '书签' })).toHaveAttribute('aria-selected', 'true');
  await notesDialog.getByRole('tab', { name: '标注', exact: true }).click();
  await expect(notesDialog.getByRole('tab', { name: '书内注释' })).toHaveAttribute('aria-selected', 'true');
});

test('EPUB safe optimization marks only ordinary body paragraphs and remains reversible', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await mockReaderApi(page, 'epub');
  await page.goto('/reader/epub-volume');
  let iframe = await currentEpubIframe(page);
  await iframe.contentFrame().locator('body').evaluate((body) => {
    const [plain, duplicate] = Array.from(body.querySelectorAll<HTMLParagraphElement>('p'));
    if (!plain || !duplicate) throw new Error('EPUB fixture requires two body paragraphs');
    plain.id = 'smart-plain';
    duplicate.id = 'smart-duplicate';
    duplicate.style.textIndent = '2em';
    duplicate.textContent = `　${duplicate.textContent ?? ''}`;
  });

  await showReaderControls(page);
  await page.getByRole('button', { name: '阅读设置' }).click();
  const settingsDialog = page.getByRole('dialog', { name: '设置' });
  const safeOptimization = settingsDialog.getByRole('checkbox', { name: '安全优化' });
  const safeOptimizationLabel = settingsDialog.getByText('安全优化', { exact: true });
  await safeOptimizationLabel.click();
  await expect(safeOptimization).not.toBeChecked();
  await safeOptimizationLabel.click();
  await expect(safeOptimization).toBeChecked();
  iframe = await currentEpubIframe(page);

  const optimized = await iframe.contentFrame().locator('body').evaluate((body) => {
    const state = (id: string) => body.querySelector<HTMLElement>(`#${id}`)?.className ?? '';
    return {
      plain: state('smart-plain'),
      duplicate: state('smart-duplicate'),
      duplicateText: body.querySelector('#smart-duplicate')?.textContent ?? ''
    };
  });
  expect(optimized.plain).toContain('shuku-smart-auto-indent');
  expect(optimized.duplicate).toContain('shuku-smart-deduplicate-indent');
  expect(optimized.duplicateText.startsWith('　')).toBe(true);

  await safeOptimizationLabel.click();
  await expect(safeOptimization).not.toBeChecked();
  iframe = await currentEpubIframe(page);
  await expect.poll(() => iframe.contentFrame().locator('#smart-plain').evaluate((element) => element.className)).not.toContain('shuku-smart-');
  await expect.poll(() => iframe.contentFrame().locator('#smart-duplicate').evaluate((element) => element.className)).not.toContain('shuku-smart-');
});

test('tablet comic controller keeps format-appropriate actions and an inline progress scrubber', async ({ page }) => {
  await page.setViewportSize({ width: 834, height: 1112 });
  await mockReaderApi(page, 'comic');
  await page.goto('/reader/comic-volume');
  await showReaderControls(page);

  const console = page.locator('[data-reader-controller="bottom-console"]');
  const consoleControls = console.locator('[data-reader-console-controls="true"]');
  await expect(consoleControls).toHaveCount(1);
  await consoleControls.evaluate((element) => {
    element.setAttribute('data-reader-controls-identity', 'persistent-desktop-controls');
  });
  const consoleBounds = await console.locator(':scope > div').boundingBox();
  expect(consoleBounds).not.toBeNull();
  expect(consoleBounds!.x).toBeGreaterThan(16);
  expect(consoleBounds!.width).toBeLessThan(834 - 32);
  await expect(page.getByRole('slider', { name: '阅读进度' })).toBeVisible();
  await expect(page.getByRole('button', { name: '进度' })).toHaveCount(0);
  await expect(page.getByRole('button', { name: '标注与批注' })).toHaveCount(0);
  await expect(page.getByRole('button', { name: '目录' })).toBeVisible();
  await expect(console.getByRole('button', { name: '笔记', exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: '阅读设置' })).toBeVisible();

  const directoryButton = page.getByRole('button', { name: '目录' });
  const directoryButtonBounds = await directoryButton.boundingBox();
  await startReaderControlGeometrySampling(consoleControls);
  await directoryButton.click();
  await expectReaderControlGeometryStable(consoleControls);
  const directoryDialog = page.getByRole('dialog', { name: '目录' });
  await expect(directoryDialog).toBeVisible();
  await expect(directoryButton).toHaveAttribute('aria-expanded', 'true');
  await expect(consoleControls).toHaveCount(1);
  await expect(consoleControls).toHaveAttribute('data-reader-controls-identity', 'persistent-desktop-controls');
  await expect(console.getByRole('slider', { name: '阅读进度' })).toBeVisible();
  const directoryBounds = await directoryDialog.boundingBox();
  expect(directoryButtonBounds).not.toBeNull();
  expect(directoryBounds).not.toBeNull();
  expect(directoryBounds!.y + directoryBounds!.height).toBeLessThanOrEqual(1112 - 10);
  expect(directoryBounds!.x).toBeGreaterThanOrEqual(16);
  expect(directoryBounds!.width).toBeGreaterThan(780);
  const workspace = page.locator('[data-reader-workspace="true"]');
  await expect(workspace).toHaveAttribute('data-reader-panel', 'toc');
  await directoryDialog.getByRole('button', { name: '外观' }).click();
  await expect(directoryDialog).not.toBeAttached();
  await expect(directoryButton).toHaveAttribute('aria-expanded', 'false');
  const settingsDialog = page.getByRole('dialog', { name: '外观' });
  await expect(settingsDialog).toBeVisible();
  await expect(workspace).toHaveAttribute('data-reader-panel', 'appearance');
  await expect(workspace).toHaveCount(1);
  await expect(settingsDialog.getByRole('group', { name: '主题' }).getByRole('button')).toHaveCount(5);
  await expect(settingsDialog.getByText('主题', { exact: true })).toHaveCount(0);
  if (process.env.SHUKU_READER_SETTINGS_CAPTURE) {
    await page.screenshot({ path: process.env.SHUKU_READER_SETTINGS_CAPTURE });
  }
  const settingsBounds = await settingsDialog.boundingBox();
  expect(settingsBounds).not.toBeNull();
  expect(settingsBounds!.width).toBeGreaterThan(780);
  expect(settingsBounds!.y + settingsBounds!.height).toBeLessThanOrEqual(1112 - 10);
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
  if (!process.env.SHUKU_READER_SETTINGS_CAPTURE) {
    await startReaderControlGeometrySampling(consoleControls);
    await settingsDialog.getByRole('button', { name: '关闭面板' }).click();
    await expectReaderControlGeometryStable(consoleControls);
  }
});

test('PDF uses the same responsive reader workspace for appearance, settings, directory, and notes', async ({ page }) => {
  await page.setViewportSize({ width: 1024, height: 900 });
  await mockReaderApi(page, 'pdf');
  await page.goto('/reader/pdf-volume');
  await showReaderControls(page);

  const console = page.locator('[data-reader-controller="bottom-console"]');
  await console.getByRole('button', { name: '阅读设置' }).click();
  const workspace = page.locator('[data-reader-workspace="true"]');
  await expect(workspace).toHaveAttribute('data-reader-panel', 'settings');
  const panelSurface = workspace.locator('[data-reader-panel-surface="true"]');
  const consoleControls = workspace.locator('[data-reader-console-controls="true"]');
  const [panelSurfaceBox, consoleControlsBox] = await Promise.all([
    panelSurface.boundingBox(),
    consoleControls.boundingBox()
  ]);
  expect(panelSurfaceBox).not.toBeNull();
  expect(consoleControlsBox).not.toBeNull();
  expect(panelSurfaceBox!.width).toBeGreaterThanOrEqual(399.5);
  expect(panelSurfaceBox!.width).toBeLessThanOrEqual(400.5);
  expect(panelSurfaceBox!.height).toBeGreaterThanOrEqual(499.5);
  expect(panelSurfaceBox!.height).toBeLessThanOrEqual(500.5);
  expect(panelSurfaceBox!.width).toBeLessThan(consoleControlsBox!.width);
  expect(panelSurfaceBox!.y + panelSurfaceBox!.height).toBeLessThan(consoleControlsBox!.y);
  expect(Math.abs(panelSurfaceBox!.x + panelSurfaceBox!.width - (consoleControlsBox!.x + consoleControlsBox!.width))).toBeLessThanOrEqual(1);
  await expect(page.getByRole('dialog', { name: '设置' }).getByRole('group', { name: '适配' })).toBeVisible();
  await expect(page.getByRole('dialog', { name: '设置' }).getByRole('group', { name: '阅读方式' })).toBeVisible();
  await expect(page.getByRole('dialog', { name: '设置' }).getByRole('group', { name: '页面旋转' })).toBeVisible();
  await expect(page.getByRole('dialog', { name: '设置' }).getByRole('group', { name: '自动裁白边' })).toBeVisible();
  const desktopDisplaySection = workspace.getByText('阅读界面', { exact: true }).locator('xpath=ancestor::section');
  const desktopPagingSection = workspace.getByText('翻页设置', { exact: true }).locator('xpath=ancestor::section');
  const [desktopDisplayBox, desktopPagingBox, desktopWorkspaceBox] = await Promise.all([
    desktopDisplaySection.boundingBox(),
    desktopPagingSection.boundingBox(),
    panelSurface.boundingBox()
  ]);
  expect(desktopDisplayBox).not.toBeNull();
  expect(desktopPagingBox).not.toBeNull();
  expect(desktopWorkspaceBox).not.toBeNull();
  expect(desktopPagingBox!.y).toBeGreaterThan(desktopDisplayBox!.y + desktopDisplayBox!.height - 1);
  expect(desktopDisplayBox!.width).toBeGreaterThan(desktopWorkspaceBox!.width * 0.8);
  const [desktopFlowBox, desktopFitBox] = await Promise.all([
    workspace.getByRole('group', { name: '阅读方式' }).boundingBox(),
    workspace.getByRole('group', { name: '适配' }).boundingBox()
  ]);
  expect(desktopFlowBox).not.toBeNull();
  expect(desktopFitBox).not.toBeNull();
  expect(desktopFitBox!.y).toBeGreaterThan(desktopFlowBox!.y + desktopFlowBox!.height - 1);

  await workspace.getByRole('button', { name: '外观' }).click();
  await expect(workspace).toHaveAttribute('data-reader-panel', 'appearance');
  await expect(page.getByRole('dialog', { name: '外观' }).getByRole('group', { name: '主题' })).toBeVisible();
  await expect(page.getByRole('dialog', { name: '外观' }).getByRole('button', { name: '护眼绿' })).toBeVisible();
  const [appearancePanelBox, appearanceConsoleBox] = await Promise.all([
    panelSurface.boundingBox(),
    consoleControls.boundingBox()
  ]);
  expect(appearancePanelBox).not.toBeNull();
  expect(appearanceConsoleBox).not.toBeNull();
  expect(Math.abs(appearancePanelBox!.x + appearancePanelBox!.width - (appearanceConsoleBox!.x + appearanceConsoleBox!.width))).toBeLessThanOrEqual(1);

  await workspace.getByRole('button', { name: '目录' }).click();
  await expect(workspace).toHaveAttribute('data-reader-panel', 'toc');
  await expect(page.getByRole('dialog', { name: '目录' }).getByRole('button', { name: /1.*第 1 页/ })).toBeVisible();
  const [tocPanelBox, tocConsoleBox] = await Promise.all([
    panelSurface.boundingBox(),
    consoleControls.boundingBox()
  ]);
  expect(tocPanelBox).not.toBeNull();
  expect(tocConsoleBox).not.toBeNull();
  expect(Math.abs(tocPanelBox!.x - tocConsoleBox!.x)).toBeLessThanOrEqual(1);

  await workspace.getByRole('button', { name: '笔记' }).click();
  await expect(workspace).toHaveAttribute('data-reader-panel', 'notes');
  await expect(page.getByRole('dialog', { name: '笔记' }).getByRole('tab', { name: '书签' })).toHaveAttribute('aria-selected', 'true');
  const [notesPanelBox, notesConsoleBox] = await Promise.all([
    panelSurface.boundingBox(),
    consoleControls.boundingBox()
  ]);
  expect(notesPanelBox).not.toBeNull();
  expect(notesConsoleBox).not.toBeNull();
  expect(Math.abs(notesPanelBox!.x - notesConsoleBox!.x)).toBeLessThanOrEqual(1);
  await expect(workspace).toHaveCount(1);
});

test('desktop EPUB appearance, settings, and advanced controls keep every option in one column', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1200 });
  await mockReaderApi(page, 'epub');
  await page.goto('/reader/epub-volume');
  await showReaderControls(page);

  const console = page.locator('[data-reader-controller="bottom-console"]');
  await console.getByRole('button', { name: '外观' }).click();
  const appearanceDialog = page.getByRole('dialog', { name: '外观' });
  const [fontSizeBox, quickFontSizeBox] = await Promise.all([
    appearanceDialog.getByRole('button', { name: '字号减少' }).boundingBox(),
    appearanceDialog.getByRole('group', { name: '快捷字号' }).boundingBox()
  ]);
  expect(fontSizeBox).not.toBeNull();
  expect(quickFontSizeBox).not.toBeNull();
  expect(quickFontSizeBox!.y).toBeGreaterThan(fontSizeBox!.y + fontSizeBox!.height - 1);
  if (process.env.SHUKU_READER_DESKTOP_APPEARANCE_CAPTURE) {
    await page.screenshot({ path: process.env.SHUKU_READER_DESKTOP_APPEARANCE_CAPTURE, fullPage: true });
  }

  await appearanceDialog.getByRole('button', { name: '阅读设置', exact: true }).click();
  const settingsDialog = page.getByRole('dialog', { name: '设置' });
  const [displaySectionBox, pagingSectionBox, flowBox, spreadBox, safeOptimizationBox, deduplicateIndentBox] = await Promise.all([
    settingsDialog.getByText('阅读界面', { exact: true }).locator('xpath=ancestor::section').boundingBox(),
    settingsDialog.getByText('翻页设置', { exact: true }).locator('xpath=ancestor::section').boundingBox(),
    settingsDialog.getByRole('group', { name: '阅读方式' }).boundingBox(),
    settingsDialog.getByRole('group', { name: '页面' }).boundingBox(),
    settingsDialog.getByText('安全优化', { exact: true }).locator('..').boundingBox(),
    settingsDialog.getByText('重复缩进去重', { exact: true }).locator('..').boundingBox()
  ]);
  expect(displaySectionBox).not.toBeNull();
  expect(pagingSectionBox).not.toBeNull();
  expect(flowBox).not.toBeNull();
  expect(spreadBox).not.toBeNull();
  expect(safeOptimizationBox).not.toBeNull();
  expect(deduplicateIndentBox).not.toBeNull();
  expect(pagingSectionBox!.y).toBeGreaterThan(displaySectionBox!.y + displaySectionBox!.height - 1);
  expect(spreadBox!.y).toBeGreaterThan(flowBox!.y + flowBox!.height - 1);
  expect(deduplicateIndentBox!.y).toBeGreaterThan(safeOptimizationBox!.y + safeOptimizationBox!.height - 1);
  await settingsDialog.getByRole('button', { name: '高级设置' }).click();
  const [paragraphIndentBox, paragraphSpacingBox, keyboardPageTurnBox, volumePageTurnBox] = await Promise.all([
    settingsDialog.getByRole('group', { name: '段首缩进' }).boundingBox(),
    settingsDialog.getByRole('group', { name: '段间距' }).boundingBox(),
    settingsDialog.getByText('键盘翻页', { exact: true }).locator('..').boundingBox(),
    settingsDialog.getByText('音量键翻页', { exact: true }).locator('..').boundingBox()
  ]);
  expect(paragraphIndentBox).not.toBeNull();
  expect(paragraphSpacingBox).not.toBeNull();
  expect(keyboardPageTurnBox).not.toBeNull();
  expect(volumePageTurnBox).not.toBeNull();
  expect(paragraphSpacingBox!.y).toBeGreaterThan(paragraphIndentBox!.y + paragraphIndentBox!.height - 1);
  expect(volumePageTurnBox!.y).toBeGreaterThan(keyboardPageTurnBox!.y + keyboardPageTurnBox!.height - 1);
  if (process.env.SHUKU_READER_DESKTOP_ADVANCED_CAPTURE) {
    await page.screenshot({ path: process.env.SHUKU_READER_DESKTOP_ADVANCED_CAPTURE, fullPage: true });
  }
});

test('desktop EPUB settings stays near 400 by 500 and scrolls internally without chrome', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1600 });
  await mockReaderApi(page, 'epub');
  await page.goto('/reader/epub-volume');
  await showReaderControls(page);

  const console = page.locator('[data-reader-controller="bottom-console"]');
  await console.getByRole('button', { name: '阅读设置' }).click();
  const settingsDialog = page.getByRole('dialog', { name: '设置' });
  const settingsPanel = settingsDialog.locator('[data-reader-panel-surface="true"]');
  const settingsScrollArea = settingsDialog.locator('[data-pwa-scroll="true"]');
  const settingsPanelBox = await settingsPanel.boundingBox();
  expect(settingsPanelBox).not.toBeNull();
  expect(settingsPanelBox!.width).toBeGreaterThanOrEqual(399.5);
  expect(settingsPanelBox!.width).toBeLessThanOrEqual(400.5);
  expect(settingsPanelBox!.height).toBeGreaterThanOrEqual(499.5);
  expect(settingsPanelBox!.height).toBeLessThanOrEqual(500.5);
  const initialPanelHeight = await console.evaluate((element) => element.getBoundingClientRect().height);

  await settingsDialog.getByRole('button', { name: '高级设置' }).click();
  await expect(settingsDialog.locator('#reader-advanced-settings')).toHaveAttribute('data-expanded', 'true');
  await expect.poll(() => console.evaluate((element) => element.getBoundingClientRect().height)).toBeLessThanOrEqual(initialPanelHeight + 1);
  await expect.poll(() => settingsScrollArea.evaluate((element) => element.scrollHeight > element.clientHeight + 1)).toBe(true);

  await page.setViewportSize({ width: 1440, height: 640 });
  await expect.poll(() => console.evaluate((element) => element.getBoundingClientRect().height)).toBeLessThanOrEqual(640 - 96);
  await expect.poll(() => settingsScrollArea.evaluate((element) => element.scrollHeight > element.clientHeight + 1)).toBe(true);
  await expect(settingsScrollArea).toHaveCSS('scrollbar-width', 'none');
  await settingsScrollArea.evaluate((element) => {
    element.scrollTop = element.scrollHeight;
  });
  await expect.poll(() => settingsScrollArea.evaluate((element) => element.scrollTop)).toBeGreaterThan(0);
});

test('an EPUB without other media or volume choices shows only its chapter hierarchy', async ({ page }, testInfo) => {
  const consoleErrors: string[] = [];
  page.on('console', (message) => {
    if (message.type() === 'error') consoleErrors.push(message.text());
  });
  const usesDesktopWorkspace = !testInfo.project.name.includes('iphone');
  if (usesDesktopWorkspace) await page.setViewportSize({ width: 1440, height: 900 });
  await mockReaderApi(page, 'epub', [], { epubHrefPrefix: 'OEBPS/' });
  await page.goto('/reader/epub-volume');
  await showReaderControls(page);
  if (usesDesktopWorkspace) {
    const previousChapter = page.getByRole('button', { name: '上一章' });
    const nextChapter = page.getByRole('button', { name: '下一章' });
    await expect(previousChapter).toBeDisabled();
    await nextChapter.click();
    await expect.poll(() => page.locator('[data-reader-engine="reflowable-v3"]').getAttribute('data-reader-location-href')).toContain('chapter2.xhtml');
    await previousChapter.click();
    await expect.poll(() => page.locator('[data-reader-engine="reflowable-v3"]').getAttribute('data-reader-location-href')).toContain('chapter1.xhtml');
  }
  const directoryButton = page.getByRole('button', { name: '目录' });
  const directoryButtonBounds = await directoryButton.boundingBox();
  const dockSurface = directoryButton.locator('[data-reader-dock-surface="true"]');
  const hoverSurfaceBox = usesDesktopWorkspace ? await (async () => {
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
  expect(selectedSurfaceBox!.x - directoryButtonBox!.x).toBeGreaterThanOrEqual(4);
  expect(selectedSurfaceBox!.y - directoryButtonBox!.y).toBeGreaterThanOrEqual(4);
  if (usesDesktopWorkspace) expect(hoverSurfaceBox).not.toBeNull();
  const directoryBounds = await directory.boundingBox();
  expect(directoryButtonBounds).not.toBeNull();
  expect(directoryBounds).not.toBeNull();
  expect(directoryBounds!.x).toBeGreaterThanOrEqual(10);
  expect(directoryBounds!.width).toBeGreaterThanOrEqual(usesDesktopWorkspace ? 1000 : (page.viewportSize()?.width ?? 390) - 30);
  if (usesDesktopWorkspace) {
    expect(Math.abs((directoryBounds!.x + directoryBounds!.width / 2) - (page.viewportSize()?.width ?? 1440) / 2)).toBeLessThanOrEqual(1);
  }
  expect(directoryBounds!.y + directoryBounds!.height).toBeLessThanOrEqual((page.viewportSize()?.height ?? 900) - 10);
  await expect(directory.getByText('默认版本', { exact: true })).toHaveCount(0);
  await expect(directory.getByText('版本', { exact: true })).toHaveCount(0);
  await expect(directory.getByText('卷册', { exact: true })).toHaveCount(0);
  await expect(directory.getByText('章节', { exact: true })).toBeVisible();
  await expect(directory.getByRole('button', { name: /1.*第一章/ })).toBeVisible();
  await expect(directory.getByRole('button', { name: /2.*第二章/ })).toBeVisible();
  const panelCapturePath = process.env.SHUKU_READER_PANEL_CAPTURE;
  if (panelCapturePath) await page.screenshot({ path: panelCapturePath });
  await page.mouse.click(8, 100);
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
            <div class="label">实现：目录在统一阅读控制台内展开</div>
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
  await page.goto('/reader/comic-volume');
  await expect(page.locator('[data-reader-engine="comic-v3"]')).toBeVisible();
  await expect(page.getByText('第 1 页 / 共 3 页').first()).toBeVisible();
  await showReaderControls(page);
  const previousButton = page.getByRole('button', { name: '上一章' });
  await expect(previousButton).toBeDisabled();
  await page.keyboard.press('Escape');

  await page.keyboard.press('ArrowRight');
  await expect(page.getByText('第 2 页 / 共 3 页').first()).toBeVisible();
  await expect.poll(() => progressBodies.some((body) => (
    body.location?.type === 'comic'
    && body.location.volumeId === 'comic-volume'
    && body.location.pageIndex === 2
  )), { timeout: 8_000 }).toBe(true);

  await showReaderControls(page);
  await page.getByRole('button', { name: '阅读设置' }).click();
  const settingsDialog = page.getByRole('dialog', { name: '设置' });
  await expect(settingsDialog).toBeVisible();
  await expect(page.getByRole('button', { name: '关闭面板' })).toBeFocused();
  await page.keyboard.press('Shift+Tab');
  await expect(settingsDialog.getByRole('button', { name: '阅读设置', exact: true })).toBeFocused();
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
  await expect(page.getByRole('dialog', { name: '设置' })).toBeVisible();
  await page.getByRole('dialog', { name: '设置' }).getByRole('button', { name: '外观' }).click();
  await page.getByRole('button', { name: '纯黑' }).click();
  await expect(page.locator('[data-reader-shell="v3"]')).toHaveAttribute('data-reader-theme', 'black');
  await page.getByRole('dialog', { name: '外观' }).getByRole('button', { name: '阅读设置', exact: true }).click();
  await page.getByRole('button', { name: '高级设置' }).click();
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
  await page.locator('[data-reader-shell="v3"] > div').first().focus();
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
  await expect(page.locator('[data-reader-engine="comic-v3"]')).toBeVisible();
  await expect(page.locator('[data-reader-shell="v3"]')).toHaveAttribute('data-reader-theme', 'black');
  await showReaderControls(page);
  await page.getByRole('button', { name: '阅读设置' }).click();
  await page.getByRole('button', { name: '恢复阅读默认设置' }).click();
  await expect(page.locator('[data-reader-shell="v3"]')).toHaveAttribute('data-reader-theme', 'warm');
});

test('comic vertical flow keeps stable slots while scrolling into the next page', async ({ page }) => {
  await mockReaderApi(page, 'comic');
  await page.goto('/reader/comic-volume');
  const engine = page.locator('[data-reader-engine="comic-v3"]');
  await expect(engine).toBeVisible();
  await showReaderControls(page);
  await page.getByRole('button', { name: '阅读设置' }).click();
  await page.getByRole('dialog', { name: '设置' }).getByRole('button', { name: '竖向连续', exact: true }).click();

  const stream = engine.locator('[data-comic-continuous="true"]');
  const firstSlot = stream.locator('[data-comic-continuous-page="1"]');
  await expect(stream.locator('[data-comic-continuous-page]')).toHaveCount(3);
  await firstSlot.evaluate((element) => { element.dataset.e2eStableSlot = 'first'; });
  await stream.evaluate((element) => {
    const second = element.querySelector<HTMLElement>('[data-comic-continuous-page="2"]');
    if (!second) throw new Error('The second comic page slot is unavailable');
    element.scrollTop = second.offsetTop;
    element.dispatchEvent(new Event('scroll'));
  });

  await expect(stream).toHaveAttribute('data-comic-continuous-current', '2');
  await expect(firstSlot).toHaveAttribute('data-e2e-stable-slot', 'first');
  await expect(stream.locator('img')).toHaveCount(3);
});

test('PDF.js renders a bounded canvas and selectable text layer', async ({ page }) => {
  await mockReaderApi(page, 'pdf');
  await page.goto('/reader/pdf-volume');
  await expect(page.locator('[data-reader-engine="pdf-v3"] canvas')).toBeVisible();
  await expect(page.locator('[data-reader-engine="pdf-v3"] .textLayer')).toBeAttached();
  await expect(page.getByText('第 1 页 / 共 1 页').first()).toBeVisible();
  const canvasPixels = await page.locator('[data-reader-engine="pdf-v3"] canvas').evaluate((canvas: HTMLCanvasElement) => canvas.width * canvas.height);
  expect(canvasPixels).toBeLessThanOrEqual(12_000_000);
});

test('corrupted PDF fails safely with retry and library actions', async ({ page }) => {
  await mockReaderApi(page, 'pdf', [], { pdfBody: Buffer.from([0, 1, 2, 3, 4, 5]) });
  await page.goto('/reader/pdf-volume');
  await expect(page.getByText('阅读器加载失败')).toBeVisible({ timeout: 30_000 });
  await expect(page.getByRole('button', { name: '重试' })).toBeVisible();
  await expect(page.getByRole('button', { name: '返回书库' })).toBeVisible();
  await expect(page.locator('[data-reader-engine="pdf-v3"] canvas')).toHaveCount(0);
});

test('legacy mobile reader links return to the responsive web detail page', async ({ page }) => {
  await mockReaderApi(page, 'comic');
  await page.goto('/reader/comic-volume?from=mobile&tab=shelf');
  await expect(page.locator('[data-reader-engine="comic-v3"]')).toBeVisible();
  await showReaderControls(page);
  await page.getByRole('button', { name: '返回详情页' }).click();
  await expect(page).toHaveURL(/\/works\/work-comic$/);
});

test('a comic bookmark target opens the saved page in its requested volume', async ({ page }) => {
  await mockReaderApi(page, 'comic');
  await page.goto('/reader/comic-volume?page=3');
  await expect(page.locator('[data-reader-engine="comic-v3"]')).toBeVisible();
  await expect(page.getByText('第 3 页 / 共 3 页').first()).toBeVisible();
  await expect(page.locator('[data-comic-spread-slot="current"] img')).toHaveAttribute('alt', '第 3 页');
});

test('50 consecutive comic turns keep one engine and a bounded DOM surface', async ({ page }) => {
  test.skip(test.info().project.name !== 'chromium', 'Long-running leak sentinel runs once in Chromium');
  await mockReaderApi(page, 'comic');
  await page.goto('/reader/comic-volume');
  await expect(page.locator('[data-reader-engine="comic-v3"]')).toBeVisible();
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
  await expect(page.locator('[data-reader-engine="comic-v3"]')).toHaveCount(1);
  await expect(page.locator('[data-comic-spread-slot]')).toHaveCount(3);
  await expect(page.locator('[data-comic-spread-slot="current"] img')).toHaveCount(1);
  await expect.poll(() => page.locator('[data-reader-engine="comic-v3"] img').count()).toBeLessThanOrEqual(3);
  await expect(page.locator('[data-reader-engine="comic-v3"] canvas, [data-reader-engine="comic-v3"] iframe')).toHaveCount(0);
});

test('EPUB reload restores the pending local CFI while an explicit href still wins', async ({ page }) => {
  const progressBodies: Array<Record<string, any>> = [];
  await mockReaderApi(page, 'epub', progressBodies, { progressStatus: 503 });

  await page.goto('/reader/epub-volume');
  let iframe = page.locator('[data-reader-engine="reflowable-v3"] iframe').first();
  await expect(iframe.contentFrame().getByText('第一章 开始阅读')).toBeVisible();
  await waitForReaderReady(page);

  await page.keyboard.press('ArrowRight');
  await expect.poll(() => progressBodies.some((body) => (
    body.location?.type === 'reflowable'
    && typeof body.location.href === 'string'
    && body.location.href.endsWith('chapter2.xhtml')
  )), { timeout: 8_000 }).toBe(true);
  await expect.poll(() => progressBodies.some((body) => (
    body.location?.type === 'reflowable'
    && typeof body.location.cfi === 'string'
    && body.location.cfi.startsWith('epubcfi(')
  )), { timeout: 8_000 }).toBe(true);

  await page.reload();
  await waitForReaderReady(page);
  await showReaderControls(page);
  await page.getByRole('button', { name: '目录' }).click();
  const restoredDirectory = page.getByRole('dialog', { name: '目录' });
  await expect(restoredDirectory.getByRole('button', { name: /2.*第二章/ })).toHaveAttribute('aria-current', 'location');
  await page.keyboard.press('Escape');

  await page.goto('/reader/epub-volume?href=chapter1.xhtml');
  iframe = await currentEpubIframe(page);
  await expect(iframe.contentFrame().getByText('第一章 开始阅读')).toBeVisible();
});

test('EPUB cross-spine paging uses one foliate step without a custom track or animation', async ({ page }) => {
  await page.addInitScript(() => {
    const state = window as typeof window & { __epubPageTurnAnimations?: number };
    state.__epubPageTurnAnimations = 0;
    const originalAnimate = Element.prototype.animate;
    Element.prototype.animate = function (keyframes, options) {
      if ((this as HTMLElement).dataset.readerEngine === 'reflowable-v3') {
        state.__epubPageTurnAnimations = (state.__epubPageTurnAnimations ?? 0) + 1;
      }
      return originalAnimate.call(this, keyframes, options);
    };
  });
  const progressBodies: Array<Record<string, any>> = [];
  await mockReaderApi(page, 'epub', progressBodies);
  await page.goto('/reader/epub-volume');
  const iframe = page.locator('[data-reader-engine="reflowable-v3"] iframe').first();
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
    body.location?.type === 'reflowable'
    && typeof body.location.href === 'string'
    && body.location.href.endsWith('chapter2.xhtml')
  )), { timeout: 8_000 }).toBe(true);
  await expect(page.locator('[data-epub-continuous-track], [data-epub-default-track]')).toHaveCount(0);
  await expect.poll(() => page.evaluate(() => (
    window as typeof window & { __epubPageTurnAnimations?: number }
  ).__epubPageTurnAnimations ?? 0)).toBe(0);
});

test('EPUB scrolled flow keeps adjacent chapters mounted in one stable stream', async ({ page }) => {
  const progressBodies: Array<Record<string, any>> = [];
  await page.setViewportSize({ width: 1600, height: 900 });
  await mockReaderApi(page, 'epub', progressBodies);
  await page.goto('/reader/epub-volume');
  let iframe = await currentEpubIframe(page);
  await expect(iframe.contentFrame().getByText('第一章 开始阅读')).toBeVisible();
  const paginatedWidth = await iframe.evaluate((element) => element.getBoundingClientRect().width);
  expect(paginatedWidth).toBeLessThanOrEqual(defaultPreferences.epub.pageWidth + 1);

  await showReaderControls(page);
  await page.getByRole('button', { name: '阅读设置' }).click();
  await page.getByRole('dialog', { name: '设置' }).getByRole('button', { name: '滚动', exact: true }).click();
  const engine = page.locator('[data-reader-engine="reflowable-v3"]');
  await expect(engine).toHaveAttribute('data-reader-flow', 'scrolled');
  const stream = engine.locator('[data-reflowable-continuous="true"]');
  const firstSlot = stream.locator('[data-reflowable-continuous-section="0"]');
  const secondSlot = stream.locator('[data-reflowable-continuous-section="1"]');
  await expect(firstSlot.locator('iframe')).toHaveCount(1);
  await expect(secondSlot.locator('iframe')).toHaveCount(1);
  const scrolledMeasure = await firstSlot.evaluate((element) => {
    const bounds = element.getBoundingClientRect();
    const viewport = element.parentElement?.getBoundingClientRect();
    return {
      width: bounds.width,
      centered: viewport ? Math.abs((bounds.left + bounds.width / 2) - (viewport.left + viewport.width / 2)) : Number.POSITIVE_INFINITY
    };
  });
  expect(Math.abs(scrolledMeasure.width - paginatedWidth)).toBeLessThanOrEqual(1);
  expect(scrolledMeasure.centered).toBeLessThanOrEqual(1);
  await firstSlot.evaluate((element) => { element.dataset.e2eStableSlot = 'first'; });
  await firstSlot.locator('iframe').evaluate((element) => { element.dataset.e2eStableFrame = 'first'; });

  await page.getByRole('dialog', { name: '设置' }).getByRole('button', { name: '外观' }).click();
  await page.getByRole('dialog', { name: '外观' }).getByRole('group', { name: '页宽' }).getByRole('button', { name: '窄', exact: true }).click();
  await expect.poll(() => firstSlot.evaluate((element) => {
    const bounds = element.getBoundingClientRect();
    const viewport = element.parentElement?.getBoundingClientRect();
    return {
      width: bounds.width,
      centered: viewport ? Math.abs((bounds.left + bounds.width / 2) - (viewport.left + viewport.width / 2)) : Number.POSITIVE_INFINITY
    };
  })).toEqual({ width: 760, centered: 0 });

  await stream.evaluate((element) => {
    const second = element.querySelector<HTMLElement>('[data-reflowable-continuous-section="1"]');
    if (!second) throw new Error('The next stable section slot is unavailable');
    element.scrollTop = Math.max(0, second.offsetTop - element.clientHeight * 0.2);
  });
  await iframe.contentFrame().locator('body').evaluate((body) => {
    body.dispatchEvent(new WheelEvent('wheel', { bubbles: true, deltaY: 120 }));
  });
  await expect.poll(() => engine.getAttribute('data-reader-location-href')).toContain('chapter2.xhtml');
  iframe = secondSlot.locator('iframe');
  await expect(iframe.contentFrame().getByText('第二章 翻页验证')).toBeVisible();
  await expect(firstSlot).toHaveAttribute('data-e2e-stable-slot', 'first');
  await expect(firstSlot.locator('iframe')).toHaveAttribute('data-e2e-stable-frame', 'first');

  await stream.evaluate((element) => { element.scrollTop = 0; });
  await page.waitForTimeout(220);
  await iframe.contentFrame().locator('body').evaluate((body) => {
    body.dispatchEvent(new WheelEvent('wheel', { bubbles: true, deltaY: -120 }));
  });
  await expect.poll(() => engine.getAttribute('data-reader-location-href')).toContain('chapter1.xhtml');
  await expect(firstSlot.locator('iframe')).toHaveAttribute('data-e2e-stable-frame', 'first');
});

test('EPUB scrolled flow resolves section-normalized document links without opening a tab', async ({ page }) => {
  await mockReaderApi(page, 'epub');
  await page.goto('/reader/epub-volume');
  await showReaderControls(page);
  await page.getByRole('button', { name: '阅读设置' }).click();
  await page.getByRole('dialog', { name: '设置' }).getByRole('button', { name: '滚动', exact: true }).click();

  const engine = page.locator('[data-reader-engine="reflowable-v3"]');
  const firstFrame = engine.locator('[data-reflowable-continuous-section="0"] iframe');
  const pagesBeforeNavigation = page.context().pages().length;
  await firstFrame.contentFrame().locator('body').evaluate((body) => {
    const anchor = body.ownerDocument.createElement('a');
    anchor.href = 'chapter2.xhtml';
    anchor.target = '_blank';
    anchor.textContent = '第二章';
    body.append(anchor);
    anchor.click();
  });

  await expect.poll(() => engine.getAttribute('data-reader-location-href')).toContain('chapter2.xhtml');
  await expect(engine.locator('[data-reflowable-continuous-section="1"] iframe').contentFrame().getByText('第二章 翻页验证')).toBeVisible();
  expect(page.context().pages()).toHaveLength(pagesBeforeNavigation);
});

test('EPUB scrolled flow resumes inside a chapter instead of its beginning', async ({ page }) => {
  await page.addInitScript((preferences) => {
    window.localStorage.setItem('shuku:reader:device-defaults:v1:user-e2e', JSON.stringify(preferences));
  }, { ...defaultPreferences, epub: { ...defaultPreferences.epub, flow: 'scrolled' } });
  const progressBodies: Array<Record<string, any>> = [];
  await mockReaderApi(page, 'epub', progressBodies, {
    resumeLocation: {
      type: 'reflowable',
      format: 'epub',
      cfi: 'epubcfi(/6/2)',
      href: 'chapter1.xhtml',
      progression: 0.25,
      foliate: { continuous: { sectionFraction: 0.5 } }
    },
    progressPercent: 25
  });
  await page.goto('/reader/epub-volume');

  const engine = page.locator('[data-reader-engine="reflowable-v3"]');
  const stream = engine.locator('[data-reflowable-continuous="true"]');
  await expect(engine).toHaveAttribute('data-reader-flow', 'scrolled');
  await expect.poll(() => stream.evaluate((element) => element.scrollTop)).toBeGreaterThan(10);
  await expect.poll(async () => Number(await engine.getAttribute('data-reader-location-progression'))).toBeGreaterThan(0.05);
  await expect.poll(() => engine.getAttribute('data-reader-location-href')).toContain('chapter1.xhtml');
  await expect.poll(() => progressBodies.some((body) => (
    typeof body.location?.foliate?.continuous?.sectionFraction === 'number'
    && body.location.foliate.continuous.sectionFraction > 0
  ))).toBe(true);
});

test('EPUB scrolled flow leaves touch movement native and defers remeasurement until scroll settles', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await mockReaderApi(page, 'epub');
  await page.goto('/reader/epub-volume');
  await showReaderControls(page);
  await page.getByRole('button', { name: '阅读设置' }).click();
  await page.getByRole('dialog', { name: '设置' }).getByRole('button', { name: '滚动', exact: true }).click();

  const stream = page.locator('[data-reflowable-continuous="true"]');
  const iframe = await currentEpubIframe(page);
  const body = iframe.contentFrame().locator('body');
  await expect(stream).toHaveCSS('touch-action', 'pan-y');
  await expect(stream).toHaveCSS('overflow-y', 'auto');

  const initialFrameHeight = await iframe.evaluate((element) => element.getBoundingClientRect().height);
  const touchMoveWasNotCancelled = await body.evaluate((element) => {
    const touch = { clientX: 195, clientY: 500, screenX: 195, screenY: 600 };
    const dispatch = (type: string, touches: readonly object[]) => {
      const event = new Event(type, { bubbles: true, cancelable: true });
      Object.defineProperties(event, {
        changedTouches: { value: touches.length ? touches : [touch] },
        touches: { value: touches }
      });
      return element.dispatchEvent(event);
    };
    dispatch('touchstart', [touch]);
    const moveAllowed = dispatch('touchmove', [touch]);
    const spacer = element.ownerDocument.createElement('div');
    spacer.dataset.e2eNativeScrollSpacer = 'true';
    spacer.style.height = '800px';
    element.append(spacer);
    return moveAllowed;
  });
  expect(touchMoveWasNotCancelled).toBe(true);
  await expect(stream).toHaveAttribute('data-native-scroll-state', 'active');
  await page.waitForTimeout(100);
  await expect.poll(() => iframe.evaluate((element) => element.getBoundingClientRect().height)).toBe(initialFrameHeight);

  await body.evaluate((element) => {
    const event = new Event('touchend', { bubbles: true, cancelable: true });
    Object.defineProperties(event, {
      changedTouches: { value: [{}] },
      touches: { value: [] }
    });
    element.dispatchEvent(event);
  });
  await expect(stream).toHaveAttribute('data-native-scroll-state', 'idle');
  await expect.poll(() => iframe.evaluate((element) => element.getBoundingClientRect().height)).toBeGreaterThan(initialFrameHeight + 300);
});

test('EPUB scrolled flow tap zones move by one viewport without jumping chapters', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await mockReaderApi(page, 'epub');
  await page.goto('/reader/epub-volume');
  await showReaderControls(page);
  await page.getByRole('button', { name: '阅读设置' }).click();
  await page.getByRole('dialog', { name: '设置' }).getByRole('button', { name: '滚动', exact: true }).click();
  await page.getByRole('dialog', { name: '设置' }).getByRole('button', { name: '关闭面板' }).click();

  const engine = page.locator('[data-reader-engine="reflowable-v3"]');
  const stream = engine.locator('[data-reflowable-continuous="true"]');
  const firstFrame = stream.locator('[data-reflowable-continuous-section="0"] iframe');
  const firstBody = firstFrame.contentFrame().locator('body');
  await firstBody.evaluate((body) => {
    const spacer = body.ownerDocument.createElement('div');
    spacer.dataset.e2eViewportPagingSpacer = 'true';
    spacer.style.height = '300vh';
    body.append(spacer);
  });
  await expect.poll(() => firstFrame.evaluate((frame) => frame.getBoundingClientRect().height)).toBeGreaterThan(2_000);
  await stream.evaluate((element) => { element.scrollTop = 0; });
  await expect.poll(() => engine.getAttribute('data-reader-location-href')).toContain('chapter1.xhtml');

  const viewportHeight = await stream.evaluate((element) => element.clientHeight);
  await clickVisibleReflowableZone(firstBody, 0.9);
  await expect.poll(() => stream.evaluate((element) => element.scrollTop)).toBeGreaterThan(viewportHeight * 0.9);
  await expect.poll(() => stream.evaluate((element) => element.scrollTop)).toBeLessThanOrEqual(viewportHeight * 1.05);
  await expect.poll(() => engine.getAttribute('data-reader-location-href')).toContain('chapter1.xhtml');

  await clickVisibleReflowableZone(firstBody, 0.1);
  await expect.poll(() => stream.evaluate((element) => element.scrollTop)).toBeLessThan(2);
  await expect.poll(() => engine.getAttribute('data-reader-location-href')).toContain('chapter1.xhtml');
});

test('EPUB restores a section location when switching from scrolling back to pagination', async ({ page }) => {
  const paginationRestoreErrors: string[] = [];
  page.on('console', (message) => {
    if (message.type() === 'error' && /Cannot read properties of undefined.*length/u.test(message.text())) {
      paginationRestoreErrors.push(message.text());
    }
  });
  await mockReaderApi(page, 'epub');
  await page.goto('/reader/epub-volume?href=chapter2.xhtml');
  const engine = page.locator('[data-reader-engine="reflowable-v3"]');
  await expect((await currentEpubIframe(page)).contentFrame().getByText('第二章 翻页验证')).toBeVisible();

  await showReaderControls(page);
  await page.getByRole('button', { name: '阅读设置' }).click();
  await page.getByRole('dialog', { name: '设置' }).getByRole('button', { name: '滚动', exact: true }).click();
  await expect(engine).toHaveAttribute('data-reader-flow', 'scrolled');
  await page.getByRole('button', { name: '分页', exact: true }).click();
  await expect(engine).toHaveAttribute('data-reader-flow', 'paginated');
  await expect((await currentEpubIframe(page)).contentFrame().getByText('第二章 翻页验证')).toBeVisible();
  expect(paginationRestoreErrors).toHaveLength(0);
});

test('EPUB swipe submits one navigation command without a visual paging track', async ({ page }) => {
  const progressBodies: Array<Record<string, any>> = [];
  await mockReaderApi(page, 'epub', progressBodies);
  await page.goto('/reader/epub-volume');
  const iframe = await currentEpubIframe(page);
  await expect(iframe.contentFrame().getByText('第一章 开始阅读')).toBeVisible();
  const iframeHtml = iframe.contentFrame().locator('html');
  await expect(iframeHtml).toHaveAttribute('data-shuku-input-bridge', 'ready');
  await waitForReaderReady(page);
  const touchEventsAvailable = await iframe.contentFrame().locator('body').evaluate((body) => {
    const view = body.ownerDocument.defaultView;
    if (!view?.Touch || !view.TouchEvent) return false;
    const width = body.ownerDocument.documentElement.clientWidth;
    const clientY = body.ownerDocument.documentElement.clientHeight * 0.5;
    try {
      const start = new view.Touch({ identifier: 1, target: body, clientX: width * 0.85, clientY, screenX: width * 0.85, screenY: clientY });
      const move = new view.Touch({ identifier: 1, target: body, clientX: width * 0.45, clientY, screenX: width * 0.45, screenY: clientY });
      const end = new view.Touch({ identifier: 1, target: body, clientX: width * 0.15, clientY, screenX: width * 0.15, screenY: clientY });
      body.dispatchEvent(new view.TouchEvent('touchstart', { bubbles: true, changedTouches: [start], touches: [start] }));
      body.dispatchEvent(new view.TouchEvent('touchmove', { bubbles: true, cancelable: true, changedTouches: [move], touches: [move] }));
      body.dispatchEvent(new view.TouchEvent('touchend', { bubbles: true, changedTouches: [end], touches: [] }));
      return true;
    } catch {
      return false;
    }
  });
  if (!touchEventsAvailable) {
    await expect(page.locator('[data-reader-engine="reflowable-v3"]')).toHaveAttribute('data-reader-input-bridge', 'ready');
    await expect(page.locator('[data-epub-continuous-track], [data-epub-default-track]')).toHaveCount(0);
    return;
  }
  await expect.poll(() => progressBodies.some((body) => (
    body.location?.type === 'reflowable'
    && typeof body.location.href === 'string'
    && body.location.href.endsWith('chapter2.xhtml')
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
  await page.goto('/reader/epub-volume');
  const iframe = page.locator('[data-reader-engine="reflowable-v3"] iframe').first();
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
    const engine = document.querySelector<HTMLElement>('[data-reader-engine="reflowable-v3"]');
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
  await clickVisibleReflowableZone(firstBody, 0.9);
  await expect.poll(() => page.evaluate(() => (
    window as typeof window & { __epubNavigationStarts?: number }
  ).__epubNavigationStarts ?? 0)).toBe(1);
  await expect.poll(() => progressBodies.some((body) => (
    body.location?.type === 'reflowable'
    && typeof body.location.href === 'string'
    && body.location.href.endsWith('chapter2.xhtml')
  )), { timeout: 8_000 }).toBe(true);
  const secondBody = (await currentEpubIframe(page)).contentFrame().locator('body');
  await clickVisibleReflowableZone(secondBody, 0.9);
  await expect(secondBody.getByText('第二章 翻页验证')).toBeVisible();
  await expect(page.locator('[data-shuku-epub-transition-placeholder="true"]')).toHaveCount(0);
  const currentFrame = await currentEpubIframe(page);
  await expect(page.locator('[data-reader-engine="reflowable-v3"]')).toHaveAttribute('data-reader-theme', 'ready');
  const transitionAudit = await page.evaluate(() => {
    const audit = (window as typeof window & {
      __epubTransitionAudit?: { placeholderSeen: boolean; violations: number; stop: () => void };
    }).__epubTransitionAudit;
    audit?.stop();
    return audit ? { placeholderSeen: audit.placeholderSeen, violations: audit.violations } : null;
  });
  expect(transitionAudit).toEqual({ placeholderSeen: false, violations: 0 });
  expect(await page.evaluate(() => (
    window as typeof window & { __epubNavigationStarts?: number }
  ).__epubNavigationStarts ?? 0)).toBe(2);
});

test('EPUB document links stay inside the reader while external links use the application boundary', async ({ page }) => {
  await mockReaderApi(page, 'epub');
  await page.goto('/reader/epub-volume');
  await expect((await currentEpubIframe(page)).contentFrame().getByText('第一章 开始阅读')).toBeVisible();

  const pagesBeforeInternalNavigation = page.context().pages().length;
  await (await currentEpubIframe(page)).contentFrame().locator('body').evaluate((body) => {
    const document = body.ownerDocument;
    const anchor = document.createElement('a');
    anchor.setAttribute('href', 'chapter2.xhtml');
    anchor.setAttribute('target', '_blank');
    anchor.textContent = '第二章';
    document.body.append(anchor);
    anchor.click();
  });
  await expect((await currentEpubIframe(page)).contentFrame().getByText('第二章 翻页验证')).toBeVisible();
  expect(page.context().pages()).toHaveLength(pagesBeforeInternalNavigation);

  await page.evaluate(() => {
    const state = window as typeof window & { __readerExternalLinks?: string[] };
    state.__readerExternalLinks = [];
    window.open = ((href?: string | URL) => {
      state.__readerExternalLinks?.push(String(href ?? ''));
      return null;
    }) as typeof window.open;
  });
  const externalEventCancelled = await (await currentEpubIframe(page)).contentFrame().locator('body').evaluate((body) => {
    let node: Node | null = body.ownerDocument.defaultView?.frameElement ?? null;
    let view: Element | null = null;
    while (node) {
      const root = node.getRootNode();
      const host = 'host' in root ? root.host as Element : null;
      if (!host || typeof host.localName !== 'string') break;
      if (host.localName === 'foliate-view') {
        view = host;
        break;
      }
      node = host;
    }
    if (!view) throw new Error('The EPUB view is unavailable');
    const ViewCustomEvent = view.ownerDocument.defaultView?.CustomEvent;
    if (!ViewCustomEvent) throw new Error('The EPUB event constructor is unavailable');
    return !view.dispatchEvent(new ViewCustomEvent('external-link', {
      bubbles: true,
      cancelable: true,
      detail: { href: 'https://example.com/reference' }
    }));
  });
  expect(externalEventCancelled).toBe(true);
  await expect.poll(() => page.evaluate(() => (
    window as typeof window & { __readerExternalLinks?: string[] }
  ).__readerExternalLinks)).toEqual(['https://example.com/reference']);
});

test('EPUB iframe is scriptless and receives the selected theme snapshot', async ({ page }) => {
  const progressBodies: unknown[] = [];
  const maliciousRequests: string[] = [];
  page.on('request', (request) => {
    const url = new URL(request.url());
    if (url.pathname === '/api/epub-pwn' || url.hostname === 'attacker.invalid') maliciousRequests.push(request.url());
  });
  await mockReaderApi(page, 'epub', progressBodies);
  await page.goto('/reader/epub-volume?href=chapter2.xhtml');
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
  const startsCompact = (page.viewportSize()?.width ?? Number.POSITIVE_INFINITY) <= 640;
  expect(pageLayout.paddingTop).toBeGreaterThanOrEqual(startsCompact ? 16 : 32);
  expect(pageLayout.paddingBottom).toBeGreaterThanOrEqual(32);
  const engine = page.locator('[data-reader-engine="reflowable-v3"]');
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
  expect(Math.abs(pageLayout.leftGap - pageLayout.rightGap)).toBeLessThanOrEqual(2);

  const initialViewport = page.viewportSize();
  if (initialViewport) {
    await page.setViewportSize({ width: Math.max(320, initialViewport.width - 240), height: initialViewport.height });
    await expect.poll(async () => {
      const resizedEngineWidth = await engine.evaluate((element) => element.getBoundingClientRect().width);
      const resizedIframe = await currentEpubIframe(page);
      return resizedIframe.contentFrame().locator('body').evaluate((body, width) => {
        const bounds = body.getBoundingClientRect();
        const viewportWidth = body.ownerDocument.documentElement.clientWidth;
        return {
          fitsViewport: bounds.width <= width + 1,
          horizontallyContained: bounds.left >= 0 && viewportWidth - bounds.right >= 0
        };
      }, resizedEngineWidth);
    }).toEqual({ fitsViewport: true, horizontallyContained: true });
    iframe = await currentEpubIframe(page);

    await page.setViewportSize({ width: 390, height: 844 });
    const mobileIframe = await currentEpubIframe(page);
    await expect(engine).toHaveAttribute('data-epub-viewport-layout', 'compact');
    const mobilePaginator = page.locator('foliate-paginator');
    await expect(mobilePaginator).toHaveAttribute('gap', '0%');
    await expect.poll(() => mobilePaginator.evaluate((element) => (
      Number.parseFloat(getComputedStyle(element).paddingBottom)
    ))).toBeGreaterThanOrEqual(10);
    await expect.poll(() => mobileIframe.contentFrame().locator('body').evaluate((body) => {
      const style = getComputedStyle(body);
      const rootStyle = getComputedStyle(body.ownerDocument.documentElement);
      const viewportHeight = body.ownerDocument.documentElement.clientHeight;
      const expectedTop = Math.max(16, Math.min(32, viewportHeight * 0.025));
      const expectedBottom = Math.max(32, Math.min(64, viewportHeight * 0.05));
      return {
        inlinePaddingMatchesFont: Math.abs(Number.parseFloat(style.paddingLeft) - Number.parseFloat(style.fontSize)) < 0.1
          && Math.abs(Number.parseFloat(style.paddingRight) - Number.parseFloat(style.fontSize)) < 0.1,
        rootPaddingLeft: Number.parseFloat(rootStyle.paddingLeft),
        rootPaddingRight: Number.parseFloat(rootStyle.paddingRight),
        topIsHalved: Math.abs(Number.parseFloat(style.paddingTop) - expectedTop) < 0.1,
        bottomIsUnchanged: Math.abs(Number.parseFloat(style.paddingBottom) - expectedBottom) < 0.1
      };
    })).toEqual({
      inlinePaddingMatchesFont: true,
      rootPaddingLeft: 0,
      rootPaddingRight: 0,
      topIsHalved: true,
      bottomIsUnchanged: true
    });
    await page.setViewportSize(initialViewport);
    await expect(engine).toHaveAttribute('data-epub-viewport-layout', startsCompact ? 'compact' : 'regular');
    await expect(page.locator('foliate-paginator')).toHaveAttribute('gap', startsCompact ? '0%' : '7%');
    const restoredBottomInset = await page.locator('foliate-paginator').evaluate((element) => (
      Number.parseFloat(getComputedStyle(element).paddingBottom)
    ));
    if (startsCompact) expect(restoredBottomInset).toBeGreaterThanOrEqual(10);
    else expect(restoredBottomInset).toBe(0);
    iframe = await currentEpubIframe(page);
  }

  await showReaderControls(page);
  await expect(page.locator('[data-reader-controller="top-minimal"]')).not.toContainText(/EPUB 阅读|第二章|全书 \d+%/);
  await expect(page.locator('[data-reader-controller="top-minimal"]').getByRole('button')).toHaveCount(2);
  await expect(page.locator('[data-reader-shell="v3"]')).not.toContainText('共 2 页');
  await expect(page.locator('[data-reader-shell="v3"]')).not.toContainText(/第 \d+ \/ 2 章/);
  await page.getByRole('button', { name: '阅读设置' }).click();
  const settingsDialog = page.getByRole('dialog', { name: '设置' });
  await expect(settingsDialog).toBeVisible();
  await settingsDialog.getByRole('button', { name: '外观' }).click();
  const appearanceDialog = page.getByRole('dialog', { name: '外观' });
  await page.getByRole('button', { name: '暖色' }).click();
  await expect(page.locator('[data-reader-shell="v3"]')).toHaveAttribute('data-reader-theme', 'warm');
  await expect.poll(async () => iframe.contentFrame().locator('body').evaluate((body) => getComputedStyle(body).backgroundColor)).toBe('rgb(253, 246, 234)');
  const hostileTheme = await iframe.contentFrame().locator('#hostile-theme').evaluate((element) => {
    const style = getComputedStyle(element);
    return { color: style.color, background: style.backgroundColor, font: style.fontFamily, inlineStyle: element.getAttribute('style') };
  });
  expect(hostileTheme.color).toBe('rgb(43, 33, 24)');
  expect(hostileTheme.background).toBe('rgba(0, 0, 0, 0)');
  expect(hostileTheme.font).not.toContain('monospace');
  expect(hostileTheme.inlineStyle ?? '').not.toMatch(/(?:color|background|font-family|line-height)\s*:/i);

  await appearanceDialog.getByRole('button', { name: '行距大' }).click();
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

  await page.getByRole('dialog', { name: '外观' }).getByRole('button', { name: startsCompact ? '设置' : '阅读设置', exact: true }).click();
  await page.getByRole('button', { name: '滚动', exact: true }).click();
  await expect(engine).toHaveAttribute('data-reader-flow', 'scrolled');
  iframe = await currentEpubIframe(page);
  await expect.poll(async () => iframe.contentFrame().locator('body').evaluate((body) => Number.parseFloat(getComputedStyle(body).paddingTop))).toBeGreaterThanOrEqual(startsCompact ? 14 : 28);
  await page.getByRole('button', { name: '分页', exact: true }).click();
  await expect(engine).toHaveAttribute('data-reader-flow', 'paginated');
  iframe = await currentEpubIframe(page);
  await expect(page.locator('[data-reader-engine="reflowable-v3"]')).toHaveCount(1);

  await page.getByRole('dialog', { name: '设置' }).getByRole('button', { name: '外观' }).click();

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
    await expect(page.locator('[data-reader-shell="v3"]')).toHaveAttribute('data-reader-theme', theme);
    await expect.poll(async () => iframe.contentFrame().locator('body').evaluate((body) => getComputedStyle(body).backgroundColor)).toBe(background);
  }

  await page.waitForTimeout(1_800);
  const progressCountAfterSettings = progressBodies.length;
  await page.waitForTimeout(1_800);
  expect(progressBodies).toHaveLength(progressCountAfterSettings);

  await page.reload();
  await expect(page.locator('[data-reader-engine="reflowable-v3"] iframe').first()).toBeVisible();
  await expect(page.locator('[data-reader-shell="v3"]')).toHaveAttribute('data-reader-theme', 'day');
  await showReaderControls(page);
  await page.getByRole('button', { name: '阅读设置' }).click();
  await page.getByRole('button', { name: '恢复阅读默认设置' }).click();
  await expect(page.locator('[data-reader-shell="v3"]')).toHaveAttribute('data-reader-theme', 'warm');
});
