import assert from 'node:assert/strict';
import test from 'node:test';
import { resolveEpubFont } from './epub-font';

test('EPUB font resolver prefers an installed system face without downloading', async () => {
  let fetched = false;
  const resolution = await resolveEpubFont('pingfang', {
    signal: new AbortController().signal,
    fontSet: { check: (font) => font.includes('PingFang SC') },
    fetch: async () => { fetched = true; throw new Error('unexpected'); }
  });
  assert.equal(resolution.source, 'system');
  assert.equal(fetched, false);
});

test('EPUB font resolver pins a system fallback after an embedded font failure', async () => {
  const resolution = await resolveEpubFont('kaiti', {
    signal: new AbortController().signal,
    fontSet: { check: () => false },
    fetch: async () => new Response('', { status: 503 })
  });
  assert.equal(resolution.source, 'fallback');
  assert.equal(resolution.embedded, undefined);
  assert.match(resolution.stack, /serif/);
});

test('EPUB font resolver reuses a session object URL instead of exposing the server font URL to every chapter', async () => {
  let fetched = 0;
  let revoked = '';
  const resolution = await resolveEpubFont('kaiti', {
    signal: new AbortController().signal,
    fontSet: { check: () => false },
    fetch: async () => {
      fetched += 1;
      return new Response(new Uint8Array([1, 2, 3]), { status: 200 });
    },
    createObjectURL: () => 'blob:reader-font-session',
    revokeObjectURL: (url) => { revoked = url; }
  });

  assert.equal(fetched, 1);
  assert.equal(resolution.embedded?.url, 'blob:reader-font-session');
  resolution.embedded?.release?.();
  resolution.embedded?.release?.();
  assert.equal(revoked, 'blob:reader-font-session');
});
