import { expect, test, type Page } from '@playwright/test';

async function mockWebAppApi(page: Page) {
  await page.route('**/api/**', async (route) => {
    const pathname = new URL(route.request().url()).pathname;
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
              monitorFolderIds: [],
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
    if (pathname.endsWith('/api/dashboard/recent-books') || pathname.endsWith('/api/works')) {
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

test('PWA launch parameters keep the responsive web shell on mobile widths', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/?source=pwa');

  await expect(page).toHaveURL(/\/?\?source=pwa$/);
  await expect(page.getByRole('heading', { name: '主页' })).toBeVisible();
  await expect(page.locator('html')).not.toHaveClass(/pwa-native/);
  await expect(page.getByRole('link', { name: '未读', exact: true })).toHaveCount(0);
  await expect(page.getByRole('link', { name: '已读', exact: true })).toHaveCount(0);
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

test('desktop library navigation keeps only All and Reading', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto('/');

  const sidebar = page.locator('aside');
  await expect(sidebar.getByRole('link', { name: '全部', exact: true })).toBeVisible();
  await expect(sidebar.getByRole('link', { name: '进行中', exact: true })).toBeVisible();
  await expect(sidebar.getByRole('link', { name: '未读', exact: true })).toHaveCount(0);
  await expect(sidebar.getByRole('link', { name: '已读', exact: true })).toHaveCount(0);
  const accountLink = sidebar.getByRole('link', { name: '进入账户与设置' });
  await expect(accountLink.getByText('Web', { exact: true })).toBeVisible();
  await expect(accountLink.getByText('账户与设置', { exact: true })).toBeVisible();
});

test('dashboard recent shelves share a ten-book horizontal rail without visible scrollbars or progress bars', async ({ page }) => {
  const requestedQueries: string[] = [];
  const recentReading = Array.from({ length: 12 }, (_, index) => ({
    id: `recent-reading-${index + 1}`,
    title: `最近阅读 ${index + 1}`,
    author: '测试作者',
    type: 'ebook',
    format: 'EPUB',
    formatValue: 'EPUB',
    status: '在读',
    statusValue: 'READING',
    progress: 40 + index,
    lastReadAt: `2026-07-24T${String(12 - index).padStart(2, '0')}:00:00.000Z`,
    tags: [],
    coverUrl: '',
    gradient: 'from-orange-100 to-stone-200'
  }));
  const recentAdded = recentReading.map((book, index) => ({
    ...book,
    id: `recent-added-${index + 1}`,
    title: `最近加入 ${index + 1}`,
    lastReadAt: null,
    progress: 0
  }));

  await page.route('**/api/works?**', async (route) => {
    requestedQueries.push(route.request().url());
    await route.fulfill({ json: { ok: true, data: { books: recentReading, total: recentReading.length } } });
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

  await expect(readingShelf.locator('[data-bookshelf-progress]')).toHaveCount(0);
  expect(requestedQueries.some((url) => new URL(url).searchParams.get('pageSize') === '10')).toBe(true);
  expect(requestedQueries.some((url) => new URL(url).searchParams.get('limit') === '10')).toBe(true);
});

test('wide shelf details use responsive bookshelf rows and load more on scroll', async ({ page }) => {
  const coverRequestUrls: string[] = [];
  const shelfRequestUrls: string[] = [];
  page.on('request', (request) => {
    if (new URL(request.url()).pathname.includes('/cover')) coverRequestUrls.push(request.url());
  });
  const books = Array.from({ length: 25 }, (_, index) => ({
    id: `shelf-work-${index + 1}`,
    title: `书架读物 ${index + 1}`,
    author: '测试作者',
    type: 'ebook',
    format: 'EPUB',
    formatValue: 'EPUB',
    status: '未读',
    statusValue: 'UNREAD',
    progress: 0,
    tags: [],
    coverUrl: index === 0 ? '/test-landscape-cover.svg' : '',
    gradient: 'from-orange-100 to-stone-200'
  }));

  await page.route('**/test-landscape-cover.svg', async (route) => {
    await route.fulfill({
      contentType: 'image/svg+xml',
      body: '<svg xmlns="http://www.w3.org/2000/svg" width="320" height="180"><rect width="320" height="180" fill="#d94724"/></svg>'
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

  const grid = page.getByTestId('shelf-book-bookshelves');
  await expect(grid).toBeVisible();
  await expect(grid.locator('[data-book-cover="true"]')).toHaveCount(25);
  await expect.poll(() => coverRequestUrls.some((url) => url.includes('/shelf-work-2/cover?size=small'))).toBe(true);
  const firstCover = grid.locator('[data-book-cover="true"]').first();
  const firstBook = grid.getByRole('button', { name: '查看《书架读物 1》' });
  const firstBookVisual = firstBook.locator('[data-bookshelf-book-visual]');
  await expect(firstCover.locator('img')).toHaveCSS('object-fit', 'contain');
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
    const rows = Array.from(element.querySelectorAll<HTMLElement>('[data-testid="bookshelf-row"]'));
    const firstRowGrid = rows[0]?.querySelector<HTMLElement>('.grid');
    const firstCoverShadow = getComputedStyle(covers[0]).boxShadow;
    return {
      contentWidth: bounds?.width ?? 0,
      coverWidths: covers.map((cover) => cover.getBoundingClientRect().width),
      coverRatios: covers.map((cover) => cover.getBoundingClientRect().height / cover.getBoundingClientRect().width),
      firstCoverBackground: getComputedStyle(covers[0]).backgroundColor,
      firstCoverHasVisibleShadow: firstCoverShadow !== 'none'
        && firstCoverShadow
          .split(/,\s*(?=rgba)/)
          .some((shadow) => !shadow.startsWith('rgba(0, 0, 0, 0)')),
      rowCount: rows.length,
      columnCount: firstRowGrid ? getComputedStyle(firstRowGrid).gridTemplateColumns.split(' ').filter(Boolean).length : 0,
      firstRowTop: covers[0]?.getBoundingClientRect().top,
      eleventhTop: covers[10]?.getBoundingClientRect().top
    };
  });

  expect(layout.contentWidth).toBeLessThanOrEqual(1280);
  expect(layout.columnCount).toBe(10);
  expect(layout.rowCount).toBe(3);
  expect(Math.min(...layout.coverWidths)).toBeGreaterThan(90);
  expect(Math.max(...layout.coverWidths)).toBeLessThanOrEqual(130);
  expect(layout.coverRatios.every((ratio) => Math.abs(ratio - 1.5) < 0.01)).toBe(true);
  expect(layout.firstCoverBackground).toBe('rgba(0, 0, 0, 0)');
  expect(layout.firstCoverHasVisibleShadow).toBe(true);
  expect(layout.eleventhTop).toBeGreaterThan(layout.firstRowTop ?? 0);
  await expect(grid.getByRole('button', { name: '查看《书架读物 25》' })).toBeVisible();
  await expect(page.getByText('已加载 25 / 25 本')).toBeVisible();
  expect(shelfRequestUrls.some((url) => new URL(url).searchParams.get('page') === '2')).toBe(true);
  await expect(page.getByRole('button', { name: '下一页' })).toHaveCount(0);
});

test('legacy mobile URLs redirect authenticated users to the shared web home', async ({ page }) => {
  await page.goto('/mobile');

  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByRole('heading', { name: '主页' })).toBeVisible();
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
    id: 'mobile-work',
    workId: 'mobile-work',
    editionId: 'mobile-edition',
    title: '用于验证移动端卡片布局的超长读物标题',
    author: '未知作者',
    type: 'ebook',
    format: 'EPUB',
    formatValue: 'EPUB',
    status: '在读',
    statusValue: 'READING',
    progress: 42,
    lastRead: '今天',
    lastReadAt: '2026-07-17T08:30:00.000Z',
    tags: ['移动端'],
    coverUrl: '',
    coverStatus: 'MISSING',
    gradient: 'from-orange-100 to-stone-200',
    seriesName: null,
    seriesIndex: null,
    publishedYear: null,
    desc: '',
    path: '/books/mobile.epub',
    importedAt: '2026-07-17T08:30:00.000Z',
    metadataQuality: 20
  };

  await page.route('**/api/works?**', async (route) => {
    await route.fulfill({ json: { ok: true, data: { books: [mobileBook], total: 1, page: 1, pageSize: 24, totalPages: 1 } } });
  });
  await page.setViewportSize({ width: 390, height: 844 });

  await page.goto('/library');
  await page.getByRole('button', { name: '管理图书', exact: true }).click();
  await expect(page.getByTestId('book-list-mobile-card')).toBeVisible();
  await expect(page.getByTestId('book-list-desktop-table')).toBeHidden();
  await expect(page.getByRole('button', { name: `查看《${mobileBook.title}》`, exact: true })).toHaveCSS('width', '44px');
  await expect(page.getByRole('button', { name: `删除《${mobileBook.title}》`, exact: true })).toHaveCSS('width', '44px');
  await expect(page.getByRole('button', { name: '更多筛选', exact: true })).toHaveCSS('width', '44px');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);

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
            duplicates: []
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
    id: `continuous-work-${index + 1}`,
    title: `连续书架读物 ${index + 1}`,
    author: '测试作者',
    type: 'ebook',
    format: 'EPUB',
    formatValue: 'EPUB',
    status: '未读',
    statusValue: 'UNREAD',
    progress: 0,
    tags: [],
    coverUrl: '',
    gradient: 'from-orange-100 to-stone-200'
  }));

  await page.route('**/api/works?**', async (route) => {
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
  await expect.poll(() => coverRequestUrls.some((url) => url.includes('/continuous-work-1/cover?size=small'))).toBe(true);
  await shelves.locator('[data-book-cover="true"]').last().scrollIntoViewIfNeeded();
  await expect.poll(() => requestedPages.includes('2')).toBe(true);
  await expect(shelves.locator('[data-book-cover="true"]')).toHaveCount(75);
  await expect(page.getByText('已加载 75 / 75 本')).toBeVisible();
});

test('desktop book list opens details from both the cover and title', async ({ page }) => {
  const requestedPageSizes: string[] = [];
  const requestedSorts: Array<{ sort: string; direction: string }> = [];
  const requestedViews: string[] = [];
  const book = {
    id: 'desktop-list-work',
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
    coverUrl: '',
    gradient: 'from-orange-100 to-stone-200'
  };
  await page.route('**/api/works?**', async (route) => {
    const requestUrl = new URL(route.request().url());
    const requestedPageSize = requestUrl.searchParams.get('pageSize') ?? '';
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
          coverUrl: book.coverUrl
        }
      : book;
    requestedPageSizes.push(requestedPageSize);
    requestedSorts.push({ sort: requestedSort, direction: requestedDirection });
    requestedViews.push(requestUrl.searchParams.get('view') ?? '');
    await route.fulfill({ json: { ok: true, data: { books: [responseBook], total: 1, page: 1, pageSize: Number(requestedPageSize), totalPages: 1 } } });
  });
  await page.setViewportSize({ width: 1280, height: 900 });

  await page.goto('/library');
  await expect(page.getByRole('button', { name: '保存筛选' })).toHaveCount(0);
  await expect(page.getByRole('button', { name: '更多筛选' })).toHaveCount(0);
  await page.getByRole('button', { name: '管理图书', exact: true }).click();
  await page.getByRole('button', { name: '更多筛选' }).click();
  await expect(page.getByRole('button', { name: '保存筛选' })).toBeVisible();
  await expect(page.getByRole('button', { name: '网格排序方式' })).toHaveCount(0);
  await expect(page.getByRole('button', { name: '每页数量' })).toContainText('20 本/页');
  await page.getByRole('button', { name: '每页数量' }).click();
  await page.getByRole('option', { name: '100 本/页' }).click();
  await expect.poll(() => requestedPageSizes.at(-1)).toBe('100');
  await expect.poll(() => requestedViews.at(-1)).toBe('management');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
  await expect(page.getByRole('button', { name: '进度排序' })).toHaveCount(0);
  await expect(page.getByRole('columnheader', { name: '标题排序' })).toBeVisible();
  await expect(page.getByRole('columnheader', { name: '作者排序' })).toBeVisible();
  await expect(page.getByRole('columnheader', { name: '出版社排序' })).toBeVisible();
  await expect(page.getByRole('columnheader', { name: '系列排序' })).toBeVisible();
  await page.getByRole('button', { name: '标题排序' }).click();
  await expect.poll(() => requestedSorts.at(-1)).toEqual({ sort: 'title', direction: 'asc' });
  await page.getByRole('button', { name: '标题排序，当前正序' }).click();
  await expect.poll(() => requestedSorts.at(-1)).toEqual({ sort: 'title', direction: 'desc' });
  await expect(page).toHaveURL(/sort=title/);
  await expect(page).toHaveURL(/sortDirection=desc/);
  await page.getByRole('button', { name: '作者排序' }).click();
  await expect.poll(() => requestedSorts.at(-1)).toEqual({ sort: 'author', direction: 'asc' });
  await page.getByRole('button', { name: '出版社排序' }).click();
  await expect.poll(() => requestedSorts.at(-1)).toEqual({ sort: 'publisher', direction: 'asc' });
  await page.getByRole('button', { name: '系列排序' }).click();
  await expect.poll(() => requestedSorts.at(-1)).toEqual({ sort: 'series', direction: 'asc' });
  await page.getByRole('button', { name: '加入时间排序' }).click();
  await expect.poll(() => requestedSorts.at(-1)).toEqual({ sort: 'recent_import', direction: 'desc' });
  await page.getByRole('button', { name: '加入时间排序，当前倒序' }).click();
  await expect.poll(() => requestedSorts.at(-1)).toEqual({ sort: 'recent_import', direction: 'asc' });
  await page.getByRole('button', { name: '查看《桌面列表入口测试》封面' }).click();
  await expect(page).toHaveURL(/\/works\/desktop-list-work$/);

  await page.goto('/library');
  await page.getByRole('button', { name: '查看《桌面列表入口测试》详情' }).click();
  await expect(page).toHaveURL(/\/works\/desktop-list-work$/);
});
