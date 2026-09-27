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


test('AI identity preview applies corrections and reloads book detail', async ({ page }) => {
  let saved = false;
  let detailReads = 0;
  await page.route(/\/api\/books\/book-1(?:\?|$)/, async (route) => {
    detailReads += 1;
    await route.fulfill({ json: { ok: true, data: { book: {
      id: 'book-1', sourceNodeId: 'book-node', title: saved ? '活着' : '活着 完整版',
      author: saved ? '余华' : '鲁迅', description: '保留简介', resources: [epubResource]
    } } } });
  });
  await page.route('**/api/metadata/providers', (route) => route.fulfill({ json: { ok: true, data: { providers: [
    { id: 'douban', name: '豆瓣', enabled: true, priority: 1 },
    { id: 'ai', name: 'AI 增强识别', enabled: true, priority: 2 }
  ] } } }));
  await page.route('**/metadata/search', (route) => route.fulfill({ json: { ok: true, data: {
    query: '活着', selectedId: 'ai-identity', preferLocalMetadata: true,
    identity: { title: '活着', author: '余华', needsReview: false, reason: '受控 UI 测试' },
    candidates: [{ id: 'ai-identity', source: 'ai', title: '活着', author: '余华', description: null, tags: [] }]
  } } }));
  await page.route('**/metadata/apply', async (route) => {
    const body = route.request().postDataJSON();
    expect(body.candidate.title).toBe('活着');
    expect(body.candidate.author).toBe('余华');
    expect(body.fields).toEqual(['book.title', 'book.author']);
    saved = true;
    await route.fulfill({ json: { ok: true, data: { appliedFields: body.fields, skippedFields: [], coverStatus: 'notSelected' } } });
  });
  await page.goto('/books/book-1');
  await page.getByRole('button', { name: '管理图书 活着 完整版' }).click();
  await page.getByRole('menuitem', { name: '识别', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: '元数据识别', exact: true });
  await dialog.getByRole('button', { name: '搜索', exact: true }).click();
  await expect(dialog.getByText('活着 完整版 → 活着', { exact: true })).toBeVisible();
  await expect(dialog.getByText('鲁迅 → 余华', { exact: true })).toBeVisible();
  const readsBeforeSave = detailReads;
  await dialog.getByRole('button', { name: '应用所选字段' }).click();
  await expect(dialog).toHaveCount(0);
  await expect(page.getByRole('button', { name: '管理图书 活着', exact: true })).toBeVisible();
  expect(detailReads).toBeGreaterThan(readsBeforeSave);
  await page.reload();
  await expect(page.getByRole('button', { name: '管理图书 活着', exact: true })).toBeVisible();
});


test('AI identity preview respects a subsequent manual query', async ({ page }) => {
  await page.route(/\/api\/books\/book-1(?:\?|$)/, (route) => route.fulfill({ json: { ok: true, data: { book: {
    id: 'book-1', sourceNodeId: 'book-node', title: '甲书 完整版', author: '旧作者', resources: [epubResource]
  } } } }));
  await page.route('**/api/metadata/providers', (route) => route.fulfill({ json: { ok: true, data: { providers: [
    { id: 'douban', name: '豆瓣', enabled: true, priority: 1 }
  ] } } }));
  const searches: unknown[] = [];
  await page.route('**/metadata/search', (route) => {
    const body = route.request().postDataJSON();
    searches.push(body);
    const title = body.manualQuery ? body.query : '甲书';
    return route.fulfill({ json: { ok: true, data: {
      query: title, selectedId: 'site', preferLocalMetadata: true,
      identity: body.manualQuery ? null : { title: '甲书', author: '作者甲', needsReview: false, reason: '受控 UI 测试' },
      candidates: [{ id: 'site', source: 'douban', title, author: body.manualQuery ? '作者乙' : '作者甲', tags: [] }]
    } } });
  });
  await page.goto('/books/book-1');
  await page.getByRole('button', { name: '管理图书 甲书 完整版' }).click();
  await page.getByRole('menuitem', { name: '识别', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: '元数据识别', exact: true });
  await dialog.getByRole('button', { name: '搜索', exact: true }).click();
  await expect(dialog.getByText('甲书 完整版 → 甲书', { exact: true })).toBeVisible();
  const query = dialog.getByRole('textbox');
  await expect(query).toHaveValue('甲书');
  await query.fill('乙书');
  await dialog.getByRole('button', { name: '搜索', exact: true }).click();
  await expect(dialog.getByRole('checkbox', { name: '作者 旧作者 作者乙', exact: true })).toBeVisible();
  await expect(query).toHaveValue('乙书');
  await expect(dialog.getByText('甲书 完整版 → 甲书', { exact: true })).toHaveCount(0);
  expect(searches).toEqual([
    { providerId: 'douban', query: '甲书 完整版', manualQuery: false },
    { providerId: 'douban', query: '乙书', manualQuery: true }
  ]);
});


test('AI semantic match applies source metadata and allows changing the record', async ({ page }) => {
  let saved = false;
  let detailReads = 0;
  const primary = { id: 'bangumi:1', source: 'bangumi', title: '海辺のカフカ', author: '村上春樹', description: '网站真实简介', tags: [] };
  await page.route(/\/api\/books\/book-1(?:\?|$)/, async (route) => {
    detailReads += 1;
    await route.fulfill({ json: { ok: true, data: { book: {
      id: 'book-1', sourceNodeId: 'book-node', title: saved ? '海边的卡夫卡' : '卡夫卡 下载版',
      author: saved ? '村上春树' : '错误作者', description: saved ? '网站真实简介' : null, resources: [epubResource]
    } } } });
  });
  await page.route('**/api/metadata/providers', (route) => route.fulfill({ json: { ok: true, data: { providers: [
    { id: 'bangumi', name: 'Bangumi', enabled: true, priority: 1 }
  ] } } }));
  const selectionRequests: string[] = [];
  await page.route('**/metadata/search', (route) => {
    const body = route.request().postDataJSON();
    if (body.selectedCandidate) {
      selectionRequests.push(body.selectedCandidate.id);
      return route.fulfill({ json: { ok: true, data: { query: body.query, candidates: [], selectedId: body.selectedCandidate.id,
        selectedMetadata: { ...body.selectedCandidate, description: '其他条目详情简介' } } } });
    }
    return route.fulfill({ json: { ok: true, data: {
    query: '海边的卡夫卡', selectedId: primary.id, preferLocalMetadata: true,
    identity: { title: '海边的卡夫卡', author: '村上春树', needsReview: false, reason: '名称写法不同，确认同一作品' },
    candidates: [primary, { id: 'douban:1', source: 'douban', title: '其他作品', author: '其他作者', tags: [] }],
    selectedMetadata: { ...primary, title: '海边的卡夫卡', author: '村上春树' }
  } } });
  });
  await page.route('**/metadata/apply', async (route) => {
    const body = route.request().postDataJSON();
    expect(body.candidate.id).toBe(primary.id);
    expect(body.candidate.source).toBe('bangumi');
    expect(body.candidate.author).toBe('村上春树');
    expect(body.candidate.description).toBe('网站真实简介');
    expect(body.fields).toEqual(['book.title', 'book.author', 'book.description']);
    saved = true;
    await route.fulfill({ json: { ok: true, data: { appliedFields: body.fields, skippedFields: [], coverStatus: 'notSelected' } } });
  });
  await page.goto('/books/book-1');
  await page.getByRole('button', { name: '管理图书 卡夫卡 下载版' }).click();
  await page.getByRole('menuitem', { name: '识别', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: '元数据识别', exact: true });
  await dialog.getByRole('button', { name: '搜索', exact: true }).click();
  await expect(dialog.getByText('名称写法不同，确认同一作品', { exact: true })).toBeVisible();
  const primaryButton = dialog.getByRole('button', { name: /海辺のカフカ.*村上春樹.*bangumi/ });
  await expect(primaryButton).toBeVisible();
  await dialog.getByRole('button', { name: /其他作品.*其他作者.*douban/ }).click();
  await expect(dialog.getByRole('checkbox', { name: '作者 错误作者 其他作者', exact: true })).toBeChecked();
  await expect(dialog.getByRole('checkbox', { name: '简介 未填写 其他条目详情简介', exact: true })).toBeChecked();
  expect(selectionRequests).toEqual(['douban:1']);
  await primaryButton.click();
  await expect(dialog.getByRole('checkbox', { name: '作者 错误作者 村上春树', exact: true })).toBeChecked();
  const beforeSave = detailReads;
  await dialog.getByRole('button', { name: '应用所选字段' }).click();
  await expect(dialog).toHaveCount(0);
  await expect(page.getByText('网站真实简介', { exact: true })).toBeVisible();
  expect(detailReads).toBeGreaterThan(beforeSave);
  await page.reload();
  await expect(page.getByRole('button', { name: '管理图书 海边的卡夫卡', exact: true })).toBeVisible();
  await expect(page.getByText('网站真实简介', { exact: true })).toBeVisible();
});


test('AI generated fields are previewed, applied, reloaded and isolated when changing records', async ({ page }) => {
  let saved = false;
  const generated = { id: 'ai-identity', source: 'ai', title: '活着', author: '余华', description: '本次生成的作品介绍', tags: ['人生', '小说'],
    generatedFields: ['description', 'tags'], generationSource: 'AI_GENERATED', generationNeedsReview: false, generationReason: '生成测试', generationRevision: 'revision-1' };
  const other = { id: 'bangumi:2', source: 'bangumi', title: '另一作品', author: '另一作者', tags: [] };
  await page.route(/\/api\/books\/book-1(?:\?|$)/, (route) => route.fulfill({ json: { ok: true, data: { book: {
    id: 'book-1', sourceNodeId: 'book-node', title: '活着', author: '余华', description: saved ? generated.description : null,
    tags: saved ? generated.tags : [], generatedFields: saved ? generated.generatedFields : [], resources: [epubResource]
  } } } }));
  await page.route('**/api/metadata/providers', (route) => route.fulfill({ json: { ok: true, data: { providers: [{ id: 'bangumi', name: 'Bangumi', enabled: true, priority: 1 }] } } }));
  await page.route('**/metadata/search', (route) => {
    const body = route.request().postDataJSON();
    const selected = body.selectedCandidate ? { ...other, description: '另一身份的生成介绍', generatedFields: ['description'], generationSource: 'AI_GENERATED' } : generated;
    return route.fulfill({ json: { ok: true, data: { query: '活着', candidates: [generated, other], selectedId: selected.id, selectedMetadata: selected, preferLocalMetadata: true } } });
  });
  await page.route('**/metadata/apply', async (route) => {
    const body = route.request().postDataJSON();
    expect(body.candidate.generatedFields).toEqual(['description', 'tags']);
    expect(body.candidate.generationRevision).toBe('revision-1');
    expect(body.candidate.description).toBe(generated.description);
    expect(body.fields).toEqual(['book.description', 'book.tags']);
    saved = true;
    await route.fulfill({ json: { ok: true, data: { appliedFields: body.fields, skippedFields: [], coverStatus: 'notSelected' } } });
  });
  await page.goto('/books/book-1');
  await page.getByRole('button', { name: '管理图书 活着', exact: true }).click();
  await page.getByRole('menuitem', { name: '识别', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: '元数据识别', exact: true });
  await dialog.getByRole('button', { name: '搜索', exact: true }).click();
  await expect(dialog.getByText('AI 生成', { exact: true })).toHaveCount(2);
  await dialog.getByRole('button', { name: /另一作品.*另一作者.*bangumi/ }).click();
  await expect(dialog.getByRole('checkbox', { name: /简介.*另一身份的生成介绍/ })).toBeChecked();
  await dialog.getByRole('button', { name: /活着.*余华.*ai/ }).click();
  await expect(dialog.getByRole('checkbox', { name: /简介.*本次生成的作品介绍/ })).toBeChecked();
  await dialog.getByRole('button', { name: '应用所选字段' }).click();
  await expect(dialog).toHaveCount(0);
  await expect(page.getByText('简介 · AI 生成', { exact: true })).toBeVisible();
  await expect(page.getByText('标签 · AI 生成', { exact: true })).toBeVisible();
  await page.reload();
  await expect(page.getByText(generated.description, { exact: true })).toBeVisible();
  await expect(page.getByText('简介 · AI 生成', { exact: true })).toBeVisible();
});


test('single same-node resource exposes recognition with its explicit target', async ({ page }) => {
  let saved = false;
  const generated = { id: 'ai-identity', source: 'ai', title: '活着', author: '余华', description: '资源生成简介', tags: [], generatedFields: ['description'], generationSource: 'AI_GENERATED', generationRevision: 'book|resource', coverUrl: 'https://example.test/cover.jpg' };
  const other = { id: 'bangumi:2', source: 'bangumi', title: '另一条目', author: '余华', tags: [] };
  await page.route(/\/api\/books\/book-1(?:\?|$)/, (route) => route.fulfill({ json: { ok: true, data: { book: {
    id: 'book-1', sourceNodeId: 'book-node', title: '活着', author: '余华', description: '书级简介保留', tags: [], metadataPending: true,
    resources: [{ ...epubResource, sourceNodeId: 'book-node', title: '活着', description: saved ? generated.description : '', generatedFields: saved ? ['description'] : [] }]
  } } } }));
  await page.route('**/api/metadata/providers', (route) => route.fulfill({ json: { ok: true, data: { providers: [{ id: 'bangumi', name: 'Bangumi', enabled: true, priority: 1 }] } } }));
  await page.route('**/metadata/search', async (route) => {
    const body = route.request().postDataJSON();
    expect(body.scope).toBe('resource'); expect(body.resourceId).toBe('resource-epub');
    await new Promise((resolve) => setTimeout(resolve, 2500)); // Detail polling must not abort this operation.
    const selected = body.selectedCandidate ? { ...generated, id: other.id } : generated;
    return route.fulfill({ json: { ok: true, data: { query: '活着', candidates: [generated, other], selectedId: selected.id, selectedMetadata: selected, preferLocalMetadata: true } } });
  });
  await page.route('**/metadata/apply', (route) => {
    const body = route.request().postDataJSON();
    expect(body.scope).toBe('resource'); expect(body.resourceId).toBe('resource-epub');
    expect(body.fields).toEqual(['resource.description']); saved = true;
    return route.fulfill({ json: { ok: true, data: { appliedFields: body.fields, skippedFields: [], coverStatus: 'notSelected' } } });
  });
  await page.goto('/books/book-1');
  await page.getByRole('button', { name: '管理 活着', exact: true }).click();
  await page.getByRole('menuitem', { name: '识别', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: '元数据识别', exact: true });
  await dialog.getByRole('button', { name: '搜索', exact: true }).click();
  await expect(dialog.getByText('AI 生成', { exact: true })).toBeVisible();
  await dialog.getByRole('button', { name: /另一条目.*余华.*bangumi/ }).click();
  await expect(dialog.getByRole('button', { name: '应用所选字段' })).toBeEnabled();
  const cover = dialog.getByRole('checkbox', { name: /^封面/ });
  await cover.uncheck();
  await page.waitForTimeout(2500); // A second poll must also preserve manual field selection.
  await expect(cover).not.toBeChecked();
  await dialog.getByRole('button', { name: '应用所选字段' }).click();
  await expect(dialog).toHaveCount(0);
  await page.reload();
  await expect(page.getByText('简介 · AI 生成', { exact: true })).toBeVisible();
  await expect(page.getByText('资源生成简介', { exact: true })).toBeVisible();
  await expect(page.getByText('书级简介保留', { exact: true })).toBeVisible();
});

test('manual metadata selection applies conflicting candidates and every available field', async ({ page }) => {
  await page.unroute('**/api/**');
  await mockBookDetailApi(page, [epubResource, secondEpubResource]);
  await page.route('**/api/books/book-1', (route) => route.fulfill({ json: { ok: true, data: { book: {
    id: 'book-1', sourceNodeId: 'book-node', title: 'Resource detail book', author: 'Author',
    resources: [epubResource, secondEpubResource], metadataState: 'RUNNING', metadataOnlineState: 'RUNNING'
  } } } }));
  await page.route('**/api/metadata/providers', (route) => route.fulfill({ json: { ok: true, data: { providers: [
    { id: 'bangumi', name: 'Bangumi', enabled: true, mode: 'search' }
  ] } } }));
  const candidate = {
    id: 'manual-candidate', source: 'bangumi', title: '罗杰疑案', author: '另一作者',
    description: '候选简介', seriesName: '系列', seriesIndex: 2, tags: ['推理'],
    publisher: '出版社', publishedAt: '2026-09-27', language: 'zh', isbn: 'arbitrary-isbn',
    identifier: 'manual-id', narrator: '朗读者', abridged: false, resourceIndex: 3,
    coverUrl: 'https://example.test/cover.jpg',
    match: { outcome: 'REJECTED', level: 'UNKNOWN', reasons: ['AUTHOR_CONFLICT'], evidenceIds: [], allowedFields: [] },
    confirmableFields: ['book.author', 'book.series_name', 'book.series_index', 'book.tags',
      'resource.title', 'resource.description', 'resource.publisher', 'resource.published_at',
      'resource.language', 'resource.isbn', 'resource.identifier', 'resource.narrator',
      'resource.abridged', 'resource.resource_index', 'resource.cover_ref']
  };
  await page.route('**/metadata/search', (route) => route.fulfill({ json: { ok: true, data: {
    sourceNodeId: 'epub-node', providerId: 'bangumi', query: '罗杰疑案', candidates: [candidate], hints: []
  } } }));
  await page.route('**/metadata/apply', async (route) => {
    const body = route.request().postDataJSON();
    expect(body.fields).toHaveLength(15);
    expect(body.fields).toEqual(expect.arrayContaining(['book.author', 'book.tags', 'resource.cover', 'resource.abridged', 'resource.title']));
    await route.fulfill({ json: { ok: true, data: { appliedFields: body.fields, skippedFields: [], coverStatus: 'applied', writebackStatus: 'notRequested' } } });
  });
  await page.goto('/books/book-1');
  await expect(page.getByRole('heading', { name: 'Resource detail book', exact: true })).toBeVisible();
  await expect(page.getByText('图书信息识别中', { exact: true })).toHaveCount(0);
  await expect(page.getByText('图书信息联网识别中', { exact: true })).toHaveCount(0);
  await page.getByRole('button', { name: '管理 EPUB resource', exact: true }).focus();
  await page.keyboard.press('Enter');
  await page.getByRole('menuitem', { name: '识别', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: '元数据识别', exact: true });
  await dialog.getByRole('button', { name: '搜索', exact: true }).click();
  await expect(dialog.getByText('找到 1 条候选')).toBeVisible();
  await expect(dialog.getByText('已排除', { exact: true })).toHaveCount(0);
  await expect(dialog.getByText('范围未知', { exact: true })).toHaveCount(0);
  await expect(dialog.getByText('作者不一致', { exact: true })).toHaveCount(0);
  const fields = dialog.getByRole('checkbox');
  await expect(fields).toHaveCount(15);
  for (const field of await fields.all()) {
    await expect(field).toBeEnabled();
    await field.uncheck();
  }
  const apply = dialog.getByRole('button', { name: '应用所选字段', exact: true });
  await expect(apply).toBeDisabled();
  for (const field of await fields.all()) await field.check();
  await expect(apply).toBeEnabled();
  await apply.click();
  await expect(dialog).toBeHidden();
});
