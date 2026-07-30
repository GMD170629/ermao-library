import type {
  PrivateFileEntry,
  PrivateFileSystem,
} from '../files/private-file-system';
import type { Clock, IdGenerator } from '../lib/runtime';

function parentDirectory(relativeFile: string): string {
  const separator = relativeFile.lastIndexOf('/');
  return separator < 0 ? '' : relativeFile.slice(0, separator);
}

export class MemoryPrivateFileSystem implements PrivateFileSystem {
  private readonly directories = new Set<string>();
  private readonly files = new Map<string, string>();
  failNextMove = false;

  async ensureDirectory(relativeDirectory: string): Promise<void> {
    const segments = relativeDirectory.split('/');
    for (let index = 1; index <= segments.length; index += 1) {
      this.directories.add(segments.slice(0, index).join('/'));
    }
  }

  async list(
    relativeDirectory: string,
  ): Promise<readonly PrivateFileEntry[]> {
    const prefix = `${relativeDirectory}/`;
    const entries = new Map<string, PrivateFileEntry>();

    for (const directory of this.directories) {
      if (!directory.startsWith(prefix)) {
        continue;
      }
      const remainder = directory.slice(prefix.length);
      const name = remainder.split('/')[0];
      if (name !== undefined && name.length > 0) {
        entries.set(name, { kind: 'directory', name });
      }
    }
    for (const file of this.files.keys()) {
      if (!file.startsWith(prefix)) {
        continue;
      }
      const remainder = file.slice(prefix.length);
      if (!remainder.includes('/') && remainder.length > 0) {
        entries.set(remainder, { kind: 'file', name: remainder });
      }
    }
    return [...entries.values()];
  }

  async readText(relativeFile: string): Promise<string | null> {
    return this.files.get(relativeFile) ?? null;
  }

  async writeText(
    relativeFile: string,
    contents: string,
  ): Promise<void> {
    const parent = parentDirectory(relativeFile);
    if (parent.length > 0) {
      await this.ensureDirectory(parent);
    }
    this.files.set(relativeFile, contents);
  }

  async moveFile(
    sourceRelativeFile: string,
    destinationRelativeFile: string,
    options: Readonly<{ overwrite: boolean }>,
  ): Promise<void> {
    if (this.failNextMove) {
      this.failNextMove = false;
      throw new Error('Injected move failure');
    }
    const source = this.files.get(sourceRelativeFile);
    if (source === undefined) {
      throw new Error('Source file does not exist');
    }
    if (
      !options.overwrite &&
      this.files.has(destinationRelativeFile)
    ) {
      throw new Error('Destination file already exists');
    }
    this.files.set(destinationRelativeFile, source);
    this.files.delete(sourceRelativeFile);
  }

  async deleteFile(relativeFile: string): Promise<void> {
    this.files.delete(relativeFile);
  }

  setFile(relativeFile: string, contents: string): void {
    this.files.set(relativeFile, contents);
  }

  fileNames(relativeDirectory: string): readonly string[] {
    const prefix = `${relativeDirectory}/`;
    return [...this.files.keys()]
      .filter((file) => file.startsWith(prefix))
      .map((file) => file.slice(prefix.length))
      .filter((file) => !file.includes('/'))
      .sort();
  }
}

export class SequenceIdGenerator implements IdGenerator {
  private sequence = 0;

  nextId(): string {
    this.sequence += 1;
    return `id-${String(this.sequence).padStart(6, '0')}`;
  }
}

export class IncrementingClock implements Clock {
  constructor(private currentMs: number) {}

  nowMs(): number {
    const value = this.currentMs;
    this.currentMs += 1;
    return value;
  }
}
