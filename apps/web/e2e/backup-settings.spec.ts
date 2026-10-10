import { expect, test } from '@playwright/test';

for (const locale of ['zh-CN', 'en-US']) {
  test(`backup uploads, compatibility and restore failure details (${locale})`, async ({ page }) => {
    const en = locale === 'en-US';
    await page.context().addCookies([{ name: 'shuku_session', value: 'backup-test-session', domain: '127.0.0.1', path: '/' }]);
    const compatible = { id: 'backup', name: 'backup.zip', filename: 'backup.zip', kind: 'manual', sizeBytes: 100,
      createdAt: '2026-09-28T00:00:00Z', counts: {}, compatibility: { status: 'compatible', problem: null,
        formatVersion: '5', databaseRevision: 'current', requiredFormatVersion: '5', requiredDatabaseRevision: 'current' } };
    const incompatible = { ...compatible, id: 'old', name: 'old.zip', filename: 'old.zip', compatibility: {
      ...compatible.compatibility, status: 'incompatible', databaseRevision: 'old', problem: {
        code: 'BACKUP_DATABASE_MISMATCH', message: '备份数据库结构版本为 old，当前要求 current',
        messageEn: 'Backup database revision is old; this application requires current', params: { actual: 'old', expected: 'current' } } } };
    const archives = [compatible, incompatible];
    let uploads = 0;
    let restores = 0;
    await page.route('**/api/**', async (route) => {
      const path = new URL(route.request().url()).pathname;
      if (path === '/api/auth/me') {
        await route.fulfill({ json: { ok: true, data: { user: { id: 'admin', email: 'backup@example.com', name: 'Backup admin', role: 'admin', locale },
          authorization: { isAdmin: true, canManageSystem: true, authzVersion: 1 } } } });
      } else if (path === '/api/backups/upload') {
        uploads++;
        const uploaded = { ...incompatible, id: 'old（1）', name: 'old（1）.zip', filename: 'old（1）.zip' };
        archives.push(uploaded);
        await route.fulfill({ status: 201, json: { ok: true, data: { backup: uploaded } } });
      } else if (path === '/api/backups') {
        await route.fulfill({ json: { ok: true, data: { backups: archives } } });
      } else if (path.endsWith('/restore')) {
        restores++;
        await route.fulfill({ status: 400, json: { ok: false,
          error: { code: 'BACKUP_REQUIRED_FIELD', message: '验证备份数据：缺少必填字段：User.id',
            params: { messageEn: 'Validate backup data: Required field is missing: User.id' } } } });
      } else {
        await route.fulfill({ json: { ok: true, data: { shelves: [], settings: {}, libraries: [] } } });
      }
    });
    await page.goto('/settings/data');
    await expect(page.getByText(en ? /Restoration in future versions is not guaranteed/ : /不保证未来版本能够恢复此备份/)).toBeVisible();
    const oldRow = page.locator('div.flex.flex-col').filter({ has: page.getByText('old.zip', { exact: true }) }).last();
    await expect(oldRow.getByRole('button', { name: en ? 'Restore' : '恢复', exact: true })).toBeDisabled();
    await expect(page.getByText(en ? 'Backup database revision is old; this application requires current' : '备份数据库结构版本为 old，当前要求 current', { exact: true })).toBeVisible();
    await page.locator('input[type=file]').setInputFiles({ name: 'old.zip', mimeType: 'application/zip', buffer: Buffer.from('test upload') });
    await expect(page.getByText('old（1）.zip', { exact: true })).toBeVisible();
    expect(uploads).toBe(1);
    const goodRow = page.locator('div.flex.flex-col').filter({ has: page.getByText('backup.zip', { exact: true }) }).last();
    page.on('dialog', (dialog) => dialog.accept('RESTORE'));
    await goodRow.getByRole('button', { name: en ? 'Restore' : '恢复', exact: true }).click();
    await page.getByRole('button', { name: en ? 'Continue Restore' : '继续恢复', exact: true }).click();
    await expect(page.getByTestId('app-shell-content').getByRole('alert')).toContainText('User.id');
    await expect(page.getByTestId('app-shell-content').getByRole('alert')).not.toContainText('diag-backup-test');
    expect(restores).toBe(1);
  });
}
