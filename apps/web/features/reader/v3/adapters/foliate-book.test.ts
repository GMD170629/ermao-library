import assert from 'node:assert/strict';
import test from 'node:test';
import {
  NovelOpenError,
  normalizeFoliateFixedLayoutViewport,
  openFoliateBook
} from './foliate-book';

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

test('normalizes an empty fixed-layout viewport so Foliate can use the page image size', () => {
  const book = {
    sections: [{ load: () => '' }],
    rendition: { layout: 'pre-paginated', viewport: {} }
  };

  normalizeFoliateFixedLayoutViewport(book);

  assert.deepEqual(book.rendition, {
    layout: 'pre-paginated',
    viewport: undefined
  });
});

test('preserves valid fixed-layout and reflowable viewport metadata', () => {
  const fixedLayout = {
    sections: [{ load: () => '' }],
    rendition: {
      layout: 'pre-paginated',
      viewport: { width: '1200', height: '1800' }
    }
  };
  const reflowable = {
    sections: [{ load: () => '' }],
    rendition: { layout: 'reflowable', viewport: {} }
  };

  normalizeFoliateFixedLayoutViewport(fixedLayout);
  normalizeFoliateFixedLayoutViewport(reflowable);

  assert.deepEqual(fixedLayout.rendition.viewport, { width: '1200', height: '1800' });
  assert.deepEqual(reflowable.rendition.viewport, {});
});
