import { readFile } from 'node:fs/promises';
import { expect, test, type Page } from '@playwright/test';
import type { CreateGrantRequest, GrantView, ManagedOperationFields, Scope } from '../generated/automation';

function grant(id: string, changes: Partial<GrantView> = {}): GrantView {
  return { id, name: id, scopes: ['library:read'], libraryScope: 'all', libraryIds: [], tokenAvailable: true, writebackTargets: [], allowCrossLibrary: false, createdAtMs: Date.now(), expiresAtMs: Date.now() + 86400000, revokedAtMs: null, lastUsedAtMs: null, ...changes };
}
async function mockApi(page: Page, { admin = true, locale = 'zh-CN', enabled = true } = {}) {
  await page.context().addCookies([{ name: 'shuku_session', value: 'test-session', domain: '127.0.0.1', path: '/' }]);
  const grants: GrantView[] = [grant('Client A'), grant('Client B'), grant('Legacy', { tokenAvailable: false, libraryScope: 'selected', libraryIds: ['library'] }), grant('Revoked', { revokedAtMs: Date.now(), tokenAvailable: false }), grant('Expired', { expiresAtMs: 1 })];
  const created: CreateGrantRequest[] = [];
  const revealed: string[] = [];
  const scopes: Scope[] = ['library:read', 'shelves:write', 'metadata:write', 'metadata:override', 'files:read', 'files:move', 'metadata:writeback'];
  const operation: ManagedOperationFields = { operation_id: 'job-1', grant_id: 'grant-1', kind: 'file_move', created_at_ms: 1700000000000,
    status: 'RUNNING', cancel_requested: false, total_targets: 1,
    targets: [{ stage: 'PREPARED', relative_path: 'Before/book.epub', destination_relative_path: 'After/book.epub', error_code: null }] };
  await page.route('**/api/**', async (route) => {
    const path = decodeURIComponent(new URL(route.request().url()).pathname);
    const method = route.request().method();
    let data: object = {};
    if (path === '/api/auth/me') data = { user: { id: 'user', name: 'User', email: 'user@example.invalid', role: admin ? 'admin' : 'member', locale }, authorization: { isAdmin: admin, canManageSystem: admin, authzVersion: 1 } };
    if (path === '/api/shelves') data = { shelves: [] };
    if (path === '/api/system-settings') data = { settings: {} };
    if (path === '/api/libraries') data = { libraries: [{ id: 'library', name: 'Test library' }] };
    if (path === '/api/automation/settings') data = { enabled, enabledScopes: scopes, publicBaseUrl: 'http://books.example:8080/books' };
    if (path === '/api/automation/grants' && method === 'POST') {
      const input: CreateGrantRequest = route.request().postDataJSON(); created.push(input);
      const item = grant(input.name, input); grants.unshift(item); data = { grant: item, token: `secret-${item.id}` };
    } else if (path === '/api/automation/grants') data = { grants };
    if (path.endsWith('/reveal')) { const id = path.split('/').at(-2)!; revealed.push(id); data = { token: `secret-${id}` }; }
    if (path.startsWith('/api/automation/grants/') && method === 'DELETE') {
      const item = grants.find((entry) => path.endsWith(entry.id));
      if (item) { item.revokedAtMs = Date.now(); item.tokenAvailable = false; } data = { revoked: true };
    }
    if (path === '/api/automation/operations') data = { operations: admin ? [operation] : [] };
    if (path.endsWith('/cancel')) { operation.cancel_requested = true; data = { operation }; }
    await route.fulfill({ json: { ok: true, data } });
  });
  return { created, revealed };
}
const row = (page: Page, name: string) => page.getByRole('region', { name: '授权列表' }).getByRole('listitem').filter({ has: page.getByRole('heading', { name, exact: true }) });

test('grant list defaults, expandable creation and browser tab history', async ({ page }) => {
  const state = await mockApi(page);
  await page.goto('/settings/automation');
  await expect(page.getByRole('link', { name: '授权服务', exact: true })).toHaveAttribute('aria-current', 'page');
  await expect(page.getByRole('heading', { name: '创建自动化授权' })).toHaveCount(0);
  await page.getByRole('button', { name: '创建授权', exact: true }).click();
  await expect(page.getByRole('radio', { name: '全部书库（动态）', exact: true })).toBeChecked();
  await page.getByLabel('授权名称', { exact: true }).fill('Dynamic');
  await page.getByRole('button', { name: '创建授权', exact: true }).last().click();
  await expect(row(page, 'Dynamic')).toBeVisible();
  expect(state.created[0]).toMatchObject({ libraryScope: 'all', libraryIds: [] });
  await expect(page.getByRole('heading', { name: '创建自动化授权' })).toHaveCount(0);
  await expect(page.locator('pre')).toHaveCount(0);
  await page.getByRole('button', { name: '创建授权', exact: true }).click();
  await page.getByRole('radio', { name: '指定书库', exact: true }).check();
  await page.getByRole('checkbox', { name: 'Test library' }).check();
  await page.getByLabel('授权名称', { exact: true }).fill('Fixed');
  await page.getByRole('button', { name: '创建授权', exact: true }).last().click();
  await expect(row(page, 'Fixed')).toBeVisible();
  expect(state.created[1]).toMatchObject({ libraryScope: 'selected', libraryIds: ['library'] });
  await page.getByRole('link', { name: 'MCP 服务', exact: true }).click();
  await expect(page).toHaveURL(/tab=service/);
  await expect(page.getByRole('checkbox', { name: '启用 MCP 服务' })).toBeVisible();
  await expect(page.getByRole('checkbox', { name: /HTTP/ })).toHaveCount(0);
  await page.reload();
  await expect(page.getByRole('button', { name: '保存服务设置' })).toBeVisible();
  await page.goBack();
  await expect(row(page, 'Fixed')).toBeVisible();
  await page.goForward();
  await expect(page.getByRole('button', { name: '保存服务设置' })).toBeVisible();
});

test('row configuration stays bound, survives reload and clears on close or navigation', async ({ page }, testInfo) => {
  const state = await mockApi(page);
  await page.goto('/settings/automation');
  await row(page, 'Client A').getByRole('button', { name: '复制配置', exact: true }).click();
  await expect(row(page, 'Client A').locator('pre')).toContainText('[mcp_servers.ermao-library]');
  await expect(page.locator('pre')).toContainText('secret-Client A');
  await row(page, 'Client B').getByRole('button', { name: '复制配置', exact: true }).click();
  await expect(page.locator('pre')).toContainText('secret-Client B');
  await expect(page.locator('pre')).not.toContainText('secret-Client A');
  await page.getByRole('button', { name: 'AI 客户端', exact: true }).click();
  await page.getByRole('option', { name: 'LM Studio', exact: true }).click();
  await expect(page.locator('pre')).toContainText('"mcpServers"');
  await expect(page.locator('pre')).toContainText('http://books.example:8080/books/api/mcp');
  await page.context().grantPermissions(['clipboard-read', 'clipboard-write']);
  await row(page, 'Client B').getByRole('region', { name: '授权配置' }).getByRole('button', { name: '复制配置', exact: true }).click();
  expect(await page.evaluate(() => navigator.clipboard.readText())).toContain('secret-Client B');
  await page.getByRole('button', { name: 'AI 客户端', exact: true }).click();
  await page.getByRole('option', { name: 'Cursor', exact: true }).click();
  const downloading = page.waitForEvent('download');
  await page.getByRole('button', { name: '下载配置', exact: true }).click();
  const downloaded = await downloading;
  expect(downloaded.suggestedFilename()).toBe('ermao-mcp.json');
  await expect(page.locator('.shuku-toast-region')).toContainText('配置下载已开始');
  const content = await readFile((await downloaded.path())!, 'utf8');
  expect(JSON.parse(content).mcpServers['ermao-library'].headers.Authorization).toBe('Bearer secret-Client B');

  await expect(row(page, 'Legacy')).toContainText('历史令牌无法取回，请重新创建授权');
  for (const name of ['Legacy', 'Revoked', 'Expired']) await expect(row(page, name).getByRole('button', { name: '复制配置', exact: true })).toBeDisabled();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath('grants-inline-config.png'), fullPage: true });
  await page.getByRole('button', { name: '关闭配置' }).click();
  await expect(page.locator('pre')).toHaveCount(0);
  await page.reload();
  await row(page, 'Client A').getByRole('button', { name: '复制配置', exact: true }).click();
  await expect(page.locator('pre')).toContainText('secret-Client A');
  await page.getByRole('link', { name: '操作列表', exact: true }).click();
  await expect(page.locator('pre')).toHaveCount(0);
  await page.goBack();
  await expect(page.locator('pre')).toHaveCount(0);
  expect(state.revealed).toEqual(['Client A', 'Client B', 'Client A']);
  expect(await page.evaluate(() => JSON.stringify({ local: { ...localStorage }, session: { ...sessionStorage } }))).not.toContain('secret-Client');
  await row(page, 'Client A').getByRole('button', { name: '撤销授权' }).click();
  await expect(row(page, 'Client A').getByRole('button', { name: '复制配置', exact: true })).toBeDisabled();
});

test('service disabled links admins to service and still permits saved configuration', async ({ page }) => {
  await mockApi(page, { enabled: false });
  await page.goto('/settings/automation');
  await row(page, 'Client A').getByRole('button', { name: '复制配置', exact: true }).click();
  await expect(page.locator('pre')).toContainText('secret-Client A');
  await page.getByRole('button', { name: '请先开启 MCP 服务' }).click();
  await expect(page).toHaveURL(/tab=service/);
  await expect(page.getByRole('checkbox', { name: '启用 MCP 服务' })).not.toBeChecked();
});

test('job cancellation preserves per-file results and responsive layout', async ({ page }) => {
  await mockApi(page);
  await page.goto('/settings/automation?tab=operations');
  await page.getByText('查看逐项结果（最多 50 项）', { exact: true }).click();
  await expect(page.getByText('Before/book.epub → After/book.epub')).toBeVisible();
  await page.getByRole('button', { name: '取消任务', exact: true }).click();
  await expect(page.getByRole('button', { name: '已请求取消' })).toBeDisabled();
  await page.getByRole('button', { name: '刷新任务' }).click();
  await expect(page.getByRole('button', { name: '已请求取消' })).toBeDisabled();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});

test('ordinary account has English labels and bounded creation choices', async ({ page }) => {
  await mockApi(page, { admin: false, locale: 'en-US' });
  await page.goto('/settings/automation');
  await page.getByRole('button', { name: 'Create access', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Create automation access' })).toBeVisible();
  await expect(page.getByRole('checkbox', { name: 'Browse libraries', exact: true })).toBeVisible();
  await expect(page.getByRole('checkbox', { name: 'Move and organize files', exact: true })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Save service settings' })).toHaveCount(0);
});

test('ordinary account must ask an administrator to enable service', async ({ page }) => {
  await mockApi(page, { admin: false, enabled: false });
  await page.goto('/settings/automation');
  await expect(page.getByRole('button', { name: '请先开启 MCP 服务' })).toBeDisabled();
  await expect(page.getByText('请联系管理员开启 MCP 服务后创建授权。')).toBeVisible();
});

test('late token response cannot replace another grant configuration', async ({ page }) => {
  await mockApi(page);
  let release: () => void = () => {};
  const pending = new Promise<void>((resolve) => { release = resolve; });
  await page.route('**/api/automation/grants/Client%20A/reveal', async (route) => {
    await pending;
    await route.fulfill({ json: { ok: true, data: { token: 'late-secret-A' } } }).catch(() => {});
  });
  await page.goto('/settings/automation');
  const requested = page.waitForRequest('**/api/automation/grants/Client%20A/reveal');
  await row(page, 'Client A').getByRole('button', { name: '复制配置', exact: true }).click();
  await requested;
  await row(page, 'Client B').getByRole('button', { name: '复制配置', exact: true }).click();
  await expect(page.locator('pre')).toContainText('secret-Client B');
  release();
  await expect(page.locator('pre')).not.toContainText('late-secret-A');
  await expect(row(page, 'Client A').locator('pre')).toHaveCount(0);
});


test('automation actions report success and failure through shared feedback', async ({ page }) => {
  await mockApi(page);
  const feedback = page.locator('.shuku-toast-region');
  await page.goto('/settings/automation?tab=service');
  await page.getByRole('button', { name: '保存服务设置', exact: true }).click();
  await expect(feedback).toContainText('MCP 服务设置已保存');
  await page.getByRole('link', { name: '授权服务', exact: true }).click();
  await page.getByRole('button', { name: '创建授权', exact: true }).click();
  await page.getByLabel('授权名称', { exact: true }).fill('Feedback client');
  await page.getByRole('button', { name: '创建授权', exact: true }).last().click();
  await expect(feedback).toContainText('授权已创建');
  await row(page, 'Feedback client').getByRole('button', { name: '撤销授权' }).click();
  await expect(feedback).toContainText('授权已撤销');
  await page.getByRole('link', { name: '操作列表', exact: true }).click();
  await page.getByRole('button', { name: '刷新任务', exact: true }).click();
  await expect(feedback).toContainText('任务列表已刷新');
  await page.getByRole('button', { name: '取消任务', exact: true }).click();
  await expect(feedback).toContainText('已请求取消任务');
  while (await feedback.getByRole('button').count()) await feedback.getByRole('button').first().click();
  await page.route('**/api/automation/settings', async (route) => {
    if (route.request().method() !== 'PUT') return route.fallback();
    await route.fulfill({ status: 400, json: { ok: false, error: { code: 'INVALID_PUBLIC_URL' } } });
  });
  await page.getByRole('link', { name: 'MCP 服务', exact: true }).click();
  await page.getByRole('button', { name: '保存服务设置', exact: true }).click();
  await expect(feedback).toContainText('保存服务设置失败');
  await expect(feedback).not.toContainText('MCP 服务设置已保存');
  await page.getByRole('button', { name: '重新读取', exact: true }).click();
  await expect(feedback).toContainText('自动化配置已重新读取');
  await page.route('**/api/automation/grants/*/reveal', async (route) => {
    await route.fulfill({ status: 400, json: { ok: false, error: { code: 'TOKEN_KEY_UNAVAILABLE' } } });
  });
  await page.getByRole('link', { name: '授权服务', exact: true }).click();
  await row(page, 'Client A').getByRole('button', { name: '复制配置', exact: true }).click();
  await expect(feedback).toContainText('配置读取失败');
  await expect(page.getByRole('region', { name: '授权配置' })).toContainText('令牌密钥不可用或解密失败');
});

test('service save feedback uses the current English locale', async ({ page }) => {
  await mockApi(page, { locale: 'en-US' });
  await page.goto('/settings/automation?tab=service');
  await page.getByRole('button', { name: 'Save service settings', exact: true }).click();
  await expect(page.locator('.shuku-toast-region')).toContainText('MCP service settings saved');
});
