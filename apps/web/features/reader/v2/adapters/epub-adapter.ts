import type {
  EpubLocation,
  OperationToken,
  ReaderAdapter,
  ReaderAdapterOpenContext,
  ReaderAdapterOperationContext,
  ReaderCapabilities,
  ReaderCommand,
  ReaderCommandAck,
  ReaderPreferences
} from '@shuku/reader-core';
import type { Book, Location, Rendition } from 'epubjs';
import { ReaderAdapterBase, StaleReaderOperationError, errorMessage, isAbortError, throwIfAborted } from './adapter-base';
import {
  EPUB_LOCATION_BREAK,
  claimSharedEpubLocations,
  loadEpubLocations,
  saveEpubLocations,
  saveSharedEpubLocations,
  sharedEpubLocationsWaitMs
} from './epub-location-cache';
import { generateEpubLocations } from './epub-location-generation';
import { approximateEpubProgression, classifyEpubHref, completedEpubProgression, resolveEpubDocumentHref, restoreEpubLocation, selectEpubTocHref, selectEpubVisibleResource, type EpubRestoreTarget } from './epub-restore';
import { hardenEpubIframe, sanitizeEpubDocument, sanitizeEpubDocumentForLocationIndex, sanitizeEpubMarkup } from './epub-security';
import { fallbackEpubFont, resolveEpubFont, type EpubFontResolution } from './epub-font';
import { applyEpubDocumentSpacing, applyEpubThemeSnapshot, epubSurfaceColor, epubSurfaceTextColor } from './epub-theme';
import { EpubLayoutCoordinator, preserveEpubImageDimensions, waitForEpubLayoutBarrier, waitForStableEpubLayout } from './epub-layout';
import { resolveEpubSpineIntervalHref } from '../epub-navigation';
import type { ReaderAdapterInputHandler, ReaderAdapterInputIntent, ReaderInteractiveAdapter, ReaderInteractionPolicy } from './reader-interaction';
import {
  hasActiveTextSelection,
  isReaderControlTarget,
  projectReaderFramePointer,
  readerKeyIntent,
  readerPointerIntentInViewport,
  readerSwipeIntent,
  type ReaderInputIntent
} from '../input-router';

type PageStep = -1 | 1;

type EpubView = {
  document?: Document;
  iframe?: HTMLIFrameElement;
  contents?: {
    on: (event: 'resize' | 'expand', listener: () => void) => void;
    off?: (event: 'resize' | 'expand', listener: () => void) => void;
  };
};

type EpubSection = {
  href?: string;
  index?: number;
  cfiFromElement?: (element: Element) => string;
};

type EpubTocItem = {
  href?: string;
  subitems?: EpubTocItem[];
};

export type EpubAdapterNavigationItem = {
  href?: string | null;
};

export type EpubInputIntent = ReaderAdapterInputIntent;

export type EpubAdapterOptions = {
  container: HTMLElement;
  navigationItems?: readonly EpubAdapterNavigationItem[];
  onInputIntent?: ReaderAdapterInputHandler;
  fetch?: typeof globalThis.fetch;
  locations?: {
    load: typeof loadEpubLocations;
    save: typeof saveEpubLocations;
  };
  sharedLocations?: {
    claim: typeof claimSharedEpubLocations;
    save: typeof saveSharedEpubLocations;
  };
  onEndOfVolume?: () => void;
};

type EpubBook = Omit<Book, 'spine'> & {
  packaging?: { metadata?: { direction?: string } };
  navigation?: { toc?: EpubTocItem[] };
  epubcfi?: { compare: (first: string, second: string) => number };
  spine: Book['spine'] & {
    length?: number;
    get: (target: string | number) => EpubSection | undefined;
  };
};

type RenditionWithLocation = Rendition & {
  currentLocation?: () => Location | Location[] | null;
  off?: (event: 'relocated', listener: (location: Location) => void) => void;
};

type EpubViewTransition = {
  id: number;
  promise: Promise<void>;
  resolve: () => void;
  timer: ReturnType<typeof setTimeout>;
  placeholderTimer: ReturnType<typeof setTimeout>;
  labelTimer: ReturnType<typeof setTimeout>;
  rendered: boolean;
};

const epubTransitionPlaceholderDelayMs = 120;
const epubTransitionLabelDelayMs = 600;

function clamp(value: number, minimum: number, maximum: number) {
  return Math.max(minimum, Math.min(maximum, value));
}

function epubLocationIdentity(location: EpubLocation | null) {
  return location?.cfi ?? (location ? `${location.href ?? ''}:${location.spineIndex ?? ''}:${location.progression ?? ''}` : '');
}

function epubLayoutChanged(previous: ReaderPreferences | null, next: ReaderPreferences) {
  if (!previous) return true;
  return previous.epub.flow !== next.epub.flow
    || previous.epub.fontSize !== next.epub.fontSize
    || previous.epub.lineHeight !== next.epub.lineHeight
    || previous.epub.pageWidth !== next.epub.pageWidth
    || previous.epub.fontFamily !== next.epub.fontFamily
    || previous.epub.spreadMode !== next.epub.spreadMode;
}

function waitForSharedLocations(milliseconds: number, signal: AbortSignal) {
  return new Promise<void>((resolve, reject) => {
    throwIfAborted(signal);
    const timer = window.setTimeout(() => {
      signal.removeEventListener('abort', abort);
      resolve();
    }, milliseconds);
    const abort = () => {
      window.clearTimeout(timer);
      reject(new DOMException('The operation was aborted', 'AbortError'));
    };
    signal.addEventListener('abort', abort, { once: true });
  });
}


export class EpubReaderAdapter extends ReaderAdapterBase implements ReaderAdapter, ReaderInteractiveAdapter {
  private readonly container: HTMLElement;
  private readonly navigationItems: EpubTocItem[];
  private readonly onInputIntent?: EpubAdapterOptions['onInputIntent'];
  private readonly fetcher: typeof globalThis.fetch;
  private readonly locationCache: NonNullable<EpubAdapterOptions['locations']>;
  private readonly sharedLocationCache: NonNullable<EpubAdapterOptions['sharedLocations']>;
  private readonly onEndOfVolume?: EpubAdapterOptions['onEndOfVolume'];
  private lifecycleController: AbortController | null = null;
  private rendition: Rendition | null = null;
  private book: EpubBook | null = null;
  private preferences: ReaderPreferences | null = null;
  private appliedPreferences: ReaderPreferences | null = null;
  private source: ReaderAdapterOpenContext['source'] | null = null;
  private currentLocation: EpubLocation | null = null;
  private readingDirection: 'ltr' | 'rtl' = 'ltr';
  private layoutCoordinator = new EpubLayoutCoordinator();
  private navigationGeneration = 0;
  private preferenceGeneration = 0;
  private resolvedFont: EpubFontResolution | null = null;
  private resolvedFontFamily: ReaderPreferences['epub']['fontFamily'] | null = null;
  private readonly fontResolutions = new Map<ReaderPreferences['epub']['fontFamily'], Promise<EpubFontResolution>>();
  private resizeObserver: ResizeObserver | null = null;
  private resizeFrame: number | null = null;
  private viewportSize = { width: 0, height: 0 };
  private locationsReady = false;
  private locationOperation = null as ReaderAdapterOpenContext['operation'] | null;
  private locationOperationAfterPreference = null as ReaderAdapterOpenContext['operation'] | null;
  private suppressedLocationEmissions = 0;
  private layoutMutationDepth = 0;
  private readerReady = false;
  private pointerGesture: { pointerId: number; x: number; y: number; time: number } | null = null;
  private suppressClickUntil = 0;
  private bridgedDocuments = new WeakMap<Document, AbortController>();
  private documentLayoutDisposers = new WeakMap<Document, () => void>();
  private activeDocuments = new Set<Document>();
  private documentHrefs = new WeakMap<Document, string>();
  private tocCfiCandidates = new WeakMap<Document, Array<{ href: string; cfi: string }>>();
  private tocSpineTargets: Array<{ href: string; sectionIndex: number }> | null = null;
  private renditionAttachments = new WeakMap<Rendition, Promise<void>>();
  private viewTransitionSequence = 0;
  private viewTransition: EpubViewTransition | null = null;
  private viewTransitionPlaceholder: HTMLElement | null = null;
  private hiddenTransitionFrames = new Set<HTMLIFrameElement>();

  constructor(options: EpubAdapterOptions) {
    super();
    this.container = options.container;
    this.navigationItems = (options.navigationItems ?? []).flatMap((item) => {
      const href = item.href?.trim();
      return href ? [{ href }] : [];
    });
    this.onInputIntent = options.onInputIntent;
    this.fetcher = options.fetch ?? globalThis.fetch.bind(globalThis);
    this.locationCache = options.locations ?? { load: loadEpubLocations, save: saveEpubLocations };
    this.sharedLocationCache = options.sharedLocations ?? { claim: claimSharedEpubLocations, save: saveSharedEpubLocations };
    this.onEndOfVolume = options.onEndOfVolume;
  }

  getInteractionPolicy(): ReaderInteractionPolicy {
    if (this.preferences?.epub.flow !== 'paginated') return { horizontalPaging: 'none' };
    return {
      horizontalPaging: this.onInputIntent ? 'adapter-interactive' : 'shell-discrete'
    };
  }


  getCapabilities(): ReaderCapabilities {
    return {
      canGoNext: this.hasAdjacentPage(1),
      canGoPrevious: this.hasAdjacentPage(-1),
      canJumpToProgress: true,
      canJumpToHref: true,
      canJumpToIndex: true,
      canZoom: false,
      canSelectText: true,
      supportsPagination: true,
      supportsScrolling: true,
      supportsSpreads: true,
      readingDirection: this.readingDirection
    };
  }

  async open(context: ReaderAdapterOpenContext) {
    this.cleanupEngine();
    const generation = this.beginSession(context.sessionId, context.operation);
    this.locationOperation = context.operation;
    this.locationOperationAfterPreference = null;
    this.preferences = context.preferences;
    this.appliedPreferences = context.preferences;
    this.resolvedFont = fallbackEpubFont(context.preferences.epub.fontFamily);
    this.resolvedFontFamily = context.preferences.epub.fontFamily;
    this.source = context.source;
    this.lifecycleController = new AbortController();
    const signal = this.combineSignals(context.signal, this.lifecycleController.signal);
    this.container.replaceChildren();
    this.container.style.background = epubSurfaceColor(context.preferences);
    this.applyContainerMeasure(context.preferences);
    this.container.dataset.readerEngine = 'epub-v2';
    this.emit({ type: 'phase-changed', phase: 'loading-content' }, context.operation);

    try {
      const [response, epubModule] = await Promise.all([
        this.fetcher(context.source.contentUrl, { signal }),
        import('epubjs')
      ]);
      if (!response.ok) throw new Error(`EPUB 文件加载失败 (${response.status})`);
      const buffer = await response.arrayBuffer();
      this.assertActive(generation, signal);

      const book = epubModule.default() as EpubBook;
      this.book = book;
      await book.open(buffer, 'binary');
      await Promise.all([book.opened, book.ready]);
      this.assertActive(generation, signal);

      this.readingDirection = (book as EpubBook).packaging?.metadata?.direction === 'rtl' ? 'rtl' : 'ltr';
      let cachedLocations = null as string | null;
      try {
        cachedLocations = await this.locationCache.load(context.source.contentFingerprint, EPUB_LOCATION_BREAK);
      } catch {
        // A cache failure must never make a readable book unavailable.
      }
      this.assertActive(generation, signal);
      if (cachedLocations) {
        try {
          book.locations.load(cachedLocations);
          this.locationsReady = book.locations.length() > 0;
        } catch {
          cachedLocations = null;
          this.locationsReady = false;
        }
      }
      if (this.locationsReady && cachedLocations) {
        try {
          const shared = await this.sharedLocationCache.claim(context.source, EPUB_LOCATION_BREAK, signal);
          if (shared.status === 'claimed') {
            await this.sharedLocationCache.save(
              context.source,
              shared.leaseToken,
              cachedLocations,
              EPUB_LOCATION_BREAK,
              signal
            );
          }
        } catch (reason) {
          if (isAbortError(reason)) throw reason;
          // A local index remains sufficient when the shared cache is offline.
        }
        this.assertActive(generation, signal);
      }
      if (!this.locationsReady) {
        this.emit({ type: 'phase-changed', phase: 'generating-pagination' }, context.operation);
        let sharedLeaseToken: string | null = null;
        const sharedWaitStartedAt = Date.now();
        try {
          try {
            while (!this.locationsReady && !sharedLeaseToken) {
              const shared = await this.sharedLocationCache.claim(context.source, EPUB_LOCATION_BREAK, signal);
              this.assertActive(generation, signal);
              if (shared.status === 'ready') {
                book.locations.load(shared.serialized);
                this.locationsReady = book.locations.length() > 0;
                if (this.locationsReady) {
                  await this.locationCache.save(
                    context.source.contentFingerprint,
                    shared.serialized,
                    EPUB_LOCATION_BREAK
                  ).catch(() => undefined);
                }
                break;
              }
              if (shared.status === 'claimed') {
                sharedLeaseToken = shared.leaseToken;
                break;
              }
              this.emit({ type: 'pagination-progress', completed: 0, total: 0, percent: 0 }, context.operation);
              const waitMs = sharedEpubLocationsWaitMs(shared.retryAfterMs, sharedWaitStartedAt);
              if (waitMs <= 0) break;
              await waitForSharedLocations(waitMs, signal);
            }
          } catch (reason) {
            if (isAbortError(reason) || reason instanceof StaleReaderOperationError) throw reason;
            // The server cache is an optimization. Generate locally if it is unavailable.
          }

          if (!this.locationsReady) {
            const generatedLocations = await generateEpubLocations(book, {
              breakSize: EPUB_LOCATION_BREAK,
              signal,
              prepareDocument: sanitizeEpubDocumentForLocationIndex,
              onProgress: ({ completed, total, percent }) => {
                if (!this.isActive(generation, signal)) return;
                this.emit({ type: 'pagination-progress', completed, total, percent }, context.operation);
              }
            });
            book.locations.load(JSON.stringify(generatedLocations));
            this.assertActive(generation, signal);
            this.locationsReady = book.locations.length() > 0;
            if (this.locationsReady) {
              const serialized = book.locations.save();
              await this.locationCache.save(
                context.source.contentFingerprint,
                serialized,
                EPUB_LOCATION_BREAK
              ).catch(() => undefined);
              if (sharedLeaseToken) {
                await this.sharedLocationCache.save(
                  context.source,
                  sharedLeaseToken,
                  serialized,
                  EPUB_LOCATION_BREAK,
                  signal
                ).catch(() => undefined);
              }
            }
          }
        } catch (reason) {
          if (isAbortError(reason) || reason instanceof StaleReaderOperationError) throw reason;
          // Location maps improve percentage jumps but a damaged section must
          // not make an otherwise readable EPUB unavailable.
          book.locations.load('[]');
          this.locationsReady = false;
        }
        this.assertActive(generation, signal);
      }

      book.spine.hooks.content.register((document: Document) => {
        sanitizeEpubDocument(document);
        const preferences = this.appliedPreferences ?? context.preferences;
        applyEpubThemeSnapshot(document, preferences, this.resolvedFont ?? fallbackEpubFont(preferences.epub.fontFamily));
        applyEpubDocumentSpacing(document, preferences);
      });
      book.spine.hooks.serialize.register((markup: string, section: { output?: string }) => {
        section.output = sanitizeEpubMarkup(section.output ?? markup);
      });

      const activePreferences = this.preferences ?? context.preferences;
      this.emit({ type: 'phase-changed', phase: 'loading-font' }, context.operation);
      this.resolvedFont = await this.resolveSessionFont(activePreferences.epub.fontFamily, signal);
      this.resolvedFontFamily = activePreferences.epub.fontFamily;
      this.assertActive(generation, signal);
      const rendition = this.createRendition(book, activePreferences, generation);
      this.viewportSize = this.readContainerViewport();
      await this.waitForRenditionAttached(rendition, signal);
      this.assertActive(generation, signal);
      this.emit({ type: 'phase-changed', phase: 'rendering' }, context.operation);
      const initialLocation = context.initialLocation?.kind === 'epub' ? context.initialLocation : null;
      await restoreEpubLocation(initialLocation, (target) => this.displayRestoreTarget(target, signal));
      this.assertActive(generation, signal);
      await waitForEpubLayoutBarrier(this.activeDocuments, signal);
      this.assertActive(generation, signal);
      const anchorCfi = initialLocation?.cfi?.trim() || this.renditionLocation()?.start?.cfi;
      if (anchorCfi) {
        await this.displayAndWaitForRelocated(anchorCfi, signal);
        await waitForStableEpubLayout(this.activeDocuments, signal);
        this.assertActive(generation, signal);
      }
      this.applyThemeToActiveDocuments(activePreferences);
      const location = this.readCurrentLocation();
      if (location) this.currentLocation = location;
      this.readerReady = true;
      this.installResizeObserver(generation);
      this.emit({ type: 'ready', capabilities: this.getCapabilities(), location: this.currentLocation }, context.operation);
    } catch (reason) {
      if (isAbortError(reason) || reason instanceof StaleReaderOperationError) return;
      this.emit({
        type: 'error',
        error: { code: 'EPUB_OPEN_FAILED', message: errorMessage(reason, 'EPUB 加载失败'), recoverable: true }
      }, context.operation);
      throw reason;
    }
  }

  async execute(command: ReaderCommand, context: ReaderAdapterOperationContext): Promise<ReaderCommandAck> {
    try {
      this.beginOperation(context);
    } catch {
      return this.failOperation(context, 'stale-session');
    }
    if (command.type === 'retry') {
      const source = this.source;
      const preferences = this.preferences;
      const initialLocation = this.currentLocation;
      if (!source || !preferences) return this.failOperation(context, 'retry-context-unavailable');
      try {
        await this.open({
          sessionId: context.operation.sessionId,
          operation: context.operation,
          signal: context.signal,
          source,
          initialLocation,
          preferences
        });
        return context.signal.aborted
          ? this.failOperation(context, 'operation-cancelled')
          : this.ack(context.operation, true, { location: this.currentLocation ?? undefined });
      } catch (reason) {
        return this.failOperation(context, errorMessage(reason, 'retry-failed'));
      }
    }
    if (!this.rendition || !this.book) return this.failOperation(context, 'not-ready');
    if (command.type === 'set-zoom' || command.type === 'set-fit') return this.failOperation(context, 'unsupported-command');
    if (command.type === 'cancel') {
      this.navigationGeneration += 1;
      this.pointerGesture = null;
      return this.ack(context.operation, true, { location: this.currentLocation ?? undefined });
    }
    if (command.type === 'previous' && !this.hasAdjacentPage(-1)) {
      this.emit({ type: 'activity' }, context.operation);
      return this.failOperation(context, 'start-of-volume');
    }
    if (command.type === 'next' && !this.hasAdjacentPage(1)) {
      this.emit({ type: 'activity' }, context.operation);
      this.emitCompletedLocation(context.operation);
      this.onEndOfVolume?.();
      return this.failOperation(context, 'end-of-volume');
    }
    const queuedGeneration = this.currentGeneration();
    const navigationGeneration = this.navigationGeneration;
    const locationBeforeCommand = command.type === 'next' ? this.readCurrentLocation() : null;
    const task = this.layoutCoordinator.enqueueNavigation(async () => {
      this.assertActive(queuedGeneration, context.signal);
      if (navigationGeneration !== this.navigationGeneration) throw new StaleReaderOperationError();
      this.locationOperation = context.operation;
      this.locationOperationAfterPreference = null;
      this.emit({ type: 'activity' }, context.operation);
      await this.runCommand(command, context.signal);
      if (
        command.type === 'next'
        && !this.hasAdjacentPage(1)
        && epubLocationIdentity(locationBeforeCommand)
        && epubLocationIdentity(locationBeforeCommand) === epubLocationIdentity(this.readCurrentLocation())
      ) {
        this.emitCompletedLocation(context.operation);
        this.onEndOfVolume?.();
      }
      this.assertActive(queuedGeneration, context.signal);
      if (command.type !== 'next' && command.type !== 'previous') {
        this.rendition?.reportLocation();
        const viewportLocation = this.readCurrentLocation();
        if (
          viewportLocation
          && epubLocationIdentity(viewportLocation) !== epubLocationIdentity(this.currentLocation)
        ) {
          this.currentLocation = viewportLocation;
          this.emit({
            type: 'location-changed',
            location: viewportLocation,
            percent: viewportLocation.progression * 100
          }, context.operation);
          this.emit({ type: 'capabilities-changed', capabilities: this.getCapabilities() }, context.operation);
        }
      }
    });

    try {
      await task;
      return this.ack(context.operation, true, { location: this.currentLocation ?? undefined });
    } catch (reason) {
      if (isAbortError(reason) || reason instanceof StaleReaderOperationError) {
        return this.failOperation(context, 'operation-cancelled');
      }
      this.emit({
        type: 'error',
        error: { code: 'EPUB_NAVIGATION_FAILED', message: errorMessage(reason, 'EPUB 导航失败'), recoverable: true }
      }, context.operation);
      return this.failOperation(context, errorMessage(reason, 'navigation-failed'));
    }
  }

  async applyPreferences(preferences: ReaderPreferences, context: ReaderAdapterOperationContext): Promise<ReaderCommandAck> {
    try {
      this.beginOperation(context);
    } catch {
      return this.failOperation(context, 'stale-session');
    }
    const sessionGeneration = this.currentGeneration();
    const preferenceGeneration = ++this.preferenceGeneration;
    const layoutChanged = epubLayoutChanged(this.appliedPreferences, preferences);
    const fontChanged = this.resolvedFontFamily !== preferences.epub.fontFamily;
    this.preferences = preferences;
    this.container.style.background = epubSurfaceColor(preferences);
    this.pointerGesture = null;
    if (!this.rendition) {
      this.appliedPreferences = preferences;
      this.applyContainerMeasure(preferences);
      return this.ack(context.operation, true, { location: this.currentLocation ?? undefined });
    }
    let announcedFontLoading = false;
    try {
      if (layoutChanged && fontChanged) {
        announcedFontLoading = true;
        this.emit({ type: 'phase-changed', phase: 'loading-font' }, context.operation);
      }
      let applied = false;
      if (layoutChanged) {
        const scheduled = this.enqueueLayoutTransaction({
          preferences,
          operation: context.operation,
          requestSignal: context.signal,
          generation: sessionGeneration
        });
        applied = await scheduled.promise;
      } else {
        await this.layoutCoordinator.enqueueNavigation(async () => {
          this.assertActive(sessionGeneration, context.signal);
          if (preferenceGeneration !== this.preferenceGeneration) throw new StaleReaderOperationError();
          this.appliedPreferences = preferences;
          this.applyThemeToActiveDocuments(preferences);
          applied = true;
        });
      }
      if (!applied || context.signal.aborted || preferenceGeneration !== this.preferenceGeneration) {
        return this.failOperation(context, 'operation-cancelled');
      }
    } catch (reason) {
      if (isAbortError(reason) || reason instanceof StaleReaderOperationError) {
        return this.failOperation(context, 'operation-cancelled');
      }
      throw reason;
    } finally {
      if (announcedFontLoading && !context.signal.aborted && preferenceGeneration === this.preferenceGeneration) {
        this.emit({ type: 'phase-changed', phase: null }, context.operation);
      }
    }
    return this.ack(context.operation, true, { location: this.currentLocation ?? undefined });
  }

  dispose() {
    if (!this.markDisposed()) return;
    this.cleanupEngine();
    this.releaseFontResolutions();
  }

  private async runCommand(command: Exclude<ReaderCommand, { type: 'set-zoom' | 'set-fit' | 'retry' | 'cancel' }>, signal: AbortSignal) {
    const rendition = this.rendition;
    const book = this.book;
    if (!rendition || !book) throw new Error('EPUB is not ready');
    throwIfAborted(signal);
    if (command.type !== 'next' && command.type !== 'previous') this.pointerGesture = null;
    switch (command.type) {
      case 'next':
        await this.runPagedStep(1, signal);
        return;
      case 'previous':
        await this.runPagedStep(-1, signal);
        return;
      case 'first':
        await this.displayAndWaitForRelocated(0, signal);
        return;
      case 'last':
        await this.displayAndWaitForRelocated(book.spine.last()?.href ?? 0, signal);
        return;
      case 'go-to-progress': {
        const progression = clamp(command.progression, 0, 1);
        const cfi = this.locationsReady && progression > 0
          ? book.locations.cfiFromPercentage(progression)
          : undefined;
        if (cfi) await this.displayAndWaitForRelocated(cfi, signal);
        else await this.displayAndWaitForRelocated(this.spineIndexFromProgression(progression), signal);
        return;
      }
      case 'go-to-href':
        await this.displayAndWaitForRelocated(command.href, signal);
        return;
      case 'go-to-index':
        await this.displayAndWaitForRelocated(Math.max(0, Math.round(command.index) - 1), signal);
        return;
      case 'go-to-location':
        if (command.location.kind !== 'epub') throw new Error('location-kind-mismatch');
        await restoreEpubLocation(command.location, (target) => this.displayRestoreTarget(target, signal));
        return;
    }
  }

  private createRendition(book: EpubBook, preferences: ReaderPreferences, generation: number) {
    const spread = preferences.epub.spreadMode === 'double' ? 'always' : 'none';
    const minSpreadWidth = preferences.epub.spreadMode === 'double' ? 0 : Number.MAX_SAFE_INTEGER;
    const rendition = book.renderTo(this.container, {
      manager: preferences.epub.flow === 'paginated' ? 'default' : 'continuous',
      width: '100%',
      height: '100%',
      flow: preferences.epub.flow === 'scrolled' ? 'scrolled-doc' : 'paginated',
      spread,
      minSpreadWidth,
      // Safari requires this sandbox capability for callbacks registered by
      // the host. EPUB-authored scripts are still stripped and denied by CSP.
      allowScriptedContent: true
    });
    const attached = new Promise<void>((resolve) => rendition.on('attached', resolve));
    this.renditionAttachments.set(rendition, attached);
    this.rendition = rendition;
    rendition.spread(spread, minSpreadWidth);
    rendition.on('rendered', (section: EpubSection, view: EpubView) => this.handleRenderedView(view, generation, section));
    rendition.on('removed', (_section: unknown, view: EpubView) => this.releaseDocumentBridge(view.document));
    rendition.on('relocated', (location: Location) => this.handleRelocated(location, generation));
    return rendition;
  }

  private releaseRendition() {
    Array.from(this.activeDocuments).forEach((document) => this.releaseDocumentBridge(document));
    try {
      this.rendition?.destroy();
    } catch {
      // A view can be between attach and removal while a flow switch wins.
    }
    this.rendition = null;
    this.container.replaceChildren();
  }

  private async runPagedStep(step: PageStep, signal: AbortSignal) {
    const rendition = this.rendition;
    if (!rendition) throw new Error('EPUB is not ready');
    const previous = this.readCurrentLocation() ?? this.currentLocation;
    const transition = this.preferences?.epub.flow === 'paginated' ? this.beginViewTransition() : null;
    try {
      if (step === 1) await rendition.next();
      else await rendition.prev();
      throwIfAborted(signal);
      // Same-spine rendition steps do not render a new iframe. In that case
      // there is nothing to gate and the placeholder disappears immediately.
      if (transition && !transition.rendered) this.finishViewTransition(transition.id);
      else if (transition) await this.waitForRequest(transition.promise, signal);
    } catch (reason) {
      this.finishViewTransition();
      throw reason;
    }

    const location = this.readCurrentLocation();
    if (!location) return;
    const changed = epubLocationIdentity(previous) !== epubLocationIdentity(location);
    this.currentLocation = location;
    if (changed) {
      const operation = this.locationOperation ?? this.currentOperation();
      this.emit({ type: 'location-changed', location, percent: (location.progression ?? 0) * 100 }, operation);
      this.emit({ type: 'capabilities-changed', capabilities: this.getCapabilities() }, operation);
    }
  }

  private enqueueLayoutTransaction(options: {
    preferences: ReaderPreferences;
    operation: ReaderAdapterOpenContext['operation'];
    requestSignal: AbortSignal;
    generation: number;
    viewport?: { width: number; height: number };
  }) {
    let completed = false;
    const scheduled = this.layoutCoordinator.enqueueLayout(async ({ isCurrent }) => {
      this.assertActive(options.generation, options.requestSignal);
      let resolvedFont = this.resolvedFont;
      if (!resolvedFont || this.resolvedFontFamily !== options.preferences.epub.fontFamily) {
        resolvedFont = await this.resolveSessionFont(options.preferences.epub.fontFamily, options.requestSignal);
      }
      this.assertActive(options.generation, options.requestSignal);
      if (!isCurrent()) return;

      let rendition = this.rendition;
      const book = this.book;
      if (!rendition || !book) throw new StaleReaderOperationError();
      const previousPreferences = this.appliedPreferences;
      const currentRenditionLocation = this.renditionLocation();
      const anchorCfi = this.currentLocation?.cfi ?? currentRenditionLocation?.start?.cfi;
      const anchorTarget = anchorCfi
        ?? currentRenditionLocation?.start?.href
        ?? this.currentLocation?.href
        ?? 0;
      const lifecycleSignal = this.lifecycleController?.signal ?? options.requestSignal;

      this.pointerGesture = null;
      // From this point through CFI restoration the queue owns the rendition.
      // A newer epoch can be requested, but cannot mutate until this atomic
      // transaction has restored the pre-layout anchor.
      this.suppressedLocationEmissions += 1;
      this.layoutMutationDepth += 1;
      if (options.operation.kind === 'preferences') {
        this.locationOperationAfterPreference = this.locationOperation?.kind === 'preferences'
          ? this.locationOperationAfterPreference
          : this.locationOperation;
      }
      this.locationOperation = options.operation;
      try {
        this.appliedPreferences = options.preferences;
        this.resolvedFont = resolvedFont;
        this.resolvedFontFamily = options.preferences.epub.fontFamily;
        this.applyContainerMeasure(options.preferences);
        const flowChanged = previousPreferences?.epub.flow !== options.preferences.epub.flow;
        if (flowChanged) {
          // The manager type is immutable after renderTo(). Preserve the CFI,
          // replace only the rendition, and keep the Book/package alive.
          this.releaseRendition();
          rendition = this.createRendition(book, options.preferences, options.generation);
          await this.waitForRenditionAttached(rendition, lifecycleSignal);
          this.assertActive(options.generation, lifecycleSignal);
        }
        const spread = options.preferences.epub.spreadMode === 'double' ? 'always' : 'none';
        const minSpreadWidth = options.preferences.epub.spreadMode === 'double' ? 0 : Number.MAX_SAFE_INTEGER;
        rendition.spread(spread, minSpreadWidth);
        const viewport = options.viewport ?? this.readContainerViewport();
        this.viewportSize = viewport;
        if (viewport.width > 0 && viewport.height > 0) rendition.resize(viewport.width, viewport.height);

        await waitForEpubLayoutBarrier(this.activeDocuments, lifecycleSignal);
        this.assertActive(options.generation, lifecycleSignal);
        if (anchorCfi || flowChanged) {
          await this.displayAndWaitForRelocated(anchorTarget, lifecycleSignal);
          await waitForStableEpubLayout(this.activeDocuments, lifecycleSignal);
          this.assertActive(options.generation, lifecycleSignal);
        }
        this.applyThemeToActiveDocuments(options.preferences);
        // reportLocation may resolve asynchronously in epub.js. The restored
        // CFI has already updated currentLocation, so handleRelocated's identity
        // gate prevents this presentation-only report from escaping suppression.
        rendition.reportLocation();
        const location = this.readCurrentLocation();
        if (location) this.currentLocation = location;
        completed = true;
      } finally {
        this.layoutMutationDepth = Math.max(0, this.layoutMutationDepth - 1);
        this.suppressedLocationEmissions = Math.max(0, this.suppressedLocationEmissions - 1);
      }
    });
    return {
      epoch: scheduled.epoch,
      promise: scheduled.promise.then((accepted) => accepted && completed)
    };
  }

  private async displayAndWaitForRelocated(target: string | number, signal: AbortSignal) {
    const rendition = this.rendition as RenditionWithLocation | null;
    if (!rendition) throw new Error('EPUB is not ready');
    throwIfAborted(signal);
    let resolveRelocated!: () => void;
    const relocated = new Promise<void>((resolve) => { resolveRelocated = resolve; });
    const listener = () => resolveRelocated();
    rendition.on('relocated', listener);
    let fallbackTimer: ReturnType<typeof setTimeout> | null = null;
    try {
      if (typeof target === 'number') await rendition.display(target);
      else await rendition.display(target);
      await this.waitForRequest(Promise.race([
        relocated,
        new Promise<void>((resolve) => { fallbackTimer = setTimeout(resolve, 1_200); })
      ]), signal);
      throwIfAborted(signal);
      // The first relocated event can precede the newly rendered iframe's
      // final bounds. Re-report after consecutive stable paints so chapter
      // highlighting follows the document that actually occupies the viewport.
      await waitForStableEpubLayout(this.activeDocuments, signal);
      throwIfAborted(signal);
      rendition.reportLocation();
    } finally {
      if (fallbackTimer !== null) clearTimeout(fallbackTimer);
      rendition.off?.('relocated', listener);
    }
  }

  private async waitForRenditionAttached(rendition: Rendition, signal: AbortSignal) {
    await this.waitForRequest(rendition.started, signal);
    const attached = this.renditionAttachments.get(rendition);
    if (attached) await this.waitForRequest(attached, signal);
    throwIfAborted(signal);
  }

  private spineIndexFromProgression(progression: number) {
    const length = Math.max(1, Number(this.book?.spine.length) || 1);
    return Math.min(length - 1, Math.floor(clamp(progression, 0, 1) * length));
  }

  private async displayRestoreTarget(target: EpubRestoreTarget, requestSignal?: AbortSignal) {
    const rendition = this.rendition;
    const book = this.book;
    if (!rendition || !book) throw new Error('EPUB is not ready');
    const signal = requestSignal ?? this.lifecycleController?.signal ?? new AbortController().signal;
    if (target.kind === 'cfi' || target.kind === 'href') return this.displayAndWaitForRelocated(target.value, signal);
    if (target.kind === 'spine') return this.displayAndWaitForRelocated(target.value, signal);
    if (target.kind === 'progression') {
      // epub.js stores range CFIs. Its first generated range can resolve to the
      // end of a short first section, so exact 0 must always mean spine start.
      const cfi = this.locationsReady && target.value > 0
        ? book.locations.cfiFromPercentage(target.value)
        : undefined;
      return this.displayAndWaitForRelocated(cfi || this.spineIndexFromProgression(target.value), signal);
    }
    return this.displayAndWaitForRelocated(0, signal);
  }

  private handleRenderedView(view: EpubView, generation: number, section?: EpubSection) {
    if (!this.isActive(generation)) return;
    hardenEpubIframe(view.iframe);
    if (!view.document) return;
    const transition = this.viewTransition;
    if (transition && view.iframe) {
      transition.rendered = true;
      view.iframe.style.setProperty('opacity', '0', 'important');
      this.hiddenTransitionFrames.add(view.iframe);
    }
    view.document.documentElement.dataset.shukuThemeReady = 'pending';
    this.activeDocuments.add(view.document);
    if (section?.href) this.documentHrefs.set(view.document, section.href);
    sanitizeEpubDocument(view.document);
    if (this.appliedPreferences) {
      applyEpubThemeSnapshot(view.document, this.appliedPreferences, this.resolvedFont ?? fallbackEpubFont(this.appliedPreferences.epub.fontFamily));
      applyEpubDocumentSpacing(view.document, this.appliedPreferences);
      this.applyDocumentInteractionMode(view.document, this.appliedPreferences);
    }
    view.document.querySelectorAll<HTMLImageElement>('img').forEach((image) => {
      if (image.complete) preserveEpubImageDimensions(image);
    });
    this.bindDocumentLayout(view, generation);
    view.document.querySelectorAll<HTMLAnchorElement>('a').forEach((anchor) => {
      // epub.js installs property handlers after spine sanitization. Remove them
      // so the semantic bridge remains the sole navigation event source.
      anchor.onclick = null;
    });
    this.bridgeDocumentInput(view.document, generation);
    if (transition && view.iframe) {
      void this.revealTransitionView(view.document, view.iframe, generation, transition.id);
    } else {
      view.document.documentElement.dataset.shukuThemeReady = 'ready';
    }
  }

  private beginViewTransition() {
    if (!this.readerReady) return null;
    if (this.viewTransition) return this.viewTransition;

    const preferences = this.appliedPreferences ?? this.preferences;
    const placeholder = this.container.ownerDocument.createElement('div');
    placeholder.dataset.shukuEpubTransitionPlaceholder = 'true';
    placeholder.setAttribute('aria-hidden', 'true');
    Object.assign(placeholder.style, {
      position: 'absolute',
      inset: '0',
      zIndex: '20',
      display: 'none',
      alignItems: 'center',
      justifyContent: 'center',
      pointerEvents: 'none',
      background: preferences ? epubSurfaceColor(preferences) : this.container.style.background,
      color: preferences ? epubSurfaceTextColor(preferences) : 'inherit'
    });
    const label = this.container.ownerDocument.createElement('span');
    label.textContent = '正在载入下一章…';
    Object.assign(label.style, {
      fontSize: '14px',
      letterSpacing: '0.08em',
      opacity: '0'
    });
    placeholder.append(label);
    if (this.container.ownerDocument.defaultView?.getComputedStyle(this.container).position === 'static') {
      this.container.style.position = 'relative';
      this.container.dataset.shukuEpubTransitionPosition = 'true';
    }
    this.container.append(placeholder);
    this.container.dataset.shukuEpubTransitionActive = 'true';
    this.viewTransitionPlaceholder = placeholder;

    const id = ++this.viewTransitionSequence;
    let resolve!: () => void;
    const promise = new Promise<void>((settle) => { resolve = settle; });
    const timer = setTimeout(() => this.finishViewTransition(id), 5_000);
    const placeholderTimer = setTimeout(() => {
      if (this.viewTransition?.id !== id || !placeholder.isConnected) return;
      placeholder.style.display = 'flex';
    }, epubTransitionPlaceholderDelayMs);
    const labelTimer = setTimeout(() => {
      if (this.viewTransition?.id !== id || !label.isConnected) return;
      label.style.opacity = '0.62';
    }, epubTransitionLabelDelayMs);
    this.viewTransition = { id, promise, resolve, timer, placeholderTimer, labelTimer, rendered: false };
    return this.viewTransition;
  }

  private async revealTransitionView(document: Document, iframe: HTMLIFrameElement, generation: number, transitionId: number) {
    const signal = this.lifecycleController?.signal;
    try {
      await waitForEpubLayoutBarrier([document], signal);
      if (!this.isActive(generation, signal) || this.viewTransition?.id !== transitionId) return;
      const preferences = this.appliedPreferences ?? this.preferences;
      if (preferences) {
        applyEpubThemeSnapshot(document, preferences, this.resolvedFont ?? fallbackEpubFont(preferences.epub.fontFamily));
        applyEpubDocumentSpacing(document, preferences);
        this.applyDocumentInteractionMode(document, preferences);
        await waitForStableEpubLayout([document], signal);
      }
      if (!this.isActive(generation, signal) || this.viewTransition?.id !== transitionId) return;
      document.documentElement.dataset.shukuThemeReady = 'ready';
      iframe.dataset.shukuEpubTransitionReady = 'true';
      iframe.style.removeProperty('opacity');
      this.hiddenTransitionFrames.delete(iframe);
      await new Promise<void>((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => resolve())));
      this.finishViewTransition(transitionId);
    } catch {
      if (this.viewTransition?.id === transitionId) this.finishViewTransition(transitionId);
    }
  }

  private finishViewTransition(id?: number) {
    const transition = this.viewTransition;
    if (!transition || (id !== undefined && transition.id !== id)) return;
    clearTimeout(transition.timer);
    clearTimeout(transition.placeholderTimer);
    clearTimeout(transition.labelTimer);
    this.hiddenTransitionFrames.forEach((iframe) => iframe.style.removeProperty('opacity'));
    this.hiddenTransitionFrames.clear();
    delete this.container.dataset.shukuEpubTransitionActive;
    this.viewTransitionPlaceholder?.remove();
    this.viewTransitionPlaceholder = null;
    this.viewTransition = null;
    transition.resolve();
  }

  private handleRelocated(location: Location, generation: number) {
    if (!this.isActive(generation) || !this.book) return;
    const anchor = this.resolveRenditionAnchor(location);
    const cfi = anchor?.cfi;
    const href = this.resolveCurrentTocHref(anchor?.href, cfi);
    const anchorIndex = anchor?.index;
    const spineIndex = Number.isFinite(anchorIndex) ? Math.max(0, Math.round(anchorIndex!)) : undefined;
    const progression = completedEpubProgression(cfi && this.locationsReady
      ? clamp(this.book.locations.percentageFromCfi(cfi), 0, 1)
      : approximateEpubProgression(
        anchor?.index,
        anchor?.percentage,
        Number(this.book.spine.length) || 0,
        anchor?.displayed?.page,
        anchor?.displayed?.total
      ), Boolean(location.atEnd && spineIndex === Math.max(0, (Number(this.book.spine.length) || 1) - 1)));
    const readerLocation: EpubLocation = { kind: 'epub', cfi, href, spineIndex, progression };
    const locationChanged = epubLocationIdentity(this.currentLocation) !== epubLocationIdentity(readerLocation);
    this.currentLocation = readerLocation;
    if (this.suppressedLocationEmissions > 0 || !locationChanged) return;
    this.emit({ type: 'location-changed', location: readerLocation, percent: progression * 100 }, this.locationOperation ?? this.currentOperation());
    this.emit({ type: 'capabilities-changed', capabilities: this.getCapabilities() }, this.locationOperation ?? this.currentOperation());
  }

  private hasAdjacentPage(step: PageStep) {
    const current = this.renditionLocation();
    const anchor = this.resolveRenditionAnchor(current);
    if (!anchor) return false;
    const anchorIndex = anchor.index;
    const lastSpineIndex = Math.max(0, (Number(this.book?.spine.length) || 1) - 1);
    if (step === 1) return !current?.atEnd || (Number.isFinite(anchorIndex) && anchorIndex! < lastSpineIndex);
    return !current?.atStart || (Number.isFinite(anchorIndex) && anchorIndex! > 0);
  }


  private readCurrentLocation() {
    const current = this.renditionLocation();
    const start = this.resolveRenditionAnchor(current);
    if (!start) return null;
    const cfi = start?.cfi;
    const spineIndex = start?.index;
    const progression = completedEpubProgression(cfi && this.book && this.locationsReady
      ? clamp(this.book.locations.percentageFromCfi(cfi), 0, 1)
      : approximateEpubProgression(
        start?.index,
        start?.percentage,
        Number(this.book?.spine.length) || 0,
        start?.displayed?.page,
        start?.displayed?.total
      ), Boolean(current?.atEnd && start.index === Math.max(0, (Number(this.book?.spine.length) || 1) - 1)));
    return {
      kind: 'epub' as const,
      cfi,
      href: this.resolveCurrentTocHref(start?.href, cfi),
      spineIndex: Number.isFinite(spineIndex) ? Math.max(0, Math.round(spineIndex!)) : undefined,
      progression
    };
  }

  private renditionLocation() {
    const current = (this.rendition as RenditionWithLocation | null)?.currentLocation?.();
    return Array.isArray(current) ? current[0] ?? null : current ?? null;
  }

  private resolveRenditionAnchor(location: Location | null) {
    const start = location?.start;
    const viewport = this.container.getBoundingClientRect();
    const candidates = Array.from(this.container.querySelectorAll<HTMLElement>('.epub-view[ref]')).flatMap((view) => {
      const index = Number(view.getAttribute('ref'));
      const section = Number.isFinite(index) ? this.book?.spine.get(index) : null;
      const href = section?.href;
      if (!href) return [];
      const bounds = view.getBoundingClientRect();
      return [{ href, index, left: bounds.left, top: bounds.top, right: bounds.right, bottom: bounds.bottom }];
    });
    const visibleHref = selectEpubVisibleResource(candidates, {
      left: viewport.left,
      top: viewport.top,
      right: viewport.right,
      bottom: viewport.bottom
    }, start?.href);
    if (!visibleHref || (start && this.resourceHrefKey(visibleHref) === this.resourceHrefKey(start.href))) return start;

    const end = location?.end;
    if (end && this.resourceHrefKey(visibleHref) === this.resourceHrefKey(end.href)) return end;

    const visible = candidates.find((candidate) => this.resourceHrefKey(candidate.href) === this.resourceHrefKey(visibleHref));
    const section = this.book?.spine.get(visibleHref);
    let cfi: string | undefined;
    const visibleDocument = Array.from(this.activeDocuments).find((document) => (
      this.resourceHrefKey(this.documentHrefs.get(document)) === this.resourceHrefKey(visibleHref)
    ));
    const cfiElement = visibleDocument?.body?.firstElementChild ?? visibleDocument?.body;
    if (cfiElement && section?.cfiFromElement) {
      try { cfi = section.cfiFromElement(cfiElement); } catch { /* fall back to the resource anchor */ }
    }
    return {
      ...(start ?? {}),
      cfi,
      href: visibleHref,
      index: Number.isFinite(section?.index) ? section!.index : visible?.index ?? start?.index,
      percentage: undefined,
      displayed: { page: 1, total: start?.displayed?.total ?? 1 }
    };
  }

  private emitCompletedLocation(operation: OperationToken) {
    const current = this.readCurrentLocation();
    if (!current) return;
    const completed = { ...current, progression: 1 };
    this.currentLocation = completed;
    this.emit({ type: 'location-changed', location: completed, percent: 100 }, operation);
    this.emit({ type: 'capabilities-changed', capabilities: this.getCapabilities() }, operation);
  }

  private applyThemeToActiveDocuments(preferences: ReaderPreferences) {
    this.container.querySelectorAll<HTMLIFrameElement>('iframe').forEach((iframe) => {
      try {
        if (iframe.contentDocument) {
          applyEpubThemeSnapshot(iframe.contentDocument, preferences, this.resolvedFont ?? fallbackEpubFont(preferences.epub.fontFamily));
          applyEpubDocumentSpacing(iframe.contentDocument, preferences);
          this.applyDocumentInteractionMode(iframe.contentDocument, preferences);
        }
      } catch {
        // A detached view can disappear between query and access.
      }
    });
  }
  private applyDocumentInteractionMode(document: Document, preferences: ReaderPreferences) {
    const touchAction = preferences.epub.flow === 'paginated' ? 'pan-y' : 'auto';
    document.documentElement.style.touchAction = touchAction;
    if (document.body) document.body.style.touchAction = touchAction;
  }


  private releaseDocumentBridge(document: Document | undefined) {
    if (!document) return;
    this.activeDocuments.delete(document);
    this.documentHrefs.delete(document);
    this.tocCfiCandidates.delete(document);
    this.bridgedDocuments.get(document)?.abort();
    this.bridgedDocuments.delete(document);
    this.documentLayoutDisposers.get(document)?.();
    this.documentLayoutDisposers.delete(document);
  }

  private bindDocumentLayout(view: EpubView, generation: number) {
    const document = view.document;
    const contents = view.contents;
    if (!document || !contents || this.documentLayoutDisposers.has(document)) return;
    const restoreSpacing = () => {
      if (!this.isActive(generation) || !this.appliedPreferences) return;
      applyEpubDocumentSpacing(document, this.appliedPreferences);
    };
    contents.on('resize', restoreSpacing);
    contents.on('expand', restoreSpacing);
    this.documentLayoutDisposers.set(document, () => {
      contents.off?.('resize', restoreSpacing);
      contents.off?.('expand', restoreSpacing);
    });
  }

  private resolveCurrentTocHref(resourceHref: string | undefined, currentCfi: string | undefined) {
    const book = this.book;
    const compare = book?.epubcfi?.compare;
    // ReaderShell and epub.js may flatten a nested NCX/EPUB 3 TOC differently.
    // Resolve selection from the exact href list rendered by ReaderShell so an
    // authored contents resource cannot point at an invisible navigation item.
    const toc = this.navigationItems.length > 0 ? this.navigationItems : book?.navigation?.toc;
    if (!book || !resourceHref || !toc?.length) return resourceHref;
    const resourceKey = this.resourceHrefKey(resourceHref);
    if (currentCfi && compare) {
      const document = Array.from(this.activeDocuments).find((candidate) => (
        this.resourceHrefKey(this.documentHrefs.get(candidate)) === resourceKey
      ));
      const sectionHref = document ? this.documentHrefs.get(document) ?? resourceHref : resourceHref;
      const section = this.spineSectionForHref(sectionHref) ?? this.spineSectionForHref(resourceHref);
      if (document && section?.cfiFromElement) {
        let candidates = this.tocCfiCandidates.get(document);
        if (!candidates) {
          candidates = [];
          const visit = (items: EpubTocItem[]) => {
            items.forEach((item) => {
              const href = item.href?.trim();
              if (href && this.resourceHrefKey(href) === resourceKey) {
                const encodedFragment = href.split('#')[1];
                if (encodedFragment) {
                  let fragment = encodedFragment;
                  try { fragment = decodeURIComponent(encodedFragment); } catch { /* keep the authored id */ }
                  const element = document.getElementById(fragment);
                  if (element) {
                    try {
                      const cfi = section.cfiFromElement!(element);
                      if (cfi) candidates!.push({ href, cfi });
                    } catch {
                      // Broken TOC anchors fall back to the stable spine href.
                    }
                  }
                }
              }
              if (item.subitems?.length) visit(item.subitems);
            });
          };
          visit(toc);
          this.tocCfiCandidates.set(document, candidates);
        }
        const selected = selectEpubTocHref(resourceHref, currentCfi, candidates, compare.bind(book.epubcfi));
        if (selected !== resourceHref) return selected;
      }
    }

    const section = this.spineSectionForHref(resourceHref) ?? this.spineSectionForHref(resourceKey);
    return resolveEpubSpineIntervalHref(this.epubTocSpineTargets(toc), section?.index, resourceHref);
  }

  private epubTocSpineTargets(toc: EpubTocItem[]) {
    if (this.tocSpineTargets) return this.tocSpineTargets;
    const targets: Array<{ href: string; sectionIndex: number }> = [];
    const visit = (items: EpubTocItem[]) => {
      items.forEach((item) => {
        const href = item.href?.trim();
        const section = href ? this.spineSectionForHref(href) : undefined;
        if (href && Number.isFinite(section?.index)) targets.push({ href, sectionIndex: section!.index! });
        if (item.subitems?.length) visit(item.subitems);
      });
    };
    visit(toc);
    this.tocSpineTargets = targets;
    return targets;
  }

  private resourceHrefKey(href: string | undefined) {
    const value = href?.split('#')[0]?.split('?')[0] ?? '';
    try { return decodeURIComponent(value).replace(/^\.\//, '').toLowerCase(); } catch { return value.replace(/^\.\//, '').toLowerCase(); }
  }

  private spineSectionForHref(href: string | undefined) {
    const book = this.book;
    if (!book || !href) return undefined;
    const direct = book.spine.get(href) ?? book.spine.get(href.split('#')[0]);
    if (direct) return direct;
    const target = this.resourceHrefKey(href);
    if (!target) return undefined;
    const matches: EpubSection[] = [];
    const length = Math.max(0, Number(book.spine.length) || 0);
    for (let index = 0; index < length; index += 1) {
      const section = book.spine.get(index);
      const candidate = this.resourceHrefKey(section?.href);
      if (
        candidate
        && (candidate === target || candidate.endsWith(`/${target}`) || target.endsWith(`/${candidate}`))
      ) matches.push(section!);
    }
    return matches.length === 1 ? matches[0] : undefined;
  }

  private applyContainerMeasure(preferences: ReaderPreferences) {
    const maxWidth = Math.max(600, Math.min(1350, Math.round(preferences.epub.pageWidth)));
    this.container.dataset.readerFlow = preferences.epub.flow;
    this.container.style.width = '100%';
    this.container.style.maxWidth = `${maxWidth}px`;
    this.container.style.marginInline = 'auto';
  }

  private installResizeObserver(generation: number) {
    if (typeof ResizeObserver === 'undefined') return;
    this.resizeObserver?.disconnect();
    let pendingViewport = this.viewportSize;
    this.resizeObserver = new ResizeObserver((entries) => {
      const entry = entries.find((candidate) => candidate.target === this.container) ?? entries[0];
      if (!entry) return;
      pendingViewport = {
        width: Math.round(entry.contentRect.width),
        height: Math.round(entry.contentRect.height)
      };
      if (this.resizeFrame !== null) cancelAnimationFrame(this.resizeFrame);
      this.resizeFrame = requestAnimationFrame(() => {
        this.resizeFrame = null;
        if (!this.isActive(generation) || !this.rendition || !this.preferences) return;
        const { width, height } = pendingViewport;
        if (width <= 0 || height <= 0) return;
        if (width === this.viewportSize.width && height === this.viewportSize.height) return;
        this.viewportSize = { width, height };
        const signal = this.lifecycleController?.signal ?? new AbortController().signal;
        const scheduled = this.enqueueLayoutTransaction({
          preferences: this.preferences,
          operation: this.locationOperation ?? this.currentOperation(),
          requestSignal: signal,
          generation,
          viewport: { width, height }
        });
        void scheduled.promise.catch((reason) => {
          if (!isAbortError(reason) && !(reason instanceof StaleReaderOperationError)) {
            this.emit({
              type: 'error',
              error: { code: 'EPUB_LAYOUT_FAILED', message: errorMessage(reason, 'EPUB 重排失败'), recoverable: true }
            }, this.locationOperation ?? this.currentOperation());
          }
        });
      });
    });
    this.resizeObserver.observe(this.container);
  }

  private readContainerViewport() {
    const rect = this.container.getBoundingClientRect();
    return {
      width: Math.round(rect.width || this.container.clientWidth),
      height: Math.round(rect.height || this.container.clientHeight)
    };
  }

  private resumeLocationTrackingAfterPreference() {
    if (this.preferences?.epub.flow !== 'scrolled') return;
    if (this.locationOperation?.kind !== 'preferences' || !this.locationOperationAfterPreference) return;
    this.locationOperation = this.locationOperationAfterPreference;
    this.locationOperationAfterPreference = null;
  }

  private bridgeDocumentInput(document: Document, generation: number) {
    if (this.bridgedDocuments.has(document)) return;
    const Controller = document.defaultView?.AbortController ?? AbortController;
    const controller = new Controller();
    const signal = controller.signal;
    this.bridgedDocuments.set(document, controller);
    document.documentElement.setAttribute('data-shuku-input-bridge', 'v2');
    const listen = <K extends keyof DocumentEventMap>(
      type: K,
      listener: (event: DocumentEventMap[K]) => void,
      options?: AddEventListenerOptions
    ) => {
      document.addEventListener(type, listener as EventListener, options);
      signal.addEventListener('abort', () => {
        document.removeEventListener(type, listener as EventListener, options?.capture ?? false);
      }, { once: true });
    };

    const activity = () => {
      if (!this.isActive(generation)) return;
      this.emit({ type: 'activity' }, this.locationOperation ?? this.currentOperation());
    };
    const intent = (value: EpubInputIntent) => {
      activity();
      this.onInputIntent?.(value);
    };
    const forwardInputIntent = (input: ReaderInputIntent | null) => {
      if (!input) return;
      if (input === 'toggle-controls') intent({ type: 'toggle-controls' });
      else if (input === 'escape') intent({ type: 'escape' });
      else intent({ type: 'command', command: { type: input } });
    };
    const projectPointer = (clientX: number, clientY: number) => {
      const frame = document.defaultView?.frameElement;
      if (!frame) return { clientX, clientY };
      const frameBounds = frame.getBoundingClientRect();
      const frameViewportWidth = document.documentElement.clientWidth || document.defaultView?.innerWidth || frameBounds.width;
      const frameViewportHeight = document.documentElement.clientHeight || document.defaultView?.innerHeight || frameBounds.height;
      return projectReaderFramePointer(
        clientX,
        clientY,
        frameViewportWidth,
        frameViewportHeight,
        frameBounds
      ) ?? { clientX, clientY };
    };
    const pointerIntent = (clientX: number, clientY: number) => {
      const viewport = this.container.getBoundingClientRect();
      const projected = projectPointer(clientX, clientY);
      forwardInputIntent(readerPointerIntentInViewport(
        projected.clientX,
        projected.clientY,
        viewport,
        this.readingDirection
      ));
    };

    listen('keydown', (event) => {
      const input = readerKeyIntent(event, this.readingDirection);
      if (!input) return;
      if (input !== 'escape' && (isReaderControlTarget(event.target) || hasActiveTextSelection(document.getSelection()))) return;
      event.preventDefault();
      forwardInputIntent(input);
    });

    listen('click', (event) => {
      document.documentElement.setAttribute('data-shuku-last-input', 'click');
      if (Date.now() < this.suppressClickUntil) return;
      if (hasActiveTextSelection(document.getSelection())) return;
      const eventElement = event.target as Element | null;
      const anchor = eventElement && typeof eventElement.closest === 'function' ? eventElement.closest('a') : null;
      if (anchor) {
        const href = anchor.getAttribute('href')?.trim();
        if (!href) return;
        event.preventDefault();
        activity();
        const classified = classifyEpubHref(href);
        if (classified.kind === 'external') {
          this.emit({ type: 'external-link', href: classified.href }, this.locationOperation ?? this.currentOperation());
        } else if (classified.kind === 'internal') {
          this.onInputIntent?.({
            type: 'command',
            command: {
              type: 'go-to-href',
              href: resolveEpubDocumentHref(href, this.documentHrefs.get(document) ?? this.currentLocation?.href)
            }
          });
        }
        return;
      }
      if (isReaderControlTarget(event.target)) return;
      pointerIntent(event.clientX, event.clientY);
    });

    listen('wheel', () => {
      this.resumeLocationTrackingAfterPreference();
      activity();
    }, { passive: true });
    listen('pointerdown', (event) => {
      if (
        this.preferences?.epub.flow !== 'paginated'
        || event.isPrimary === false
        || event.pointerType === 'mouse'
        || isReaderControlTarget(event.target)
        || hasActiveTextSelection(document.getSelection())
      ) return;
      activity();
      const projected = projectPointer(event.clientX, event.clientY);
      this.pointerGesture = { pointerId: event.pointerId, x: projected.clientX, y: projected.clientY, time: Date.now() };
    }, { passive: false });
    listen('pointermove', (event) => {
      const gesture = this.pointerGesture;
      if (gesture && gesture.pointerId === event.pointerId) {
        const projected = projectPointer(event.clientX, event.clientY);
        const deltaX = projected.clientX - gesture.x;
        const deltaY = projected.clientY - gesture.y;
        if (Math.abs(deltaX) > 12 && Math.abs(deltaX) > Math.abs(deltaY) * 1.15) {
          event.preventDefault();
          event.stopPropagation();
          return;
        }
      }
      if (event.buttons && Math.abs(event.movementY) > Math.abs(event.movementX)) {
        this.resumeLocationTrackingAfterPreference();
      }
    }, { passive: false });
    listen('pointerup', (event) => {
      const gesture = this.pointerGesture;
      this.pointerGesture = null;
      if (!gesture || gesture.pointerId !== event.pointerId) return;
      const projected = projectPointer(event.clientX, event.clientY);
      const swipeIntent = readerSwipeIntent(
        projected.clientX - gesture.x,
        projected.clientY - gesture.y,
        Date.now() - gesture.time,
        this.readingDirection
      );
      if (swipeIntent) {
        event.preventDefault();
        event.stopPropagation();
        this.suppressClickUntil = Date.now() + 450;
        forwardInputIntent(swipeIntent);
      }
    }, { passive: false });
    listen('pointercancel', () => {
      this.pointerGesture = null;
    }, { passive: false });
    document.documentElement.setAttribute('data-shuku-input-bridge', 'ready');
  }

  private combineSignals(first: AbortSignal, second: AbortSignal) {
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

  private resolveSessionFont(family: ReaderPreferences['epub']['fontFamily'], requestSignal: AbortSignal) {
    let resolution = this.fontResolutions.get(family);
    if (!resolution) {
      const lifecycleSignal = this.lifecycleController?.signal ?? requestSignal;
      const ownerDocument = this.container.ownerDocument;
      const ownerWindow = ownerDocument.defaultView;
      resolution = resolveEpubFont(family, {
        signal: lifecycleSignal,
        fetch: this.fetcher,
        document: ownerDocument,
        FontFace: ownerWindow?.FontFace,
        createObjectURL: ownerWindow?.URL?.createObjectURL?.bind(ownerWindow.URL),
        revokeObjectURL: ownerWindow?.URL?.revokeObjectURL?.bind(ownerWindow.URL)
      }).catch((reason) => {
        if (isAbortError(reason)) this.fontResolutions.delete(family);
        throw reason;
      });
      this.fontResolutions.set(family, resolution);
    }
    return this.waitForRequest(resolution, requestSignal);
  }

  private releaseFontResolutions() {
    const resolutions = Array.from(this.fontResolutions.values());
    this.fontResolutions.clear();
    resolutions.forEach((resolution) => {
      void resolution.then((resolved) => resolved.embedded?.release?.()).catch(() => undefined);
    });
  }

  private waitForRequest<T>(request: Promise<T>, signal: AbortSignal) {
    if (signal.aborted) return Promise.reject<T>(new DOMException('The operation was aborted', 'AbortError'));
    return new Promise<T>((resolve, reject) => {
      const abort = () => reject(new DOMException('The operation was aborted', 'AbortError'));
      signal.addEventListener('abort', abort, { once: true });
      request.then(
        (value) => {
          signal.removeEventListener('abort', abort);
          resolve(value);
        },
        (reason) => {
          signal.removeEventListener('abort', abort);
          reject(reason);
        }
      );
    });
  }

  private cleanupEngine() {
    this.lifecycleController?.abort();
    this.lifecycleController = null;
    this.navigationGeneration += 1;
    this.preferenceGeneration += 1;
    this.layoutCoordinator.invalidateLayouts();
    this.layoutCoordinator = new EpubLayoutCoordinator();
    this.resizeObserver?.disconnect();
    this.resizeObserver = null;
    if (this.resizeFrame !== null) cancelAnimationFrame(this.resizeFrame);
    this.resizeFrame = null;
    this.viewportSize = { width: 0, height: 0 };
    this.locationsReady = false;
    this.locationOperationAfterPreference = null;
    this.suppressedLocationEmissions = 0;
    this.pointerGesture = null;
    this.suppressClickUntil = 0;
    this.layoutMutationDepth = 0;
    this.readerReady = false;
    this.finishViewTransition();
    this.container.querySelectorAll<HTMLIFrameElement>('iframe').forEach((iframe) => {
      try {
        this.releaseDocumentBridge(iframe.contentDocument ?? undefined);
      } catch {
        // The view may already be detached.
      }
    });
    try {
      this.rendition?.destroy();
    } catch {
      // epub.js can throw while a view is between attach and removal.
    }
    try {
      this.book?.destroy();
    } catch {
      // Resources are already detached; cleanup errors are not actionable.
    }
    this.rendition = null;
    this.book = null;
    this.currentLocation = null;
    this.preferences = null;
    this.appliedPreferences = null;
    this.resolvedFont = null;
    this.resolvedFontFamily = null;
    this.source = null;
    this.container.replaceChildren();
    this.container.style.removeProperty('width');
    this.container.style.removeProperty('max-width');
    this.container.style.removeProperty('margin-inline');
    if (this.container.dataset.shukuEpubTransitionPosition === 'true') {
      this.container.style.removeProperty('position');
      delete this.container.dataset.shukuEpubTransitionPosition;
    }
    delete this.container.dataset.readerFlow;
    this.bridgedDocuments = new WeakMap<Document, AbortController>();
    this.documentLayoutDisposers = new WeakMap<Document, () => void>();
    this.activeDocuments = new Set<Document>();
    this.documentHrefs = new WeakMap<Document, string>();
    this.tocCfiCandidates = new WeakMap<Document, Array<{ href: string; cfi: string }>>();
    this.tocSpineTargets = null;
    this.renditionAttachments = new WeakMap<Rendition, Promise<void>>();
    delete this.container.dataset.readerEngine;
  }
}

export function createEpubAdapter(options: EpubAdapterOptions) {
  return new EpubReaderAdapter(options);
}
