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
import { readerThemeSurfaces } from '../../reader-theme';
import { isReaderControlTarget } from '../input-router';
import { PagedTrackController } from '../paged-track/paged-track-controller';
import type { PageStep, PagedTrackCommitRequest, PagedTrackPointerInput } from '../paged-track/paged-track-types';
import { ReaderAdapterBase, StaleReaderOperationError, errorMessage, isAbortError } from './adapter-base';
import { ComicSpreadTrackDriver, type ComicTrackSpread, type ComicTrackView } from './comic-track';
import { ComicContinuousController } from './comic-continuous';
import { effectiveReaderPageWidth } from '../page-width';
import type { ReaderAdapterInputHandler, ReaderInteractiveAdapter, ReaderInteractionPolicy } from './reader-interaction';
import {
  comicAdjacentSpreadPage,
  comicLastSpreadPage,
  comicNormalizePage,
  comicOrderedPages,
  comicPageForProgress,
  comicPagePercent,
  comicSpreadPages,
  comicVisualPages,
  type ComicPairingPolicy,
  type ComicPageMeta
} from './comic-model';

export type ComicPageView = ComicPageMeta & {
  url: string;
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

export type ComicAdapterOptions = {
  container: HTMLElement;
  onInputIntent?: ReaderAdapterInputHandler;
  pageUrl?: (context: ReaderAdapterOpenContext, pageIndex: number, preferences: ReaderPreferences, retry: number) => string;
  initialPages?: ComicPageMeta[];
  revision: string;
  onViewModel?: (model: ComicViewModel) => void;
  onEndOfResource?: () => void;
};

function clampPage(page: number, pageCount: number) {
  return Math.max(0, Math.min(Math.max(0, pageCount - 1), Math.round(Number.isFinite(page) ? page : 0)));
}

function defaultPageUrl(
  context: ReaderAdapterOpenContext,
  pageIndex: number,
  preferences: ReaderPreferences,
  retry: number,
  revision: string
) {
  if (context.source.kind !== 'comic') throw new Error('COMIC_SOURCE_INVALID');
  const parameters = new URLSearchParams({ imageVariant: preferences.comic.imageVariant, revision });
  if (retry > 0) parameters.set('retry', String(retry));
  return `${context.source.comicPageUrlTemplate.replace('{pageIndex}', encodeURIComponent(String(pageIndex)))}?${parameters}`;
}

export class ComicReaderAdapter extends ReaderAdapterBase implements ReaderAdapter, ReaderInteractiveAdapter {
  private readonly container: HTMLElement;
  private readonly pageUrl: NonNullable<ComicAdapterOptions['pageUrl']>;
  private readonly initialPages?: ComicPageMeta[];
  private readonly revision: string;
  private readonly onEndOfResource?: ComicAdapterOptions['onEndOfResource'];
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
  private currentPage = 0;
  private retryCounts = new Map<number, number>();
  private status: ComicViewModel['status'] = 'idle';
  private error: string | undefined;
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
    if (!/^sha256:[a-f0-9]{64}$/.test(options.revision)) throw new Error('READER_COMIC_MANIFEST_INVALID');
    this.revision = options.revision;
    this.pageUrl = options.pageUrl ?? ((context, pageIndex, preferences, retry) => (
      defaultPageUrl(context, pageIndex, preferences, retry, this.revision)
    ));
    this.initialPages = options.initialPages;
    this.onEndOfResource = options.onEndOfResource;
    this.onInputIntent = options.onInputIntent;
    this.track = new ComicSpreadTrackDriver(this.container, {
      getView: () => this.trackView(),
      prepare: (step, signal) => this.prepareTrackSpread(step, signal),
      promote: (step, signal) => this.promoteTrackSpread(step, signal),
      retry: (page) => this.retryPage(page)
    });
    this.trackController = new PagedTrackController(this.track, {
      requestCommit: (request) => this.requestTrackCommit(request),
      boundaryCommitSteps: [1]
    });
    this.continuous = new ComicContinuousController(this.container, (page) => {
      if (this.preferences?.comic.flow !== 'scrolled' || page === this.currentPage) return;
      this.currentPage = clampPage(page, this.pages.length);
      this.emitLocation();
      this.emitView();
    }, (page) => {
      const signal = this.lifecycleController?.signal;
      if (!signal || signal.aborted) return;
      this.retryCounts.set(page, (this.retryCounts.get(page) ?? 0) + 1);
      if (this.preferences?.comic.flow === 'scrolled') {
        this.renderContinuous();
        return;
      }
      this.track.render();
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
    if (this.preferences?.comic.flow === 'scrolled') return { horizontalPaging: 'none' };
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
      supportsScrolling: this.preferences?.comic.flow === 'scrolled',
      supportsSpreads: this.preferences?.comic.flow !== 'scrolled',
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
      this.assertActive(generation, signal);
      if (!pages?.length) throw new Error('READER_COMIC_MANIFEST_INVALID');
      if (pages.length) {
        pages.forEach((page) => this.pageMeta.set(page.pageIndex, page));
        pageCount = Math.max(pageCount, ...pages.map((page) => page.pageIndex + 1));
      }
      if (pageCount <= 0) throw new Error('漫画资源没有可读取页面');
      this.pages = comicOrderedPages(pageCount);
      const initialPage = context.initialLocation?.kind === 'comic' ? context.initialLocation.pageIndex : 0;
      this.currentPage = comicNormalizePage(this.pages, clampPage(initialPage, pageCount), this.comicMode(context.preferences), this.pairingPolicy(context.preferences));
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
      if (this.preferences.comic.flow === 'scrolled') {
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
      if (command.location.resourceId !== this.openContext.source.resourceId) {
        return this.failOperation(context, 'resource-switch-requires-new-session');
      }
      nextPage = comicNormalizePage(this.pages, clampPage(command.location.pageIndex, this.pages.length), this.comicMode(), this.pairingPolicy());
    } else if (command.type === 'retry') {
      comicSpreadPages(this.pages, this.currentPage, this.comicMode(), this.pairingPolicy()).forEach((page) => {
        this.retryCounts.set(page, (this.retryCounts.get(page) ?? 0) + 1);
      });
    }

    if (!nextPage || nextPage === this.currentPage && command.type !== 'retry') {
      return this.failOperation(context, 'no-op');
    }

    this.currentPage = nextPage;
    this.emit({ type: 'activity' }, context.operation);
    this.status = 'ready';
    this.emitView();
    if (this.preferences.comic.flow === 'scrolled') this.continuous.scrollToPage(this.currentPage);
    else this.track.recenter(true);
    this.emitLocation(context.operation);
    return this.ack(context.operation, true, { location: this.location() });
  }

  async applyPreferences(preferences: ReaderPreferences, context: ReaderAdapterOperationContext): Promise<ReaderCommandAck> {
    try {
      this.beginOperation(context);
    } catch {
      return this.failOperation(context, 'stale-session');
    }
    this.trackController.interrupt({ suspended: preferences.comic.zoom > 1 });
    const previousFlow = this.preferences?.comic.flow;
    const modeChanged = preferences.comic.spreadMode !== this.preferences?.comic.spreadMode
      || preferences.comic.flow !== this.preferences?.comic.flow
      || preferences.comic.coverSingle !== this.preferences?.comic.coverSingle;
    const pageBeforeModeChange = this.currentPage;
    this.preferences = preferences;
    if (modeChanged) this.currentPage = comicNormalizePage(this.pages, this.currentPage, this.comicMode(preferences), this.pairingPolicy(preferences));
    this.zoom = preferences.comic.zoom;
    this.container.style.background = readerThemeSurfaces[preferences.appearance.theme].background;
    if (this.openContext && this.pages.length) {
      this.assertActive(this.currentGeneration(), context.signal);
      this.emitView();
      if (preferences.comic.flow === 'scrolled') {
        if (previousFlow !== 'scrolled') this.continuous.scrollToPage(this.currentPage);
      } else {
        this.track.recenter();
      }
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
    if (this.preferences?.comic.flow === 'scrolled') this.renderContinuous();
    else {
      this.track.render();
      this.track.recenter();
    }
  }

  private async executeAdjacentStep(step: PageStep, context: ReaderAdapterOperationContext): Promise<ReaderCommandAck> {
    const target = comicAdjacentSpreadPage(this.pages, this.currentPage, this.comicMode(), step, this.pairingPolicy());
    if (target === this.currentPage) {
      if (step === 1) this.onEndOfResource?.();
      return this.failOperation(context, step === 1 ? 'end-of-resource' : 'start-of-resource');
    }

    this.emit({ type: 'activity' }, context.operation);
    this.status = 'loading';
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
        return this.failOperation(context, 'page-not-ready');
      }

      this.status = 'ready';
      this.emitLocation(context.operation);
      this.emitView();
      return this.ack(context.operation, true, { location: this.location() });
    } catch (reason) {
      if (isAbortError(reason) || reason instanceof StaleReaderOperationError) {
        this.status = 'ready';
        this.emitView();
        return this.failOperation(context, 'operation-cancelled');
      }
      this.status = 'ready';
      const message = errorMessage(reason, '漫画加载失败');
      this.emitView();
      return this.failOperation(context, message);
    }
  }

  private async executeContinuousAdjacentStep(
    step: PageStep,
    context: ReaderAdapterOperationContext
  ): Promise<ReaderCommandAck> {
    const target = comicAdjacentSpreadPage(this.pages, this.currentPage, 'single', step, this.pairingPolicy());
    if (target === this.currentPage) {
      return this.failOperation(context, step === 1 ? 'end-of-resource' : 'start-of-resource');
    }
    this.emit({ type: 'activity' }, context.operation);
    this.currentPage = target;
    this.status = 'ready';
    this.emitView();
    this.continuous.scrollToPage(target);
    this.emitLocation(context.operation);
    return this.ack(context.operation, true, { location: this.location() });
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
    const resourceId = this.openContext?.source.resourceId;
    if (!resourceId) throw new Error('comic-resource-id-missing');
    return {
      kind: 'comic',
      resourceId,
      pageIndex: this.currentPage,
      ...(this.pageMeta.get(this.currentPage)?.resourceHref
        ? { resourceHref: this.pageMeta.get(this.currentPage)?.resourceHref }
        : {})
    };
  }

  private viewModel(): ComicViewModel {
    const preferences = this.preferences;
    const visiblePages = preferences
      ? comicVisualPages(this.pages, this.currentPage, this.comicMode(preferences), preferences.comic.direction, this.pairingPolicy(preferences)).map((page) => {
          return {
            pageIndex: page,
            ...this.pageMeta.get(page),
            url: this.pageSource(page)
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
    const vertical = this.preferences?.comic.flow === 'scrolled';
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
      pageWidth: effectiveReaderPageWidth(
        preferences?.comic.pageWidth ?? 1350,
        this.viewportWidth || this.container.clientWidth || 1350
      ),
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
        return {
          pageIndex: page,
          ...this.pageMeta.get(page),
          url: this.pageSource(page)
        };
      })
    };
  }

  private comicMode(preferences = this.preferences): 'single' | 'double' {
    if (!preferences || preferences.comic.flow === 'scrolled') return 'single';
    return preferences.comic.spreadMode;
  }

  private pairingPolicy(preferences = this.preferences): ComicPairingPolicy {
    return preferences?.comic.coverSingle ? 'cover-single' : 'paired-from-first';
  }

  private renderContinuous() {
    const preferences = this.preferences;
    const context = this.openContext;
    if (!preferences || !context) return;
    this.continuous.render({
      currentPage: this.currentPage,
      pageCount: this.pages.length,
      imageFit: preferences.comic.imageFit,
      zoom: this.zoom,
      pageWidth: effectiveReaderPageWidth(
        preferences.comic.pageWidth,
        this.viewportWidth || this.container.clientWidth || 1350
      ),
      pages: this.pages.map((page) => {
        return {
          pageIndex: page,
          ...this.pageMeta.get(page),
          url: this.pageSource(page)
        };
      })
    });
  }

  private async prepareTrackSpread(step: -1 | 1, signal: AbortSignal) {
    this.assertActive(this.currentGeneration(), signal);
    const preferences = this.preferences;
    if (!preferences || !this.pages.length) return false;
    const target = comicAdjacentSpreadPage(this.pages, this.currentPage, this.comicMode(preferences), step, this.pairingPolicy(preferences));
    return target !== this.currentPage;
  }

  private promoteTrackSpread(step: -1 | 1, signal: AbortSignal) {
    this.assertActive(this.currentGeneration(), signal);
    const preferences = this.preferences;
    if (!preferences) throw new StaleReaderOperationError();
    const target = comicAdjacentSpreadPage(this.pages, this.currentPage, this.comicMode(preferences), step, this.pairingPolicy(preferences));
    if (target === this.currentPage) throw new Error(step === 1 ? 'end-of-resource' : 'start-of-resource');
    this.currentPage = target;
    this.status = 'ready';
    this.error = undefined;
  }

  private pageSource(page: number) {
    const context = this.openContext;
    const preferences = this.preferences;
    if (!context || !preferences) throw new StaleReaderOperationError();
    if (this.pageMeta.get(page)?.safetyError) return '';
    return this.pageUrl(context, page, preferences, this.retryCounts.get(page) ?? 0);
  }

  private retryPage(page: number) {
    if (this.pageMeta.get(page)?.safetyError) return;
    this.retryCounts.set(page, (this.retryCounts.get(page) ?? 0) + 1);
    if (this.preferences?.comic.flow === 'scrolled') this.renderContinuous();
    else this.track.render();
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
    this.openContext = null;
    this.preferences = null;
    this.pages = [];
    this.pageMeta.clear();
    this.retryCounts.clear();
    this.currentPage = 0;
    this.status = 'idle';
    this.error = undefined;
    this.track.reset();
    delete this.container.dataset.readerEngine;
  }
}

export function createComicAdapter(options: ComicAdapterOptions) {
  return new ComicReaderAdapter(options);
}
