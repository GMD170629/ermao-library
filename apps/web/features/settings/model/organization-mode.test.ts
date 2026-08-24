import assert from 'node:assert/strict';
import test from 'node:test';
import { ORGANIZATION_MODES } from './organization-mode';

test('only the two ADR 0018 organization modes are public', () => {
  assert.deepEqual(ORGANIZATION_MODES.map((mode) => mode.value), ['FLAT', 'VOLUMES']);
});

test('organization modes use the user-facing single-book and volume language', () => {
  assert.deepEqual(
    ORGANIZATION_MODES.map(({ label, description }) => ({ label, description })),
    [
      { label: '单本', description: '所有支持文件均独立成书，递归遍历任意目录层级' },
      { label: '分卷', description: '下级目录作为图书，一个图书可能有多个分卷' }
    ]
  );
});
