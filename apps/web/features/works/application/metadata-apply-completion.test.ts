import assert from 'node:assert/strict';
import test from 'node:test';
import { completeMetadataApply } from './metadata-apply-completion';

test('closes the metadata lookup as soon as the update succeeds', async () => {
  const events: string[] = [];
  let finishRefresh: (() => void) | undefined;
  const refreshPending = new Promise<void>((resolve) => {
    finishRefresh = resolve;
  });

  const completion = completeMetadataApply({
    close: () => events.push('closed'),
    refresh: () => {
      events.push('refreshing');
      return refreshPending;
    }
  });

  assert.deepEqual(events, ['closed', 'refreshing']);
  finishRefresh?.();
  await completion;
});
