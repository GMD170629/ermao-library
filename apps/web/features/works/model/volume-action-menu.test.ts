import assert from 'node:assert/strict';
import test from 'node:test';
import { volumeActionAvailability } from './volume-action-menu';

test('returns no management actions without system-management permission', () => {
  assert.deepEqual(volumeActionAvailability({ canManage: false, readable: true, mediaKind: 'EBOOK' }), []);
});

test('orders the primary actions and offers only the other media kinds', () => {
  const actions = volumeActionAvailability({ canManage: true, readable: true, mediaKind: 'AUDIOBOOK' });
  assert.deepEqual(actions.map((item) => item.action), ['download', 'edit', 'set-media-kind', 'set-ebook', 'set-comic']);
});

test('disables unavailable navigation without hiding management actions', () => {
  const actions = volumeActionAvailability({ canManage: true, readable: false, mediaKind: 'COMIC' });
  assert.equal(actions.find((item) => item.action === 'download')?.disabled, true);
  assert.equal(actions.some((item) => item.action === 'set-comic'), false);
});

test('keeps edit visible but disables it for multiple selected volumes', () => {
  const actions = volumeActionAvailability({ canManage: true, readable: true, mediaKind: 'EBOOK', selectionCount: 2 });
  assert.equal(actions.find((item) => item.action === 'edit')?.disabled, true);
});
