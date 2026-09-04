export const READER_PREFERENCES_VERSION = 6 as const;

export const READER_SCHEMA_VERSION = 5 as const;

export type ReflowableFormat = 'epub' | 'mobi' | 'azw' | 'azw3' | 'prc' | 'fb2' | 'txt';
export type ReaderKind = 'reflowable' | 'comic' | 'pdf';
export type ReaderTheme = 'day' | 'warm' | 'green' | 'night' | 'black';
export type ReaderFontFamily = 'pingfang' | 'songti' | 'kaiti';
export type ReaderWritingMode = 'horizontal' | 'vertical';
export type ReaderReadingProgression = 'ltr' | 'rtl';
export type ReaderLifecycle = 'bootstrapping' | 'loading' | 'ready' | 'error' | 'disposed';
export type ReaderOperationKind = 'bootstrap' | 'navigation' | 'render' | 'preferences' | 'pagination';

export type ReflowableLocation = {
  kind: 'reflowable';
  format: ReflowableFormat;
  cfi?: string;
  href?: string;
  /** Zero-based reading-order resource used for local chapter navigation. */
  spineIndex?: number;
  /** Position within the current resource, never the whole-book percent. */
  resourceProgression?: number;
  /** Parser-independent position when supplied by a compatible publication. */
  position?: number;
  textQuote?: {
    exact: string;
    prefix?: string;
    suffix?: string;
  };
  /** Whole-book fraction used only as the final approximate fallback. */
  progression?: number;
};

export type ComicLocation = {
  kind: 'comic';
  resourceId: string;
  /** Zero-based canonical comic page. */
  pageIndex: number;
  resourceHref?: string;
};

export type PdfLocation = {
  kind: 'pdf';
  /** Zero-based canonical document page. */
  pageIndex: number;
  /** Normalized position within the page, quantized to four decimals. */
  pageProgression: number;
};

export type ReaderLocation = ReflowableLocation | ComicLocation | PdfLocation;

/**
 * A serialized position owned by the active reader engine.
 *
 * The reader core deliberately does not inspect Locator fields.  Concrete
 * adapters may deserialize their own value when restoring a session, while
 * transport and persistence layers carry this object unchanged.
 */
export type ReaderOpaqueLocator = Readonly<Record<string, unknown>>;

export type ReaderChapterPresentation = Readonly<{
  href: string | null;
  title: string | null;
  index: number | null;
}>;

export type ReaderPagePresentation = Readonly<{
  number: number;
  total: number | null;
}>;

export type ReaderPlaybackPresentation = Readonly<{
  positionMillis: number;
  durationMillis: number | null;
}>;

/** Presentation facts are independent from the opaque engine Locator. */
export type ReaderPositionPresentation = Readonly<{
  displayPercent: number;
  totalProgression: number;
  currentHref: string | null;
  chapter: ReaderChapterPresentation | null;
  page: ReaderPagePresentation | null;
  playback: ReaderPlaybackPresentation | null;
}>;

export type ReaderPositionReport = Readonly<{
  locator: ReaderOpaqueLocator;
  presentation: ReaderPositionPresentation;
}>;

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
  schemaVersion: typeof READER_PREFERENCES_VERSION;
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
    readingProgression: ReaderReadingProgression;
    writingMode: ReaderWritingMode;
    fontSize: number;
    lineHeight: number;
    pageWidth: number;
    fontFamily: ReaderFontFamily;
    fontWeight: 400 | 500 | 700;
    letterSpacing: number;
    pageMargin: 'narrow' | 'standard' | 'wide';
    spreadMode: 'auto' | 'single' | 'double';
    pageTurnAnimation: 'slide' | 'off';
    flow: 'paginated' | 'scrolled';
    typography: {
      paragraphIndent: number;
      paragraphSpacing: number;
      textAlign: 'publisher' | 'left' | 'justify';
      preservePublisherStyles: boolean;
    };
    optimization: {
      enabled: boolean;
      deduplicateIndent: boolean;
      indentUnindented: boolean;
    };
  };
  comic: {
    direction: 'ltr' | 'rtl';
    spreadMode: 'single' | 'double';
    pageTurnAnimation: 'slide' | 'off';
    imageFit: 'width' | 'height' | 'contain' | 'original';
    imageVariant: 'original' | 'data-saver';
    zoom: number;
    pageWidth: number;
    flow: 'paginated' | 'scrolled';
    coverSingle: boolean;
    pageGap: 0 | 8 | 16 | 24;
  };
  pdf: {
    zoom: number;
    pageWidth: number;
    fit: 'width' | 'page';
    flow: 'paged' | 'continuous';
    rotation: 0 | 90 | 180 | 270;
    cropMargins: 'off' | 'auto';
  };
};

type ReaderSourceBase = {
  bookId: string;
  resourceId: string;
  totalPages?: number | null;
};

export type ReaderOriginalResource = Readonly<{
  resourceId: string;
  assetId: string;
  /** Exact immutable asset identity used by every local-original store. */
  assetVersion: `${number}:${number}`;
  sourceFormat: ReflowableFormat;
  mimeType: string;
  sizeBytes: number;
  mtimeMs: number;
  downloadUrl: string;
}>;

export type ReaderSource = ReaderSourceBase & (
  | {
    kind: 'reflowable';
    sourceFormat: ReflowableFormat;
    /** The original, unconverted publication downloaded before local parsing. */
    originalResource: ReaderOriginalResource;
    navigation: ReaderNavigationEntry[];
    navigationFingerprint?: string;
  }
  | {
      kind: 'comic';
      contentUrl: string;
      sourceFormat: 'cbz' | 'zip' | 'cbr' | 'rar' | 'image_dir';
      comicManifestUrl: string;
      comicPageUrlTemplate: string;
    }
  | { kind: 'pdf'; contentUrl: string; sourceFormat?: never }
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
  /** Setting controls truthfully consumed by the active local adapter. */
  supportedControls?: readonly string[];
};

export type ReaderCommand =
  | { type: 'next' }
  | { type: 'previous' }
  | { type: 'first' }
  | { type: 'last' }
  | { type: 'go-to-progress'; progression: number }
  | { type: 'go-to-href'; href: string }
  | { type: 'go-to-index'; index: number }
  | { type: 'go-to-position'; position: ReaderPositionReport }
  | { type: 'set-zoom'; zoom: number }
  | { type: 'set-fit'; fit: 'width' | 'page' }
  | { type: 'retry' }
  | { type: 'cancel' };

export type ReaderCommandAck = {
  operation: OperationToken;
  accepted: boolean;
  location?: ReaderLocation;
  position?: ReaderPositionReport;
  reason?: string;
};

export type ReaderError = {
  code: string;
  message: string;
  recoverable: boolean;
  safeContext?: Readonly<Record<string, string>>;
  /** Internal diagnostic only; never serialize it or render it as user copy. */
  cause?: unknown;
};

type ReaderAdapterEventBase = {
  sessionId: string;
  operation: OperationToken;
  occurredAt: number;
};

export type ReaderAdapterEvent =
  | (ReaderAdapterEventBase & { type: 'ready'; capabilities: ReaderCapabilities; location: ReaderLocation | null; position?: ReaderPositionReport | null })
  | (ReaderAdapterEventBase & { type: 'capabilities-changed'; capabilities: ReaderCapabilities })
  | (ReaderAdapterEventBase & { type: 'metadata-changed'; totalPages: number | null })
  | (ReaderAdapterEventBase & { type: 'navigation-changed'; items: ReaderNavigationEntry[] })
  | (ReaderAdapterEventBase & { type: 'location-changed'; location: ReaderLocation; percent: number; position?: ReaderPositionReport })
  | (ReaderAdapterEventBase & { type: 'phase-changed'; phase: 'loading-content' | 'loading-font' | 'generating-pagination' | 'rendering' | null })
  | (ReaderAdapterEventBase & { type: 'pagination-progress'; completed: number; total: number; percent: number })
  | (ReaderAdapterEventBase & { type: 'activity' })
  | (ReaderAdapterEventBase & { type: 'external-link'; href: string })
  | (ReaderAdapterEventBase & { type: 'password-required'; reason: 'need-password' | 'incorrect-password' })
  | (ReaderAdapterEventBase & { type: 'error'; error: ReaderError });
