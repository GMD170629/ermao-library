export type ResourceFormat =
  | 'COMIC' | 'CBZ' | 'CBR' | 'RAR' | 'ZIP' | 'EPUB' | 'PDF' | 'AUDIO'
  | 'MP3' | 'M4A' | 'M4B' | 'MOBI' | 'AZW' | 'AZW3' | 'PRC' | 'FB2' | 'TXT'
  | 'IMAGE_DIR' | 'AUDIOBOOK_DIR';
export type MediaKind = 'EBOOK' | 'COMIC' | 'AUDIOBOOK';
export type ReaderType = 'reflowable' | 'comic' | 'pdf' | 'audio';
export type ClassificationSource = 'AUTO' | 'LIBRARY_RULE' | 'USER';
export type PublicationStatus = 'UNKNOWN' | 'ONGOING' | 'COMPLETED' | 'HIATUS' | 'CANCELLED';
export type TrackingStatus = 'NOT_TRACKING' | 'TRACKING' | 'PAUSED' | 'IGNORED';

export type ResourceImportSummary = Readonly<{
  ready: number;
  pending: number;
  failed: number;
}>;

export type ResourceAssetView = Readonly<{
  id: string;
  resourceId: string;
  sourceNodeId: string;
  role: string;
  mimeType: string;
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
  url: string;
  downloadUrl: string;
}>;

export type ReadableResourceView = Readonly<{
  id: string;
  bookId: string;
  sourceNodeId: string;
  title: string;
  description: string;
  resourceIndex: number | null;
  sortOrder: number;
  format: ResourceFormat;
  readerType: ReaderType;
  classification: Readonly<{
    source: ClassificationSource;
    reason: string;
    suggestedMediaKind: MediaKind | null;
  }>;
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
  assets: ResourceAssetView[];
}>;

export type BookView = Readonly<{
  id: string;
  sourceNodeId: string;
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
  continueResourceId: string | null;
  continueResourceTitle?: string | null;
  continueResourceProgress?: number;
  continueReaderType?: ReaderType | null;
  completed: boolean;
  resources: ReadableResourceView[];
  resourceImportSummary: ResourceImportSummary;
  availableMediaKinds?: MediaKind[];
}>;

export function allBookResources(book: BookView): ReadableResourceView[] {
  return book.resources;
}

export function resourceById(book: BookView, resourceId: string | null | undefined): ReadableResourceView | null {
  if (!resourceId) return null;
  return book.resources.find((resource) => resource.id === resourceId) ?? null;
}
