import { expect, test, type Page } from '@playwright/test';
import type { PreparationState } from '../generated/updates';

const target = { version: '1.0.5', format: 1 as const, sha256: 'a'.repeat(64), filename: 'shuku-1.0.5-linux-x86_64.tar.gz', size: 100, expanded_size: 200, file_count: 3, environment: { format: 1 as const, platform: 'linux-x86_64', compatibility: 'b'.repeat(64) } };
async function fixture(page: Page, options: { admin?: boolean; supported?: boolean; reason?: string; protocol?: number; locale?: string } = {}) {
  const data = { state: { phase: 'idle', downloaded: 0 } as PreparationState, current: '1.0.4', latest: '1.0.5', prepare: 0, install: 0, disconnect: false, submitted: null as unknown };
  const supported = options.supported ?? true;
  await page.context().addCookies([{ name: 'shuku_locale', value: options.locale ?? 'zh-CN', domain: '127.0.0.1', path: '/' }, { name: 'shuku_session', value: 'update-fixture', domain: '127.0.0.1', path: '/' }]);
  await page.route('https://raw.githubusercontent.com/**', route => {
    if (new URL(route.request().url()).pathname.endsWith('.md')) return route.fulfill({ contentType: 'text/plain', body: '<!-- shuku:locale=zh-CN:start -->\n更新说明\n<!-- shuku:locale=zh-CN:end -->\n<!-- shuku:locale=en-US:start -->\nRelease notes\n<!-- shuku:locale=en-US:end -->' });
    return route.fulfill({ json: {
    schemaVersion: 1, repository: 'GMD170629/ermao-library', releases: [{ version: data.latest, tag: `v${data.latest}`, notesPath: `v${data.latest}.md`, publishedAt: '2026-09-15T00:00:00Z', releaseUrl: `https://github.com/GMD170629/ermao-library/releases/tag/v${data.latest}` }]
  } });
  });
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname;
    const ok = (value: unknown, status = 200) => route.fulfill({ status, json: { ok: true, data: value } });
    if (path.endsWith('/auth/me')) return ok({ user: { id: 'update-user', email: 'fixture@example.com', name: 'Fixture', role: options.admin === false ? 'member' : 'admin', locale: options.locale ?? 'zh-CN' }, authorization: { isAdmin: options.admin !== false, canManageSystem: options.admin !== false } });
    if (path.endsWith('/config')) return ok({ language: options.locale ?? 'zh-CN' });
    if (path.endsWith('/updates/runtime')) return ok({ current_version: data.current, supported, install_protocol: options.protocol ?? 1 });
    if (path.endsWith('/updates/check')) return ok({ current_version: data.current, supported, releases: [{ version: data.latest, installable: !options.reason && supported, reason: options.reason ?? null }] });
    if (path.endsWith('/updates/status')) {
      if (data.disconnect) return route.abort();
      return ok(data.state);
    }
    if (path.endsWith('/updates/prepare')) {
      data.prepare++;
      data.state = { phase: 'downloading', downloaded: 25, target };
      return ok(data.state, 202);
    }
    if (path.endsWith('/updates/install')) {
      data.install++;
      data.submitted = route.request().postDataJSON();
      if (JSON.stringify(data.submitted) !== JSON.stringify({ version: data.state.target?.version, sha256: data.state.target?.sha256, ...(data.state.summary?.plan_sha256 ? { plan_sha256: data.state.summary.plan_sha256 } : {}) })) return route.fulfill({ status: 400, json: { ok: false, error: { code: 'PACKAGE_NOT_READY' } } });
      data.state = { ...data.state, phase: 'requested' };
      data.disconnect = true;
      return route.abort(); // Accepted POST, lost response: never automatically resubmit.
    }
    return ok({ shelves: [], libraries: [] });
  });
  return data;
}

test('direct download and explicit install confirmation; ready persists across refresh; lost install response only polls', async ({ page }) => {
  const f = await fixture(page);
  await page.goto('/settings/about');
  await page.getByRole('button', { name: '下载更新', exact: true }).click();
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await expect(page.getByText('正在下载更新包', { exact: true })).toBeVisible();
  await expect(page.getByText('25%', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: '下载更新', exact: true })).toBeDisabled();
  f.state = { phase: 'verifying', target, downloaded: 100 };
  await expect(page.getByText('正在校验更新包', { exact: true })).toBeVisible();
  f.state = { phase: 'extracting', target, downloaded: 100 };
  await expect(page.getByText('正在解压更新包', { exact: true })).toBeVisible();
  f.state = { phase: 'ready', target, downloaded: 100 };
  await expect(page.getByText('更新包已准备好，等待安装', { exact: true })).toBeVisible();
  expect([f.prepare, f.install]).toEqual([1, 0]);
  f.latest = '1.0.6';
  await page.reload();
  await expect(page.getByText('本次更新包：v1.0.5', { exact: true })).toBeVisible();
  await page.getByText('更新详情', { exact: true }).click();
  await expect(page.getByText('远程最新版本：v1.0.6', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: '立即更新', exact: true }).click();
  await page.getByRole('button', { name: '取消', exact: true }).click();
  expect(f.install).toBe(0);
  await page.getByRole('button', { name: '立即更新', exact: true }).click();
  f.latest = '1.0.5';
  await page.getByRole('button', { name: '确认更新', exact: true }).click();
  await expect(page.getByText('正在确认更新状态，请勿重复提交。', { exact: true })).toBeVisible();
  expect(f.install).toBe(1);
  f.disconnect = false;
  f.state = { ...f.state, phase: 'success' }; // HTTP/state success without matching running version isn't success.
  await expect(page.getByText('更新成功，实际运行版本 v1.0.5。', { exact: true })).toHaveCount(0);
  f.current = '1.0.5';
  await expect(page.getByText('更新成功，实际运行版本 v1.0.5。', { exact: true })).toBeVisible();
  await expect(page.getByTestId('update-status').getByRole('alert')).toHaveCount(0);
  expect([f.prepare, f.install]).toEqual([1, 1]);
  f.latest = '1.0.6';
  await page.getByRole('button', { name: '刷新更新状态', exact: true }).click();
  await expect(page.getByRole('button', { name: '下载更新', exact: true })).toBeEnabled();
});

test('changed package during confirmation is rejected, not silently replaced', async ({ page }) => {
  const f = await fixture(page);
  f.state = { phase: 'ready', target, downloaded: 100 };
  await page.goto('/settings/about');
  await page.getByRole('button', { name: '立即更新', exact: true }).click();
  f.state = { ...f.state, target: { ...target, sha256: 'c'.repeat(64) } };
  await page.getByRole('button', { name: '确认更新', exact: true }).click();
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
    await expect(page.getByRole('button', { name: '立即更新', exact: true })).toHaveCount(0);
    expect([f.prepare, f.install]).toEqual([0, 0]);
  });
}

test('ambiguous installation times out without offering a blind second submission', async ({ page }) => {
  await page.clock.install();
  const f = await fixture(page);
  f.state = { phase: 'ready', target, downloaded: 100 };
  await page.goto('/settings/about');
  await page.getByRole('button', { name: '立即更新', exact: true }).click();
  await page.getByRole('button', { name: '确认更新', exact: true }).click();
  await expect(page.getByText('正在确认更新状态，请勿重复提交。', { exact: true })).toBeVisible();
  await page.clock.fastForward(21 * 60_000);
  await expect(page.getByText('确认更新状态超时，请检查容器日志和 STORAGE_ROOT/update-tmp/installation.log。', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: '立即更新', exact: true })).toBeDisabled();
  expect(f.install).toBe(1);
});

test('protocol 2 ready survives refresh and never offers installation', async ({ page }) => {
  const f = await fixture(page);
  f.state = { phase: 'ready', downloaded: 100, target: { format: 2, version: target.version, environment: target.environment, filename: 'shuku-1.0.5-linux-x86_64-v2.json', size: 100, sha256: target.sha256 } };
  await page.goto('/settings/about');
  await expect(page.getByText('更新已准备，当前版本尚不支持安装此协议。', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: '立即更新', exact: true })).toHaveCount(0);
  await page.reload();
  await expect(page.getByText('更新已准备，当前版本尚不支持安装此协议。', { exact: true })).toBeVisible();
  expect([f.prepare, f.install]).toEqual([0, 0]);
});


test('GHCR protocol 2 sends captured plan and shows real dependency totals', async ({ page }) => {
  const f = await fixture(page, { protocol: 2 });
  const summary = { plan_sha256: 'e'.repeat(64), dependency_identity: 'b'.repeat(64), baseline: 'c'.repeat(64), code_sha256: 'd'.repeat(64), keep: 58, install: 1, remove: 2, total_bytes: 12000, dependency_bytes: 10240, verified_artifacts: 2 };
  f.state = { phase: 'ready', downloaded: 12000, target: { format: 2, version: target.version, environment: target.environment, filename: 'shuku-1.0.5-linux-x86_64-v2.json', size: 100, sha256: target.sha256, oci_digest: `sha256:${'9'.repeat(64)}` }, summary };
  await page.goto('/settings/about');
  await page.getByText('更新详情', { exact: true }).click();
  await expect(page.getByText('依赖：安装／替换 1，删除 2，保留 58。', { exact: false })).toBeVisible();
  await expect(page.getByText('已下载 12,000 字节，总计 12,000 字节；依赖下载 10,240 字节。', { exact: false })).toBeVisible();
  await page.getByRole('button', { name: '立即更新', exact: true }).click();
  await page.getByRole('button', { name: '取消', exact: true }).click();
  expect(f.install).toBe(0);
  await page.reload();
  await page.getByRole('button', { name: '立即更新', exact: true }).click();
  f.state = { ...f.state, summary: { ...summary, plan_sha256: 'f'.repeat(64) } };
  await page.getByRole('button', { name: '确认更新', exact: true }).click();
  await expect(page.getByText('准备包已变化或失效，请重新查看并确认。', { exact: true })).toBeVisible();
  expect(f.submitted).toEqual({ version: target.version, sha256: target.sha256, plan_sha256: summary.plan_sha256 });
  expect(f.state.phase).toBe('ready');
});

for (const locale of ['zh-CN', 'en-US']) {
  test(`single status bar and keyboard confirmation (${locale})`, async ({ page }, testInfo) => {
    const errors: string[] = [];
    page.on('pageerror', error => errors.push(error.message));
    page.on('console', message => { if (message.type() === 'error') errors.push(message.text()); });
    const f = await fixture(page, { locale });
    f.latest = f.current;
    await page.goto('/settings/about');
    await expect(page).toHaveURL(/\/settings\/about$/);
    expect(await page.title()).not.toBe('');
    const bar = page.getByTestId('update-status');
    await expect(bar).toHaveCount(1);
    await expect(bar).toContainText(locale === 'zh-CN' ? '当前已是最新正式版本。' : 'You are running the latest stable version.');
    await expect(bar).toHaveClass(/bg-\[#F2F8F1\]/);
    await expect(bar.locator('details')).not.toHaveAttribute('open', '');
    await expect(bar.getByRole('button', { name: locale === 'zh-CN' ? '下载更新' : 'Download update', exact: true })).toHaveCount(0);
    f.latest = '1.0.5';
    await bar.getByRole('button', { name: locale === 'zh-CN' ? '刷新更新状态' : 'Refresh update status' }).click();
    await expect(bar).toContainText(locale === 'zh-CN' ? '检查到新版本 v1.0.5' : 'New version detected: v1.0.5');
    await expect(bar).toHaveClass(/bg-orange-50/);
    await bar.scrollIntoViewIfNeeded();
    await page.screenshot({ path: `/tmp/about-update-${testInfo.project.name}-${locale}.png` });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    f.state = { phase: 'ready', target, downloaded: 100 };
    await page.reload();
    const install = bar.getByRole('button', { name: locale === 'zh-CN' ? '立即更新' : 'Update now', exact: true });
    await install.focus();
    await page.keyboard.press('Enter');
    const dialog = page.getByRole('dialog');
    await expect(dialog).toContainText(locale === 'zh-CN' ? '暂停队列领取' : 'pause queue processing');
    await expect(dialog).toContainText('1.0.4');
    await expect(dialog).toContainText('1.0.5');
    await dialog.getByRole('button', { name: locale === 'zh-CN' ? '取消' : 'Cancel', exact: true }).focus();
    await page.keyboard.press('Enter');
    await expect(dialog).toHaveCount(0);
    expect(f.install).toBe(0);
    expect(errors).toEqual([]);
  });
}

test('failed download stays in the status bar and can be retried', async ({ page }) => {
  const f = await fixture(page);
  f.state = { phase: 'failed', failed_phase: 'downloading', error: 'DOWNLOAD_FAILED', target, downloaded: 0 };
  await page.goto('/settings/about');
  const bar = page.getByTestId('update-status');
  await expect(bar).toHaveClass(/bg-\[#FFF4F1\]/);
  await expect(bar.getByRole('alert')).toContainText('下载失败');
  await bar.getByRole('button', { name: '下载更新', exact: true }).click();
  await expect(bar).toContainText('正在下载更新包');
  expect([f.prepare, f.install]).toEqual([1, 0]);
});
