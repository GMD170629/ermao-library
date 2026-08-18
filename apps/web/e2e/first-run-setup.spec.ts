import { expect, test } from '@playwright/test';

test('an uninitialized installation opens the account setup wizard', async ({ page }) => {
  await page.route('**/api/auth/setup/status', async (route) => {
    await route.fulfill({ json: { ok: true, data: { initialized: false } } });
  });
  await page.route('**/api/auth/setup', async (route) => {
    expect(route.request().method()).toBe('POST');
    expect(route.request().postDataJSON()).toEqual({
      name: '二毛',
      email: 'owner@example.com',
      password: 'initial-password-123',
      locale: 'zh-CN'
    });
    await route.fulfill({
      status: 201,
      json: {
        ok: true,
        data: {
          initialized: true,
          user: { name: '二毛', email: 'owner@example.com', role: 'admin' }
        }
      }
    });
  });
  await page.route('**/api/libraries', async (route) => {
    if (route.request().method() === 'GET') {
      await route.fulfill({ json: { ok: true, data: { libraries: [] } } });
      return;
    }
    expect(route.request().method()).toBe('POST');
    expect(route.request().postDataJSON()).toEqual({
      name: '我的书库',
      rootPath: '/monitor',
      organizationMode: 'FLAT',
      enabled: true,
      ignorePatterns: '',
      ignoreHidden: true,
      minFileSizeBytes: 0
    });
    await route.fulfill({ status: 201, json: { ok: true, data: { library: { id: 'folder-1', name: '我的书库', rootPath: '/monitor', organizationMode: 'FLAT', enabled: true } } } });
  });
  await page.route('**/api/libraries/tree**', async (route) => {
    const requestedPath = new URL(route.request().url()).searchParams.get('path');
    await route.fulfill({
      json: {
        ok: true,
        data: {
          node: requestedPath === '/monitor'
            ? { name: 'monitor', path: '/monitor', readable: true, error: null, children: [] }
            : { name: '/', path: '/', readable: true, error: null, children: [{ name: 'monitor', path: '/monitor', readable: true }] },
          monitorRoot: null
        }
      }
    });
  });

  await page.goto('/login');

  await expect(page).toHaveURL(/\/setup$/);
  await expect(page.getByRole('heading', { name: '创建你的管理账户' })).toBeVisible();
  const setupForm = page.getByTestId('setup-form');
  await page.getByRole('button', { name: '创建账户' }).click();
  await expect(setupForm.getByRole('alert')).toHaveText('请输入用户名');
  await expect(setupForm.getByRole('alert')).toHaveClass(/bg-red-50/);
  await page.getByLabel('用户名').fill('二毛');
  await page.getByRole('button', { name: '创建账户' }).click();
  await expect(setupForm.getByRole('alert')).toHaveText('请输入登录邮箱');
  await page.getByLabel('登录邮箱').fill('owner@example.com');
  await page.getByLabel('登录密码').fill('initial-password-123');
  await page.getByLabel('确认密码').fill('initial-password-123');
  await page.getByRole('button', { name: '创建账户' }).click();

  await expect(page.getByRole('heading', { name: '新增书库' })).toBeVisible();
  const folderPath = page.getByRole('combobox', { name: '书库路径' });
  await folderPath.fill('/monitor');
  await page.getByRole('button', { name: '展开文件夹路径树' }).click();
  const directoryTree = page.getByRole('tree');
  await expect(directoryTree.getByRole('button', { name: '/', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'monitor', exact: true }).click();
  await expect(folderPath).toHaveValue('/monitor');
  await page.getByRole('button', { name: '添加并继续' }).click();

  await expect(page.getByRole('heading', { name: '你的私人书库已准备好' })).toBeVisible();
  await expect(page.getByText(/书库已启用/)).toBeVisible();
  await expect(page.getByText(/owner@example.com/)).toBeVisible();
  await expect(page.getByRole('button', { name: '进入书库' })).toBeVisible();
});

test('an initialized installation cannot reopen the setup wizard', async ({ page }) => {
  await page.route('**/api/auth/setup/status', async (route) => {
    await route.fulfill({ json: { ok: true, data: { initialized: true } } });
  });
  await page.route('**/api/auth/me', async (route) => {
    await route.fulfill({ status: 401, json: { ok: false, error: { message: 'UNAUTHORIZED' } } });
  });

  await page.goto('/setup');

  await expect(page).toHaveURL(/\/login$/);
  await expect(page.getByRole('button', { name: '登录' })).toBeVisible();
});

test('an authenticated owner can resume unfinished library onboarding after refresh', async ({ page }) => {
  await page.addInitScript(() => {
    window.localStorage.setItem('shuku.setup.progress', JSON.stringify({
      stage: 'folder',
      email: 'owner@example.com',
      folderAdded: false,
      folderPath: '/monitor'
    }));
  });
  await page.route('**/api/auth/setup/status', async (route) => {
    await route.fulfill({ json: { ok: true, data: { initialized: true } } });
  });
  await page.route('**/api/auth/me', async (route) => {
    await route.fulfill({ json: { ok: true, data: { user: { email: 'owner@example.com' } } } });
  });

  await page.goto('/setup');

  await expect(page.getByRole('heading', { name: '新增书库' })).toBeVisible();
  await expect(page.getByRole('combobox', { name: '书库路径' })).toHaveValue('/monitor');
});

test('login shows password errors in the system feedback style and in Chinese', async ({ page }) => {
  await page.route('**/api/auth/setup/status', async (route) => {
    await route.fulfill({ json: { ok: true, data: { initialized: true } } });
  });
  await page.route('**/api/auth/login', async (route) => {
    await route.fulfill({ status: 401, json: { ok: false, error: { message: 'Incorrect email or password' } } });
  });

  await page.goto('/login');
  await page.getByLabel('邮箱').fill('owner@example.com');
  await page.getByRole('button', { name: '登录' }).click();
  await expect(page.getByRole('alert').filter({ hasText: '请输入登录密码' })).toHaveText('请输入登录密码');

  await page.getByLabel('密码').fill('wrong-password');
  await page.getByRole('button', { name: '登录' }).click();
  const alert = page.getByRole('alert').filter({ hasText: '邮箱或密码不正确' });
  await expect(alert).toHaveText('邮箱或密码不正确');
  await expect(alert).toHaveClass(/bg-red-50/);
});

test('login recovers to setup when the initial status check was unavailable', async ({ page }) => {
  let loginAttempted = false;
  await page.route('**/api/auth/setup/status', async (route) => {
    if (!loginAttempted) {
      await route.fulfill({ status: 503, json: { ok: false, error: { message: '暂时不可用' } } });
      return;
    }
    await route.fulfill({ json: { ok: true, data: { initialized: false } } });
  });
  await page.route('**/api/auth/login', async (route) => {
    loginAttempted = true;
    await route.fulfill({
      status: 409,
      json: { ok: false, error: { message: '系统尚未初始化', details: { code: 'SETUP_REQUIRED' } } }
    });
  });

  await page.goto('/login');
  await page.getByLabel('邮箱').fill('owner@example.com');
  await page.getByLabel('密码').fill('not-created-yet');
  await page.getByRole('button', { name: '登录' }).click();

  await expect(page).toHaveURL(/\/setup$/);
  await expect(page.getByRole('heading', { name: '创建你的管理账户' })).toBeVisible();
});
