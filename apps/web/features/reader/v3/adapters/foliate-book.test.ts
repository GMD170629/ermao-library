import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import test from 'node:test';
import {
  NovelOpenError,
  normalizeFoliateFixedLayoutViewport,
  openFoliateBook
} from './foliate-book';
import { MemoryReaderStorage } from '../../../../lib/reader/memory-storage';

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

test('downloads a Foliate book once, reports byte progress, and reopens it from the private cache', async () => {
  const storage = new MemoryReaderStorage();
  const progress: Array<{ loadedBytes: number; totalBytes: number | null; percent: number | null }> = [];
  let requests = 0;
  const options = {
    url: '/book.txt',
    format: 'txt' as const,
    title: 'Cached TXT',
    signal: signal(),
    cache: {
      storage,
      identity: { userId: 'user-1', volumeId: 'volume-1', contentFingerprint: 'sha256:first' }
    }
  };

  const first = await openFoliateBook({
    ...options,
    fetch: async () => {
      requests += 1;
      return new Response('第一章\n缓存正文', {
        status: 200,
        headers: { 'Content-Length': String(new TextEncoder().encode('第一章\n缓存正文').byteLength) }
      });
    },
    onDownloadProgress: (value) => progress.push(value)
  });
  await first.destroy();

  const second = await openFoliateBook({
    ...options,
    fetch: async () => {
      requests += 1;
      throw new Error('cache miss');
    }
  });

  assert.equal(requests, 1);
  assert.equal(second.book.sections.length, 1);
  assert.equal(progress.at(-1)?.percent, 100);
  assert.ok((progress.at(-1)?.loadedBytes ?? 0) > 0);
  await second.destroy();
});

test('validates downloaded and cached publications against the local SHA-256 identity', async () => {
  const body = '已校验的本地图书内容';
  const expectedSha256 = `sha256:${createHash('sha256').update(body).digest('hex')}`;
  const storage = new MemoryReaderStorage();
  const identity = { userId: 'user-1', volumeId: 'volume-hash', contentFingerprint: 'server-token' };
  const opened = await openFoliateBook({
    url: '/book.txt',
    format: 'txt',
    title: 'Hash checked',
    signal: signal(),
    expectedSha256,
    cache: { storage, identity },
    fetch: async () => new Response(body)
  });
  await opened.destroy();
  await assert.rejects(openFoliateBook({
    url: '/book.txt',
    format: 'txt',
    title: 'Hash mismatch',
    signal: signal(),
    expectedSha256: `sha256:${'0'.repeat(64)}`,
    fetch: async () => new Response(body)
  }), (reason: unknown) => reason instanceof NovelOpenError && reason.code === 'NOVEL_RESOURCE_FAILED');
});

test('keeps the downloaded book usable when persistent storage rejects the cache write', async () => {
  const storage = new MemoryReaderStorage();
  storage.putBookFile = async () => {
    throw new DOMException('quota', 'QuotaExceededError');
  };
  const warnings: string[] = [];
  const result = await openFoliateBook({
    url: '/book.txt',
    format: 'txt',
    title: 'No storage',
    signal: signal(),
    cache: {
      storage,
      identity: { userId: 'user-1', volumeId: 'volume-1', contentFingerprint: 'sha256:no-space' }
    },
    fetch: async () => new Response('正文'),
    onCacheWarning: (code) => warnings.push(code)
  });

  assert.equal(result.book.sections.length, 1);
  assert.deepEqual(warnings, ['BOOK_CACHE_WRITE_FAILED']);
  await result.destroy();
});

test('serializes concurrent opens so only one tab-local request downloads the same book', async () => {
  const storage = new MemoryReaderStorage();
  let requests = 0;
  const options = {
    url: '/book.txt',
    format: 'txt' as const,
    title: 'Concurrent TXT',
    signal: signal(),
    cache: {
      storage,
      identity: { userId: 'user-1', volumeId: 'volume-concurrent', contentFingerprint: 'sha256:concurrent' }
    },
    fetch: async () => {
      requests += 1;
      await new Promise((resolve) => setTimeout(resolve, 5));
      return new Response('并发正文');
    }
  };

  const [first, second] = await Promise.all([openFoliateBook(options), openFoliateBook(options)]);
  assert.equal(requests, 1);
  await Promise.all([first.destroy(), second.destroy()]);
});

test('does not persist a partial file when the reader cancels the first download', async () => {
  const storage = new MemoryReaderStorage();
  const controller = new AbortController();
  const identity = { userId: 'user-1', volumeId: 'volume-abort', contentFingerprint: 'sha256:abort' };
  const body = new ReadableStream<Uint8Array>({
    start(streamController) {
      streamController.enqueue(new TextEncoder().encode('部分正文'));
    }
  });

  await assert.rejects(openFoliateBook({
    url: '/book.txt',
    format: 'txt',
    title: 'Cancelled TXT',
    signal: controller.signal,
    cache: { storage, identity },
    fetch: async () => new Response(body),
    onDownloadProgress: (progress) => {
      if (progress.loadedBytes > 0) controller.abort();
    }
  }), (reason: unknown) => reason instanceof DOMException && reason.name === 'AbortError');
  assert.equal(await storage.getBookFile(identity), null);
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
