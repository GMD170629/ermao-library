import assert from 'node:assert/strict';
import test from 'node:test';
import { IDBFactory, IDBKeyRange } from 'fake-indexeddb';
import { activateOriginalPublicationUser, clearOriginalPublicationData, originalPublicationStorage } from './publication-storage-runtime';

Object.assign(globalThis, { indexedDB: new IDBFactory(), IDBKeyRange });

test('legacy cleanup is precise, retries failure, and private clearing revokes original sessions', async () => {
  const old = 'shuku-pwa-private-v1-user-1-1-reader-original-v1';
  const names = new Set([old, 'shuku-pwa-private-v1-user-1-1-cover', 'shuku-static-v1', 'other-reader-original-v1']);
  let rejectCleanup = true;
  Object.assign(globalThis, { window: { caches: {
    keys: async () => [...names],
    delete: async (name: string) => {
      if (rejectCleanup) throw new DOMException('Blocked', 'SecurityError');
      return names.delete(name);
    }
  } } });
  await activateOriginalPublicationUser('user-1-1');
  const token = await originalPublicationStorage.session('user-1-1');
  assert.equal(names.has(old), true);
  rejectCleanup = false;
  await activateOriginalPublicationUser('user-1-1');
  assert.equal(names.has(old), false);
  assert.equal(names.size, 3);
  assert.deepEqual(await originalPublicationStorage.session('user-1-1'), token);
  await clearOriginalPublicationData();
  await assert.rejects(originalPublicationStorage.session('user-1-1'), { name: 'AbortError' });
  assert.equal(names.size, 3);
});

test('unavailable Cache Storage does not prevent HTTP IndexedDB activation', async () => {
  Object.assign(globalThis, { window: {} });
  await activateOriginalPublicationUser('user-2-1');
  assert.equal((await originalPublicationStorage.session('user-2-1')).namespace, 'user-2-1');
  await clearOriginalPublicationData();
});
