import type {
  ProgressConnection,
  ReaderProgressDocument,
} from '../model/reader-progress';

export type ProgressDocumentReadResult = Readonly<{
  document: ReaderProgressDocument | null;
  recoveredFromCorruption: boolean;
}>;

export type ProgressDocumentMutation<Result> = Readonly<{
  document: ReaderProgressDocument;
  result: Result;
}>;

export type ProgressDocumentWriteResult<Result> = Readonly<{
  document: ReaderProgressDocument;
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
      current: ReaderProgressDocument | null,
    ) => ProgressDocumentMutation<Result>,
  ): Promise<ProgressDocumentWriteResult<Result>>;
}
