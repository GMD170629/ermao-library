import assert from 'node:assert/strict';
import test from 'node:test';
import { EPUB_CONTENT_SECURITY_POLICY, sanitizeEpubMarkup, sanitizeEpubMarkupFallback } from './epub-security';

test('EPUB fallback sanitizer removes executable markup and attributes', () => {
  const sanitized = sanitizeEpubMarkupFallback(`
    <html><body onload="steal()">
      <script>alert(1)</script>
      <iframe srcdoc="<script>alert(2)</script>"></iframe>
      <form action="https://attacker.invalid"><input name="secret" /></form>
      <a href="javascript:alert(3)" onclick="alert(4)">bad</a>
      <p style="width: expression(alert(5))">text</p>
    </body></html>
  `);

  assert.doesNotMatch(sanitized, /<\s*(?:script|iframe|form|input)\b/i);
  assert.doesNotMatch(sanitized, /\son[a-z]+\s*=/i);
  assert.doesNotMatch(sanitized, /javascript\s*:/i);
  assert.doesNotMatch(sanitized, /expression\s*\(/i);
  assert.match(sanitized, />text</);
});

test('EPUB CSP denies scripts, connections, frames, objects, and forms', () => {
  assert.match(EPUB_CONTENT_SECURITY_POLICY, /script-src 'none'/);
  assert.match(EPUB_CONTENT_SECURITY_POLICY, /connect-src 'none'/);
  assert.match(EPUB_CONTENT_SECURITY_POLICY, /frame-src 'none'/);
  assert.match(EPUB_CONTENT_SECURITY_POLICY, /object-src 'none'/);
  assert.match(EPUB_CONTENT_SECURITY_POLICY, /form-action 'none'/);
});

test('malformed EPUB markup fails closed with CSP and no source payload', () => {
  const sanitized = sanitizeEpubMarkup('<html><head></head><body><script>globalThis.pwned = true</script>');
  assert.match(sanitized, /Content-Security-Policy/);
  assert.match(sanitized, /script-src 'none'/);
  assert.doesNotMatch(sanitized, /globalThis\.pwned/);
});
