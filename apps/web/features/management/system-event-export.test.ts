import assert from 'node:assert/strict';
import test from 'node:test';
import { translateMessage } from '../../i18n/messages';
import type { ManagementEvent } from './api/events';
import { systemEventsCsv } from './system-event-export';

const event: ManagementEvent = {
  id: 'event-1', createdAt: '2026-09-26T12:00:00Z', level: 'error', source: 'system',
  actorType: 'system', action: 'operation.failed_before_cleanup',
  targetType: 'importTask', targetId: 'task-1', message: 'TXT metadata failed',
  metadata: {
    taskId: 'task-1', stage: 'local_metadata',
    diagnostics: {
      id: 'diag-1', exceptionType: 'ValueError', causeStatus: 'PROVIDED',
      rootCause: { type: 'OSError', errno: 5, message: 'read failed' },
      chain: [{ type: 'ValueError' }, { type: 'OSError', errno: 5 }],
      traceback: 'Traceback\n  File "reader.py", line 4\nOSError: read failed',
      databaseOperations: [{ statement: 'UPDATE books SET title = ?', parameters: ['a,"b"\nc'] }],
    },
  },
};

function quoted(value: unknown) {
  return `"${JSON.stringify(value).replaceAll('"', '""')}"`;
}

test('export retains original summaries, complete SQL, chains and all metadata', () => {
  const csv = systemEventsCsv([event], 'zh-CN', (key) => translateMessage('zh-CN', key));
  assert.ok(csv.startsWith('\uFEFF"时间"'));
  assert.ok(csv.includes(quoted(event.metadata)));
  assert.ok(csv.includes('"TXT metadata failed"'));
  assert.ok(csv.includes('"diag-1"'));
  assert.ok(csv.includes('"local_metadata"'));
  assert.ok(csv.includes('"task-1"'));
  assert.ok(csv.includes('File ""reader.py"", line 4'));
});

test('English export translates headers and levels, never error evidence', () => {
  const csv = systemEventsCsv([event], 'en-US', (key) => translateMessage('en-US', key));
  const header = csv.split('\r\n')[0];
  assert.doesNotMatch(header, /[\u3400-\u9fff]/u);
  assert.ok(header.includes('"Root cause"'));
  assert.ok(csv.includes('"Error"'));
  assert.ok(csv.includes(quoted(event.metadata)));
});

test('legacy events explicitly lack diagnostics and formula cells stay literal', () => {
  const csv = systemEventsCsv([{ ...event, message: '=1+1', metadata: {} }], 'en-US', (key) => key);
  assert.ok(csv.includes('"NOT_RECORDED"'));
  assert.ok(csv.includes('"\'=1+1"'));
  assert.ok(csv.includes('"{}"'));
});
