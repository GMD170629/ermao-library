import assert from 'node:assert/strict';
import test from 'node:test';
import { createSecurePublicationFetch } from './readium-publication-security';

const secureMarkup = `<?xml version="1.0"?>
<html><head></head><body><script>bookCode()</script><p>Text</p></body></html>`;

const secureHeaders = {
  'content-type': 'application/xhtml+xml; charset=utf-8',
  'content-security-policy': "default-src 'none'; connect-src 'none'; form-action 'none'; frame-src 'none'; object-src 'none'; script-src blob:",
  'x-content-type-options': 'nosniff',
};

test('accepts a head-decorated resource without rewriting author body content', async () => {
  const fetcher = createSecurePublicationFetch(async () => new Response(secureMarkup, {
    headers: secureHeaders,
  }));

  const response = await fetcher('https://reader.test/chapter.xhtml');

  assert.equal(await response.text(), secureMarkup);
  assert.match(secureMarkup, /<body><script>bookCode\(\)<\/script><p>Text<\/p><\/body>/);
});

test('rejects markup before Readium blob creation when response security headers are absent', async () => {
  const fetcher = createSecurePublicationFetch(async () => new Response(
    '<html><head></head><body><p>Unsafe boundary</p></body></html>',
    { headers: { 'content-type': 'application/xhtml+xml' } },
  ));

  await assert.rejects(
    fetcher('https://reader.test/chapter.xhtml'),
    /READIUM_PUBLICATION_SECURITY_PROFILE_MISSING/,
  );
});


test('rejects a changed revision before consuming an unfinished body', async () => {
  let requests = 0;
  let cancelled = false;
  const fetcher = createSecurePublicationFetch(async () => {
    requests += 1;
    if (requests === 1) return new Response('{}', {
      headers: { 'content-type': 'application/json', 'X-Publication-Revision': 'first' },
    });
    return new Response(new ReadableStream({ cancel() { cancelled = true; } }), {
      headers: { ...secureHeaders, 'X-Publication-Revision': 'second' },
    });
  });
  await fetcher('https://reader.test/manifest.json');
  await assert.rejects(fetcher('https://reader.test/chapter.xhtml'), /PUBLICATION_CHANGED/);
  assert.equal(cancelled, true);
});


test('reports a chapter limit response without classifying it as a version change', async () => {
  let requests = 0;
  const fetcher = createSecurePublicationFetch(async () => ++requests === 1
    ? new Response('{}', { headers: { 'content-type': 'application/json', 'X-Publication-Revision': 'first' } })
    : new Response(null, { status: 413 }));
  await fetcher('https://reader.test/manifest.json');
  await assert.rejects(fetcher('https://reader.test/chapter.xhtml'), { code: 'PUBLICATION_RESOURCE_TOO_LARGE' });
});
