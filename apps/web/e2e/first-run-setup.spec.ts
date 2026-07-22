import { expect, test } from '@playwright/test';

test('an uninitialized installation opens the account setup wizard', async ({ page }) => {
  await page.route('**/api/auth/setup/status', async (route) => {
    await route.fulfill({ json: { ok: true, data: { initialized: false } } });
  });
  await page.route('**/api/auth/setup', async (route) => {
    expect(route.request().method()).toBe('POST');
    expect(route.request().postDataJSON()).toEqual({
      name: '管理员',
      email: 'owner@example.com',
      password: 'initial-password-123'
    });
    await route.fulfill({
      status: 201,
      json: {
        ok: true,
        data: {
          initialized: true,
          user: { name: '管理员', email: 'owner@example.com', role: 'admin' }
        }
      }
    });
  });

  await page.goto('/login');

  await expect(page).toHaveURL(/\/setup$/);
  await expect(page.getByRole('heading', { name: '创建你的管理账户' })).toBeVisible();
  await expect(page.getByLabel('账户名称')).toHaveCount(0);
  await page.getByRole('button', { name: '创建账户' }).click();
  await expect(page.getByRole('alert')).toHaveText('请输入登录邮箱');
  await expect(page.getByRole('alert')).toHaveClass(/bg-red-50/);
  await page.getByLabel('登录邮箱').fill('owner@example.com');
  await page.getByLabel('登录密码').fill('initial-password-123');
  await page.getByLabel('确认密码').fill('initial-password-123');
  await page.getByRole('button', { name: '创建账户' }).click();

  await expect(page.getByRole('heading', { name: '你的私人书库已准备好' })).toBeVisible();
  await expect(page.getByText('owner@example.com')).toBeVisible();
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
  await expect(page.getByRole('alert')).toHaveText('请输入登录密码');

  await page.getByLabel('密码').fill('wrong-password');
  await page.getByRole('button', { name: '登录' }).click();
  const alert = page.getByRole('alert');
  await expect(alert).toHaveText('邮箱或密码不正确');
  await expect(alert).toHaveClass(/bg-red-50/);
});

test('login recovers to setup when the initial status check was unavailable', async ({ page }) => {
  let statusRequests = 0;
  await page.route('**/api/auth/setup/status', async (route) => {
    statusRequests += 1;
    if (statusRequests === 1) {
      await route.fulfill({ status: 503, json: { ok: false, error: { message: '暂时不可用' } } });
      return;
    }
    await route.fulfill({ json: { ok: true, data: { initialized: false } } });
  });
  await page.route('**/api/auth/login', async (route) => {
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
