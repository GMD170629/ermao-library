import type { ReaderKind, ReflowableFormat } from './types';

export type SupportedReaderSourceFormat = ReflowableFormat | 'cbz' | 'zip' | 'cbr' | 'rar' | 'image_dir' | 'pdf';
export type ReaderDeliveryMode = 'DOWNLOAD_ORIGINAL' | 'STREAM' | 'UNSUPPORTED';

export type ReaderFormatCapability = Readonly<{
  sourceFormat: SupportedReaderSourceFormat;
  extension: `.${string}`;
  readerKind: ReaderKind;
  deliveryMode: ReaderDeliveryMode;
}>;

export const READER_FORMAT_CAPABILITIES: readonly ReaderFormatCapability[] = [
  { sourceFormat: 'epub', extension: '.epub', readerKind: 'reflowable', deliveryMode: 'DOWNLOAD_ORIGINAL' },
  { sourceFormat: 'mobi', extension: '.mobi', readerKind: 'reflowable', deliveryMode: 'DOWNLOAD_ORIGINAL' },
  { sourceFormat: 'azw', extension: '.azw', readerKind: 'reflowable', deliveryMode: 'DOWNLOAD_ORIGINAL' },
  { sourceFormat: 'azw3', extension: '.azw3', readerKind: 'reflowable', deliveryMode: 'DOWNLOAD_ORIGINAL' },
  { sourceFormat: 'prc', extension: '.prc', readerKind: 'reflowable', deliveryMode: 'DOWNLOAD_ORIGINAL' },
  { sourceFormat: 'txt', extension: '.txt', readerKind: 'reflowable', deliveryMode: 'DOWNLOAD_ORIGINAL' },
  { sourceFormat: 'fb2', extension: '.fb2', readerKind: 'reflowable', deliveryMode: 'DOWNLOAD_ORIGINAL' },
  { sourceFormat: 'cbz', extension: '.cbz', readerKind: 'comic', deliveryMode: 'STREAM' },
  { sourceFormat: 'zip', extension: '.zip', readerKind: 'comic', deliveryMode: 'STREAM' },
  { sourceFormat: 'cbr', extension: '.cbr', readerKind: 'comic', deliveryMode: 'STREAM' },
  { sourceFormat: 'rar', extension: '.rar', readerKind: 'comic', deliveryMode: 'STREAM' },
  { sourceFormat: 'image_dir', extension: '.image-dir', readerKind: 'comic', deliveryMode: 'STREAM' },
  { sourceFormat: 'pdf', extension: '.pdf', readerKind: 'pdf', deliveryMode: 'STREAM' }
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
