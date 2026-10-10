import { expect, test } from '@playwright/test';
import { readFile } from 'node:fs/promises';
import { Uint8ArrayReader, Uint8ArrayWriter, ZipWriter } from '@zip.js/zip.js';

for (const locale of ['zh-CN', 'en-US'] as const) {
  test(`raw log details, copy, export and filters (${locale})`, async ({ page, context, isMobile }, testInfo) => {
    const en = locale === 'en-US';
    const raw = '未知错误'; // This is also an i18n key; original errors must remain unchanged.
    const stack = `Traceback\n${'  original frame\n'.repeat(2000)}${raw}\ntoken=test-secret /private/book\nEND-OF-STACK`;
    const event = { id: 'log-only-id', source: 'worker', level: 'error', actorType: 'system', action: 'failed',
      message: raw, metadata: { diagnostics: { exceptionType: 'RuntimeError', message: raw, traceback: stack } }, createdAt: '2026-10-10T00:00:00Z' };
    const queries: URLSearchParams[] = [];
    const exportQueries: string[] = [];
    const archive = new ZipWriter(new Uint8ArrayWriter());
    await archive.add('api/2026-10-10.jsonl', new Uint8ArrayReader(Buffer.from(`${JSON.stringify(event)}\n`)));
    const originalArchive = Buffer.from(await archive.close());
    const settingWrites: unknown[] = [];
    let retentionDays = 3;
    let minimumLevel = 'error';
    await context.grantPermissions(['clipboard-read', 'clipboard-write']);
    await context.addCookies([{ name: 'shuku_session', value: 'test-session', domain: '127.0.0.1', path: '/' }]);
    await page.route('**/api/**', async (route) => {
      const url = new URL(route.request().url());
      if (url.pathname === '/api/auth/me') {
        await route.fulfill({ json: { ok: true, data: { user: { id: 'admin', name: 'Admin', email: 'admin@example.test', role: 'admin', locale }, authorization: { isAdmin: true, canManageSystem: true, authzVersion: 1 } } } });
      } else if (url.pathname === '/api/management/events/export') {
        exportQueries.push(url.search);
        await route.fulfill({ contentType: 'application/zip', body: originalArchive });
      } else if (url.pathname === '/api/management/events/log-only-id') {
        await route.fulfill({ json: { ok: true, data: event } });
      } else if (url.pathname === '/api/management/events') {
        queries.push(url.searchParams);
        await route.fulfill({ json: { ok: true, data: { events: [event], total: 1, totalPages: 1, storage: { sizeBytes: stack.length, retentionDays, minimumLevel } } } });
      } else if (url.pathname === '/api/system/log-settings') {
        const body = route.request().postDataJSON();
        settingWrites.push(body);
        retentionDays = body.retentionDays;
        minimumLevel = body.minimumLevel;
        await route.fulfill({ json: { ok: true, data: { storage: { sizeBytes: stack.length, retentionDays, minimumLevel } } } });
      } else {
        await route.fulfill({ json: { ok: true, data: {} } });
      }
    });
    await Promise.all([
      page.waitForResponse((response) => new URL(response.url()).pathname === '/api/auth/me'),
      page.goto('/settings/logs'),
    ]);
    const days = page.getByRole('spinbutton', { name: en ? 'Retention days' : '保留天数' });
    await expect(days).toHaveValue('3');
    const minimum = page.getByRole('button', { name: en ? 'Minimum recording level' : '最低记录级别' });
    await expect(minimum).toHaveText(en ? 'Error' : '错误');
    await expect(page.locator('select')).toHaveCount(0);
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    await page.screenshot({ path: testInfo.outputPath('logs-form.png'), fullPage: true });
    await days.fill('4');
    await minimum.focus();
    await minimum.press('ArrowDown');
    await expect(page.getByRole('listbox')).toBeVisible();
    await minimum.press('ArrowDown');
    await minimum.press('Enter');
    await expect(minimum).toHaveText(en ? 'Debug' : '调试');
    await expect(minimum).toBeFocused();
    await page.getByRole('button', { name: en ? 'Save' : '保存', exact: true }).click();
    await expect.poll(() => settingWrites.at(-1)).toEqual({ retentionDays: 4, minimumLevel: 'debug' });
    await expect(days).toHaveValue('4');
    await page.getByRole('button', { name: en ? 'Level' : '级别', exact: true }).click();
    await page.getByRole('option', { name: en ? 'Error' : '错误', exact: true }).click();
    await expect.poll(() => queries.at(-1)?.get('level')).toBe('error');
    await page.getByRole('button', { name: en ? 'Source' : '来源', exact: true }).click();
    await page.getByRole('option', { name: en ? 'System' : '系统', exact: true }).click();
    await expect.poll(() => queries.at(-1)?.get('source')).toBe('system');
    const logs = page.getByTestId(isMobile ? 'system-event-mobile-card' : 'system-event-desktop-table');
    await expect(logs.getByText(raw, { exact: true })).toBeVisible();
    await logs.getByRole('button', { name: en ? (isMobile ? 'View Details' : 'Expand Log Details') : (isMobile ? '查看详情' : '展开日志详情') }).click();
    await expect(logs.locator('pre')).toHaveText(stack);
    await expect(logs.locator('a')).toHaveCount(0);
    await logs.getByRole('button', { name: en ? 'Copy stack trace' : '复制堆栈' }).click();
    // Windows clipboard uses CRLF; compare all content after its newline conversion.
    await expect.poll(() => page.evaluate(async () => (await navigator.clipboard.readText()).replace(/\r\n/g, '\n'))).toBe(stack);
    await page.getByPlaceholder(en ? 'Search error messages' : '搜索错误信息').fill('test-secret');
    await page.getByRole('button', { name: en ? 'Search' : '搜索', exact: true }).click();
    await expect.poll(() => queries.at(-1)?.get('search')).toBe('test-secret');
    await expect(page.locator('input[type="date"]')).toHaveCount(0);
    expect(queries.every((query) => !query.has('dateFrom') && !query.has('dateTo'))).toBe(true);
    const downloadPromise = page.waitForEvent('download');
    await page.getByRole('button', { name: en ? 'Export' : '导出', exact: true }).click();
    const download = await downloadPromise;
    expect(download.suggestedFilename()).toBe('shuku-system-logs.zip');
    expect(await readFile((await download.path())!)).toEqual(originalArchive);
    expect(exportQueries).toEqual(['']);
  });
}
