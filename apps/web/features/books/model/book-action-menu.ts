export type BookActionId =
  | 'edit'
  | 'metadata'
  | 'upload-cover'
  | 'regenerate-cover'
  | 'kindle';

export function bookActionIds({
  canManage,
  canRegenerateCover,
  kindleSendAvailable
}: {
  canManage: boolean;
  canRegenerateCover: boolean;
  kindleSendAvailable: boolean;
}): BookActionId[] {
  const actions: BookActionId[] = [];
  if (canManage) actions.push('edit', 'metadata', 'upload-cover');
  if (canManage && canRegenerateCover) actions.push('regenerate-cover');
  if (kindleSendAvailable) actions.push('kindle');
  return actions;
}
