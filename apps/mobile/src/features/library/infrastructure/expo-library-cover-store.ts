import {
  CryptoDigestAlgorithm,
  digestStringAsync,
} from 'expo-crypto';
import { Directory, File, Paths } from 'expo-file-system';

import type {
  LibraryCoverStore,
  LibraryCoverStoreResult,
} from '../application/ports';
import type { LibraryCover } from '../model/library';

type CoverDigest = (value: string) => Promise<string>;

export interface LibraryCoverFileSystem {
  write(
    serverDirectory: string,
    fileName: string,
    bytes: Uint8Array,
  ): Promise<string>;
  clear(serverDirectory: string): Promise<void>;
}

async function sha256(value: string): Promise<string> {
  return digestStringAsync(CryptoDigestAlgorithm.SHA256, value);
}

function extensionFor(contentType: LibraryCover['contentType']): string {
  switch (contentType) {
    case 'image/jpeg':
      return 'jpg';
    case 'image/png':
      return 'png';
    case 'image/webp':
      return 'webp';
  }
}

function serverAddressFromCacheKey(cacheKey: string): string | null {
  const separator = cacheKey.indexOf('\n');
  return separator > 0 ? cacheKey.slice(0, separator) : null;
}

export class ExpoLibraryCoverFileSystem implements LibraryCoverFileSystem {
  private readonly root = new Directory(
    Paths.cache,
    'shuku-starship',
    'mobile',
    'v1',
    'covers',
  );

  async write(
    serverDirectory: string,
    fileName: string,
    bytes: Uint8Array,
  ): Promise<string> {
    const directory = new Directory(this.root, serverDirectory);
    directory.create({ idempotent: true, intermediates: true });
    const file = new File(directory, fileName);
    file.create({ intermediates: true, overwrite: true });
    file.write(bytes);
    return file.uri;
  }

  async clear(serverDirectory: string): Promise<void> {
    const directory = new Directory(this.root, serverDirectory);
    if (directory.exists) directory.delete();
  }
}

export class ExpoLibraryCoverStore implements LibraryCoverStore {
  constructor(
    private readonly fileSystem: LibraryCoverFileSystem =
      new ExpoLibraryCoverFileSystem(),
    private readonly digest: CoverDigest = sha256,
  ) {}

  async store(cover: LibraryCover): Promise<LibraryCoverStoreResult> {
    const serverAddress = serverAddressFromCacheKey(cover.cacheKey);
    if (serverAddress === null) {
      return { outcome: 'failed', reason: 'INVALID_COVER_CACHE_KEY' };
    }
    try {
      const [serverDirectory, coverName] = await Promise.all([
        this.digest(serverAddress),
        this.digest(cover.cacheKey),
      ]);
      const uri = await this.fileSystem.write(
        serverDirectory,
        `${coverName}.${extensionFor(cover.contentType)}`,
        cover.bytes,
      );
      return {
        outcome: 'stored',
        source: { cacheKey: cover.cacheKey, uri },
      };
    } catch (cause: unknown) {
      return {
        outcome: 'failed',
        reason: cause instanceof Error && cause.name.length > 0
          ? cause.name
          : 'COVER_CACHE_WRITE_FAILED',
      };
    }
  }

  async clearServer(serverCachePrefix: string): Promise<void> {
    const serverDirectory = await this.digest(serverCachePrefix);
    await this.fileSystem.clear(serverDirectory);
  }
}
