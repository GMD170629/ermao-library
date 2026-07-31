import type {
  ProgressConnection,
  ReaderProgressDocumentV1,
} from '../model/reader-progress';

export type ProgressDocumentReadResult = Readonly<{
  document: ReaderProgressDocumentV1 | null;
  recoveredFromCorruption: boolean;
}>;

export type ProgressDocumentMutation<Result> = Readonly<{
  document: ReaderProgressDocumentV1;
  result: Result;
}>;

export type ProgressDocumentWriteResult<Result> = Readonly<{
  document: ReaderProgressDocumentV1;
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
      current: ReaderProgressDocumentV1 | null,
    ) => ProgressDocumentMutation<Result>,
  ): Promise<ProgressDocumentWriteResult<Result>>;
}
