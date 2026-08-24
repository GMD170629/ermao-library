import { expect, test } from '@playwright/test';

test('an uninitialized installation opens the account setup wizard', async ({ page }) => {
  let accountCreated = false;
  let createdLibraries = 0;
  const activatedLibraries: string[] = [];
  const removedLibraries: string[] = [];
  const consoleErrors: string[] = [];
  await page.route('**/api/auth/setup/status', async (route) => {
    await route.fulfill({ json: { ok: true, data: { initialized: accountCreated } } });
  });
  await page.route('**/api/auth/setup', async (route) => {
    expect(route.request().method()).toBe('POST');
    expect(route.request().postDataJSON()).toEqual({
      name: '二毛',
      email: 'owner@example.com',
      password: 'initial-password-123',
      locale: 'zh-CN'
    });
    accountCreated = true;
    await route.fulfill({
      status: 201,
      headers: { 'Set-Cookie': 'shuku_session=e2e-session; Path=/; HttpOnly; SameSite=Lax' },
      json: {
        ok: true,
        data: {
          initialized: true,
          user: { name: '二毛', email: 'owner@example.com', role: 'admin' }
        }
      }
    });
  });
  await page.route('**/api/auth/me', async (route) => {
    await route.fulfill(accountCreated
      ? { json: { ok: true, data: { user: { name: '二毛', email: 'owner@example.com', role: 'admin' } } } }
      : { status: 401, json: { ok: false, error: { message: 'UNAUTHORIZED' } } });
  });
  await page.route('**/api/libraries', async (route) => {
    if (route.request().method() === 'GET') {
      await route.fulfill({ json: { ok: true, data: { libraries: [] } } });
      return;
    }
    expect(route.request().method()).toBe('POST');
    expect(route.request().postDataJSON()).toEqual({
      name: createdLibraries === 0 ? '电子书' : '漫画合集',
      rootPath: createdLibraries === 0 ? '/library' : '/comics',
      organizationMode: createdLibraries === 0 ? 'FLAT' : 'VOLUMES',
      enabled: false,
      ignorePatterns: '',
      ignoreHidden: true,
      minFileSizeBytes: 0
    });
    createdLibraries += 1;
    const index = createdLibraries;
    await route.fulfill({ status: 201, json: { ok: true, data: { library: { id: `folder-${index}`, name: index === 1 ? '电子书' : '漫画合集', rootPath: index === 1 ? '/library' : '/comics', organizationMode: index === 1 ? 'FLAT' : 'VOLUMES', enabled: false } } } });
  });
  await page.route('**/api/libraries/folder-*', async (route) => {
    if (route.request().method() === 'DELETE') {
      removedLibraries.push(route.request().url());
      await route.fulfill({ json: { ok: true, data: { deleted: true } } });
      return;
    }
    expect(route.request().method()).toBe('PATCH');
    expect(route.request().postDataJSON()).toEqual({ enabled: true });
    activatedLibraries.push(route.request().url());
    await route.fulfill({ json: { ok: true, data: { library: {} } } });
  });
  await page.route('**/api/libraries/tree**', async (route) => {
    const requestedPath = new URL(route.request().url()).searchParams.get('path');
    if (requestedPath === '/missing/path') {
      await route.fulfill({ status: 404, json: { ok: false, error: { message: '路径不存在' } } });
      return;
    }
    if (requestedPath === '/home') {
      await route.fulfill({ json: { ok: true, data: { node: { name: 'home', path: '/home', readable: true, error: null, children: [{ name: 'liumianti', path: '/home/liumianti', readable: true }, { name: 'liufeng', path: '/home/liufeng', readable: true }, { name: 'Android', path: '/home/Android', readable: true }] } } } });
      return;
    }
    await route.fulfill({
      json: {
        ok: true,
        data: {
          node: requestedPath === '/library' || requestedPath === '/comics'
            ? { name: requestedPath.slice(1), path: requestedPath, readable: true, error: null, children: [] }
            : { name: '/', path: '/', readable: true, error: null, children: [{ name: 'home', path: '/home', readable: true }, { name: 'library', path: '/library', readable: true }, { name: 'comics', path: '/comics', readable: true }] },
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
  page.on('console', (message) => { if (message.type() === 'error') consoleErrors.push(message.text()); });

  await expect(page.getByRole('heading', { name: '添加书库' })).toBeVisible();
  const emptyLibraryList = page.getByRole('region', { name: '书库清单' });
  const initialAddButton = emptyLibraryList.getByRole('button', { name: /添加书库/ });
  const emptyListBox = await emptyLibraryList.boundingBox();
  const initialAddButtonBox = await initialAddButton.boundingBox();
  expect(initialAddButtonBox?.width).toBeGreaterThanOrEqual(176);
  expect(initialAddButtonBox?.height).toBeGreaterThanOrEqual(176);
  expect(Math.abs((initialAddButtonBox?.x ?? 0) + (initialAddButtonBox?.width ?? 0) / 2 - ((emptyListBox?.x ?? 0) + (emptyListBox?.width ?? 0) / 2))).toBeLessThan(2);
  await initialAddButton.click();
  const addDialog = page.getByRole('dialog', { name: '新增书库' });
  await expect(addDialog).toBeVisible();
  await expect(addDialog.getByText(/快速检查/)).toHaveCount(0);
  await expect(page.getByText('识别说明')).toHaveCount(0);
  await expect(addDialog.getByRole('radio', { checked: true })).toHaveCount(0);
  await expect(addDialog).toHaveCSS('overflow-y', 'visible');
  await page.getByLabel('书库名称').fill('电子书');
  const folderPath = page.getByRole('combobox', { name: '书库路径' });
  await folderPath.fill('/home/liu');
  await expect(page.locator('[data-directory-path="/home"]')).toHaveAttribute('aria-selected', 'false');
  await expect(page.locator('[data-directory-path="/home/liumianti"]')).toBeVisible();
  await expect(page.locator('[data-directory-path="/home/liufeng"]')).toBeVisible();
  await expect(page.locator('[data-directory-path="/home/Android"]')).toHaveCount(0);
  await folderPath.fill('/missing/path');
  await expect(addDialog.getByText('路径不存在')).toBeVisible();
  consoleErrors.length = 0;
  await folderPath.fill('/library');
  const directoryTree = page.getByRole('tree');
  const selectedLibrary = page.locator('[data-directory-path="/library"]');
  await expect(selectedLibrary).toHaveAttribute('aria-selected', 'true');
  await expect(selectedLibrary).toBeInViewport();
  const treeBox = await directoryTree.boundingBox();
  const selectedLibraryBox = await selectedLibrary.boundingBox();
  expect((selectedLibraryBox?.y ?? 0) - (treeBox?.y ?? 0)).toBeLessThan(20);
  const dialogBox = await addDialog.boundingBox();
  const treePanelBox = await directoryTree.locator('..').boundingBox();
  expect((treePanelBox?.y ?? 0) + (treePanelBox?.height ?? 0)).toBeLessThanOrEqual((dialogBox?.y ?? 0) + (dialogBox?.height ?? 0) + 1);
  await page.getByRole('button', { name: '收起文件夹路径树' }).click();
  await addDialog.getByRole('button', { name: '添加', exact: true }).click();
  await expect(addDialog.getByRole('alert')).toHaveText('请选择文件组织方式');
  const organizationModes = page.getByRole('radiogroup', { name: '组织方式' });
  const modeBoxes = await Promise.all(['单本', '分卷'].map((name) => addDialog.getByRole('radio', { name }).boundingBox()));
  expect(modeBoxes[0]?.y).toBe(modeBoxes[1]?.y);
  await expect(addDialog.getByText('下级目录作为图书，一个图书可能有多个分卷')).toBeVisible();
  await page.getByRole('button', { name: '展开文件夹路径树' }).click();
  await expect(selectedLibrary).toHaveAttribute('aria-selected', 'true');
  await expect(selectedLibrary).toBeInViewport();
  await page.getByRole('button', { name: '收起文件夹路径树' }).click();
  await page.getByRole('radio', { name: '单本' }).click();
  await addDialog.getByRole('button', { name: '添加', exact: true }).click();

  await expect(page.getByRole('dialog', { name: '新增书库' })).toHaveCount(0);
  await expect(page.getByText('电子书')).toBeVisible();
  await page.getByRole('button', { name: /添加书库/ }).click();
  await expect(page.getByRole('dialog', { name: '新增书库' }).getByRole('radio', { checked: true })).toHaveCount(0);
  await page.getByLabel('书库名称').fill('漫画合集');
  await page.getByRole('combobox', { name: '书库路径' }).fill('/comics');
  await page.getByRole('button', { name: '收起文件夹路径树' }).click();
  await page.getByRole('radio', { name: '分卷' }).click();
  await page.getByRole('dialog', { name: '新增书库' }).getByRole('button', { name: '添加', exact: true }).click();

  await expect(page.getByText('漫画合集')).toBeVisible();
  const mangaLibraryRow = page.locator('article').filter({ hasText: '漫画合集' });
  await mangaLibraryRow.getByRole('button', { name: '移除书库' }).click();
  expect(removedLibraries).toHaveLength(1);
  await expect(page.getByText('漫画合集')).toHaveCount(0);
  await page.getByRole('button', { name: /添加书库/ }).click();
  await page.getByLabel('书库名称').fill('漫画合集');
  await page.getByRole('combobox', { name: '书库路径' }).fill('/comics');
  await page.getByRole('button', { name: '收起文件夹路径树' }).click();
  await page.getByRole('radio', { name: '分卷' }).click();
  await page.getByRole('dialog', { name: '新增书库' }).getByRole('button', { name: '添加', exact: true }).click();
  expect(consoleErrors).toEqual([]);
  await page.getByRole('button', { name: '确认' }).click();

  await expect(page).toHaveURL(/\/library$/);
  expect(activatedLibraries).toHaveLength(2);
  await expect(page.getByRole('heading', { name: '你的私人书库已准备好' })).toHaveCount(0);
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
      stage: 'library',
      email: 'owner@example.com',
      libraries: []
    }));
  });
  await page.route('**/api/auth/setup/status', async (route) => {
    await route.fulfill({ json: { ok: true, data: { initialized: true } } });
  });
  await page.route('**/api/auth/me', async (route) => {
    await route.fulfill({ json: { ok: true, data: { user: { email: 'owner@example.com' } } } });
  });

  await page.goto('/setup');
  await page.context().addCookies([{ name: 'shuku_session', value: 'e2e-session', url: new URL(page.url()).origin }]);

  await expect(page.getByRole('heading', { name: '添加书库' })).toBeVisible();
  const skipButton = page.getByRole('button', { name: '跳过' });
  await expect(skipButton).toHaveCSS('text-decoration-line', 'underline');
  await skipButton.hover();
  await expect(skipButton).toHaveCSS('color', 'rgb(196, 61, 47)');
  await skipButton.click();
  const skipConfirmation = page.getByRole('alertdialog', { name: '确认跳过添加书库？' });
  await expect(skipConfirmation).toBeVisible();
  await skipConfirmation.getByRole('button', { name: '返回添加' }).click();
  await expect(skipConfirmation).toHaveCount(0);
  await page.getByRole('button', { name: /添加书库/ }).click();
  await expect(page.getByRole('dialog', { name: '新增书库' })).toBeVisible();
  await expect(page.getByRole('combobox', { name: '书库路径' })).toHaveValue('');
  await page.getByRole('dialog', { name: '新增书库' }).getByRole('button', { name: '关闭' }).click();
  await page.getByRole('button', { name: '跳过' }).click();
  await page.getByRole('alertdialog', { name: '确认跳过添加书库？' }).getByRole('button', { name: '确认跳过' }).click();
  await expect(page).toHaveURL(/\/library$/);
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
