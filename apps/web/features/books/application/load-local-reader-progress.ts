import type { ReaderV5PendingMutation, ReaderV5ProgressIdentity, ReaderV5Storage } from '../../../lib/reader';

type BookProgressIdentity = Omit<ReaderV5ProgressIdentity, 'clientId' | 'resourceId'>;

/** Load local reports that may override a freshly fetched book projection. */
export async function loadBookLocalProgress(
  storage: Pick<ReaderV5Storage, 'getClientId' | 'getV5PendingProgressForIdentity'>,
  identity: BookProgressIdentity,
  resourceIds: readonly string[]
): Promise<ReaderV5PendingMutation[]> {
  const clientId = await storage.getClientId();
  // Acknowledged local history can be older than another client's server report.
  const records = await Promise.all(resourceIds.map((resourceId) => storage.getV5PendingProgressForIdentity({
    ...identity, clientId, resourceId
  })));
  return records.filter((record): record is NonNullable<typeof record> => record !== null);
}
