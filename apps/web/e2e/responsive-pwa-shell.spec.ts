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

test('wide shelf details keep five-column density and paginate large shelves', async ({ page }) => {
  const books = Array.from({ length: 23 }, (_, index) => ({
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

  await page.route('**/api/shelves/wide-shelf', async (route) => {
    await route.fulfill({
      json: {
        ok: true,
        data: {
          shelf: {
            id: 'wide-shelf',
            name: '宽屏书架',
            description: '验证书架详情布局',
            bookCount: books.length,
            bookIds: books.map((book) => book.id),
            books,
            createdAt: '2026-07-17T08:30:00.000Z',
            updatedAt: '2026-07-17T08:30:00.000Z'
          }
        }
      }
    });
  });

  await page.setViewportSize({ width: 2048, height: 1152 });
  await page.goto('/shelves?shelf=wide-shelf');

  const grid = page.getByTestId('shelf-book-grid');
  await expect(grid).toBeVisible();
  const firstCover = grid.locator('[data-book-cover="true"]').first();
  await expect(firstCover.locator('img')).toHaveCSS('object-fit', 'contain');
  const layout = await grid.evaluate((element) => {
    const bounds = element.parentElement?.parentElement?.getBoundingClientRect();
    const covers = Array.from(element.querySelectorAll<HTMLElement>('[data-book-cover="true"]'));
    const styles = getComputedStyle(element);
    return {
      contentWidth: bounds?.width ?? 0,
      coverWidths: covers.map((cover) => cover.getBoundingClientRect().width),
      coverRatios: covers.map((cover) => cover.getBoundingClientRect().height / cover.getBoundingClientRect().width),
      firstCoverBackground: getComputedStyle(covers[0]).backgroundColor,
      firstCoverShadow: getComputedStyle(covers[0]).boxShadow,
      columnCount: styles.gridTemplateColumns.split(' ').filter(Boolean).length,
      overflowX: styles.overflowX,
      firstRowTop: covers[0]?.getBoundingClientRect().top,
      sixthTop: covers[5]?.getBoundingClientRect().top
    };
  });

  expect(layout.contentWidth).toBeLessThanOrEqual(1280);
  expect(layout.columnCount).toBe(5);
  expect(layout.overflowX).toBe('visible');
  expect(Math.min(...layout.coverWidths)).toBeGreaterThan(220);
  expect(Math.max(...layout.coverWidths)).toBeLessThanOrEqual(240);
  expect(layout.coverRatios.every((ratio) => Math.abs(ratio - 1.5) < 0.01)).toBe(true);
  expect(layout.firstCoverBackground).toBe('rgba(0, 0, 0, 0)');
  expect(layout.firstCoverShadow).toBe('none');
  expect(layout.sixthTop).toBeGreaterThan(layout.firstRowTop ?? 0);
  await expect(grid.locator('[data-book-cover="true"]')).toHaveCount(20);
  await expect(page.getByText('第 1–20 本，共 23 本')).toBeVisible();

  await page.getByRole('button', { name: '下一页' }).click();

  await expect(page.getByText('书架读物 21', { exact: true })).toBeVisible();
  await expect(page.getByText('书架读物 1', { exact: true })).toHaveCount(0);
  await expect(grid.locator('[data-book-cover="true"]')).toHaveCount(3);
  await expect(page.getByText('第 21–23 本，共 23 本')).toBeVisible();
  await expect(page.getByRole('button', { name: '下一页' })).toBeDisabled();
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

test('mobile data-heavy views use cards instead of compressed desktop tables', async ({ page }) => {
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
  await page.route('**/api/organize/jobs?**', async (route) => {
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
  await page.route('**/api/management/events?**', async (route) => {
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

  await page.setViewportSize({ width: 390, height: 844 });

  await page.goto('/library');
  await page.getByRole('button', { name: '列表', exact: true }).click();
  await expect(page.getByTestId('book-list-mobile-card')).toBeVisible();
  await expect(page.getByTestId('book-list-desktop-table')).toBeHidden();
  await expect(page.getByRole('button', { name: `查看《${mobileBook.title}》`, exact: true })).toHaveCSS('width', '44px');
  await expect(page.getByRole('button', { name: `删除《${mobileBook.title}》`, exact: true })).toHaveCSS('width', '44px');
  await expect(page.getByRole('button', { name: '更多筛选', exact: true })).toHaveCSS('width', '44px');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);

  await page.goto('/organize');
  await expect(page.getByTestId('organize-job-mobile-card')).toBeVisible();
  await expect(page.getByTestId('organize-job-desktop-table')).toBeHidden();

  await page.goto('/management/logs');
  await expect(page.getByTestId('system-event-mobile-card')).toBeVisible();
  await expect(page.getByTestId('system-event-desktop-table')).toBeHidden();
});

test('desktop book list opens details from both the cover and title', async ({ page }) => {
  const requestedPageSizes: string[] = [];
  const requestedSorts: Array<{ sort: string; direction: string }> = [];
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
    const requestedPageSize = new URL(route.request().url()).searchParams.get('pageSize') ?? '';
    const requestUrl = new URL(route.request().url());
    const requestedSort = requestUrl.searchParams.get('sort') ?? '';
    const requestedDirection = requestUrl.searchParams.get('sortDirection') ?? '';
    requestedPageSizes.push(requestedPageSize);
    requestedSorts.push({ sort: requestedSort, direction: requestedDirection });
    await route.fulfill({ json: { ok: true, data: { books: [book], total: 1, page: 1, pageSize: Number(requestedPageSize), totalPages: 1 } } });
  });
  await page.setViewportSize({ width: 1280, height: 900 });

  await page.goto('/library');
  await expect(page.getByRole('button', { name: '保存筛选' })).toHaveCount(0);
  await page.getByRole('button', { name: '更多筛选' }).click();
  await expect(page.getByRole('button', { name: '保存筛选' })).toBeVisible();
  await expect(page.getByRole('button', { name: '网格排序方式' })).toHaveCount(0);
  await expect(page.getByRole('button', { name: '每页数量' })).toContainText('20 本/页');
  await page.getByRole('button', { name: '每页数量' }).click();
  await page.getByRole('option', { name: '100 本/页' }).click();
  await expect.poll(() => requestedPageSizes.at(-1)).toBe('100');
  await page.getByRole('button', { name: '列表', exact: true }).click();
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
