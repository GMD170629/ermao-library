import assert from 'node:assert/strict';
import test from 'node:test';
import { PagedTrackController } from './paged-track-controller';
import type {
  PageStep,
  PageTrackTarget,
  PagedTrackClock,
  PagedTrackDriver,
  PagedTrackDriverSnapshot
} from './paged-track-types';

function deferred() {
  let resolve!: () => void;
  const promise = new Promise<void>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

function abortError() {
  return new DOMException('The operation was aborted', 'AbortError');
}

function abortable(promise: Promise<void>, signal: AbortSignal) {
  if (signal.aborted) return Promise.reject(abortError());
  return new Promise<void>((resolve, reject) => {
    const abort = () => {
      cleanup();
      reject(abortError());
    };
    const cleanup = () => signal.removeEventListener('abort', abort);
    signal.addEventListener('abort', abort, { once: true });
    promise.then(() => {
      cleanup();
      resolve();
    }, (reason) => {
      cleanup();
      reject(reason);
    });
  });
}

async function flush() {
  await new Promise<void>((resolve) => setImmediate(resolve));
}

class FakeDriver implements PagedTrackDriver {
  state: PagedTrackDriverSnapshot = {
    readingDirection: 'ltr',
    viewportWidth: 400,
    hasPrevious: true,
    hasNext: true,
    reducedMotion: false
  };
  prepareReady = true;
  calls: string[] = [];
  offsets: number[] = [];
  animations: Array<{ target: PageTrackTarget; durationMs: number }> = [];
  promotions: PageStep[] = [];
  animateGates: Promise<void>[] = [];
  promoteGates: Promise<void>[] = [];

  snapshot() {
    return { ...this.state };
  }

  async prepare(step: PageStep, signal: AbortSignal) {
    this.calls.push('prepare:' + step);
    if (signal.aborted) throw abortError();
    return this.prepareReady;
  }

  setLogicalOffset(offsetPx: number) {
    this.offsets.push(offsetPx);
    this.calls.push('offset:' + Math.round(offsetPx));
  }

  async animateTo(target: PageTrackTarget, durationMs: number, signal: AbortSignal) {
    this.animations.push({ target, durationMs });
    this.calls.push('animate:' + target);
    const gate = this.animateGates.shift();
    if (gate) await abortable(gate, signal);
    else if (signal.aborted) throw abortError();
  }

  async promote(step: PageStep, signal: AbortSignal) {
    this.promotions.push(step);
    this.calls.push('promote:' + step);
    const gate = this.promoteGates.shift();
    if (gate) await abortable(gate, signal);
    else if (signal.aborted) throw abortError();
  }

  recenter() {
    this.calls.push('recenter');
  }

  cancel() {
    this.calls.push('cancel');
  }
}

class ManualClock implements PagedTrackClock {
  private sequence = 0;
  private tasks = new Map<number, () => void>();

  now() {
    return 0;
  }

  setTimeout(callback: () => void) {
    const id = ++this.sequence;
    this.tasks.set(id, callback);
    return id as unknown as ReturnType<typeof setTimeout>;
  }

  clearTimeout(handle: ReturnType<typeof setTimeout>) {
    this.tasks.delete(handle as unknown as number);
  }

  runAll() {
    const tasks = Array.from(this.tasks.values());
    this.tasks.clear();
    tasks.forEach((task) => task());
  }
}

function pointer(pointerId: number, clientX: number, clientY: number, timeMs: number) {
  return { pointerId, clientX, clientY, timeMs, isPrimary: true };
}

test('a claimed gesture stays visual until its session-authorized pending command is accepted', async () => {
  const driver = new FakeDriver();
  const requests: Array<{ gestureId: number; step: PageStep }> = [];
  const controller = new PagedTrackController(driver, {
    requestCommit: (request) => {
      requests.push(request);
    }
  });

  assert.equal(controller.pointerDown(pointer(1, 300, 100, 0)).phase, 'priming');
  const moved = controller.pointerMove(pointer(1, 180, 102, 400));
  assert.equal(moved.claimed, true);
  assert.equal(moved.preventDefault, true);
  assert.equal(moved.logicalOffsetPx, 120);

  const release = await controller.pointerUp(pointer(1, 180, 102, 410));
  assert.equal(release.kind, 'commit-requested');
  assert.equal(controller.snapshot().phase, 'awaiting-command');
  assert.equal(controller.getPendingStep(), 1);
  assert.deepEqual(requests, [{ gestureId: 1, step: 1 }]);
  assert.equal(driver.promotions.length, 0);
  assert.equal(driver.animations.length, 0);

  const promoteGate = deferred();
  driver.promoteGates.push(promoteGate.promise);
  const accepted = controller.acceptPending(1, {
    gestureId: release.kind === 'commit-requested' ? release.gestureId : undefined
  });
  await flush();
  assert.equal(controller.snapshot().phase, 'reconciling');
  assert.deepEqual(driver.animations.map((animation) => animation.target), [1]);
  assert.deepEqual(driver.promotions, [1]);

  promoteGate.resolve();
  assert.equal(await accepted, true);
  assert.equal(controller.snapshot().phase, 'idle');
  assert.equal(controller.snapshot().logicalOffsetPx, 0);
  assert.equal(driver.calls.at(-1), 'recenter');
});

test('small movement is a tap, while an insufficient claimed drag animates back without promotion', async () => {
  const driver = new FakeDriver();
  const controller = new PagedTrackController(driver);

  controller.pointerDown(pointer(1, 100, 100, 0));
  assert.deepEqual(await controller.pointerUp(pointer(1, 104, 102, 20)), {
    kind: 'tap',
    claimed: false,
    logicalOffsetPx: 0
  });

  controller.pointerDown(pointer(2, 300, 100, 100));
  controller.pointerMove(pointer(2, 240, 100, 400));
  const release = await controller.pointerUp(pointer(2, 240, 100, 410));
  assert.equal(release.kind, 'rollback');
  assert.equal(release.kind === 'rollback' ? release.reason : null, 'insufficient');
  assert.deepEqual(driver.animations.map((animation) => animation.target), [0]);
  assert.equal(driver.promotions.length, 0);
  assert.equal(controller.snapshot().phase, 'idle');
});

test('vertical movement is released to browser scrolling and never moves the track', async () => {
  const driver = new FakeDriver();
  const controller = new PagedTrackController(driver);

  controller.pointerDown(pointer(1, 100, 100, 0));
  const movement = controller.pointerMove(pointer(1, 106, 130, 20));
  assert.equal(movement.handled, false);
  assert.equal(movement.claimed, false);
  assert.equal(movement.preventDefault, false);
  assert.equal(controller.snapshot().phase, 'idle');
  assert.equal((await controller.pointerUp(pointer(1, 106, 130, 30))).kind, 'ignored');
  assert.equal(driver.offsets.length, 0);
});

test('LTR and RTL physical swipes produce the same positive logical next offset', async () => {
  const ltrDriver = new FakeDriver();
  const ltr = new PagedTrackController(ltrDriver);
  ltr.pointerDown(pointer(1, 300, 0, 0));
  ltr.pointerMove(pointer(1, 180, 0, 400));
  const ltrRelease = await ltr.pointerUp(pointer(1, 180, 0, 410));

  const rtlDriver = new FakeDriver();
  rtlDriver.state.readingDirection = 'rtl';
  const rtl = new PagedTrackController(rtlDriver);
  rtl.pointerDown(pointer(1, 100, 0, 0));
  rtl.pointerMove(pointer(1, 220, 0, 400));
  const rtlRelease = await rtl.pointerUp(pointer(1, 220, 0, 410));

  assert.equal(ltrDriver.offsets.at(-1), 120);
  assert.equal(rtlDriver.offsets.at(-1), 120);
  assert.equal(ltrRelease.kind === 'commit-requested' ? ltrRelease.step : null, 1);
  assert.equal(rtlRelease.kind === 'commit-requested' ? rtlRelease.step : null, 1);
  await ltr.rejectPending();
  await rtl.rejectPending();
});

test('a gesture keeps the availability captured at its committed anchor', async () => {
  const driver = new FakeDriver();
  const controller = new PagedTrackController(driver);

  controller.pointerDown(pointer(1, 360, 0, 0));
  controller.pointerMove(pointer(1, 120, 0, 300));
  driver.state.hasNext = false;
  controller.pointerMove(pointer(1, 40, 0, 400));

  assert.equal(driver.offsets.at(-1), 320);
  const release = await controller.pointerUp(pointer(1, 40, 0, 410));
  assert.equal(driver.offsets.at(-1), 320);
  assert.equal(release.kind === 'commit-requested' ? release.step : null, 1);
  await controller.rejectPending();
});

test('a quick short fling commits, while a strong terminal reversal rolls back', async () => {
  const flingDriver = new FakeDriver();
  const fling = new PagedTrackController(flingDriver);
  fling.pointerDown(pointer(1, 300, 0, 0));
  fling.pointerMove(pointer(1, 260, 0, 40));
  const flingRelease = await fling.pointerUp(pointer(1, 260, 0, 41));
  assert.equal(flingRelease.kind === 'commit-requested' ? flingRelease.step : null, 1);
  await fling.rejectPending();

  const reverseDriver = new FakeDriver();
  const reverse = new PagedTrackController(reverseDriver);
  reverse.pointerDown(pointer(1, 300, 0, 0));
  reverse.pointerMove(pointer(1, 140, 0, 200));
  reverse.pointerMove(pointer(1, 200, 0, 240));
  const reverseRelease = await reverse.pointerUp(pointer(1, 200, 0, 241));
  assert.equal(reverseRelease.kind, 'rollback');
  assert.equal(reverseRelease.kind === 'rollback' ? reverseRelease.reason : null, 'reverse-velocity');
  assert.equal(reverseDriver.promotions.length, 0);
});

test('a missing or unprepared neighbor can only rubber-band and return to the committed anchor', async () => {
  const boundaryDriver = new FakeDriver();
  boundaryDriver.state.hasNext = false;
  const boundary = new PagedTrackController(boundaryDriver);
  boundary.pointerDown(pointer(1, 300, 0, 0));
  const movement = boundary.pointerMove(pointer(1, 0, 0, 400));
  assert.ok(movement.logicalOffsetPx > 0 && movement.logicalOffsetPx < 60);
  await boundary.pointerUp(pointer(1, 0, 0, 410));
  assert.equal(boundaryDriver.calls.some((call) => call === 'prepare:1'), false);
  assert.deepEqual(boundaryDriver.animations.map((animation) => animation.target), [0]);

  const unavailableDriver = new FakeDriver();
  unavailableDriver.prepareReady = false;
  const unavailable = new PagedTrackController(unavailableDriver);
  unavailable.pointerDown(pointer(1, 300, 0, 0));
  unavailable.pointerMove(pointer(1, 180, 0, 400));
  const unavailableRelease = await unavailable.pointerUp(pointer(1, 180, 0, 410));
  assert.equal(unavailableRelease.kind, 'rollback');
  assert.equal(unavailableRelease.kind === 'rollback' ? unavailableRelease.reason : null, 'prepare-failed');
  assert.deepEqual(unavailableDriver.animations.map((animation) => animation.target), [0]);
  assert.equal(unavailableDriver.promotions.length, 0);
});

test('an opted-in next boundary requests a session command after rubber-banding', async () => {
  const driver = new FakeDriver();
  driver.state.hasNext = false;
  const commits: PageStep[] = [];
  const controller = new PagedTrackController(driver, {
    boundaryCommitSteps: [1],
    requestCommit: ({ step }) => { commits.push(step); }
  });

  controller.pointerDown(pointer(1, 300, 0, 0));
  controller.pointerMove(pointer(1, 0, 0, 400));
  const release = await controller.pointerUp(pointer(1, 0, 0, 410));
  await flush();

  assert.equal(release.kind, 'rollback');
  assert.deepEqual(commits, [1]);
  assert.deepEqual(driver.animations.map((animation) => animation.target), [0]);
  assert.equal(driver.promotions.length, 0);

  controller.pointerDown(pointer(2, 300, 0, 500));
  controller.pointerMove(pointer(2, 100, 0, 700));
  controller.pointerMove(pointer(2, 240, 0, 730));
  await controller.pointerUp(pointer(2, 240, 0, 731));
  await flush();
  assert.deepEqual(commits, [1]);
});

test('a mismatched command rejects its pending gesture instead of navigating twice', async () => {
  const driver = new FakeDriver();
  const controller = new PagedTrackController(driver);
  controller.pointerDown(pointer(1, 300, 0, 0));
  controller.pointerMove(pointer(1, 180, 0, 400));
  const release = await controller.pointerUp(pointer(1, 180, 0, 410));
  assert.equal(release.kind, 'commit-requested');

  assert.equal(await controller.acceptPending(-1), false);
  assert.equal(controller.getPendingStep(), null);
  assert.deepEqual(driver.animations.map((animation) => animation.target), [0]);
  assert.equal(driver.promotions.length, 0);
});

test('pending gestures time out and roll back when no session command consumes them', async () => {
  const driver = new FakeDriver();
  const clock = new ManualClock();
  const controller = new PagedTrackController(driver, { clock });
  controller.pointerDown(pointer(1, 300, 0, 0));
  controller.pointerMove(pointer(1, 180, 0, 400));
  await controller.pointerUp(pointer(1, 180, 0, 410));
  assert.equal(controller.snapshot().phase, 'awaiting-command');

  clock.runAll();
  await flush();
  assert.equal(controller.snapshot().phase, 'idle');
  assert.equal(controller.getPendingStep(), null);
  assert.deepEqual(driver.animations.map((animation) => animation.target), [0]);
});

test('programmatic steps are serialized and every queued intent promotes exactly once', async () => {
  const driver = new FakeDriver();
  const firstPromotion = deferred();
  driver.promoteGates.push(firstPromotion.promise);
  const controller = new PagedTrackController(driver);

  const first = controller.step(1);
  const second = controller.step(1);
  await flush();
  assert.equal(driver.calls.filter((call) => call === 'prepare:1').length, 1);
  assert.deepEqual(driver.promotions, [1]);

  firstPromotion.resolve();
  assert.equal(await first, true);
  assert.equal(await second, true);
  assert.equal(driver.calls.filter((call) => call === 'prepare:1').length, 2);
  assert.deepEqual(driver.promotions, [1, 1]);
  assert.equal(controller.snapshot().phase, 'idle');
});

test('programmatic prepare false never animates and reduced motion still promotes through duration zero', async () => {
  const unavailableDriver = new FakeDriver();
  unavailableDriver.prepareReady = false;
  const unavailable = new PagedTrackController(unavailableDriver);
  assert.equal(await unavailable.step(1), false);
  assert.equal(unavailableDriver.animations.length, 0);
  assert.equal(unavailableDriver.promotions.length, 0);
  assert.equal(unavailable.snapshot().phase, 'idle');

  const reducedDriver = new FakeDriver();
  reducedDriver.state.reducedMotion = true;
  const reduced = new PagedTrackController(reducedDriver);
  assert.equal(await reduced.step(-1), true);
  assert.deepEqual(reducedDriver.animations, [{ target: -1, durationMs: 0 }]);
  assert.deepEqual(reducedDriver.promotions, [-1]);
});

test('AbortSignal and interrupt restore the committed center and invalidate queued work', async () => {
  const abortDriver = new FakeDriver();
  const animation = deferred();
  abortDriver.animateGates.push(animation.promise);
  const abortController = new AbortController();
  const abortTrack = new PagedTrackController(abortDriver);
  const abortedStep = abortTrack.step(1, { signal: abortController.signal });
  await flush();
  abortController.abort();
  assert.equal(await abortedStep, false);
  assert.equal(abortTrack.snapshot().phase, 'idle');
  assert.ok(abortDriver.calls.includes('cancel'));
  assert.equal(abortDriver.calls.at(-1), 'recenter');

  const interruptDriver = new FakeDriver();
  const blockedAnimation = deferred();
  interruptDriver.animateGates.push(blockedAnimation.promise);
  const interruptedTrack = new PagedTrackController(interruptDriver);
  const active = interruptedTrack.step(1);
  const queued = interruptedTrack.step(1);
  await flush();
  interruptedTrack.interrupt();
  assert.equal(await active, false);
  assert.equal(await queued, false);
  assert.equal(interruptDriver.calls.filter((call) => call === 'prepare:1').length, 1);
  assert.equal(interruptedTrack.snapshot().phase, 'idle');
});

test('suspend, resume, pointer cancel and dispose keep the track at its committed center', async () => {
  const driver = new FakeDriver();
  const controller = new PagedTrackController(driver);
  controller.suspend();
  assert.equal(controller.snapshot().phase, 'suspended');
  assert.equal(await controller.step(1), false);
  assert.equal(controller.pointerDown(pointer(1, 100, 0, 0)).handled, false);
  assert.equal(controller.resume(), true);

  controller.pointerDown(pointer(2, 300, 0, 100));
  controller.pointerMove(pointer(2, 200, 0, 200));
  assert.equal(await controller.pointerCancel(2), true);
  assert.equal(controller.snapshot().phase, 'idle');
  assert.equal(controller.snapshot().logicalOffsetPx, 0);

  controller.dispose();
  assert.equal(controller.snapshot().phase, 'suspended');
  assert.equal(controller.resume(), false);
  assert.equal(await controller.step(1), false);
});
