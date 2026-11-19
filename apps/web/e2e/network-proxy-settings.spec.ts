import { expect, test } from '@playwright/test';

test('data and system tabs and unsaved proxy test use the same draft', async ({ page }) => {
  const initial = { connection: null, presets: [], domains: [], presetDomains: { updates: ['ghcr.io'], github: ['github.com'], bangumi: ['bgm.tv'] } };
  let tested: unknown;
  let saved: unknown;
  await page.context().addCookies([{ name: 'shuku_session', value: 'proxy-session', domain: '127.0.0.1', path: '/' }]);
  await page.route('**/api/**', async route => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    const ok = (data: unknown) => route.fulfill({ json: { ok: true, data } });
    if (path === '/api/auth/me') return ok({ user: { id: 'proxy-admin', email: 'proxy@example.com', name: 'Admin', role: 'admin', locale: 'zh-CN' }, authorization: { isAdmin: true, canManageSystem: true, authzVersion: 1 } });
    if (path.endsWith('/network-proxy/test')) {
      tested = request.postDataJSON();
      return ok([{ host: 'ghcr.io', rules: ['updates'], result: 'timeout' }]);
    }
    if (path.endsWith('/network-proxy') && request.method() === 'PUT') {
      const payload = request.postDataJSON();
      saved = payload;
      return ok({ ...initial, ...payload, connection: { ...payload.connection, passwordConfigured: true } });
    }
    if (path.endsWith('/network-proxy')) return ok(initial);
    return ok({ shelves: [], settings: {}, libraries: [], backups: [], language: 'zh-CN' });
  });
  await page.goto('/settings/data');
  const content = page.getByTestId('app-shell-content');
  await expect(content.getByRole('link', { name: '备份与恢复' })).toHaveAttribute('aria-current', 'page');
  await content.getByRole('link', { name: '网络与代理' }).click();
  await expect(page).toHaveURL(/tab=proxy$/);
  await content.getByLabel('协议').selectOption('socks5');
  await content.getByLabel('服务器地址').fill('proxy.example.com');
  await content.getByLabel('端口').fill('1080');
  await content.getByLabel('密码（可选）').fill('proxy-test-password');
  await content.getByLabel('版本更新').check();
  await content.getByLabel('自定义域名', { exact: false }).fill('metadata.home.arpa');
  await content.getByText('查看域名', { exact: true }).click();
  await expect(content.getByText('ghcr.io', { exact: true })).toBeVisible();
  await content.getByRole('button', { name: '测试连接' }).click();
  await expect(content.getByText('连接超时')).toBeVisible();
  expect(saved).toBeUndefined();
  expect(tested).toMatchObject({ connection: { protocol: 'socks5', host: 'proxy.example.com', port: 1080, password: 'proxy-test-password' }, presets: ['updates'], domains: ['metadata.home.arpa'] });
  await content.getByRole('button', { name: '保存设置' }).click();
  await expect(content.getByText('代理设置已保存')).toBeVisible();
  expect(saved).toEqual(tested);
  await expect(content.getByLabel('密码（可选）')).toHaveValue('');
  await expect(content.getByLabel('密码（可选）')).toHaveAttribute('placeholder', '已配置');
  await page.goBack();
  await expect(content.getByRole('link', { name: '备份与恢复' })).toHaveAttribute('aria-current', 'page');
});
