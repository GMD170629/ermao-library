export type VolumeActionId =
  | 'open'
  | 'download'
  | 'edit'
  | 'set-media-kind'
  | 'set-ebook'
  | 'set-comic'
  | 'set-audiobook'
  | 'split'
  | 'transfer'
  | 'delete';

export type VolumeActionAvailability = Readonly<{
  action: VolumeActionId;
  disabled: boolean;
}>;

export function volumeActionAvailability({
  canManage,
  readable,
  mediaKind
}: {
  canManage: boolean;
  readable: boolean;
  mediaKind: 'EBOOK' | 'COMIC' | 'AUDIOBOOK';
}): VolumeActionAvailability[] {
  if (!canManage) return [];
  const actions: VolumeActionAvailability[] = [
    { action: 'open', disabled: !readable },
    { action: 'download', disabled: !readable },
    { action: 'edit', disabled: false },
    { action: 'set-media-kind', disabled: false }
  ];
  if (mediaKind !== 'EBOOK') actions.push({ action: 'set-ebook', disabled: false });
  if (mediaKind !== 'COMIC') actions.push({ action: 'set-comic', disabled: false });
  if (mediaKind !== 'AUDIOBOOK') actions.push({ action: 'set-audiobook', disabled: false });
  actions.push(
    { action: 'split', disabled: false },
    { action: 'transfer', disabled: false },
    { action: 'delete', disabled: false }
  );
  return actions;
}
