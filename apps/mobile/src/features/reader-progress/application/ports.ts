import type {
  ProgressConnection,
  ReaderProgressDocumentV2,
} from '../model/reader-progress';

export type ProgressDocumentReadResult = Readonly<{
  document: ReaderProgressDocumentV2 | null;
  recoveredFromCorruption: boolean;
}>;

export type ProgressDocumentMutation<Result> = Readonly<{
  document: ReaderProgressDocumentV2;
  result: Result;
}>;

export type ProgressDocumentWriteResult<Result> = Readonly<{
  document: ReaderProgressDocumentV2;
  result: Result;
  recoveredFromCorruption: boolean;
  maintenanceWarningCount: number;
}>;

export interface ReaderProgressDocumentStore {
  read(
    connection: ProgressConnection,
  ): Promise<ProgressDocumentReadResult>;
  update<Result>(
    connection: ProgressConnection,
    mutate: (
      current: ReaderProgressDocumentV2 | null,
    ) => ProgressDocumentMutation<Result>,
  ): Promise<ProgressDocumentWriteResult<Result>>;
}
