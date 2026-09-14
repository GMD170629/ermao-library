import { expect, test, type Page, type Route } from '@playwright/test';

type RequestCounts = Record<string, number>;

const organizeJobs = {
  jobs: [],
  books: [],
  page: 1,
  pageSize: 20,
  total: 0,
  totalPages: 1,
  statusCounts: { SUCCESS: 0, FAILED: 0, RECOGNIZING: 0, WAITING: 0 },
  providerNames: {}
};

async function mockSettingsApi(page: Page, locale: 'zh-CN' | 'en-US' = 'zh-CN') {
  const counts: RequestCounts = {};
  await page.route('**/api/**', async (route) => {
    const url = new URL(route.request().url());
    const pathname = url.pathname;
    counts[pathname] = (counts[pathname] ?? 0) + 1;
    const methodPath = `${route.request().method()} ${pathname}`;
    counts[methodPath] = (counts[methodPath] ?? 0) + 1;

    if (pathname.endsWith('/api/auth/me')) {
      await route.fulfill({
        json: {
          ok: true,
          data: {
            user: { id: 'settings-user', email: 'settings@example.com', name: 'Settings user', role: 'admin', locale },
            authorization: { isAdmin: true, canManageSystem: true, authzVersion: 1 }
          }
        }
      });
      return;
    }
    if (pathname.endsWith('/api/shelves')) {
      await route.fulfill({ json: { ok: true, data: { shelves: [] } } });
      return;
    }
    if (pathname.endsWith('/api/organize/jobs')) {
      await route.fulfill({ json: { ok: true, data: organizeJobs } });
      return;
    }
    if (pathname.endsWith('/api/metadata/providers')) {
      await route.fulfill({ json: { ok: true, data: { providers: [], pipelines: [] } } });
      return;
    }
    if (pathname.endsWith('/api/library/facets')) {
      await route.fulfill({ json: { ok: true, data: { facets: [], page: 1, pageSize: 20, total: 0, totalPages: 1 } } });
      return;
    }
    if (pathname.endsWith('/api/organize/policy')) {
      await route.fulfill({
        json: {
          ok: true,
          data: {
            policy: {
              id: 'default', enabled: false, scheduleMode: 'MANUAL', intervalMinutes: 60, autoRunOnNew: false,
              autoRunOnNewSince: null, rules: { unrecognized: true, missingMetadata: true }, writeMetadataToFiles: false,
              preferLocalMetadata: true, localMetadataPriority: ['SIDECAR_OPF', 'EMBEDDED', 'PATH'],
              lastScheduledAt: null, nextRunAt: null, updatedAt: null
            }
          }
        }
      });
      return;
    }
    if (pathname.endsWith('/api/organize/candidates')) {
      await route.fulfill({ json: { ok: true, data: { candidates: { total: 0 } } } });
      return;
    }
    if (pathname.endsWith('/api/kindle-settings')) {
      await route.fulfill({ json: { ok: true, data: { kindle: { email: '' }, smtp: { configured: false, fromEmail: '' } } } });
      return;
    }
    if (pathname.endsWith('/api/email-settings')) {
      await route.fulfill({
        json: {
          ok: true,
          data: {
            smtp: { host: '', port: 587, security: 'starttls', username: '', fromEmail: '', fromName: '', maxAttachmentMb: null, passwordConfigured: false },
            kindle: { email: '' }
          }
        }
      });
      return;
    }
    if (pathname.endsWith('/api/kindle-send-tasks')) {
      await route.fulfill({ json: { ok: true, data: { tasks: [], total: 0 } } });
      return;
    }
    if (pathname.endsWith('/api/library-import-tasks')) {
      await route.fulfill({ json: { ok: true, data: { tasks: [], completed: 0, failed: 0, page: 1, pageSize: 10, total: 0, totalPages: 1 } } });
      return;
    }
    if (pathname.endsWith('/api/libraries/tree')) {
      const requestedPath = url.searchParams.get('path');
      await route.fulfill({ json: { ok: true, data: { node: requestedPath === '/library' ? { name: 'library', path: '/library', readable: true, children: [] } : { name: '/', path: '/', readable: true, children: [{ name: 'library', path: '/library', readable: true }] } } } });
      return;
    }
    if (pathname.endsWith('/api/libraries')) {
      await route.fulfill({ json: { ok: true, data: { libraries: [{ id: 'library-1', name: '主书库', rootPath: '/library', enabled: true }] } } });
      return;
    }
    if (pathname.endsWith('/api/system-settings')) {
      await route.fulfill({ json: { ok: true, data: { settings: {} } } });
      return;
    }
    await route.fulfill({ json: { ok: true, data: {} } });
  });
  return counts;
}

function requestCount(counts: RequestCounts, pathname: string) {
  return counts[pathname] ?? 0;
}

test('recognition settings save only writable policy fields and retain saved values', async ({ page }) => {
  let writablePolicy = {
    enabled: false, scheduleMode: 'MANUAL', intervalMinutes: 60, autoRunOnNew: false,
    rules: { unrecognized: true, missingMetadata: true }, writeMetadataToFiles: false,
    preferLocalMetadata: true, localMetadataPriority: ['SIDECAR_OPF', 'EMBEDDED', 'PATH']
  };
  const submitted: unknown[] = [];
  await page.route('**/api/organize/policy', async (route) => {
    if (route.request().method() === 'PUT') {
      submitted.push(route.request().postDataJSON());
      writablePolicy = {
        enabled: true, scheduleMode: 'INTERVAL', intervalMinutes: 1440, autoRunOnNew: true,
        rules: { unrecognized: false, missingMetadata: true }, writeMetadataToFiles: true,
        preferLocalMetadata: false, localMetadataPriority: ['EMBEDDED', 'SIDECAR_OPF', 'PATH']
      };
    }
    await route.fulfill({ json: { ok: true, data: { policy: {
      ...writablePolicy, id: 'default', autoRunOnNewSince: '2026-09-10T00:00:00Z',
      lastScheduledAt: '2026-09-10T00:00:00Z', nextRunAt: '2026-09-11T00:00:00Z',
      updatedAt: '2026-09-10T00:00:00Z'
    } } } });
  });
  await page.goto('/settings/organize?tab=recognition');
  await page.getByRole('switch', { name: '定时执行识别', exact: true }).click();
  await page.getByRole('button', { name: '识别任务执行间隔', exact: true }).click();
  await page.getByRole('option', { name: '每天', exact: true }).click();
  await page.getByRole('switch', { name: '新增后自动执行', exact: true }).click();
  await page.getByRole('switch', { name: '元数据变化自动保存到旁车 OPF', exact: true }).click();
  await page.getByRole('switch', { name: '本地元数据优先', exact: true }).click();
  await page.getByRole('checkbox', { name: '尚未识别的读物', exact: true }).uncheck();
  await page.getByRole('button', { name: '下移OPF 文件', exact: true }).click();
  await page.getByRole('button', { name: '保存设置', exact: true }).click();
  await expect.poll(() => submitted.length).toBe(1);
  expect(submitted[0]).toEqual(writablePolicy);
  await expect(page.getByText('识别设置已保存', { exact: true })).toBeVisible();

  await page.reload();
  await expect(page.getByRole('switch', { name: '定时执行识别', exact: true })).toBeEnabled();
  await expect(page.getByRole('switch', { name: '定时执行识别', exact: true })).toBeChecked();
  await expect(page.getByRole('button', { name: '识别任务执行间隔', exact: true })).toContainText('每天');
  await expect(page.getByRole('checkbox', { name: '尚未识别的读物', exact: true })).not.toBeChecked();
  await page.getByRole('button', { name: '保存设置', exact: true }).click();
  await expect.poll(() => submitted.length).toBe(2);
  expect(submitted[1]).toEqual(writablePolicy);
});

test.beforeEach(async ({ context, page }) => {
  await context.addCookies([{ name: 'shuku_session', value: 'settings-session', domain: '127.0.0.1', path: '/' }]);
  await context.addInitScript(() => localStorage.setItem('shuku:pwa:install-dismissed:settings-user', '1'));
  await mockSettingsApi(page);
});

test('settings tab starts its selected animation before the route is confirmed', async ({ page }) => {
  await page.goto('/settings/organize?tab=queue');
  const providersTab = page.locator('a[href="/settings/organize?tab=providers"]');
  await expect(providersTab).toHaveCount(1);

  await page.route(/\/settings\/organize(?:\?.*)?$/, async (route) => {
    if (new URL(route.request().url()).searchParams.get('tab') === 'providers') {
      await new Promise((resolve) => setTimeout(resolve, 500));
    }
    await route.continue();
  });

  await providersTab.click({ noWaitAfter: true });
  await expect(providersTab).toHaveAttribute('data-pending-navigation', 'true');
  await expect(providersTab).not.toHaveAttribute('aria-current', 'page');
  await expect(page).toHaveURL(/tab=providers/);
  await expect(providersTab).toHaveAttribute('aria-current', 'page');
});

test('settings navigation keeps session and shelves stable while tabs load on demand', async ({ page }) => {
  const counts = await mockSettingsApi(page);
  await page.goto('/settings/organize?tab=queue');
  await expect.poll(() => requestCount(counts, '/api/organize/jobs')).toBeGreaterThan(0);
  await expect.poll(() => requestCount(counts, '/api/auth/me')).toBeGreaterThan(0);
  await expect.poll(() => requestCount(counts, '/api/shelves')).toBeGreaterThan(0);
  await page.waitForTimeout(750);
  const initialJobsRequests = requestCount(counts, '/api/organize/jobs');
  const initialAuthRequests = requestCount(counts, '/api/auth/me');
  const initialShelfRequests = requestCount(counts, '/api/shelves');
  expect(requestCount(counts, '/api/metadata/providers')).toBe(0);
  expect(requestCount(counts, '/api/library/facets')).toBe(0);
  expect(requestCount(counts, '/api/organize/policy')).toBe(0);
  expect(requestCount(counts, '/api/organize/candidates')).toBe(0);

  await page.locator('a[href="/settings/organize?tab=providers"]').click();
  await expect.poll(() => requestCount(counts, '/api/metadata/providers')).toBeGreaterThan(0);
  await page.locator('a[href="/settings/organize?tab=categories"]').click();
  await expect.poll(() => requestCount(counts, '/api/library/facets')).toBeGreaterThan(0);
  await page.locator('a[href="/settings/organize?tab=recognition"]').click();
  await expect.poll(() => requestCount(counts, '/api/organize/policy')).toBeGreaterThan(0);
  await expect.poll(() => requestCount(counts, '/api/organize/candidates')).toBeGreaterThan(0);
  await page.locator('a[href="/settings/organize?tab=queue"]').click();
  await expect.poll(() => requestCount(counts, '/api/organize/jobs')).toBeGreaterThan(initialJobsRequests);

  await page
    .getByRole('navigation', { name: '设置分类' })
    .getByRole('link', { name: '邮件与 Kindle' })
    .click();
  await expect.poll(() => requestCount(counts, '/api/kindle-settings')).toBeGreaterThan(0);
  expect(requestCount(counts, '/api/email-settings')).toBe(0);
  expect(requestCount(counts, '/api/kindle-send-tasks')).toBe(0);

  await page.locator('a[href="/settings/email?tab=smtp"]').click();
  await expect.poll(() => requestCount(counts, '/api/email-settings')).toBeGreaterThan(0);
  await page.locator('a[href="/settings/email?tab=queue"]').click();
  await expect.poll(() => requestCount(counts, '/api/kindle-send-tasks')).toBeGreaterThan(0);

  expect(requestCount(counts, '/api/auth/me')).toBe(initialAuthRequests);
  expect(requestCount(counts, '/api/shelves')).toBe(initialShelfRequests);

  await page.evaluate(() => {
    window.dispatchEvent(new CustomEvent('shuku:account-changed', {
      detail: { id: 'settings-user', email: 'updated@example.com', name: 'Updated settings user' }
    }));
    window.dispatchEvent(new CustomEvent('shuku:shelves-changed'));
  });
  const mobileNavigationTrigger = page.getByRole('button', { name: '打开导航菜单' });
  if (await mobileNavigationTrigger.isVisible()) {
    await mobileNavigationTrigger.click();
    await expect(
      page.getByTestId('mobile-navigation').getByText('Updated settings user', { exact: true })
    ).toBeVisible();
  } else {
    await expect(
      page.locator('aside').first().getByText('Updated settings user', { exact: true })
    ).toBeVisible();
  }
  await expect.poll(() => requestCount(counts, '/api/shelves')).toBe(initialShelfRequests + 1);
  expect(requestCount(counts, '/api/auth/me')).toBe(initialAuthRequests);
});

test('library import sections fetch only when their tab mounts and refresh after remount', async ({ page }) => {
  const counts = await mockSettingsApi(page);
  await page.goto('/settings/library');
  await expect.poll(() => requestCount(counts, '/api/library-import-tasks')).toBeGreaterThan(0);
  const initialImportTaskRequests = requestCount(counts, '/api/library-import-tasks');
  expect(requestCount(counts, '/api/libraries/tree')).toBe(0);
  expect(requestCount(counts, '/api/libraries')).toBeGreaterThan(0);
  expect(requestCount(counts, '/api/system-settings')).toBe(0);

  await expect(page.getByRole('tab', { name: '文件管理' })).toHaveCount(0);
  await expect(page.getByRole('tab')).toHaveCount(4);
  await page.getByRole('tab', { name: '书库' }).click();
  await expect.poll(() => requestCount(counts, '/api/libraries')).toBeGreaterThan(0);
  await page.getByRole('tab', { name: '偏好设置' }).click();
  await expect.poll(() => requestCount(counts, '/api/system-settings')).toBeGreaterThan(0);
  await page.getByRole('tab', { name: '导入记录' }).click();
  await expect.poll(() => requestCount(counts, '/api/library-import-tasks')).toBeGreaterThan(initialImportTaskRequests);
  expect(requestCount(counts, '/api/libraries/tree')).toBe(0);
});

test('new library shows expanded scan rules with a 10 KB minimum by default', async ({ page }) => {
  await page.goto('/settings/library');
  await page.getByRole('tab', { name: '书库' }).click();
  await page.getByRole('button', { name: '新增书库' }).click();

  const folderPath = page.getByRole('combobox', { name: '书库路径' });
  await folderPath.fill('/library');
  const directoryTree = page.getByRole('tree');
  await expect(directoryTree.getByRole('button', { name: '/', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'library', exact: true }).click();
  await expect(folderPath).toHaveValue('/library');

  const scanRules = page.getByRole('button', { name: /扫描规则/ });
  await expect(scanRules).toHaveAttribute('aria-expanded', 'true');
  await expect(page.getByRole('spinbutton', { name: '最小文件大小 KB' })).toHaveValue('10');

  const form = page.locator('form').filter({ has: folderPath });
  for (const width of [1920, 1440, 834, 390]) {
    await page.setViewportSize({ width, height: 1100 });
    const formBounds = await form.boundingBox();
    const tabBounds = await page.getByRole('tablist').boundingBox();
    expect(formBounds).not.toBeNull();
    expect(tabBounds).not.toBeNull();
    expect(formBounds?.x).toBe(tabBounds?.x);
    expect(formBounds?.width).toBe(tabBounds?.width);
    const controls = [
      form.getByRole('textbox', { name: '名称', exact: true }),
      form.getByRole('button', { name: '组织方式' }),
      folderPath.locator('..'),
      form.getByRole('spinbutton').locator('..'),
      form.getByRole('checkbox').locator('..'),
      form.getByRole('button', { name: '保存', exact: true })
    ];
    for (const control of controls) {
      const bounds = await control.boundingBox();
      expect(bounds).not.toBeNull();
      expect(bounds?.height).toBe(44);
      expect(bounds?.x).toBeGreaterThanOrEqual(0);
      expect((bounds?.x ?? 0) + (bounds?.width ?? 0)).toBeLessThanOrEqual(width);
    }
    await expect(controls[5]).toHaveCSS('width', '120px');
    await page.screenshot({ path: test.info().outputPath(`library-form-${width}.png`), fullPage: true });
  }
  await scanRules.click();
  await expect(scanRules).toHaveAttribute('aria-expanded', 'false');
  await expect(form.getByRole('button', { name: '保存', exact: true })).toBeVisible();
});

test('new library form labels and compact save fit in English on a narrow screen', async ({ page }) => {
  await mockSettingsApi(page, 'en-US');
  await page.setViewportSize({ width: 390, height: 1100 });
  await page.goto('/settings/library');
  await page.getByRole('tab', { name: 'Library', exact: true }).click();
  await page.getByRole('button', { name: 'Add library', exact: true }).click();
  const form = page.locator('form');
  await expect(form.getByText('Minimum file size', { exact: true })).toBeVisible();
  await expect(form.getByText('Filter options', { exact: true })).toBeVisible();
  await expect(form.getByRole('button', { name: 'Close Add Form' })).toHaveText('Collapse');
  await expect(form.getByRole('button', { name: 'Save', exact: true })).toHaveCSS('width', '120px');
  await expect(form.getByRole('checkbox', { name: 'Ignore hidden files', exact: true }).locator('..')).toHaveCSS('height', '44px');
});

for (const locale of ['zh-CN', 'en-US'] as const) {
  test(`library editor reuses create layout and saves existing values (${locale})`, async ({ page }) => {
    await mockSettingsApi(page, locale);
    const chinese = locale === 'zh-CN';
    const library = { id: 'library-1', name: 'Existing library', rootPath: '/library', enabled: true,
      organizationMode: 'FLAT', ignorePatterns: '*.tmp', ignoreHidden: true, minFileSizeBytes: 20480 };
    await page.route('**/api/libraries', (route) => route.fulfill({ json: { ok: true, data: { libraries: [library] } } }));
    const submitted: unknown[] = [];
    await page.route('**/api/libraries/library-1', async (route) => {
      submitted.push(route.request().postDataJSON());
      await route.fulfill({ json: { ok: true, data: {} } });
    });
    await page.goto('/settings/library');
    await page.getByRole('tab', { name: chinese ? '书库' : 'Library', exact: true }).click();
    await page.getByRole('button', { name: chinese ? '新增书库' : 'Add library', exact: true }).click();
    await page.getByRole('button', { name: chinese ? '设置' : 'Settings', exact: true }).click();
    const forms = page.locator('form').filter({ has: page.getByRole('combobox') });
    await expect(forms).toHaveCount(2);
    const create = forms.nth(0);
    const edit = forms.nth(1);
    const name = edit.getByRole('textbox', { name: chinese ? '名称' : 'Name', exact: true });
    await expect(name).toHaveValue('Existing library');
    await expect(edit.getByRole('combobox')).toHaveValue('/library');
    await expect(edit.getByRole('spinbutton')).toHaveValue('20');
    await expect(edit.locator('textarea')).toHaveValue('*.tmp');
    await expect(edit.getByRole('checkbox', { name: chinese ? '忽略隐藏文件' : 'Ignore hidden files', exact: true })).toBeChecked();
    const cleanup = edit.getByRole('checkbox', { name: chinese ? '允许扫描清空书库' : 'Allow scans to empty this library', exact: false });
    await expect(cleanup).not.toBeChecked();
    await cleanup.check();
    for (const width of [1440, 390]) {
      await page.setViewportSize({ width, height: 1100 });
      for (const selector of ['input[type="number"]', 'textarea']) {
        await expect(edit.locator(selector)).toHaveCSS('height', await create.locator(selector).evaluate((node) => getComputedStyle(node).height));
      }
      await expect(edit.getByRole('button', { name: chinese ? '保存' : 'Save', exact: true })).toHaveCSS('width', '120px');
      await page.screenshot({ path: test.info().outputPath(`library-editor-${width}.png`), fullPage: true });
    }
    await name.fill('Renamed library');
    await edit.getByRole('button', { name: chinese ? '保存' : 'Save', exact: true }).click();
    await expect.poll(() => submitted.length).toBe(1);
    expect(submitted[0]).toEqual({ name: 'Renamed library', rootPath: '/library', organizationMode: 'FLAT',
      ignorePatterns: '*.tmp', ignoreHidden: true, allowEmptyLibraryCleanup: true, minFileSizeBytes: 20480 });
  });
}

for (const locale of ['zh-CN', 'en-US'] as const) {
  test(`library scan queues once and reports acceptance ${locale}`, async ({ page }) => {
    await mockSettingsApi(page, locale);
    const chinese = locale === 'zh-CN';
    await page.route('**/api/libraries', (route) => route.fulfill({ json: { ok: true, data: { libraries: [
      { id: 'library-1', name: 'Scan target', rootPath: '/library', enabled: true, organizationMode: 'FLAT', ignoreHidden: true, allowEmptyLibraryCleanup: false },
      { id: 'disabled', name: 'Disabled library', rootPath: '/disabled', enabled: false, organizationMode: 'FLAT', ignoreHidden: true }
    ] } } }));
    const requests: Route[] = [];
    await page.route('**/api/libraries/library-1/scan', (route) => { requests.push(route); });
    await page.goto('/settings/library');
    await page.getByRole('tab', { name: chinese ? '书库' : 'Library', exact: true }).click();
    const buttons = page.getByRole('button', { name: chinese ? '扫描' : 'Scan', exact: true });
    await expect(buttons).toHaveCount(2);
    await expect(buttons.nth(1)).toBeDisabled();
    await buttons.first().click();
    await expect.poll(() => requests.length).toBe(1);
    await expect(buttons.first()).toBeDisabled();
    expect(requests[0].request().method()).toBe('POST');
    await requests[0].fulfill({ status: 202, json: { ok: true, data: { taskId: 'scan-1', libraryId: 'library-1', sourceNodeId: null, requeuedFailed: 0, enqueued: true } } });
    await expect(page.getByText(chinese ? '已加入扫描队列' : 'Scan queued', { exact: true })).toBeVisible();
    await expect(buttons.first()).toBeEnabled();
    await page.screenshot({ path: test.info().outputPath('library-scan.png'), fullPage: true });
    await buttons.first().click();
    await expect.poll(() => requests.length).toBe(2);
    await requests[1].fulfill({ status: 503, json: { ok: false, error: { message: 'Unavailable' } } });
    await expect(page.getByText(chinese ? '扫描入队失败' : 'Could not queue the scan', { exact: true })).toBeVisible();
    await expect(buttons.first()).toBeEnabled();
  });
}

test('provider configuration matches recognition order width', async ({ page }) => {
  await page.route('**/api/metadata/providers', (route) => route.fulfill({ json: { ok: true, data: { providers: [{
    id: 'douban', sourceId: null, name: '豆瓣图书', version: 'builtin', description: '通过豆瓣读书网页获取图书信息。',
    mode: 'builtin', configFields: [], automaticRateLimit: null, config: {}, configuredSecrets: {},
    enabled: true, priority: 1, lastTestAt: null, lastTestStatus: null, lastError: null
  }] } } }));
  await page.goto('/settings/organize?tab=providers');
  const order = page.getByRole('region', { name: '识别数据源', exact: true }).locator('article');
  const configuration = page.getByRole('region', { name: '数据源配置', exact: true });
  await expect(order).toBeVisible();
  for (const width of [1440, 834, 390]) {
    await page.setViewportSize({ width, height: 1100 });
    const orderBounds = await order.boundingBox();
    const configBounds = await configuration.boundingBox();
    expect(orderBounds).not.toBeNull();
    expect(configBounds).not.toBeNull();
    expect(configBounds?.x).toBe(orderBounds?.x);
    expect(configBounds?.width).toBe(orderBounds?.width);
    await expect(configuration.getByRole('button', { name: '配置', exact: true })).toBeVisible();
    await page.screenshot({ path: test.info().outputPath(`provider-width-${width}.png`), fullPage: true });
  }
});

test('automatic scan switch keeps its thumb inside the track in both states', async ({ page }) => {
  await page.route('**/api/system-settings/library-scan', (route) => route.fulfill({
    json: { ok: true, data: { watchEnabled: true, intervalMinutes: 30 } }
  }));
  await page.goto('/settings/library');
  await page.getByRole('tab', { name: '自动扫描' }).click();
  const toggle = page.getByRole('switch', { name: '实时监听', exact: true });
  const thumb = toggle.locator('[aria-hidden="true"]');
  await expect(toggle).toBeEnabled();
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 1100 });
    const intervalSection = page.getByRole('region', { name: '周期扫描间隔', exact: true });
    const description = intervalSection.locator('p').first();
    const frequency = page.getByRole('button', { name: '扫描频率', exact: true });
    const descriptionBounds = await description.boundingBox();
    const frequencyBounds = await frequency.boundingBox();
    expect(descriptionBounds).not.toBeNull();
    expect(frequencyBounds).not.toBeNull();
    if (width >= 768) {
      expect(frequencyBounds?.x).toBeGreaterThan((descriptionBounds?.x ?? 0) + (descriptionBounds?.width ?? 0));
    } else {
      expect(frequencyBounds?.y).toBeGreaterThan((descriptionBounds?.y ?? 0) + (descriptionBounds?.height ?? 0));
    }
    for (const enabled of [true, false]) {
      await expect(toggle).toHaveAttribute('aria-checked', String(enabled));
      await expect.poll(async () => {
        const trackBounds = await toggle.boundingBox();
        const thumbBounds = await thumb.boundingBox();
        if (!trackBounds || !thumbBounds) return null;
        return {
          left: Math.round(thumbBounds.x - trackBounds.x),
          top: Math.round(thumbBounds.y - trackBounds.y),
          right: Math.round(trackBounds.x + trackBounds.width - thumbBounds.x - thumbBounds.width),
          bottom: Math.round(trackBounds.y + trackBounds.height - thumbBounds.y - thumbBounds.height)
        };
      }).toEqual({ left: enabled ? 24 : 4, top: 4, right: enabled ? 4 : 24, bottom: 4 });
      await toggle.focus();
      await expect(toggle).toBeFocused();
      await page.screenshot({ path: test.info().outputPath(`scan-switch-${width}-${enabled}.png`), fullPage: true });
      await toggle.press('Space');
    }
  }
});

test('library import preferences save after editing ignore patterns', async ({ page }) => {
  const counts = await mockSettingsApi(page);
  await page.goto('/settings/library');
  await page.getByRole('tab', { name: '偏好设置' }).click();
  await expect.poll(() => requestCount(counts, '/api/system-settings')).toBeGreaterThan(0);

  const ignorePatterns = page.locator('textarea');
  await ignorePatterns.fill('*.tmp');
  await expect(page.getByRole('button', { name: '保存偏好' })).toBeEnabled();
  await page.getByRole('button', { name: '保存偏好' }).click();

  await expect.poll(() => requestCount(counts, 'PUT /api/system-settings')).toBe(1);
  await expect(page.getByRole('button', { name: '保存偏好' })).toBeDisabled();

  await ignorePatterns.fill('*.part');
  await page.getByRole('button', { name: '保存偏好' }).click();
  await expect.poll(() => requestCount(counts, 'PUT /api/system-settings')).toBe(2);
  await expect(page.getByRole('button', { name: '保存偏好' })).toBeDisabled();

  await ignorePatterns.fill('*.cache');
  await expect(page.getByRole('button', { name: '保存偏好' })).toBeEnabled();
  await page.getByRole('button', { name: '撤销更改' }).click();
  await expect(ignorePatterns).toHaveValue('*.part');
  await expect(page.getByRole('button', { name: '保存偏好' })).toBeDisabled();
});

test('English settings tabs retain route-backed accessibility state', async ({ context, page }) => {
  await context.clearCookies();
  await context.addCookies([{ name: 'shuku_session', value: 'english-settings-session', domain: '127.0.0.1', path: '/' }]);
  await mockSettingsApi(page, 'en-US');
  await page.goto('/settings/organize?tab=queue');

  const queueTab = page.locator('a[href="/settings/organize?tab=queue"]');
  const providersTab = page.locator('a[href="/settings/organize?tab=providers"]');
  await expect(queueTab).toHaveAttribute('aria-current', 'page');
  await expect(providersTab).not.toHaveAttribute('aria-current', 'page');
  await providersTab.press('Enter');
  await expect(providersTab).toHaveAttribute('aria-current', 'page');
});

for (const locale of ['zh-CN', 'en-US'] as const) {
  test(`import history combines library, keyword and state filters (${locale})`, async ({ page }, testInfo) => {
    await mockSettingsApi(page, locale);
    const requests: URL[] = [];
    await page.route(/\/api\/(library-import-tasks|libraries\/library-1\/import-tasks)\?/, async (route) => {
      const url = new URL(route.request().url());
      requests.push(url);
      const keyword = url.searchParams.get('keyword') ?? '';
      await route.fulfill({ json: { ok: true, data: {
        tasks: [{ id: 'task-1', kind: 'SCAN_LIBRARY', libraryId: 'library-1', libraryName: keyword || '主书库', state: 'QUEUED', createdAt: '2026-09-10T00:00:00Z' }],
        queued: 1, running: 0, completed: 0, failed: 0, page: Number(url.searchParams.get('page')), pageSize: 10, total: 21, totalPages: 3
      } } });
    });
    await page.goto('/settings/library');
    const chinese = locale === 'zh-CN';
    const allLibraries = chinese ? '全部书库' : 'All libraries';
    const refresh = page.getByRole('button', { name: chinese ? '刷新' : 'Refresh', exact: true });
    const search = page.getByRole('searchbox', { name: chinese ? '关键字筛选' : 'Filter by keyword' });
    const library = page.getByRole('button', { name: chinese ? '书库' : 'Library', exact: true });
    await expect(library).toContainText(allLibraries);
    await expect(refresh).toBeEnabled();
    expect(requests[0]?.pathname).toBe('/api/library-import-tasks');
    await expect(search.locator('..').getByRole('button', { name: chinese ? '刷新' : 'Refresh', exact: true })).toBeVisible();
    await page.getByRole('button', { name: chinese ? '下一页' : 'Next Page', exact: true }).click();
    await expect.poll(() => requests.at(-1)?.searchParams.get('page')).toBe('2');
    await search.fill('  Book%_title  ');
    await expect.poll(() => requests.at(-1)?.searchParams.get('keyword')).toBe('Book%_title');
    expect(requests.at(-1)?.searchParams.get('page')).toBe('1');
    await library.click();
    await page.getByRole('option', { name: '主书库', exact: true }).click();
    await expect.poll(() => requests.at(-1)?.pathname).toBe('/api/libraries/library-1/import-tasks');
    const state = page.getByRole('button', { name: chinese ? '按状态筛选' : 'Filter by Status', exact: true });
    await state.click();
    await page.getByRole('option', { name: chinese ? '失败' : 'Failed', exact: true }).click();
    await expect.poll(() => requests.at(-1)?.searchParams.get('state')).toBe('FAILED');
    expect(requests.at(-1)?.searchParams.get('keyword')).toBe('Book%_title');
    await expect(refresh).toBeEnabled();
    const beforeRefresh = requests.length;
    await refresh.click();
    await expect.poll(() => requests.length).toBeGreaterThan(beforeRefresh);
    expect(requests.at(-1)?.searchParams.get('keyword')).toBe('Book%_title');
    await search.fill('');
    await expect.poll(() => requests.at(-1)?.searchParams.has('keyword')).toBe(false);
    await library.click();
    await page.getByRole('option', { name: allLibraries, exact: true }).click();
    await expect.poll(() => requests.at(-1)?.pathname).toBe('/api/library-import-tasks');
    const beforePolling = requests.length;
    await expect.poll(() => requests.length).toBeGreaterThan(beforePolling);
    await search.focus();
    await expect(search).toBeFocused();
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    await page.screenshot({ path: testInfo.outputPath('import-filters.png'), fullPage: true });
  });
}

test('import keyword debounce rejects an older slow response and supports empty libraries', async ({ page }) => {
  await mockSettingsApi(page);
  await page.route('**/api/libraries', async (route) => {
    await route.fulfill({ json: { ok: true, data: { libraries: [] } } });
  });
  const requests: string[] = [];
  const pending: Route[] = [];
  const result = (title: string) => ({ ok: true, data: {
    tasks: title ? [{ id: title, kind: 'SCAN_LIBRARY', libraryId: 'disabled-library', libraryName: title, state: 'SUCCEEDED', createdAt: '2026-09-10T00:00:00Z' }] : [],
    queued: 0, running: 0, completed: 1, failed: 0, page: 1, pageSize: 10, total: title ? 1 : 0, totalPages: 1
  } });
  await page.route('**/api/library-import-tasks?**', async (route) => {
    const keyword = new URL(route.request().url()).searchParams.get('keyword') ?? '';
    requests.push(keyword);
    if (keyword === 'old') {
      pending.push(route);
      return;
    }
    await route.fulfill({ json: result(keyword) });
  });
  await page.goto('/settings/library');
  await expect(page.getByText('暂无导入任务。', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: '书库', exact: true })).toContainText('全部书库');
  const search = page.getByRole('searchbox', { name: '关键字筛选' });
  await page.clock.install({ time: new Date('2026-09-10T00:00:00Z') });
  await page.clock.pauseAt(new Date('2026-09-10T00:00:01Z'));
  await search.fill('o');
  await page.clock.runFor(200);
  await search.fill('old');
  await page.clock.runFor(299);
  expect(requests.filter((keyword) => keyword !== '')).toEqual([]);
  await page.clock.runFor(1);
  await expect.poll(() => pending.length).toBe(1);
  await search.fill('new');
  await page.clock.runFor(300);
  await expect(page.getByText('new', { exact: true })).toBeVisible();
  for (const route of pending) await route.fulfill({ json: result('old') });
  await expect(page.getByText('old', { exact: true })).toHaveCount(0);
  await expect(page.getByText('new', { exact: true })).toBeVisible();
  await search.fill('');
  await page.clock.runFor(1);
  await expect(page.getByText('暂无导入任务。', { exact: true })).toBeVisible();
});
