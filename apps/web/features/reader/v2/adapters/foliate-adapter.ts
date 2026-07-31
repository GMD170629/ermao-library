import type {
  EpubLocation,
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
import { createEpubThemeSnapshot, epubSurfaceColor } from './epub-theme';
import { fallbackEpubFont } from './epub-font';
import type { ReaderAdapterInputHandler, ReaderInteractiveAdapter, ReaderInteractionPolicy } from './reader-interaction';
import { hasActiveTextSelection, isReaderControlTarget, readerKeyIntent, readerPointerIntent } from '../input-router';

type FoliateRelocateDetail = {
  cfi?: string;
  fraction?: number;
  tocItem?: { href?: unknown };
};

type FoliateLoadDetail = {
  doc: Document;
  index: number;
};

type FoliateRenderer = HTMLElement & {
  setStyles?: (css: string) => void;
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
  goToFraction: (fraction: number) => Promise<void>;
  goToTextStart: () => Promise<unknown>;
};

export type FoliateAdapterOptions = {
  container: HTMLElement;
  title?: string;
  onInputIntent?: ReaderAdapterInputHandler;
  onEndOfVolume?: () => void;
  fetch?: typeof globalThis.fetch;
};

function clamp(value: number, minimum = 0, maximum = 1) {
  return Math.max(minimum, Math.min(maximum, value));
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}

export function parseFoliateRelocateDetail(value: unknown): FoliateRelocateDetail | null {
  if (!isRecord(value)) return null;
  const cfi = typeof value.cfi === 'string' && value.cfi ? value.cfi : undefined;
  const fraction = typeof value.fraction === 'number' && Number.isFinite(value.fraction)
    ? clamp(value.fraction)
    : undefined;
  const tocItem = isRecord(value.tocItem) ? value.tocItem : undefined;
  return cfi || fraction !== undefined ? { cfi, fraction, tocItem } : null;
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
    return [{ id: `${prefix}-${index}`, label, href, children: children.length ? children : undefined }];
  });
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
  private lifecycleController: AbortController | null = null;
  private view: FoliateView | null = null;
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

  constructor(options: FoliateAdapterOptions) {
    super();
    this.container = options.container;
    this.title = options.title;
    this.onInputIntent = options.onInputIntent;
    this.onEndOfVolume = options.onEndOfVolume;
    this.fetcher = options.fetch;
  }

  getInteractionPolicy(): ReaderInteractionPolicy {
    return { horizontalPaging: this.preferences?.epub.flow === 'scrolled' ? 'none' : 'adapter-interactive' };
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
    this.locationOperation = context.operation;
    this.lastPersistentOperation = context.operation;
    this.preferences = context.preferences;
    this.format = reflowableFormat(context.source);
    this.container.dataset.readerEngine = 'reflowable-v2';
    this.lifecycleController = new AbortController();
    const signal = combineSignals(context.signal, this.lifecycleController.signal);
    this.emit({ type: 'phase-changed', phase: 'loading-content' }, context.operation);
    try {
      await import('foliate-js/view.js');
      throwIfAborted(signal);
      const opened = await openFoliateBook({
        url: context.source.contentUrl,
        format: this.format,
        title: this.title ?? context.source.editionId,
        signal,
        fetch: this.fetcher
      });
      this.assertActive(generation, signal);
      this.book = opened.book;
      this.destroyBook = opened.destroy;
      this.readingDirection = opened.book.dir === 'rtl' ? 'rtl' : 'ltr';
      const view = document.createElement('foliate-view') as FoliateView;
      this.view = view;
      this.bindView(view, generation);
      this.container.replaceChildren(view);
      this.emit({ type: 'phase-changed', phase: 'rendering' }, context.operation);
      await view.open(opened.book);
      this.assertActive(generation, signal);
      this.applyRendererPreferences(context.preferences);
      const navigationItems = foliateNavigationEntries(opened.book.toc);
      if (navigationItems.length) {
        this.emit({ type: 'navigation-changed', items: navigationItems }, context.operation);
      }
      this.suppressRelocate = true;
      await this.restore(normalizeFoliateInitialLocation(context.initialLocation, this.format));
      await nextFrame();
      this.assertActive(generation, signal);
      this.suppressRelocate = false;
      const stable = this.pendingRelocate ?? parseFoliateRelocateDetail(view.lastLocation);
      this.pendingRelocate = null;
      if (stable) this.applyRelocate(stable, context.operation);
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

  async execute(command: ReaderCommand, context: ReaderAdapterOperationContext): Promise<ReaderCommandAck> {
    this.beginOperation(context);
    this.locationOperation = context.operation;
    this.lastPersistentOperation = context.operation;
    const view = this.view;
    if (!view) return this.failOperation(context, 'Reader is not ready');
    try {
      if (command.type === 'next') {
        if (!this.getCapabilities().canGoNext && this.onEndOfVolume) this.onEndOfVolume();
        else await view.next();
      } else if (command.type === 'previous') await view.prev();
      else if (command.type === 'first') await view.goToTextStart();
      else if (command.type === 'last') await view.goToFraction(1);
      else if (command.type === 'go-to-progress') await view.goToFraction(clamp(command.progression));
      else if (command.type === 'go-to-href') await view.goTo(command.href);
      else if (command.type === 'go-to-index') await view.goTo(command.index);
      else if (command.type === 'go-to-location') {
        const location = normalizeFoliateInitialLocation(command.location, this.format);
        if (!location) return this.failOperation(context, 'Location does not belong to the novel reader');
        await this.restore(location);
      } else if (command.type === 'cancel') return this.ack(context.operation, true);
      else return this.failOperation(context, `Unsupported command: ${command.type}`);
      throwIfAborted(context.signal);
      return this.ack(context.operation, true, { location: this.currentLocation ?? undefined });
    } catch (reason) {
      if (isAbortError(reason) || reason instanceof StaleReaderOperationError) throw reason;
      return this.failOperation(context, reason instanceof Error ? reason.message : 'Navigation failed');
    }
  }

  async applyPreferences(preferences: ReaderPreferences, context: ReaderAdapterOperationContext) {
    this.beginOperation(context);
    this.preferences = preferences;
    this.locationOperation = context.operation;
    this.suppressRelocate = true;
    this.applyRendererPreferences(preferences);
    await nextFrame();
    await nextFrame();
    throwIfAborted(context.signal);
    this.suppressRelocate = false;
    const stable = this.pendingRelocate ?? parseFoliateRelocateDetail(this.view?.lastLocation);
    this.pendingRelocate = null;
    if (stable) this.applyRelocate(stable, context.operation);
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
      else this.applyRelocate(detail, this.locationOperation ?? this.currentOperation());
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

  private bindDocument(document: Document) {
    this.bridgedDocuments.get(document)?.abort();
    const controller = new AbortController();
    this.bridgedDocuments.set(document, controller);
    sanitizeEpubDocument(document);
    const frame = document.defaultView?.frameElement;
    hardenEpubIframe(frame instanceof HTMLIFrameElement ? frame : undefined);
    document.documentElement.dataset.shukuInputBridge = 'ready';
    this.container.dataset.readerContent = 'ready';
    this.container.dataset.readerInputBridge = 'ready';
    const signal = controller.signal;
    let touchStart: { x: number; y: number } | null = null;
    let suppressClick = false;
    document.addEventListener('touchstart', (event) => {
      const touch = event.changedTouches[0];
      touchStart = touch ? { x: touch.clientX, y: touch.clientY } : null;
      suppressClick = false;
    }, { passive: true, signal });
    document.addEventListener('touchmove', (event) => {
      const touch = event.changedTouches[0];
      if (touch && touchStart && Math.hypot(touch.clientX - touchStart.x, touch.clientY - touchStart.y) > 12) suppressClick = true;
    }, { passive: true, signal });
    document.addEventListener('keydown', (event) => {
      if (!this.onInputIntent || isReaderControlTarget(event.target)) return;
      const intent = commandForInput(readerKeyIntent(event, this.readingDirection));
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
      const intent = commandForInput(readerPointerIntent(event.clientX, event.clientY, viewport.clientWidth, viewport.clientHeight, this.readingDirection));
      if (!intent) return;
      event.preventDefault();
      void this.onInputIntent(intent);
    }, { signal });
  }

  private applyRendererPreferences(preferences: ReaderPreferences) {
    const renderer = this.view?.renderer;
    if (!renderer) return;
    renderer.setAttribute('flow', preferences.epub.flow);
    renderer.setAttribute('max-inline-size', `${Math.round(clamp(preferences.epub.pageWidth, 600, 1350))}px`);
    renderer.setAttribute('max-column-count', preferences.epub.spreadMode === 'double' ? '2' : '1');
    if (preferences.epub.pageTurnAnimation === 'slide') renderer.setAttribute('animated', '');
    else renderer.removeAttribute('animated');
    renderer.setStyles?.(createEpubThemeSnapshot(preferences, fallbackEpubFont(preferences.epub.fontFamily)));
    this.container.style.background = epubSurfaceColor(preferences);
    this.container.dataset.readerTheme = 'ready';
    this.container.dataset.readerFlow = preferences.epub.flow;
    this.container.dataset.readerSpread = preferences.epub.spreadMode;
  }

  private async restore(location: ReflowableLocation | null) {
    const view = this.view;
    if (!view) return;
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
      .filter((target, index, values): target is string => Boolean(target) && values.indexOf(target) === index);
    for (const target of targets) {
      try {
        const resolved = await view.goTo(target);
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

  private applyRelocate(detail: FoliateRelocateDetail, operation: OperationToken) {
    const progression = detail.fraction ?? this.currentLocation?.progression ?? 0;
    const href = typeof detail.tocItem?.href === 'string' ? detail.tocItem.href : undefined;
    this.currentLocation = {
      kind: 'reflowable',
      format: this.format,
      cfi: detail.cfi,
      href,
      progression
    };
    this.container.dataset.readerLocationCfi = detail.cfi ?? '';
    this.container.dataset.readerLocationHref = href ?? '';
    this.container.dataset.readerLocationProgression = String(progression);
    this.emit({ type: 'location-changed', location: this.currentLocation, percent: progression * 100 }, operation);
    this.emit({ type: 'capabilities-changed', capabilities: this.getCapabilities() }, operation);
  }

  private async cleanupEngine() {
    this.lifecycleController?.abort();
    this.lifecycleController = null;
    this.bridgedDocuments.forEach((controller) => controller.abort());
    this.bridgedDocuments.clear();
    const view = this.view;
    const destroyBook = this.destroyBook;
    this.view = null;
    this.book = null;
    this.destroyBook = null;
    this.currentLocation = null;
    this.pendingRelocate = null;
    this.locationOperation = null;
    this.lastPersistentOperation = null;
    delete this.container.dataset.readerContent;
    delete this.container.dataset.readerInputBridge;
    delete this.container.dataset.readerTheme;
    delete this.container.dataset.readerFlow;
    delete this.container.dataset.readerSpread;
    delete this.container.dataset.readerLocationCfi;
    delete this.container.dataset.readerLocationHref;
    delete this.container.dataset.readerLocationProgression;
    delete this.container.dataset.readerEngine;
    this.container.replaceChildren();
    try {
      view?.close();
    } finally {
      await destroyBook?.();
    }
  }
}

export function createFoliateAdapter(options: FoliateAdapterOptions) {
  return new FoliateReaderAdapter(options);
}
