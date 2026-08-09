import {
  ExpoLibraryCoverStore,
  type LibraryCoverFileSystem,
} from './expo-library-cover-store';

class FakeCoverFileSystem implements LibraryCoverFileSystem {
  readonly writes: Readonly<{
    serverDirectory: string;
    fileName: string;
    bytes: Uint8Array;
  }>[] = [];
  readonly cleared: string[] = [];

  async write(
    serverDirectory: string,
    fileName: string,
    bytes: Uint8Array,
  ): Promise<string> {
    this.writes.push({ serverDirectory, fileName, bytes });
    return `file:///cache/${serverDirectory}/${fileName}`;
  }

  async clear(serverDirectory: string): Promise<void> {
    this.cleared.push(serverDirectory);
  }
}

test('stores a protected cover under a server-isolated cache directory', async () => {
  const fileSystem = new FakeCoverFileSystem();
  const store = new ExpoLibraryCoverStore(
    fileSystem,
    async (value) => value.startsWith('https://books.test')
      ? value.includes('\n') ? 'cover-hash' : 'server-hash'
      : 'unexpected',
  );
  const bytes = new Uint8Array([1, 2, 3]);

  const result = await store.store({
    cacheKey: 'https://books.test/base\nhttps://books.test/base/api/works/1/cover',
    sourceUrl: 'https://books.test/base/api/works/1/cover',
    contentType: 'image/png',
    bytes,
  });

  expect(result).toEqual({
    outcome: 'stored',
    source: {
      cacheKey: 'https://books.test/base\nhttps://books.test/base/api/works/1/cover',
      uri: 'file:///cache/server-hash/cover-hash.png',
    },
  });
  expect(fileSystem.writes).toEqual([
    { serverDirectory: 'server-hash', fileName: 'cover-hash.png', bytes },
  ]);
});

test('clears only the requested server cache directory', async () => {
  const fileSystem = new FakeCoverFileSystem();
  const store = new ExpoLibraryCoverStore(fileSystem, async () => 'server-hash');

  await store.clearServer('https://books.test/base');

  expect(fileSystem.cleared).toEqual(['server-hash']);
});

test('rejects a cache key that does not identify its server', async () => {
  const store = new ExpoLibraryCoverStore(
    new FakeCoverFileSystem(),
    async () => 'unused',
  );

  await expect(store.store({
    cacheKey: 'invalid',
    sourceUrl: 'https://books.test/api/works/1/cover',
    contentType: 'image/jpeg',
    bytes: new Uint8Array([1]),
  })).resolves.toEqual({
    outcome: 'failed',
    reason: 'INVALID_COVER_CACHE_KEY',
  });
});
