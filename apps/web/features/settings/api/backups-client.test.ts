import assert from 'node:assert/strict';
import test from 'node:test';
import { BackupApiError, backupDownloadUrl, backupErrorMessage, parseBackup, restoreBackup, uploadBackup } from './backups-client';

const backup = {
  id: '备份（1）', filename: '备份（1）.zip', name: '备份（1）.zip', createdAt: '2026-09-28T00:00:00Z', sizeBytes: 100,
  compatibility: { status: 'incompatible', problem: { code: 'BACKUP_DATABASE_MISMATCH', message: '旧数据库版本', messageEn: 'Old database revision', params: {} },
    formatVersion: '5', databaseRevision: 'old', requiredFormatVersion: '5', requiredDatabaseRevision: 'current' }
};

test('uploaded incompatible backup retains its stored identity and reason', async () => {
  const original = globalThis.fetch;
  globalThis.fetch = async (url, init) => {
    assert.equal(url, '/api/backups/upload');
    assert.ok(init?.body instanceof FormData);
    assert.equal(init.headers, undefined);
    return Response.json({ ok: true, data: { backup } }, { status: 201 });
  };
  try {
    const result = await uploadBackup(new File(['data'], '备份.zip'), new AbortController().signal);
    assert.equal(result.filename, '备份（1）.zip');
    assert.equal(result.compatibility.status, 'incompatible');
    assert.equal(result.compatibility.problem?.messageEn, 'Old database revision');
    assert.equal(backupDownloadUrl(result.id), `/api/backups/${encodeURIComponent('备份（1）')}/download`);
  } finally { globalThis.fetch = original; }
});

test('restore exposes the real bilingual error and diagnostic identifier', async () => {
  const original = globalThis.fetch;
  globalThis.fetch = async () => Response.json({ ok: false, error: { code: 'BACKUP_REQUIRED_FIELD', message: '缺少必填字段：User.id',
    params: { messageEn: 'Required field is missing: User.id' } } }, { status: 400, headers: { 'X-Error-Id': 'diag-test' } });
  try {
    await assert.rejects(restoreBackup(backup.id, new AbortController().signal), (error: unknown) => {
      assert.ok(error instanceof BackupApiError);
      assert.match(backupErrorMessage(error, 'zh-CN'), /User.id.*\n诊断编号: diag-test/);
      assert.match(backupErrorMessage(error, 'en-US'), /Required field is missing: User.id\nDiagnostic ID: diag-test/);
      return true;
    });
  } finally { globalThis.fetch = original; }
});

test('malformed compatibility cannot enable restoration', () => {
  assert.throws(() => parseBackup({ ...backup, compatibility: { ...backup.compatibility, status: 'compatible' } }), BackupApiError);
  assert.throws(() => parseBackup({ ...backup, compatibility: null }), BackupApiError);
});
