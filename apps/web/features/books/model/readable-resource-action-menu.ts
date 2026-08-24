export type ReadableResourceActionId =
  | 'edit'
  | 'upload-cover'
  | 'regenerate-cover'
  | 'recognize'
  | 'kindle'
  | 'delete';

export function readableResourceActionIds({
  canManage,
  kindleSendAvailable
}: {
  canManage: boolean;
  kindleSendAvailable: boolean;
}): ReadableResourceActionId[] {
  const actions: ReadableResourceActionId[] = [];
  if (canManage) actions.push('edit', 'upload-cover', 'regenerate-cover', 'recognize');
  if (kindleSendAvailable) actions.push('kindle');
  if (canManage) actions.push('delete');
  return actions;
}
