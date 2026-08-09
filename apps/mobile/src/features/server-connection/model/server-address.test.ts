import assert from 'node:assert/strict';
import test from 'node:test';

import {
  parseServerAddress,
  serverApiUrl,
  serverHealthUrl,
} from './server-address';

test('uses the library web address as the only public origin for API requests', () => {
  const parsed = parseServerAddress(' 192.168.1.20:3000/ ');
  assert.equal(parsed.ok, true);
  if (parsed.ok) {
    assert.equal(parsed.baseUrl.value, 'http://192.168.1.20:3000');
    assert.equal(parsed.baseUrl.security, 'local-http');
    assert.equal(
      serverHealthUrl(parsed.baseUrl),
      'http://192.168.1.20:3000/api/health',
    );
    assert.equal(
      serverApiUrl(parsed.baseUrl, '/api/auth/me'),
      'http://192.168.1.20:3000/api/auth/me',
    );
  }
});

test('treats local hostnames with ports as addresses rather than URI schemes', () => {
  const hostname = parseServerAddress('nas:3000');
  assert.equal(hostname.ok, true);
  if (hostname.ok) {
    assert.equal(hostname.baseUrl.value, 'http://nas:3000');
  }

  const multicastDns = parseServerAddress('books.local:8080/shuku/');
  assert.equal(multicastDns.ok, true);
  if (multicastDns.ok) {
    assert.equal(
      multicastDns.baseUrl.value,
      'http://books.local:8080/shuku',
    );
  }
});

test('preserves a reverse-proxy base path for the health endpoint', () => {
  const parsed = parseServerAddress(
    'https://books.example.com/shuku/',
  );
  assert.equal(parsed.ok, true);
  if (parsed.ok) {
    assert.equal(parsed.baseUrl.basePath, '/shuku');
    assert.equal(
      serverHealthUrl(parsed.baseUrl),
      'https://books.example.com/shuku/api/health',
    );
    assert.equal(
      serverApiUrl(parsed.baseUrl, '/api/auth/logout'),
      'https://books.example.com/shuku/api/auth/logout',
    );
  }
});

test('rejects public cleartext, device loopback, credentials and queries', () => {
  assert.deepEqual(parseServerAddress('http://books.example.com'), {
    ok: false,
    code: 'INSECURE_REMOTE_NOT_ALLOWED',
  });
  assert.deepEqual(parseServerAddress('http://127.0.0.1:3000'), {
    ok: false,
    code: 'DEVICE_LOOPBACK_NOT_ALLOWED',
  });
  assert.deepEqual(
    parseServerAddress('https://user:secret@books.example.com'),
    { ok: false, code: 'CREDENTIALS_NOT_ALLOWED' },
  );
  assert.deepEqual(
    parseServerAddress('https://books.example.com?token=secret'),
    { ok: false, code: 'QUERY_OR_FRAGMENT_NOT_ALLOWED' },
  );
});

test('accepts an HTTPS scheme case-insensitively', () => {
  const parsed = parseServerAddress('HTTPS://books.example.com');
  assert.equal(parsed.ok, true);
});

test('rejects an explicit unsupported URI scheme', () => {
  assert.deepEqual(parseServerAddress('ftp://books.local:3000'), {
    ok: false,
    code: 'UNSUPPORTED_SCHEME',
  });
});
