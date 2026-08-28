import assert from 'node:assert/strict';
import test from 'node:test';
import { createSecurePublicationFetch } from './readium-publication-security';
import readerHttpErrorStatuses from '../../../../../../packages/reader-contracts/reader-http-error-statuses.json';

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

test('preserves each declared server error and cancels an unfinished body', async () => {
  for (const [code, statuses] of Object.entries(readerHttpErrorStatuses.publication)) {
    for (const status of statuses) {
      let cancelled = false;
      const fetcher = createSecurePublicationFetch(async () => new Response(
        new ReadableStream({ cancel() { cancelled = true; } }),
        { status, headers: { 'X-Error-Code': code } },
      ));
      await assert.rejects(fetcher('https://reader.test/manifest.json'), { code, stage: 'manifest', status });
      assert.equal(cancelled, true);
    }
  }
});

test('a forged limit code cannot replace an authentication failure', async () => {
  const fetcher = createSecurePublicationFetch(async () => new Response(null, {
    status: 401, headers: { 'X-Error-Code': 'PUBLICATION_ONLINE_LIMIT' },
  }));
  await assert.rejects(fetcher('https://reader.test/chapter.xhtml'), { code: 'UNAUTHORIZED' });
});

test('passes malformed markup and NUL unchanged to the actual renderer', async () => {
  const source = '<html><body>A\0B\0';
  const fetcher = createSecurePublicationFetch(async () => new Response(source, { headers: secureHeaders }));
  assert.equal(await (await fetcher('https://reader.test/chapter.xhtml')).text(), source);
});

test('failure to cancel an error body does not overwrite the server cause', async () => {
  const cause = new Error('private-cleanup-details');
  const fetcher = createSecurePublicationFetch(async () => new Response(
    new ReadableStream({ cancel() { throw cause; } }),
    { status: 403, headers: { 'X-Error-Code': 'FORBIDDEN' } },
  ));
  await assert.rejects(fetcher('https://reader.test/chapter.xhtml'), {
    code: 'FORBIDDEN', stage: 'chapter', status: 403, source: 'server', cause,
  });
});
