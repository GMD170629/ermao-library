import type { MediaKind } from '../../../types/work';

export function structureFileLabel(mediaKind: MediaKind, path: string): string {
  if (mediaKind !== 'AUDIOBOOK') return path;

  const segments = path.split(/[\\/]/u);
  return segments.at(-1) || path;
}
