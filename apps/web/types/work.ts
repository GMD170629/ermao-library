export type VolumeFormat = 'COMIC' | 'EPUB' | 'PDF' | 'AUDIO' | 'MOBI' | 'AZW' | 'AZW3' | 'PRC' | 'FB2' | 'TXT';
export type ReadingFormat = VolumeFormat;
export type MediaKind = 'EBOOK' | 'COMIC' | 'AUDIOBOOK';
export type WorkDetailTabKey = MediaKind | 'STRUCTURE';
export type PublicationStatus = 'UNKNOWN' | 'ONGOING' | 'COMPLETED' | 'HIATUS' | 'CANCELLED';
export type TrackingStatus = 'NOT_TRACKING' | 'TRACKING' | 'PAUSED' | 'IGNORED';

export type WorkDetailTab = Readonly<{
  key: WorkDetailTabKey;
  label: string;
  sortOrder: number;
}>;

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
  mediaVersionId: string;
  title: string;
  volumeIndex: number | null;
  sortOrder: number;
  format: VolumeFormat;
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
  pageCount: number | null;
  chapterCount: number | null;
  durationMs: number | null;
  trackCount: number | null;
  progress: number;
  lastReadAt: string | null;
  hidden: boolean;
  readable: boolean;
  conversionAvailable: boolean;
  files: LibraryFileResource[];
}>;

export type MediaVersionResource = Readonly<{
  id: string;
  mediaKind: MediaKind;
  completed: boolean;
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
  recentMediaKind: MediaKind | null;
  continueVolumeId: string | null;
  completed: boolean;
  mediaVersions: MediaVersionResource[];
}>;

export type SeriesSummary = Readonly<{
  name: string;
  bookCount: number;
  latestUpdatedAt: string | null;
}>;

export function allWorkVolumes(work: WorkView): VolumeResource[] {
  return work.mediaVersions.flatMap((mediaVersion) => mediaVersion.volumes);
}

export function mediaVersionForKind(work: WorkView, mediaKind: MediaKind): MediaVersionResource | null {
  return work.mediaVersions.find((mediaVersion) => mediaVersion.mediaKind === mediaKind) ?? null;
}

export function volumeById(work: WorkView, volumeId: string | null | undefined): VolumeResource | null {
  if (!volumeId) return null;
  return allWorkVolumes(work).find((volume) => volume.id === volumeId) ?? null;
}
