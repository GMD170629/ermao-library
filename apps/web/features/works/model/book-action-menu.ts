export type BookActionId =
  | 'edit'
  | 'metadata'
  | 'upload-cover'
  | 'regenerate-cover'
  | 'download'
  | 'kindle'
  | 'delete';

export function bookActionIds({
  canManage,
  hasDownload,
  kindleSendAvailable
}: {
  canManage: boolean;
  hasDownload: boolean;
  kindleSendAvailable: boolean;
}): BookActionId[] {
  const actions: BookActionId[] = [];
  if (canManage) actions.push('edit', 'metadata', 'upload-cover', 'regenerate-cover');
  if (hasDownload) actions.push('download');
  if (kindleSendAvailable) actions.push('kindle');
  if (canManage) actions.push('delete');
  return actions;
}
