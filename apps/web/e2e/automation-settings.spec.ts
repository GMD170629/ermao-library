import { readFile } from 'node:fs/promises';
import { expect, test, type Page } from '@playwright/test';
import type { CreateGrantRequest, UpdateGrantRequest, GrantView, ManagedOperationFields, Scope } from '../generated/automation';

function grant(id: string, changes: Partial<GrantView> = {}): GrantView {
  return { id, name: id, scopes: ['system:read'], libraryScope: 'all', libraryIds: [], tokenAvailable: true, createdAtMs: Date.now(), expiresAtMs: Date.now() + 86400000, revokedAtMs: null, lastUsedAtMs: null, ...changes };
}
async function mockApi(page: Page, { admin = true, locale = 'zh-CN', enabled = true, uploads = false, fileOperations = false } = {}) {
  await page.context().addCookies([{ name: 'shuku_session', value: 'test-session', domain: '127.0.0.1', path: '/' }]);
  const grants: GrantView[] = [grant('Client A'), grant('Client B'), grant('Legacy', { tokenAvailable: false, libraryScope: 'selected', libraryIds: ['library'] }), grant('Revoked', { revokedAtMs: Date.now(), tokenAvailable: false }), grant('Expired', { expiresAtMs: 1 })];
  const created: CreateGrantRequest[] = [];
  const revealed: string[] = [];
  const updated: { id: string; input: UpdateGrantRequest }[] = [];
  const scopes: Scope[] = ['system:read', 'system:manage', 'books:write', 'shelves:write', 'files:upload', 'files:modify'];
  const operation: ManagedOperationFields = { operation_id: 'job-1', grant_id: 'grant-1', kind: 'file_move', created_at_ms: 1700000000000,
    status: 'RUNNING', cancel_requested: false, total_targets: 1,
    targets: [{ stage: 'PREPARED', relative_path: 'Before/book.epub', destination_relative_path: 'After/book.epub', error_code: null }] };
  const uploaded: ManagedOperationFields = { operation_id: 'upload-1', grant_id: 'grant-1', kind: 'book_upload', created_at_ms: 1700000000000, status: 'FAILED', cancel_requested: false, total_targets: 1, received_bytes: 1024, size_bytes: 1024, file_saved: true,
    upload_result: { status: 'FAILED', error_code: 'UPLOAD_IMPORT_FAILED', book_ids: [], resource_ids: [] },
    targets: [{ stage: 'FAILED', relative_path: 'Books/new.epub', destination_relative_path: null, error_code: 'UPLOAD_IMPORT_FAILED' }] };
  const deleting: ManagedOperationFields = { operation_id: 'delete-1', grant_id: 'grant-1', kind: 'file_delete', created_at_ms: 1700000000000,
    status: 'RUNNING', cancel_requested: false, total_targets: 1,
    targets: [{ stage: 'DELETING', relative_path: 'Books/old', destination_relative_path: null, error_code: null }] };
  const recovery: ManagedOperationFields = { operation_id: 'recovery-1', grant_id: 'grant-1', kind: 'file_move', created_at_ms: 1700000000000,
    status: 'RECOVERY_REQUIRED', cancel_requested: false, total_targets: 1,
    targets: [{ stage: 'RECOVERY_REQUIRED', relative_path: 'Before/book.epub', destination_relative_path: 'After/book.epub', error_code: 'FILE_MOVE_INCOMPLETE' }] };
  await page.route('**/api/**' , async (route) => {
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
      const item = grant(input.name, { ...input, expiresAtMs: input.lifetimeDays === null ? null : Date.now() + 86400000 }); grants.unshift(item); data = { grant: item, token: `secret-${item.id}` };
    } else if (path === '/api/automation/grants') data = { grants };
    if (path.endsWith('/reveal')) { const id = path.split('/').at(-2)!; revealed.push(id); data = { token: `secret-${id}` }; }
    if (path.startsWith('/api/automation/grants/') && method === 'PATCH') {
      const item = grants.find((entry) => path.endsWith(entry.id));
      const input: UpdateGrantRequest = route.request().postDataJSON();
      if (item) { updated.push({ id: item.id, input }); Object.assign(item, input); if (input.lifetimeDays === null) item.expiresAtMs = null; data = { grant: item }; }
    }
    if (path.startsWith('/api/automation/grants/') && method === 'DELETE') {
      const item = grants.find((entry) => path.endsWith(entry.id));
      if (item) { item.revokedAtMs = Date.now(); item.tokenAvailable = false; } data = { revoked: true };
    }
    if (path === '/api/automation/operations') data = { operations: admin ? (fileOperations ? [deleting, recovery] : uploads ? [operation, uploaded] : [operation]) : [] };
    if (path.endsWith('/cancel')) { operation.cancel_requested = true; data = { operation }; }
    await route.fulfill({ json: { ok: true, data } });
  });
  return { created, revealed, updated };
}
const row = (page: Page, name: string) => page.getByRole('region', { name: '授权列表' }).getByRole('listitem').filter({ has: page.getByRole('heading', { name, exact: true }) });

test('grant list defaults, expandable creation and browser tab history', async ({ page }, testInfo) => {
  const state = await mockApi(page);
  await page.goto('/settings/automation');
  await expect(page.getByRole('link', { name: '授权服务', exact: true })).toHaveAttribute('aria-current', 'page');
  await expect(page.getByRole('heading', { name: '创建自动化授权' })).toHaveCount(0);
  await page.getByRole('button', { name: '创建授权', exact: true }).click();
  await expect(page.getByRole('radio', { name: '全部书库（动态）', exact: true })).toBeChecked();
  const nameBounds = await page.getByLabel('授权名称', { exact: true }).boundingBox();
  const lifetimeBounds = await page.getByRole('button', { name: '有效期', exact: true }).boundingBox();
  expect(Math.abs(nameBounds!.height - lifetimeBounds!.height)).toBeLessThanOrEqual(1);
  if (testInfo.project.name === 'chrome') expect(Math.abs(nameBounds!.y - lifetimeBounds!.y)).toBeLessThanOrEqual(1);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath('create-grant-aligned.png'), fullPage: true });

  for (const checkbox of await page.locator('form').getByRole('checkbox').all()) await expect(checkbox).toBeChecked();
  await page.getByRole('button', { name: '有效期', exact: true }).click();
  await page.getByRole('option', { name: '长期', exact: true }).click();
  await page.getByLabel('授权名称', { exact: true }).fill('Dynamic');
  await page.getByRole('button', { name: '创建授权', exact: true }).last().click();
  await expect(row(page, 'Dynamic')).toBeVisible();
  expect(state.created[0]).toMatchObject({ libraryScope: 'all', libraryIds: [], lifetimeDays: null });
  expect(state.created[0].scopes).toContain('files:modify');
  await expect(row(page, 'Dynamic')).toContainText('长期');
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
  await expect(page.getByRole('checkbox', { name: 'Basic queries', exact: true })).toBeChecked();
  await expect(page.getByRole('checkbox', { name: 'Manage shelves', exact: true })).toBeChecked();
  await expect(page.getByRole('checkbox', { name: 'Modify book files', exact: true })).toHaveCount(0);
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

for (const locale of ['zh-CN', 'en-US']) {
  test(`file deletion stage and incomplete move guidance (${locale})`, async ({ page }) => {
    await mockApi(page, { locale, fileOperations: true });
    await page.goto('/settings/automation?tab=operations');
    await expect(page.getByText(locale === 'zh-CN'
      ? '显示当前权限内最近 50 项任务。已接收不代表已完成；取消只影响尚未开始的文件操作。'
      : 'Shows the latest 50 operations within your current permissions. Accepted does not mean completed; cancellation only affects file operations that have not started.')).toBeVisible();
    const deletion = page.getByRole('listitem').filter({ hasText: 'delete-1' });
    await deletion.getByText(locale === 'zh-CN' ? '查看逐项结果（最多 50 项）' : 'View individual results (up to 50)').click();
    await expect(deletion).toContainText(locale === 'zh-CN' ? '正在删除文件' : 'Deleting files');
    const recovery = page.getByRole('listitem').filter({ hasText: 'recovery-1' });
    await expect(recovery.getByRole('alert')).toHaveText(locale === 'zh-CN'
      ? '任务未完成，需要核对文件和书库记录。请保留任务标识，不要重复提交相同操作。'
      : 'The operation is incomplete. Review the files and library records, keep the operation ID, and do not submit the same operation again.');
    await expect(recovery.getByRole('button')).toHaveCount(0);
  });
  test(`attachment scopes and saved import failure (${locale})`, async ({ page }) => {
    await mockApi(page, { locale, uploads: true });
    await page.goto('/settings/automation?tab=grants');
    await page.getByRole('button', { name: locale === 'zh-CN' ? '创建授权' : 'Create access', exact: true }).click();
    await expect(page.getByRole('checkbox', { name: locale === 'zh-CN' ? '上传图书' : 'Upload books', exact: true })).toBeChecked();
    await expect(page.getByRole('checkbox', { name: locale === 'zh-CN' ? '更新图书元数据' : 'Update book metadata', exact: true })).toBeChecked();
    await page.goto('/settings/automation?tab=operations');
    const upload = page.getByRole('listitem').filter({ has: page.getByRole('heading', { name: locale === 'zh-CN' ? '上传图书附件 · 失败' : 'Upload book attachments · Failed' }) });
    await expect(upload).toContainText('1,024 / 1,024');
    await expect(upload).toContainText(locale === 'zh-CN' ? '原文件已保存；导入失败也不会删除原文件。' : 'Original file saved; an import failure will not delete it.');
    await expect(upload.getByRole('button')).toHaveCount(0);
    await upload.getByText(locale === 'zh-CN' ? '查看逐项结果（最多 50 项）' : 'View individual results (up to 50)').click();
    await expect(upload).toContainText('UPLOAD_IMPORT_FAILED');
  });
}


test('edit grant keeps row identity and original configuration', async ({ page }, testInfo) => {
  const state = await mockApi(page);
  await page.goto('/settings/automation');
  await row(page, 'Client A').getByRole('button', { name: '复制配置', exact: true }).click();
  await expect(page.locator('pre')).toContainText('secret-Client A');
  await row(page, 'Client A').getByRole('button', { name: '修改', exact: true }).click();
  await expect(page.locator('pre')).toHaveCount(0);
  await expect(page.getByLabel('授权名称', { exact: true })).toHaveValue('Client A');
  await expect(page.getByRole('button', { name: '有效期', exact: true })).toContainText('保持原到期时间');
  await page.getByLabel('授权名称', { exact: true }).fill('Edited A');
  await page.getByRole('button', { name: '保存修改', exact: true }).click();
  await expect(row(page, 'Edited A')).toBeVisible();
  expect(state.updated[0].id).toBe('Client A');
  expect(state.updated[0].input).not.toHaveProperty('lifetimeDays');
  await expect(page.getByRole('heading', { name: '修改自动化授权' })).toHaveCount(0);
  await row(page, 'Edited A').getByRole('button', { name: '复制配置', exact: true }).click();
  await expect(page.locator('pre')).toContainText('secret-Client A');
  await row(page, 'Client B').getByRole('button', { name: '修改', exact: true }).click();
  await expect(page.getByLabel('授权名称', { exact: true })).toHaveValue('Client B');
  await page.getByRole('button', { name: '有效期', exact: true }).click();
  await page.getByRole('option', { name: '长期', exact: true }).click();
  await page.getByRole('button', { name: '保存修改', exact: true }).click();
  await expect(row(page, 'Client B')).toContainText('长期');
  await expect(row(page, 'Revoked').getByRole('button', { name: '修改', exact: true })).toBeDisabled();
  await expect(row(page, 'Expired').getByRole('button', { name: '修改', exact: true })).toBeDisabled();
  await page.screenshot({ path: testInfo.outputPath('grant-edit.png'), fullPage: true });
});
