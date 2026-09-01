import { expect, test, type Page, type Route } from '@playwright/test';
import { TextReader, Uint8ArrayWriter, ZipWriter } from '@zip.js/zip.js';

test.beforeEach(async ({ context }) => {
  await context.addCookies([{ name: 'shuku_session', value: 'readium-e2e-session', domain: '127.0.0.1', path: '/' }]);
});

const chapterOne = `<?xml version="1.0" encoding="UTF-8"?><html xmlns="http://www.w3.org/1999/xhtml"><head><title>第一章</title></head><body>
  <h1 id="chapter-title">第一章 Readium 验收</h1>
  <p id="opening">天地玄黄，宇宙洪荒。</p>
  ${Array.from({ length: 24 }, (_, index) => `<p id="filler-${index}">定位夹具正文 ${index + 1}：用于确保恢复目标不在首屏。</p>`).join('')}
  <p id="target">跨端恢复目标正文。</p>
</body></html>`;
const chapterTwo = `<?xml version="1.0" encoding="UTF-8"?><html xmlns="http://www.w3.org/1999/xhtml"><head><title>第二章</title></head><body><h1 id="chapter-two">第二章</h1><p id="second-opening">第二章正文。</p></body></html>`;

type EpubFixtureItem = Readonly<{ href: string; title: string; body: string }>;

async function createEpub(items: readonly EpubFixtureItem[] = [
  { href: 'chapter1.xhtml', title: '第一章', body: chapterOne },
  { href: 'chapter2.xhtml', title: '第二章', body: chapterTwo }
], language: string | null = 'zh-CN'): Promise<Uint8Array> {
  const writer = new ZipWriter(new Uint8ArrayWriter());
  await writer.add('mimetype', new TextReader('application/epub+zip'), { level: 0 });
  await writer.add('META-INF/container.xml', new TextReader('<?xml version="1.0"?><container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0"><rootfiles><rootfile full-path="content.opf" media-type="application/oebps-package+xml"/></rootfiles></container>'));
  const manifest = items.map((item, index) => `<item id="item-${index}" href="${item.href}" media-type="application/xhtml+xml"/>`).join('');
  const spine = items.map((_item, index) => `<itemref idref="item-${index}"/>`).join('');
  await writer.add('content.opf', new TextReader(`<?xml version="1.0"?><package xmlns="http://www.idpf.org/2007/opf" version="3.0"><metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>Readium E2E</dc:title>${language ? `<dc:language>${language}</dc:language>` : ''}</metadata><manifest><item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>${manifest}</manifest><spine>${spine}</spine></package>`));
  await writer.add('nav.xhtml', new TextReader(`<?xml version="1.0"?><html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops"><head><title>目录</title></head><body><nav epub:type="toc"><ol>${items.map((item) => `<li><a href="${item.href}">${item.title}</a></li>`).join('')}</ol></nav></body></html>`));
  for (const item of items) await writer.add(item.href, new TextReader(item.body));
  return writer.close();
}

function exactLocator(cssSelector: string, highlight: string, progression = 0, href = 'chapter1.xhtml', position = 1) {
  return {
    kind: 'reflowable',
    engineLocator: {
      engine: 'readium', platform: 'web', version: 'readium-ts:2.8.2',
      payload: { href, type: 'application/xhtml+xml', locations: { cssSelector, fragments: [cssSelector.slice(1)], progression, position }, text: { highlight } }
    }
  } as const;
}

function readerBootstrap(progressSnapshot: Record<string, unknown> | null, legacyPercent = 0) {
  const resource = { id: 'epub-resource', bookId: 'book-epub', title: '全本', resourceIndex: null, sortOrder: 0, format: 'EPUB', readerType: 'reflowable', pageCount: null, chapterCount: 2, durationMs: null, trackCount: null, progress: legacyPercent, lastReadAt: null };
  return { ok: true, data: {
    schemaVersion: 4, userId: 'user-e2e', readerType: 'reflowable', sourceFormat: 'epub',
    book: { id: 'book-epub', title: 'Readium E2E', author: 'Test', coverUrl: null },
    resourceCompleted: false,
    resource, availableResources: [resource],
    assets: [{ id: 'epub-asset', kind: 'CONTENT', mimeType: 'application/epub+zip', sizeBytes: 100, durationMs: null, discNumber: null, trackNumber: null, sortOrder: 0, url: '/api/assets/epub-asset' }],
    units: [],
    capabilities: { canGoNext: true, canGoPrevious: false, canJumpToProgress: false, canJumpToHref: true, canJumpToIndex: true, canZoom: false, canSelectText: true, supportsPagination: true, supportsScrolling: true, supportsSpreads: true },
    progressSnapshot, progressPercent: legacyPercent
  } };
}

async function fulfillApi(route: Route, snapshot: Record<string, unknown> | null, legacyPercent: number, writes: unknown[], epub: Uint8Array) {
  const request = route.request(); const pathname = new URL(request.url()).pathname;
  if (pathname.endsWith('/bootstrap')) return route.fulfill({ json: readerBootstrap(snapshot, legacyPercent) });
  if (pathname === '/api/resources/epub-resource') return route.fulfill({ json: { ok: true, data: { resource: {
    id: 'epub-resource', bookId: 'book-epub', sourceNodeId: 'source-epub', title: '全本', format: 'EPUB', readerType: 'reflowable',
    sortOrder: 0, importStatus: 'READY', coverUrl: '', sizeBytes: epub.byteLength, readable: true, kindleSendAvailable: false,
    assets: [{ id: 'epub-asset', title: 'Original', resourceId: 'epub-resource', sourceNodeId: 'source-asset', role: 'PRIMARY', mimeType: 'application/epub+zip', sourceFormat: 'EPUB', sizeBytes: epub.byteLength, size: `${epub.byteLength} B`, mtimeMs: 1234, sortOrder: 0, url: '/api/assets/epub-asset', downloadUrl: '/api/assets/epub-asset?download=true' }]
  } } } });
  if (pathname === '/api/assets/epub-asset') return route.fulfill({ status: 200, contentType: 'application/epub+zip', headers: { 'Content-Length': String(epub.byteLength), 'X-Asset-Version': `${epub.byteLength}:1234` }, body: Buffer.from(epub) });
  if (pathname.endsWith('/progress')) {
    if (request.method() === 'GET') {
      const revision = typeof snapshot?.revision === 'number' ? snapshot.revision : 0;
      const etag = `"reader-progress-${revision}"`;
      return route.fulfill({
        headers: { ETag: etag },
        json: { ok: true, data: { schemaVersion: 4, progressSnapshot: snapshot } }
      });
    }
    const body: unknown = request.postDataJSON(); writes.push(body);
    const item = body as { clientId: string; locator: Record<string, unknown>; baseRevision: number };
    return route.fulfill({ json: { ok: true, data: { schemaVersion: 4, clientId: item.clientId, revision: item.baseRevision + 1, locator: item.locator, displayPercent: 0, receivedAtEpochMillis: Date.now() } } });
  }
  if (pathname === '/api/auth/me') return route.fulfill({ json: { ok: true, data: { user: { id: 'user-e2e', email: 'e2e@example.com', name: 'E2E', role: 'admin' }, authorization: { isAdmin: true, canManageSystem: true, allLibraryScopes: true, libraryIds: [], canViewManualImports: true, authzVersion: 1 } } } });
  return route.fulfill({ json: { ok: true, data: {} } });
}

async function installReaderRoutes(
  page: Page,
  snapshot: Record<string, unknown> | null = null,
  legacyPercent = 0,
  items?: readonly EpubFixtureItem[],
  language: string | null = 'zh-CN'
) {
  const writes: unknown[] = [];
  const epub = await createEpub(items, language);
  await page.route('**/api/**', (route) => fulfillApi(route, snapshot, legacyPercent, writes, epub));
  return writes;
}

async function visibleReadiumFrame(page: Page) {
  const shell = page.locator('[data-reader-shell="v3"]'); await expect(shell).toBeVisible();
  const frame = shell.locator('iframe:visible').first(); await expect(frame).toBeVisible(); return frame;
}

test('Readium opens a cached original EPUB without manifest, positions or chapter requests', async ({ page }) => {
  const requests: string[] = [];
  page.on('request', (request) => requests.push(new URL(request.url()).pathname));
  const writes = await installReaderRoutes(page); await page.goto('/reader/epub-resource');
  const frame = await visibleReadiumFrame(page); await expect(frame.contentFrame().getByText('第一章 Readium 验收')).toBeVisible();
  await expect.poll(() => writes.length, { timeout: 10_000 }).toBeGreaterThan(0);
  const write = writes.at(-1) as { locator: ReturnType<typeof exactLocator> };
  expect(write.locator.engineLocator.engine).toBe('readium');
  expect(write.locator.kind).toBe('reflowable');
  expect(write.locator.engineLocator.payload.href).toBe('chapter1.xhtml');
  expect(write.locator.engineLocator.payload.locations.cssSelector || write.locator.engineLocator.payload.locations.fragments?.length || write.locator.engineLocator.payload.text?.highlight).toBeTruthy();
  expect(requests.filter((path) => /\/publication\/(?:manifest|positions|chapter)/.test(path))).toEqual([]);
  expect(requests.filter((path) => path === '/api/assets/epub-asset')).toHaveLength(1);
});

test('Readium sanitizes active EPUB content and never lets authored content initiate network requests', async ({ page }) => {
  const requests: string[] = [];
  let authoredNetworkRequests = 0;
  page.on('request', (request) => requests.push(new URL(request.url()).pathname));
  await page.route('https://reader-safety.invalid/**', async (route) => {
    authoredNetworkRequests += 1;
    await route.abort();
  });
  await installReaderRoutes(page, null, 0, [{
    href: 'chapter1.xhtml',
    title: 'Unsafe',
    body: `<?xml version="1.0"?>
      <!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.1//EN" "http://www.w3.org/TR/xhtml11/DTD/xhtml11.dtd">
      <html xmlns="http://www.w3.org/1999/xhtml"><head><title>Sanitized</title>
      <style>@import url("https://reader-safety.invalid/author.css"); .remote{background:url("https://reader-safety.invalid/background.png")}</style>
      <script id="authored-active-script">fetch("https://reader-safety.invalid/script-fetch")</script></head><body onload="fetch('https://reader-safety.invalid/onload')">
      <h1 id="safe-heading">安全正文仍然可读</h1>
      <a id="unsafe-link" href="javascript:alert(1)">unsafe</a>
      <img id="remote-image" src="https://reader-safety.invalid/remote.png" alt="remote"/>
      <svg xmlns="http://www.w3.org/2000/svg"><image id="remote-svg" href="https://reader-safety.invalid/vector.png"/></svg>
      </body></html>`
  }]);

  await page.goto('/reader/epub-resource');
  const frame = await visibleReadiumFrame(page);
  const content = frame.contentFrame();
  await expect(content.locator('#safe-heading')).toBeVisible();
  await expect(content.locator('#authored-active-script')).toHaveCount(0);
  await expect(content.locator('#unsafe-link')).not.toHaveAttribute('href', /.+/);
  await expect(content.locator('#remote-image')).not.toHaveAttribute('src', /.+/);
  await expect(content.locator('#remote-svg')).not.toHaveAttribute('href', /.+/);
  await expect.poll(() => authoredNetworkRequests).toBe(0);
  expect(requests.filter((path) => path === '/api/assets/epub-asset')).toHaveLength(1);
  expect(requests.filter((path) => /\/publication\/(?:manifest|positions|chapter)/.test(path))).toEqual([]);
});

test('Readium progress advances while paging inside the same chapter', async ({ page }) => {
  await installReaderRoutes(page);
  await page.goto('/reader/epub-resource');
  const frame = await visibleReadiumFrame(page);
  const bounds = await frame.boundingBox();
  if (!bounds) throw new Error('READIUM_FRAME_BOUNDS_MISSING');
  const progress = page.locator('input[aria-label="阅读进度"]:visible');
  await expect(progress).toHaveAttribute('step', '0.1');
  const before = Number(await progress.inputValue());

  await page.mouse.click(bounds.x + bounds.width - 20, bounds.y + bounds.height / 2);

  await expect.poll(async () => Number(await progress.inputValue())).toBeGreaterThan(before);
});

test('Readium highlights the current chapter and enables adjacent chapter navigation', async ({ page }) => {
  await installReaderRoutes(page);
  await page.goto('/reader/epub-resource');
  const frame = await visibleReadiumFrame(page);
  const bounds = await frame.boundingBox();
  if (!bounds) throw new Error('READIUM_FRAME_BOUNDS_MISSING');
  await page.mouse.click(bounds.x + bounds.width / 2, bounds.y + bounds.height / 2);
  await page.getByRole('button', { name: '目录' }).click();

  const firstChapter = page.getByRole('button', { name: /第一章/ });
  const secondChapter = page.getByRole('button', { name: /第二章/ });
  const previous = page.locator('button[aria-label="上一章"]:visible');
  const next = page.locator('button[aria-label="下一章"]:visible');
  await expect(firstChapter).toHaveAttribute('aria-current', 'location');
  await expect(previous).toBeDisabled();
  await expect(next).toBeEnabled();

  await next.click();
  await expect(secondChapter).toHaveAttribute('aria-current', 'location');
  await expect(previous).toBeEnabled();
  await expect(next).toBeDisabled();

  await previous.click();
  await expect(firstChapter).toHaveAttribute('aria-current', 'location');
});

test('Readium treats local EPUB reading order as the only正文 source', async ({ page }) => {
  await installReaderRoutes(page, null, 0, [
    { href: 'cover.xhtml', title: '封面', body: '<html xmlns="http://www.w3.org/1999/xhtml"><head><title>封面</title></head><body><p id="front-cover">封面前置页</p></body></html>' },
    { href: 'contents.xhtml', title: '目录', body: '<html xmlns="http://www.w3.org/1999/xhtml"><head><title>目录</title></head><body><p id="front-contents">目录前置页</p></body></html>' },
    { href: 'chapter1.xhtml', title: '第一章', body: chapterOne },
    { href: 'chapter2.xhtml', title: '第二章', body: chapterTwo }
  ]);

  await page.goto('/reader/epub-resource');
  const frame = await visibleReadiumFrame(page);
  await expect(frame.contentFrame().locator('#front-cover')).toBeVisible();

  await frame.contentFrame().locator('body').press('End');
  const finalFrame = await visibleReadiumFrame(page);
  await expect(finalFrame.contentFrame().locator('#chapter-two')).toBeVisible();
  await finalFrame.contentFrame().locator('body').press('Home');
  const startFrame = await visibleReadiumFrame(page);
  await expect(startFrame.contentFrame().locator('#front-cover')).toBeVisible();
});

test('Readium applies block margins to every page viewport without special-casing covers', async ({ page }) => {
  await installReaderRoutes(page, null, 0, [
    { href: 'cover.xhtml', title: '封面', body: '<?xml version="1.0" encoding="UTF-8"?><html xmlns="http://www.w3.org/1999/xhtml"><head><title>Cover</title><style>body{text-align:center;padding:0;margin:0}</style></head><body><div><svg xmlns="http://www.w3.org/2000/svg" width="100%" height="100%" viewBox="0 0 521 751" preserveAspectRatio="none"><rect id="cover-art" width="521" height="751" fill="#315b48"/></svg></div></body></html>' },
    { href: 'contents.xhtml', title: '目录', body: '<?xml version="1.0" encoding="UTF-8"?><html xmlns="http://www.w3.org/1999/xhtml"><head><title>目录</title></head><body><p id="front-contents">目录前置页</p></body></html>' },
    { href: 'chapter1.xhtml', title: '第一章', body: '<?xml version="1.0" encoding="UTF-8"?><html xmlns="http://www.w3.org/1999/xhtml"><head><title>第一章</title></head><body><h1 id="chapter-title">第一章 Readium 验收</h1><p>短章正文。</p></body></html>' },
    { href: 'chapter2.xhtml', title: '第二章', body: chapterTwo }
  ]);

  await page.goto('/reader/epub-resource');
  let frame = await visibleReadiumFrame(page);
  let bounds: Awaited<ReturnType<typeof frame.boundingBox>>;
  await expect(frame.contentFrame().locator('#cover-art')).toHaveCount(1);
  const coverLayout = await frame.contentFrame().locator('body').evaluate((body) => {
    const documentElement = body.ownerDocument.documentElement;
    const cover = body.ownerDocument.querySelector('#cover-art');
    const coverRect = cover?.getBoundingClientRect();
    return {
      speciallyClassified: body.hasAttribute('data-shuku-readium-media-only'),
      paddingBlock: getComputedStyle(body).paddingBlock,
      scrollWidth: documentElement.scrollWidth,
      clientWidth: documentElement.clientWidth,
      coverX: coverRect?.x ?? -1
    };
  });
  expect(coverLayout).toEqual({
    speciallyClassified: false,
    paddingBlock: '0px',
    scrollWidth: coverLayout.clientWidth,
    clientWidth: coverLayout.clientWidth,
    coverX: expect.any(Number)
  });
  expect(coverLayout.coverX).toBeGreaterThanOrEqual(0);
  expect(coverLayout.coverX).toBeLessThan(coverLayout.clientWidth);
  const readerViewport = page.locator('[data-reader-viewport="stable"]');
  const viewportBounds = await readerViewport.boundingBox();
  bounds = await frame.boundingBox();
  if (!viewportBounds || !bounds) throw new Error('READIUM_VIEWPORT_BOUNDS_MISSING');
  expect(bounds.y - viewportBounds.y).toBeCloseTo(viewportBounds.height * 0.05, 0);
  expect(viewportBounds.y + viewportBounds.height - (bounds.y + bounds.height)).toBeCloseTo(
    viewportBounds.height * 0.05,
    0
  );

  bounds = await frame.boundingBox();
  if (!bounds) throw new Error('READIUM_FRAME_BOUNDS_MISSING');
  await page.mouse.click(bounds.x + bounds.width - 20, bounds.y + bounds.height / 2);
  frame = await visibleReadiumFrame(page);
  await expect(frame.contentFrame().locator('#front-contents')).toBeVisible();
});

test('Readium iframe routes center and jittered edge mouse taps without leaving a blue selection', async ({ page }) => {
  await installReaderRoutes(page, null, 0, [
    { href: 'chapter1.xhtml', title: '短章', body: '<?xml version="1.0" encoding="UTF-8"?><html xmlns="http://www.w3.org/1999/xhtml"><head><title>短章</title></head><body><h1 id="short-title">短章</h1><p id="short-opening">用于点击翻页与选择保护，拖动选择这段正文时不能翻页。</p><a id="inside-link" href="#short-title">内部链接</a></body></html>' },
    { href: 'chapter2.xhtml', title: '第二章', body: chapterTwo }
  ]);
  await page.goto('/reader/epub-resource');
  const frame = await visibleReadiumFrame(page);
  const bounds = await frame.boundingBox();
  if (!bounds) throw new Error('READIUM_FRAME_BOUNDS_MISSING');
  const centerX = bounds.x + bounds.width * 0.5;
  const centerY = bounds.y + bounds.height * 0.5;
  await expect(page.getByRole('button', { name: '外观' })).toBeHidden();

  await page.mouse.click(centerX, centerY);
  await expect(page.getByRole('button', { name: '外观' })).toBeVisible();
  await page.mouse.click(centerX, centerY);
  await expect(page.getByRole('button', { name: '外观' })).toBeHidden();

  await frame.contentFrame().locator('#inside-link').click();
  await expect(frame.contentFrame().locator('#short-title')).toBeVisible();
  await expect(page.getByRole('button', { name: '外观' })).toBeHidden();

  const textBounds = await frame.contentFrame().locator('#short-opening').boundingBox();
  if (!textBounds) throw new Error('READIUM_TEXT_BOUNDS_MISSING');
  await page.mouse.move(textBounds.x + 6, textBounds.y + textBounds.height / 2);
  await page.mouse.down();
  await page.mouse.move(textBounds.x + Math.min(180, textBounds.width - 6), textBounds.y + textBounds.height / 2);
  await page.mouse.up();
  await expect.poll(() => frame.contentFrame().locator('body').evaluate(() => window.getSelection()?.toString() ?? '')).not.toBe('');
  await expect(frame.contentFrame().locator('#chapter-two')).toHaveCount(0);
  await frame.contentFrame().locator('body').evaluate(() => window.getSelection()?.removeAllRanges());

  await frame.contentFrame().locator('body').evaluate((body) => {
    body.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true, pointerId: 31, isPrimary: true, pointerType: 'touch', clientX: 500, clientY: 300 }));
    body.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true, pointerId: 32, isPrimary: false, pointerType: 'touch', clientX: 530, clientY: 300 }));
    body.dispatchEvent(new PointerEvent('pointerup', { bubbles: true, pointerId: 31, isPrimary: true, pointerType: 'touch', clientX: 500, clientY: 300 }));
  });
  await expect(page.getByRole('button', { name: '外观' })).toBeHidden();

  const startX = bounds.x + bounds.width * 0.9;
  const startY = bounds.y + bounds.height * 0.5;
  await page.mouse.move(startX, startY);
  await page.mouse.down();
  await page.mouse.move(startX + 4, startY + 1);
  await page.mouse.up();

  const nextFrame = await visibleReadiumFrame(page);
  await expect(nextFrame.contentFrame().locator('#chapter-two')).toBeVisible();
  await expect.poll(() => nextFrame.contentFrame().locator('body').evaluate(() => window.getSelection()?.toString() ?? '')).toBe('');
});

test('Readium centers a constrained paginated surface instead of pinning it to the start edge', async ({ page }) => {
  await page.setViewportSize({ width: 1920, height: 937 });
  await installReaderRoutes(page);
  await page.goto('/reader/epub-resource');
  await visibleReadiumFrame(page);

  const geometry = await page.locator('[aria-label="Readium E2E 阅读内容"]').evaluate((container) => {
    const parent = container.parentElement;
    if (!parent) throw new Error('READIUM_CONTAINER_PARENT_MISSING');
    const containerRect = container.getBoundingClientRect();
    const parentRect = parent.getBoundingClientRect();
    return {
      containerLeft: containerRect.left,
      containerWidth: containerRect.width,
      parentLeft: parentRect.left,
      parentWidth: parentRect.width
    };
  });

  expect(geometry.containerWidth).toBe(1350);
  expect(geometry.containerLeft).toBeCloseTo(
    geometry.parentLeft + (geometry.parentWidth - geometry.containerWidth) / 2,
    0
  );

  const frame = await visibleReadiumFrame(page);
  const frameGeometry = await frame.evaluate((element) => {
    const frameRect = element.getBoundingClientRect();
    const containerRect = element.parentElement?.getBoundingClientRect();
    return {
      width: frameRect.width,
      height: frameRect.height,
      containerWidth: containerRect?.width ?? 0,
      containerHeight: containerRect?.height ?? 0
    };
  });
  expect(frameGeometry.width).toBeCloseTo(1350, 1);
  expect(frameGeometry.height).toBeCloseTo(843.3125, 1);
  expect(frameGeometry.containerWidth).toBeCloseTo(1350, 1);
  expect(frameGeometry.containerHeight).toBeCloseTo(843.3125, 1);
  const publicationGeometry = await frame.contentFrame().locator('body').evaluate((body) => {
    const style = getComputedStyle(body);
    return {
      paddingInlineStart: Number.parseFloat(style.paddingInlineStart),
      paddingInlineEnd: Number.parseFloat(style.paddingInlineEnd),
      paddingTop: Number.parseFloat(style.paddingTop),
      paddingBottom: Number.parseFloat(style.paddingBottom)
    };
  });
  expect(publicationGeometry.paddingInlineStart).toBe(24);
  expect(publicationGeometry.paddingInlineEnd).toBe(24);
  expect(publicationGeometry.paddingTop).toBe(0);
  expect(publicationGeometry.paddingBottom).toBe(0);

  await page.locator('[data-reader-shell="v3"] > div.relative').dispatchEvent('click', {
    clientX: 960,
    clientY: 420
  });
  await page.getByRole('button', { name: '外观' }).click();
  await page.getByRole('slider', { name: '页宽' }).fill('600');

  await expect.poll(async () => page.locator('[aria-label="Readium E2E 阅读内容"]').evaluate((container) => {
    const parent = container.parentElement;
    if (!parent) throw new Error('READIUM_CONTAINER_PARENT_MISSING');
    const containerRect = container.getBoundingClientRect();
    const parentRect = parent.getBoundingClientRect();
    return {
      centered: Math.abs(containerRect.left - (parentRect.left + (parentRect.width - containerRect.width) / 2)) <= 1,
      width: containerRect.width
    };
  })).toEqual({ centered: true, width: 600 });
});

test('an exact paragraph restore stays non-fatal when a preceding block shares the page', async ({ page }) => {
  const target = exactLocator('#target', '跨端恢复目标正文。', 0.8, 'chapter1.xhtml', 1);
  await installReaderRoutes(page, {
    schemaVersion: 4,
    clientId: 'ios-e2e',
    revision: 11,
    locator: target,
    displayPercent: 40,
    receivedAtEpochMillis: 100
  });

  await page.goto('/reader/epub-resource');
  let frame = await visibleReadiumFrame(page);
  await expect(frame.contentFrame().locator('#target')).toBeVisible();
  await expect(page.getByText('无法精确恢复到另一设备的位置')).toHaveCount(0);

  await frame.contentFrame().locator('body').press('PageDown');
  frame = await visibleReadiumFrame(page);
  await expect(page.getByText('阅读器加载失败')).toHaveCount(0);
});

test('Readium restore is accepted only after re-capturing the same exact DOM block', async ({ page }) => {
  const target = exactLocator('#chapter-two', '第二章', 0, 'chapter2.xhtml', 2);
  const writes = await installReaderRoutes(page, { schemaVersion: 4, clientId: 'android-e2e', revision: 7, locator: target, displayPercent: 70, receivedAtEpochMillis: 100 });
  await page.goto('/reader/epub-resource'); const frame = await visibleReadiumFrame(page);
  await expect(frame.contentFrame().locator('#chapter-two')).toBeVisible();
  await expect(page.locator('[data-reader-exact-restore="verified"]')).toHaveCount(1);
  expect(writes).toHaveLength(0);
  await expect(page.getByText('无法精确恢复到另一设备的位置')).toHaveCount(0);
});

test('an in-session remote update stays non-modal and jumps only after exact verification', async ({ page }) => {
  const writes: unknown[] = [];
  let currentSnapshot: Record<string, unknown> | null = null;
  const epub = await createEpub();
  await page.route('**/api/**', (route) => fulfillApi(route, currentSnapshot, 0, writes, epub));
  await page.goto('/reader/epub-resource');
  await visibleReadiumFrame(page);
  await expect.poll(() => writes.length, { timeout: 10_000 }).toBeGreaterThan(0);

  currentSnapshot = {
    schemaVersion: 4,
    clientId: 'ios-e2e',
    revision: 7,
    locator: exactLocator('#chapter-two', '第二章', 0, 'chapter2.xhtml', 2),
    displayPercent: 70,
    receivedAtEpochMillis: Date.now()
  };
  await page.evaluate(() => window.dispatchEvent(new Event('online')));
  await expect(page.getByText(/其他设备已阅读至/)).toBeVisible();
  const writesBeforeJump = writes.length;
  await page.getByRole('button', { name: '跳转' }).click();
  const frame = await visibleReadiumFrame(page);
  await expect(frame.contentFrame().locator('#chapter-two')).toBeVisible();
  await expect(page.getByText(/其他设备已阅读至/)).toHaveCount(0);
  await page.waitForTimeout(700);
  expect(writes).toHaveLength(writesBeforeJump);
});

test('whole-publication percentage is display-only and never an automatic restore target', async ({ page }) => {
  const writes = await installReaderRoutes(page, null, 88); await page.goto('/reader/epub-resource');
  const frame = await visibleReadiumFrame(page); await expect(frame.contentFrame().locator('#chapter-title')).toBeVisible();
  await expect.poll(() => writes.length, { timeout: 10_000 }).toBeGreaterThan(0);
  const write = writes.at(-1) as { locator: ReturnType<typeof exactLocator> };
  expect(write.locator.engineLocator.payload.locations.cssSelector).toBeTruthy();
  expect(write.locator.engineLocator.payload.locations.progression).not.toBe(0.88);
});

test('Readium settings expose scrolling, auto spread and publisher styles with truthful context states', async ({ page }) => {
  await installReaderRoutes(page, null, 0, undefined, null);
  await page.goto('/reader/epub-resource');
  await visibleReadiumFrame(page);

  await page.locator('[data-reader-shell="v3"] > div.relative').dispatchEvent('click', {
    clientX: 640,
    clientY: 320
  });
  await page.getByRole('button', { name: '阅读设置' }).click();

  const flow = page.getByRole('group', { name: '阅读方式' });
  await expect(flow.getByRole('button', { name: '分页' })).toHaveAttribute('aria-pressed', 'true');
  await flow.getByRole('button', { name: '滚动' }).click();
  await expect(flow.getByRole('button', { name: '滚动' })).toHaveAttribute('aria-pressed', 'true');

  const spread = page.getByRole('group', { name: '页面' });
  await expect(spread.getByRole('button', { name: '自动' })).toBeDisabled();
  await expect(spread.getByRole('button', { name: '单页' })).toHaveAttribute('aria-pressed', 'true');
  await expect(page.getByText('滚动模式下暂不可用')).toBeVisible();
  await flow.getByRole('button', { name: '分页' }).click();
  await expect(spread.getByRole('button', { name: '自动' })).toBeEnabled();
  await spread.getByRole('button', { name: '双页' }).click();
  await expect(spread.getByRole('button', { name: '双页' })).toHaveAttribute('aria-pressed', 'true');

  const animation = page.getByRole('group', { name: '动画' });
  await expect(animation.getByRole('button', { name: '平移' })).toBeDisabled();
  await expect(animation.getByRole('button', { name: '关闭' })).toBeDisabled();

  const swipe = page.getByRole('checkbox', { name: /滑动翻页/ });
  await expect(swipe).toBeChecked();
  await expect(swipe).toBeDisabled();

  await page.getByRole('button', { name: '高级设置', exact: true }).click();
  const readingProgression = page.getByRole('group', { name: '阅读方向' });
  await expect(readingProgression.getByRole('button', { name: 'LTR' })).toHaveAttribute('aria-pressed', 'true');
  await readingProgression.getByRole('button', { name: 'RTL' }).click();
  await expect(readingProgression.getByRole('button', { name: 'RTL' })).toHaveAttribute('aria-pressed', 'true');
  const writingMode = page.getByRole('group', { name: '排版方向' });
  await expect(writingMode.getByRole('button', { name: '横排' })).toHaveAttribute('aria-pressed', 'true');
  await writingMode.getByRole('button', { name: '竖排' }).click();
  await expect(writingMode.getByRole('button', { name: '竖排' })).toHaveAttribute('aria-pressed', 'true');
  await expect(flow.getByRole('button', { name: '分页' })).toBeDisabled();
  await expect(spread.getByRole('button', { name: '单页' })).toBeDisabled();
  const verticalModeHints = page.getByText('竖排模式使用滚动阅读');
  await expect(verticalModeHints).toHaveCount(2);
  await expect(verticalModeHints.first()).toBeVisible();
  const verticalFrame = await visibleReadiumFrame(page);
  await expect.poll(() => verticalFrame.contentFrame().locator('html').evaluate(
    (root) => getComputedStyle(root).writingMode
  )).toContain('vertical');
  await readingProgression.getByRole('button', { name: 'LTR' }).click();
  await expect(readingProgression.getByRole('button', { name: 'LTR' })).toHaveAttribute('aria-pressed', 'true');
  const verticalLtrFrame = await visibleReadiumFrame(page);
  await expect.poll(() => verticalLtrFrame.contentFrame().locator('html').evaluate(
    (root) => getComputedStyle(root).writingMode
  )).toContain('vertical');
  await writingMode.getByRole('button', { name: '横排' }).click();
  await expect(writingMode.getByRole('button', { name: '横排' })).toHaveAttribute('aria-pressed', 'true');
  await expect(flow.getByRole('button', { name: '分页' })).toBeEnabled();
  await expect(spread.getByRole('button', { name: '双页' })).toBeEnabled();
  const publisher = page.getByRole('checkbox', { name: /出版方样式/ });
  await expect(publisher).toBeEnabled();
  await expect(publisher).not.toBeChecked();
  await page.getByText('出版方样式', { exact: true }).click();
  await expect(publisher).toBeChecked();
  await expect(page.getByText('保留出版方行高', { exact: true })).toHaveCount(0);
  await expect(page.getByText('允许出版方颜色', { exact: true })).toHaveCount(0);
  await expect(page.getByText('允许出版方字体', { exact: true })).toHaveCount(0);
  await expect(page.locator('#reader-advanced-settings')).toHaveCSS('opacity', '1');
  const publisherLabel = page.getByText('出版方样式', { exact: true });
  await publisherLabel.scrollIntoViewIfNeeded();
  await expect(publisherLabel).toBeInViewport();
  await page.screenshot({ path: 'test-results/reader-settings-publisher-master.png' });
});

test('Readium applies reader themes inside the publication without persisting a reflow as progress', async ({ page }) => {
  const writes = await installReaderRoutes(page);
  await page.goto('/reader/epub-resource');
  const frame = await visibleReadiumFrame(page);
  await expect.poll(() => writes.length, { timeout: 10_000 }).toBeGreaterThan(0);
  await page.waitForTimeout(300);
  const writesBeforeTheme = writes.length;

  await page.locator('[data-reader-shell="v3"] > div.relative').dispatchEvent('click', {
    clientX: 640,
    clientY: 320
  });
  await page.getByRole('button', { name: '外观' }).click();
  await page.getByRole('button', { name: '纯黑' }).click();

  await expect(page.locator('[data-reader-shell="v3"]')).toHaveAttribute('data-reader-theme', 'black');
  await expect.poll(async () => frame.contentFrame().locator('body').evaluate((body) => ({
    background: getComputedStyle(body).backgroundColor,
    color: getComputedStyle(body).color
  }))).toEqual({ background: 'rgb(0, 0, 0)', color: 'rgb(248, 250, 252)' });
  await page.waitForTimeout(500);
  expect(writes).toHaveLength(writesBeforeTheme);
});

test('Readium iframe keyboard input reaches first and last publication positions', async ({ page }) => {
  await installReaderRoutes(page);
  await page.goto('/reader/epub-resource');
  let frame = await visibleReadiumFrame(page);

  await frame.contentFrame().locator('body').evaluate((body) => {
    body.dispatchEvent(new KeyboardEvent('keydown', { key: 'End', bubbles: true }));
    body.dispatchEvent(new KeyboardEvent('keyup', { key: 'End', bubbles: true }));
  });
  frame = await visibleReadiumFrame(page);
  await expect(frame.contentFrame().locator('#chapter-two')).toBeVisible();

  await frame.contentFrame().locator('body').evaluate((body) => {
    body.dispatchEvent(new KeyboardEvent('keydown', { key: 'Home', bubbles: true }));
    body.dispatchEvent(new KeyboardEvent('keyup', { key: 'Home', bubbles: true }));
  });
  frame = await visibleReadiumFrame(page);
  await expect(frame.contentFrame().locator('#chapter-title')).toBeVisible();
});

test('Reader deletes a failed original transfer and retries it from zero', async ({ page }) => {
  const originalRequests: string[] = [];
  const epub = await createEpub();
  await page.route('**/api/**', async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === '/api/assets/epub-asset') {
      originalRequests.push(path);
      return route.fulfill({ status: 403, contentType: 'text/plain', body: 'private-response-body' });
    }
    return fulfillApi(route, null, 0, [], epub);
  });
  await page.goto('/reader/epub-resource');
  await expect(page.getByText('原文件下载响应无效')).toBeVisible();
  await expect(page.getByText('private-response-body')).toHaveCount(0);
  await page.reload();
  await expect(page.getByText('原文件下载响应无效')).toBeVisible();
  expect(originalRequests).toHaveLength(2);
});
