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
  { id: 'ebook', formats: ['.epub', '.mobi', '.azw', '.azw3', '.prc', '.fb2', '.txt'] },
  { id: 'document-comic', formats: ['.pdf', '.cbz', '.zip', '.cbr', '.rar'] },
  { id: 'common-audio', formats: commonAudiobookExtensions },
  { id: 'compatibility-audio', formats: compatibilityAudiobookExtensions }
] as const;

export const allImportExtensions = importFormatGroups.flatMap((group) => [...group.formats]);

export const importFileInputAccept = allImportExtensions.join(',');
