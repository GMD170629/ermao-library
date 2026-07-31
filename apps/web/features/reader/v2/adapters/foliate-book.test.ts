import assert from 'node:assert/strict';
import test from 'node:test';
import { NovelOpenError, openFoliateBook } from './foliate-book';

function signal() {
  return new AbortController().signal;
}

test('openFoliateBook builds TXT through the official book interface boundary', async () => {
  const result = await openFoliateBook({
    url: '/book.txt',
    format: 'txt',
    title: 'TXT fixture',
    signal: signal(),
    fetch: async () => new Response('第一章 开始\n正文', { status: 200 })
  });
  assert.equal(
    typeof result.book.metadata === 'object' && result.book.metadata !== null && 'title' in result.book.metadata
      ? result.book.metadata.title
      : null,
    'TXT fixture'
  );
  assert.equal(result.book.sections.length, 1);
  await result.destroy();
});

test('openFoliateBook returns a stable resource error for HTTP failures', async () => {
  await assert.rejects(openFoliateBook({
    url: '/missing.epub',
    format: 'epub',
    title: 'Missing',
    signal: signal(),
    fetch: async () => new Response('', { status: 404 })
  }), (reason: unknown) => reason instanceof NovelOpenError && reason.code === 'NOVEL_RESOURCE_FAILED');
});

test('openFoliateBook preserves AbortError instead of translating it to parse failure', async () => {
  const controller = new AbortController();
  controller.abort();
  await assert.rejects(openFoliateBook({
    url: '/book.epub',
    format: 'epub',
    title: 'Aborted',
    signal: controller.signal,
    fetch: async (_url, init) => {
      if (init?.signal?.aborted) throw new DOMException('aborted', 'AbortError');
      return new Response('');
    }
  }), (reason: unknown) => reason instanceof DOMException && reason.name === 'AbortError');
});
