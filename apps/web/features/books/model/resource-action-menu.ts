export type ResourceActionId =
  | 'download'
  | 'edit'
  | 'set-media-kind'
  | 'set-ebook'
  | 'set-comic'
  | 'set-audiobook';

export type ResourceActionAvailability = Readonly<{
  action: ResourceActionId;
  disabled: boolean;
}>;

export function resourceActionAvailability({
  canManage,
  readable,
  mediaKind,
  selectionCount = 1
}: {
  canManage: boolean;
  readable: boolean;
  mediaKind: 'EBOOK' | 'COMIC' | 'AUDIOBOOK';
  selectionCount?: number;
}): ResourceActionAvailability[] {
  if (!canManage) return [];
  const actions: ResourceActionAvailability[] = [
    { action: 'download', disabled: !readable },
    { action: 'edit', disabled: selectionCount !== 1 },
    { action: 'set-media-kind', disabled: false }
  ];
  if (mediaKind !== 'EBOOK') actions.push({ action: 'set-ebook', disabled: false });
  if (mediaKind !== 'COMIC') actions.push({ action: 'set-comic', disabled: false });
  if (mediaKind !== 'AUDIOBOOK') actions.push({ action: 'set-audiobook', disabled: false });
  return actions;
}
