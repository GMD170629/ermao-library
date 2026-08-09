import assert from 'node:assert/strict';
import test from 'node:test';

import {
  FetchApiTransport,
  type ApiFetchFunction,
  type ApiFetchResponse,
} from './api-transport';

const encoder = new TextEncoder();
const emptyHeaders: ApiFetchResponse['headers'] = { get: () => null };

function bodyFromText(text: string): ReadableStream<Uint8Array> {
  return new ReadableStream({
    start(controller) {
      controller.enqueue(encoder.encode(text));
      controller.close();
    },
  });
}

test('decodes a bounded authenticated JSON response and metadata', async () => {
  let credentials: 'include' | null = null;
  const fetchFunction: ApiFetchFunction = async (_url, request) => {
    credentials = request.credentials;
    return {
      body: bodyFromText('{"ok":true}'),
      headers: {
        get: (name) =>
          name === 'content-type'
            ? 'application/json'
            : name === 'etag'
              ? '"cover-v1"'
              : null,
      },
      status: 200,
    };
  };
  const result = await new FetchApiTransport(fetchFunction).request({
    maximumResponseBytes: 1_024,
    method: 'GET',
    responseType: 'json',
    timeoutMs: 1_000,
    url: 'https://library.example/api/health',
  });

  assert.deepEqual(result, {
    ok: true,
    responseType: 'json',
    status: 200,
    headers: {
      contentType: 'application/json',
      etag: '"cover-v1"',
      lastModified: null,
    },
    body: { ok: true },
  });
  assert.equal(credentials, 'include');
});

test('serializes JSON writes with the API content type', async () => {
  let capturedBody: FormData | string | undefined;
  let capturedContentType: string | undefined;
  const fetchFunction: ApiFetchFunction = async (_url, request) => {
    capturedBody = request.body;
    capturedContentType = request.headers['Content-Type'];
    return { body: bodyFromText('{"ok":true}'), headers: emptyHeaders, status: 200 };
  };

  await new FetchApiTransport(fetchFunction).request({
    body: {
      kind: 'json',
      value: { email: 'reader@example.com', password: 'secret' },
    },
    maximumResponseBytes: 1_024,
    method: 'POST',
    responseType: 'json',
    timeoutMs: 1_000,
    url: 'https://library.example/api/auth/login',
  });

  assert.equal(
    capturedBody,
    '{"email":"reader@example.com","password":"secret"}',
  );
  assert.equal(capturedContentType, 'application/json');
});

test('passes FormData through without manually setting Content-Type', async () => {
  const form = new FormData();
  form.append('target_path', '/library/incoming');
  let capturedBody: FormData | string | undefined;
  let contentTypeWasSet = false;
  const fetchFunction: ApiFetchFunction = async (_url, request) => {
    capturedBody = request.body;
    contentTypeWasSet = Object.keys(request.headers).some(
      (name) => name.toLowerCase() === 'content-type',
    );
    return { body: null, headers: emptyHeaders, status: 202 };
  };

  await new FetchApiTransport(fetchFunction).request({
    body: { kind: 'form-data', value: form },
    maximumResponseBytes: 1_024,
    method: 'POST',
    responseType: 'json',
    timeoutMs: 1_000,
    url: 'https://library.example/api/works/import',
  });

  assert.strictEqual(capturedBody, form);
  assert.equal(contentTypeWasSet, false);
});

test('returns bounded bytes without decoding binary content', async () => {
  const bytes = new Uint8Array([0, 255, 10, 42]);
  const fetchFunction: ApiFetchFunction = async () => ({
    body: new ReadableStream({
      start(controller) {
        controller.enqueue(bytes.subarray(0, 2));
        controller.enqueue(bytes.subarray(2));
        controller.close();
      },
    }),
    headers: {
      get: (name) => (name === 'content-type' ? 'image/webp' : null),
    },
    status: 200,
  });

  const result = await new FetchApiTransport(fetchFunction).request({
    maximumResponseBytes: 16,
    method: 'GET',
    responseType: 'bytes',
    timeoutMs: 1_000,
    url: 'https://library.example/api/covers/one',
  });

  assert.equal(result.ok, true);
  if (!result.ok || result.responseType !== 'bytes') return;
  assert.deepEqual(result.body, bytes);
  assert.equal(result.headers.contentType, 'image/webp');
});

test('returns null for an empty JSON response body', async () => {
  const fetchFunction: ApiFetchFunction = async () => ({
    body: null,
    headers: emptyHeaders,
    status: 204,
  });
  const result = await new FetchApiTransport(fetchFunction).request({
    maximumResponseBytes: 1_024,
    method: 'DELETE',
    responseType: 'json',
    timeoutMs: 1_000,
    url: 'https://library.example/api/resource',
  });
  assert.deepEqual(result, {
    ok: true,
    responseType: 'json',
    status: 204,
    headers: { contentType: null, etag: null, lastModified: null },
    body: null,
  });
});

test('cancels a response stream after the byte limit is exceeded', async () => {
  let cancelled = false;
  const fetchFunction: ApiFetchFunction = async () => ({
    body: new ReadableStream({
      start(controller) {
        controller.enqueue(encoder.encode('x'.repeat(32)));
      },
      cancel() {
        cancelled = true;
      },
    }),
    headers: emptyHeaders,
    status: 200,
  });
  const result = await new FetchApiTransport(fetchFunction).request({
    maximumResponseBytes: 16,
    method: 'GET',
    responseType: 'bytes',
    timeoutMs: 1_000,
    url: 'https://library.example/api/covers/one',
  });

  assert.deepEqual(result, {
    ok: false,
    reason: 'response-too-large',
    status: 200,
  });
  assert.equal(cancelled, true);
});

test('preserves the HTTP status for an invalid JSON response', async () => {
  const fetchFunction: ApiFetchFunction = async () => ({
    body: bodyFromText('<html>not the API</html>'),
    headers: emptyHeaders,
    status: 404,
  });
  const result = await new FetchApiTransport(fetchFunction).request({
    maximumResponseBytes: 1_024,
    method: 'GET',
    responseType: 'json',
    timeoutMs: 1_000,
    url: 'https://library.example/wrong/api/health',
  });

  assert.deepEqual(result, {
    ok: false,
    reason: 'invalid-json',
    status: 404,
  });
});

test('classifies an internal abort deadline as a timeout', async () => {
  const fetchFunction: ApiFetchFunction = (_url, request) =>
    new Promise((_resolve, reject) => {
      request.signal.addEventListener(
        'abort',
        () => reject(new Error('aborted by test deadline')),
        { once: true },
      );
    });
  const result = await new FetchApiTransport(fetchFunction).request({
    maximumResponseBytes: 1_024,
    method: 'GET',
    responseType: 'json',
    timeoutMs: 1,
    url: 'https://library.example/api/health',
  });

  assert.deepEqual(result, { ok: false, reason: 'timeout' });
});

test('rejects body-bearing GET and manually typed FormData', async () => {
  const fetchFunction: ApiFetchFunction = async () => {
    assert.fail('fetch must not run for an invalid request');
  };
  const transport = new FetchApiTransport(fetchFunction);
  await assert.rejects(
    transport.request({
      body: { kind: 'json', value: {} },
      maximumResponseBytes: 1_024,
      method: 'GET',
      responseType: 'json',
      timeoutMs: 1_000,
      url: 'https://library.example/api/health',
    }),
    /GET requests cannot include/,
  );
  await assert.rejects(
    transport.request({
      body: { kind: 'form-data', value: new FormData() },
      headers: { 'content-type': 'multipart/form-data' },
      maximumResponseBytes: 1_024,
      method: 'POST',
      responseType: 'json',
      timeoutMs: 1_000,
      url: 'https://library.example/api/works/import',
    }),
    /FormData Content-Type/,
  );
});
