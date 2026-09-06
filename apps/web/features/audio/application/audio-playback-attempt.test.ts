import assert from 'node:assert/strict';
import test from 'node:test';
import { AudioPlaybackAttempt } from './audio-playback-attempt';

test('pause supersedes both delayed success and rejection of the pending play', async () => {
  for (const reject of [false, true]) {
    const attempt = new AudioPlaybackAttempt();
    let settle: () => void = () => { throw new Error('play did not start'); };
    const pending = attempt.run(() => new Promise<void>((resolve, fail) => {
      settle = reject ? () => fail(new Error('engine play interrupted by pause')) : resolve;
    }));
    attempt.cancel();
    settle();
    assert.deepEqual(await pending, { type: 'superseded' });
  }
});

test('an older source cannot overwrite a newer successful play', async () => {
  const attempt = new AudioPlaybackAttempt();
  let failPrevious: () => void = () => { throw new Error('play did not start'); };
  const previous = attempt.run(() => new Promise<void>((_resolve, reject) => {
    failPrevious = () => reject(new Error('old source detached'));
  }));
  assert.deepEqual(await attempt.run(() => Promise.resolve()), { type: 'playing' });
  failPrevious();
  assert.deepEqual(await previous, { type: 'superseded' });
});

test('a current engine failure remains visible and retains the original cause', async () => {
  const attempt = new AudioPlaybackAttempt();
  const reason = new Error('decoder unavailable');
  const outcome = await attempt.run(() => Promise.reject(reason));
  assert.deepEqual(outcome, { type: 'failed', reason });
});

test('close waits for local durability and does not reset on local failure', async () => {
  for (const saved of [true, false]) {
    const attempt = new AudioPlaybackAttempt();
    let finishSave: (saved: boolean) => void = () => { throw new Error('save did not start'); };
    let resets = 0;
    const closed = attempt.close(() => new Promise<boolean>((resolve) => { finishSave = resolve; }), () => { resets += 1; });
    assert.equal(resets, 0);
    finishSave(saved);
    await closed;
    assert.equal(resets, saved ? 1 : 0);
  }
});

test('new playback or a same-resource open supersedes a close waiting on local storage', async () => {
  for (const intention of ['play', 'open'] as const) {
    const attempt = new AudioPlaybackAttempt();
    let finishSave: (saved: boolean) => void = () => { throw new Error('save did not start'); };
    let resets = 0;
    const closed = attempt.close(() => new Promise<boolean>((resolve) => { finishSave = resolve; }), () => { resets += 1; });
    if (intention === 'play') await attempt.run(() => Promise.resolve());
    else attempt.cancelPendingClose();
    finishSave(true);
    await closed;
    assert.equal(resets, 0);
  }
});

test('repeated close waits for the newest save and resets once', async () => {
  const attempt = new AudioPlaybackAttempt();
  const finishes: ((saved: boolean) => void)[] = [];
  let resets = 0;
  const save = () => new Promise<boolean>((resolve) => { finishes.push(resolve); });
  const reset = () => { resets += 1; };
  const first = attempt.close(save, reset);
  const second = attempt.close(save, reset);
  finishes[0](true);
  await first;
  assert.equal(resets, 0);
  finishes[1](true);
  await second;
  assert.equal(resets, 1);
});
