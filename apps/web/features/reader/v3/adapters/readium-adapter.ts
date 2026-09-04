import { EpubNavigator, EpubPreferences, type EpubNavigatorListeners } from '@readium/navigator';
import { Layout, Link, Locator, LocatorLocations } from '@readium/shared';
import {
  readerAdjacentResourceProgression,
  type OperationToken,
  type ReaderAdapter,
  type ReaderAdapterOpenContext,
  type ReaderAdapterOperationContext,
  type ReaderCapabilities,
  type ReaderCommand,
  type ReaderCommandAck,
  type ReaderOpaqueLocator,
  type ReaderPreferences,
  type ReaderPositionReport,
  type ReflowableLocation
} from '@shuku/reader-core';
import { ReaderAdapterBase } from './adapter-base';
import { openReadiumPublication } from './readium-publication';
import type { ReaderAdapterInputHandler, ReaderInteractiveAdapter, ReaderInteractionPolicy } from './reader-interaction';
import {
  closestReadiumPosition,
  bareHref,
  findReadiumPublicationResource,
  hrefFragment,
  isAllowedReadiumExternalHref,
  readiumTotalProgression,
  readiumNavigationEntries,
  resolveReadiumStartupTargets,
  resolveReadiumHref,
  samePublicationResource
} from './readium-navigation';
import {
  ReaderKeyboardNavigationController,
  hasActiveTextSelection,
  isReaderControlTarget,
  isReaderKeyboardControlTarget,
  readerFramePointerIntent,
  readerKeyIntent,
  readerPointerIntent
} from '../input-router';
import {
  applyReadiumDocumentPresentation,
  createReadiumEpubPreferences,
  resolveReadiumViewportPresentation
} from './readium-presentation';
import { resolveEpubFont, type EpubFontResolution } from './epub-font';
import { advanceScrollViewport, positionScrollResourceEdge } from './scroll-page-turn';
import { LOCATION_RESTORE_FAILED as STANDARD_LOCATION_RESTORE_FAILED } from '../../../../lib/reader/v5-locator';

const READIUM_VERSION = 'readium-ts:2.8.2';
export const LOCATION_RESTORE_FAILED = STANDARD_LOCATION_RESTORE_FAILED;
const READIUM_SUPPORTED_CONTROLS = [
  'Theme', 'SystemTheme', 'FontSize', 'FontFamily', 'FontWeight', 'LineHeight',
  'LetterSpacing', 'NegativeLetterSpacing', 'PageMargins', 'PageWidth', 'ReadingMode',
  'ReadingProgression', 'WritingMode', 'Spread', 'ParagraphIndent', 'ParagraphSpacing', 'TextAlignment', 'PublisherStyles',
  'SmartOptimization', 'DeduplicateIndent', 'IndentUnindented', 'ProgressStyle', 'Clock',
  'KeepAwake', 'TapZones', 'Keyboard'
] as const;

export type ReadiumAdapterOptions = {
  container: HTMLElement;
  publicationBlob: Blob;
  publicationTitle: string;
  initialHref?: string | null;
  onInputIntent?: ReaderAdapterInputHandler;
  onEndOfResource?: () => boolean | Promise<boolean>;
};

function callbackNavigation(run: (callback: (ok: boolean) => void) => void) {
  return new Promise<boolean>((resolve) => run(resolve));
}

function capabilities(navigator: EpubNavigator): ReaderCapabilities {
  const supportsTextLayout = navigator.publication.metadata.layout !== Layout.fixed;
  return { readingDirection: navigator.readingProgression === 'rtl' ? 'rtl' : 'ltr', canGoNext: navigator.canGoForward, canGoPrevious: navigator.canGoBackward, canJumpToProgress: true, canJumpToHref: true, canJumpToIndex: true, canZoom: false, canSelectText: true, supportsPagination: true, supportsScrolling: true, supportsSpreads: true, supportedControls: supportsTextLayout ? READIUM_SUPPORTED_CONTROLS : READIUM_SUPPORTED_CONTROLS.filter((control) => control !== 'ReadingProgression' && control !== 'WritingMode') };
}

const DEFAULT_CAPABILITIES: ReaderCapabilities = {
  readingDirection: 'ltr',
  canGoNext: false,
  canGoPrevious: false,
  canJumpToProgress: true,
  canJumpToHref: true,
  canJumpToIndex: true,
  canZoom: false,
  canSelectText: true,
  supportsPagination: true,
  supportsScrolling: true,
  supportsSpreads: true,
  supportedControls: READIUM_SUPPORTED_CONTROLS
};

function commandForInput(intent: ReturnType<typeof readerKeyIntent> | ReturnType<typeof readerPointerIntent>) {
  if (intent === 'previous') return { type: 'command', command: { type: 'previous' } } as const;
  if (intent === 'next') return { type: 'command', command: { type: 'next' } } as const;
  if (intent === 'first') return { type: 'command', command: { type: 'first' } } as const;
  if (intent === 'last') return { type: 'command', command: { type: 'last' } } as const;
  if (intent === 'escape') return { type: 'escape' } as const;
  if (intent === 'toggle-controls') return { type: 'toggle-controls' } as const;
  return null;
}


export function deserializeReadiumLocator(value: ReaderOpaqueLocator): Locator {
  try {
    const locator = Locator.deserialize(value);
    if (!locator) throw new Error('Readium returned no Locator');
    return locator;
  } catch (cause) {
    throw new Error(LOCATION_RESTORE_FAILED, { cause });
  }
}

function location(locator: Locator, format: ReflowableLocation['format'], navigator: EpubNavigator | null): ReflowableLocation {
  const fragments = Array.isArray(locator.locations.fragments) ? locator.locations.fragments : [];
  const cfi = fragments.find((value) => value.startsWith('epubcfi('));
  const spineIndex = navigator?.publication.readingOrder.items.findIndex((item) => samePublicationResource(item.href, locator.href)) ?? -1;
  return { kind: 'reflowable', format, href: locator.href, ...(cfi ? { cfi } : {}), ...(spineIndex >= 0 ? { spineIndex } : {}), ...(typeof locator.locations.progression === 'number' ? { resourceProgression: locator.locations.progression } : {}), ...(typeof locator.locations.position === 'number' ? { position: locator.locations.position } : {}), ...(locator.text?.highlight ? { textQuote: { exact: locator.text.highlight, ...(locator.text.before ? { prefix: locator.text.before } : {}), ...(locator.text.after ? { suffix: locator.text.after } : {}) } } : {}) };
}

function locatorAtStartup(target: Readonly<{ position: Locator; fragment: string }> | null) {
  if (!target) return null;
  if (!target.fragment) return target.position;
  return new Locator({
    href: `${bareHref(target.position.href)}#${target.fragment}`,
    type: target.position.type,
    ...(target.position.title ? { title: target.position.title } : {}),
    locations: target.position.locations,
    ...(target.position.text ? { text: target.position.text } : {})
  });
}

export class ReadiumWebReaderAdapter extends ReaderAdapterBase implements ReaderAdapter, ReaderInteractiveAdapter {
  private navigator: EpubNavigator | null = null;
  private preferences: ReaderPreferences | null = null;
  private source: Extract<ReaderAdapterOpenContext['source'], { kind: 'reflowable' }> | null = null;
  private format: ReflowableLocation['format'] = 'epub';
  private latestLocator: Locator | null = null;
  private latestPosition: ReaderPositionReport | null = null;
  private captureEnabled = false;
  private pendingFrameCapture: {
    window: Window;
    requestId: number;
    completesPresentation: boolean;
    reportsLocation: boolean;
  } | null = null;
  private positions: Locator[] = [];
  private startLocator: Locator | null = null;
  private locationOperation: OperationToken | null = null;
  private presentationOperation: OperationToken | null = null;
  private resolvedFont: EpubFontResolution | null = null;
  private resolvedFontFamily: ReaderPreferences['epub']['fontFamily'] | null = null;
  private fontController: AbortController | null = null;
  private viewportObserver: ResizeObserver | null = null;
  private viewportSignature = '';
  private resizeSequence = 0;
  private resizePresentationInFlight = false;
  private closePublication: (() => void) | null = null;
  private readonly keyboardNavigation = new ReaderKeyboardNavigationController();
  private readonly frameControllers = new Set<AbortController>();
  private readonly bridgedDocuments = new WeakMap<Document, AbortController>();
  constructor(private readonly options: ReadiumAdapterOptions) { super(); }
  getInteractionPolicy(): ReaderInteractionPolicy { return { horizontalPaging: 'adapter-interactive' }; }
  getCapabilities() { return this.navigator ? capabilities(this.navigator) : DEFAULT_CAPABILITIES; }

  async open(context: ReaderAdapterOpenContext) {
    const generation = this.beginSession(context.sessionId, context.operation);
    this.locationOperation = context.operation;
    if (context.source.kind !== 'reflowable') throw new Error('READIUM_SOURCE_INVALID');
    this.source = context.source;
    this.preferences = context.preferences; this.format = context.source.sourceFormat;
    this.emit({ type: 'phase-changed', phase: 'loading-font' }, context.operation);
    await this.resolveFont(context.preferences, context.signal);
    this.emit({ type: 'phase-changed', phase: 'loading-content' }, context.operation);
    const opened = await openReadiumPublication(
      this.options.publicationBlob,
      context.source.sourceFormat,
      this.options.publicationTitle,
      context.preferences.epub.readingProgression,
      context.preferences.epub.writingMode,
      context.signal
    );
    this.closePublication = opened.close;
    this.assertActive(generation, context.signal);
    this.positions = opened.positions;
    const handlePointer: EpubNavigatorListeners['tap'] = (event) => this.onPointer(event);
    const listeners: EpubNavigatorListeners = {
      frameLoaded: (window) => this.onFrameLoaded(window),
      positionChanged: (value) => this.onPositionChanged(value),
      timelineItemChanged: () => undefined,
      tap: handlePointer,
      click: handlePointer,
      zoom: () => undefined,
      miscPointer: () => undefined,
      scroll: () => undefined,
      customEvent: () => undefined,
      handleLocator: (locator) => this.onUnhandledLocator(locator),
      textSelected: () => undefined,
      contentProtection: () => undefined,
      contextMenu: () => undefined,
      peripheral: () => undefined
    };
    // Only the engine-owned opaque Locator is used for restoration. The
    // presentation projection and legacy domain location never navigate.
    let requestedRestoreLocator: Locator | null = null;
    if (context.initialPosition) {
      try {
        requestedRestoreLocator = deserializeReadiumLocator(context.initialPosition.locator);
      } catch {
        requestedRestoreLocator = null;
      }
    }
    const requestedHref = context.initialLocation?.kind === 'reflowable'
      ? context.initialLocation.href
      : null;
    const startupTargets = resolveReadiumStartupTargets(
      opened.publication.readingOrder.items,
      opened.positions,
      this.options.initialHref,
      requestedHref
    );
    this.startLocator = locatorAtStartup(startupTargets.start);
    const startupLocator = locatorAtStartup(startupTargets.initial);
    const restoreInitial = requestedRestoreLocator
      ? opened.positions.find((position) => samePublicationResource(position.href, requestedRestoreLocator.href)) ?? null
      : startupLocator ?? opened.positions[0];
    const initial = restoreInitial ?? undefined;
    this.navigator = new EpubNavigator(this.options.container, opened.publication, listeners, opened.positions, initial, {
      preferences: createReadiumEpubPreferences(context.preferences, this.viewportWidth(), this.resolvedFont ?? undefined),
      defaults: { optimalLineLength: 66 }
    });
    await this.navigator.load(); this.assertActive(generation, context.signal);
    this.applyPresentationToLoadedFrames();
    this.observeViewport();
    if (requestedRestoreLocator) {
      await this.navigateToPosition(this.navigator, requestedRestoreLocator).catch(() => false);
      this.assertActive(generation, context.signal);
    } else if (requestedHref && startupLocator) {
      // EpubNavigator can bootstrap its iframe at the publication start even
      // when a different initial Locator is provided. Re-issue the explicit
      // chapter intent after load so both another resource and an HTML anchor
      // are applied before the reader becomes ready.
      await this.navigateToPosition(this.navigator, startupLocator);
      this.assertActive(generation, context.signal);
    }
    this.captureEnabled = true;
    this.capturePosition(this.navigator.currentLocator);
    // A restored opaque Locator must never be written back merely because the
    // publication was opened. A genuinely new session at the publication
    // start still reports Readium's first settled location so it can establish
    // its first v5 position record.
    this.scheduleFrameCapture(
      this.options.container.ownerDocument.defaultView ?? window,
      false,
      requestedRestoreLocator === null
    );
    const navigation = readiumNavigationEntries(opened.publication);
    if (navigation.length > 0) this.emit({ type: 'navigation-changed', items: navigation }, context.operation);
    this.emit({
      type: 'ready',
      capabilities: capabilities(this.navigator),
      location: this.latestLocator ? location(this.latestLocator, this.format, this.navigator) : null,
      position: this.latestPosition
    }, context.operation);
    this.emit({ type: 'phase-changed', phase: null }, context.operation);
  }

  private scheduleFrameCapture(
    window: Window,
    completesPresentation = false,
    reportsLocation = true
  ) {
    const shouldCompletePresentation = completesPresentation
      || this.pendingFrameCapture?.completesPresentation === true;
    const shouldReportLocation = reportsLocation
      && this.pendingFrameCapture?.reportsLocation !== false;
    if (this.pendingFrameCapture) {
      this.pendingFrameCapture.window.cancelAnimationFrame(this.pendingFrameCapture.requestId);
    }
    const afterLayout = () => {
      this.pendingFrameCapture = null;
      if (this.navigator) {
        if (shouldReportLocation) this.onPositionChanged(this.navigator.currentLocator);
        else this.capturePosition(this.navigator.currentLocator);
      }
      if (shouldCompletePresentation) this.presentationOperation = null;
    };
    const firstRequestId = window.requestAnimationFrame(() => {
      const secondRequestId = window.requestAnimationFrame(afterLayout);
      this.pendingFrameCapture = {
        window,
        requestId: secondRequestId,
        completesPresentation: shouldCompletePresentation,
        reportsLocation: shouldReportLocation
      };
    });
    this.pendingFrameCapture = {
      window,
      requestId: firstRequestId,
      completesPresentation: shouldCompletePresentation,
      reportsLocation: shouldReportLocation
    };
  }

  private onFrameLoaded(window: Window) {
    if (this.preferences) {
      applyReadiumDocumentPresentation(
        window.document,
        this.preferences,
        this.resolvedFont ?? undefined
      );
    }
    this.bindFrameKeyboard(window.document);
    this.options.container.dataset.readerPageError = this.hasUnreadablePage()
      ? 'resource-unreadable'
      : '';
    this.scheduleFrameCapture(window);
  }

  private isScrollMode() {
    return this.preferences?.epub.writingMode === 'vertical' || this.preferences?.epub.flow === 'scrolled';
  }

  private currentContentDocument() {
    const frames = Array.from(this.options.container.querySelectorAll('iframe'));
    const visible = frames.find((frame) => {
      if (!frame.contentDocument) return false;
      const bounds = frame.getBoundingClientRect();
      const viewport = this.options.container.getBoundingClientRect();
      return bounds.right > viewport.left && bounds.left < viewport.right
        && bounds.bottom > viewport.top && bounds.top < viewport.bottom;
    });
    return visible?.contentDocument ?? frames.find((frame) => frame.contentDocument)?.contentDocument ?? null;
  }

  private navigationAnimationEnabled() {
    const ownerWindow = this.options.container.ownerDocument.defaultView ?? window;
    return this.preferences?.epub.pageTurnAnimation === 'slide'
      && !ownerWindow.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
  }

  private hasUnreadablePage() {
    return Array.from(this.options.container.querySelectorAll('iframe')).some((frame) => {
      try {
        return frame.contentDocument?.body?.dataset.shukuResourceError === 'RESOURCE_UNREADABLE';
      } catch {
        return false;
      }
    });
  }

  private bindFrameKeyboard(document: Document) {
    this.bridgedDocuments.get(document)?.abort();
    const controller = new AbortController();
    this.bridgedDocuments.set(document, controller);
    this.frameControllers.add(controller);
    controller.signal.addEventListener('abort', () => this.frameControllers.delete(controller), { once: true });
    document.defaultView?.addEventListener('pagehide', () => controller.abort(), { once: true, signal: controller.signal });
    document.documentElement.dataset.shukuInputBridge = 'ready';
    this.options.container.dataset.readerInputBridge = 'ready';
    this.bindFramePointer(document, controller.signal);
    document.addEventListener('keydown', (event) => {
      if (
        !this.options.onInputIntent
        || isReaderKeyboardControlTarget(event.target, event.key)
        || hasActiveTextSelection(document.getSelection())
      ) return;
      const navigator = this.navigator;
      const intent = commandForInput(readerKeyIntent(event, navigator?.readingProgression === 'rtl' ? 'rtl' : 'ltr', {
        keyboardPageTurn: this.preferences?.interaction.keyboardPageTurn,
        volumeKeyPageTurn: this.preferences?.interaction.volumeKeyPageTurn
      }));
      if (!intent) return;
      event.preventDefault();
      this.keyboardNavigation.keyDown(event, () => this.options.onInputIntent?.(intent));
    }, { signal: controller.signal });
    document.addEventListener('keyup', (event) => {
      this.keyboardNavigation.keyUp(event);
    }, { signal: controller.signal });
  }

  private bindFramePointer(document: Document, signal: AbortSignal) {
    type PointerGesture = {
      pointerId: number;
      startX: number;
      startY: number;
      maximumDistance: number;
      blocked: boolean;
      multiplePointers: boolean;
    };
    let gesture: PointerGesture | null = null;
    const updateDistance = (event: PointerEvent, current: PointerGesture) => {
      current.maximumDistance = Math.max(
        current.maximumDistance,
        Math.hypot(event.clientX - current.startX, event.clientY - current.startY)
      );
    };
    document.addEventListener('pointerdown', (event) => {
      if (!event.isPrimary) {
        if (gesture) gesture.multiplePointers = true;
        return;
      }
      gesture = {
        pointerId: event.pointerId,
        startX: event.clientX,
        startY: event.clientY,
        maximumDistance: 0,
        blocked: isReaderControlTarget(event.target) || hasActiveTextSelection(document.getSelection()),
        multiplePointers: false
      };
    }, { capture: true, signal });
    document.addEventListener('pointermove', (event) => {
      if (!gesture || event.pointerId !== gesture.pointerId) return;
      updateDistance(event, gesture);
    }, { capture: true, signal });
    document.addEventListener('pointerup', (event) => {
      const current = gesture;
      if (!current || event.pointerId !== current.pointerId) return;
      gesture = null;
      updateDistance(event, current);
      if (current.multiplePointers) {
        event.preventDefault();
        event.stopImmediatePropagation();
        return;
      }
      if (
        current.blocked
        || current.maximumDistance > 12
        || isReaderControlTarget(event.target)
      ) return;

      // Readium treats a mouse movement over one pixel as a drag and returns
      // before preventing native selection. Clear only a selection created by
      // this short tap; deliberate drags and pre-existing selections remain.
      const selection = document.getSelection();
      if (hasActiveTextSelection(selection)) selection?.removeAllRanges();
      event.preventDefault();
      event.stopImmediatePropagation();
      this.onFramePointer(event, document);
    }, { capture: true, signal });
    document.addEventListener('pointercancel', () => {
      gesture = null;
    }, { capture: true, signal });
  }

  private onFramePointer(event: PointerEvent, document: Document) {
    if (!this.options.onInputIntent || !this.navigator) return;
    const frameWindow = document.defaultView;
    const frame = frameWindow?.frameElement;
    if (!(frame instanceof HTMLElement) || !frameWindow) return;
    const intent = commandForInput(readerFramePointerIntent(
      event.clientX,
      event.clientY,
      Math.max(1, frameWindow.innerWidth),
      Math.max(1, frameWindow.innerHeight),
      frame.getBoundingClientRect(),
      this.options.container.getBoundingClientRect(),
      this.navigator.readingProgression === 'rtl' ? 'rtl' : 'ltr',
      this.preferences?.interaction.tapZones
    ));
    if (intent) void this.options.onInputIntent(intent);
  }

  private onPointer(event: Parameters<EpubNavigatorListeners['tap']>[0]) {
    // Readium prevents the originating pointer event before emitting every
    // FrameClickEvent, so defaultPrevented is expected here.
    if (event.doNotDisturb) return true;
    if (!this.options.onInputIntent || !this.navigator) return false;
    const ownerWindow = this.options.container.ownerDocument.defaultView;
    const devicePixelRatio = ownerWindow?.devicePixelRatio ?? 1;
    const intent = commandForInput(readerPointerIntent(
      event.x,
      event.y,
      Math.max(1, this.options.container.clientWidth * devicePixelRatio),
      Math.max(1, this.options.container.clientHeight * devicePixelRatio),
      this.navigator.readingProgression === 'rtl' ? 'rtl' : 'ltr',
      this.preferences?.interaction.tapZones
    ));
    if (!intent) return true;
    void this.options.onInputIntent(intent);
    return true;
  }

  private onUnhandledLocator(locator: Locator) {
    const href = locator.href.trim();
    if (isAllowedReadiumExternalHref(href)) {
      this.emit({ type: 'external-link', href }, this.locationOperation ?? this.currentOperation());
    }
    // Unknown and unsafe schemes are deliberately consumed rather than opened by the publication.
    return true;
  }

  private positionReport(value: Locator): ReaderPositionReport {
    const totalProgression = readiumTotalProgression(value, this.positions);
    const serialized = value.serialize();
    const href = typeof serialized.href === 'string' ? serialized.href : null;
    const navigation = this.navigator ? readiumNavigationEntries(this.navigator.publication) : [];
    const chapter = href
      ? navigation.find((item) => item.href && samePublicationResource(item.href, href))
      : undefined;
    return {
      // This is the exact object returned by Readium's public serialize().
      locator: serialized,
      presentation: {
        displayPercent: Math.max(0, Math.min(100, totalProgression * 100)),
        totalProgression: Math.max(0, Math.min(1, totalProgression)),
        currentHref: href,
        chapter: chapter ? { href: chapter.href ?? null, title: chapter.label ?? null, index: chapter.index ?? null } : null,
        page: null,
        playback: null
      }
    };
  }

  private onPositionChanged(value: Locator, _settledNavigation = false) {
    if (
      !this.captureEnabled
      || (this.resizePresentationInFlight && !_settledNavigation)
    ) return;
    const percent = this.capturePosition(value);
    const position = this.latestPosition;
    if (percent === null || !position) return;
    const operation = this.presentationOperation ?? this.locationOperation ?? this.currentOperation();
    this.emit({ type: 'location-changed', location: location(value, this.format, this.navigator), percent, position }, operation);
    if (this.navigator) this.emit({ type: 'capabilities-changed', capabilities: capabilities(this.navigator) }, operation);
    if (this.presentationOperation === operation) this.presentationOperation = null;
  }

  private capturePosition(value: Locator): number | null {
    // Error-marker resources remain navigable, but must never become progress
    // or bookmark locations. The last successfully rendered Locator stays current.
    if (this.hasUnreadablePage()) return null;
    const totalProgression = readiumTotalProgression(value, this.positions);
    this.latestLocator = value;
    this.latestPosition = this.positionReport(value);
    return totalProgression * 100;
  }

  async execute(command: ReaderCommand, context: ReaderAdapterOperationContext): Promise<ReaderCommandAck> {
    this.beginOperation(context);
    this.locationOperation = context.operation;
    const navigator = this.navigator;
    if (!navigator) return this.failOperation(context, 'READIUM_NOT_READY');
    let accepted = false;
    if (command.type === 'next' || command.type === 'previous') {
      const direction = command.type;
      if (this.isScrollMode()) {
        const document = this.currentContentDocument();
        if (!document || !this.preferences) return this.failOperation(context, 'READIUM_SCROLL_VIEWPORT_UNAVAILABLE');
        const result = await advanceScrollViewport({
          document,
          direction,
          writingMode: this.preferences.epub.writingMode,
          readingProgression: this.preferences.epub.readingProgression,
          animated: this.navigationAnimationEnabled()
        });
        accepted = result === 'moved'
          ? true
          : result === 'boundary' && await this.navigateAdjacentScrollResource(navigator, direction);
      } else if (direction === 'next') {
        if (!navigator.canGoForward) accepted = await Promise.resolve(this.options.onEndOfResource?.() ?? false);
        else {
          accepted = await this.navigateWithCallback(navigator, (cb) => navigator.goForward(false, cb));
          if (!accepted && !navigator.canGoForward) accepted = await Promise.resolve(this.options.onEndOfResource?.() ?? false);
        }
      } else {
        accepted = await this.navigateWithCallback(navigator, (cb) => navigator.goBackward(false, cb));
      }
    } else if (command.type === 'first') accepted = await this.navigateToPosition(navigator, this.startLocator ?? this.positions[0] ?? null);
    else if (command.type === 'last') {
      const last = this.positions.at(-1) ?? null;
      accepted = await this.navigateToPosition(navigator, last);
    } else if (command.type === 'go-to-progress') {
      const target = command.progression <= 0
        ? this.startLocator ?? this.positions[0] ?? null
        : closestReadiumPosition(this.positions, command.progression);
      accepted = await this.navigateToPosition(navigator, target);
    } else if (command.type === 'go-to-index') {
      const link = Number.isInteger(command.index) && command.index >= 0
        ? navigator.publication.readingOrder.items[command.index]
        : undefined;
      accepted = link ? await this.navigateToPosition(navigator, link.locator) : false;
    }
    else if (command.type === 'go-to-position') {
      const readium = deserializeReadiumLocator(command.position.locator);
      accepted = await this.navigateToPosition(navigator, readium);
      if (!accepted) throw new Error(LOCATION_RESTORE_FAILED);
    } else if (command.type === 'go-to-href') {
      accepted = await this.navigateToHref(navigator, command.href);
    }
    return this.ack(context.operation, accepted, this.latestLocator ? {
      location: location(this.latestLocator, this.format, this.navigator),
      position: this.latestPosition ?? undefined
    } : {});
  }

  private async navigateAdjacentScrollResource(navigator: EpubNavigator, direction: 'previous' | 'next') {
    const readingOrder = navigator.publication.readingOrder.items;
    const currentIndex = readingOrder.findIndex((link) => (
      samePublicationResource(link.href, navigator.currentLocator.href)
    ));
    if (currentIndex < 0) return false;
    const target = readingOrder[currentIndex + (direction === 'next' ? 1 : -1)];
    if (!target) {
      return direction === 'next'
        ? Promise.resolve(this.options.onEndOfResource?.() ?? false)
        : false;
    }
    const accepted = await this.navigateToPosition(
      navigator,
      new Locator({
        href: target.href,
        type: target.type ?? navigator.currentLocator.type,
        title: target.title,
        locations: new LocatorLocations({ progression: readerAdjacentResourceProgression(direction) })
      })
    );
    if (!accepted || !this.preferences) return false;
    const document = this.currentContentDocument();
    if (!document || !await positionScrollResourceEdge({
      document,
      direction,
      writingMode: this.preferences.epub.writingMode,
      readingProgression: this.preferences.epub.readingProgression
    })) return false;
    return true;
  }

  private async navigateToPosition(navigator: EpubNavigator, target: Locator | null) {
    if (!target) return false;
    return this.navigateWithCallback(navigator, (callback) => navigator.go(target, false, callback));
  }

  private async navigateWithCallback(
    navigator: EpubNavigator,
    run: (callback: (accepted: boolean) => void) => void
  ) {
    const accepted = await callbackNavigation(run);
    if (!accepted) return false;
    const ownerWindow = this.options.container.ownerDocument.defaultView ?? window;
    await new Promise<void>((resolve) => {
      ownerWindow.requestAnimationFrame(() => ownerWindow.requestAnimationFrame(() => resolve()));
    });
    if (navigator === this.navigator) {
      // Readium can finish its public navigation callback before its recycled
      // iframe emits a dependable Locator. Capture the now-visible document
      // before acknowledging the command so Shell chapter state cannot lag.
      this.onPositionChanged(navigator.currentLocator, true);
    }
    return true;
  }

  private async navigateToHref(navigator: EpubNavigator, href: string) {
    const candidate = href.trim();
    if (!candidate) return false;
    const currentHref = this.latestLocator?.href ?? navigator.currentLocator.href;
    const resolved = resolveReadiumHref(candidate, currentHref);
    const publication = navigator.publication;
    const match = [candidate, resolved]
      .map((value) => publication.linkWithHref(value))
      .find((link): link is Link => Boolean(link))
      ?? findReadiumPublicationResource(publication.readingOrder.items, [candidate, resolved]);
    if (!match) {
      if (isAllowedReadiumExternalHref(candidate)) {
        this.emit({ type: 'external-link', href: candidate }, this.locationOperation ?? this.currentOperation());
        return true;
      }
      return false;
    }
    const fragment = hrefFragment(resolved) || hrefFragment(candidate);
    const target = new Locator({ href: `${bareHref(match.href)}${fragment}`, type: match.type ?? navigator.currentLocator.type });
    return this.navigateToPosition(navigator, target);
  }

  async applyPreferences(preferences: ReaderPreferences, context: ReaderAdapterOperationContext) {
    this.beginOperation(context);
    const navigator = this.navigator;
    if (!navigator) return this.failOperation(context, 'READIUM_NOT_READY');
    const textLayoutChanged = this.preferences?.epub.writingMode !== preferences.epub.writingMode
      || this.preferences?.epub.readingProgression !== preferences.epub.readingProgression;
    if (textLayoutChanged && navigator.publication.metadata.layout !== Layout.fixed) {
      return this.rebuildForTextLayout(preferences, context);
    }
    this.presentationOperation = context.operation;
    try {
      await this.resolveFont(preferences, context.signal);
      if (context.signal.aborted) throw new DOMException('The operation was aborted', 'AbortError');
      this.preferences = preferences;
      await navigator.submitPreferences(new EpubPreferences(
        createReadiumEpubPreferences(preferences, this.viewportWidth(), this.resolvedFont ?? undefined)
      ));
      if (context.signal.aborted) throw new DOMException('The operation was aborted', 'AbortError');
      this.applyPresentationToLoadedFrames();
      this.scheduleFrameCapture(this.options.container.ownerDocument.defaultView ?? window, true);
      return this.ack(context.operation, true);
    } catch (reason) {
      if (this.presentationOperation === context.operation) {
        this.presentationOperation = null;
      }
      throw reason;
    }
  }

  private async rebuildForTextLayout(preferences: ReaderPreferences, context: ReaderAdapterOperationContext) {
    const previous = this.preferences;
    const source = this.source;
    const navigator = this.navigator;
    if (!previous || !source || !navigator) return this.failOperation(context, 'READIUM_NOT_READY');
    const current = navigator.currentLocator;
    const initialLocation: ReflowableLocation = {
      kind: 'reflowable',
      format: this.format,
      href: current.href,
      resourceProgression: current.locations.progression
    };
    const initialPosition = this.latestPosition;
    this.presentationOperation = context.operation;
    await this.closeActiveNavigator();
    try {
      this.assertActive(this.currentGeneration(), context.signal);
      await this.open({
        sessionId: context.operation.sessionId,
        operation: context.operation,
        signal: context.signal,
        source,
        preferences,
        initialLocation,
        initialPosition
      });
      return this.ack(context.operation, true);
    } catch (reason) {
      await this.closeActiveNavigator();
      if (this.isActive(this.currentGeneration(), context.signal)) {
        try {
          await this.open({
            sessionId: context.operation.sessionId,
            operation: context.operation,
            signal: context.signal,
            source,
            preferences: previous,
            initialLocation,
            initialPosition
          });
          return this.failOperation(context, 'READER_PREFERENCES_ENGINE_FAILED');
        } catch {
          await this.closeActiveNavigator();
        }
      }
      throw reason;
    }
  }

  private async closeActiveNavigator() {
    if (this.pendingFrameCapture) {
      this.pendingFrameCapture.window.cancelAnimationFrame(this.pendingFrameCapture.requestId);
      this.pendingFrameCapture = null;
    }
    this.frameControllers.forEach((controller) => controller.abort());
    this.frameControllers.clear();
    this.viewportObserver?.disconnect();
    this.viewportObserver = null;
    const navigator = this.navigator;
    this.navigator = null;
    this.closePublication?.();
    this.closePublication = null;
    this.options.container.replaceChildren();
    if (navigator) await navigator.destroy();
  }

  private viewportWidth() {
    // Readium mutates the mount element's inline width to the effective page
    // measure. The parent remains the actual reader viewport and must stay the
    // source for responsive constraints; reading the mount here makes a 600px
    // preference rebound to Readium's default line length on the next resize.
    const viewport = this.options.container.parentElement ?? this.options.container;
    return Math.max(1, Math.round(
      viewport.getBoundingClientRect().width
      || viewport.clientWidth
      || this.options.container.ownerDocument.defaultView?.innerWidth
      || 1
    ));
  }

  private async resolveFont(preferences: ReaderPreferences, signal: AbortSignal) {
    if (this.resolvedFont && this.resolvedFontFamily === preferences.epub.fontFamily) return;
    this.fontController?.abort();
    const controller = new AbortController();
    this.fontController = controller;
    const combinedSignal = typeof AbortSignal.any === 'function'
      ? AbortSignal.any([signal, controller.signal])
      : signal;
    const ownerDocument = this.options.container.ownerDocument;
    const ownerWindow = ownerDocument.defaultView;
    const next = await resolveEpubFont(preferences.epub.fontFamily, {
      signal: combinedSignal,
      fontSet: ownerDocument.fonts,
      FontFace: ownerWindow?.FontFace,
      document: ownerDocument,
      createObjectURL: (blob) => URL.createObjectURL(blob),
      revokeObjectURL: (url) => URL.revokeObjectURL(url)
    });
    if (combinedSignal.aborted) {
      next.embedded?.release?.();
      throw new DOMException('The operation was aborted', 'AbortError');
    }
    this.resolvedFont?.embedded?.release?.();
    this.resolvedFont = next;
    this.resolvedFontFamily = preferences.epub.fontFamily;
    if (this.fontController === controller) this.fontController = null;
  }

  private applyPresentationToLoadedFrames() {
    const preferences = this.preferences;
    if (!preferences) return;
    const width = this.viewportWidth();
    this.options.container.querySelectorAll<HTMLIFrameElement>('iframe').forEach((frame) => {
      const document = frame.contentDocument;
      if (document) applyReadiumDocumentPresentation(document, preferences, this.resolvedFont ?? undefined);
    });
    this.viewportSignature = JSON.stringify(resolveReadiumViewportPresentation(preferences, width));
  }

  private observeViewport() {
    this.viewportObserver?.disconnect();
    if (typeof ResizeObserver === 'undefined') return;
    this.viewportObserver = new ResizeObserver(() => {
      const navigator = this.navigator;
      const preferences = this.preferences;
      if (!navigator || !preferences) return;
      const width = this.viewportWidth();
      const signature = JSON.stringify(resolveReadiumViewportPresentation(preferences, width));
      if (signature === this.viewportSignature) return;
      this.viewportSignature = signature;
      const sequence = ++this.resizeSequence;
      this.resizePresentationInFlight = true;
      void navigator.submitPreferences(new EpubPreferences(
        createReadiumEpubPreferences(preferences, width, this.resolvedFont ?? undefined)
      )).then(async () => {
        if (sequence !== this.resizeSequence || navigator !== this.navigator) return;
        this.applyPresentationToLoadedFrames();
      }).catch(() => undefined).finally(() => {
        if (sequence === this.resizeSequence) this.resizePresentationInFlight = false;
      });
    });
    this.viewportObserver.observe(this.options.container.parentElement ?? this.options.container);
  }

  async dispose() {
    if (!this.markDisposed()) return;
    this.resizeSequence += 1;
    this.resizePresentationInFlight = false;
    this.fontController?.abort();
    this.fontController = null;
    this.resolvedFont?.embedded?.release?.();
    this.resolvedFont = null;
    this.resolvedFontFamily = null;
    this.keyboardNavigation.reset();
    await this.closeActiveNavigator();
    this.positions = [];
    this.startLocator = null;
    this.latestLocator = null;
    this.latestPosition = null;
    this.locationOperation = null;
    this.presentationOperation = null;
    this.source = null;
  }
}

export function createReadiumWebReaderAdapter(options: ReadiumAdapterOptions) { return new ReadiumWebReaderAdapter(options); }
