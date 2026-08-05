import assert from 'node:assert/strict';
import test from 'node:test';
import { createScreenWakeLockController, type ScreenWakeLockPort } from './screen-wake-lock';

const flushAsyncWork = () => new Promise<void>((resolve) => setImmediate(resolve));

test('wake lock acquires while visible, releases in the background, and reacquires on return', async () => {
  let visibility: DocumentVisibilityState = 'visible';
  const listener: { current: (() => void) | null } = { current: null };
  let requests = 0;
  let releases = 0;
  const documentValue = {
    get visibilityState() { return visibility; },
    addEventListener: (_type: string, next: EventListenerOrEventListenerObject) => { listener.current = next as () => void; },
    removeEventListener: () => { listener.current = null; }
  } as unknown as Document;
  const port: ScreenWakeLockPort = {
    request: async () => {
      requests += 1;
      return { release: async () => { releases += 1; } };
    }
  };
  const controller = createScreenWakeLockController(documentValue, port);
  controller.start();
  await flushAsyncWork();
  assert.equal(requests, 1);
  visibility = 'hidden';
  listener.current?.();
  await flushAsyncWork();
  assert.equal(releases, 1);
  visibility = 'visible';
  listener.current?.();
  await flushAsyncWork();
  assert.equal(requests, 2);
  controller.stop();
  await flushAsyncWork();
  assert.equal(releases, 2);
});

test('wake lock request rejection never blocks the reader lifecycle', async () => {
  const documentValue = {
    visibilityState: 'visible',
    addEventListener: () => undefined,
    removeEventListener: () => undefined
  } as unknown as Document;
  const controller = createScreenWakeLockController(documentValue, { request: async () => { throw new Error('denied'); } });
  controller.start();
  await Promise.resolve();
  controller.stop();
});
