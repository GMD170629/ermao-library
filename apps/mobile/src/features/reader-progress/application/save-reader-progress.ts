import type { ReaderLocation } from '@shuku/reader-core';

import type { Clock, IdGenerator } from '../../../shared/lib/runtime';
import type { ReaderProgressDocumentStore } from './ports';
import {
  recordReaderProgress,
  type LocalProgressEntryV1,
  type ProgressConnection,
  type ProgressOwner,
} from '../model/reader-progress';

export type SaveReaderProgressCommand = Readonly<{
  connection: ProgressConnection;
  owner: ProgressOwner;
  workId: string;
  editionId: string;
  volumeId: string | null;
  contentFingerprint: string;
  location: ReaderLocation;
  percent: number;
}>;

export type SaveReaderProgressResult = Readonly<{
  entry: LocalProgressEntryV1;
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
