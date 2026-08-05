import type {
  EpubLocation,
  FoliateProgressSnapshot,
  OperationToken,
  ReaderAdapter,
  ReaderAdapterOpenContext,
  ReaderAdapterOperationContext,
  ReaderCapabilities,
  ReaderCommand,
  ReaderCommandAck,
  ReaderNavigationEntry,
  ReaderPreferences,
  ReflowableFormat,
  ReflowableLocation
} from '@shuku/reader-core';
import { ReaderAdapterBase, StaleReaderOperationError, isAbortError, throwIfAborted } from './adapter-base';
import { openFoliateBook, NovelOpenError, type FoliateBook, type FoliateTocItem } from './foliate-book';
import { hardenEpubIframe, sanitizeEpubDocument } from './epub-security';
import {
  applyEpubDocumentSpacing,
  createEpubThemeSnapshot,
  epubSurfaceColor,
  resolveEpubViewportLayout,
  type EpubViewportLayout
} from './epub-theme';
import { fallbackEpubFont } from './epub-font';
import type { ReaderAdapterInputHandler, ReaderInteractiveAdapter, ReaderInteractionPolicy } from './reader-interaction';
import { hasActiveTextSelection, isReaderControlTarget, readerFramePointerIntent, readerKeyIntent, readerPointerIntent } from '../input-router';
import { isEngineResolvableReflowableHref } from '../reflowable-navigation-href';
import type { ReaderBookCache } from '../../../../lib/reader/book-cache';
import {
  ReflowableContinuousController,
  type ReflowableContinuousRelocate,
  type ReflowableContinuousTarget
} from './reflowable-continuous';

type FoliateRelocateDetail = {
  cfi?: string;
  fraction?: number;
  tocItem?: Record<string, unknown>;
  section?: { current: number; total: number };
  location?: { current: number; next: number; total: number };
  time?: { section: number; total: number };
};

type FoliateLoadDetail = {
  doc: Document;
  index: number;
};

type FoliateRenderer = HTMLElement & {
  readonly start?: number;
  readonly end?: number;
  readonly viewSize?: number;
  setStyles?: (css: string) => void;
  goTo?: (target: unknown) => Promise<void>;
};

type FoliateView = HTMLElement & {
  book?: FoliateBook;
  renderer?: FoliateRenderer;
  lastLocation?: unknown;
  open: (book: FoliateBook) => Promise<void>;
  init: (options: { lastLocation?: string | { fraction: number }; showTextStart?: boolean }) => Promise<void>;
  close: () => void;
  next: () => Promise<void>;
  prev: () => Promise<void>;
  goLeft: () => Promise<void>;
  goRight: () => Promise<void>;
  goTo: (target: string | number | { fraction: number }) => Promise<unknown>;
  getTOCItemOf?: (target: string) => Promise<unknown>;
  goToFraction: (fraction: number) => Promise<void>;
  goToTextStart: () => Promise<unknown>;
};

export type FoliateAdapterOptions = {
  container: HTMLElement;
  title?: string;
  onInputIntent?: ReaderAdapterInputHandler;
  onEndOfVolume?: () => void;
  fetch?: typeof globalThis.fetch;
  userId: string;
  bookCache: ReaderBookCache;
  onCacheWarning?: (code: 'BOOK_CACHE_WRITE_FAILED') => void;
};

function clamp(value: number, minimum = 0, maximum = 1) {
  return Math.max(minimum, Math.min(maximum, value));
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}

function nonNegativeNumber(value: unknown): number | undefined {
  return typeof value === 'number' && Number.isFinite(value) && value >= 0 ? value : undefined;
}

function nonNegativeInteger(value: unknown): number | undefined {
  const number = nonNegativeNumber(value);
  return number !== undefined && Number.isInteger(number) ? number : undefined;
}

function progressPair(value: unknown) {
  if (!isRecord(value)) return undefined;
  const current = nonNegativeInteger(value.current);
  const total = nonNegativeInteger(value.total);
  return current !== undefined && total !== undefined && current < total ? { current, total } : undefined;
}

function locationProgress(value: unknown) {
  if (!isRecord(value)) return undefined;
  const current = nonNegativeInteger(value.current);
  const next = nonNegativeInteger(value.next);
  const total = nonNegativeInteger(value.total);
  if (current === undefined || next === undefined || total === undefined || total < 1) return undefined;
  return {
    current: Math.min(current, total - 1),
    next: Math.min(Math.max(current, next), total),
    total
  };
}

function remainingTime(value: unknown) {
  if (!isRecord(value)) return undefined;
  const section = nonNegativeNumber(value.section);
  const total = nonNegativeNumber(value.total);
  return section !== undefined && total !== undefined ? { section, total } : undefined;
}

export function foliateRemainingSeconds(value: FoliateRelocateDetail['time']) {
  return value ? { section: value.section * 60, total: value.total * 60 } : undefined;
}

export async function resolveAsynchronousFoliateHref(book: FoliateBook, href: string) {
  const candidate = book.resolveHref?.(href);
  if (!isRecord(candidate) || typeof candidate.then !== 'function') {
    return { asynchronous: false as const };
  }
  return { asynchronous: true as const, target: await candidate };
}

export async function foliateResolvedSectionIndex(book: FoliateBook, href: string) {
  try {
    const split = book.splitTOCHref?.(href);
    if (Array.isArray(split) && Number.isInteger(split[0]) && split[0] >= 0) return split[0] as number;
  } catch {
    // Some MOBI/KF8 books contain TOC hrefs the fast splitter cannot parse.
    // Fall through to Foliate's full public resolver for the same target.
  }
  const resolved = await Promise.resolve(book.resolveHref?.(href));
  if (!isRecord(resolved)) return undefined;
  return nonNegativeInteger(resolved.index);
}

export function foliateSectionIndexFromDisplayIndex(index: number) {
  return Math.max(0, Math.floor(index) - 1);
}

export function parseFoliateRelocateDetail(value: unknown): FoliateRelocateDetail | null {
  if (!isRecord(value)) return null;
  const cfi = typeof value.cfi === 'string' && value.cfi ? value.cfi : undefined;
  const fraction = typeof value.fraction === 'number' && Number.isFinite(value.fraction)
    ? clamp(value.fraction)
    : undefined;
  const tocItem = isRecord(value.tocItem) ? value.tocItem : undefined;
  const section = progressPair(value.section);
  const location = locationProgress(value.location);
  const time = remainingTime(value.time);
  return cfi || fraction !== undefined ? {
    ...(cfi ? { cfi } : {}),
    ...(fraction !== undefined ? { fraction } : {}),
    ...(tocItem ? { tocItem } : {}),
    ...(section ? { section } : {}),
    ...(location ? { location } : {}),
    ...(time ? { time } : {})
  } : null;
}

export function shouldResolveFoliateTocItem(
  detail: FoliateRelocateDetail,
  fixedLayout: boolean
): boolean {
  if (fixedLayout || detail.tocItem || !detail.cfi) return false;
  // A section-only CFI such as epubcfi(/6/2) has no content path after `!`.
  // Foliate's text-range resolver requires that path and cannot resolve it.
  return detail.cfi.includes('!');
}

function loadDetail(value: unknown): FoliateLoadDetail | null {
  if (!isRecord(value) || !isRecord(value.doc) || !Number.isInteger(value.index)) return null;
  const candidate = value.doc;
  if (candidate.nodeType !== Node.DOCUMENT_NODE
    || !isRecord(candidate.documentElement)
    || typeof candidate.addEventListener !== 'function') return null;
  return { doc: candidate as unknown as Document, index: value.index as number };
}

function reflowableFormat(source: ReaderAdapterOpenContext['source']): ReflowableFormat {
  if (source.kind === 'reflowable') return source.sourceFormat;
  return 'epub';
}

export function normalizeFoliateInitialLocation(location: ReaderAdapterOpenContext['initialLocation'], format: ReflowableFormat): ReflowableLocation | null {
  if (!location) return null;
  if (location.kind === 'reflowable') return location;
  if (location.kind !== 'epub') return null;
  const legacy = location as EpubLocation;
  return {
    kind: 'reflowable',
    format,
    cfi: legacy.cfi,
    href: legacy.href,
    progression: legacy.progression
  };
}

export function foliateNavigationEntries(items: FoliateTocItem[] | undefined, prefix = 'toc'): ReaderNavigationEntry[] {
  if (!Array.isArray(items)) return [];
  return items.flatMap((candidate, index) => {
    if (!isRecord(candidate)) return [];
    const label = typeof candidate.label === 'string' ? candidate.label.trim() : '';
    const href = typeof candidate.href === 'string' ? candidate.href : undefined;
    if (!label) return [];
    const children = foliateNavigationEntries(Array.isArray(candidate.subitems) ? candidate.subitems as FoliateTocItem[] : undefined, `${prefix}-${index}`);
    const navigationKey = typeof candidate.navigationKey === 'string' ? candidate.navigationKey : undefined;
    return [{
      id: navigationKey ?? `${prefix}-${index}`,
      ...(navigationKey ? { navigationKey } : {}),
      label,
      href,
      children: children.length ? children : undefined
    }];
  });
}

export async function validatedServerToc(
  book: FoliateBook,
  entries: ReaderNavigationEntry[]
): Promise<FoliateTocItem[]> {
  const validate = async (entry: ReaderNavigationEntry): Promise<FoliateTocItem | null> => {
    if (!entry.href || !entry.navigationKey || !book.resolveHref) return null;
    try {
      const target = await Promise.resolve(book.resolveHref(entry.href));
      if (!isRecord(target)) return null;
      const sectionIndex = nonNegativeInteger(target.index);
      if (sectionIndex === undefined || sectionIndex >= book.sections.length) return null;
      const subitems = (await Promise.all((entry.children ?? []).map(validate)))
        .filter((item): item is FoliateTocItem => item !== null);
      return {
        label: entry.label,
        href: entry.href,
        navigationKey: entry.navigationKey,
        ...(subitems.length ? { subitems } : {})
      };
    } catch (reason) {
      console.warn('reader.navigation-contract.invalid-target', {
        navigationKey: entry.navigationKey,
        href: entry.href,
        reason: reason instanceof Error ? reason.message : String(reason)
      });
      return null;
    }
  };
  return (await Promise.all(entries.map(validate)))
    .filter((item): item is FoliateTocItem => item !== null);
}

function commandForInput(intent: ReturnType<typeof readerKeyIntent> | ReturnType<typeof readerPointerIntent>) {
  if (intent === 'previous') return { type: 'command', command: { type: 'previous' } } as const;
  if (intent === 'next') return { type: 'command', command: { type: 'next' } } as const;
  if (intent === 'first') return { type: 'command', command: { type: 'first' } } as const;
  if (intent === 'last') return { type: 'command', command: { type: 'last' } } as const;
  if (intent === 'escape') return { type: 'escape' } as const;
  if (intent === 'toggle-controls') return { type: 'toggle-controls' } as const;
  return null;
}

function nextFrame() {
  return new Promise<void>((resolve) => requestAnimationFrame(() => resolve()));
}

function combineSignals(first: AbortSignal, second: AbortSignal) {
  if (typeof AbortSignal.any === 'function') return AbortSignal.any([first, second]);
  const controller = new AbortController();
  const abort = () => controller.abort();
  if (first.aborted || second.aborted) controller.abort();
  else {
    first.addEventListener('abort', abort, { once: true });
    second.addEventListener('abort', abort, { once: true });
  }
  return controller.signal;
}

export class FoliateReaderAdapter extends ReaderAdapterBase implements ReaderAdapter, ReaderInteractiveAdapter {
  private readonly container: HTMLElement;
  private readonly onInputIntent?: ReaderAdapterInputHandler;
  private readonly onEndOfVolume?: () => void;
  private readonly fetcher?: typeof globalThis.fetch;
  private readonly title?: string;
  private readonly userId: string;
  private readonly bookCache: ReaderBookCache;
  private readonly onCacheWarning?: (code: 'BOOK_CACHE_WRITE_FAILED') => void;
  private lifecycleController: AbortController | null = null;
  private view: FoliateView | null = null;
  private continuous: ReflowableContinuousController | null = null;
  private book: FoliateBook | null = null;
  private destroyBook: (() => void | Promise<void>) | null = null;
  private preferences: ReaderPreferences | null = null;
  private format: ReflowableFormat = 'epub';
  private currentLocation: ReflowableLocation | null = null;
  private readingDirection: 'ltr' | 'rtl' = 'ltr';
  private suppressRelocate = false;
  private pendingRelocate: FoliateRelocateDetail | null = null;
  private locationOperation: OperationToken | null = null;
  private lastPersistentOperation: OperationToken | null = null;
  private bridgedDocuments = new Map<Document, AbortController>();
  private tocSnapshots = new WeakMap<object, NonNullable<FoliateProgressSnapshot['toc']>>();
  private tocSnapshotsById = new Map<number, NonNullable<FoliateProgressSnapshot['toc']>>();
  private tocSnapshotsByHref = new Map<string, NonNullable<FoliateProgressSnapshot['toc']>>();
  private tocSnapshotsBySection = new Map<number, NonNullable<FoliateProgressSnapshot['toc']>>();
  private pendingTocSnapshot: NonNullable<FoliateProgressSnapshot['toc']> | null = null;
  private relocateResolutionSequence = 0;
  private navigationFingerprint: string | undefined;
  private viewportLayout: EpubViewportLayout = resolveEpubViewportLayout(Number.POSITIVE_INFINITY);
  private viewportObserver: ResizeObserver | null = null;
  private sessionGeneration = 0;

  constructor(options: FoliateAdapterOptions) {
    super();
    this.container = options.container;
    this.title = options.title;
    this.onInputIntent = options.onInputIntent;
    this.onEndOfVolume = options.onEndOfVolume;
    this.fetcher = options.fetch;
    this.userId = options.userId;
    this.bookCache = options.bookCache;
    this.onCacheWarning = options.onCacheWarning;
  }

  getInteractionPolicy(): ReaderInteractionPolicy {
    return { horizontalPaging: this.continuous ? 'none' : 'adapter-interactive' };
  }

  getCapabilities(): ReaderCapabilities {
    const progression = this.currentLocation?.progression ?? 0;
    return {
      readingDirection: this.readingDirection,
      canGoNext: progression < 0.9999,
      canGoPrevious: progression > 0.0001,
      canJumpToProgress: true,
      canJumpToHref: true,
      canJumpToIndex: true,
      canZoom: false,
      canSelectText: true,
      supportsPagination: true,
      supportsScrolling: true,
      supportsSpreads: true
    };
  }

  async open(context: ReaderAdapterOpenContext) {
    await this.cleanupEngine();
    const generation = this.beginSession(context.sessionId, context.operation);
    this.sessionGeneration = generation;
    this.locationOperation = context.operation;
    this.lastPersistentOperation = context.operation;
    this.preferences = context.preferences;
    this.format = reflowableFormat(context.source);
    this.container.dataset.readerEngine = 'reflowable-v3';
    this.lifecycleController = new AbortController();
    this.observeViewport();
    const signal = combineSignals(context.signal, this.lifecycleController.signal);
    this.emit({ type: 'phase-changed', phase: 'loading-content' }, context.operation);
    try {
      await import('foliate-js/view.js');
      throwIfAborted(signal);
      const opened = await openFoliateBook({
        url: context.source.contentUrl,
        format: this.format,
        title: this.title ?? context.source.volumeId,
        signal,
        fetch: this.fetcher,
        cache: {
          storage: this.bookCache,
          identity: {
            userId: this.userId,
            volumeId: context.source.volumeId,
            contentFingerprint: context.source.contentFingerprint
          }
        },
        onPhase: (phase) => {
          this.emit({
            type: 'phase-changed',
            phase: phase === 'downloading' ? 'downloading-content' : 'loading-content'
          }, context.operation);
        },
        onDownloadProgress: (progress) => {
          this.emit({ type: 'download-progress', ...progress }, context.operation);
        },
        onCacheWarning: this.onCacheWarning
      });
      this.assertActive(generation, signal);
      this.book = opened.book;
      this.destroyBook = opened.destroy;
      this.readingDirection = opened.book.dir === 'rtl' ? 'rtl' : 'ltr';
      this.navigationFingerprint = context.source.kind === 'reflowable'
        ? context.source.navigationFingerprint
        : undefined;
      opened.book.toc = context.source.kind === 'reflowable'
        ? await validatedServerToc(opened.book, context.source.navigation)
        : [];
      const navigationItems = foliateNavigationEntries(opened.book.toc);
      this.emit({ type: 'navigation-changed', items: navigationItems }, context.operation);
      this.emit({ type: 'phase-changed', phase: 'rendering' }, context.operation);
      this.suppressRelocate = true;
      const initialLocation = normalizeFoliateInitialLocation(context.initialLocation, this.format);
      if (this.shouldUseContinuous(context.preferences)) {
        await this.indexToc(opened.book.toc);
        await this.openContinuousSurface(initialLocation, generation);
      } else {
        await this.openPaginatedSurface(initialLocation, generation, signal);
      }
      await nextFrame();
      this.assertActive(generation, signal);
      this.suppressRelocate = false;
      const stable = this.pendingRelocate ?? parseFoliateRelocateDetail(this.view?.lastLocation);
      this.pendingRelocate = null;
      if (stable) this.commitRelocate(stable, context.operation, generation);
      this.emit({ type: 'phase-changed', phase: null }, context.operation);
      this.emit({ type: 'ready', capabilities: this.getCapabilities(), location: this.currentLocation }, context.operation);
      this.emit({ type: 'capabilities-changed', capabilities: this.getCapabilities() }, context.operation);
    } catch (reason) {
      if (isAbortError(reason) || reason instanceof StaleReaderOperationError || signal.aborted) return;
      const error = reason instanceof NovelOpenError
        ? reason
        : new NovelOpenError('NOVEL_PARSE_FAILED', 'The novel reader failed to open the book', { cause: reason });
      this.emit({ type: 'phase-changed', phase: null }, context.operation);
      this.emit({ type: 'error', error: { code: error.code, message: error.message, recoverable: error.code !== 'NOVEL_DRM_PROTECTED' } }, context.operation);
      return;
    }
  }

  private shouldUseContinuous(preferences: ReaderPreferences) {
    return preferences.epub.flow === 'scrolled' && this.book?.rendition?.layout !== 'pre-paginated';
  }

  private async openPaginatedSurface(
    location: ReflowableLocation | null,
    generation: number,
    signal: AbortSignal
  ) {
    const book = this.book;
    if (!book) throw new Error('The novel reader book is unavailable');
    const view = document.createElement('foliate-view') as FoliateView;
    this.view = view;
    this.bindView(view, generation);
    this.container.replaceChildren(view);
    await view.open(book);
    this.assertActive(generation, signal);
    await this.indexToc(book.toc);
    if (this.preferences) this.applyRendererPreferences(this.preferences);
    await this.restore(location);
  }

  private async openContinuousSurface(location: ReflowableLocation | null, generation: number) {
    const book = this.book;
    const preferences = this.preferences;
    if (!book || !preferences) throw new Error('The continuous novel reader is unavailable');
    const controller = new ReflowableContinuousController({
      container: this.container,
      book,
      preferences,
      viewportLayout: this.viewportLayout,
      onDocument: (document) => this.bindDocument(document),
      onRelocate: (relocate) => {
        if (!this.isActive(generation) || this.continuous !== controller) return;
        const detail = this.continuousRelocateDetail(relocate);
        if (this.suppressRelocate) this.pendingRelocate = detail;
        else this.commitRelocate(detail, this.locationOperation ?? this.currentOperation(), generation);
      },
      onExternalLink: (href) => this.emit({ type: 'external-link', href })
    });
    this.continuous = controller;
    this.applyContinuousSurfacePreferences(preferences);
    const target = await this.resolveContinuousLocation(location, controller);
    await controller.open(target ?? { index: this.firstLinearSectionIndex() });
    if (!target && typeof location?.progression === 'number') {
      await controller.goToProgress(clamp(location.progression));
    }
  }

  private continuousRelocateDetail(relocate: ReflowableContinuousRelocate): FoliateRelocateDetail {
    const toc = this.tocSnapshotsBySection.get(relocate.index);
    const sectionId = this.book?.sections[relocate.index]?.id;
    const href = toc?.href ?? (typeof sectionId === 'string' ? sectionId : undefined);
    if (!this.pendingTocSnapshot && toc) this.pendingTocSnapshot = toc;
    return {
      ...(relocate.cfi ? { cfi: relocate.cfi } : {}),
      fraction: relocate.fraction,
      section: { current: relocate.index, total: this.book?.sections.length ?? 0 },
      ...(href ? { tocItem: { href, ...(toc ? { label: toc.title } : {}) } } : {})
    };
  }

  private async resolveContinuousLocation(
    location: ReflowableLocation | null,
    controller = this.continuous
  ): Promise<ReflowableContinuousTarget | null> {
    if (!controller || !location) return null;
    this.pendingTocSnapshot = location.foliate?.toc ?? null;
    if (location.cfi) {
      const target = await Promise.resolve(controller.resolveCFI(location.cfi));
      if (target) return target;
    }
    if (location.href && isEngineResolvableReflowableHref(this.format, location.href)) {
      const target = await controller.resolveHref(location.href);
      if (target) return target;
    }
    const section = location.foliate?.section?.current;
    return typeof section === 'number' && section >= 0 && section < (this.book?.sections.length ?? 0)
      ? { index: section }
      : null;
  }

  private firstLinearSectionIndex() {
    const index = this.book?.sections.findIndex((section) => section.linear !== 'no' && section.linear !== false) ?? -1;
    return Math.max(0, index);
  }

  private lastLinearSectionIndex() {
    const sections = this.book?.sections ?? [];
    for (let index = sections.length - 1; index >= 0; index -= 1) {
      const section = sections[index];
      if (section?.linear !== 'no' && section?.linear !== false) return index;
    }
    return Math.max(0, sections.length - 1);
  }

  private applyContinuousSurfacePreferences(preferences: ReaderPreferences) {
    this.container.style.background = epubSurfaceColor(preferences);
    this.container.dataset.readerTheme = 'ready';
    this.container.dataset.readerFlow = 'scrolled';
    this.container.dataset.readerSpread = preferences.epub.spreadMode;
    this.container.dataset.epubViewportLayout = this.viewportLayout.compact ? 'compact' : 'regular';
  }

  private clearReadingSurface() {
    this.bridgedDocuments.forEach((controller) => controller.abort());
    this.bridgedDocuments.clear();
    this.continuous?.destroy();
    this.continuous = null;
    try {
      this.view?.close();
    } catch (reason) {
      console.warn('reader.reflowable-surface-close.failed', {
        reason: reason instanceof Error ? reason.message : String(reason)
      });
    }
    this.view = null;
    this.container.replaceChildren();
  }

  async execute(command: ReaderCommand, context: ReaderAdapterOperationContext): Promise<ReaderCommandAck> {
    this.beginOperation(context);
    this.locationOperation = context.operation;
    this.lastPersistentOperation = context.operation;
    const view = this.view;
    const continuous = this.continuous;
    if (!view && !continuous) return this.failOperation(context, 'Reader is not ready');
    try {
      if (continuous) {
        if (command.type === 'next') await continuous.next();
        else if (command.type === 'previous') await continuous.previous();
        else if (command.type === 'first') await continuous.goTo({ index: this.firstLinearSectionIndex() });
        else if (command.type === 'last') await continuous.goTo({ index: this.lastLinearSectionIndex(), fraction: 1 });
        else if (command.type === 'go-to-progress') await continuous.goToProgress(clamp(command.progression));
        else if (command.type === 'go-to-href') {
          if (!isEngineResolvableReflowableHref(this.format, command.href)) {
            return this.failOperation(context, 'Unsupported navigation href for this format');
          }
          this.pendingTocSnapshot = this.tocSnapshotsByHref.get(command.href) ?? null;
          const target = await continuous.resolveHref(command.href);
          if (!target) return this.failOperation(context, 'The chapter target could not be resolved');
          await continuous.goTo(target);
        } else if (command.type === 'go-to-index') {
          await continuous.goTo({ index: foliateSectionIndexFromDisplayIndex(command.index) });
        } else if (command.type === 'go-to-location') {
          const location = normalizeFoliateInitialLocation(command.location, this.format);
          if (!location) return this.failOperation(context, 'Location does not belong to the novel reader');
          const target = await this.resolveContinuousLocation(location, continuous);
          if (target) await continuous.goTo(target);
          else if (typeof location.progression === 'number') await continuous.goToProgress(location.progression);
          else await continuous.goTo({ index: this.firstLinearSectionIndex() });
        } else if (command.type === 'cancel') return this.ack(context.operation, true);
        else return this.failOperation(context, `Unsupported command: ${command.type}`);
      } else if (command.type === 'next') {
        if (!this.getCapabilities().canGoNext && this.onEndOfVolume) this.onEndOfVolume();
        else await view?.next();
      } else if (command.type === 'previous') await view?.prev();
      else if (command.type === 'first') await view?.goToTextStart();
      else if (command.type === 'last') await view?.goToFraction(1);
      else if (command.type === 'go-to-progress') await view?.goToFraction(clamp(command.progression));
      else if (command.type === 'go-to-href') {
        if (!isEngineResolvableReflowableHref(this.format, command.href)) {
          return this.failOperation(context, 'Unsupported navigation href for this format');
        }
        this.pendingTocSnapshot = this.tocSnapshotsByHref.get(command.href) ?? null;
        await this.goToHref(command.href);
      }
      else if (command.type === 'go-to-index') await view?.goTo(foliateSectionIndexFromDisplayIndex(command.index));
      else if (command.type === 'go-to-location') {
        const location = normalizeFoliateInitialLocation(command.location, this.format);
        if (!location) return this.failOperation(context, 'Location does not belong to the novel reader');
        await this.restore(location);
      } else if (command.type === 'cancel') return this.ack(context.operation, true);
      else return this.failOperation(context, `Unsupported command: ${command.type}`);
      throwIfAborted(context.signal);
      return this.ack(context.operation, true, { location: this.currentLocation ?? undefined });
    } catch (reason) {
      this.pendingTocSnapshot = null;
      if (isAbortError(reason) || reason instanceof StaleReaderOperationError) throw reason;
      return this.failOperation(context, reason instanceof Error ? reason.message : 'Navigation failed');
    }
  }

  async applyPreferences(preferences: ReaderPreferences, context: ReaderAdapterOperationContext) {
    this.beginOperation(context);
    const location = this.currentLocation;
    const wasContinuous = Boolean(this.continuous);
    this.preferences = preferences;
    this.locationOperation = context.operation;
    this.suppressRelocate = true;
    const wantsContinuous = this.shouldUseContinuous(preferences);
    if (wasContinuous !== wantsContinuous) {
      this.clearReadingSurface();
      if (wantsContinuous) {
        await this.openContinuousSurface(location, this.sessionGeneration);
      } else {
        const signal = this.lifecycleController
          ? combineSignals(context.signal, this.lifecycleController.signal)
          : context.signal;
        await this.openPaginatedSurface(location, this.sessionGeneration, signal);
      }
    } else if (this.continuous) {
      this.applyContinuousSurfacePreferences(preferences);
      await this.continuous.applyPreferences(preferences, this.viewportLayout);
    } else {
      this.applyRendererPreferences(preferences);
      this.bridgedDocuments.forEach((_controller, document) => applyEpubDocumentSpacing(document, preferences));
    }
    await nextFrame();
    await nextFrame();
    throwIfAborted(context.signal);
    this.suppressRelocate = false;
    const stable = this.pendingRelocate ?? parseFoliateRelocateDetail(this.view?.lastLocation);
    this.pendingRelocate = null;
    if (stable) this.commitRelocate(stable, context.operation);
    this.emit({ type: 'capabilities-changed', capabilities: this.getCapabilities() }, context.operation);
    this.locationOperation = this.lastPersistentOperation ?? context.operation;
    return this.ack(context.operation, true, { location: this.currentLocation ?? undefined });
  }

  async dispose() {
    if (!this.markDisposed()) return;
    await this.cleanupEngine();
  }

  private bindView(view: FoliateView, generation: number) {
    view.addEventListener('relocate', (event) => {
      if (!this.isActive(generation)) return;
      const detail = parseFoliateRelocateDetail(event instanceof CustomEvent ? event.detail : null);
      if (!detail) return;
      if (this.suppressRelocate) this.pendingRelocate = detail;
      else this.commitRelocate(detail, this.locationOperation ?? this.currentOperation(), generation);
    });
    view.addEventListener('load', (event) => {
      if (!this.isActive(generation)) return;
      const detail = loadDetail(event instanceof CustomEvent ? event.detail : null);
      if (detail) this.bindDocument(detail.doc);
    });
    view.addEventListener('external-link', (event) => {
      if (!(event instanceof CustomEvent) || !isRecord(event.detail)) return;
      const href = typeof event.detail.href_ === 'string' ? event.detail.href_ : null;
      if (!href) return;
      event.preventDefault();
      this.emit({ type: 'external-link', href });
    });
  }

  private commitRelocate(detail: FoliateRelocateDetail, operation: OperationToken, generation?: number) {
    const sequence = ++this.relocateResolutionSequence;
    const hasKnownToc = Boolean(detail.tocItem || this.pendingTocSnapshot);
    const view = this.view;
    this.applyRelocate(detail, operation);
    const fixedLayout = this.book?.rendition?.layout === 'pre-paginated';
    const cfi = detail.cfi;
    if (hasKnownToc || !cfi || !shouldResolveFoliateTocItem(detail, fixedLayout) || !view?.getTOCItemOf) return;
    void view.getTOCItemOf(cfi).then((tocItem) => {
      if (this.view !== view || (generation !== undefined && !this.isActive(generation))
        || sequence !== this.relocateResolutionSequence || !isRecord(tocItem)) return;
      this.applyRelocate({ ...detail, tocItem }, operation);
    }).catch(() => undefined);
  }

  private bindDocument(document: Document) {
    this.bridgedDocuments.get(document)?.abort();
    const controller = new AbortController();
    this.bridgedDocuments.set(document, controller);
    sanitizeEpubDocument(document);
    if (this.preferences) applyEpubDocumentSpacing(document, this.preferences);
    const frame = document.defaultView?.frameElement;
    hardenEpubIframe(frame instanceof HTMLIFrameElement ? frame : undefined);
    document.documentElement.dataset.shukuInputBridge = 'ready';
    this.container.dataset.readerContent = 'ready';
    this.container.dataset.readerInputBridge = 'ready';
    const signal = controller.signal;
    let touchStart: { x: number; y: number } | null = null;
    let suppressClick = false;
    document.addEventListener('touchstart', (event) => {
      if (this.preferences?.interaction.swipePageTurn !== false || event.touches.length !== 1) return;
      event.stopImmediatePropagation();
    }, { capture: true, passive: true, signal });
    document.addEventListener('touchstart', (event) => {
      const touch = event.changedTouches[0];
      touchStart = touch ? { x: touch.clientX, y: touch.clientY } : null;
      suppressClick = false;
    }, { passive: true, signal });
    document.addEventListener('touchmove', (event) => {
      const touch = event.changedTouches[0];
      if (touch && touchStart && Math.hypot(touch.clientX - touchStart.x, touch.clientY - touchStart.y) > 12) suppressClick = true;
    }, { passive: true, signal });
    document.addEventListener('touchend', () => {
      touchStart = null;
    }, { passive: true, signal });
    document.addEventListener('keydown', (event) => {
      if (!this.onInputIntent || isReaderControlTarget(event.target)) return;
      const intent = commandForInput(readerKeyIntent(event, this.readingDirection, {
        keyboardPageTurn: this.preferences?.interaction.keyboardPageTurn,
        volumeKeyPageTurn: this.preferences?.interaction.volumeKeyPageTurn
      }));
      if (!intent) return;
      event.preventDefault();
      void this.onInputIntent(intent);
    }, { signal });
    document.addEventListener('click', (event) => {
      if (!this.onInputIntent || suppressClick || isReaderControlTarget(event.target) || hasActiveTextSelection(document.getSelection())) {
        suppressClick = false;
        return;
      }
      const viewport = document.documentElement;
      const intent = commandForInput(frame instanceof HTMLIFrameElement
        ? readerFramePointerIntent(
          event.clientX,
          event.clientY,
          frame.clientWidth || viewport.clientWidth,
          frame.clientHeight || viewport.clientHeight,
          frame.getBoundingClientRect(),
          this.container.getBoundingClientRect(),
          this.readingDirection,
          this.preferences?.interaction.tapZones
        )
        : readerPointerIntent(
          event.clientX,
          event.clientY,
          viewport.clientWidth,
          viewport.clientHeight,
          this.readingDirection,
          this.preferences?.interaction.tapZones
        ));
      if (!intent) return;
      event.preventDefault();
      void this.onInputIntent(intent);
    }, { signal });
    return () => {
      controller.abort();
      if (this.bridgedDocuments.get(document) === controller) this.bridgedDocuments.delete(document);
    };
  }

  private applyRendererPreferences(preferences: ReaderPreferences) {
    const renderer = this.view?.renderer;
    if (!renderer) return;
    renderer.setAttribute('flow', 'paginated');
    renderer.setAttribute('gap', this.viewportLayout.paginatorGap);
    renderer.style.paddingBottom = this.viewportLayout.bottomInset;
    renderer.setAttribute('max-inline-size', `${Math.round(clamp(preferences.epub.pageWidth, 600, 1350))}px`);
    const columnCount = preferences.epub.spreadMode === 'auto'
      ? this.viewportLayout.automaticColumnCount
      : preferences.epub.spreadMode === 'double' ? 2 : 1;
    renderer.setAttribute('max-column-count', String(columnCount));
    if (preferences.epub.pageTurnAnimation === 'slide') renderer.setAttribute('animated', '');
    else renderer.removeAttribute('animated');
    renderer.setStyles?.(createEpubThemeSnapshot(
      preferences,
      fallbackEpubFont(preferences.epub.fontFamily),
      this.viewportLayout
    ));
    this.container.style.background = epubSurfaceColor(preferences);
    this.container.dataset.readerTheme = 'ready';
    this.container.dataset.readerFlow = 'paginated';
    this.container.dataset.readerSpread = preferences.epub.spreadMode;
    this.container.dataset.epubViewportLayout = this.viewportLayout.compact ? 'compact' : 'regular';
  }

  private observeViewport() {
    this.viewportObserver?.disconnect();
    this.viewportLayout = resolveEpubViewportLayout(this.container.getBoundingClientRect().width);
    this.viewportObserver = new ResizeObserver((entries) => {
      const width = entries[0]?.contentRect.width ?? this.container.getBoundingClientRect().width;
      const nextLayout = resolveEpubViewportLayout(width);
      if (
        nextLayout.compact === this.viewportLayout.compact
        && nextLayout.automaticColumnCount === this.viewportLayout.automaticColumnCount
      ) return;
      this.viewportLayout = nextLayout;
      if (this.preferences && this.continuous) {
        this.applyContinuousSurfacePreferences(this.preferences);
        void this.continuous.applyPreferences(this.preferences, nextLayout);
      } else if (this.preferences) this.applyRendererPreferences(this.preferences);
    });
    this.viewportObserver.observe(this.container);
  }

  private async restore(location: ReflowableLocation | null) {
    const view = this.view;
    if (!view) return;
    this.pendingTocSnapshot = location?.foliate?.toc ?? null;
    const href = location?.href;
    const normalizedHref = href?.replace(/^\.\//u, '');
    const matchingSection = normalizedHref
      ? this.book?.sections.find((section) => {
        if (typeof section.id !== 'string') return false;
        const sectionId = section.id.replace(/^\.\//u, '');
        return sectionId === normalizedHref || sectionId.endsWith(`/${normalizedHref}`);
      })?.id
      : undefined;
    const targets = [location?.cfi, matchingSection, href]
      .filter((target, index, values): target is string => Boolean(target) && values.indexOf(target) === index)
      .filter((target) => {
        // CFI and section ids are engine-native; only filter href-like pseudo targets.
        if (target === location?.cfi || target === matchingSection) return true;
        return isEngineResolvableReflowableHref(this.format, target);
      });
    for (const target of targets) {
      try {
        const resolved = target === href ? await this.goToHref(target) : await view.goTo(target);
        if (resolved) return;
      } catch {
        // Continue to the next official navigation representation.
      }
    }
    if (typeof location?.progression === 'number') {
      try {
        await view.goToFraction(clamp(location.progression));
        return;
      } catch {
        // Fall through to the official text start.
      }
    }
    await view.init({ showTextStart: true });
  }

  private async goToHref(href: string) {
    const view = this.view;
    const book = this.book;
    if (!view || !book) return undefined;
    const asynchronous = await resolveAsynchronousFoliateHref(book, href);
    if (asynchronous.asynchronous) {
      const resolved = asynchronous.target;
      if (!resolved || !view.renderer?.goTo) throw new Error('The chapter target could not be resolved');
      await view.renderer.goTo(resolved);
      return resolved;
    }
    return view.goTo(href);
  }

  private applyRelocate(detail: FoliateRelocateDetail, operation: OperationToken) {
    const progression = detail.fraction ?? this.currentLocation?.progression ?? 0;
    const href = typeof detail.tocItem?.href === 'string' ? detail.tocItem.href : undefined;
    // At an exact anchor boundary Foliate can briefly report the preceding TOC
    // item. The explicit user target is authoritative for that first relocate.
    const toc = this.pendingTocSnapshot
      ?? this.resolveTocSnapshot(detail.tocItem)
      ?? undefined;
    this.pendingTocSnapshot = null;
    const sectionId = detail.section
      ? this.book?.sections[detail.section.current]?.id
      : undefined;
    const currentHref = toc?.href ?? href ?? (typeof sectionId === 'string' ? sectionId : undefined);
    const foliate: FoliateProgressSnapshot = {
      toc,
      navigationFingerprint: this.navigationFingerprint,
      section: detail.section,
      location: detail.location,
      // Foliate's SectionProgress exposes reading-time estimates in minutes.
      remainingSeconds: foliateRemainingSeconds(detail.time)
    };
    const hasFoliateMetrics = Object.values(foliate).some(Boolean);
    this.currentLocation = {
      kind: 'reflowable',
      format: this.format,
      cfi: detail.cfi,
      href: currentHref,
      progression,
      foliate: hasFoliateMetrics ? foliate : undefined
    };
    this.container.dataset.readerLocationCfi = detail.cfi ?? '';
    this.container.dataset.readerLocationHref = currentHref ?? '';
    this.container.dataset.readerLocationProgression = String(progression);
    this.container.dataset.readerLocationTocIndex = toc ? String(toc.index) : '';
    this.container.dataset.readerLocationTocTitle = toc?.title ?? '';
    this.emit({ type: 'location-changed', location: this.currentLocation, percent: progression * 100 }, operation);
    this.emit({ type: 'capabilities-changed', capabilities: this.getCapabilities() }, operation);
  }

  private async indexToc(items: FoliateTocItem[] | undefined) {
    this.tocSnapshots = new WeakMap();
    this.tocSnapshotsById.clear();
    this.tocSnapshotsByHref.clear();
    this.tocSnapshotsBySection.clear();
    const hrefSnapshots: Array<NonNullable<FoliateProgressSnapshot['toc']>> = [];
    let index = 0;
    const visit = (candidates: FoliateTocItem[] | undefined) => {
      if (!Array.isArray(candidates)) return;
      for (const candidate of candidates) {
        if (!isRecord(candidate)) continue;
        const title = typeof candidate.label === 'string' ? candidate.label.trim() : '';
        if (title) {
          const snapshot = {
            index,
            title,
            href: typeof candidate.href === 'string' ? candidate.href : undefined,
            navigationKey: typeof candidate.navigationKey === 'string'
              ? candidate.navigationKey
              : undefined
          };
          this.tocSnapshots.set(candidate, snapshot);
          if (typeof candidate.id === 'number' && Number.isInteger(candidate.id)) {
            this.tocSnapshotsById.set(candidate.id, snapshot);
          }
          if (snapshot.href && !this.tocSnapshotsByHref.has(snapshot.href)) {
            this.tocSnapshotsByHref.set(snapshot.href, snapshot);
            hrefSnapshots.push(snapshot);
          }
          index += 1;
        }
        visit(Array.isArray(candidate.subitems) ? candidate.subitems as FoliateTocItem[] : undefined);
      }
    };
    visit(items);
    const book = this.book;
    if (!book) return;
    await Promise.all(hrefSnapshots.map(async (snapshot) => {
      if (!snapshot.href) return;
      const resolvedSection = await foliateResolvedSectionIndex(book, snapshot.href);
      const normalizedHref = snapshot.href.replace(/^\.\//u, '');
      const matchingSection = book.sections.findIndex((section) => {
        if (typeof section.id !== 'string') return false;
        const sectionId = section.id.replace(/^\.\//u, '');
        return sectionId === normalizedHref || sectionId.endsWith(`/${normalizedHref}`);
      });
      const section = resolvedSection ?? (matchingSection >= 0 ? matchingSection : undefined);
      if (section !== undefined && !this.tocSnapshotsBySection.has(section)) {
        this.tocSnapshotsBySection.set(section, snapshot);
      }
    }));
  }

  private resolveTocSnapshot(item: Record<string, unknown> | undefined) {
    if (!item) return undefined;
    const direct = this.tocSnapshots.get(item);
    if (direct) return direct;
    if (typeof item.id === 'number' && Number.isInteger(item.id)) {
      const byId = this.tocSnapshotsById.get(item.id);
      if (byId) return byId;
    }
    return typeof item.href === 'string' ? this.tocSnapshotsByHref.get(item.href) : undefined;
  }

  private async cleanupEngine() {
    this.lifecycleController?.abort();
    this.lifecycleController = null;
    this.viewportObserver?.disconnect();
    this.viewportObserver = null;
    this.clearReadingSurface();
    this.tocSnapshots = new WeakMap();
    this.tocSnapshotsById.clear();
    this.tocSnapshotsByHref.clear();
    this.tocSnapshotsBySection.clear();
    this.pendingTocSnapshot = null;
    this.relocateResolutionSequence += 1;
    this.navigationFingerprint = undefined;
    const destroyBook = this.destroyBook;
    this.book = null;
    this.destroyBook = null;
    this.currentLocation = null;
    this.pendingRelocate = null;
    this.locationOperation = null;
    this.lastPersistentOperation = null;
    this.sessionGeneration = 0;
    delete this.container.dataset.readerContent;
    delete this.container.dataset.readerInputBridge;
    delete this.container.dataset.readerTheme;
    delete this.container.dataset.readerFlow;
    delete this.container.dataset.readerSpread;
    delete this.container.dataset.epubViewportLayout;
    delete this.container.dataset.readerLocationCfi;
    delete this.container.dataset.readerLocationHref;
    delete this.container.dataset.readerLocationProgression;
    delete this.container.dataset.readerLocationTocIndex;
    delete this.container.dataset.readerLocationTocTitle;
    delete this.container.dataset.readerEngine;
    this.container.replaceChildren();
    await destroyBook?.();
  }
}

export function createFoliateAdapter(options: FoliateAdapterOptions) {
  return new FoliateReaderAdapter(options);
}
