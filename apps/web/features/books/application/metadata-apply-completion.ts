export type MetadataApplyCompletion = Readonly<{
  close: () => void;
  refresh: () => void | Promise<void>;
}>;

/**
 * Finish the UI flow after the server has accepted the metadata update.
 * File writeback is a background concern and must not keep the modal open.
 */
export async function completeMetadataApply({ close, refresh }: MetadataApplyCompletion): Promise<void> {
  close();
  await refresh();
}
