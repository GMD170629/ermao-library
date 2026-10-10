import assert from 'node:assert/strict';
import test, { beforeEach, afterEach } from 'node:test';
import { mkdtempSync, readFileSync, readdirSync, rmSync, mkdirSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { writeServerLog } from './server-exceptions';

let temporaryRoot: string;
let originalRoot: string | undefined;
beforeEach(() => {
  originalRoot = process.env.STORAGE_ROOT;
  temporaryRoot = mkdtempSync(join(tmpdir(), 'ermao-daily-logs-'));
  process.env.STORAGE_ROOT = temporaryRoot;
});
afterEach(() => {
  if (originalRoot === undefined) delete process.env.STORAGE_ROOT;
  else process.env.STORAGE_ROOT = originalRoot;
  rmSync(temporaryRoot, { recursive: true, force: true });
});

test('daily JSONL defaults to errors, retains full stacks and prunes only expired daily files', () => {
  const directory = join(temporaryRoot, 'logs', 'web');
  mkdirSync(directory, { recursive: true });
  writeFileSync(join(directory, '2000-01-01.jsonl'), 'old\n');
  writeFileSync(join(directory, 'keep.txt'), 'unrelated');
  writeServerLog('debug', 'debug');
  writeServerLog('info', 'info');
  writeServerLog('warning', 'warning');
  const traceback = 'raw token=test-secret /private/path\n'.repeat(30000);
  writeServerLog('error', 'original', { diagnostics: { traceback } });
  const files = readdirSync(directory).filter((name) => name.endsWith('.jsonl'));
  assert.equal(files.length, 1);
  const lines = readFileSync(join(directory, files[0]), 'utf8').trimEnd().split('\n');
  assert.equal(lines.length, 1);
  assert.equal(JSON.parse(lines[0]).metadata.diagnostics.traceback, traceback);
  assert.ok(readdirSync(directory).includes('keep.txt'));
  writeFileSync(join(temporaryRoot, 'logs', 'settings.json'), JSON.stringify({ retentionDays: 3, minimumLevel: 'debug' }));
  writeServerLog('debug', 'enabled');
  assert.equal(readFileSync(join(directory, files[0]), 'utf8').trimEnd().split('\n').length, 2);
});
import { installServerExceptionObserver, recordServerException } from './server-exceptions';

test('server exception entry preserves long errors, causes and every group member', (t) => {
  const messages: string[] = [];
  t.mock.method(process.stderr, 'write', (chunk: string) => { messages.push(chunk); return true; });
  const original = new Error(`password=test-value /private/book.epub\n${'原始错误'.repeat(20_000)}`);
  const wrapper = new Error('wrapper', { cause: original });
  const group = new AggregateError([wrapper, new Error('independent failure')], 'batch');
  recordServerException(group);
  recordServerException(group);
  assert.equal(messages.length, 1);
  assert.ok(messages[0].includes(original.stack!));
  assert.ok(messages[0].includes(wrapper.stack!));
  assert.ok(messages[0].includes('independent failure'));
});

test('a broken error formatter is recorded without replacing the caller result', (t) => {
  const messages: string[] = [];
  t.mock.method(process.stderr, 'write', (chunk: string) => { messages.push(chunk); return true; });
  const error = new Error('original');
  Object.defineProperty(error, 'stack', { get() { throw new TypeError('broken formatter'); } });
  assert.doesNotThrow(() => recordServerException(error));
  assert.ok(messages[0].includes('Error: original'));
  assert.ok(messages[0].includes('TypeError: broken formatter'));
});

test('server observer preserves deep stacks without replacing fatal exception handling', (t) => {
  const limit = Error.stackTraceLimit;
  const handlers = process.listeners('uncaughtException');
  t.after(() => {
    Error.stackTraceLimit = limit;
    process.removeListener('uncaughtExceptionMonitor', recordServerException);
  });
  installServerExceptionObserver();
  function deepFailure(depth: number): Error {
    return depth ? deepFailure(depth - 1) : new Error('deep original error');
  }
  const messages: string[] = [];
  t.mock.method(process.stderr, 'write', (chunk: string) => { messages.push(chunk); return true; });
  recordServerException(deepFailure(120));
  assert.equal(messages[0].split('at deepFailure').length - 1, 121);
  assert.deepEqual(process.listeners('uncaughtException'), handlers);
});
