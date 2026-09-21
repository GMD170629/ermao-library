import { expect, test, type Page } from '@playwright/test';
import type { GrantView, ManagedOperationFields, Scope } from '../generated/automation';

async function mockApi(page: Page, admin = true, locale = 'zh-CN') {
  await page.context().addCookies([{ name: 'shuku_session', value: 'test-session', domain: '127.0.0.1', path: '/' }]);
  const grants: GrantView[] = [];
  const scopes: Scope[] = ['library:read', 'shelves:write', 'metadata:write', 'metadata:override', 'files:read', 'files:move', 'metadata:writeback'];
  const operation: ManagedOperationFields = { operation_id: 'job-1', grant_id: 'grant-1', kind: 'file_move', created_at_ms: 1700000000000,
    status: 'RUNNING', cancel_requested: false, total_targets: 1,
    targets: [{ stage: 'PREPARED', relative_path: 'Before/book.epub', destination_relative_path: 'After/book.epub', error_code: null }] };
  await page.route('**/api/**', async (route) => {
    const path = new URL(route.request().url()).pathname;
    const method = route.request().method();
    let data: object = {};
    if (path === '/api/auth/me') data = { user: { id: 'user', name: 'User', email: 'user@example.invalid', role: admin ? 'admin' : 'member', locale }, authorization: { isAdmin: admin, canManageSystem: admin, authzVersion: 1 } };
    if (path === '/api/shelves') data = { shelves: [] };
    if (path === '/api/system-settings') data = { settings: {} };
    if (path === '/api/libraries') data = { libraries: [{ id: 'library', name: 'Test library' }] };
    if (path === '/api/automation/settings') data = { enabled: true, enabledScopes: scopes, publicBaseUrl: 'https://books.example/books', allowInsecureHttp: false };
    if (path === '/api/automation/grants' && method === 'POST') {
      const grant: GrantView = { id: `grant-${grants.length + 1}`, name: 'Test client', scopes: ['library:read'], libraryIds: ['library'], writebackTargets: [], allowCrossLibrary: false, createdAtMs: Date.now(), expiresAtMs: Date.now() + 86400000, revokedAtMs: null, lastUsedAtMs: null };
      grants.push(grant); data = { grant, token: `test-once-token-${grant.id}` };
    } else if (path === '/api/automation/grants') data = { grants };
    if (path.startsWith('/api/automation/grants/') && method === 'DELETE') {
      const grant = grants.find((entry) => path.endsWith(entry.id));
      if (grant) grant.revokedAtMs = Date.now(); data = { revoked: true };
    }
    if (path === '/api/automation/operations') data = { operations: admin ? [operation] : [] };
    if (path.endsWith('/cancel')) { operation.cancel_requested = true; data = { operation }; }
    await route.fulfill({ json: { ok: true, data } });
  });
}

test('one-time credentials require explicit template inclusion and disappear after refresh', async ({ page }) => {
  await mockApi(page);
  await page.goto('/settings/automation');
  await expect(page.getByRole('heading', { name: '创建自动化授权' })).toBeVisible();
  await page.getByLabel('授权名称', { exact: true }).fill('Test client');
  await page.getByRole('button', { name: '有效期', exact: true }).click();
  await page.getByRole('option', { name: '30 天', exact: true }).click();
  await expect(page.getByRole('button', { name: '有效期', exact: true })).toContainText('30 天');
  await page.getByRole('checkbox', { name: 'Test library' }).check();
  await page.getByRole('button', { name: '创建授权并显示令牌' }).click();
  await expect(page.getByLabel('新建的自动化令牌')).toHaveValue('test-once-token-grant-1');
  await expect(page.locator('pre')).toContainText('<ERMAO_TOKEN>');
  await page.getByRole('checkbox', { name: /在复制和下载的配置中包含本次令牌/ }).check();
  await expect(page.locator('pre')).toContainText('test-once-token-grant-1');
  await page.getByRole('button', { name: '创建授权并显示令牌' }).click();
  await expect(page.getByLabel('新建的自动化令牌')).toHaveValue('test-once-token-grant-2');
  await expect(page.locator('pre')).toContainText('<ERMAO_TOKEN>');
  await page.reload();
  await expect(page.getByRole('heading', { name: '我的授权' })).toBeVisible();
  await expect(page.getByLabel('新建的自动化令牌')).toHaveCount(0);
  expect(await page.evaluate(() => JSON.stringify({ local: { ...localStorage }, session: { ...sessionStorage } }))).not.toContain('test-once-token');
  await page.getByRole('button', { name: '撤销授权' }).first().click();
  await expect(page.getByText('已撤销', { exact: false })).toBeVisible();
});

test('job cancellation preserves per-file results and responsive layout', async ({ page }, testInfo) => {
  await mockApi(page);
  await page.goto('/settings/automation');
  await page.getByText('查看逐项结果（最多 50 项）', { exact: true }).click();
  await expect(page.getByText('Before/book.epub → After/book.epub')).toBeVisible();
  await page.getByRole('button', { name: '取消任务', exact: true }).click();
  await expect(page.getByRole('button', { name: '已请求取消' })).toBeDisabled();
  await page.getByRole('button', { name: '刷新任务' }).click();
  await expect(page.getByRole('button', { name: '已请求取消' })).toBeDisabled();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath('automation-settings.png'), fullPage: true });
});

test('ordinary account sees read and shelf grants, with English labels', async ({ page }) => {
  await mockApi(page, false, 'en-US');
  await page.goto('/settings/automation');
  await expect(page.getByRole('heading', { name: 'Create automation access' })).toBeVisible();
  await expect(page.getByRole('checkbox', { name: 'Browse libraries', exact: true })).toBeVisible();
  await expect(page.getByRole('checkbox', { name: 'Move and organize files', exact: true })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Save service settings' })).toHaveCount(0);
});
