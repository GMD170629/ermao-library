import type {
  PdfLocation,
  ReaderAdapter,
  ReaderAdapterOpenContext,
  ReaderAdapterOperationContext,
  ReaderCapabilities,
  ReaderCommand,
  ReaderCommandAck,
  ReaderPreferences
} from '@shuku/reader-core';
import { effectiveReaderPageWidth } from '../page-width';
import type {
  PDFDocumentLoadingTask,
  PDFDocumentProxy,
  PDFPageProxy,
  RenderTask,
  TextLayer
} from 'pdfjs-dist/legacy/build/pdf.mjs';
import { withBasePath } from '../../../../lib/base-path';
import { normalizeLocale } from '../../../../i18n/config';
import { translateMessage } from '../../../../i18n/messages';
import { readerThemeSurfaces } from '../../reader-theme';
import { ReaderAdapterBase, StaleReaderOperationError, errorMessage, isAbortError } from './adapter-base';
import { computePdfRenderBudget, pdfPageScale } from './pdf-render-budget';
import { detectPdfCropBox, pdfContinuousWindowPages, type PdfCropBox } from './pdf-layout';
import {
  captureContinuousAnchor,
  continuousItemAtReadingLine,
  restoreContinuousAnchor
} from './continuous-layout';

type PdfJsModule = typeof import('pdfjs-dist/legacy/build/pdf.mjs');

type RenderedPdfPage = {
  page: PDFPageProxy;
  wrapper: HTMLDivElement;
  renderTask: RenderTask;
  textLayer: TextLayer | null;
  settled: boolean;
};

type PdfPageCandidate = {
  entry: RenderedPdfPage;
  previous: RenderedPdfPage | null;
  fresh: boolean;
};

export type PdfViewModel = {
  status: 'idle' | 'loading' | 'password' | 'ready' | 'error';
  pageNumber: number;
  pageCount: number;
  zoom: number;
  fit: 'width' | 'page';
  passwordReason?: 'need-password' | 'incorrect-password';
  error?: string;
};

export type PdfAdapterOptions = {
  container: HTMLElement;
  fetch?: typeof globalThis.fetch;
  loadPdfJs?: () => Promise<PdfJsModule>;
  onViewModel?: (model: PdfViewModel) => void;
};

async function assertPdfHeader(url: string, fetcher: typeof globalThis.fetch, signal: AbortSignal) {
  const response = await fetcher(url, {
    signal,
    cache: 'no-store',
    headers: { Range: 'bytes=0-1023' }
  });
  if (!response.ok) throw new Error(`PDF 文件读取失败 (${response.status})`);
  const reader = response.body?.getReader();
  const bytes: number[] = [];
  if (reader) {
    try {
      while (bytes.length < 1024) {
        const chunk = await reader.read();
        if (chunk.done) break;
        for (const byte of chunk.value) {
          bytes.push(byte);
          if (bytes.length >= 1024) break;
        }
      }
    } finally {
      await reader.cancel().catch(() => undefined);
    }
  } else {
    bytes.push(...new Uint8Array(await response.arrayBuffer()).slice(0, 1024));
  }
  const prefix = String.fromCharCode(...bytes);
  if (!prefix.includes('%PDF-')) throw new Error('PDF 文件格式无效或已经损坏');
}

function clampPage(page: number, pageCount: number) {
  return Math.max(1, Math.min(Math.max(1, pageCount), Math.round(page || 1)));
}

const pdfTextLayerStyles = `
  .shuku-pdf-page .textLayer {
    position: absolute; inset: 0; overflow: clip; opacity: 1; line-height: 1;
    letter-spacing: normal; word-spacing: normal; transform-origin: 0 0;
    text-align: initial; text-size-adjust: none; forced-color-adjust: none;
    --min-font-size: 1; --text-scale-factor: calc(var(--total-scale-factor) * var(--min-font-size));
    --min-font-size-inv: calc(1 / var(--min-font-size));
  }
  .shuku-pdf-page .textLayer :is(span, br) {
    color: transparent; position: absolute; white-space: pre; cursor: text;
    transform-origin: 0% 0%; user-select: text;
  }
  .shuku-pdf-page .textLayer > :not(.markedContent),
  .shuku-pdf-page .textLayer .markedContent span:not(.markedContent) {
    z-index: 1; --font-height: 0; --scale-x: 1; --rotate: 0deg;
    font-size: calc(var(--text-scale-factor) * var(--font-height));
    transform: rotate(var(--rotate)) scaleX(var(--scale-x)) scale(var(--min-font-size-inv));
  }
  .shuku-pdf-page .textLayer .markedContent { display: contents; }
  .shuku-pdf-page .textLayer ::selection { background: rgba(37, 99, 235, 0.28); color: transparent; }
  .shuku-pdf-page .textLayer .endOfContent { display: block; position: absolute; inset: 100% 0 0; }
`;

export class PdfReaderAdapter extends ReaderAdapterBase implements ReaderAdapter {
  private readonly container: HTMLElement;
  private readonly fetcher: typeof globalThis.fetch;
  private readonly loadPdfJs: () => Promise<PdfJsModule>;
  private readonly viewListeners = new Set<(model: PdfViewModel) => void>();
  private pdfjs: PdfJsModule | null = null;
  private loadingTask: PDFDocumentLoadingTask | null = null;
  private document: PDFDocumentProxy | null = null;
  private preferences: ReaderPreferences | null = null;
  private openContext: ReaderAdapterOpenContext | null = null;
  private pageNumber = 1;
  private pageCount = 0;
  private lastDirection: 1 | -1 = 1;
  private renderEpoch = 0;
  private renderedPages = new Map<number, RenderedPdfPage>();
  private pendingPages = new Set<RenderedPdfPage>();
  private pendingCropTasks = new Set<RenderTask>();
  private resizeObserver: ResizeObserver | null = null;
  private resizeFrame: number | null = null;
  private resizeController: AbortController | null = null;
  private observedViewportSize: { width: number; height: number } | null = null;
  private renderTail: Promise<void> = Promise.resolve();
  private cropBoxes = new Map<number, PdfCropBox | null>();
  private scrollFrame: number | null = null;
  private continuousRenderController: AbortController | null = null;
  private continuousSlots = new Map<number, HTMLElement>();
  private continuousPageHeights = new Map<number, number>();
  private continuousFailures = new Map<number, string>();
  private passwordCallback: ((password: string) => void) | null = null;
  private passwordReason: PdfViewModel['passwordReason'];
  private status: PdfViewModel['status'] = 'idle';
  private error: string | undefined;
  private readonly handleContinuousScroll = () => {
    if (this.preferences?.pdf.flow !== 'continuous' || this.scrollFrame !== null) return;
    this.scrollFrame = requestAnimationFrame(() => {
      this.scrollFrame = null;
      const candidates = Array.from(this.continuousSlots.values());
      const index = continuousItemAtReadingLine(candidates, this.container.scrollTop, this.container.clientHeight);
      const page = Number(candidates[index]?.dataset.pdfContinuousSlot);
      if (!Number.isFinite(page) || page === this.pageNumber) return;
      this.pageNumber = clampPage(page, this.pageCount);
      this.emitLocation();
      this.continuousRenderController?.abort();
      const controller = new AbortController();
      this.continuousRenderController = controller;
      void this.queueRender(this.currentGeneration(), controller.signal).catch(() => undefined);
    });
  };

  constructor(options: PdfAdapterOptions) {
    super();
    this.container = options.container;
    this.fetcher = options.fetch ?? globalThis.fetch.bind(globalThis);
    this.loadPdfJs = options.loadPdfJs ?? (() => import('pdfjs-dist/legacy/build/pdf.mjs'));
    if (options.onViewModel) this.viewListeners.add(options.onViewModel);
    this.container.addEventListener('scroll', this.handleContinuousScroll, { passive: true });
  }

  subscribeView(listener: (model: PdfViewModel) => void) {
    this.viewListeners.add(listener);
    listener(this.viewModel());
    return () => this.viewListeners.delete(listener);
  }

  getViewModel() {
    return this.viewModel();
  }

  getCapabilities(): ReaderCapabilities {
    return {
      canGoNext: this.pageNumber < this.pageCount,
      canGoPrevious: this.pageNumber > 1,
      canJumpToProgress: true,
      canJumpToHref: false,
      canJumpToIndex: true,
      canZoom: true,
      canSelectText: true,
      supportsPagination: true,
      supportsScrolling: this.preferences?.pdf.flow === 'continuous',
      supportsSpreads: false,
      readingDirection: 'ltr'
    };
  }

  async open(context: ReaderAdapterOpenContext) {
    await this.cleanupEngine();
    const generation = this.beginSession(context.sessionId, context.operation);
    this.openContext = context;
    this.preferences = context.preferences;
    this.pageNumber = context.initialLocation?.kind === 'pdf' ? Math.max(1, context.initialLocation.pageNumber) : 1;
    this.status = 'loading';
    this.error = undefined;
    this.container.dataset.readerEngine = 'pdf-v3';
    this.applySurface();
    this.emitView();
    this.emit({ type: 'phase-changed', phase: 'loading-content' }, context.operation);

    try {
      const [, pdfjs] = await Promise.all([
        assertPdfHeader(context.source.contentUrl, this.fetcher, context.signal),
        this.loadPdfJs()
      ]);
      this.assertActive(generation, context.signal);
      this.pdfjs = pdfjs;
      pdfjs.GlobalWorkerOptions.workerSrc = withBasePath('/vendor/pdfjs/pdf.worker.legacy.min.mjs?v=6.1.200');
      const loadingTask = pdfjs.getDocument({
        url: context.source.contentUrl,
        disableRange: false,
        disableStream: false,
        disableAutoFetch: false,
        useWorkerFetch: true,
        stopAtErrors: true,
        // The reader never evaluates PDF actions or XFA content. Links and
        // annotations are deliberately not rendered below either, leaving the
        // canvas plus selectable text as the complete execution surface.
        enableXfa: false
      });
      this.loadingTask = loadingTask;
      loadingTask.onPassword = (updatePassword: (password: string) => void, reason: number) => {
        if (!this.isActive(generation, context.signal)) return;
        this.passwordCallback = updatePassword;
        this.passwordReason = reason === pdfjs.PasswordResponses.INCORRECT_PASSWORD ? 'incorrect-password' : 'need-password';
        this.status = 'password';
        this.emitView();
        this.emit({ type: 'password-required', reason: this.passwordReason }, context.operation);
      };
      const document = await loadingTask.promise;
      this.assertActive(generation, context.signal);
      this.document = document;
      this.passwordCallback = null;
      this.passwordReason = undefined;
      this.pageCount = Math.max(1, document.numPages);
      this.pageNumber = clampPage(this.pageNumber, this.pageCount);
      this.emit({ type: 'metadata-changed', totalPages: this.pageCount }, context.operation);
      this.installResizeObserver(generation);
      this.status = 'loading';
      this.emit({ type: 'phase-changed', phase: 'rendering' }, context.operation);
      await this.queueRender(generation, context.signal);
      this.assertActive(generation, context.signal);
      this.status = 'ready';
      this.emitLocation(context.operation);
      this.emitView();
      this.emit({ type: 'ready', capabilities: this.getCapabilities(), location: this.location() }, context.operation);
    } catch (reason) {
      if (isAbortError(reason) || reason instanceof StaleReaderOperationError) return;
      this.status = 'error';
      this.error = this.pdfErrorMessage(reason);
      this.emitView();
      this.emit({
        type: 'error',
        error: { code: this.pdfErrorCode(reason), message: this.error, recoverable: true }
      }, context.operation);
      throw reason;
    }
  }

  providePassword(password: string | null) {
    const callback = this.passwordCallback;
    this.passwordCallback = null;
    if (!callback) return false;
    if (password === null) {
      void this.loadingTask?.destroy();
      this.status = 'error';
      this.error = '已取消 PDF 密码输入';
      this.emitView();
      return true;
    }
    callback(password);
    this.status = 'loading';
    this.emitView();
    return true;
  }

  async execute(command: ReaderCommand, context: ReaderAdapterOperationContext): Promise<ReaderCommandAck> {
    try {
      this.beginOperation(context);
    } catch {
      return this.failOperation(context, 'stale-session');
    }
    if (command.type === 'retry' && !this.document) {
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
    if (!this.document || !this.preferences) return this.failOperation(context, 'not-ready');
    if (command.type === 'go-to-href') return this.failOperation(context, 'unsupported-command');
    if (command.type === 'cancel') {
      this.cancelRenders();
      return this.ack(context.operation, true, { location: this.location() });
    }
    let forceRender = false;
    let pageChanged = false;
    if (command.type === 'set-zoom') {
      this.preferences = { ...this.preferences, pdf: { ...this.preferences.pdf, zoom: Math.max(0.6, Math.min(2.4, command.zoom)) } };
      forceRender = true;
    } else if (command.type === 'set-fit') {
      this.preferences = { ...this.preferences, pdf: { ...this.preferences.pdf, fit: command.fit } };
      forceRender = true;
    } else {
      let target = this.pageNumber;
      if (command.type === 'next') target += 1;
      else if (command.type === 'previous') target -= 1;
      else if (command.type === 'first') target = 1;
      else if (command.type === 'last') target = this.pageCount;
      else if (command.type === 'go-to-progress') target = Math.round(Math.max(0, Math.min(1, command.progression)) * (this.pageCount - 1)) + 1;
      else if (command.type === 'go-to-index') target = command.index;
      else if (command.type === 'go-to-location') {
        if (command.location.kind !== 'pdf') return this.failOperation(context, 'location-kind-mismatch');
        target = command.location.pageNumber;
      } else if (command.type === 'retry') {
        this.continuousFailures.delete(this.pageNumber);
        this.releasePage(this.pageNumber);
      }
      const clamped = clampPage(target, this.pageCount);
      if (clamped === this.pageNumber && command.type !== 'retry') {
        if (command.type === 'next') this.emitLocation(context.operation);
        return this.failOperation(context, command.type === 'next' ? 'end-of-document' : command.type === 'previous' ? 'start-of-document' : 'no-op');
      }
      this.lastDirection = clamped >= this.pageNumber ? 1 : -1;
      pageChanged = clamped !== this.pageNumber;
      this.pageNumber = clamped;
    }

    this.emit({ type: 'activity' }, context.operation);
    this.status = 'loading';
    this.emitView();
    try {
      await this.queueRender(this.currentGeneration(), context.signal, forceRender);
      if (pageChanged && this.preferences.pdf.flow === 'paged') this.container.scrollTop = 0;
      if (pageChanged && this.preferences.pdf.flow === 'continuous') this.scrollToContinuousPage(this.pageNumber);
      this.status = 'ready';
      this.emitLocation(context.operation);
      this.emitView();
      return this.ack(context.operation, true, { location: this.location() });
    } catch (reason) {
      if (isAbortError(reason) || reason instanceof StaleReaderOperationError || this.isRenderingCancelled(reason)) {
        return this.failOperation(context, 'operation-cancelled');
      }
      this.status = 'error';
      this.error = this.pdfErrorMessage(reason);
      this.emitView();
      this.emit({
        type: 'error',
        error: { code: 'PDF_RENDER_FAILED', message: this.error, recoverable: true }
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
    const renderingGeometryChanged = preferences.pdf.rotation !== this.preferences?.pdf.rotation
      || preferences.pdf.pageWidth !== this.preferences?.pdf.pageWidth
      || preferences.pdf.cropMargins !== this.preferences?.pdf.cropMargins;
    this.preferences = preferences;
    if (renderingGeometryChanged) this.cropBoxes.clear();
    this.applySurface();
    if (this.document) {
      await this.queueRender(this.currentGeneration(), context.signal, true);
    }
    this.emitView();
    return this.ack(context.operation, true, { location: this.location() });
  }

  async dispose() {
    if (!this.markDisposed()) return;
    await this.cleanupEngine();
    this.container.removeEventListener('scroll', this.handleContinuousScroll);
    this.viewListeners.clear();
  }

  private async renderCurrentAndNeighbor(generation: number, signal: AbortSignal, force = false) {
    this.assertActive(generation, signal);
    const epoch = ++this.renderEpoch;
    this.cancelPendingRenders();
    const neighbor = this.neighborPage();
    const keep = new Set([this.pageNumber, neighbor].filter((page): page is number => Boolean(page)));
    Array.from(this.renderedPages.keys()).forEach((page) => {
      if (!keep.has(page)) this.releasePage(page);
    });

    const current = await this.renderPage(this.pageNumber, generation, epoch, signal, force);
    try {
      this.assertRenderActive(generation, epoch, signal);
    } catch (reason) {
      this.discardCandidate(current);
      throw reason;
    }
    this.container.replaceChildren(current.entry.wrapper);
    this.continuousSlots.clear();
    this.commitPage(this.pageNumber, current);
    if (neighbor) {
      void this.renderPage(neighbor, generation, epoch, signal, force)
        .then((candidate) => {
          try {
            this.assertRenderActive(generation, epoch, signal);
          } catch (reason) {
            this.discardCandidate(candidate);
            throw reason;
          }
          this.commitPage(neighbor, candidate);
        })
        .catch((reason) => {
          if (!this.isRenderingCancelled(reason) && !isAbortError(reason) && !(reason instanceof StaleReaderOperationError)) {
            this.releasePage(neighbor);
          }
        });
    }
  }

  private async renderContinuousWindow(generation: number, signal: AbortSignal, force = false) {
    this.assertActive(generation, signal);
    const epoch = ++this.renderEpoch;
    this.cancelPendingRenders();
    const hadSlots = this.continuousSlots.size > 0;
    this.ensureContinuousSlots();
    const anchor = this.captureContinuousAnchor();
    const windowPages = pdfContinuousWindowPages(this.pageNumber, this.pageCount);
    const keep = new Set(windowPages);
    Array.from(this.renderedPages.keys()).forEach((page) => {
      if (!keep.has(page)) this.releasePage(page);
    });
    const candidates = await Promise.all(windowPages.map(async (page) => {
      try {
        const candidate = await this.renderPage(page, generation, epoch, signal, force);
        this.continuousFailures.delete(page);
        return { page, candidate };
      } catch (reason) {
        if (this.isRenderingCancelled(reason) || isAbortError(reason) || reason instanceof StaleReaderOperationError) throw reason;
        this.continuousFailures.set(page, this.pdfErrorMessage(reason));
        return { page, candidate: null };
      }
    }));
    candidates.forEach(({ page, candidate }) => {
      if (candidate) this.commitPage(page, candidate);
    });
    this.assertRenderActive(generation, epoch, signal);
    this.reconcileContinuousSlots();
    this.restoreContinuousAnchor(anchor);
    if (!hadSlots) this.scrollToContinuousPage(this.pageNumber);
  }

  private ensureContinuousSlots() {
    if (this.continuousSlots.size) return;
    const document = documentOwner(this.container);
    const fallbackHeight = Math.max(320, Math.round(this.container.clientHeight * 0.85));
    this.container.replaceChildren();
    for (let page = 1; page <= this.pageCount; page += 1) {
      const slot = document.createElement('section');
      slot.dataset.pdfContinuousSlot = String(page);
      Object.assign(slot.style, {
        alignItems: 'flex-start',
        display: 'flex',
        justifyContent: 'center',
        margin: '0 auto 24px',
        minHeight: `${this.continuousPageHeights.get(page) ?? fallbackHeight}px`,
        position: 'relative',
        width: '100%'
      });
      this.continuousSlots.set(page, slot);
      this.container.append(slot);
    }
  }

  private reconcileContinuousSlots() {
    const fallbackHeight = Math.max(320, Math.round(this.container.clientHeight * 0.85));
    for (let page = 1; page <= this.pageCount; page += 1) {
      const slot = this.continuousSlots.get(page);
      if (!slot) continue;
      const rendered = this.renderedPages.get(page);
      if (rendered) {
        delete slot.dataset.pdfFailure;
        const height = Number.parseFloat(rendered.wrapper.style.height) || rendered.wrapper.offsetHeight || fallbackHeight;
        this.continuousPageHeights.set(page, height);
        slot.style.minHeight = `${height}px`;
        if (slot.firstElementChild !== rendered.wrapper) slot.replaceChildren(rendered.wrapper);
        continue;
      }
      const failure = this.continuousFailures.get(page);
      if (failure) this.renderContinuousFailure(slot, page, failure);
      else {
        delete slot.dataset.pdfFailure;
        if (slot.childElementCount) slot.replaceChildren();
      }
      slot.style.minHeight = `${this.continuousPageHeights.get(page) ?? fallbackHeight}px`;
    }
  }

  private renderContinuousFailure(slot: HTMLElement, page: number, messageText: string) {
    if (slot.dataset.pdfFailure === messageText) return;
    slot.dataset.pdfFailure = messageText;
    const document = documentOwner(this.container);
    const failure = document.createElement('div');
    failure.setAttribute('role', 'alert');
    const message = document.createElement('p');
    message.textContent = messageText;
    const retry = document.createElement('button');
    retry.type = 'button';
    retry.textContent = translateMessage(normalizeLocale(document.documentElement.lang), '重试本页');
    retry.addEventListener('click', () => {
      this.continuousFailures.delete(page);
      delete slot.dataset.pdfFailure;
      this.releasePage(page);
      const controller = new AbortController();
      this.continuousRenderController?.abort();
      this.continuousRenderController = controller;
      void this.queueRender(this.currentGeneration(), controller.signal, true).catch(() => undefined);
    });
    failure.append(message, retry);
    slot.replaceChildren(failure);
  }

  private captureContinuousAnchor() {
    return captureContinuousAnchor(
      this.container,
      Array.from(this.continuousSlots.values()),
      (item) => item.dataset.pdfContinuousSlot
    );
  }

  private restoreContinuousAnchor(anchor: ReturnType<typeof captureContinuousAnchor>) {
    restoreContinuousAnchor(
      this.container,
      Array.from(this.continuousSlots.values()),
      anchor,
      (item) => item.dataset.pdfContinuousSlot
    );
  }

  private scrollToContinuousPage(page: number) {
    const slot = this.continuousSlots.get(page);
    if (slot) this.container.scrollTop = Math.max(0, slot.offsetTop);
  }

  private queueRender(generation: number, signal: AbortSignal, force = false) {
    const run = async () => {
      this.assertActive(generation, signal);
      const abortRender = () => this.cancelRenders();
      signal.addEventListener('abort', abortRender, { once: true });
      try {
      if (this.preferences?.pdf.flow === 'continuous') await this.renderContinuousWindow(generation, signal, force);
      else await this.renderCurrentAndNeighbor(generation, signal, force);
      } finally {
        signal.removeEventListener('abort', abortRender);
      }
    };
    const task = this.renderTail.catch(() => undefined).then(run);
    this.renderTail = task.catch(() => undefined);
    return task;
  }

  private async renderPage(
    pageNumber: number,
    generation: number,
    epoch: number,
    signal: AbortSignal,
    force = false
  ): Promise<PdfPageCandidate> {
    const cached = this.renderedPages.get(pageNumber);
    if (cached?.settled && !force) {
      return { entry: cached, previous: null, fresh: false };
    }
    const document = this.document;
    const pdfjs = this.pdfjs;
    const preferences = this.preferences;
    if (!document || !pdfjs || !preferences) throw new Error('PDF is not ready');
    const page = await document.getPage(pageNumber);
    this.assertRenderActive(generation, epoch, signal);
    const baseViewport = page.getViewport({ scale: 1, rotation: preferences.pdf.rotation });
    const visibleContainerWidth = Math.max(1, this.container.clientWidth || window.innerWidth || baseViewport.width);
    const containerWidth = effectiveReaderPageWidth(preferences.pdf.pageWidth, visibleContainerWidth);
    const containerHeight = Math.max(1, this.container.clientHeight || window.innerHeight || baseViewport.height);
    const scale = pdfPageScale({
      pageWidth: baseViewport.width,
      pageHeight: baseViewport.height,
      containerWidth,
      containerHeight,
      fit: preferences.pdf.fit,
      zoom: preferences.pdf.zoom
    });
    const viewport = page.getViewport({ scale, rotation: preferences.pdf.rotation });
    const cropBox = preferences.pdf.cropMargins === 'auto'
      ? await this.resolveCropBox(pageNumber, page, generation, epoch, signal)
      : null;
    const budget = computePdfRenderBudget({
      cssWidth: viewport.width,
      cssHeight: viewport.height,
      devicePixelRatio: window.devicePixelRatio || 1
    });
    const wrapper = documentOwner(this.container).createElement('div');
    wrapper.className = 'shuku-pdf-page';
    wrapper.dataset.pageNumber = String(pageNumber);
    Object.assign(wrapper.style, {
      background: '#ffffff',
      height: `${viewport.height * (cropBox ? cropBox.bottom - cropBox.top : 1)}px`,
      margin: '0 auto',
      position: 'relative',
      overflow: 'hidden',
      width: `${viewport.width * (cropBox ? cropBox.right - cropBox.left : 1)}px`
    });
    const style = documentOwner(this.container).createElement('style');
    style.textContent = pdfTextLayerStyles;
    const canvas = documentOwner(this.container).createElement('canvas');
    canvas.width = budget.pixelWidth;
    canvas.height = budget.pixelHeight;
    canvas.style.display = 'block';
    canvas.style.height = `${viewport.height}px`;
    canvas.style.width = `${viewport.width}px`;
    if (cropBox) canvas.style.transform = `translate(${-cropBox.left * viewport.width}px, ${-cropBox.top * viewport.height}px)`;
    canvas.setAttribute('aria-label', `PDF 第 ${pageNumber} 页`);
    const textLayerElement = documentOwner(this.container).createElement('div');
    textLayerElement.className = 'textLayer';
    textLayerElement.setAttribute('aria-label', `PDF 第 ${pageNumber} 页文本`);
    textLayerElement.style.setProperty('--total-scale-factor', String(scale));
    if (cropBox) textLayerElement.style.transform = `translate(${-cropBox.left * viewport.width}px, ${-cropBox.top * viewport.height}px)`;
    wrapper.append(style, canvas, textLayerElement);

    const renderTask = page.render({
      canvas,
      viewport,
      transform: budget.outputScale === 1 ? undefined : [budget.outputScale, 0, 0, budget.outputScale, 0, 0],
      annotationMode: pdfjs.AnnotationMode.DISABLE,
      background: '#ffffff'
    });
    const entry: RenderedPdfPage = { page, wrapper, renderTask, textLayer: null, settled: false };
    this.pendingPages.add(entry);
    try {
      await renderTask.promise;
      this.assertRenderActive(generation, epoch, signal);
      const textLayer = new pdfjs.TextLayer({
        textContentSource: page.streamTextContent({ includeMarkedContent: true }),
        container: textLayerElement,
        viewport
      });
      entry.textLayer = textLayer;
      try {
        await textLayer.render();
        this.assertRenderActive(generation, epoch, signal);
      } catch (reason) {
        if (isAbortError(reason) || reason instanceof StaleReaderOperationError || this.isRenderingCancelled(reason)) throw reason;
        // A malformed text stream should not hide an otherwise renderable page.
        textLayer.cancel();
        textLayerElement.remove();
        entry.textLayer = null;
      }
      entry.settled = true;
      this.pendingPages.delete(entry);
      return { entry, previous: cached ?? null, fresh: true };
    } catch (reason) {
      this.pendingPages.delete(entry);
      this.releaseEntry(entry);
      throw reason;
    }
  }

  private async resolveCropBox(
    pageNumber: number,
    page: PDFPageProxy,
    generation: number,
    epoch: number,
    signal: AbortSignal
  ): Promise<PdfCropBox | null> {
    if (this.cropBoxes.has(pageNumber)) return this.cropBoxes.get(pageNumber) ?? null;
    const pdfjs = this.pdfjs;
    if (!pdfjs) return null;
    const viewport = page.getViewport({ scale: 0.2, rotation: this.preferences?.pdf.rotation ?? 0 });
    const canvas = documentOwner(this.container).createElement('canvas');
    canvas.width = Math.max(1, Math.round(viewport.width));
    canvas.height = Math.max(1, Math.round(viewport.height));
    const context = canvas.getContext('2d', { willReadFrequently: true });
    if (!context) return null;
    const task = page.render({ canvas, viewport, annotationMode: pdfjs.AnnotationMode.DISABLE, background: '#ffffff' });
    this.pendingCropTasks.add(task);
    const cancel = () => task.cancel();
    signal.addEventListener('abort', cancel, { once: true });
    try {
      await task.promise;
      this.assertRenderActive(generation, epoch, signal);
      const pixels = context.getImageData(0, 0, canvas.width, canvas.height).data;
      const crop = detectPdfCropBox(pixels, canvas.width, canvas.height);
      this.cropBoxes.set(pageNumber, crop);
      return crop;
    } catch (reason) {
      if (this.isRenderingCancelled(reason) || isAbortError(reason) || reason instanceof StaleReaderOperationError) throw reason;
      this.cropBoxes.set(pageNumber, null);
      return null;
    } finally {
      this.pendingCropTasks.delete(task);
      signal.removeEventListener('abort', cancel);
      canvas.remove();
    }
  }

  private installResizeObserver(generation: number) {
    if (typeof ResizeObserver === 'undefined') return;
    this.resizeObserver?.disconnect();
    this.observedViewportSize = this.viewportSize();
    this.resizeObserver = new ResizeObserver((entries) => {
      const entry = entries[entries.length - 1];
      const nextSize = entry
        ? {
            width: Math.round(entry.contentRect.width),
            height: Math.round(entry.contentRect.height)
          }
        : this.viewportSize();
      if (
        this.observedViewportSize
        && nextSize.width === this.observedViewportSize.width
        && nextSize.height === this.observedViewportSize.height
      ) return;
      this.observedViewportSize = nextSize;
      if (this.resizeFrame !== null) cancelAnimationFrame(this.resizeFrame);
      this.resizeFrame = requestAnimationFrame(() => {
        this.resizeFrame = null;
        if (!this.isActive(generation) || !this.document) return;
        this.resizeController?.abort();
        const controller = new AbortController();
        this.resizeController = controller;
        void this.queueRender(generation, controller.signal, true).catch(() => undefined);
      });
    });
    this.resizeObserver.observe(this.container);
  }

  private viewportSize() {
    return {
      width: Math.round(this.container.clientWidth),
      height: Math.round(this.container.clientHeight)
    };
  }

  private commitPage(pageNumber: number, candidate: PdfPageCandidate) {
    if (!candidate.fresh) return;
    this.renderedPages.set(pageNumber, candidate.entry);
    if (candidate.previous) this.releaseEntry(candidate.previous);
  }

  private discardCandidate(candidate: PdfPageCandidate) {
    if (candidate.fresh) this.releaseEntry(candidate.entry);
  }

  private emitLocation(operation = this.currentOperation()) {
    const percent = this.pageCount > 1 ? ((this.pageNumber - 1) / (this.pageCount - 1)) * 100 : 100;
    this.emit({ type: 'location-changed', location: this.location(), percent }, operation);
    this.emit({ type: 'capabilities-changed', capabilities: this.getCapabilities() }, operation);
  }

  private location(): PdfLocation {
    return { kind: 'pdf', pageNumber: this.pageNumber };
  }

  private neighborPage() {
    const requested = this.pageNumber + this.lastDirection;
    if (requested >= 1 && requested <= this.pageCount) return requested;
    const opposite = this.pageNumber - this.lastDirection;
    return opposite >= 1 && opposite <= this.pageCount ? opposite : null;
  }

  private assertRenderActive(generation: number, epoch: number, signal: AbortSignal) {
    this.assertActive(generation, signal);
    if (epoch !== this.renderEpoch) throw new StaleReaderOperationError();
  }

  private cancelRenders(incrementEpoch = true) {
    if (incrementEpoch) this.renderEpoch += 1;
    this.renderedPages.forEach((entry) => {
      entry.renderTask.cancel();
      entry.textLayer?.cancel();
    });
    this.cancelPendingRenders();
  }

  private cancelPendingRenders() {
    this.pendingPages.forEach((entry) => {
      entry.renderTask.cancel();
      entry.textLayer?.cancel();
    });
    this.pendingCropTasks.forEach((task) => task.cancel());
  }

  private releasePage(pageNumber: number) {
    const entry = this.renderedPages.get(pageNumber);
    if (!entry) return;
    this.renderedPages.delete(pageNumber);
    this.releaseEntry(entry);
  }

  private releaseEntry(entry: RenderedPdfPage) {
    entry.renderTask.cancel();
    entry.textLayer?.cancel();
    entry.page.cleanup();
    entry.wrapper.remove();
  }

  private releaseAllPages() {
    Array.from(this.renderedPages.keys()).forEach((page) => this.releasePage(page));
  }

  private isRenderingCancelled(reason: unknown) {
    return Boolean(this.pdfjs?.RenderingCancelledException && reason instanceof this.pdfjs.RenderingCancelledException);
  }

  private pdfErrorCode(reason: unknown) {
    const pdfjs = this.pdfjs;
    if (pdfjs && reason instanceof pdfjs.InvalidPDFException) return 'PDF_INVALID';
    if (pdfjs && reason instanceof pdfjs.PasswordException) return 'PDF_PASSWORD_CANCELLED';
    if (pdfjs && reason instanceof pdfjs.ResponseException) return 'PDF_NETWORK_FAILED';
    return 'PDF_OPEN_FAILED';
  }

  private pdfErrorMessage(reason: unknown) {
    const code = this.pdfErrorCode(reason);
    if (code === 'PDF_INVALID') return 'PDF 文件已损坏或格式无效';
    if (code === 'PDF_PASSWORD_CANCELLED') return '未提供 PDF 密码';
    if (code === 'PDF_NETWORK_FAILED') return 'PDF 网络请求失败';
    return errorMessage(reason, 'PDF 加载失败');
  }

  private viewModel(): PdfViewModel {
    return {
      status: this.status,
      pageNumber: this.pageNumber,
      pageCount: this.pageCount,
      zoom: this.preferences?.pdf.zoom ?? 1,
      fit: this.preferences?.pdf.fit ?? 'page',
      passwordReason: this.passwordReason,
      error: this.error
    };
  }

  private emitView() {
    const model = this.viewModel();
    this.viewListeners.forEach((listener) => listener(model));
  }

  private applySurface() {
    if (!this.preferences) return;
    Object.assign(this.container.style, {
      alignItems: '',
      background: readerThemeSurfaces[this.preferences.appearance.theme].background,
      display: 'block',
      height: '100%',
      justifyContent: '',
      overflow: 'auto',
      touchAction: this.preferences.pdf.flow === 'continuous' || this.preferences.pdf.zoom > 1 ? 'pan-x pan-y' : 'none',
      width: '100%'
    });
  }

  private async cleanupEngine() {
    this.renderEpoch += 1;
    if (this.scrollFrame !== null) cancelAnimationFrame(this.scrollFrame);
    this.scrollFrame = null;
    this.continuousRenderController?.abort();
    this.continuousRenderController = null;
    if (this.resizeFrame !== null) cancelAnimationFrame(this.resizeFrame);
    this.resizeFrame = null;
    this.resizeController?.abort();
    this.resizeController = null;
    this.resizeObserver?.disconnect();
    this.resizeObserver = null;
    this.observedViewportSize = null;
    this.cancelPendingRenders();
    this.releaseAllPages();
    const loadingTask = this.loadingTask;
    this.loadingTask = null;
    this.document = null;
    this.pdfjs = null;
    this.passwordCallback = null;
    this.passwordReason = undefined;
    this.openContext = null;
    this.preferences = null;
    this.pageNumber = 1;
    this.pageCount = 0;
    this.cropBoxes.clear();
    this.continuousSlots.clear();
    this.continuousPageHeights.clear();
    this.continuousFailures.clear();
    this.status = 'idle';
    this.error = undefined;
    try {
      await loadingTask?.destroy();
    } catch {
      // The worker may already be gone after an aborted network request.
    }
    this.container.replaceChildren();
    delete this.container.dataset.readerEngine;
  }
}

function documentOwner(element: Element) {
  return element.ownerDocument ?? document;
}

export function createPdfAdapter(options: PdfAdapterOptions) {
  return new PdfReaderAdapter(options);
}
