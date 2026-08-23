import { READER_FORMAT_CAPABILITIES } from '@shuku/reader-core';

export const commonAudiobookExtensions = [
  '.m4b', '.m4a', '.m4r', '.mp3', '.mp2', '.aac', '.flac', '.wav', '.wave',
  '.rf64', '.w64', '.ogg', '.oga', '.opus', '.weba'
] as const;

export const compatibilityAudiobookExtensions = [
  '.ac3', '.adx', '.aif', '.aifc', '.aiff', '.amr', '.ape', '.aptx', '.aptxhd',
  '.au', '.caf', '.dff', '.dsf', '.dts', '.eac3', '.g722', '.g726', '.gsm',
  '.lbc', '.mka', '.mlp', '.mpc', '.oma', '.qcp', '.ra', '.shn', '.snd', '.sph',
  '.spx', '.tak', '.thd', '.tta', '.voc', '.wma', '.wv', '.xma'
] as const;

export const importFormatGroups = [
  { id: 'ebook', formats: READER_FORMAT_CAPABILITIES.filter((entry) => entry.readerKind === 'reflowable').map((entry) => entry.extension) },
  { id: 'document-comic', formats: READER_FORMAT_CAPABILITIES.filter((entry) => entry.readerKind !== 'reflowable' && entry.sourceFormat !== 'image_dir').map((entry) => entry.extension) },
  { id: 'common-audio', formats: commonAudiobookExtensions },
  { id: 'compatibility-audio', formats: compatibilityAudiobookExtensions }
] as const;

export const allImportExtensions = importFormatGroups.flatMap((group) => [...group.formats]);

export const importFileInputAccept = allImportExtensions.join(',');
