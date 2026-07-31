import { Directory, File, Paths } from 'expo-file-system';

import {
  PrivateFileSystemError,
  type PrivateFileEntry,
  type PrivateFileSystem,
  type PrivateFileSystemOperation,
} from './private-file-system';

const SAFE_SEGMENT = /^[A-Za-z0-9._-]+$/;

function pathSegments(relativePath: string): readonly string[] {
  const segments = relativePath.split('/');
  if (
    relativePath.length === 0 ||
    relativePath.startsWith('/') ||
    relativePath.includes('\\') ||
    segments.some(
      (segment) =>
        segment.length === 0 ||
        segment === '.' ||
        segment === '..' ||
        !SAFE_SEGMENT.test(segment),
    )
  ) {
    throw new TypeError('Private file path must contain safe relative segments');
  }

  return segments;
}

function parentPath(relativeFile: string): string | null {
  const segments = pathSegments(relativeFile);
  return segments.length > 1 ? segments.slice(0, -1).join('/') : null;
}

export class ExpoPrivateFileSystem implements PrivateFileSystem {
  private readonly root = new Directory(
    Paths.document,
    'shuku-starship',
    'mobile',
    'v1',
  );

  async ensureDirectory(relativeDirectory: string): Promise<void> {
    await this.perform('ensure-directory', relativeDirectory, () => {
      this.directory(relativeDirectory).create({
        idempotent: true,
        intermediates: true,
      });
    });
  }

  async list(relativeDirectory: string): Promise<readonly PrivateFileEntry[]> {
    return this.perform('list', relativeDirectory, () => {
      const directory = this.directory(relativeDirectory);
      if (!directory.exists) {
        return [];
      }

      return directory.list().map((entry) => ({
        kind: entry instanceof Directory ? 'directory' : 'file',
        name: Paths.basename(entry.uri),
      }));
    });
  }

  async readText(relativeFile: string): Promise<string | null> {
    return this.perform('read', relativeFile, async () => {
      const file = this.file(relativeFile);
      return file.exists ? file.text() : null;
    });
  }

  async writeText(relativeFile: string, contents: string): Promise<void> {
    await this.perform('write', relativeFile, () => {
      const file = this.file(relativeFile);
      file.create({ intermediates: true, overwrite: true });
      file.write(contents);
    });
  }

  async moveFile(
    sourceRelativeFile: string,
    destinationRelativeFile: string,
    options: Readonly<{ overwrite: boolean }>,
  ): Promise<void> {
    await this.perform(
      'move',
      `${sourceRelativeFile} -> ${destinationRelativeFile}`,
      async () => {
        const destinationParent = parentPath(destinationRelativeFile);
        if (destinationParent !== null) {
          this.directory(destinationParent).create({
            idempotent: true,
            intermediates: true,
          });
        }

        await this.file(sourceRelativeFile).move(
          this.file(destinationRelativeFile),
          { overwrite: options.overwrite },
        );
      },
    );
  }

  async deleteFile(relativeFile: string): Promise<void> {
    await this.perform('delete', relativeFile, () => {
      const file = this.file(relativeFile);
      if (file.exists) {
        file.delete();
      }
    });
  }

  private directory(relativeDirectory: string): Directory {
    return new Directory(this.root, ...pathSegments(relativeDirectory));
  }

  private file(relativeFile: string): File {
    return new File(this.root, ...pathSegments(relativeFile));
  }

  private async perform<Result>(
    operation: PrivateFileSystemOperation,
    relativePath: string,
    action: () => Result | Promise<Result>,
  ): Promise<Result> {
    try {
      return await action();
    } catch (cause: unknown) {
      throw new PrivateFileSystemError(operation, relativePath, cause);
    }
  }
}
