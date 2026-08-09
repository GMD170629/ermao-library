import type { Clock, IdGenerator } from '../../../shared/lib/runtime';
import type { ReaderProgressDocumentStore } from './ports';
import type { ReaderProgressLocation } from '../model/reader-location';
import {
  recordReaderProgress,
  type LocalProgressEntry,
  type ProgressConnection,
  type ProgressOwner,
} from '../model/reader-progress';

export type SaveReaderProgressCommand = Readonly<{
  connection: ProgressConnection;
  owner: ProgressOwner;
  workId: string;
  mediaVersionId: string;
  volumeId: string;
  contentFingerprint: string;
  location: ReaderProgressLocation;
  percent: number;
}>;

export type SaveReaderProgressResult = Readonly<{
  entry: LocalProgressEntry;
  recoveredFromCorruption: boolean;
  maintenanceWarningCount: number;
}>;

export class SaveReaderProgress {
  constructor(
    private readonly store: ReaderProgressDocumentStore,
    private readonly clock: Clock,
    private readonly idGenerator: IdGenerator,
  ) {}

  async execute(
    command: SaveReaderProgressCommand,
  ): Promise<SaveReaderProgressResult> {
    const write = await this.store.update(
      command.connection,
      (current) => {
        const recorded = recordReaderProgress(current, {
          ...command,
          nowMs: this.clock.nowMs(),
          proposedClientId: this.idGenerator.nextId(),
          mutationId: this.idGenerator.nextId(),
        });
        return {
          document: recorded.document,
          result: recorded.entry,
        };
      },
    );
    return {
      entry: write.result,
      recoveredFromCorruption: write.recoveredFromCorruption,
      maintenanceWarningCount: write.maintenanceWarningCount,
    };
  }
}
