import { expect, test, type Page, type Route } from '@playwright/test';

type ApiRouteOverride = (route: Route, url: URL) => Promise<boolean>;

async function mockWebAppApi(page: Page, override?: ApiRouteOverride) {
  await page.route('**/api/**', async (route) => {
    const url = new URL(route.request().url());
    const pathname = url.pathname;
    if (override && await override(route, url)) return;
    if (pathname.endsWith('/api/auth/me')) {
      await route.fulfill({
        json: {
          ok: true,
          data: {
            user: { id: 'web-user', email: 'web@example.com', name: 'Web', role: 'admin' },
            authorization: {
              isAdmin: true,
              canManageSystem: true,
              allLibraryScopes: true,
              libraryIds: [],
              canViewManualImports: true,
              authzVersion: 1
            }
          }
        }
      });
      return;
    }
    if (pathname.endsWith('/api/dashboard/continue-reading')) {
      await route.fulfill({ json: { ok: true, data: { item: null } } });
      return;
    }
    if (pathname.endsWith('/api/dashboard/recent-reading') || pathname.endsWith('/api/dashboard/recent-books') || pathname.endsWith('/api/books')) {
      await route.fulfill({ json: { ok: true, data: { books: [], total: 0 } } });
      return;
    }
    if (pathname.endsWith('/api/shelves')) {
      await route.fulfill({ json: { ok: true, data: { shelves: [{ id: 'to-read', name: '待读' }] } } });
      return;
    }
    await route.fulfill({ json: { ok: true, data: {} } });
  });
}

test.beforeEach(async ({ context, page }) => {
  await context.addCookies([{ name: 'shuku_session', value: 'web-session', domain: '127.0.0.1', path: '/' }]);
  await context.addInitScript(() => localStorage.setItem('shuku:pwa:install-dismissed:web-user', '1'));
  await mockWebAppApi(page);
});

test('smart filter searches high-cardinality author options only after edited input', async ({ page }) => {
  let optionRequests = 0;
  const filteredBookRequests: URL[] = [];
  await page.route('**/api/library/filter-schema', async (route) => {
    await route.fulfill({
      json: {
        ok: true,
        data: {
          fields: [{
            key: 'author',
            label: '作者',
            group: '图书元数据',
            type: 'select',
            operators: ['equals'],
            optionSource: 'authors',
            allowCustom: true,
            options: []
          }],
          maxConditions: 30
        }
      }
    });
  });
  await page.route('**/api/library/filter-options?**', async (route) => {
    optionRequests += 1;
    const requestUrl = new URL(route.request().url());
    expect(requestUrl.searchParams.get('source')).toBe('authors');
    expect(requestUrl.searchParams.get('query')).toBe('哆啦A梦');
    expect(requestUrl.searchParams.get('limit')).toBe('20');
    await route.fulfill({
      json: {
        ok: true,
        data: {
          source: 'authors',
          query: '哆啦A梦',
          options: [{ value: '哆啦A梦', label: '哆啦A梦', count: 3 }],
          hasMore: false,
          indexReady: true
        }
      }
    });
  });
  await page.route('**/api/books?**', async (route) => {
    const requestUrl = new URL(route.request().url());
    if (requestUrl.searchParams.has('filters')) filteredBookRequests.push(requestUrl);
    await route.fulfill({ json: { ok: true, data: { books: [], total: 0 } } });
  });

  await page.goto('/library');
  await page.getByRole('button', { name: '管理图书', exact: true }).click();
  await page.getByRole('button', { name: '更多筛选' }).click();
  await page.getByRole('button', { name: '添加第一个筛选条件' }).click();
  const authorInput = page.getByRole('combobox', { name: '作者筛选值' });
  await authorInput.focus();
  await page.waitForTimeout(300);
  expect(optionRequests).toBe(0);

  await authorInput.pressSequentially('哆啦A梦', { delay: 20 });
  expect(optionRequests).toBe(0);
  expect(filteredBookRequests).toHaveLength(0);
  await expect.poll(() => optionRequests).toBe(1);
  await expect.poll(() => filteredBookRequests.length).toBe(1);
  expect(filteredBookRequests[0]?.searchParams.get('filters')).toContain('"value":"哆啦A梦"');
  await page.getByRole('option', { name: '哆啦A梦 · 3' }).click();
  await expect(authorInput).toHaveValue('哆啦A梦');
  await page.waitForTimeout(300);
  expect(optionRequests).toBe(1);
  expect(filteredBookRequests).toHaveLength(1);
});

test('PWA launch parameters keep the responsive web shell on mobile widths', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/?source=pwa');

  await expect(page).toHaveURL(/\/?\?source=pwa$/);
  await expect(page.getByRole('heading', { name: '主页' })).toBeVisible();
  await expect(page.locator('html')).not.toHaveClass(/pwa-native/);
  await expect(page.getByRole('link', { name: '未读', exact: true })).toHaveCount(0);
  await expect(page.getByRole('link', { name: '已读', exact: true })).toHaveCount(0);
});

test('book detail resource covers support selection, keyboard-accessible context management, and double-click open', async ({ page }) => {
  const resource = (id: string, title: string, sortOrder: number) => ({
    id,
    bookId: 'context-book',
    sourceNodeId: `${id}-source-node`,
    title,
    resourceIndex: sortOrder + 1,
    sortOrder,
    format: 'CBZ',
    publisher: null,
    publishedAt: null,
    language: null,
    isbn: null,
    identifier: null,
    narrator: null,
    abridged: null,
    importStatus: 'READY',
    importError: null,
    coverUrl: '',
    pageCount: 24,
    chapterCount: null,
    durationMs: null,
    trackCount: null,
    progress: sortOrder === 0 ? 80 : 100,
    lastReadAt: null,
    hidden: false,
    readable: true,
    readerType: 'comic',
    kindleSendAvailable: false,
    classification: { suggestedMediaKind: 'COMIC', source: 'USER', reason: 'USER_SELECTED' },
    assets: [{ id: `${id}-asset`, resourceId: id, sourceNodeId: `${id}-source-node`, role: 'PRIMARY', mimeType: 'application/zip', sortOrder: 0, sizeBytes: 1024, size: '1 KB', url: `/api/assets/${id}-asset`, downloadUrl: `/api/assets/${id}-asset?download=true` }]
  });
  const resources = [resource('context-resource-1', '第一资源', 0), resource('context-resource-2', '第二资源', 1)];
  const sourceNodeEntry = { sourceNodeId: 'context-source-node', parentSourceNodeId: 'context-book-node', name: '测试来源目录', title: '测试目录标题', description: '目录简介', kind: 'FOLDER', physicalKind: 'DIRECTORY', sizeBytes: null, observedAt: '2026-08-03T08:00:00.000Z', hasChildren: true, resourceId: null, representativeResourceId: resources[0].id };
  const book = {
    id: 'context-book',
    sourceNodeId: 'context-book-node',
    title: '右键菜单测试图书',
    author: '测试作者',
    description: '',
    tags: [],
    coverUrl: '',
    coverStatus: 'MISSING',
    gradient: 'from-orange-100 to-stone-200',
    seriesName: null,
    seriesIndex: null,
    publicationStatus: 'UNKNOWN',
    trackingStatus: 'NOT_TRACKING',
    ignored: false,
    organized: true,
    metadataQuality: 100,
    addedAt: '2026-08-03T08:00:00.000Z',
    updatedAt: '2026-08-03T08:00:00.000Z',
    continueResourceId: resources[0].id,
    continueResourceTitle: resources[0].title,
    continueResourceProgress: resources[0].progress,
    continueReaderType: 'comic',
    completed: false,
    resources
  };
  await page.unroute('**/api/**');
  await mockWebAppApi(page, async (route, url) => {
    if (!url.pathname.includes('/api/books/context-book')) return false;
    if (url.pathname.includes('/contents')) {
      const nested = url.searchParams.get('sourceNodeId') === sourceNodeEntry.sourceNodeId;
      const resourceEntries = resources.map((resource, index) => ({
        sourceNodeId: `context-node-${index + 1}`,
        parentSourceNodeId: nested ? sourceNodeEntry.sourceNodeId : 'context-book-node',
        name: resource.title,
        title: resource.title,
        description: null,
        kind: 'FILE',
        physicalKind: 'REGULAR_FILE',
        sizeBytes: 0,
        observedAt: book.updatedAt,
        hasChildren: false,
        resourceId: resource.id,
        representativeResourceId: resource.id
      }));
      await route.fulfill({ json: { ok: true, data: {
        bookId: book.id,
        currentSourceNodeId: nested ? sourceNodeEntry.sourceNodeId : 'context-book-node',
        currentResourceId: null,
        currentNode: nested ? sourceNodeEntry : { sourceNodeId: 'context-book-node', parentSourceNodeId: null, name: book.title, title: book.title, description: null, kind: 'FOLDER', physicalKind: 'DIRECTORY', sizeBytes: null, observedAt: book.updatedAt, hasChildren: true, resourceId: null, representativeResourceId: resources[0].id },
        currentResourceIds: resources.map((resource) => resource.id),
        parentSourceNodeId: null,
        breadcrumbs: nested ? [sourceNodeEntry] : [],
        entries: nested ? resourceEntries : [sourceNodeEntry, ...resourceEntries],
        page: 1,
        pageSize: 100,
        total: resources.length + (nested ? 0 : 1),
        totalPages: 1
      } } });
      return true;
    }
    await route.fulfill({ json: { ok: true, data: book } });
    return true;
  });

  await page.goto('/books/context-book?resourceId=context-resource-1&returnTo=%2Flibrary%3Fstatus%3DREADING%26sort%3Dtitle');
  const sourcePath = page.getByRole('navigation', { name: '来源目录路径' });
  await expect(sourcePath).toBeVisible();
  await expect(page.getByRole('heading', { name: '来源目录与可读资源' })).toHaveCount(0);
  const sourceNodeActions = page.getByRole('button', { name: '管理 测试目录标题', exact: true });
  await sourceNodeActions.click();
  const sourceNodeMenu = page.getByRole('menu', { name: '管理来源目录' });
  await expect(sourceNodeMenu.getByRole('menuitem')).toHaveCount(4);
  await expect(sourceNodeMenu.getByRole('menuitem', { name: /^编辑/ })).toBeVisible();
  await expect(sourceNodeMenu.getByRole('menuitem', { name: /^重新生成封面/ })).toBeVisible();
  await expect(sourceNodeMenu.getByRole('menuitem', { name: /^识别元数据/ })).toBeVisible();
  await expect(sourceNodeMenu.getByRole('menuitem', { name: /^重新扫描文件/ })).toBeVisible();
  await page.keyboard.press('Escape');
  await page.getByRole('button', { name: '打开来源目录 测试目录标题' }).click();
  await expect(page.getByRole('heading', { name: '测试目录标题', level: 1 })).toBeVisible();
  await expect(page.getByText('目录简介', { exact: true })).toBeVisible();
  await expect(page.getByText('90%', { exact: true })).toBeVisible();
  await expect(sourcePath.getByRole('button', { name: book.title, exact: true })).toBeVisible();
  await expect(sourcePath.getByRole('button', { name: sourceNodeEntry.title, exact: true })).toBeVisible();
  await page.getByRole('button', { name: book.title, exact: true }).click();
  const first = page.getByRole('button', { name: '可读资源 1，阅读进度 80%' });
  const second = page.getByRole('button', { name: '可读资源 2，阅读进度 100%' });
  const resourceProgress = page.locator('[data-resource-progress]');
  await expect(resourceProgress).toHaveCount(2);
  await expect(resourceProgress.nth(0)).toHaveAttribute('data-resource-progress-state', 'reading');
  await expect(resourceProgress.nth(1)).toHaveAttribute('data-resource-progress-state', 'finished');
  await expect(page.locator('[data-resource-progress-complete]')).toHaveCount(1);
  const progressRatio = await resourceProgress.first().evaluate((element) => {
    const fill = element.firstElementChild?.getBoundingClientRect();
    const track = element.getBoundingClientRect();
    return fill && track.width > 0 ? fill.width / track.width : 0;
  });
  expect(progressRatio).toBeCloseTo(0.8, 2);

  const firstActions = page.getByRole('button', { name: '管理 第一资源', exact: true });
  await firstActions.click();
  const cardMenu = page.getByRole('menu', { name: '管理可读资源' });
  await expect(cardMenu.getByRole('menuitem')).toHaveCount(4);
  await expect(cardMenu.getByRole('menuitem', { name: /^编辑/ })).toBeVisible();
  await expect(cardMenu.getByRole('menuitem', { name: /^重新生成封面/ })).toBeVisible();
  await expect(cardMenu.getByRole('menuitem', { name: /^识别/ })).toBeVisible();
  await expect(cardMenu.getByRole('menuitem', { name: /^删除/ })).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(firstActions).toBeFocused();
  await firstActions.click({ button: 'right' });
  await expect(cardMenu).toBeVisible();
  await page.keyboard.press('Escape');
  await firstActions.press('Shift+F10');
  await expect(cardMenu).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(page).toHaveURL(/\/books\/context-book\?/);

  await expect(page.getByRole('button', { name: '管理资源', exact: true })).toHaveCount(0);
  const gridControl = page.getByRole('button', { name: '网格显示' });
  const listControl = page.getByRole('button', { name: '列表显示' });
  await expect(gridControl).toHaveAttribute('aria-pressed', 'true');
  await listControl.click();
  await expect(listControl).toHaveAttribute('aria-pressed', 'true');
  await gridControl.click();
  await expect(first).toBeVisible();
  await page.getByRole('button', { name: '返回全部图书', exact: true }).click();
  await expect(page).toHaveURL((url) => url.pathname === '/library' && url.searchParams.get('status') === 'READING' && url.searchParams.get('sort') === 'title');
  await page.goto('/books/context-book?resourceId=context-resource-1&returnTo=%2Flibrary%3Fstatus%3DREADING%26sort%3Dtitle');
  await expect(page.getByRole('button', { name: '返回全部图书', exact: true })).toBeVisible();
  await second.click();
  await expect(page).toHaveURL(/\/reader\/context-resource-2$/);
});

test('book detail requests a selected readable resource through the direct contract', async ({ page }) => {
  const selectedResource = {
    id: 'resource-2',
    bookId: 'direct-book',
    title: '第二资源',
    resourceIndex: 2,
    sortOrder: 1,
    format: 'PDF',
    publisher: null,
    publishedAt: null,
    language: null,
    isbn: null,
    identifier: null,
    narrator: null,
    abridged: null,
    importStatus: 'READY',
    importError: null,
    coverUrl: '',
    pageCount: 128,
    chapterCount: null,
    durationMs: null,
    trackCount: null,
    progress: 0,
    lastReadAt: null,
    hidden: false,
    readable: true,
    readerType: 'pdf',
    kindleSendAvailable: false,
    classification: { suggestedMediaKind: 'EBOOK', source: 'USER', reason: 'USER_SELECTED' },
    assets: [{ id: 'resource-2-asset', resourceId: 'resource-2', sourceNodeId: 'resource-2-source-node', role: 'PRIMARY', mimeType: 'application/pdf', sortOrder: 0, sizeBytes: 1024, size: '1 KB', url: '/api/assets/resource-2-asset', downloadUrl: '/api/assets/resource-2-asset?download=true' }]
  };
  const requestedResourceIds: Array<string | null> = [];
  await page.unroute('**/api/**');
  await mockWebAppApi(page, async (route, url) => {
    if (!url.pathname.includes('/api/books/direct-book')) return false;
    if (url.pathname.includes('/contents')) {
      await route.fulfill({ json: { ok: true, data: {
        bookId: 'direct-book',
        currentSourceNodeId: 'direct-book-node',
        currentResourceId: null,
        currentNode: { sourceNodeId: 'direct-book-node', parentSourceNodeId: null, name: '直接资源图书', title: '直接资源图书', description: null, kind: 'FOLDER', physicalKind: 'DIRECTORY', sizeBytes: null, observedAt: '2026-08-03T08:00:00.000Z', hasChildren: true, resourceId: null, representativeResourceId: selectedResource.id },
        currentResourceIds: [selectedResource.id],
        parentSourceNodeId: null,
        breadcrumbs: [],
        entries: [{ sourceNodeId: 'resource-2-node', parentSourceNodeId: 'direct-book-node', name: selectedResource.title, title: selectedResource.title, description: null, kind: 'FILE', physicalKind: 'REGULAR_FILE', sizeBytes: 1024, observedAt: '2026-08-03T08:00:00.000Z', hasChildren: false, resourceId: selectedResource.id, representativeResourceId: selectedResource.id }],
        page: 1,
        pageSize: 100,
        total: 1,
        totalPages: 1
      } } });
      return true;
    }
    requestedResourceIds.push(url.searchParams.get('resourceId'));
    await route.fulfill({
      json: {
        ok: true,
        data: {
          id: 'direct-book',
          title: '直接资源图书',
          author: '测试作者',
          description: '',
          tags: [],
          coverUrl: '',
          coverStatus: 'MISSING',
          gradient: 'from-orange-100 to-stone-200',
          seriesName: null,
          seriesIndex: null,
          publicationStatus: 'UNKNOWN',
          trackingStatus: 'NOT_TRACKING',
          ignored: false,
          organized: true,
          metadataQuality: 100,
          addedAt: '2026-08-03T08:00:00.000Z',
          updatedAt: '2026-08-03T08:00:00.000Z',
          continueResourceId: selectedResource.id,
          continueResourceTitle: selectedResource.title,
          continueResourceProgress: 0,
          continueReaderType: 'pdf',
          completed: false,
          resources: [selectedResource]
        }
      }
    });
    return true;
  });

  await page.goto('/books/direct-book?resourceId=resource-2');
  await expect(page.getByRole('heading', { name: '直接资源图书' })).toBeVisible();
  await expect(page.getByRole('button', { name: '第 1 卷' })).toBeVisible();
  expect(requestedResourceIds).toContain('resource-2');
});

test('mobile PWA shell and drawer consume safe-area insets without reserving bottom-nav space', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/?source=pwa');

  await page.evaluate(() => {
    document.documentElement.style.setProperty('--shuku-safe-area-top', '47px');
    document.documentElement.style.setProperty('--shuku-safe-area-right', '13px');
    document.documentElement.style.setProperty('--shuku-safe-area-bottom', '34px');
    document.documentElement.style.setProperty('--shuku-safe-area-left', '11px');
  });

  const content = page.getByTestId('app-shell-content');
  const main = page.getByTestId('app-shell-main');
  await page.getByRole('button', { name: '打开导航菜单' }).click();
  const navigation = page.getByTestId('mobile-navigation');

  await expect(page.locator('meta[name="viewport"]')).toHaveAttribute('content', /viewport-fit=cover/);
  await expect(content).toHaveCSS('padding-top', '75px');
  await expect(content).toHaveCSS('padding-right', '33px');
  await expect(content).toHaveCSS('padding-left', '31px');
  await expect(navigation).toHaveCSS('padding-top', '63px');
  await expect(navigation).toHaveCSS('padding-bottom', '56px');
  await expect(main).toHaveCSS('padding-bottom', '76px');
  await expect(page.locator('.shuku-mobile-shell-nav')).toHaveCount(0);
});

test('mobile drawer supports focus, escape, browser back, and route navigation', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/');

  const trigger = page.getByRole('button', { name: '打开导航菜单' });
  const drawer = page.getByTestId('mobile-navigation');

  await expect(trigger).toBeVisible();
  await expect(drawer).toBeHidden();
  await trigger.click();

  await expect(drawer).toBeVisible();
  await expect(trigger).toHaveAttribute('aria-expanded', 'true');
  await expect(page.locator('body')).toHaveCSS('overflow', 'hidden');
  await expect(drawer.getByRole('link', { name: '首页', exact: true })).toHaveAttribute('aria-current', 'page');
  await expect(drawer.getByRole('link', { name: '待读', exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: '关闭导航菜单' }).last()).toBeFocused();

  await page.keyboard.press('Escape');
  await expect(drawer).toBeHidden();
  await expect(trigger).toBeFocused();

  await page.keyboard.press('Control+k');
  await expect(drawer).toBeVisible();
  await expect(drawer.getByRole('textbox', { name: '搜索图书' })).toBeFocused();
  await page.keyboard.press('Escape');
  await expect(drawer).toBeHidden();

  await trigger.click();
  await page.goBack();
  await expect(page).toHaveURL(/\/$/);
  await expect(drawer).toBeHidden();

  await trigger.click();
  await drawer.getByRole('link', { name: '全部', exact: true }).click();
  await expect(page).toHaveURL(/\/library$/);
  await expect(drawer).toBeHidden();
});

test('desktop and mobile library navigation expose all, reading, series, and authors', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto('/');

  const sidebar = page.locator('aside');
  await expect(sidebar.getByRole('link', { name: '全部', exact: true })).toBeVisible();
  await expect(sidebar.getByRole('link', { name: '在读', exact: true })).toBeVisible();
  await expect(sidebar.getByRole('link', { name: '系列', exact: true })).toHaveAttribute('href', '/library/series');
  await expect(sidebar.getByRole('link', { name: '作者', exact: true })).toHaveAttribute('href', '/library/authors');
  await expect(sidebar.getByRole('link', { name: '未读', exact: true })).toHaveCount(0);
  await expect(sidebar.getByRole('link', { name: '已读', exact: true })).toHaveCount(0);
  const accountLink = sidebar.getByRole('link', { name: '进入账户与设置' });
  await expect(accountLink.getByText('Web', { exact: true })).toBeVisible();
  await expect(accountLink.getByText('账户与设置', { exact: true })).toBeVisible();
});

test('desktop sidebar search results match the search field width', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto('/');

  const searchInput = page.getByTestId('top-search-input');
  await searchInput.fill('流面体');

  const searchField = searchInput.locator('..');
  const searchDropdown = page.getByTestId('top-search-dropdown');
  await expect(searchDropdown).toBeVisible();

  const [searchFieldBox, searchDropdownBox] = await Promise.all([
    searchField.boundingBox(),
    searchDropdown.boundingBox()
  ]);
  expect(searchFieldBox).not.toBeNull();
  expect(searchDropdownBox).not.toBeNull();
  expect(searchDropdownBox?.width).toBe(searchFieldBox?.width);
});

test('shelf collections and unassigned shelves are the only top-level sidebar entries', async ({ page }) => {
  await page.route('**/api/shelves', async (route) => {
    await route.fulfill({
      json: {
        ok: true,
        data: {
          shelves: [
            { id: 'loose', name: '独立书架', kind: 'STATIC', collectionIds: [] },
            { id: 'assigned', name: '合集成员', kind: 'SMART', collectionIds: ['collection-a'] },
            { id: 'collection-a', name: '旅行合集', kind: 'COLLECTION', shelfCount: 1 }
          ]
        }
      }
    });
  });

  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto('/');
  const sidebar = page.locator('aside');
  await expect(sidebar.getByRole('link', { name: '独立书架', exact: true })).toHaveAttribute('data-shelf-kind', 'STATIC');
  await expect(sidebar.getByRole('link', { name: '旅行合集', exact: true })).toHaveAttribute('data-shelf-kind', 'COLLECTION');
  await expect(sidebar.getByRole('link', { name: '合集成员', exact: true })).toHaveCount(0);

  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole('button', { name: '打开导航菜单' }).click();
  const drawer = page.getByTestId('mobile-navigation');
  await expect(drawer.getByRole('link', { name: '系列', exact: true })).toBeVisible();
  await expect(drawer.getByRole('link', { name: '独立书架', exact: true })).toBeVisible();
  await expect(drawer.getByRole('link', { name: '旅行合集', exact: true })).toHaveAttribute('data-shelf-kind', 'COLLECTION');
  await expect(drawer.getByRole('link', { name: '合集成员', exact: true })).toHaveCount(0);
});

test('series and author groupings open the existing library with exact facet filters', async ({ page }) => {
  const requestedBookQueries: URL[] = [];
  await page.route('**/api/library/groupings?**', async (route) => {
    const url = new URL(route.request().url());
    const isSeries = url.searchParams.get('kind') === 'SERIES';
    await route.fulfill({
      json: {
        ok: true,
        data: {
          groups: [{
            id: isSeries ? 'series-facet' : 'author-facet',
            name: isSeries ? '星海丛书' : '林川',
            bookCount: isSeries ? 2 : 1,
            updatedAt: '2026-07-29T00:00:00Z'
          }],
          page: 1,
          pageSize: 48,
          total: 1,
          totalPages: 1
        }
      }
    });
  });
  await page.route('**/api/books?**', async (route) => {
    requestedBookQueries.push(new URL(route.request().url()));
    await route.fulfill({
      json: {
        ok: true,
        data: {
          books: [],
          total: 0,
          page: 1,
          pageSize: 50,
          totalPages: 1
        }
      }
    });
  });

  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto('/library/series');
  await expect(page.getByRole('heading', { name: '系列' })).toBeVisible();
  await page.getByRole('button', { name: /打开“星海丛书”/ }).click();
  await expect(page).toHaveURL(/facetKind=SERIES/);
  await expect(page.getByRole('heading', { name: '星海丛书' })).toBeVisible();
  await expect.poll(() => requestedBookQueries.some((url) => (
    url.searchParams.get('facetKind') === 'SERIES'
    && url.searchParams.get('facetId') === 'series-facet'
    && url.searchParams.get('sort') === 'series_index'
    && url.searchParams.get('sortDirection') === 'asc'
  ))).toBe(true);

  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/library/authors');
  await expect(page.getByRole('heading', { name: '作者' })).toBeVisible();
  await page.getByRole('button', { name: /打开“林川”/ }).click();
  await expect(page).toHaveURL(/facetKind=AUTHOR/);
  await expect(page.getByRole('heading', { name: '林川' })).toBeVisible();
  await expect.poll(() => requestedBookQueries.some((url) => (
    url.searchParams.get('facetKind') === 'AUTHOR'
    && url.searchParams.get('facetId') === 'author-facet'
    && url.searchParams.get('sort') === 'updated'
    && url.searchParams.get('sortDirection') === 'desc'
  ))).toBe(true);
  await page.getByRole('button', { name: '管理图书', exact: true }).click();
  const authorMoreFilters = page.getByRole('button', { name: '更多筛选', exact: true });
  await expect(authorMoreFilters).toHaveCSS('width', '48px');
  const authorFilterCount = page.getByTestId('library-advanced-filter-count');
  await expect(authorFilterCount).toHaveText('1');
  await expect(authorFilterCount).toHaveCSS('position', 'absolute');
  await authorMoreFilters.click();
  await page.getByRole('button', { name: '清除作者筛选', exact: true }).click();
  await expect(page).toHaveURL(/\/library$/);
});

test('collection creation can select standard and smart shelf members', async ({ page }) => {
  const members = [
    {
      id: 'member-static',
      name: '纸书计划',
      description: null,
      kind: 'STATIC',
      bookCount: 3,
      books: [],
      collectionIds: [],
      createdAt: '2026-07-29T00:00:00Z',
      updatedAt: '2026-07-29T00:00:00Z'
    },
    {
      id: 'member-smart',
      name: '近期科幻',
      description: null,
      kind: 'SMART',
      bookCount: 5,
      books: [],
      collectionIds: [],
      createdAt: '2026-07-29T00:00:00Z',
      updatedAt: '2026-07-29T00:00:00Z'
    }
  ];
  let collection: Record<string, unknown> | null = null;

  await page.route('**/api/shelves**', async (route) => {
    const url = new URL(route.request().url());
    const method = route.request().method();
    if (method === 'POST' && url.pathname.endsWith('/api/shelves')) {
      const body = route.request().postDataJSON() as { name: string; description: string; memberShelfIds: string[] };
      collection = {
        id: 'collection-new',
        name: body.name,
        description: body.description,
        kind: 'COLLECTION',
        shelfCount: body.memberShelfIds.length,
        memberShelfIds: body.memberShelfIds,
        shelves: members,
        page: 1,
        pageSize: 24,
        total: body.memberShelfIds.length,
        totalPages: 1,
        createdAt: '2026-07-29T00:00:00Z',
        updatedAt: '2026-07-29T00:00:00Z'
      };
      await route.fulfill({ status: 201, json: { ok: true, data: { shelf: collection } } });
      return;
    }
    if (url.pathname.endsWith('/api/shelves/collection-new')) {
      await route.fulfill({ json: { ok: true, data: { shelf: collection } } });
      return;
    }
    await route.fulfill({
      json: {
        ok: true,
        data: { shelves: collection ? [...members, collection] : members }
      }
    });
  });

  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto('/shelves?create=1&kind=collection');
  await expect(page.getByRole('button', { name: /书架合集/ })).toHaveAttribute('aria-pressed', 'true');
  await page.getByPlaceholder('例如：周末阅读、轻小说收藏').fill('暑期阅读');
  await page.getByRole('checkbox').nth(0).check();
  await page.getByRole('checkbox').nth(1).check();
  await page.getByRole('button', { name: '创建合集' }).click();

  await expect(page).toHaveURL(/shelf=collection-new/);
  await expect(page.getByRole('heading', { name: '暑期阅读' })).toBeVisible();
  await expect(page.getByRole('button', { name: /纸书计划/ })).toBeVisible();
  await expect(page.getByRole('button', { name: /近期科幻/ })).toBeVisible();
});

test('dashboard recent shelves share a ten-book horizontal rail with cover-bottom reading progress', async ({ page }) => {
  const requestedQueries: string[] = [];
  const recentReading = Array.from({ length: 12 }, (_, index) => ({
    id: `recent-reading-${index + 1}`,
    title: `最近阅读 ${index + 1}`,
    author: '测试作者',
    coverUrl: '',
    progress: index === 0 ? 80 : index === 1 ? 100 : index === 2 ? 0.4 : 0
  }));
  const recentAdded = recentReading.map((book, index) => ({
    ...book,
    id: `recent-added-${index + 1}`,
    title: `最近加入 ${index + 1}`
  }));

  await page.route('**/api/dashboard/recent-reading?**', async (route) => {
    requestedQueries.push(route.request().url());
    await route.fulfill({ json: { ok: true, data: { books: recentReading } } });
  });
  await page.route('**/api/dashboard/recent-books?**', async (route) => {
    requestedQueries.push(route.request().url());
    await route.fulfill({ json: { ok: true, data: { books: recentAdded } } });
  });

  await page.setViewportSize({ width: 1200, height: 900 });
  await page.goto('/');

  const readingShelf = page.getByTestId('dashboard-recent-reading-shelf');
  const addedShelf = page.getByTestId('dashboard-recent-added-shelf');
  await expect(readingShelf.locator('[data-book-cover="true"]')).toHaveCount(10);
  await expect(addedShelf.locator('[data-book-cover="true"]')).toHaveCount(10);

  for (const shelf of [readingShelf, addedShelf]) {
    const scroller = shelf.getByTestId(`${await shelf.getAttribute('data-testid')}-scroller`);
    await expect(scroller).toHaveCSS('overflow-x', 'auto');
    await expect(scroller).toHaveCSS('scrollbar-width', 'none');
    const geometry = await scroller.evaluate((element) => {
      const ledge = element.querySelector<HTMLElement>('[data-testid="bookshelf-ledge-asset"]');
      const covers = Array.from(element.querySelectorAll<HTMLElement>('[data-book-cover="true"]'));
      return {
        clientWidth: element.clientWidth,
        scrollWidth: element.scrollWidth,
        ledgeWidth: ledge?.getBoundingClientRect().width ?? 0,
        firstTop: covers[0]?.getBoundingClientRect().top ?? 0,
        lastTop: covers.at(-1)?.getBoundingClientRect().top ?? 0
      };
    });
    expect(geometry.scrollWidth).toBeGreaterThan(geometry.clientWidth);
    expect(geometry.ledgeWidth).toBeGreaterThanOrEqual(geometry.scrollWidth - 10);
    expect(Math.abs(geometry.firstTop - geometry.lastTop)).toBeLessThan(1);
  }

  for (const shelf of [readingShelf, addedShelf]) {
    const progressLines = shelf.locator('[data-bookshelf-progress]');
    await expect(progressLines).toHaveCount(2);
    await expect(shelf.locator('[data-bookshelf-progress-complete]')).toHaveCount(1);
    await expect(progressLines.nth(0)).toHaveAttribute('data-bookshelf-progress-state', 'reading');
    await expect(progressLines.nth(1)).toHaveAttribute('data-bookshelf-progress-state', 'finished');
    const progressRatio = await progressLines.first().evaluate((element) => {
      const fill = element.firstElementChild?.getBoundingClientRect();
      const track = element.getBoundingClientRect();
      return fill && track.width > 0 ? fill.width / track.width : 0;
    });
    expect(progressRatio).toBeCloseTo(0.8, 2);

    const metadata = shelf.getByTestId(`${await shelf.getAttribute('data-testid')}-metadata`);
    await expect(metadata).not.toContainText('未读');
    await expect(metadata).not.toContainText('阅读中');
    await expect(metadata).not.toContainText('已读完');
  }
  await expect(readingShelf.getByRole('button').first()).toHaveAccessibleName('查看《最近阅读 1》，阅读进度 80%');
  await expect(readingShelf.getByRole('button').nth(2)).toHaveAccessibleName('查看《最近阅读 3》');
  expect(requestedQueries.length).toBeGreaterThanOrEqual(2);
  expect(new Set(requestedQueries.map((url) => new URL(url).pathname))).toEqual(new Set([
    '/api/dashboard/recent-reading',
    '/api/dashboard/recent-books'
  ]));
  expect(requestedQueries.every((url) => new URL(url).searchParams.get('limit') === '10')).toBe(true);

  const readingScroller = readingShelf.getByTestId('dashboard-recent-reading-shelf-scroller');
  const firstBook = readingShelf.getByRole('button').first();
  const firstBookBox = await firstBook.boundingBox();
  if (!firstBookBox) throw new Error('Expected the first recent-reading book to be visible');

  await page.mouse.move(firstBookBox.x + firstBookBox.width / 2, firstBookBox.y + firstBookBox.height / 2);
  await page.mouse.down();
  await page.mouse.move(firstBookBox.x - 180, firstBookBox.y + firstBookBox.height / 2, { steps: 8 });
  await page.mouse.up();
  await expect.poll(() => readingScroller.evaluate((element) => element.scrollLeft)).toBeGreaterThan(100);
  await expect(page).toHaveURL(/\/$/);

  await readingScroller.evaluate((element) => { element.scrollLeft = 0; });
  await readingScroller.focus();
  await page.keyboard.press('ArrowRight');
  await expect.poll(() => readingScroller.evaluate((element) => element.scrollLeft)).toBeGreaterThan(0);
  await page.keyboard.press('End');
  await expect.poll(() => readingScroller.evaluate((element) => element.scrollLeft)).toBeGreaterThan(100);
});

test('wide shelf details use responsive bookshelf rows and load more on scroll', async ({ page }) => {
  const coverRequestUrls: string[] = [];
  const shelfRequestUrls: string[] = [];
  page.on('request', (request) => {
    if (new URL(request.url()).pathname.includes('/cover')) coverRequestUrls.push(request.url());
  });
  const books = Array.from({ length: 25 }, (_, index) => ({
    id: `shelf-book-${index + 1}`,
    title: `书架读物 ${index + 1}`,
    author: '测试作者',
    type: 'ebook',
    format: 'EPUB',
    formatValue: 'EPUB',
    status: '未读',
    statusValue: 'UNREAD',
    progress: 0,
    availableMediaKinds: ['EBOOK'],
    tags: [],
    coverUrl: index === 0
      ? '/test-landscape-cover.svg'
      : index === 1
        ? '/test-square-cover.svg'
        : index === 2
          ? '/test-extra-tall-cover.svg'
        : '',
    gradient: 'from-orange-100 to-stone-200'
  }));

  await page.route('**/test-landscape-cover.svg', async (route) => {
    await route.fulfill({
      contentType: 'image/svg+xml',
      body: '<svg xmlns="http://www.w3.org/2000/svg" width="320" height="180"><rect width="320" height="180" fill="#d94724"/></svg>'
    });
  });
  await page.route('**/test-square-cover.svg', async (route) => {
    await route.fulfill({
      contentType: 'image/svg+xml',
      body: '<svg xmlns="http://www.w3.org/2000/svg" width="320" height="320"><rect width="320" height="320" fill="#222222"/></svg>'
    });
  });
  await page.route('**/test-extra-tall-cover.svg', async (route) => {
    await route.fulfill({
      contentType: 'image/svg+xml',
      body: '<svg xmlns="http://www.w3.org/2000/svg" width="120" height="600"><rect width="120" height="600" fill="#5a4238"/></svg>'
    });
  });

  await page.route('**/api/shelves/wide-shelf**', async (route) => {
    const url = new URL(route.request().url());
    shelfRequestUrls.push(url.toString());
    const requestedPage = Number(url.searchParams.get('page') ?? '1');
    const requestedPageSize = Number(url.searchParams.get('pageSize') ?? '24');
    const start = (requestedPage - 1) * requestedPageSize;
    await route.fulfill({
      json: {
        ok: true,
        data: {
          shelf: {
            id: 'wide-shelf',
            name: '宽屏书架',
            description: '验证书架详情布局',
            bookCount: books.length,
            ...(requestedPage === 1 ? { bookIds: books.map((book) => book.id) } : {}),
            books: books.slice(start, start + requestedPageSize),
            page: requestedPage,
            pageSize: requestedPageSize,
            total: books.length,
            totalPages: Math.ceil(books.length / requestedPageSize),
            createdAt: '2026-07-17T08:30:00.000Z',
            updatedAt: '2026-07-17T08:30:00.000Z'
          }
        }
      }
    });
  });

  await page.setViewportSize({ width: 2048, height: 1152 });
  await page.goto('/shelves?shelf=wide-shelf');

  await expect(page.getByText('验证书架详情布局', { exact: true })).toBeVisible();
  await expect(page.getByRole('heading', { name: '宽屏书架' }).locator('..').getByText('25 本', { exact: true })).toBeVisible();
  await expect(page.getByText('收录图书', { exact: true })).toHaveCount(0);
  await expect(page.getByText('点击封面查看图书详情；使用“管理书架”调整名称和图书。', { exact: true })).toHaveCount(0);

  const grid = page.getByTestId('shelf-book-bookshelves');
  await expect(grid).toBeVisible();
  await expect(grid.locator('[data-book-cover="true"]')).toHaveCount(25);
  await expect.poll(() => coverRequestUrls.some((url) => url.includes('/shelf-book-4/cover?size=small'))).toBe(true);
  const firstCover = grid.locator('[data-book-cover="true"]').first();
  const firstBook = grid.getByRole('button', { name: '查看《书架读物 1》' });
  const firstBookVisual = firstBook.locator('[data-bookshelf-book-visual]');
  await expect(firstCover).toHaveCSS('object-fit', 'fill');
  await expect(grid.getByTestId('bookshelf-ledge')).toHaveCount(3);
  await expect(grid.getByTestId('bookshelf-ledge').first()).toHaveCSS('height', '30px');
  await expect(grid.getByTestId('bookshelf-ledge-asset').first()).toHaveCSS('height', '14px');
  await expect(grid.getByTestId('bookshelf-metadata-band')).toHaveCount(3);
  await expect(grid.locator('[data-bookshelf-book-metadata]')).toHaveCount(25);
  await expect(grid.locator('[data-bookshelf-book-metadata]').first()).toContainText('书架读物 1');
  await expect(grid.locator('[data-bookshelf-book-metadata]').first()).toContainText('测试作者');
  const ledgeFilter = await grid.getByTestId('bookshelf-ledge-asset').first().evaluate((element) => getComputedStyle(element).filter);
  expect(ledgeFilter.match(/drop-shadow/g)).toHaveLength(1);
  const shelfContact = await grid.evaluate((element) => {
    const firstLedge = element.querySelector<HTMLElement>('[data-testid="bookshelf-ledge-asset"]');
    const firstRowGrid = element.querySelector<HTMLElement>('[data-testid="bookshelf-row"] .grid');
    const rowCovers = firstRowGrid?.querySelectorAll<HTMLElement>('[data-book-cover="true"]');
    const firstCover = rowCovers?.[0];
    const lastCover = rowCovers?.[rowCovers.length - 1];
    if (!firstCover || !lastCover || !firstLedge || !firstRowGrid) return null;
    const coverBounds = firstCover.getBoundingClientRect();
    const lastCoverBounds = lastCover.getBoundingClientRect();
    const ledgeBounds = firstLedge.getBoundingClientRect();
    return {
      overlap: coverBounds.bottom - ledgeBounds.top,
      leftInset: coverBounds.left - ledgeBounds.left,
      rightInset: ledgeBounds.right - lastCoverBounds.right
    };
  });
  expect(shelfContact).not.toBeNull();
  expect(shelfContact?.overlap).toBeGreaterThanOrEqual(2);
  expect(shelfContact?.overlap).toBeLessThanOrEqual(4);
  expect(shelfContact?.leftInset).toBeGreaterThanOrEqual(20);
  expect(shelfContact?.rightInset).toBeGreaterThanOrEqual(20);
  await expect(firstBook.getByText('书架读物 1', { exact: true })).toHaveCount(0);
  await expect(page.getByRole('tooltip')).toHaveCount(0);
  await firstBook.hover();
  await expect.poll(async () => firstBookVisual.evaluate((element) => {
    const transform = getComputedStyle(element).transform;
    if (transform === 'none') return 1;
    return Number(transform.split('(')[1]?.split(',')[0] ?? 1);
  })).toBeGreaterThan(1);
  await expect(page.getByRole('tooltip')).toHaveCount(0);
  const layout = await grid.evaluate((element) => {
    const bounds = element.parentElement?.parentElement?.getBoundingClientRect();
    const covers = Array.from(element.querySelectorAll<HTMLElement>('[data-book-cover="true"]'));
    const coverVisuals = covers.map((cover) => cover.closest<HTMLElement>('[data-bookshelf-book-visual]'));
    const coverSizes = covers.map((cover) => {
      const styles = getComputedStyle(cover);
      return {
        width: Number.parseFloat(styles.width),
        height: Number.parseFloat(styles.height)
      };
    });
    const rows = Array.from(element.querySelectorAll<HTMLElement>('[data-testid="bookshelf-row"]'));
    const firstRowGrid = rows[0]?.querySelector<HTMLElement>('.grid');
    const firstCoverShadow = getComputedStyle(covers[0]).boxShadow;
    return {
      contentWidth: bounds?.width ?? 0,
      coverWidths: coverSizes.map(({ width }) => width),
      coverHeights: coverSizes.map(({ height }) => height),
      coverRatios: coverSizes.map(({ height, width }) => height / width),
      coverVisualWidths: coverVisuals.map((visual) => visual ? Number.parseFloat(getComputedStyle(visual).width) : 0),
      firstCoverBackground: getComputedStyle(covers[0]).backgroundColor,
      firstCoverHasVisibleShadow: firstCoverShadow !== 'none'
        && firstCoverShadow
          .split(/,\s*(?=rgba)/)
          .some((shadow) => !shadow.startsWith('rgba(0, 0, 0, 0)')),
      firstCoverHasInsetShadow: firstCoverShadow.includes('inset'),
      rowCount: rows.length,
      columnCount: firstRowGrid ? getComputedStyle(firstRowGrid).gridTemplateColumns.split(' ').filter(Boolean).length : 0,
      firstRowTop: covers[0]?.getBoundingClientRect().top,
      eleventhTop: covers[10]?.getBoundingClientRect().top
    };
  });

  expect(layout.contentWidth).toBeLessThanOrEqual(1280);
  expect(layout.columnCount).toBe(10);
  expect(layout.rowCount).toBe(3);
  expect(Math.min(...layout.coverWidths.slice(0, 2))).toBeGreaterThan(90);
  expect(Math.min(...layout.coverWidths.slice(3))).toBeGreaterThan(90);
  expect(Math.max(...layout.coverWidths)).toBeLessThanOrEqual(130);
  expect(layout.coverWidths[2]).toBeLessThan(90);
  expect(
    layout.coverHeights.every((height, index) => height <= (layout.coverVisualWidths[index] ?? 0) * 1.5 + 0.5),
    JSON.stringify({ coverHeights: layout.coverHeights, coverVisualWidths: layout.coverVisualWidths })
  ).toBe(true);
  expect(Math.abs((layout.coverHeights[2] ?? 0) - (layout.coverVisualWidths[2] ?? 0) * 1.5)).toBeLessThan(0.5);
  expect(Math.abs((layout.coverRatios[0] ?? 0) - 180 / 320)).toBeLessThan(0.01);
  expect(Math.abs((layout.coverRatios[1] ?? 0) - 1)).toBeLessThan(0.01);
  expect(Math.abs((layout.coverRatios[2] ?? 0) - 5)).toBeLessThan(0.01);
  expect(layout.coverRatios.slice(3).every((ratio) => Math.abs(ratio - 1.5) < 0.01)).toBe(true);
  expect(layout.firstCoverBackground).toBe('rgba(0, 0, 0, 0)');
  expect(layout.firstCoverHasVisibleShadow).toBe(true);
  expect(layout.firstCoverHasInsetShadow).toBe(false);
  expect(layout.eleventhTop).toBeGreaterThan(layout.firstRowTop ?? 0);
  await expect(grid.getByRole('button', { name: '查看《书架读物 25》' })).toBeVisible();
  await expect(page.getByText('已加载 25 / 25 本')).toBeVisible();
  expect(shelfRequestUrls.some((url) => new URL(url).searchParams.get('page') === '2')).toBe(true);
  await expect(page.getByRole('button', { name: '下一页' })).toHaveCount(0);

  await page.setViewportSize({ width: 390, height: 844 });
  await expect.poll(() => grid.evaluate((element) => {
    const firstRowGrid = element.querySelector<HTMLElement>('[data-testid="bookshelf-row"] .grid');
    return firstRowGrid
      ? getComputedStyle(firstRowGrid).gridTemplateColumns.split(' ').filter(Boolean).length
      : 0;
  })).toBe(3);
  const compactTallCover = grid.locator('[data-book-cover="true"]').nth(2);
  const compactTallGeometry = await compactTallCover.evaluate((cover) => {
    const visual = cover.closest<HTMLElement>('[data-bookshelf-book-visual]');
    const coverStyles = getComputedStyle(cover);
    return {
      coverHeight: Number.parseFloat(coverStyles.height),
      visualWidth: visual ? Number.parseFloat(getComputedStyle(visual).width) : 0
    };
  });
  expect(
    Math.abs(compactTallGeometry.coverHeight - compactTallGeometry.visualWidth * 1.5),
    JSON.stringify(compactTallGeometry)
  ).toBeLessThan(0.5);
  expect(compactTallGeometry.visualWidth).not.toBeCloseTo(layout.coverVisualWidths[2] ?? 0, 1);
  await expect(grid.getByTestId('bookshelf-ledge')).toHaveCount(9);
});

test('mobile page actions keep labels horizontal and move below long headings', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/import-tasks');

  const title = page.getByRole('heading', { name: '导入任务' });
  const action = page.getByRole('button', { name: '强制重新识别' });
  await expect(title).toBeVisible();
  await expect(action).toBeVisible();

  const layout = await page.evaluate(() => {
    const heading = document.querySelector('h1');
    const button = Array.from(document.querySelectorAll('button')).find((item) => item.textContent?.includes('强制重新识别'));
    if (!heading || !button) return null;
    const headingBounds = heading.getBoundingClientRect();
    const buttonBounds = button.getBoundingClientRect();
    return {
      actionTop: buttonBounds.top,
      actionHeight: buttonBounds.height,
      headingBottom: headingBounds.bottom,
      whiteSpace: getComputedStyle(button).whiteSpace
    };
  });

  expect(layout).not.toBeNull();
  expect(layout?.actionTop).toBeGreaterThan(layout?.headingBottom ?? 0);
  expect(layout?.actionHeight).toBeLessThanOrEqual(48);
  expect(layout?.whiteSpace).toBe('nowrap');
});

test('mobile data-heavy views use cards instead of compressed desktop tables', async ({ context, page }) => {
  const mobileBook = {
    id: 'mobile-book',
    title: '用于验证移动端卡片布局的超长读物标题',
    author: '未知作者',
    description: '',
    tags: ['用于验证窄屏单行截断的超长格式标签'],
    coverUrl: '/api/books/mobile-book/cover',
    coverStatus: 'MISSING',
    gradient: 'from-orange-100 to-stone-200',
    seriesName: null,
    seriesIndex: null,
    metadataQuality: 20,
    publicationStatus: 'UNKNOWN',
    trackingStatus: 'NOT_TRACKING',
    ignored: false,
    organized: true,
    addedAt: '2026-07-17T08:30:00.000Z',
    updatedAt: '2026-07-17T08:30:00.000Z',
    availableMediaKinds: ['EBOOK'],
    continueResourceId: 'mobile-resource',
    continueResourceTitle: '全本',
    continueResourceProgress: 42,
    continueReaderType: 'reflowable',
    completed: false,
    statusValue: 'UNREAD',
    lastReadAt: '2026-07-17T08:30:00.000Z',
    importedAt: '2026-07-17T08:30:00.000Z',
    resources: [{ id: 'mobile-resource', bookId: 'mobile-book', title: '全本', resourceIndex: null, sortOrder: 0, format: 'EPUB', readerType: 'reflowable', classification: { source: 'AUTO', reason: 'FORMAT_DEFAULT', suggestedMediaKind: 'EBOOK' }, publisher: null, publishedAt: null, language: null, isbn: null, identifier: null, narrator: null, abridged: null, importStatus: 'READY', importError: null, coverUrl: '', pageCount: null, chapterCount: null, durationMs: null, trackCount: null, progress: 42, lastReadAt: '2026-07-17T08:30:00.000Z', hidden: false, readable: true, kindleSendAvailable: false, assets: [] }]
  };

  await page.route('**/api/books?**', async (route) => {
    await route.fulfill({ json: { ok: true, data: { books: [mobileBook], total: 1, page: 1, pageSize: 24, totalPages: 1 } } });
  });
  await page.setViewportSize({ width: 320, height: 844 });

  await page.goto('/library');
  await page.getByRole('button', { name: '管理图书', exact: true }).click();
  const mobileTypeSelect = page.getByRole('button', { name: '图书类型', exact: true });
  await expect(mobileTypeSelect).toBeVisible();
  await expect(page.getByRole('group', { name: '图书类型', exact: true })).toBeHidden();
  await mobileTypeSelect.click();
  await page.getByRole('option', { name: '电子书', exact: true }).click();
  await expect(mobileTypeSelect).toContainText('电子书');
  await mobileTypeSelect.click();
  await page.getByRole('option', { name: '全部', exact: true }).click();
  const mobileMoreFilters = page.getByRole('button', { name: '更多筛选', exact: true });
  const mobileSearch = page.getByPlaceholder('搜索书名、作者或标签');
  const [searchBox, typeSelectBox, moreFiltersBox] = await Promise.all([
    mobileSearch.boundingBox(),
    mobileTypeSelect.boundingBox(),
    mobileMoreFilters.boundingBox()
  ]);
  expect(searchBox?.width).toBeGreaterThan(0);
  expect(typeSelectBox?.width).toBe(112);
  expect(moreFiltersBox?.width).toBe(48);
  expect(moreFiltersBox?.height).toBe(48);
  const searchCenter = (searchBox?.y ?? 0) + (searchBox?.height ?? 0) / 2;
  const typeSelectCenter = (typeSelectBox?.y ?? 0) + (typeSelectBox?.height ?? 0) / 2;
  const moreFiltersCenter = (moreFiltersBox?.y ?? 0) + (moreFiltersBox?.height ?? 0) / 2;
  expect(Math.abs(searchCenter - typeSelectCenter)).toBeLessThan(1);
  expect(Math.abs(typeSelectCenter - moreFiltersCenter)).toBeLessThan(1);
  await mobileMoreFilters.click();
  await expect(page.getByText('智能组合筛选', { exact: true })).toBeVisible();
  await expect(page.getByText('所有图书、资源、资产、阅读和书架维度都可以自由组合，修改后实时生效。', { exact: true })).toHaveCount(0);
  await mobileMoreFilters.click();
  const mobileCard = page.getByTestId('book-list-mobile-card');
  await expect(mobileCard).toBeVisible();
  await expect(page.getByTestId('book-list-desktop-table')).toBeHidden();
  const mobileSelection = mobileCard.getByRole('checkbox');
  await expect(mobileSelection).toHaveAttribute('aria-label', `选择《${mobileBook.title}》`);
  await expect(mobileSelection).toHaveClass('sr-only');
  await expect(mobileSelection).not.toBeChecked();
  const mobileMetadata = page.getByTestId('book-list-mobile-metadata');
  await expect(mobileMetadata).toHaveCSS('flex-wrap', 'nowrap');
  const metadataBadges = mobileMetadata.locator(':scope > span');
  await expect(metadataBadges).toHaveCount(3);
  const badgeTopEdges = await metadataBadges.evaluateAll((badges) => badges.map((badge) => badge.getBoundingClientRect().top));
  expect(new Set(badgeTopEdges).size).toBe(1);
  await expect(page.getByRole('button', { name: `查看《${mobileBook.title}》`, exact: true })).toHaveCount(0);
  await mobileMetadata.click();
  await expect(mobileSelection).toBeChecked();
  const mobileSelectionSurface = page.getByTestId('book-list-mobile-selection-surface');
  await expect(mobileSelectionSurface).toHaveCSS('background-color', 'rgb(255, 248, 245)');
  expect(await mobileSelectionSurface.evaluate((element) => getComputedStyle(element).boxShadow)).toContain('rgb(239, 77, 47) 1px 0px 0px 0px inset');
  await mobileMetadata.click();
  await expect(mobileSelection).not.toBeChecked();
  await expect(page.getByRole('button', { name: `删除《${mobileBook.title}》`, exact: true })).toHaveCount(0);
  await expect(page.getByRole('button', { name: '更多筛选', exact: true })).toHaveCSS('width', '48px');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
  await page.waitForTimeout(550);
  await page.getByRole('button', { name: `查看《${mobileBook.title}》详情`, exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`/books/${mobileBook.id}$`));

  const organizePage = await context.newPage();
  await mockWebAppApi(organizePage);
  await organizePage.route('**/api/organize/jobs?**', async (route) => {
    await route.fulfill({
      json: {
        ok: true,
        data: {
          jobs: [{
            id: 'mobile-job',
            status: 'REVIEWING',
            issueCodes: ['MISSING_AUTHOR'],
            summary: '等待补充作者信息',
            updatedAt: '2026-07-17T08:30:00.000Z',
            book: mobileBook,
            suggestions: [],
          }],
          books: [mobileBook],
          total: 1
        }
      }
    });
  });
  await organizePage.setViewportSize({ width: 390, height: 844 });
  await organizePage.goto('/organize');
  await expect(organizePage.getByTestId('organize-job-mobile-card')).toBeVisible();
  await expect(organizePage.getByTestId('organize-job-desktop-table')).toBeHidden();
  await organizePage.close();

  const logsPage = await context.newPage();
  await mockWebAppApi(logsPage);
  await logsPage.route('**/api/management/events?**', async (route) => {
    await route.fulfill({
      json: {
        ok: true,
        data: {
          events: [{ id: 'mobile-event', level: 'warning', source: 'import', actorType: 'system', action: 'import.failed', message: '用于验证长日志摘要在手机上自然换行', metadata: {}, createdAt: '2026-07-17T08:30:00.000Z' }],
          total: 1,
          totalPages: 1,
          storage: { sizeBytes: 0, maxBytes: 1024 },
          facets: { sources: [], levels: [] }
        }
      }
    });
  });
  await logsPage.setViewportSize({ width: 390, height: 844 });
  await logsPage.goto('/management/logs');
  await expect(logsPage.getByTestId('system-event-mobile-card')).toBeVisible();
  await expect(logsPage.getByTestId('system-event-desktop-table')).toBeHidden();
  await logsPage.close();
});

test('all-books shelves load the next batch while scrolling down', async ({ page }) => {
  const requestedPages: string[] = [];
  const coverRequestUrls: string[] = [];
  page.on('request', (request) => {
    if (new URL(request.url()).pathname.includes('/cover')) coverRequestUrls.push(request.url());
  });
  const books = Array.from({ length: 75 }, (_, index) => ({
    id: `continuous-book-${index + 1}`,
    title: `连续书架读物 ${index + 1}`,
    author: '测试作者',
    type: 'ebook',
    format: 'EPUB',
    formatValue: 'EPUB',
    status: '未读',
    statusValue: 'UNREAD',
    progress: 0,
    availableMediaKinds: ['EBOOK'],
    tags: [],
    coverUrl: `/api/books/continuous-book-${index + 1}/cover?size=medium`,
    gradient: 'from-orange-100 to-stone-200'
  }));

  await page.route('**/api/books?**', async (route) => {
    const url = new URL(route.request().url());
    const requestedPage = Number(url.searchParams.get('page') ?? '1');
    const requestedPageSize = Number(url.searchParams.get('pageSize') ?? '50');
    requestedPages.push(String(requestedPage));
    const start = (requestedPage - 1) * requestedPageSize;
    await route.fulfill({
      json: {
        ok: true,
        data: {
          books: books.slice(start, start + requestedPageSize),
          total: books.length,
          page: requestedPage,
          pageSize: requestedPageSize,
          totalPages: Math.ceil(books.length / requestedPageSize)
        }
      }
    });
  });

  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto('/library');

  const shelves = page.getByTestId('library-book-bookshelves');
  await expect(shelves.locator('[data-book-cover="true"]')).toHaveCount(50);
  await expect.poll(() => coverRequestUrls.some((url) => url.includes('/continuous-book-1/cover?size=small'))).toBe(true);
  await shelves.locator('[data-book-cover="true"]').last().scrollIntoViewIfNeeded();
  await expect.poll(() => requestedPages.includes('2')).toBe(true);
  await expect(shelves.locator('[data-book-cover="true"]')).toHaveCount(75);
  await expect(page.getByText('已加载 75 / 75 本')).toBeVisible();
});

test('desktop book list opens details from both the cover and title', async ({ page }) => {
  const requestedPageSizes: string[] = [];
  const requestedPages: string[] = [];
  const requestedSorts: Array<{ sort: string; direction: string }> = [];
  const requestedViews: string[] = [];
  const book = {
    id: 'desktop-list-book',
    title: '桌面列表入口测试',
    author: '测试作者',
    type: 'ebook',
    format: 'EPUB',
    formatValue: 'EPUB',
    status: '未读',
    statusValue: 'UNREAD',
    progress: 0,
    added: '2026-07-20',
    lastRead: '未阅读',
    tags: [],
    publisher: '测试出版社',
    seriesName: '测试系列',
    coverUrl: '/api/books/desktop-list-book/cover',
    coverStatus: 'READY',
    availableMediaKinds: ['EBOOK'],
    lastReadAt: null,
    importedAt: '2026-07-20T00:00:00.000Z',
    gradient: 'from-orange-100 to-stone-200'
  };
  const managementBooks = Array.from({ length: 20 }, (_, index) => index === 0 ? book : {
    ...book,
    id: `desktop-list-book-${index + 1}`,
    title: `桌面列表入口测试 ${index + 1}`,
    coverUrl: `/api/books/desktop-list-book-${index + 1}/cover`
  });
  await page.route('**/api/books?**', async (route) => {
    const requestUrl = new URL(route.request().url());
    const requestedPageSize = requestUrl.searchParams.get('pageSize') ?? '';
    const requestedPage = requestUrl.searchParams.get('page') ?? '1';
    const requestedSort = requestUrl.searchParams.get('sort') ?? '';
    const requestedDirection = requestUrl.searchParams.get('sortDirection') ?? '';
    const responseBook = requestUrl.searchParams.get('view') === 'bookshelf'
      ? {
          id: book.id,
          title: book.title,
          author: book.author,
          format: book.format,
          gradient: book.gradient,
          coverStatus: 'PENDING',
          coverUrl: book.coverUrl,
          availableMediaKinds: book.availableMediaKinds,
          progress: 64
      }
      : book;
    const responseBooks = requestUrl.searchParams.get('view') === 'bookshelf' ? [responseBook] : managementBooks;
    requestedPageSizes.push(requestedPageSize);
    requestedPages.push(requestedPage);
    requestedSorts.push({ sort: requestedSort, direction: requestedDirection });
    requestedViews.push(requestUrl.searchParams.get('view') ?? '');
    const numericPageSize = Number(requestedPageSize);
    await route.fulfill({ json: { ok: true, data: { books: responseBooks, total: 240, page: Number(requestedPage), pageSize: numericPageSize, totalPages: numericPageSize > 0 ? Math.ceil(240 / numericPageSize) : 1 } } });
  });
  await page.setViewportSize({ width: 1280, height: 900 });

  await page.goto('/library');
  await expect(page.getByRole('button', { name: '保存筛选' })).toHaveCount(0);
  await expect(page.getByRole('button', { name: '更多筛选' })).toHaveCount(0);
  await page.getByRole('button', { name: '管理图书', exact: true }).click();
  const desktopMoreFilters = page.getByRole('button', { name: '更多筛选' });
  await expect(desktopMoreFilters).toHaveCSS('height', '48px');
  await desktopMoreFilters.click();
  await expect(page.getByRole('button', { name: '保存筛选' })).toHaveCount(0);
  await expect(page.getByRole('button', { name: '网格排序方式' })).toHaveCount(0);
  await desktopMoreFilters.click();
  const managementViewport = page.getByTestId('library-management-viewport');
  const tableViewport = page.getByTestId('book-list-desktop-table');
  const titleHeader = page.getByRole('columnheader', { name: '标题排序' });
  const initialHeaderTop = await titleHeader.evaluate((element) => element.getBoundingClientRect().top);
  await expect.poll(() => tableViewport.evaluate((element) => element.scrollHeight > element.clientHeight)).toBe(true);
  await tableViewport.evaluate((element) => { element.scrollTop = element.scrollHeight; });
  await expect.poll(() => tableViewport.evaluate((element) => element.scrollTop)).toBeGreaterThan(0);
  const scrolledHeaderTop = await titleHeader.evaluate((element) => element.getBoundingClientRect().top);
  expect(Math.abs(scrolledHeaderTop - initialHeaderTop)).toBeLessThan(1);
  await expect(managementViewport).toBeInViewport();
  await expect(page.getByTestId('library-pagination')).toBeInViewport();
  expect(await page.evaluate(() => window.scrollY)).toBe(0);
  const pagination = page.getByTestId('library-pagination');
  await expect(pagination.getByText('共 240 本图书', { exact: true })).toBeVisible();
  await expect(pagination.getByText('第 1 / 12 页', { exact: true })).toBeVisible();
  await expect(pagination.getByRole('button', { name: '上一页' })).toBeDisabled();
  await expect(pagination.getByRole('button', { name: '下一页' })).toBeEnabled();
  await expect(pagination.getByRole('button', { name: '第 1 页' })).toHaveAttribute('aria-current', 'page');
  await expect(pagination.getByText('…', { exact: true })).toBeVisible();
  await pagination.getByRole('button', { name: '下一页' }).click();
  await expect.poll(() => requestedPages.at(-1)).toBe('2');
  await expect(pagination.getByRole('button', { name: '第 2 页' })).toHaveAttribute('aria-current', 'page');
  await pagination.getByRole('button', { name: '第 12 页' }).click();
  await expect.poll(() => requestedPages.at(-1)).toBe('12');
  await expect(pagination.getByRole('button', { name: '第 12 页' })).toHaveAttribute('aria-current', 'page');
  await expect(pagination.getByRole('button', { name: '下一页' })).toBeDisabled();
  await expect(pagination.getByRole('button', { name: '第 11 页' })).toBeVisible();
  await expect(page.getByRole('button', { name: '每页数量' })).toContainText('20 本/页');
  await page.getByRole('button', { name: '每页数量' }).click();
  await page.getByRole('option', { name: '100 本/页' }).click();
  await expect.poll(() => requestedPageSizes.at(-1)).toBe('100');
  await page.getByRole('button', { name: '每页数量' }).click();
  await page.getByRole('option', { name: '500 本/页' }).click();
  await expect.poll(() => requestedPageSizes.at(-1)).toBe('500');
  await page.getByRole('button', { name: '每页数量' }).click();
  await page.getByRole('option', { name: '全部显示' }).click();
  await expect.poll(() => requestedPageSizes.at(-1)).toBe('0');
  await expect.poll(() => requestedViews.at(-1)).toBe('management');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
  await expect(page.getByRole('button', { name: '进度排序' })).toHaveCount(0);
  await expect(page.getByRole('columnheader', { name: '标题排序' })).toBeVisible();
  await expect(page.getByRole('columnheader', { name: '作者排序' })).toBeVisible();
  await expect(page.getByRole('columnheader', { name: '系列排序' })).toBeVisible();
  await page.getByRole('button', { name: '标题排序' }).click();
  await expect.poll(() => requestedSorts.at(-1)).toEqual({ sort: 'title', direction: 'asc' });
  await page.getByRole('button', { name: '标题排序，当前正序' }).click();
  await expect.poll(() => requestedSorts.at(-1)).toEqual({ sort: 'title', direction: 'desc' });
  await expect(page).toHaveURL(/sort=title/);
  await expect(page).toHaveURL(/sortDirection=desc/);
  await page.getByRole('button', { name: '作者排序' }).click();
  await expect.poll(() => requestedSorts.at(-1)).toEqual({ sort: 'author', direction: 'asc' });
  await page.getByRole('button', { name: '系列排序' }).click();
  await expect.poll(() => requestedSorts.at(-1)).toEqual({ sort: 'series', direction: 'asc' });
  await page.getByRole('button', { name: '加入时间排序' }).click();
  await expect.poll(() => requestedSorts.at(-1)).toEqual({ sort: 'recent_import', direction: 'desc' });
  await page.getByRole('button', { name: '加入时间排序，当前倒序' }).click();
  await expect.poll(() => requestedSorts.at(-1)).toEqual({ sort: 'recent_import', direction: 'asc' });

  const managedBookRow = page.locator('[data-book-id="desktop-list-book"]');
  await expect(managedBookRow.getByRole('button', { name: '查看《桌面列表入口测试》', exact: true })).toHaveCount(0);
  await expect(managedBookRow.getByRole('button', { name: '删除《桌面列表入口测试》', exact: true })).toHaveCount(0);
  await managedBookRow.getByRole('checkbox').check();
  await page.getByRole('button', { name: '批量操作', exact: true }).click();
  const batchDialog = page.getByRole('dialog', { name: '批量更新元数据' });
  await expect(batchDialog.getByRole('button', { name: '删除', exact: true })).toHaveCount(0);
  await expect(batchDialog.getByRole('button', { name: '合并', exact: true })).toHaveCount(0);
  await batchDialog.getByRole('button', { name: '关闭批量操作' }).click();
  await page.locator('[data-book-id="desktop-list-book-2"]').getByRole('checkbox').check();
  await page.getByRole('button', { name: '批量操作', exact: true }).click();
  const twoBookDialog = page.getByRole('dialog', { name: '批量更新元数据' });
  await expect(twoBookDialog.getByRole('button', { name: '合并', exact: true })).toHaveCount(0);
  await expect(twoBookDialog.getByRole('button', { name: '删除', exact: true })).toHaveCount(0);
  await twoBookDialog.getByRole('button', { name: '关闭批量操作' }).click();
  await managedBookRow.click({ button: 'right' });
  await expect(page.getByRole('menuitem', { name: /批量删除图书/ })).toHaveCount(0);
  await page.keyboard.press('Escape');
  await page.getByRole('button', { name: '清空', exact: true }).click();

  await page.getByRole('button', { name: '查看《桌面列表入口测试》封面' }).click();
  await expect(page).toHaveURL((url) => url.pathname === '/books/desktop-list-book' && url.searchParams.get('returnTo') === '/library?sortDirection=asc');

  await page.goto('/library');
  await page.getByRole('button', { name: '查看《桌面列表入口测试》详情' }).click();
  await expect(page).toHaveURL((url) => url.pathname === '/books/desktop-list-book' && url.searchParams.get('returnTo') === '/library');
});
