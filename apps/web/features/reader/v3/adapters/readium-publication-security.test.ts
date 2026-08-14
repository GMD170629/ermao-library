import assert from 'node:assert/strict';
import test from 'node:test';
import { createSecurePublicationFetch } from './readium-publication-security';

const secureMarkup = `<?xml version="1.0"?>
<html><head><meta http-equiv="Content-Security-Policy"
content="connect-src 'none'; form-action 'none'; frame-src 'none'; object-src 'none'; script-src blob:"
data-shuku-security-profile="web-v2"/></head><body><script>bookCode()</script><p>Text</p></body></html>`;

test('accepts a head-decorated resource without rewriting author body content', async () => {
  const fetcher = createSecurePublicationFetch(async () => new Response(secureMarkup, {
    headers: { 'content-type': 'application/xhtml+xml; charset=utf-8' },
  }));

  const response = await fetcher('https://reader.test/chapter.xhtml');

  assert.equal(await response.text(), secureMarkup);
  assert.match(secureMarkup, /<body><script>bookCode\(\)<\/script><p>Text<\/p><\/body>/);
});

test('rejects markup before Readium blob creation when the security profile is absent', async () => {
  const fetcher = createSecurePublicationFetch(async () => new Response(
    '<html><head></head><body><p>Unsafe boundary</p></body></html>',
    { headers: { 'content-type': 'application/xhtml+xml' } },
  ));

  await assert.rejects(
    fetcher('https://reader.test/chapter.xhtml'),
    /READIUM_PUBLICATION_SECURITY_PROFILE_MISSING/,
  );
});
