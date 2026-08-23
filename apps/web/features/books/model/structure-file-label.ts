import type { ReaderType } from '../../../types/book';

export function structureFileLabel(readerType: ReaderType, path: string): string {
  if (readerType !== 'audio') return path;

  const segments = path.split(/[\\/]/u);
  return segments.at(-1) || path;
}
