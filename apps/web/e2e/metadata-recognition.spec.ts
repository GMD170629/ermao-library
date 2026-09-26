import { expect, test, type Page } from '@playwright/test';

// Requires tests/fixtures/recognition_http_server.py and PYTHON_API_ORIGIN=:8106.
// Uses actual HTTP, authorization, source parser, SQLite and patch operations.
// Only Google response bytes are fixtures; this is not a live-provider test.
test.skip(process.env.RECOGNITION_HTTP_SMOKE !== '1', 'Requires the isolated recognition HTTP fixture');

async function openLookup(page: Page) {
  await page.goto('/books/recognition-smoke');
  await page.getByRole('button', { name: '管理 示例书 第1卷', exact: true }).focus();
  await page.keyboard.press('Enter');
  await page.getByRole('menuitem', { name: '识别', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: '元数据识别', exact: true });
  await expect(dialog).toBeVisible();
  await dialog.getByRole('button', { name: '搜索', exact: true }).click();
  await expect(dialog.getByText('找到 1 条候选')).toBeVisible();
  return dialog;
}

test('saved provider controls, field confirmation, refresh and two browser stale rejection', async ({ page, context, browser }) => {
  test.setTimeout(90_000);
  page.setDefaultTimeout(15_000);
  expect((await context.request.post("http://127.0.0.1:8106/_fixture/reset")).status()).toBe(200);
  const login = await context.request.post('/api/auth/login', { data: { email: 'recognition@example.com', password: 'RecognizedMetadata123!' } });
  expect(login.status()).toBe(200);
  await page.goto('/settings/organize?tab=providers');
  await page.getByTestId('metadata-provider-google-books').getByRole('button', { name: '配置', exact: true }).click();
  const editor = page.getByRole('dialog', { name: '配置 Google Books', exact: true });
  await editor.getByLabel('API Key').fill('fixture-key');
  await editor.getByRole('button', { name: '保存配置', exact: true }).click();
  const enable = page.getByRole('switch', { name: '启用Google Books', exact: true });
  if (await enable.count()) await enable.click();
  await expect(page.getByRole('switch', { name: '停用Google Books', exact: true })).toBeVisible();
  await page.reload();
  await expect(page.getByRole('switch', { name: '停用Google Books', exact: true })).toBeVisible();

  const other = await browser.newContext({ storageState: await context.storageState(), baseURL: test.info().project.use.baseURL ?? 'http://127.0.0.1:3100' });
  const secondPage = await other.newPage();
  try {
    const first = await openLookup(page);
    const second = await openLookup(secondPage);
    await expect(first.locator('label').filter({ hasText: '出版时间' })).toContainText('1980');
    await expect(first.locator('label').filter({ hasText: '出版时间' }).getByRole('checkbox')).toBeDisabled();
    const applied = page.waitForResponse((response) => response.url().endsWith('/metadata/apply'));
    await first.getByRole('button', { name: '应用所选字段', exact: true }).click();
    const appliedResponse = await applied;
    expect(appliedResponse.status(), await appliedResponse.text()).toBe(200);
    await expect(first).toBeHidden();
    const detail = await (await context.request.get('/api/books/recognition-smoke')).json();
    expect(detail.data.book.resources[0].publisher).toBe('Fixture Press');
    expect(detail.data.book.resources[0].isbn).toBe('9780306406157');
    expect(detail.data.book.resources[0].publishedAt).toBeNull();
    const stale = secondPage.waitForResponse((response) => response.url().endsWith('/metadata/apply'));
    await second.getByRole('button', { name: '应用所选字段', exact: true }).click();
    expect((await stale).status()).toBe(409);
    await expect(second.getByText('元数据已改变或受保护，请重新识别')).toBeVisible();
    await secondPage.keyboard.press('Escape');
    await expect(second).toBeHidden();
    await page.reload();
    await expect(page.getByText('EPUB · Fixture Press · zh', { exact: true })).toBeVisible();
  } finally {
    await other.close();
  }
});


test('path repair persists and disabled sources make zero provider requests', async ({ page, context }) => {
  page.setDefaultTimeout(15_000);
  expect((await context.request.post('/api/auth/login', { data: { email: 'recognition@example.com', password: 'RecognizedMetadata123!' } })).status()).toBe(200);
  await page.goto('/settings/organize?tab=recognition');
  const repair = page.getByRole('switch', { name: '修正低质量路径信息', exact: true });
  await expect(repair).toBeEnabled();
  if (await repair.getAttribute('aria-checked') === 'false') await repair.click();
  const saved = page.waitForResponse((response) => response.url().endsWith('/api/organize/policy') && response.request().method() === 'PUT');
  await page.getByRole('button', { name: '保存设置', exact: true }).click();
  expect((await saved).status()).toBe(200);
  await page.reload();
  await expect(repair).toHaveAttribute('aria-checked', 'true');
  const policy = await (await context.request.get('/api/organize/policy')).json();
  expect(policy.data.policy.allowRepairPathMetadata).toBe(true);
  await page.goto('/settings/organize?tab=providers');
  await expect(page.getByTestId('metadata-provider-google-books')).toBeVisible();
  const disable = page.getByRole('switch', { name: '停用Google Books', exact: true });
  if (await disable.count()) await disable.click();
  await expect(page.getByRole('switch', { name: '启用Google Books', exact: true })).toBeVisible();
  const before = await (await context.request.get('http://127.0.0.1:8106/_fixture/requests')).json();
  const result = await context.request.post('/api/books/recognition-smoke/source-nodes/recognition-smoke-resource-node/metadata/search', { data: { providerId: 'google-books', resourceId: 'recognition-smoke-resource', query: 'disabled query' } });
  expect(result.status()).toBe(200);
  expect((await result.json()).data.candidates).toEqual([]);
  expect(await (await context.request.get('http://127.0.0.1:8106/_fixture/requests')).json()).toEqual(before);
});
