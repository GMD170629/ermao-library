import type { ReaderKind } from '@shuku/reader-core';

import type { ReaderProgressDocumentStore } from './ports';
import {
  findReaderProgress,
  type LocalProgressEntryV2,
  type ProgressConnection,
  type ProgressOwner,
} from '../model/reader-progress';

export type LoadReaderProgressQuery = Readonly<{
  connection: ProgressConnection;
  owner: ProgressOwner;
  volumeId: string;
  contentFingerprint: string;
  readerKind: ReaderKind;
}>;

export type LoadReaderProgressResult =
  | Readonly<{
      outcome: 'not-found';
      recoveredFromCorruption: boolean;
    }>
  | Readonly<{
      outcome: 'found';
      entry: LocalProgressEntryV2;
      recoveredFromCorruption: boolean;
    }>;

export class LoadReaderProgress {
  constructor(private readonly store: ReaderProgressDocumentStore) {}

  async execute(
    query: LoadReaderProgressQuery,
  ): Promise<LoadReaderProgressResult> {
    const read = await this.store.read(query.connection);
    if (read.document === null) {
      return {
        outcome: 'not-found',
        recoveredFromCorruption: false,
      };
    }

    const entry = findReaderProgress(read.document, query);
    return entry === null
      ? {
          outcome: 'not-found',
          recoveredFromCorruption: read.recoveredFromCorruption,
        }
      : {
          outcome: 'found',
          entry,
          recoveredFromCorruption: read.recoveredFromCorruption,
        };
  }
}
