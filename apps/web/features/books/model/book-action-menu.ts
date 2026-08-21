export type BookActionId =
  | 'edit'
  | 'metadata'
  | 'upload-cover'
  | 'regenerate-cover'
  | 'kindle';

export function bookActionIds({
  canManage,
  kindleSendAvailable
}: {
  canManage: boolean;
  kindleSendAvailable: boolean;
}): BookActionId[] {
  const actions: BookActionId[] = [];
  if (canManage) actions.push('edit', 'metadata', 'upload-cover', 'regenerate-cover');
  if (kindleSendAvailable) actions.push('kindle');
  return actions;
}
