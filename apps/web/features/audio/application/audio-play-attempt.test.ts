import assert from 'node:assert/strict';
import test from 'node:test';
import { AudioPlayAttempt } from './audio-play-attempt';

test('pause supersedes both delayed success and rejection of the pending play', async () => {
  for (const reject of [false, true]) {
    const attempt = new AudioPlayAttempt();
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
  const attempt = new AudioPlayAttempt();
  let failPrevious: () => void = () => { throw new Error('play did not start'); };
  const previous = attempt.run(() => new Promise<void>((_resolve, reject) => {
    failPrevious = () => reject(new Error('old source detached'));
  }));
  assert.deepEqual(await attempt.run(() => Promise.resolve()), { type: 'playing' });
  failPrevious();
  assert.deepEqual(await previous, { type: 'superseded' });
});

test('a current engine failure remains visible and retains the original cause', async () => {
  const attempt = new AudioPlayAttempt();
  const reason = new Error('decoder unavailable');
  const outcome = await attempt.run(() => Promise.reject(reason));
  assert.deepEqual(outcome, { type: 'failed', reason });
});
