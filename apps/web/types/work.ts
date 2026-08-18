export type VolumeFormat = 'COMIC' | 'CBZ' | 'CBR' | 'RAR' | 'ZIP' | 'EPUB' | 'PDF' | 'AUDIO' | 'MP3' | 'M4A' | 'M4B' | 'MOBI' | 'AZW' | 'AZW3' | 'PRC' | 'FB2' | 'TXT';
export type ReadingFormat = VolumeFormat;
export type MediaKind = 'EBOOK' | 'COMIC' | 'AUDIOBOOK';
export type ReaderType = 'reflowable' | 'comic' | 'pdf' | 'audio';
export type ClassificationSource = 'AUTO' | 'MONITOR_FOLDER' | 'USER' | 'INHERITED' | 'LEGACY';
export type PublicationStatus = 'UNKNOWN' | 'ONGOING' | 'COMPLETED' | 'HIATUS' | 'CANCELLED';
export type TrackingStatus = 'NOT_TRACKING' | 'TRACKING' | 'PAUSED' | 'IGNORED';

export const IMPLICIT_VERSION_SOURCE_KEY = '__implicit__';

export type LibraryFileResource = Readonly<{
  id: string;
  volumeId: string;
  path: string;
  mimeType: string;
  kind: string;
  sortOrder: number;
  sizeBytes: number;
  size: string;
  durationMs?: number | null;
  codec?: string | null;
  bitrate?: number | null;
  sampleRate?: number | null;
  channels?: number | null;
  discNumber?: number | null;
  trackNumber?: number | null;
  url?: string;
}>;

export type VolumeResource = Readonly<{
  id: string;
  versionId: string;
  title: string;
  volumeIndex: number | null;
  sortOrder: number;
  format: VolumeFormat;
  readerType: ReaderType;
  classification: Readonly<{
    source: ClassificationSource;
    reason: string;
    suggestedMediaKind: MediaKind | null;
  }>;
  derivedFromVolumeId: string | null;
  publisher: string | null;
  publishedAt: string | null;
  language: string | null;
  isbn: string | null;
  identifier: string | null;
  narrator: string | null;
  abridged: boolean | null;
  importStatus: string;
  importError: string | null;
  coverUrl: string;
  sizeBytes: number;
  pageCount: number | null;
  chapterCount: number | null;
  durationMs: number | null;
  trackCount: number | null;
  progress: number;
  lastReadAt: string | null;
  hidden: boolean;
  readable: boolean;
  kindleSendAvailable: boolean;
  files: LibraryFileResource[];
}>;

export type VersionResource = Readonly<{
  id: string;
  sourceKey: string;
  sourceName: string | null;
  completed: boolean;
  volumeCount: number;
  sizeBytes: number;
  volumes: VolumeResource[];
}>;

export type WorkView = Readonly<{
  id: string;
  title: string;
  author: string;
  description: string;
  seriesName: string | null;
  seriesIndex: number | null;
  tags: string[];
  publicationStatus: PublicationStatus;
  trackingStatus: TrackingStatus;
  ignored: boolean;
  organized: boolean;
  metadataQuality: number;
  addedAt: string;
  updatedAt: string;
  coverUrl: string;
  coverStatus: string;
  gradient: string;
  continueVolumeId: string | null;
  completed: boolean;
  versions: VersionResource[];
}>;

export type SeriesSummary = Readonly<{
  name: string;
  bookCount: number;
  latestUpdatedAt: string | null;
}>;

export function allWorkVolumes(work: WorkView): VolumeResource[] {
  return work.versions.flatMap((version) => version.volumes);
}

export function volumeById(work: WorkView, volumeId: string | null | undefined): VolumeResource | null {
  if (!volumeId) return null;
  return allWorkVolumes(work).find((volume) => volume.id === volumeId) ?? null;
}

export function versionById(work: WorkView, versionId: string | null | undefined): VersionResource | null {
  if (!versionId) return null;
  return work.versions.find((version) => version.id === versionId) ?? null;
}
