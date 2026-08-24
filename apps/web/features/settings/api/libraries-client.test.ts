import assert from 'node:assert/strict';
import test from 'node:test';

import { deleteLibrary, LibraryApiError } from './libraries-client';


test('deletes a library only when the API confirms deletion', async (context) => {
  const originalFetch = globalThis.fetch;
  context.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = async (input, init) => {
    assert.equal(input, '/api/libraries/library-1');
    assert.equal(init?.method, 'DELETE');
    return new Response(JSON.stringify({ ok: true, data: { deleted: true, id: 'library-1' } }));
  };

  await deleteLibrary('library-1');
});


test('surfaces a failed library deletion instead of reporting success', async (context) => {
  const originalFetch = globalThis.fetch;
  context.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = async () => new Response(
    JSON.stringify({ ok: false, error: { message: '任务取消失败' } }),
    { status: 409 }
  );

  await assert.rejects(
    deleteLibrary('library-1'),
    (reason: unknown) => reason instanceof LibraryApiError && reason.message === '任务取消失败'
  );
});
