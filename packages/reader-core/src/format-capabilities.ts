import type { ReaderKind, ReflowableFormat } from './types';

export type SupportedReaderSourceFormat = ReflowableFormat | 'cbz' | 'zip' | 'cbr' | 'rar' | 'image_dir' | 'pdf';

export type ReaderFormatCapability = Readonly<{
  sourceFormat: SupportedReaderSourceFormat;
  extension: `.${string}`;
  readerKind: ReaderKind;
}>;

export const READER_FORMAT_CAPABILITIES: readonly ReaderFormatCapability[] = [
  { sourceFormat: 'epub', extension: '.epub', readerKind: 'reflowable' },
  { sourceFormat: 'mobi', extension: '.mobi', readerKind: 'reflowable' },
  { sourceFormat: 'azw', extension: '.azw', readerKind: 'reflowable' },
  { sourceFormat: 'azw3', extension: '.azw3', readerKind: 'reflowable' },
  { sourceFormat: 'prc', extension: '.prc', readerKind: 'reflowable' },
  { sourceFormat: 'txt', extension: '.txt', readerKind: 'reflowable' },
  { sourceFormat: 'fb2', extension: '.fb2', readerKind: 'reflowable' },
  { sourceFormat: 'cbz', extension: '.cbz', readerKind: 'comic' },
  { sourceFormat: 'zip', extension: '.zip', readerKind: 'comic' },
  { sourceFormat: 'cbr', extension: '.cbr', readerKind: 'comic' },
  { sourceFormat: 'rar', extension: '.rar', readerKind: 'comic' },
  { sourceFormat: 'image_dir', extension: '.image-dir', readerKind: 'comic' },
  { sourceFormat: 'pdf', extension: '.pdf', readerKind: 'pdf' }
] as const;

const capabilityBySourceFormat = new Map(
  READER_FORMAT_CAPABILITIES.map((capability) => [capability.sourceFormat, capability])
);

export function parseSupportedReaderSourceFormat(value: unknown): SupportedReaderSourceFormat | null {
  if (typeof value !== 'string') return null;
  const normalized = value.trim().toLowerCase();
  return capabilityBySourceFormat.has(normalized as SupportedReaderSourceFormat)
    ? normalized as SupportedReaderSourceFormat
    : null;
}

export function readerFormatCapability(
  sourceFormat: SupportedReaderSourceFormat
): ReaderFormatCapability {
  const capability = capabilityBySourceFormat.get(sourceFormat);
  if (!capability) throw new Error(`Unsupported reader source format: ${sourceFormat}`);
  return capability;
}
