import assert from 'node:assert/strict';
import test from 'node:test';
import { parseContinueImportResult, parseImportLibraries, parseImportTaskDetail, parseImportTasksPage, parseLibraryImportTask } from './client';

const task = {
  id: 'task-1',
  kind: 'IMPORT_ASSET',
  libraryId: 'library-1',
  resourceId: 'resource-1',
  sourceNodeId: 'source-node-1',
  role: 'PRIMARY',
  state: 'FAILED',
  errorSummary: '解析失败',
  createdAt: '2026-08-22T00:00:00Z',
  startedAt: '2026-08-22T00:00:01Z',
  finishedAt: '2026-08-22T00:00:02Z'
};

test('parses the canonical LibraryImportTask identity and terminal state', () => {
  const parsed = parseLibraryImportTask(task);
  assert.equal(parsed.kind, 'IMPORT_ASSET');
  assert.equal(parsed.sourceNodeId, 'source-node-1');
  assert.equal(parsed.state, 'FAILED');
});

test('parses import task pagination and summary', () => {
  const page = parseImportTasksPage({
    tasks: [task],
    completed: 4,
    failed: 1,
    page: 2,
    pageSize: 10,
    total: 11,
    totalPages: 2
  });
  assert.equal(page.tasks[0]?.id, 'task-1');
  assert.deepEqual(page.summary, { completed: 4, failed: 1 });
  assert.equal(page.totalPages, 2);
});

test('parses canonical library selection and task detail envelopes', () => {
  assert.deepEqual(parseImportLibraries({ libraries: [{ id: 'library-1', name: '主书库', enabled: true }] }), [
    { id: 'library-1', name: '主书库', enabled: true }
  ]);
  assert.equal(parseImportTaskDetail({ task }).id, 'task-1');
});

test('parses ContinueImport result without queue-control fields', () => {
  const result = parseContinueImportResult({
    taskId: 'task-2',
    libraryId: 'library-1',
    sourceNodeId: 'source-node-1',
    requeuedFailed: 1,
    enqueued: true
  });
  assert.equal(result.taskId, 'task-2');
  assert.equal(result.requeuedFailed, 1);
  assert.equal(result.enqueued, true);
});

test('rejects retired import task states', () => {
  assert.throws(() => parseLibraryImportTask({ ...task, state: 'COMPLETED' }), /无效状态/);
});
