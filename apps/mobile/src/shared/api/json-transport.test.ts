import assert from 'node:assert/strict';
import test from 'node:test';

import {
  FetchJsonTransport,
  type FetchFunction,
} from './json-transport';

const encoder = new TextEncoder();

function bodyFromText(text: string): ReadableStream<Uint8Array> {
  return new ReadableStream({
    start(controller) {
      controller.enqueue(encoder.encode(text));
      controller.close();
    },
  });
}

test('decodes a bounded JSON response', async () => {
  const fetchFunction: FetchFunction = async () => ({
    body: bodyFromText('{"ok":true}'),
    status: 200,
  });
  const result = await new FetchJsonTransport(fetchFunction).get({
    maximumResponseBytes: 1_024,
    timeoutMs: 1_000,
    url: 'https://library.example/api/health',
  });

  assert.deepEqual(result, {
    ok: true,
    status: 200,
    body: { ok: true },
  });
});

test('cancels a response stream after the byte limit is exceeded', async () => {
  let cancelled = false;
  const fetchFunction: FetchFunction = async () => ({
    body: new ReadableStream({
      start(controller) {
        controller.enqueue(encoder.encode('x'.repeat(32)));
      },
      cancel() {
        cancelled = true;
      },
    }),
    status: 200,
  });
  const result = await new FetchJsonTransport(fetchFunction).get({
    maximumResponseBytes: 16,
    timeoutMs: 1_000,
    url: 'https://library.example/api/health',
  });

  assert.deepEqual(result, {
    ok: false,
    reason: 'response-too-large',
    status: 200,
  });
  assert.equal(cancelled, true);
});

test('preserves the HTTP status for an invalid JSON response', async () => {
  const fetchFunction: FetchFunction = async () => ({
    body: bodyFromText('<html>not the API</html>'),
    status: 404,
  });
  const result = await new FetchJsonTransport(fetchFunction).get({
    maximumResponseBytes: 1_024,
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
  const fetchFunction: FetchFunction = (_url, request) =>
    new Promise((_resolve, reject) => {
      request.signal.addEventListener(
        'abort',
        () => {
          reject(new Error('aborted by test deadline'));
        },
        { once: true },
      );
    });
  const result = await new FetchJsonTransport(fetchFunction).get({
    maximumResponseBytes: 1_024,
    timeoutMs: 1,
    url: 'https://library.example/api/health',
  });

  assert.deepEqual(result, { ok: false, reason: 'timeout' });
});
