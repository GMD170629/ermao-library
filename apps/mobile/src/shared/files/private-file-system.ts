export type PrivateFileEntry = Readonly<{
  kind: 'file' | 'directory';
  name: string;
}>;

export interface PrivateFileSystem {
  ensureDirectory(relativeDirectory: string): Promise<void>;
  list(relativeDirectory: string): Promise<readonly PrivateFileEntry[]>;
  readText(relativeFile: string): Promise<string | null>;
  writeText(relativeFile: string, contents: string): Promise<void>;
  moveFile(
    sourceRelativeFile: string,
    destinationRelativeFile: string,
    options: Readonly<{ overwrite: boolean }>,
  ): Promise<void>;
  deleteFile(relativeFile: string): Promise<void>;
}

export type PrivateFileSystemOperation =
  | 'ensure-directory'
  | 'list'
  | 'read'
  | 'write'
  | 'move'
  | 'delete';

export class PrivateFileSystemError extends Error {
  readonly code = 'PRIVATE_FILE_SYSTEM_ERROR';

  constructor(
    readonly operation: PrivateFileSystemOperation,
    readonly relativePath: string,
    cause: unknown,
  ) {
    super(`Private file operation failed: ${operation}`, { cause });
    this.name = 'PrivateFileSystemError';
  }
}
