import type { IdGenerator } from '../lib/runtime';
import type { ValidationResult } from '../validation/unknown';
import type {
  PrivateFileEntry,
  PrivateFileSystem,
} from './private-file-system';
import type { SnapshotOperationCoordinator } from './snapshot-operation-coordinator';

const SNAPSHOT_FILE_PATTERN =
  /^snapshot-(?<generation>[0-9]{12})-(?<id>[A-Za-z0-9-]+)\.json$/;
const TEMPORARY_FILE_PATTERN =
  /^\.snapshot-(?<generation>[0-9]{12})-(?<id>[A-Za-z0-9-]+)\.tmp$/;
const SAFE_FILE_TOKEN = /^[A-Za-z0-9-]{1,128}$/;
const MAX_GENERATION = 999_999_999_999;
const DEFAULT_MAX_CHARACTERS = 8 * 1024 * 1024;

export interface JsonDocumentCodec<Value> {
  decode(value: unknown): ValidationResult<Value>;
  encode(value: Value): unknown;
}

export interface GenerationDocument {
  readonly generation: number;
}

export type SnapshotReadResult<Value> =
  | Readonly<{ status: 'empty' }>
  | Readonly<{
      status: 'loaded';
      value: Value;
      sourceFileName: string;
      recoveredFromCorruption: boolean;
      rejectedNewerSnapshots: number;
    }>;

export type SnapshotMaintenanceIssue =
  | Readonly<{
      operation: 'list-directory';
      target: string;
    }>
  | Readonly<{
      operation: 'delete-file';
      target: string;
    }>;

export type SnapshotMutation<Value, Result> = Readonly<{
  document: Value;
  result: Result;
}>;

export type SnapshotUpdateResult<Value, Result> = Readonly<{
  value: Value;
  result: Result;
  recoveredFromCorruption: boolean;
  rejectedNewerSnapshots: number;
  maintenanceIssues: readonly SnapshotMaintenanceIssue[];
}>;

export type SnapshotCorruptResetResult =
  | Readonly<{ status: 'not-corrupt'; deletedFileCount: 0 }>
  | Readonly<{ status: 'reset'; deletedFileCount: number }>;

export type SnapshotDocumentErrorCode =
  | 'CORRUPT_DOCUMENT'
  | 'GENERATION_CONFLICT'
  | 'INVALID_WRITE';

export class SnapshotDocumentError extends Error {
  constructor(
    readonly code: SnapshotDocumentErrorCode,
    message: string,
    options?: ErrorOptions,
  ) {
    super(message, options);
    this.name = 'SnapshotDocumentError';
  }
}

type SnapshotCandidate = Readonly<{
  fileName: string;
  generation: number;
}>;

type DecodedText<Value> =
  | Readonly<{ ok: true; value: Value }>
  | Readonly<{ ok: false }>;

export class SnapshotDocumentStore<Value extends GenerationDocument> {
  constructor(
    private readonly fileSystem: PrivateFileSystem,
    private readonly directory: string,
    private readonly codec: JsonDocumentCodec<Value>,
    private readonly idGenerator: IdGenerator,
    private readonly operationCoordinator: SnapshotOperationCoordinator,
    private readonly maximumCharacters = DEFAULT_MAX_CHARACTERS,
  ) {}

  async read(): Promise<SnapshotReadResult<Value>> {
    return this.operationCoordinator.run(this.directory, () =>
      this.readUnlocked(),
    );
  }

  async update<Result>(
    mutate: (current: Value | null) => SnapshotMutation<Value, Result>,
  ): Promise<SnapshotUpdateResult<Value, Result>> {
    return this.operationCoordinator.run(this.directory, async () => {
      const current = await this.readUnlocked();
      const previous =
        current.status === 'loaded' ? current.value : null;
      const expectedGeneration = (previous?.generation ?? 0) + 1;
      if (expectedGeneration > MAX_GENERATION) {
        throw new SnapshotDocumentError(
          'GENERATION_CONFLICT',
          'Snapshot generation limit has been reached',
        );
      }

      const mutation = mutate(previous);
      if (mutation.document.generation !== expectedGeneration) {
        throw new SnapshotDocumentError(
          'GENERATION_CONFLICT',
          'Snapshot mutation returned an unexpected generation',
        );
      }

      const serialized = this.serializeAndValidate(
        mutation.document,
        expectedGeneration,
      );
      const token = this.idGenerator.nextId();
      if (!SAFE_FILE_TOKEN.test(token)) {
        throw new SnapshotDocumentError(
          'INVALID_WRITE',
          'Snapshot identifier contains unsupported characters',
        );
      }

      const generationToken = String(expectedGeneration).padStart(12, '0');
      const temporaryFileName = `.snapshot-${generationToken}-${token}.tmp`;
      const snapshotFileName = `snapshot-${generationToken}-${token}.json`;
      const temporaryPath = this.childPath(temporaryFileName);
      const snapshotPath = this.childPath(snapshotFileName);

      await this.fileSystem.ensureDirectory(this.directory);
      await this.fileSystem.writeText(temporaryPath, serialized);
      const staged = await this.fileSystem.readText(temporaryPath);
      if (
        staged === null ||
        !this.decodeText(staged, expectedGeneration).ok
      ) {
        throw new SnapshotDocumentError(
          'INVALID_WRITE',
          'Staged snapshot failed its read-after-write validation',
        );
      }

      await this.fileSystem.moveFile(temporaryPath, snapshotPath, {
        overwrite: false,
      });

      const maintenanceIssues = await this.cleanupAfterCommit(
        snapshotFileName,
        current.status === 'loaded' ? current.sourceFileName : null,
      );

      return {
        value: mutation.document,
        result: mutation.result,
        recoveredFromCorruption:
          current.status === 'loaded' &&
          current.recoveredFromCorruption,
        rejectedNewerSnapshots:
          current.status === 'loaded'
            ? current.rejectedNewerSnapshots
            : 0,
        maintenanceIssues,
      };
    });
  }

  async resetCorrupt(
    assertCanReset: () => void = () => undefined,
  ): Promise<SnapshotCorruptResetResult> {
    return this.operationCoordinator.run(this.directory, async () => {
      try {
        await this.readUnlocked();
        return { status: 'not-corrupt', deletedFileCount: 0 };
      } catch (cause: unknown) {
        if (
          !(cause instanceof SnapshotDocumentError) ||
          cause.code !== 'CORRUPT_DOCUMENT'
        ) {
          throw cause;
        }
      }

      assertCanReset();
      const entries = await this.fileSystem.list(this.directory);
      const managedFiles = entries.filter(
        (entry) =>
          entry.kind === 'file' &&
          (this.snapshotCandidate(entry.name) !== null ||
            TEMPORARY_FILE_PATTERN.test(entry.name)),
      );
      for (const entry of managedFiles) {
        await this.fileSystem.deleteFile(this.childPath(entry.name));
      }
      return {
        status: 'reset',
        deletedFileCount: managedFiles.length,
      };
    });
  }

  private async readUnlocked(): Promise<SnapshotReadResult<Value>> {
    const entries = await this.fileSystem.list(this.directory);
    const candidates = entries
      .filter((entry) => entry.kind === 'file')
      .map((entry) => this.snapshotCandidate(entry.name))
      .filter(
        (candidate): candidate is SnapshotCandidate => candidate !== null,
      )
      .sort(
        (left, right) =>
          right.generation - left.generation ||
          right.fileName.localeCompare(left.fileName),
      );

    if (candidates.length === 0) {
      return { status: 'empty' };
    }

    let rejectedNewerSnapshots = 0;
    for (const candidate of candidates) {
      const text = await this.fileSystem.readText(
        this.childPath(candidate.fileName),
      );
      if (text === null) {
        rejectedNewerSnapshots += 1;
        continue;
      }

      const decoded = this.decodeText(text, candidate.generation);
      if (!decoded.ok) {
        rejectedNewerSnapshots += 1;
        continue;
      }

      return {
        status: 'loaded',
        value: decoded.value,
        sourceFileName: candidate.fileName,
        recoveredFromCorruption: rejectedNewerSnapshots > 0,
        rejectedNewerSnapshots,
      };
    }

    throw new SnapshotDocumentError(
      'CORRUPT_DOCUMENT',
      'No valid snapshot remains in the private document store',
    );
  }

  private serializeAndValidate(
    document: Value,
    expectedGeneration: number,
  ): string {
    let serialized: string;
    try {
      serialized = `${JSON.stringify(this.codec.encode(document), null, 2)}\n`;
    } catch (cause: unknown) {
      throw new SnapshotDocumentError(
        'INVALID_WRITE',
        'Snapshot could not be serialized',
        { cause },
      );
    }

    if (!this.decodeText(serialized, expectedGeneration).ok) {
      throw new SnapshotDocumentError(
        'INVALID_WRITE',
        'Snapshot codec rejected its serialized output',
      );
    }

    return serialized;
  }

  private decodeText(
    text: string,
    expectedGeneration: number,
  ): DecodedText<Value> {
    if (text.length > this.maximumCharacters) {
      return { ok: false };
    }

    try {
      const parsed: unknown = JSON.parse(text);
      const decoded = this.codec.decode(parsed);
      if (
        !decoded.ok ||
        decoded.value.generation !== expectedGeneration
      ) {
        return { ok: false };
      }
      return decoded;
    } catch (cause: unknown) {
      if (cause instanceof SyntaxError) {
        return { ok: false };
      }
      throw cause;
    }
  }

  private async cleanupAfterCommit(
    currentFileName: string,
    previousFileName: string | null,
  ): Promise<readonly SnapshotMaintenanceIssue[]> {
    const preservedFiles = new Set(
      previousFileName === null
        ? [currentFileName]
        : [currentFileName, previousFileName],
    );
    let entries: readonly PrivateFileEntry[];
    try {
      entries = await this.fileSystem.list(this.directory);
    } catch {
      return [
        {
          operation: 'list-directory',
          target: this.directory,
        },
      ];
    }
    const issues: SnapshotMaintenanceIssue[] = [];

    for (const entry of entries) {
      if (entry.kind !== 'file' || preservedFiles.has(entry.name)) {
        continue;
      }

      const candidate = this.snapshotCandidate(entry.name);
      const isTemporary = TEMPORARY_FILE_PATTERN.test(entry.name);
      if (candidate === null && !isTemporary) {
        continue;
      }

      try {
        if (candidate !== null) {
          const text = await this.fileSystem.readText(
            this.childPath(entry.name),
          );
          if (
            text === null ||
            !this.decodeText(text, candidate.generation).ok
          ) {
            continue;
          }
        }
        await this.fileSystem.deleteFile(this.childPath(entry.name));
      } catch (cause: unknown) {
        issues.push({
          operation: 'delete-file',
          target: entry.name,
        });
        if (cause instanceof SnapshotDocumentError) {
          continue;
        }
      }
    }

    return issues;
  }

  private snapshotCandidate(fileName: string): SnapshotCandidate | null {
    const match = SNAPSHOT_FILE_PATTERN.exec(fileName);
    const generationText = match?.groups?.generation;
    if (generationText === undefined) {
      return null;
    }
    const generation = Number(generationText);
    if (
      !Number.isSafeInteger(generation) ||
      generation < 1 ||
      generation > MAX_GENERATION
    ) {
      return null;
    }
    return { fileName, generation };
  }

  private childPath(fileName: string): string {
    return `${this.directory}/${fileName}`;
  }

}
