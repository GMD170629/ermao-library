import type { MediaKind } from '../../../types/work';

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
  mediaKind,
  hasDownload
}: {
  canManage: boolean;
  mediaKind: MediaKind | null;
  hasDownload: boolean;
}): BookActionId[] {
  const actions: BookActionId[] = [];
  if (canManage) actions.push('edit', 'metadata', 'upload-cover', 'regenerate-cover');
  if (mediaKind !== 'AUDIOBOOK' && hasDownload) actions.push('download');
  if (mediaKind === 'EBOOK') actions.push('kindle');
  if (canManage) actions.push('delete');
  return actions;
}
