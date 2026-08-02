import assert from 'node:assert/strict';
import test from 'node:test';
import { ReaderNavigationIntentQueue } from './use-reader-session';

function deferred() {
  let resolve!: () => void;
  const promise = new Promise<void>((complete) => {
    resolve = complete;
  });
  return { promise, resolve };
}

async function flush() {
  await Promise.resolve();
  await Promise.resolve();
}

test('navigation tokens are allocated at dequeue and every successful intermediate location is admitted', async () => {
  const queue = new ReaderNavigationIntentQueue();
  const firstGate = deferred();
  const allocatedTokens: number[] = [];
  const admittedPages: number[] = [];
  let activeSequence = 0;
  let page = 1;

  const navigate = (wait?: Promise<void>) => queue.enqueue(async () => {
    const sequence = ++activeSequence;
    allocatedTokens.push(sequence);
    if (wait) await wait;
    if (page >= 3) return false;
    page += 1;
    // Mirrors useReaderSession's event admission while this operation is active.
    if (sequence === activeSequence) admittedPages.push(page);
    return true;
  });

  const first = navigate(firstGate.promise);
  const second = navigate();
  const beyondBoundary = navigate();

  await flush();
  assert.deepEqual(allocatedTokens, [1]);
  assert.deepEqual(admittedPages, []);

  firstGate.resolve();
  assert.deepEqual(await Promise.all([first, second, beyondBoundary]), [true, true, false]);
  assert.deepEqual(allocatedTokens, [1, 2, 3]);
  assert.deepEqual(admittedPages, [2, 3]);
  assert.equal(page, 3);
});

test('reset invalidates queued navigation work from a closing adapter session', async () => {
  const queue = new ReaderNavigationIntentQueue();
  const firstGate = deferred();
  const calls: string[] = [];

  const first = queue.enqueue(async () => {
    calls.push('first');
    await firstGate.promise;
    return true;
  });
  const stale = queue.enqueue(async () => {
    calls.push('stale');
    return true;
  });

  await flush();
  queue.reset();
  const nextSession = queue.enqueue(async () => {
    calls.push('next-session');
    return true;
  });
  firstGate.resolve();

  assert.equal(await first, false);
  assert.equal(await stale, false);
  assert.equal(await nextSession, true);
  assert.deepEqual(calls, ['first', 'next-session']);
});
