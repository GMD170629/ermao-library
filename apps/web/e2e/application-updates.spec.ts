import { expect, test, type Page } from '@playwright/test';
import type { PreparationState } from '../generated/updates';

const target = { version: '1.0.5', format: 1 as const, sha256: 'a'.repeat(64), filename: 'shuku-1.0.5-linux-x86_64.tar.gz', size: 100, expanded_size: 200, file_count: 3, environment: { format: 1 as const, platform: 'linux-x86_64', compatibility: 'b'.repeat(64) } };
async function fixture(page: Page, options: { admin?: boolean; supported?: boolean; reason?: string } = {}) {
  const data = { state: { phase: 'idle', downloaded: 0 } as PreparationState, current: '1.0.4', latest: '1.0.5', prepare: 0, install: 0, disconnect: false, submitted: null as unknown };
  const supported = options.supported ?? true;
  await page.context().addCookies([{ name: 'shuku_session', value: 'update-fixture', domain: '127.0.0.1', path: '/' }]);
  await page.route('https://raw.githubusercontent.com/**', route => route.fulfill({ json: {
    schemaVersion: 1, repository: 'GMD170629/ermao-library', releases: [{ version: data.latest, tag: `v${data.latest}`, notesPath: `v${data.latest}.md`, publishedAt: '2026-09-15T00:00:00Z', releaseUrl: `https://github.com/GMD170629/ermao-library/releases/tag/v${data.latest}` }]
  } }));
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname;
    const ok = (value: unknown, status = 200) => route.fulfill({ status, json: { ok: true, data: value } });
    if (path.endsWith('/auth/me')) return ok({ user: { id: 'update-user', email: 'fixture@example.com', name: 'Fixture', role: options.admin === false ? 'member' : 'admin', locale: 'zh-CN' }, authorization: { isAdmin: options.admin !== false, canManageSystem: options.admin !== false } });
    if (path.endsWith('/updates/runtime')) return ok({ current_version: data.current, supported });
    if (path.endsWith('/updates/check')) return ok({ current_version: data.current, supported, releases: [{ version: data.latest, installable: !options.reason && supported, reason: options.reason ?? null }] });
    if (path.endsWith('/updates/status')) {
      if (data.disconnect) return route.abort();
      return ok(data.state);
    }
    if (path.endsWith('/updates/prepare')) {
      data.prepare++;
      data.state = { phase: 'ready', downloaded: target.size, target };
      return ok(data.state, 202);
    }
    if (path.endsWith('/updates/install')) {
      data.install++;
      data.submitted = route.request().postDataJSON();
      if (JSON.stringify(data.submitted) !== JSON.stringify({ version: data.state.target?.version, sha256: data.state.target?.sha256 })) return route.fulfill({ status: 400, json: { ok: false, error: { code: 'PACKAGE_NOT_READY' } } });
      data.state = { ...data.state, phase: 'requested' };
      data.disconnect = true;
      return route.abort(); // Accepted POST, lost response: never automatically resubmit.
    }
    return ok({ shelves: [], libraries: [] });
  });
  return data;
}

test('two explicit confirmations; ready persists across refresh; lost install response only polls', async ({ page }) => {
  const f = await fixture(page);
  await page.goto('/settings/about');
  await page.getByRole('button', { name: '下载更新', exact: true }).click();
  await expect(page.getByText(/此操作只下载并准备更新包/)).toBeVisible();
  await page.getByRole('button', { name: '确认下载', exact: true }).click();
  await expect(page.getByText('更新包已准备好，等待安装', { exact: true })).toBeVisible();
  expect([f.prepare, f.install]).toEqual([1, 0]);
  f.latest = '1.0.6';
  await page.reload();
  await expect(page.getByText('本次更新包：v1.0.5', { exact: true })).toBeVisible();
  await expect(page.getByText('远程最新版本：v1.0.6', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: '安装并重启', exact: true }).click();
  await page.getByRole('button', { name: '取消', exact: true }).click();
  expect(f.install).toBe(0);
  await page.getByRole('button', { name: '安装并重启', exact: true }).click();
  await page.getByRole('button', { name: '确认安装', exact: true }).click();
  await expect(page.getByText('正在确认更新状态，请勿重复提交。', { exact: true })).toBeVisible();
  expect(f.install).toBe(1);
  f.disconnect = false;
  f.state = { ...f.state, phase: 'success' }; // HTTP/state success without matching running version isn't success.
  await expect(page.getByText('更新成功，实际运行版本 v1.0.5。', { exact: true })).toHaveCount(0);
  f.current = '1.0.5';
  await expect(page.getByText('更新成功，实际运行版本 v1.0.5。', { exact: true })).toBeVisible();
  expect([f.prepare, f.install]).toEqual([1, 1]);
});

test('changed package during confirmation is rejected, not silently replaced', async ({ page }) => {
  const f = await fixture(page);
  f.state = { phase: 'ready', target, downloaded: 100 };
  await page.goto('/settings/about');
  await page.getByRole('button', { name: '安装并重启', exact: true }).click();
  f.state = { ...f.state, target: { ...target, sha256: 'c'.repeat(64) } };
  await page.getByRole('button', { name: '确认安装', exact: true }).click();
  await expect(page.getByText('准备包已变化或失效，请重新查看并确认。', { exact: true })).toBeVisible();
  expect(f.submitted).toEqual({ version: target.version, sha256: target.sha256 });
  expect(f.state.phase).toBe('ready');
});

for (const options of [{ admin: false }, { supported: false }, { reason: 'PACKAGE_UNAVAILABLE' }, { reason: 'INCOMPATIBLE_ENVIRONMENT' }]) {
  test(`unavailable actions ${JSON.stringify(options)}`, async ({ page }) => {
    const f = await fixture(page, options);
    await page.goto('/settings/about');
    await expect(page.locator('strong').filter({ hasText: 'v1.0.4' })).toBeVisible();
    await expect(page.getByRole('button', { name: '下载更新', exact: true })).toHaveCount(0);
    await expect(page.getByRole('button', { name: '安装并重启', exact: true })).toHaveCount(0);
    expect([f.prepare, f.install]).toEqual([0, 0]);
  });
}

test('ambiguous installation times out without offering a blind second submission', async ({ page }) => {
  await page.clock.install();
  const f = await fixture(page);
  f.state = { phase: 'ready', target, downloaded: 100 };
  await page.goto('/settings/about');
  await page.getByRole('button', { name: '安装并重启', exact: true }).click();
  await page.getByRole('button', { name: '确认安装', exact: true }).click();
  await expect(page.getByText('正在确认更新状态，请勿重复提交。', { exact: true })).toBeVisible();
  await page.clock.fastForward(21 * 60_000);
  await expect(page.getByText('确认更新状态超时，请检查容器日志和 STORAGE_ROOT/update-tmp/installation.log。', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: '安装并重启', exact: true })).toBeDisabled();
  expect(f.install).toBe(1);
});

test('protocol 2 ready survives refresh and never offers installation', async ({ page }) => {
  const f = await fixture(page);
  f.state = { phase: 'ready', downloaded: 100, target: { format: 2, version: target.version, environment: target.environment, filename: 'shuku-1.0.5-linux-x86_64-v2.json', size: 100, sha256: target.sha256 } };
  await page.goto('/settings/about');
  await expect(page.getByText('更新已准备，当前版本尚不支持安装此协议。', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: '安装并重启', exact: true })).toHaveCount(0);
  await page.reload();
  await expect(page.getByText('更新已准备，当前版本尚不支持安装此协议。', { exact: true })).toBeVisible();
  expect([f.prepare, f.install]).toEqual([0, 0]);
});
