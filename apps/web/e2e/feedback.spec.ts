import { expect, test, type Page } from '@playwright/test';

async function mockFeedbackApi(page: Page, locale: 'zh-CN' | 'en-US') {
  let sends = 0;
  await page.context().addCookies([{ name: 'shuku_session', value: 'feedback-test-session', domain: '127.0.0.1', path: '/' }]);
  await page.route('**/api/**', async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === '/api/auth/me') {
      await route.fulfill({ json: { ok: true, data: { user: { id: 'feedback-admin', email: 'feedback@example.com', name: 'Feedback admin', role: 'admin', locale }, authorization: { isAdmin: true, canManageSystem: true, authzVersion: 1 } } } });
    } else if (path === '/api/feedback/environment') {
      await route.fulfill({ json: { ok: true, data: { appVersion: '1.5.1' } } });
    } else if (path === '/api/feedback/preview') {
      const draft = route.request().postDataJSON();
      await route.fulfill({ json: { ok: true, data: { previewHash: 'a'.repeat(64), diagnostics: {
        ...(draft.includeEnvironment ? { environment: { appVersion: '1.5.1', installationMethod: draft.installationMethod, ...draft.clientEnvironment } } : {}),
        ...(draft.eventId ? { log: { selectedEventId: draft.eventId, events: [{ id: draft.eventId, message: 'Read failed' }], relatedBooks: [] } } : {})
      } } } });
    } else if (path === '/api/feedback' && route.request().method() === 'POST') {
      sends++;
      await route.fulfill(sends === 1
        ? { status: 503, json: { ok: false, error: { code: 'FEEDBACK_DELIVERY_FAILED', message: '暂时失败' } } }
        : { json: { ok: true, data: { id: 'FB-TEST', status: 'sent' } } });
    } else if (path === '/api/management/events') {
      await route.fulfill({ json: { ok: true, data: { events: [{ id: 'event-1', level: 'error', source: 'reader', actorType: 'system', action: 'open', targetType: 'book', targetId: 'book-1', message: 'Read failed', metadata: {}, createdAt: '2026-09-29T10:00:00Z' }], total: 1, totalPages: 1, storage: { sizeBytes: 100, maxBytes: 5 * 1024 * 1024 } } } });
    } else if (path === '/api/management/events/event-1') {
      await route.fulfill({ json: { ok: true, data: { id: 'event-1', level: 'error', source: 'reader', actorType: 'system', action: 'open', targetType: 'book', targetId: 'book-1', message: 'Read failed', metadata: {}, createdAt: '2026-09-29T10:00:00Z' } } });
    } else {
      await route.fulfill({ json: { ok: true, data: {} } });
    }
  });
  return () => sends;
}

test('environment details stay collapsed until requested and include the full user agent', async ({ page }) => {
  await mockFeedbackApi(page, 'zh-CN');
  await page.goto('/settings/about');
  await page.getByRole('button', { name: '功能建议' }).click();
  const dialog = page.getByRole('dialog');
  await dialog.getByLabel('同步系统环境信息').check();
  await expect(dialog.locator('pre')).toHaveCount(0);
  const installationPicker = dialog.getByRole('button', { name: '安装方式' });
  await installationPicker.click();
  await expect(installationPicker).toHaveAttribute('aria-expanded', 'true');
  await page.keyboard.press('Escape');
  await expect(dialog).toBeVisible();
  await expect(installationPicker).toHaveAttribute('aria-expanded', 'false');
  await installationPicker.click();
  await page.getByRole('option', { name: 'Docker 安装' }).click();
  await dialog.getByRole('button', { name: '查看会收集哪些信息' }).click();
  await expect(dialog.locator('pre')).toContainText('userAgent');
  await expect(dialog.locator('pre')).toContainText('Docker 安装');
  await dialog.locator('textarea').fill('### 测试\n环境信息核对');
  await dialog.getByRole('button', { name: '核对内容' }).click();
  await expect(dialog.locator('pre')).toContainText('userAgent');
});

for (const locale of ['zh-CN', 'en-US'] as const) {
  test(`about feedback retains draft and attachment across retry (${locale})`, async ({ page }) => {
    const sends = await mockFeedbackApi(page, locale);
    await page.goto('/settings/about');
    await page.getByRole('button', { name: locale === 'zh-CN' ? '功能建议' : 'Feature suggestion' }).click();
    const dialog = page.getByRole('dialog');
    await expect(dialog).toBeVisible();
    await dialog.locator('textarea').fill('### Example\nPlease add a clearer reading progress view.');
    await dialog.locator('input[type=file]').nth(1).setInputFiles({ name: 'note.txt', mimeType: 'text/plain', buffer: Buffer.from('extra context') });
    if (locale === 'zh-CN') {
      await dialog.locator('input[type=file]').first().setInputFiles({ name: 'capture.png', mimeType: 'image/png', buffer: Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4z8DwHwAFgAI/ScL/nwAAAABJRU5ErkJggg==', 'base64') });
      await dialog.getByRole('button', { name: '预览', exact: true }).click();
      await expect(dialog.getByRole('img', { name: 'capture.png' })).toBeVisible();
    }
    await dialog.getByRole('button', { name: locale === 'zh-CN' ? '核对内容' : 'Review content' }).click();
    await expect(dialog.getByText('note.txt')).toBeVisible();
    await dialog.getByRole('button', { name: locale === 'zh-CN' ? '确认提交' : 'Send feedback' }).click();
    await expect(dialog.getByRole('button', { name: locale === 'zh-CN' ? '重试提交' : 'Try again' })).toBeVisible();
    await expect(dialog.getByText('note.txt')).toHaveCount(0);
    await dialog.getByRole('button', { name: locale === 'zh-CN' ? '重试提交' : 'Try again' }).click();
    await expect(dialog.getByText('FB-TEST')).toBeVisible();
    expect(sends()).toBe(2);
  });
}

test('mobile log detail opens issue feedback with selected event', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await mockFeedbackApi(page, 'zh-CN');
  await page.goto('/settings/logs');
  await page.getByTestId('system-event-mobile-card').getByRole('button', { name: '查看详情' }).click();
  await page.getByTestId('system-event-mobile-card').getByRole('button', { name: '反馈此问题' }).click();
  const dialog = page.getByRole('dialog');
  await expect(dialog.getByText(/event-1/)).toBeVisible();
  await dialog.getByRole('button', { name: '查看将发送的日志' }).click();
  await expect(dialog.getByText(/Read failed/)).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(dialog).toHaveCount(0);
});
