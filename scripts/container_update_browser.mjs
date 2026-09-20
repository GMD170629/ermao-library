// Explicit browser leg of accept_container_update.py; never run against a real library.
import { createRequire } from 'node:module';
import assert from 'node:assert/strict';
import { visibleReaderFrame, revealReaderControls } from '../apps/web/e2e/reader-controls.ts';
const require = createRequire(new URL('../apps/web/package.json', import.meta.url));
const { chromium, expect } = require('@playwright/test');
const [base, source, action, current, target, profile] = process.argv.slice(2);
if (!/^http:\/\/127\.0\.0\.1:\d+$/.test(base) || !['read', 'download', 'cancel', 'install', 'verify'].includes(action)) throw Error('Disposable local acceptance only');
if (!profile) throw Error('Isolated persistent browser profile required');
const context = await chromium.launchPersistentContext(profile, { ...(process.env.ACCEPTANCE_CHROMIUM === 'bundled' ? {} : { channel: 'chrome' }), headless: true, locale: 'zh-CN' });
try {
  // Only release metadata is redirected to the real fixture server, never business APIs.
  await context.route('https://raw.githubusercontent.com/GMD170629/ermao-library/release-feed/**', async route => {
    const name = new URL(route.request().url()).pathname.split('/').at(-1);
    const response = await context.request.get(`${source}/${name}`);
    await route.fulfill({ response });
  });
  const page = await context.newPage();
  const mutations = [];
  page.on('request', request => {
    if (request.method() === 'POST' && /\/api\/updates\/(prepare|install)$/.test(new URL(request.url()).pathname)) mutations.push(request);
  });
  const session = await context.request.get(`${base}/api/auth/me`);
  if (action === 'verify') assert.equal(session.status(), 200, 'update must retain the session');
  if (session.status() !== 200) {
    await page.goto(`${base}/login`);
    await page.locator('input[type=email]').fill('acceptance@example.com');
    await page.locator('input[type=password]').fill('Acceptance-password-42');
    await page.getByRole('button', { name: '登录', exact: true }).click();
    await page.waitForURL(url => !url.pathname.endsWith('/login'));
  }
  await page.goto(`${base}/settings/about`);
  async function readerRegression(before) {
    if (before) {
      const scan = await context.request.post(`${base}/api/libraries/acceptance-reader/scan`);
      assert.equal(scan.status(), 202);
    }
    let book;
    await expect.poll(async () => {
      const response = await context.request.get(`${base}/api/books?pageSize=100`);
      const body = await response.json();
      book = body.data.books.find(item => item.libraryId === 'acceptance-reader');
      return !!book;
    }, { timeout: 60000 }).toBe(true);
    // A book can be visible before its asynchronous resource import completes.
    let detail, resource;
    await expect.poll(async () => {
      detail = await (await context.request.get(`${base}/api/books/${book.id}`)).json();
      resource = detail.data.book.resources.find(item => item.format.toUpperCase() === 'EPUB');
      return !!resource;
    }, { timeout: 60000 }).toBe(true);
    await page.goto(`${base}/library`);
    await expect(page.getByRole('button', { name: new RegExp(detail.data.book.title) }).first()).toBeVisible();
    await page.goto(`${base}/reader/${resource.id}`);
    const frame = await visibleReaderFrame(page);
    await expect(frame.contentFrame().getByText(before ? '第一章 开始阅读' : '第二章 翻页验证')).toBeVisible();
    if (before) {
      await revealReaderControls(page);
      await page.getByRole('button', { name: '下一章', exact: true }).click();
      const next = await visibleReaderFrame(page);
      await expect(next.contentFrame().getByText('第二章 翻页验证')).toBeVisible();
      await expect.poll(async () => {
        const progress = await context.request.get(`${base}/api/reader/v5/resources/${resource.id}/progress`);
        return await progress.text();
      }, { timeout: 45000 }).toContain('chapter2');
    }
  }
  if (action === 'read') {
    await readerRegression(true);
  } else if (action === 'download') {
    const accepted = page.waitForResponse(r => r.url().endsWith('/api/updates/prepare') && r.status() === 202);
    await page.getByRole('button', { name: '下载更新', exact: true }).click();
    await accepted;
    assert.equal(mutations.length, 1);
    assert.match(mutations[0].url(), /\/prepare$/);
    await page.close(); // Harness holds the real download open until this browser exits.
  } else if (action === 'cancel' || action === 'install') {
    await expect(page.getByText('更新包已准备好，等待安装', { exact: true })).toBeVisible();
    await expect(page.getByText(`本次更新包：v${target}`, { exact: true })).toBeVisible();
    await page.getByRole('button', { name: /^(安装并重启|立即更新)$/ }).click();
    await expect(page.getByText(new RegExp(`当前版本 v${current}，待安装版本 v${target}`))).toBeVisible();
    if (action === 'cancel') {
      await page.getByRole('button', { name: '取消', exact: true }).click();
      await page.reload();
      await expect(page.getByText('更新包已准备好，等待安装', { exact: true })).toBeVisible();
      assert.equal(mutations.length, 0);
    } else {
      const accepted = page.waitForResponse(r => r.url().endsWith('/api/updates/install') && r.status() === 202);
      await page.getByRole('button', { name: /^(确认安装|确认更新)$/ }).click();
      await accepted;
      assert.equal(mutations.length, 1);
      assert.equal(mutations[0].postDataJSON().version, target);
      assert.match(mutations[0].postDataJSON().sha256, /^[a-f0-9]{64}$/);
      const status = await (await context.request.get(`${base}/api/updates/status`)).json();
      if (status.data.target.format === 2) assert.equal(mutations[0].postDataJSON().plan_sha256, status.data.summary.plan_sha256);
      await page.close();
    }
  } else {
    await expect(page.getByText(`更新成功，实际运行版本 v${target}。`, { exact: true })).toBeVisible({ timeout: 30000 });
    await page.waitForLoadState('domcontentloaded');
    const response = await context.request.get(`${base}/api/updates/runtime`);
    assert.equal((await response.json()).data.current_version, target);
    assert.equal(mutations.length, 0);
    await expect(page.getByRole('alertdialog')).toHaveCount(0, { timeout: 30000 });
    await expect(page.getByText(`更新成功，实际运行版本 v${target}。`, { exact: true })).toBeVisible();
    await page.getByText(`更新成功，实际运行版本 v${target}。`, { exact: true }).scrollIntoViewIfNeeded();
    await page.screenshot({ path: `/tmp/shuku-update-${target}.png`, fullPage: true });
    // Login and catalog regression use the same authenticated browser and real API.
    await readerRegression(false);
    await page.goto(`${base}/library`);
    await expect(page.locator('body')).not.toContainText('Internal Server Error');
    const libraries = await context.request.get(`${base}/api/libraries`);
    assert.equal(libraries.status(), 200);
  }
  console.log(`browser ${action}: passed`);
} finally { await context.close(); }
