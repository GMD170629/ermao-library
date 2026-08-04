import assert from 'node:assert/strict';
import test from 'node:test';
import { createPwaUpdatePreparation } from './update-coordination';

test('PWA update preparation waits for every registered persistence task', async () => {
  const preparation = createPwaUpdatePreparation();
  const completed: string[] = [];
  preparation.detail.waitUntil(Promise.resolve().then(() => { completed.push('audio'); }));
  preparation.detail.waitUntil(Promise.resolve().then(() => { completed.push('reader'); }));

  await preparation.wait();
  assert.deepEqual(completed.sort(), ['audio', 'reader']);
});

test('a failed preparation task does not strand an already accepted app update', async () => {
  const preparation = createPwaUpdatePreparation();
  preparation.detail.waitUntil(Promise.reject(new Error('offline')));
  await assert.doesNotReject(preparation.wait());
});

test('a stalled preparation task is bounded by the forced-update timeout', async () => {
  const target = new EventTarget();
  target.addEventListener('shuku:before-pwa-update', (event) => {
    const detail = (event as CustomEvent<{ waitUntil(task: Promise<unknown>): void }>).detail;
    detail.waitUntil(new Promise(() => undefined));
  });
  const startedAt = Date.now();
  await import('./update-coordination').then(({ prepareForPwaUpdate }) =>
    prepareForPwaUpdate(target as unknown as Window, 10)
  );
  assert.ok(Date.now() - startedAt < 500);
});
