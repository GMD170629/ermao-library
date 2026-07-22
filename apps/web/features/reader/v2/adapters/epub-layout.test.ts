import assert from 'node:assert/strict';
import test from 'node:test';
import { EpubLayoutCoordinator, preserveEpubImageDimensions, waitForEpubLayoutBarrier } from './epub-layout';

function deferred() {
  let resolve!: () => void;
  const promise = new Promise<void>((done) => { resolve = done; });
  return { promise, resolve };
}

test('EPUB layout coordinator drops queued obsolete layouts before they mutate the rendition', async () => {
  const coordinator = new EpubLayoutCoordinator();
  const gate = deferred();
  const calls: string[] = [];
  const navigation = coordinator.enqueueNavigation(async () => {
    calls.push('navigation:start');
    await gate.promise;
    calls.push('navigation:end');
  });
  const stale = coordinator.enqueueLayout(async () => { calls.push('layout:stale'); });
  const current = coordinator.enqueueLayout(async () => { calls.push('layout:current'); });

  gate.resolve();
  await Promise.all([navigation, stale.promise, current.promise]);

  assert.deepEqual(calls, ['navigation:start', 'navigation:end', 'layout:current']);
  assert.equal(await stale.promise, false);
  assert.equal(await current.promise, true);
});

test('EPUB navigation cannot enter while an active layout transaction owns the rendition', async () => {
  const coordinator = new EpubLayoutCoordinator();
  const gate = deferred();
  const started = deferred();
  const calls: string[] = [];
  const layout = coordinator.enqueueLayout(async () => {
    calls.push('layout:start');
    started.resolve();
    await gate.promise;
    calls.push('layout:end');
  });
  const navigation = coordinator.enqueueNavigation(async () => { calls.push('navigation'); });

  await started.promise;
  assert.deepEqual(calls, ['layout:start']);
  gate.resolve();
  await Promise.all([layout.promise, navigation]);
  assert.deepEqual(calls, ['layout:start', 'layout:end', 'navigation']);
});

test('EPUB layout epochs serialize an active restore before the newest layout starts', async () => {
  const coordinator = new EpubLayoutCoordinator();
  const gate = deferred();
  const started = deferred();
  const calls: string[] = [];
  const active = coordinator.enqueueLayout(async () => {
    calls.push('old:capture');
    started.resolve();
    await gate.promise;
    calls.push('old:restore');
  });
  await started.promise;
  const newest = coordinator.enqueueLayout(async () => { calls.push('new:layout'); });

  gate.resolve();
  await Promise.all([active.promise, newest.promise]);
  assert.deepEqual(calls, ['old:capture', 'old:restore', 'new:layout']);
});

test('EPUB image stabilization backfills intrinsic placeholders without replacing authored dimensions', () => {
  const attributes = new Map<string, string>([['width', '320']]);
  const image = {
    naturalWidth: 640,
    naturalHeight: 480,
    style: { aspectRatio: '' },
    hasAttribute: (name: string) => attributes.has(name),
    setAttribute: (name: string, value: string) => attributes.set(name, value)
  } as unknown as HTMLImageElement;

  preserveEpubImageDimensions(image);

  assert.equal(attributes.get('width'), '320');
  assert.equal(attributes.get('height'), '480');
  assert.equal(image.style.aspectRatio, '640 / 480');
});

test('EPUB resource barrier releases immediately when the reader lifecycle aborts', async () => {
  const controller = new AbortController();
  const document = {
    fonts: { ready: new Promise<void>(() => undefined) },
    querySelectorAll: () => []
  } as unknown as Document;
  const barrier = waitForEpubLayoutBarrier([document], controller.signal);

  controller.abort();
  await assert.rejects(barrier, (reason: unknown) => reason instanceof DOMException && reason.name === 'AbortError');
});

test('EPUB resource barrier has a bounded fallback for assets that never settle', async () => {
  const document = {
    fonts: { ready: new Promise<void>(() => undefined) },
    querySelectorAll: () => []
  } as unknown as Document;

  await waitForEpubLayoutBarrier([document], undefined, 5);
});
