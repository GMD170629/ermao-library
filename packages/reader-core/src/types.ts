export const READER_SCHEMA_VERSION = 4 as const;

export type ReflowableFormat = 'epub' | 'mobi' | 'azw' | 'azw3' | 'prc' | 'fb2' | 'txt';
export type ReaderKind = 'reflowable' | 'comic' | 'pdf';
export type ReaderTheme = 'day' | 'warm' | 'green' | 'night' | 'black';
export type ReaderFontFamily = 'pingfang' | 'heiti' | 'songti' | 'yahei' | 'kaiti';
export type ReaderLifecycle = 'bootstrapping' | 'loading' | 'ready' | 'error' | 'disposed';
export type ReaderOperationKind = 'bootstrap' | 'navigation' | 'render' | 'preferences' | 'pagination';

export type EpubLocation = {
  kind: 'epub';
  cfi?: string;
  href?: string;
  spineIndex?: number;
  progression?: number;
};

/** Persisted by the former EPUB.js reader and accepted for resume migration only. */
export type LegacyEpubLocation = EpubLocation;

export type ReflowableLocation = {
  kind: 'reflowable';
  format: ReflowableFormat;
  cfi?: string;
  href?: string;
  progression?: number;
  foliate?: FoliateProgressSnapshot;
};

export type FoliateProgressSnapshot = {
  toc?: {
    index: number;
    title: string;
    href?: string;
    navigationKey?: string;
  };
  navigationFingerprint?: string;
  section?: {
    current: number;
    total: number;
  };
  location?: {
    current: number;
    next: number;
    total: number;
  };
  remainingSeconds?: {
    section: number;
    total: number;
  };
};

export type ComicLocation = {
  kind: 'comic';
  volumeId: string;
  pageIndex: number;
};

export type PdfLocation = {
  kind: 'pdf';
  pageNumber: number;
};

export type ReaderLocation = ReflowableLocation | LegacyEpubLocation | ComicLocation | PdfLocation;

export type ReaderNavigationEntry = {
  id: string;
  navigationKey?: string;
  label: string;
  href?: string;
  index?: number;
  level?: number;
  children?: ReaderNavigationEntry[];
};

export type ReaderPreferences = {
  schemaVersion: typeof READER_SCHEMA_VERSION;
  appearance: {
    theme: ReaderTheme;
    themeMode: 'manual' | 'system';
  };
  display: {
    progressStyle: 'auto' | 'percent' | 'position' | 'remaining' | 'hidden';
    showClock: boolean;
  };
  interaction: {
    tapZones: 'standard' | 'reversed' | 'disabled';
    swipePageTurn: boolean;
    keyboardPageTurn: boolean;
    volumeKeyPageTurn: boolean;
    keepScreenAwake: boolean;
  };
  epub: {
    fontSize: number;
    lineHeight: number;
    pageWidth: number;
    fontFamily: ReaderFontFamily;
    fontWeight: 400 | 500 | 700;
    letterSpacing: -0.02 | 0 | 0.04 | 0.08;
    pageMargin: 'narrow' | 'standard' | 'wide';
    spreadMode: 'auto' | 'single' | 'double';
    pageTurnAnimation: 'slide' | 'off';
    flow: 'paginated' | 'scrolled';
    typography: {
      paragraphIndent: number;
      paragraphSpacing: number;
      textAlign: 'publisher' | 'left' | 'justify';
      preservePublisherStyles: boolean;
      allowPublisherColors: boolean;
      allowPublisherFonts: boolean;
    };
    optimization: {
      enabled: boolean;
      deduplicateIndent: boolean;
      indentUnindented: boolean;
    };
  };
  comic: {
    direction: 'ltr' | 'rtl';
    mode: 'single' | 'double';
    pageTurnAnimation: 'slide' | 'off';
    imageFit: 'width' | 'height' | 'contain' | 'original';
    imageVariant: 'original' | 'data-saver';
    zoom: number;
    flow: 'paged' | 'vertical';
    coverSingle: boolean;
    pageGap: 0 | 8 | 16 | 24;
  };
  pdf: {
    zoom: number;
    fit: 'width' | 'page';
    flow: 'paged' | 'continuous';
    rotation: 0 | 90 | 180 | 270;
    cropMargins: 'off' | 'auto';
  };
};

type ReaderSourceBase = {
  workId: string;
  volumeId: string;
  contentUrl: string;
  contentFingerprint: string;
  totalPages?: number | null;
};

export type ReaderSource = ReaderSourceBase & (
  | {
    kind: 'reflowable';
    sourceFormat: ReflowableFormat;
    navigation: ReaderNavigationEntry[];
    navigationFingerprint?: string;
  }
  | { kind: 'comic' | 'pdf'; sourceFormat?: never }
);

export type OperationToken = {
  sessionId: string;
  kind: ReaderOperationKind;
  sequence: number;
};

export type ReaderCapabilities = {
  readingDirection: 'ltr' | 'rtl';
  canGoNext: boolean;
  canGoPrevious: boolean;
  canJumpToProgress: boolean;
  canJumpToHref: boolean;
  canJumpToIndex: boolean;
  canZoom: boolean;
  canSelectText: boolean;
  supportsPagination: boolean;
  supportsScrolling: boolean;
  supportsSpreads: boolean;
};

export type ReaderCommand =
  | { type: 'next' }
  | { type: 'previous' }
  | { type: 'first' }
  | { type: 'last' }
  | { type: 'go-to-progress'; progression: number }
  | { type: 'go-to-href'; href: string }
  | { type: 'go-to-index'; index: number }
  | { type: 'go-to-location'; location: ReaderLocation }
  | { type: 'set-zoom'; zoom: number }
  | { type: 'set-fit'; fit: 'width' | 'page' }
  | { type: 'retry' }
  | { type: 'cancel' };

export type ReaderCommandAck = {
  operation: OperationToken;
  accepted: boolean;
  location?: ReaderLocation;
  reason?: string;
};

export type ReaderError = {
  code: string;
  message: string;
  recoverable: boolean;
};

type ReaderAdapterEventBase = {
  sessionId: string;
  operation: OperationToken;
  occurredAt: number;
};

export type ReaderAdapterEvent =
  | (ReaderAdapterEventBase & { type: 'ready'; capabilities: ReaderCapabilities; location: ReaderLocation | null })
  | (ReaderAdapterEventBase & { type: 'capabilities-changed'; capabilities: ReaderCapabilities })
  | (ReaderAdapterEventBase & { type: 'metadata-changed'; totalPages: number | null })
  | (ReaderAdapterEventBase & { type: 'navigation-changed'; items: ReaderNavigationEntry[] })
  | (ReaderAdapterEventBase & { type: 'location-changed'; location: ReaderLocation; percent: number })
  | (ReaderAdapterEventBase & { type: 'phase-changed'; phase: 'downloading-content' | 'loading-content' | 'loading-font' | 'generating-pagination' | 'rendering' | null })
  | (ReaderAdapterEventBase & { type: 'download-progress'; loadedBytes: number; totalBytes: number | null; percent: number | null })
  | (ReaderAdapterEventBase & { type: 'pagination-progress'; completed: number; total: number; percent: number })
  | (ReaderAdapterEventBase & { type: 'activity' })
  | (ReaderAdapterEventBase & { type: 'external-link'; href: string })
  | (ReaderAdapterEventBase & { type: 'password-required'; reason: 'need-password' | 'incorrect-password' })
  | (ReaderAdapterEventBase & { type: 'error'; error: ReaderError });
