import { expect, test } from '@playwright/test';

test('an uninitialized installation opens the account setup wizard', async ({ page }) => {
  await page.route('**/api/v2/auth/setup/status', async (route) => {
    await route.fulfill({ json: { required: true } });
  });
  await page.route('**/api/v2/auth/setup', async (route) => {
    expect(route.request().method()).toBe('POST');
    expect(route.request().postDataJSON()).toEqual({
      displayName: '二毛',
      email: 'owner@example.com',
      password: 'initial-password-123',
      locale: 'zh-CN'
    });
    await route.fulfill({
      status: 201,
      json: {
        account: {
          id: 'owner-1',
          displayName: '二毛',
          email: 'owner@example.com',
          role: 'admin',
          locale: 'zh-CN',
          scopes: ['catalog:read', 'operations:write'],
          disabled: false,
          monitorFolderIds: [],
          createdAt: '2026-07-25T00:00:00Z'
        },
        expiresAt: '2026-07-26T00:00:00Z'
      }
    });
  });
  await page.route('**/api/v2/ingestion/folders/tree', async (route) => {
    await route.fulfill({
      json: {
        monitorRoot: '/monitor',
        currentPath: '/monitor',
        parentPath: null,
        directories: []
      }
    });
  });
  await page.route('**/api/v2/ingestion/folders', async (route) => {
    if (route.request().method() === 'GET') {
      await route.fulfill({ json: { items: [], page: 1, pageSize: 24, total: 0 } });
      return;
    }
    expect(route.request().method()).toBe('POST');
    expect(route.request().postDataJSON()).toEqual({
      path: '/monitor',
      recursive: true,
      options: { name: '我的书库' }
    });
    await route.fulfill({
      status: 201,
      json: {
        id: 'folder-1',
        path: '/monitor',
        enabled: true,
        recursive: true,
        options: { name: '我的书库' },
        lastScanAt: null,
        createdAt: '2026-07-25T00:00:00Z'
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

  await expect(page.getByRole('heading', { name: '添加监控文件夹' })).toBeVisible();
  await expect(page.getByLabel('监控文件夹路径')).toHaveValue('/monitor');
  await page.getByRole('button', { name: '添加并继续' }).click();

  await expect(page.getByRole('heading', { name: '你的私人书库已准备好' })).toBeVisible();
  await expect(page.getByText(/监控文件夹已启用/)).toBeVisible();
  await expect(page.getByText(/owner@example.com/)).toBeVisible();
  await expect(page.getByRole('button', { name: '进入书库' })).toBeVisible();
});

test('an initialized installation cannot reopen the setup wizard', async ({ page }) => {
  await page.route('**/api/v2/auth/setup/status', async (route) => {
    await route.fulfill({ json: { required: false } });
  });
  await page.route('**/api/v2/account', async (route) => {
    await route.fulfill({
      status: 401,
      json: {
        type: 'https://shuku.app/problems/authentication',
        title: 'Authentication required',
        status: 401,
        code: 'UNAUTHORIZED',
        detail: '请先登录',
        params: {}
      }
    });
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
  await page.route('**/api/v2/auth/setup/status', async (route) => {
    await route.fulfill({ json: { required: false } });
  });
  await page.route('**/api/v2/account', async (route) => {
    await route.fulfill({
      json: {
        id: 'owner-1',
        displayName: '二毛',
        email: 'owner@example.com',
        role: 'admin',
        locale: 'zh-CN',
        scopes: ['catalog:read', 'operations:write'],
        disabled: false,
        monitorFolderIds: [],
        createdAt: '2026-07-25T00:00:00Z'
      }
    });
  });

  await page.goto('/setup');

  await expect(page.getByRole('heading', { name: '添加监控文件夹' })).toBeVisible();
  await expect(page.getByLabel('监控文件夹路径')).toHaveValue('/monitor');
});

test('login shows password errors in the system feedback style and in Chinese', async ({ page }) => {
  await page.route('**/api/v2/auth/setup/status', async (route) => {
    await route.fulfill({ json: { required: false } });
  });
  await page.route('**/api/v2/auth/login', async (route) => {
    await route.fulfill({
      status: 401,
      json: {
        type: 'https://shuku.app/problems/authentication',
        title: 'Authentication failed',
        status: 401,
        code: 'INVALID_CREDENTIALS',
        detail: '邮箱或密码不正确',
        params: {}
      }
    });
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
  await page.route('**/api/v2/auth/setup/status', async (route) => {
    if (!loginAttempted) {
      await route.fulfill({
        status: 503,
        json: {
          type: 'https://shuku.app/problems/unavailable',
          title: 'Service unavailable',
          status: 503,
          code: 'SERVICE_UNAVAILABLE',
          detail: '暂时不可用',
          params: {}
        }
      });
      return;
    }
    await route.fulfill({ json: { required: true } });
  });
  await page.route('**/api/v2/auth/login', async (route) => {
    loginAttempted = true;
    await route.fulfill({
      status: 409,
      json: {
        type: 'https://shuku.app/problems/setup-required',
        title: 'Setup required',
        status: 409,
        code: 'SETUP_REQUIRED',
        detail: '系统尚未初始化',
        params: {}
      }
    });
  });

  await page.goto('/login');
  await page.getByLabel('邮箱').fill('owner@example.com');
  await page.getByLabel('密码').fill('not-created-yet');
  await page.getByRole('button', { name: '登录' }).click();

  await expect(page).toHaveURL(/\/setup$/);
  await expect(page.getByRole('heading', { name: '创建你的管理账户' })).toBeVisible();
});
