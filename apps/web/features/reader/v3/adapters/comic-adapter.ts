import type {
  ComicLocation,
  ReaderAdapter,
  ReaderAdapterOpenContext,
  ReaderAdapterOperationContext,
  ReaderCapabilities,
  ReaderCommand,
  ReaderCommandAck,
  ReaderPreferences
} from '@shuku/reader-core';
import { withBasePath } from '../../../../lib/base-path';
import { readerThemeSurfaces } from '../../reader-theme';
import { isReaderControlTarget } from '../input-router';
import { PagedTrackController } from '../paged-track/paged-track-controller';
import type { PageStep, PagedTrackCommitRequest, PagedTrackPointerInput } from '../paged-track/paged-track-types';
import { ReaderAdapterBase, StaleReaderOperationError, errorMessage, isAbortError } from './adapter-base';
import { ComicSpreadTrackDriver, type ComicTrackSpread, type ComicTrackView } from './comic-track';
import { ComicContinuousController } from './comic-continuous';
import type { ReaderAdapterInputHandler, ReaderInteractiveAdapter, ReaderInteractionPolicy } from './reader-interaction';
import {
  comicCacheWindow,
  comicAdjacentSpreadPage,
  comicLastSpreadPage,
  comicNormalizePage,
  comicOrderedPages,
  comicPageForProgress,
  comicPagePercent,
  comicPreloadWindow,
  comicSpreadPages,
  comicVisualPages,
  type ComicPairingPolicy,
  type ComicPageMeta
} from './comic-model';

export type ComicPageView = ComicPageMeta & {
  url?: string;
  loading: boolean;
  error?: string;
};

export type ComicViewModel = {
  status: 'idle' | 'loading' | 'ready' | 'error';
  currentPage: number;
  pageCount: number;
  visiblePages: ComicPageView[];
  direction: 'ltr' | 'rtl';
  mode: 'single' | 'double';
  imageFit: ReaderPreferences['comic']['imageFit'];
  zoom: number;
  error?: string;
};

type ComicPageIndexPayload = {
  ok?: boolean;
  data?: { pageCount?: number; pages?: ComicPageMeta[] };
  pageCount?: number;
  pages?: ComicPageMeta[];
  error?: { message?: string };
};

type CachedComicPage = {
  url?: string;
  objectUrl?: string;
  controller?: AbortController;
  promise?: Promise<string>;
  variant?: ReaderPreferences['comic']['imageVariant'];
  error?: string;
};

export type ComicAdapterOptions = {
  container: HTMLElement;
  onInputIntent?: ReaderAdapterInputHandler;
  fetch?: typeof globalThis.fetch;
  decodeImage?: (url: string, signal: AbortSignal) => Promise<void>;
  pageIndexUrl?: (context: ReaderAdapterOpenContext) => string;
  pageUrl?: (context: ReaderAdapterOpenContext, pageIndex: number, preferences: ReaderPreferences, retry: number) => string;
  initialPages?: ComicPageMeta[];
  onViewModel?: (model: ComicViewModel) => void;
  onEndOfVolume?: () => void;
};

function clampPage(page: number, pageCount: number) {
  return Math.max(1, Math.min(Math.max(1, pageCount), Math.round(page || 1)));
}

function defaultPageIndexUrl(context: ReaderAdapterOpenContext) {
  return withBasePath(`/api/volumes/${encodeURIComponent(context.source.volumeId)}/pages`);
}

function defaultPageUrl(context: ReaderAdapterOpenContext, pageIndex: number, preferences: ReaderPreferences, retry: number) {
  const parameters = new URLSearchParams({ imageVariant: preferences.comic.imageVariant });
  if (retry > 0) parameters.set('retry', String(retry));
  return withBasePath(`/api/volumes/${encodeURIComponent(context.source.volumeId)}/pages/${pageIndex}?${parameters}`);
}

function waitForSignal<T>(request: Promise<T>, signal: AbortSignal) {
  if (signal.aborted) return Promise.reject(new DOMException('The operation was aborted', 'AbortError'));
  return new Promise<T>((resolve, reject) => {
    const abort = () => reject(new DOMException('The operation was aborted', 'AbortError'));
    signal.addEventListener('abort', abort, { once: true });
    request.then(resolve, reject).finally(() => signal.removeEventListener('abort', abort));
  });
}

async function decodeComicImage(document: Document, url: string, signal: AbortSignal) {
  const ImageConstructor = document.defaultView?.Image ?? globalThis.Image;
  if (typeof ImageConstructor !== 'function') return;
  const image = new ImageConstructor();
  image.decoding = 'async';
  let resolveLoad!: () => void;
  let rejectLoad!: (reason: unknown) => void;
  const loaded = new Promise<void>((resolve, reject) => {
    resolveLoad = resolve;
    rejectLoad = reject;
  });
  const handleLoad = () => resolveLoad();
  const handleError = () => rejectLoad(new Error('comic-image-decode-failed'));
  image.addEventListener('load', handleLoad, { once: true });
  image.addEventListener('error', handleError, { once: true });
  image.src = url;
  try {
    if (typeof image.decode === 'function') {
      try {
        await waitForSignal(image.decode(), signal);
      } catch (reason) {
        if (isAbortError(reason)) throw reason;
        await waitForSignal(loaded, signal);
      }
    } else {
      await waitForSignal(loaded, signal);
    }
  } finally {
    image.removeEventListener('load', handleLoad);
    image.removeEventListener('error', handleError);
  }
}

export class ComicReaderAdapter extends ReaderAdapterBase implements ReaderAdapter, ReaderInteractiveAdapter {
  private readonly container: HTMLElement;
  private readonly fetcher: typeof globalThis.fetch;
  private readonly decodeImage: NonNullable<ComicAdapterOptions['decodeImage']>;
  private readonly pageIndexUrl: NonNullable<ComicAdapterOptions['pageIndexUrl']>;
  private readonly pageUrl: NonNullable<ComicAdapterOptions['pageUrl']>;
  private readonly initialPages?: ComicPageMeta[];
  private readonly onEndOfVolume?: ComicAdapterOptions['onEndOfVolume'];
  private readonly onInputIntent?: ComicAdapterOptions['onInputIntent'];
  private readonly track: ComicSpreadTrackDriver;
  private readonly continuous: ComicContinuousController;
  private readonly trackController: PagedTrackController;
  private readonly viewListeners = new Set<(model: ComicViewModel) => void>();
  private lifecycleController: AbortController | null = null;
  private openContext: ReaderAdapterOpenContext | null = null;
  private preferences: ReaderPreferences | null = null;
  private pageMeta = new Map<number, ComicPageMeta>();
  private pages: number[] = [];
  private currentPage = 1;
  private cache = new Map<number, CachedComicPage>();
  private retryCounts = new Map<number, number>();
  private status: ComicViewModel['status'] = 'idle';
  private error: string | undefined;
  private prepareError: string | undefined;
  private zoom = 1;
  private suppressClickUntil = 0;
  private resizeObserver: ResizeObserver | null = null;
  private viewportWidth = 0;
  private readonly handlePointerDown = (event: PointerEvent) => {
    if (
      !this.onInputIntent
      || this.zoom > 1
      || this.status !== 'ready'
      || event.button !== 0
      || !event.isPrimary
      || isReaderControlTarget(event.target)
    ) return;
    const result = this.trackController.pointerDown(this.pointerInput(event));
    if (!result.handled) return;
    try {
      this.track.getViewportElement().setPointerCapture(event.pointerId);
    } catch {
      // Pointer capture is best-effort on older WebKit.
    }
  };
  private readonly handlePointerMove = (event: PointerEvent) => {
    const result = this.trackController.pointerMove(this.pointerInput(event));
    if (!result.claimed) return;
    if (result.preventDefault && event.cancelable) event.preventDefault();
    event.stopPropagation();
  };
  private readonly handlePointerUp = (event: PointerEvent) => {
    const beforeRelease = this.trackController.snapshot();
    const released = this.trackController.pointerUp(this.pointerInput(event));
    const claimed = beforeRelease.claimed
      || (beforeRelease.phase === 'priming' && this.trackController.snapshot().phase !== 'idle');
    if (claimed) {
      this.suppressClickUntil = Date.now() + 500;
      if (event.cancelable) event.preventDefault();
      event.stopPropagation();
    }
    void released.finally(() => {
      this.releasePointerCapture(event.pointerId);
    });
  };
  private readonly handlePointerCancel = (event: PointerEvent) => {
    const claimed = this.trackController.snapshot().claimed;
    if (claimed) {
      this.suppressClickUntil = Date.now() + 500;
      event.stopPropagation();
    }
    void this.trackController.pointerCancel(event.pointerId).finally(() => {
      this.releasePointerCapture(event.pointerId);
    });
  };
  private readonly handleLostPointerCapture = (event: PointerEvent) => {
    void this.trackController.pointerCancel(event.pointerId);
  };
  private readonly suppressCompatibilityClick = (event: MouseEvent) => {
    if (Date.now() >= this.suppressClickUntil) return;
    event.preventDefault();
    event.stopPropagation();
  };

  constructor(options: ComicAdapterOptions) {
    super();
    this.container = options.container;
    this.fetcher = options.fetch ?? globalThis.fetch.bind(globalThis);
    this.pageIndexUrl = options.pageIndexUrl ?? defaultPageIndexUrl;
    this.decodeImage = options.decodeImage ?? ((url, signal) => decodeComicImage(this.container.ownerDocument, url, signal));
    this.pageUrl = options.pageUrl ?? defaultPageUrl;
    this.initialPages = options.initialPages;
    this.onEndOfVolume = options.onEndOfVolume;
    this.onInputIntent = options.onInputIntent;
    this.track = new ComicSpreadTrackDriver(this.container, {
      getView: () => this.trackView(),
      prepare: (step, signal) => this.prepareTrackSpread(step, signal),
      promote: (step, signal) => this.promoteTrackSpread(step, signal)
    });
    this.trackController = new PagedTrackController(this.track, {
      requestCommit: (request) => this.requestTrackCommit(request),
      boundaryCommitSteps: [1]
    });
    this.continuous = new ComicContinuousController(this.container, (page) => {
      if (this.preferences?.comic.flow !== 'vertical' || page === this.currentPage) return;
      this.currentPage = clampPage(page, this.pages.length);
      this.emitLocation();
      void this.refreshVisiblePages(this.currentGeneration(), this.lifecycleController?.signal ?? AbortSignal.abort()).catch(() => undefined);
    }, (page) => {
      const signal = this.lifecycleController?.signal;
      if (!signal || signal.aborted) return;
      this.retryCounts.set(page, (this.retryCounts.get(page) ?? 0) + 1);
      this.releasePage(page);
      void this.loadPage(page, this.currentGeneration(), signal, false)
        .then(() => this.emitView())
        .catch(() => this.emitView());
    });
    const viewport = this.track.getViewportElement();
    viewport.addEventListener('pointerdown', this.handlePointerDown);
    viewport.addEventListener('pointermove', this.handlePointerMove, { passive: false });
    viewport.addEventListener('pointerup', this.handlePointerUp, { passive: false });
    viewport.addEventListener('pointercancel', this.handlePointerCancel);
    viewport.addEventListener('lostpointercapture', this.handleLostPointerCapture);
    viewport.addEventListener('click', this.suppressCompatibilityClick, true);
    if (options.onViewModel) this.viewListeners.add(options.onViewModel);
    const ResizeObserverConstructor = this.container.ownerDocument.defaultView?.ResizeObserver ?? globalThis.ResizeObserver;
    if (typeof ResizeObserverConstructor === 'function') {
      this.viewportWidth = viewport.clientWidth || this.container.clientWidth;
      this.resizeObserver = new ResizeObserverConstructor(() => this.handleViewportResize());
      this.resizeObserver.observe(viewport);
      this.resizeObserver.observe(this.container);
    }
  }

  subscribeView(listener: (model: ComicViewModel) => void) {
    this.viewListeners.add(listener);
    listener(this.viewModel());
    return () => this.viewListeners.delete(listener);
  }

  getViewModel() {
    return this.viewModel();
  }

  getInteractionPolicy(): ReaderInteractionPolicy {
    if (this.preferences?.comic.flow === 'vertical') return { horizontalPaging: 'none' };
    if (this.zoom > 1) return { horizontalPaging: 'none' };
    return { horizontalPaging: this.onInputIntent ? 'adapter-interactive' : 'shell-discrete' };
  }

  getCapabilities(): ReaderCapabilities {
    const mode = this.comicMode();
    const pairing = this.pairingPolicy();
    const previous = comicAdjacentSpreadPage(this.pages, this.currentPage, mode, -1, pairing);
    const next = comicAdjacentSpreadPage(this.pages, this.currentPage, mode, 1, pairing);
    return {
      canGoNext: next !== this.currentPage,
      canGoPrevious: previous !== this.currentPage,
      canJumpToProgress: true,
      canJumpToHref: false,
      canJumpToIndex: true,
      canZoom: true,
      canSelectText: false,
      supportsPagination: true,
      supportsScrolling: this.preferences?.comic.flow === 'vertical',
      supportsSpreads: this.preferences?.comic.flow !== 'vertical',
      readingDirection: this.preferences?.comic.direction ?? 'ltr'
    };
  }

  async open(context: ReaderAdapterOpenContext) {
    this.cleanupEngine();
    const generation = this.beginSession(context.sessionId, context.operation);
    this.lifecycleController = new AbortController();
    const combinedSignal = this.combineSignals(context.signal, this.lifecycleController.signal);
    const { signal } = combinedSignal;
    this.openContext = context;
    this.preferences = context.preferences;
    this.zoom = context.preferences.comic.zoom;
    if (this.zoom > 1) this.trackController.suspend();
    else this.trackController.interrupt();
    this.status = 'loading';
    this.error = undefined;
    this.container.dataset.readerEngine = 'comic-v3';
    this.container.style.background = readerThemeSurfaces[context.preferences.appearance.theme].background;
    this.emitView();
    this.emit({ type: 'phase-changed', phase: 'loading-content' }, context.operation);

    try {
      let pages = this.initialPages;
      let pageCount = context.source.totalPages ?? pages?.length ?? 0;
      if (!pages?.length && pageCount <= 0) {
        const response = await this.fetcher(this.pageIndexUrl(context), { signal });
        if (!response.ok) throw new Error(`漫画页面索引加载失败 (${response.status})`);
        const payload = await response.json() as ComicPageIndexPayload;
        if (payload.ok === false) throw new Error(payload.error?.message ?? '漫画页面索引加载失败');
        const data = payload.data ?? payload;
        pages = data.pages;
        pageCount = data.pageCount ?? pages?.length ?? 0;
      }
      this.assertActive(generation, signal);
      if (pages?.length) {
        pages.forEach((page) => this.pageMeta.set(page.pageIndex, page));
        pageCount = Math.max(pageCount, ...pages.map((page) => page.pageIndex));
      }
      if (pageCount <= 0) throw new Error('漫画卷没有可读取页面');
      this.pages = comicOrderedPages(pageCount);
      const initialPage = context.initialLocation?.kind === 'comic' ? context.initialLocation.pageIndex : 1;
      this.currentPage = comicNormalizePage(this.pages, clampPage(initialPage, pageCount), this.comicMode(context.preferences), this.pairingPolicy(context.preferences));
      await this.refreshVisiblePages(generation, signal);
      this.assertActive(generation, signal);
      this.status = 'ready';
      this.track.recenter();
      this.emitLocation(context.operation);
      this.emitView();
      this.emit({ type: 'ready', capabilities: this.getCapabilities(), location: this.location() }, context.operation);
    } catch (reason) {
      if (isAbortError(reason) || reason instanceof StaleReaderOperationError) return;
      this.status = 'error';
      this.error = errorMessage(reason, '漫画加载失败');
      this.emitView();
      this.emit({
        type: 'error',
        error: { code: 'COMIC_OPEN_FAILED', message: this.error, recoverable: true }
      }, context.operation);
      throw reason;
    } finally {
      combinedSignal.cleanup();
    }
  }

  async execute(command: ReaderCommand, context: ReaderAdapterOperationContext): Promise<ReaderCommandAck> {
    try {
      this.beginOperation(context);
    } catch {
      return this.failOperation(context, 'stale-session');
    }
    if (command.type === 'retry' && (!this.openContext || !this.pages.length)) {
      const previous = this.openContext;
      const preferences = this.preferences;
      if (!previous || !preferences) return this.failOperation(context, 'retry-context-unavailable');
      try {
        await this.open({
          ...previous,
          sessionId: context.operation.sessionId,
          operation: context.operation,
          signal: context.signal,
          initialLocation: this.location(),
          preferences
        });
        return context.signal.aborted
          ? this.failOperation(context, 'operation-cancelled')
          : this.ack(context.operation, true, { location: this.location() });
      } catch (reason) {
        return this.failOperation(context, errorMessage(reason, 'retry-failed'));
      }
    }
    if (!this.openContext || !this.preferences || !this.pages.length) return this.failOperation(context, 'not-ready');
    if (command.type === 'go-to-href' || command.type === 'set-fit') return this.failOperation(context, 'unsupported-command');
    if (command.type === 'cancel') {
      this.trackController.interrupt();
      this.cache.forEach((entry) => entry.controller?.abort());
      return this.ack(context.operation, true, { location: this.location() });
    }
    if (command.type === 'set-zoom') {
      this.zoom = Math.max(0.6, Math.min(2.4, command.zoom));
      if (this.zoom > 1) this.trackController.suspend();
      else this.trackController.interrupt();
      this.track.render();
      this.track.recenter();
      this.emitView();
      return this.ack(context.operation, true, { location: this.location() });
    }

    if (command.type === 'next' || command.type === 'previous') {
      if (this.preferences.comic.flow === 'vertical') {
        return this.executeContinuousAdjacentStep(command.type === 'next' ? 1 : -1, context);
      }
      return this.executeAdjacentStep(command.type === 'next' ? 1 : -1, context);
    }

    this.trackController.interrupt();
    let nextPage = this.currentPage;
    if (command.type === 'first') nextPage = this.pages[0];
    else if (command.type === 'last') nextPage = comicLastSpreadPage(this.pages, this.comicMode(), this.pairingPolicy());
    else if (command.type === 'go-to-progress') nextPage = comicNormalizePage(this.pages, comicPageForProgress(command.progression, this.pages), this.comicMode(), this.pairingPolicy());
    else if (command.type === 'go-to-index') nextPage = comicNormalizePage(this.pages, clampPage(command.index, this.pages.length), this.comicMode(), this.pairingPolicy());
    else if (command.type === 'go-to-location') {
      if (command.location.kind !== 'comic') return this.failOperation(context, 'location-kind-mismatch');
      if (command.location.volumeId !== this.openContext.source.volumeId) {
        return this.failOperation(context, 'volume-switch-requires-new-session');
      }
      nextPage = comicNormalizePage(this.pages, clampPage(command.location.pageIndex, this.pages.length), this.comicMode(), this.pairingPolicy());
    } else if (command.type === 'retry') {
      comicSpreadPages(this.pages, this.currentPage, this.comicMode(), this.pairingPolicy()).forEach((page) => {
        this.retryCounts.set(page, (this.retryCounts.get(page) ?? 0) + 1);
        this.releasePage(page);
      });
    }

    if (!nextPage || nextPage === this.currentPage && command.type !== 'retry') {
      return this.failOperation(context, 'no-op');
    }

    this.currentPage = nextPage;
    this.emit({ type: 'activity' }, context.operation);
    this.status = 'loading';
    this.emitView();
    try {
      await this.refreshVisiblePages(this.currentGeneration(), context.signal);
      if (this.preferences.comic.flow === 'vertical') this.continuous.scrollToPage(this.currentPage);
      else this.track.recenter(true);
      this.status = 'ready';
      this.emitLocation(context.operation);
      this.emitView();
      return this.ack(context.operation, true, { location: this.location() });
    } catch (reason) {
      if (isAbortError(reason) || reason instanceof StaleReaderOperationError) return this.failOperation(context, 'operation-cancelled');
      this.status = 'error';
      this.error = errorMessage(reason, '漫画页面加载失败');
      this.emitView();
      this.emit({
        type: 'error',
        error: { code: 'COMIC_PAGE_LOAD_FAILED', message: this.error, recoverable: true }
      }, context.operation);
      return this.failOperation(context, this.error);
    }
  }

  async applyPreferences(preferences: ReaderPreferences, context: ReaderAdapterOperationContext): Promise<ReaderCommandAck> {
    try {
      this.beginOperation(context);
    } catch {
      return this.failOperation(context, 'stale-session');
    }
    this.trackController.interrupt({ suspended: preferences.comic.zoom > 1 });
    const variantChanged = preferences.comic.imageVariant !== this.preferences?.comic.imageVariant;
    const modeChanged = preferences.comic.mode !== this.preferences?.comic.mode
      || preferences.comic.flow !== this.preferences?.comic.flow
      || preferences.comic.coverSingle !== this.preferences?.comic.coverSingle;
    const pageBeforeModeChange = this.currentPage;
    this.preferences = preferences;
    if (modeChanged) this.currentPage = comicNormalizePage(this.pages, this.currentPage, this.comicMode(preferences), this.pairingPolicy(preferences));
    this.zoom = preferences.comic.zoom;
    this.container.style.background = readerThemeSurfaces[preferences.appearance.theme].background;
    if (variantChanged) this.releaseAllPages();
    if (this.openContext && this.pages.length) {
      await this.refreshVisiblePages(this.currentGeneration(), context.signal);
      if (preferences.comic.flow === 'vertical') this.continuous.scrollToPage(this.currentPage);
      else this.track.recenter();
    }
    if (modeChanged || this.currentPage !== pageBeforeModeChange) this.emitLocation(context.operation);
    else this.emit({ type: 'capabilities-changed', capabilities: this.getCapabilities() }, context.operation);
    this.emitView();
    return this.ack(context.operation, true, { location: this.location() });
  }

  dispose() {
    if (!this.markDisposed()) return;
    this.resizeObserver?.disconnect();
    this.resizeObserver = null;
    this.cleanupEngine();
    const viewport = this.track.getViewportElement();
    viewport.removeEventListener('pointerdown', this.handlePointerDown);
    viewport.removeEventListener('pointermove', this.handlePointerMove);
    viewport.removeEventListener('pointerup', this.handlePointerUp);
    viewport.removeEventListener('pointercancel', this.handlePointerCancel);
    viewport.removeEventListener('lostpointercapture', this.handleLostPointerCapture);
    viewport.removeEventListener('click', this.suppressCompatibilityClick, true);
    this.trackController.dispose();
    this.track.destroy();
    this.continuous.destroy();
    this.viewListeners.clear();
  }

  private handleViewportResize() {
    const viewport = this.track.getViewportElement();
    const width = viewport.clientWidth || this.container.clientWidth;
    if (!Number.isFinite(width) || width <= 0 || Math.abs(width - this.viewportWidth) < 0.5) return;
    this.viewportWidth = width;
    this.trackController.interrupt({ suspended: this.zoom > 1 });
    if (this.preferences?.comic.flow === 'vertical') this.renderContinuous();
    else {
      this.track.render();
      this.track.recenter();
    }
  }

  private async executeAdjacentStep(step: PageStep, context: ReaderAdapterOperationContext): Promise<ReaderCommandAck> {
    const target = comicAdjacentSpreadPage(this.pages, this.currentPage, this.comicMode(), step, this.pairingPolicy());
    if (target === this.currentPage) {
      if (step === 1) this.onEndOfVolume?.();
      return this.failOperation(context, step === 1 ? 'end-of-volume' : 'start-of-volume');
    }

    this.emit({ type: 'activity' }, context.operation);
    this.status = 'loading';
    this.prepareError = undefined;
    this.emitView();
    try {
      const pending = this.trackController.snapshot();
      let moved = false;
      if (pending.pendingStep !== null) {
        if (pending.pendingStep !== step) {
          await this.trackController.rejectPending(pending.pendingGestureId ?? undefined, { signal: context.signal });
          this.status = 'ready';
          this.emitView();
          return this.failOperation(context, 'pending-gesture-direction-mismatch');
        }
        moved = await this.trackController.acceptPending(step, {
          gestureId: pending.pendingGestureId ?? undefined,
          signal: context.signal
        });
      } else {
        moved = await this.trackController.step(step, { signal: context.signal });
      }
      if (!moved) {
        this.status = 'ready';
        this.emitView();
        if (context.signal.aborted) return this.failOperation(context, 'operation-cancelled');
        if (this.prepareError) {
          this.emit({
            type: 'error',
            error: { code: 'COMIC_PAGE_LOAD_FAILED', message: this.prepareError, recoverable: true }
          }, context.operation);
        }
        return this.failOperation(context, this.prepareError ?? 'page-not-ready');
      }

      this.status = 'ready';
      this.emitLocation(context.operation);
      this.emitView();
      this.preloadTrackWindow();
      return this.ack(context.operation, true, { location: this.location() });
    } catch (reason) {
      if (isAbortError(reason) || reason instanceof StaleReaderOperationError) {
        this.status = 'ready';
        this.emitView();
        return this.failOperation(context, 'operation-cancelled');
      }
      this.status = 'ready';
      this.prepareError = errorMessage(reason, '漫画页面加载失败');
      this.emitView();
      this.emit({
        type: 'error',
        error: { code: 'COMIC_PAGE_LOAD_FAILED', message: this.prepareError, recoverable: true }
      }, context.operation);
      return this.failOperation(context, this.prepareError);
    }
  }

  private async executeContinuousAdjacentStep(
    step: PageStep,
    context: ReaderAdapterOperationContext
  ): Promise<ReaderCommandAck> {
    const target = comicAdjacentSpreadPage(this.pages, this.currentPage, 'single', step, this.pairingPolicy());
    if (target === this.currentPage) {
      return this.failOperation(context, step === 1 ? 'end-of-volume' : 'start-of-volume');
    }
    this.emit({ type: 'activity' }, context.operation);
    this.status = 'loading';
    this.currentPage = target;
    this.emitView();
    try {
      await this.refreshVisiblePages(this.currentGeneration(), context.signal);
      this.continuous.scrollToPage(target);
      this.status = 'ready';
      this.emitLocation(context.operation);
      this.emitView();
      return this.ack(context.operation, true, { location: this.location() });
    } catch (reason) {
      if (isAbortError(reason) || reason instanceof StaleReaderOperationError) {
        return this.failOperation(context, 'operation-cancelled');
      }
      this.status = 'error';
      this.error = errorMessage(reason, '漫画页面加载失败');
      this.emitView();
      return this.failOperation(context, this.error);
    }
  }

  private async refreshVisiblePages(generation: number, signal: AbortSignal) {
    this.assertActive(generation, signal);
    const preferences = this.preferences;
    if (!preferences) return;
    const vertical = preferences.comic.flow === 'vertical';
    const visible = vertical
      ? this.pages.filter((page) => Math.abs(page - this.currentPage) <= 1)
      : comicSpreadPages(this.pages, this.currentPage, this.comicMode(preferences), this.pairingPolicy(preferences));
    const retained = new Set(vertical
      ? this.pages.filter((page) => Math.abs(page - this.currentPage) <= 2)
      : comicCacheWindow(this.pages, this.currentPage, this.comicMode(preferences), this.pairingPolicy(preferences)));
    this.cache.forEach((_entry, page) => {
      if (!retained.has(page)) this.releasePage(page);
    });
    if (vertical) {
      await Promise.all(visible.map((page) => this.loadPage(page, generation, signal, true).catch((reason: unknown) => {
        if (isAbortError(reason) || reason instanceof StaleReaderOperationError) throw reason;
        // The cache retains the page-scoped error so the stable slot can show
        // an inline retry without collapsing or replacing the reading stream.
        return undefined;
      })));
    } else {
      await Promise.all(visible.map((page) => this.loadPage(page, generation, signal, true)));
    }
    this.emitView();
    const preload = vertical
      ? this.pages.filter((page) => Math.abs(page - this.currentPage) === 2)
      : comicPreloadWindow(this.pages, this.currentPage, this.comicMode(preferences), this.pairingPolicy(preferences));
    for (const page of preload) {
      if (visible.includes(page)) continue;
      void this.loadPage(page, generation, signal, false).then(() => {
        if (this.isActive(generation, signal)) this.emitView();
      }).catch(() => undefined);
    }
  }

  private async loadPage(page: number, generation: number, parentSignal: AbortSignal, visible: boolean) {
    const context = this.openContext;
    const preferences = this.preferences;
    const lifecycleSignal = this.lifecycleController?.signal;
    if (!context || !preferences || !lifecycleSignal) throw new StaleReaderOperationError();
    const variant = preferences.comic.imageVariant;
    const cached = this.cache.get(page);
    if (cached?.url && cached.variant === variant) return cached.url;
    if (cached?.promise && cached.variant === variant) {
      try {
        const url = await this.waitForPageRequest(cached.promise, parentSignal);
        this.assertActive(generation, parentSignal);
        return url;
      } catch (reason) {
        if (visible && !isAbortError(reason) && !(reason instanceof StaleReaderOperationError)) {
          throw new Error(errorMessage(reason, `第 ${page} 页加载失败`));
        }
        throw reason;
      }
    }
    if (cached) this.releasePage(page);
    const controller = new AbortController();
    const combinedSignal = this.combineSignals(lifecycleSignal, controller.signal);
    const { signal } = combinedSignal;
    const ownedEntry: CachedComicPage = { controller, variant };
    this.cache.set(page, ownedEntry);
    this.emitView();
    const request = (async () => {
      try {
        const response = await this.fetcher(this.pageUrl(context, page, preferences, this.retryCounts.get(page) ?? 0), { signal });
        if (!response.ok) throw new Error(`第 ${page} 页加载失败 (${response.status})`);
        const blob = await response.blob();
        this.assertActive(generation, signal);
        const url = URL.createObjectURL(blob);
        if (!this.isActive(generation, signal) || this.cache.get(page) !== ownedEntry) {
          URL.revokeObjectURL(url);
          throw new StaleReaderOperationError();
        }
        ownedEntry.objectUrl = url;
        await this.decodeImage(url, signal);
        this.assertActive(generation, signal);
        if (this.cache.get(page) !== ownedEntry) throw new StaleReaderOperationError();
        ownedEntry.objectUrl = undefined;
        this.cache.set(page, { url, variant });
        return url;
      } catch (reason) {
        this.revokeEntryObjectUrl(ownedEntry);
        if (isAbortError(reason) || reason instanceof StaleReaderOperationError) {
          if (this.cache.get(page) === ownedEntry) this.cache.delete(page);
          throw reason;
        }
        const message = errorMessage(reason, `第 ${page} 页加载失败`);
        if (this.cache.get(page) === ownedEntry) this.cache.set(page, { error: message, variant });
        throw new Error(message);
      } finally {
        combinedSignal.cleanup();
      }
    })();
    ownedEntry.promise = request;
    try {
      const url = await this.waitForPageRequest(request, parentSignal);
      this.assertActive(generation, parentSignal);
      return url;
    } catch (reason) {
      if (visible && !isAbortError(reason) && !(reason instanceof StaleReaderOperationError)) {
        throw new Error(errorMessage(reason, `第 ${page} 页加载失败`));
      }
      throw reason;
    }
  }

  private waitForPageRequest(request: Promise<string>, signal: AbortSignal) {
    if (signal.aborted) return Promise.reject(new DOMException('The operation was aborted', 'AbortError'));
    return new Promise<string>((resolve, reject) => {
      const abort = () => reject(new DOMException('The operation was aborted', 'AbortError'));
      signal.addEventListener('abort', abort, { once: true });
      request.then(resolve, reject).finally(() => signal.removeEventListener('abort', abort));
    });
  }

  private emitLocation(operation = this.currentOperation()) {
    this.emit({
      type: 'location-changed',
      location: this.location(),
      percent: comicPagePercent(this.currentPage, this.pages, this.comicMode(), this.pairingPolicy())
    }, operation);
    this.emit({ type: 'capabilities-changed', capabilities: this.getCapabilities() }, operation);
  }

  private location(): ComicLocation {
    const volumeId = this.openContext?.source.volumeId;
    if (!volumeId) throw new Error('comic-volume-id-missing');
    return {
      kind: 'comic',
      volumeId,
      pageIndex: this.currentPage
    };
  }

  private viewModel(): ComicViewModel {
    const preferences = this.preferences;
    const visiblePages = preferences
      ? comicVisualPages(this.pages, this.currentPage, this.comicMode(preferences), preferences.comic.direction, this.pairingPolicy(preferences)).map((page) => {
          const cached = this.cache.get(page);
          return {
            pageIndex: page,
            ...this.pageMeta.get(page),
            url: cached?.url,
            loading: Boolean(cached?.controller),
            error: cached?.error
          };
        })
      : [];
    return {
      status: this.status,
      currentPage: this.currentPage,
      pageCount: this.pages.length,
      visiblePages,
      direction: preferences?.comic.direction ?? 'ltr',
      mode: this.comicMode(preferences),
      imageFit: preferences?.comic.imageFit ?? 'width',
      zoom: this.zoom,
      error: this.error
    };
  }

  private emitView() {
    const model = this.viewModel();
    const vertical = this.preferences?.comic.flow === 'vertical';
    this.track.getViewportElement().style.display = vertical ? 'none' : 'block';
    this.continuous.setEnabled(vertical);
    if (vertical) this.renderContinuous();
    else this.track.render();
    this.viewListeners.forEach((listener) => listener(model));
  }

  private trackView(): ComicTrackView {
    const preferences = this.preferences;
    const current = this.pages.length ? this.currentPage : null;
    const mode = this.comicMode(preferences);
    const pairing = this.pairingPolicy(preferences);
    const previous = current === null ? null : comicAdjacentSpreadPage(this.pages, current, mode, -1, pairing);
    const next = current === null ? null : comicAdjacentSpreadPage(this.pages, current, mode, 1, pairing);
    return {
      previous: previous === null || previous === current ? null : this.trackSpread(previous),
      current: current === null ? null : this.trackSpread(current),
      next: next === null || next === current ? null : this.trackSpread(next),
      direction: preferences?.comic.direction ?? 'ltr',
      mode,
      imageFit: preferences?.comic.imageFit ?? 'width',
      zoom: this.zoom,
      pageGap: preferences?.comic.pageGap ?? 0,
      reducedMotion: preferences?.comic.pageTurnAnimation === 'off'
        || (typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches),
      error: this.error
    };
  }

  private trackSpread(anchor: number): ComicTrackSpread {
    const preferences = this.preferences;
    const mode = this.comicMode(preferences);
    const direction = preferences?.comic.direction ?? 'ltr';
    return {
      anchor,
      pages: comicVisualPages(this.pages, anchor, mode, direction, this.pairingPolicy(preferences)).map((page) => {
        const cached = this.cache.get(page);
        return {
          pageIndex: page,
          ...this.pageMeta.get(page),
          url: cached?.url,
          loading: Boolean(cached?.controller),
          error: cached?.error
        };
      })
    };
  }

  private comicMode(preferences = this.preferences): 'single' | 'double' {
    if (!preferences || preferences.comic.flow === 'vertical') return 'single';
    return preferences.comic.mode;
  }

  private pairingPolicy(preferences = this.preferences): ComicPairingPolicy {
    return preferences?.comic.coverSingle ? 'cover-single' : 'paired-from-first';
  }

  private renderContinuous() {
    const preferences = this.preferences;
    if (!preferences) return;
    this.continuous.render({
      currentPage: this.currentPage,
      pageCount: this.pages.length,
      pageGap: preferences.comic.pageGap,
      imageFit: preferences.comic.imageFit,
      zoom: this.zoom,
      pages: this.pages.map((page) => {
        const cached = this.cache.get(page);
        const materialized = Math.abs(page - this.currentPage) <= 1;
        return {
          pageIndex: page,
          ...this.pageMeta.get(page),
          url: materialized ? cached?.url : undefined,
          loading: materialized && Boolean(cached?.controller),
          error: materialized ? cached?.error : undefined
        };
      })
    });
  }

  private async prepareTrackSpread(step: -1 | 1, signal: AbortSignal) {
    const preferences = this.preferences;
    if (!preferences || !this.pages.length) return false;
    const target = comicAdjacentSpreadPage(this.pages, this.currentPage, this.comicMode(preferences), step, this.pairingPolicy(preferences));
    if (target === this.currentPage) return false;
    try {
      await Promise.all(
        comicSpreadPages(this.pages, target, this.comicMode(preferences), this.pairingPolicy(preferences))
          .map((page) => this.loadPage(page, this.currentGeneration(), signal, false))
      );
      this.track.render();
      return true;
    } catch (reason) {
      if (isAbortError(reason) || reason instanceof StaleReaderOperationError) throw reason;
      this.prepareError = errorMessage(reason, '漫画页面加载失败');
      this.track.render();
      return false;
    }
  }

  private promoteTrackSpread(step: -1 | 1, signal: AbortSignal) {
    this.assertActive(this.currentGeneration(), signal);
    const preferences = this.preferences;
    if (!preferences) throw new StaleReaderOperationError();
    const target = comicAdjacentSpreadPage(this.pages, this.currentPage, this.comicMode(preferences), step, this.pairingPolicy(preferences));
    if (target === this.currentPage) throw new Error(step === 1 ? 'end-of-volume' : 'start-of-volume');
    this.currentPage = target;
    this.status = 'ready';
    this.error = undefined;
    const retained = new Set(comicCacheWindow(this.pages, this.currentPage, this.comicMode(preferences), this.pairingPolicy(preferences)));
    this.cache.forEach((_entry, page) => {
      if (!retained.has(page)) this.releasePage(page);
    });
  }

  private preloadTrackWindow() {
    const preferences = this.preferences;
    const signal = this.lifecycleController?.signal;
    if (!preferences || !signal) return;
    const generation = this.currentGeneration();
    for (const page of comicPreloadWindow(this.pages, this.currentPage, this.comicMode(preferences), this.pairingPolicy(preferences))) {
      void this.loadPage(page, generation, signal, false)
        .then(() => {
          if (this.isActive(generation, signal)) this.emitView();
        })
        .catch(() => undefined);
    }
  }

  private requestTrackCommit(request: PagedTrackCommitRequest) {
    if (!this.onInputIntent) return false;
    return this.onInputIntent({
      type: 'command',
      command: { type: request.step === 1 ? 'next' : 'previous' }
    });
  }

  private pointerInput(event: PointerEvent): PagedTrackPointerInput {
    return {
      pointerId: event.pointerId,
      clientX: event.clientX,
      clientY: event.clientY,
      timeMs: event.timeStamp,
      isPrimary: event.isPrimary
    };
  }

  private releasePointerCapture(pointerId: number) {
    const viewport = this.track.getViewportElement();
    try {
      if (viewport.hasPointerCapture(pointerId)) viewport.releasePointerCapture(pointerId);
    } catch {
      // The browser may release capture before the async settle completes.
    }
  }

  private releasePage(page: number) {
    const cached = this.cache.get(page);
    cached?.controller?.abort();
    if (cached?.url) {
      URL.revokeObjectURL(cached.url);
      cached.url = undefined;
    }
    if (cached) this.revokeEntryObjectUrl(cached);
    this.cache.delete(page);
  }

  private revokeEntryObjectUrl(entry: CachedComicPage) {
    if (!entry.objectUrl) return;
    URL.revokeObjectURL(entry.objectUrl);
    entry.objectUrl = undefined;
  }

  private releaseAllPages() {
    Array.from(this.cache.keys()).forEach((page) => this.releasePage(page));
  }

  private combineSignals(first: AbortSignal, second: AbortSignal) {
    if (typeof AbortSignal.any === 'function') {
      return { signal: AbortSignal.any([first, second]), cleanup: () => undefined };
    }
    const controller = new AbortController();
    let listening = false;
    const cleanup = () => {
      if (!listening) return;
      listening = false;
      first.removeEventListener('abort', abort);
      second.removeEventListener('abort', abort);
    };
    const abort = () => {
      cleanup();
      controller.abort();
    };
    if (first.aborted || second.aborted) controller.abort();
    else {
      listening = true;
      first.addEventListener('abort', abort, { once: true });
      second.addEventListener('abort', abort, { once: true });
      if (first.aborted || second.aborted) abort();
    }
    return { signal: controller.signal, cleanup };
  }

  private cleanupEngine() {
    this.trackController.interrupt();
    this.lifecycleController?.abort();
    this.lifecycleController = null;
    this.releaseAllPages();
    this.openContext = null;
    this.preferences = null;
    this.pages = [];
    this.pageMeta.clear();
    this.retryCounts.clear();
    this.currentPage = 1;
    this.status = 'idle';
    this.error = undefined;
    this.prepareError = undefined;
    this.track.reset();
    delete this.container.dataset.readerEngine;
  }
}

export function createComicAdapter(options: ComicAdapterOptions) {
  return new ComicReaderAdapter(options);
}
