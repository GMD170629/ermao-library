import assert from 'node:assert/strict';
import test from 'node:test';
import { readBoundedResponse, ResponseLimitError } from './bounded-response';

test('rejects an oversized declared response without pulling or completing its body', async () => {
  let cancelled = false;
  let pulls = 0;
  const stream = new ReadableStream<Uint8Array>({ pull() { pulls += 1; }, cancel() { cancelled = true; } }, { highWaterMark: 0 });
  await assert.rejects(readBoundedResponse(new Response(stream, { headers: { 'Content-Length': '100' } }), 8),
    (error: unknown) => error instanceof ResponseLimitError && error.code === 'RESPONSE_TOO_LARGE');
  assert.equal(cancelled, true);
  assert.equal(pulls, 0);
});

test('stops an unbounded response as soon as the byte budget is exceeded', async () => {
  let pulls = 0;
  let cancelled = false;
  const stream = new ReadableStream<Uint8Array>({
    pull(controller) { pulls += 1; controller.enqueue(new Uint8Array(3)); },
    cancel() { cancelled = true; }
  }, { highWaterMark: 0 });
  await assert.rejects(readBoundedResponse(new Response(stream), 8), /RESPONSE_TOO_LARGE/);
  assert.equal(pulls, 3);
  assert.equal(cancelled, true);
});

test('rejects interrupted and contradictory length responses', async () => {
  await assert.rejects(readBoundedResponse(new Response('abc', { headers: { 'Content-Length': '4' } }), 8), /RESPONSE_LENGTH_INVALID/);
  await assert.rejects(readBoundedResponse(new Response('abc', { headers: { 'Content-Length': '3' } }), 8, 4), /RESPONSE_LENGTH_INVALID/);
  const stream = new ReadableStream<Uint8Array>({ start(controller) { controller.error(new Error('interrupted')); } });
  await assert.rejects(readBoundedResponse(new Response(stream), 8), /interrupted/);
});

test('assembles only the bounded requested unit', async () => {
  assert.deepEqual(await readBoundedResponse(new Response('chapter'), 8, 7), new TextEncoder().encode('chapter'));
});
