import assert from 'node:assert/strict';
import test from 'node:test';
import { ignoredImportEventSummary } from './system-event-presentation';

function translate(
  message: string,
  values: Record<string, string | number> = {},
) {
  return Object.entries(values).reduce(
    (result, [key, value]) => result.replace(`{${key}}`, String(value)),
    message,
  );
}

test('ignored import events expose the file and localized rule reason', () => {
  assert.equal(
    ignoredImportEventSummary(
      {
        action: 'scan.file.ignored',
        metadata: {
          sourceName: 'draft.epub',
          reason: 'global_ignore_pattern',
        },
      },
      translate,
    ),
    '导入规则忽略文件：draft.epub（原因：全局忽略规则）',
  );
});

test('other system event types keep their stored summary', () => {
  assert.equal(
    ignoredImportEventSummary(
      { action: 'import.completed', metadata: {} },
      translate,
    ),
    null,
  );
});
