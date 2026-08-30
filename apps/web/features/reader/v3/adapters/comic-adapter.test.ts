import assert from 'node:assert/strict';
import test from 'node:test';
import {
  DEFAULT_READER_PREFERENCES,
  READER_SAFETY_RULE_IDS,
  type OperationToken,
  type ReaderCommand
} from '@shuku/reader-core';
import { ComicReaderAdapter } from './comic-adapter';
import { readerSafetyFailure } from '../security/reader-safety-policy';

const COMIC_REVISION = `sha256:${'a'.repeat(64)}`;

type FakeListener = (event: Record<string, unknown>) => void;

class FakeElement {
  readonly dataset: Record<string, string> = {};
  readonly style: Record<string, string> = {};
  readonly children: FakeElement[] = [];
  readonly listeners = new Map<string, Set<FakeListener>>();
  readonly capturedPointers = new Set<number>();
  ownerDocument: FakeDocument;
  parentElement: FakeElement | null = null;
  clientHeight = 600;
  clientWidth = 800;
  scrollHeight = 600;
  scrollWidth = 800;
  scrollLeft = 0;
  scrollTop = 0;
  offsetHeight = 600;
  offsetTop = 0;
  textContent = '';
  src = '';
  alt = '';
  loading = '';
  complete = false;
  naturalWidth = 0;
  draggable = true;

  constructor(ownerDocument: FakeDocument) {
    this.ownerDocument = ownerDocument;
  }

  append(...nodes: FakeElement[]) {
    nodes.forEach((node) => {
      if (node.parentElement) {
        const index = node.parentElement.children.indexOf(node);
        if (index >= 0) node.parentElement.children.splice(index, 1);
      }
      node.parentElement = this;
      this.children.push(node);
    });
  }

  replaceChildren(...nodes: FakeElement[]) {
    this.children.forEach((child) => {
      child.parentElement = null;
    });
    this.children.splice(0);
    this.append(...nodes);
  }

  remove() {
    if (!this.parentElement) return;
    const index = this.parentElement.children.indexOf(this);
    if (index >= 0) this.parentElement.children.splice(index, 1);
    this.parentElement = null;
  }

  addEventListener(type: string, listener: FakeListener) {
    const listeners = this.listeners.get(type) ?? new Set<FakeListener>();
    listeners.add(listener);
    this.listeners.set(type, listeners);
  }

  removeEventListener(type: string, listener: FakeListener) {
    this.listeners.get(type)?.delete(listener);
  }

  dispatch(type: string, event: Record<string, unknown>) {
    this.listeners.get(type)?.forEach((listener) => listener.call(this, event));
  }

  setAttribute() {}

  closest() {
    return null;
  }

  setPointerCapture(pointerId: number) {
    this.capturedPointers.add(pointerId);
  }

  hasPointerCapture(pointerId: number) {
    return this.capturedPointers.has(pointerId);
  }

  releasePointerCapture(pointerId: number) {
    this.capturedPointers.delete(pointerId);
  }
}

class FakeDocument {
  readonly documentElement = { lang: 'zh-CN' };
  defaultView: {
    HTMLImageElement?: typeof HTMLImageElement;
    IntersectionObserver?: typeof IntersectionObserver;
    ResizeObserver?: typeof ResizeObserver;
    requestAnimationFrame?: (callback: FrameRequestCallback) => number;
  } | null = null;
  createElement() {
    return new FakeElement(this);
  }
}
class FakeIntersectionObserver {
  static latest: FakeIntersectionObserver | null = null;
  readonly observed = new Set<FakeElement>();
  disconnected = false;
  readonly options: IntersectionObserverInit;

  constructor(
    private readonly callback: IntersectionObserverCallback,
    options: IntersectionObserverInit = {}
  ) {
    FakeIntersectionObserver.latest = this;
    this.options = options;
  }

  observe(target: Element) {
    this.observed.add(target as unknown as FakeElement);
  }

  unobserve(target: Element) {
    this.observed.delete(target as unknown as FakeElement);
  }

  disconnect() {
    this.disconnected = true;
    this.observed.clear();
  }

  trigger(target: FakeElement) {
    this.callback([{
      isIntersecting: true,
      target: target as unknown as Element
    } as IntersectionObserverEntry], this as unknown as IntersectionObserver);
  }
}
class FakeResizeObserver {
  static latest: FakeResizeObserver | null = null;
  disconnected = false;

  constructor(private readonly callback: ResizeObserverCallback) {
    FakeResizeObserver.latest = this;
  }

  observe() {}

  disconnect() {
    this.disconnected = true;
  }

  trigger() {
    this.callback([], this as unknown as ResizeObserver);
  }
}

class FakeAbortSignal {
  aborted = false;
  readonly abortListeners = new Set<EventListenerOrEventListenerObject>();

  addEventListener(type: string, listener: EventListenerOrEventListenerObject) {
    if (type === 'abort') this.abortListeners.add(listener);
  }

  removeEventListener(type: string, listener: EventListenerOrEventListenerObject) {
    if (type === 'abort') this.abortListeners.delete(listener);
  }

  abort() {
    if (this.aborted) return;
    this.aborted = true;
    const event = new Event('abort');
    Array.from(this.abortListeners).forEach((listener) => {
      if (typeof listener === 'function') listener(event);
      else listener.handleEvent(event);
    });
  }
}

function operation(sequence: number, kind: OperationToken['kind'] = 'navigation'): OperationToken {
  return { sessionId: 'comic-session', kind, sequence };
}

function pointer(target: FakeElement, pointerId: number, clientX: number, timeStamp: number) {
  const event = {
    target,
    pointerId,
    clientX,
    clientY: 300,
    timeStamp,
    isPrimary: true,
    button: 0,
    cancelable: true,
    defaultPrevented: false,
    propagationStopped: false,
    preventDefault() {
      event.defaultPrevented = true;
    },
    stopPropagation() {
      event.propagationStopped = true;
    }
  };
  return event;
}

async function waitFor(predicate: () => boolean, timeoutMs = 1_000) {
  const startedAt = Date.now();
  while (!predicate()) {
    if (Date.now() - startedAt >= timeoutMs) throw new Error('timed out waiting for comic navigation');
    await new Promise<void>((resolve) => setTimeout(resolve, 5));
  }
}


test('comic adapter commits programmatic and pointer navigation once while reusing the track slots', async () => {
  const ownerDocument = new FakeDocument();
  const container = new FakeElement(ownerDocument);
  let sequence = 1;
  let adapter!: ComicReaderAdapter;
  const events: Array<{ type: string; location?: { kind: string; pageIndex?: number } }> = [];
  adapter = new ComicReaderAdapter({
    container: container as unknown as HTMLElement,
    revision: COMIC_REVISION,
    initialPages: [0, 1, 2].map((pageIndex) => ({ pageIndex, resourceHref: `pages/${pageIndex}`, width: 600, height: 900 })),
    onInputIntent: (intent) => {
      if (intent.type !== 'command') return;
      return adapter.execute(intent.command as ReaderCommand, {
        operation: operation(++sequence),
        signal: new AbortController().signal
      }).then((ack) => ack.accepted);
    }
  });
  adapter.subscribe((event) => {
    if (event.type === 'location-changed') events.push(event);
  });

  await adapter.open({
    sessionId: 'comic-session',
    operation: operation(sequence, 'bootstrap'),
    signal: new AbortController().signal,
    source: {
      bookId: 'book-1',
      kind: 'comic',
      sourceFormat: 'cbz',
      comicManifestUrl: '/api/reader/v4/resources/resource-1/comic/manifest',
      comicPageUrlTemplate: '/api/reader/v4/resources/resource-1/comic/pages/{pageIndex}',
      contentUrl: '/comic',
      resourceId: 'resource-1',
      totalPages: 3
    },
    initialLocation: null,
    preferences: {
      ...DEFAULT_READER_PREFERENCES,
      appearance: { ...DEFAULT_READER_PREFERENCES.appearance },
      epub: { ...DEFAULT_READER_PREFERENCES.epub },
      comic: {
        ...DEFAULT_READER_PREFERENCES.comic,
        pageTurnAnimation: 'off'
      },
      pdf: { ...DEFAULT_READER_PREFERENCES.pdf }
    }
  });

  const viewport = container.children[0];
  const track = viewport.children[0];
  const currentSlot = track.children[1];
  const nextSlot = track.children[2];
  events.splice(0);

  const programmatic = await adapter.execute({ type: 'next' }, {
    operation: operation(++sequence),
    signal: new AbortController().signal
  });

  assert.equal(programmatic.accepted, true);
  assert.equal(adapter.getViewModel().currentPage, 1);
  assert.equal(container.children[0], viewport);
  assert.equal(track.children[1], nextSlot);
  assert.equal(track.children[0], currentSlot);
  assert.deepEqual(events.map((event) => event.location?.pageIndex), [1]);

  events.splice(0);
  viewport.dispatch('pointerdown', pointer(viewport, 7, 650, 100));
  const releaseEvent = pointer(viewport, 7, 80, 150);
  viewport.dispatch('pointerup', releaseEvent);
  await waitFor(() => adapter.getViewModel().currentPage === 2);
  const compatibilityClick = pointer(viewport, 7, 80, 151);
  viewport.dispatch('click', compatibilityClick);

  assert.equal(container.children[0], viewport);
  assert.deepEqual(events.map((event) => event.location?.pageIndex), [2]);
  assert.equal(releaseEvent.defaultPrevented, true);
  assert.equal(releaseEvent.propagationStopped, true);
  assert.equal(compatibilityClick.defaultPrevented, true);
  assert.equal(compatibilityClick.propagationStopped, true);
  assert.equal(adapter.getInteractionPolicy().horizontalPaging, 'adapter-interactive');

  adapter.dispose();
});

test('comic navigation promotes immediately while the native image is still loading', async () => {
  const ownerDocument = new FakeDocument();
  const container = new FakeElement(ownerDocument);
  let sequence = 1;
  const adapter = new ComicReaderAdapter({
    container: container as unknown as HTMLElement,
    revision: COMIC_REVISION,
    initialPages: [0, 1].map((pageIndex) => ({ pageIndex, resourceHref: `pages/${pageIndex}`, width: 600, height: 900 }))
  });

  await adapter.open({
    sessionId: 'comic-session',
    operation: operation(sequence, 'bootstrap'),
    signal: new AbortController().signal,
    source: {
      bookId: 'book-1',
      kind: 'comic',
      sourceFormat: 'cbz',
      comicManifestUrl: '/api/reader/v4/resources/resource-1/comic/manifest',
      comicPageUrlTemplate: '/api/reader/v4/resources/resource-1/comic/pages/{pageIndex}',
      contentUrl: '/comic',
      resourceId: 'resource-1',
      totalPages: 2
    },
    initialLocation: null,
    preferences: DEFAULT_READER_PREFERENCES
  });
  const locationPages: number[] = [];
  adapter.subscribe((event) => {
    if (event.type === 'location-changed' && event.location.kind === 'comic') {
      locationPages.push(event.location.pageIndex);
    }
  });
  locationPages.splice(0);
  const acknowledged = await adapter.execute({ type: 'next' }, {
    operation: operation(++sequence),
    signal: new AbortController().signal
  });
  assert.equal(acknowledged.accepted, true);
  assert.equal(adapter.getViewModel().currentPage, 1);
  const currentSlot = container.children[0].children[0].children[1];
  const pageSlot = currentSlot.children[0].children[0];
  const image = pageSlot.children[0];
  assert.equal(pageSlot.children[1].textContent, '加载中');
  assert.equal(image.style.visibility, 'hidden');
  assert.deepEqual(locationPages, [1]);

  image.dispatch('load', {});
  assert.equal(image.style.visibility, 'visible');
  assert.equal(pageSlot.children.length, 1);
  assert.deepEqual(locationPages, [1]);
  adapter.dispose();
});

test('comic policy blocks one unsafe page without requesting it or rejecting the publication', async () => {
  const ownerDocument = new FakeDocument();
  const container = new FakeElement(ownerDocument);
  let pageRequests = 0;
  const safetyError = readerSafetyFailure(READER_SAFETY_RULE_IDS.COMIC_PAGE_MIME);
  const adapter = new ComicReaderAdapter({
    container: container as unknown as HTMLElement,
    revision: COMIC_REVISION,
    initialPages: [{ pageIndex: 0, resourceHref: 'pages/0', safetyError }],
    pageUrl: () => {
      pageRequests += 1;
      return '/must-not-be-requested';
    }
  });

  await adapter.open({
    sessionId: 'comic-session',
    operation: operation(1, 'bootstrap'),
    signal: new AbortController().signal,
    source: {
      bookId: 'book-1',
      kind: 'comic',
      sourceFormat: 'cbz',
      comicManifestUrl: '/api/reader/v4/resources/resource-1/comic/manifest',
      comicPageUrlTemplate: '/api/reader/v4/resources/resource-1/comic/pages/{pageIndex}',
      contentUrl: '/comic',
      resourceId: 'resource-1',
      totalPages: 1
    },
    initialLocation: null,
    preferences: DEFAULT_READER_PREFERENCES
  });

  assert.equal(pageRequests, 0);
  assert.equal(adapter.getViewModel().status, 'ready');
  assert.equal(adapter.getViewModel().visiblePages[0]?.url, '');
  const currentSlot = container.children[0]?.children[0]?.children[1];
  const placeholder = currentSlot?.children[0]?.children[0]?.children[0];
  assert.equal(placeholder?.dataset.readerSafetyRuleId, READER_SAFETY_RULE_IDS.COMIC_PAGE_MIME);
  assert.equal(placeholder?.dataset.readerSafetyErrorCode, safetyError.code);
  adapter.dispose();
});

test('comic continuous flow keeps every lazy image mounted and only explicit navigation changes scrollTop', async () => {
  FakeIntersectionObserver.latest = null;
  const ownerDocument = new FakeDocument();
  ownerDocument.defaultView = {
    HTMLImageElement: FakeElement as unknown as typeof HTMLImageElement,
    IntersectionObserver: FakeIntersectionObserver as unknown as typeof IntersectionObserver,
    requestAnimationFrame: (callback) => {
      callback(0);
      return 1;
    }
  };
  const container = new FakeElement(ownerDocument);
  const preferences = {
    ...DEFAULT_READER_PREFERENCES,
    comic: { ...DEFAULT_READER_PREFERENCES.comic, flow: 'scrolled' as const }
  };
  const adapter = new ComicReaderAdapter({
    container: container as unknown as HTMLElement,
    revision: COMIC_REVISION,
    initialPages: [0, 1, 2].map((pageIndex) => ({ pageIndex, resourceHref: `pages/${pageIndex}`, width: 600, height: 900 }))
  });

  await adapter.open({
    sessionId: 'comic-session',
    operation: operation(1, 'bootstrap'),
    signal: new AbortController().signal,
    source: {
      bookId: 'book-1',
      kind: 'comic',
      sourceFormat: 'cbz',
      comicManifestUrl: '/api/reader/v4/resources/resource-1/comic/manifest',
      comicPageUrlTemplate: '/api/reader/v4/resources/resource-1/comic/pages/{pageIndex}',
      contentUrl: '/comic',
      resourceId: 'resource-1',
      totalPages: 3
    },
    initialLocation: null,
    preferences
  });

  const stream = container.children[1];
  assert.equal(stream.dataset.comicContinuous, 'true');
  assert.equal(stream.children.length, 3);
  const slots = stream.children;
  const images = slots.map((slot) => slot.children[0]);
  assert.deepEqual(images.map((image) => image.loading), ['lazy', 'lazy', 'lazy']);
  assert.deepEqual(images.map((image) => image.src), [
    `/api/reader/v4/resources/resource-1/comic/pages/0?imageVariant=original&revision=${encodeURIComponent(COMIC_REVISION)}`,
    `/api/reader/v4/resources/resource-1/comic/pages/1?imageVariant=original&revision=${encodeURIComponent(COMIC_REVISION)}`,
    `/api/reader/v4/resources/resource-1/comic/pages/2?imageVariant=original&revision=${encodeURIComponent(COMIC_REVISION)}`
  ]);
  const preloadObserver = FakeIntersectionObserver.latest as FakeIntersectionObserver | null;
  assert.ok(preloadObserver);
  assert.equal(preloadObserver.options.root, stream as unknown as Element);
  assert.equal(preloadObserver.options.rootMargin, '200% 0px');
  assert.equal(preloadObserver.observed.size, 3);
  preloadObserver.trigger(images[1]);
  assert.equal(images[1].loading, 'eager');
  assert.equal(images[1].dataset.comicContinuousPreloaded, 'true');
  assert.equal(preloadObserver.observed.has(images[1]), false);

  images[0].complete = true;
  images[0].naturalWidth = 600;
  images[0].dispatch('load', {});
  assert.equal(slots[0].style.minHeight, '0px');
  assert.equal(slots[0].dataset.comicContinuousLoaded, 'true');

  slots.forEach((slot, index) => {
    slot.offsetTop = index * 900;
    slot.offsetHeight = 900;
  });
  stream.scrollTop = 900;
  stream.dispatch('scroll', {});

  assert.equal(adapter.getViewModel().currentPage, 1);
  assert.equal(stream.scrollTop, 900);
  assert.equal(slots[0].children[0], images[0]);
  assert.deepEqual(slots.map((slot) => slot.children[0]), images);

  const jump = await adapter.execute({ type: 'go-to-index', index: 2 }, {
    operation: operation(2),
    signal: new AbortController().signal
  });
  assert.equal(jump.accepted, true);
  assert.equal(stream.scrollTop, 1800);
  assert.deepEqual(slots.map((slot) => slot.children[0]), images);
  adapter.dispose();
  assert.equal(preloadObserver.disconnected, true);
});

test('comic viewport resize interrupts a drag and recenters the committed spread at the new width', async () => {
  FakeResizeObserver.latest = null;
  const ownerDocument = new FakeDocument();
  ownerDocument.defaultView = {
    ResizeObserver: FakeResizeObserver as unknown as typeof ResizeObserver
  };
  const container = new FakeElement(ownerDocument);
  const adapter = new ComicReaderAdapter({
    container: container as unknown as HTMLElement,
    revision: COMIC_REVISION,
    initialPages: [0, 1].map((pageIndex) => ({ pageIndex, resourceHref: `pages/${pageIndex}`, width: 600, height: 900 })),
    onInputIntent: () => false
  });

  await adapter.open({
    sessionId: 'comic-session',
    operation: operation(1, 'bootstrap'),
    signal: new AbortController().signal,
    source: {
      bookId: 'book-1',
      kind: 'comic',
      sourceFormat: 'cbz',
      comicManifestUrl: '/api/reader/v4/resources/resource-1/comic/manifest',
      comicPageUrlTemplate: '/api/reader/v4/resources/resource-1/comic/pages/{pageIndex}',
      contentUrl: '/comic',
      resourceId: 'resource-1',
      totalPages: 2
    },
    initialLocation: null,
    preferences: DEFAULT_READER_PREFERENCES
  });

  const viewport = container.children[0];
  viewport.dispatch('pointerdown', pointer(viewport, 9, 650, 100));
  viewport.dispatch('pointermove', pointer(viewport, 9, 250, 130));
  assert.notEqual(viewport.scrollLeft, 800);
  viewport.clientWidth = 400;
  container.clientWidth = 400;
  const observer = FakeResizeObserver.latest as FakeResizeObserver | null;
  assert.ok(observer);
  observer.trigger();

  assert.equal(viewport.scrollLeft, 400);
  assert.equal(adapter.getViewModel().currentPage, 0);
  assert.equal(viewport.children[0].children[1].dataset.comicSpreadAnchor, '0');
  adapter.dispose();
  assert.equal(observer.disconnected, true);
});


test('comic signal fallback removes source listeners after abort and session bootstrap', async () => {
  const anyDescriptor = Object.getOwnPropertyDescriptor(AbortSignal, 'any');
  Object.defineProperty(AbortSignal, 'any', { configurable: true, value: undefined });
  const ownerDocument = new FakeDocument();
  const container = new FakeElement(ownerDocument);
  const adapter = new ComicReaderAdapter({
    container: container as unknown as HTMLElement,
    revision: COMIC_REVISION,
    initialPages: [0, 1, 2].map((pageIndex) => ({ pageIndex, resourceHref: `pages/${pageIndex}`, width: 600, height: 900 }))
  });
  type SignalCombiner = (first: AbortSignal, second: AbortSignal) => {
    signal: AbortSignal;
    cleanup: () => void;
  };
  const internals = adapter as unknown as { combineSignals: SignalCombiner };

  try {
    const first = new FakeAbortSignal();
    const second = new FakeAbortSignal();
    const combined = internals.combineSignals(
      first as unknown as AbortSignal,
      second as unknown as AbortSignal
    );
    assert.equal(first.abortListeners.size, 1);
    assert.equal(second.abortListeners.size, 1);
    first.abort();
    assert.equal(combined.signal.aborted, true);
    assert.equal(first.abortListeners.size, 0);
    assert.equal(second.abortListeners.size, 0);

    const originalCombine = internals.combineSignals.bind(adapter);
    let combineCount = 0;
    let cleanupCount = 0;
    internals.combineSignals = (left, right) => {
      const result = originalCombine(left, right);
      combineCount += 1;
      let cleaned = false;
      return {
        signal: result.signal,
        cleanup: () => {
          if (!cleaned) {
            cleaned = true;
            cleanupCount += 1;
          }
          result.cleanup();
        }
      };
    };

    await adapter.open({
      sessionId: 'comic-session',
      operation: operation(1, 'bootstrap'),
      signal: new AbortController().signal,
      source: {
        bookId: 'book-1',
        kind: 'comic',
        sourceFormat: 'cbz',
        comicManifestUrl: '/api/reader/v4/resources/resource-1/comic/manifest',
        comicPageUrlTemplate: '/api/reader/v4/resources/resource-1/comic/pages/{pageIndex}',
        contentUrl: '/comic',
        resourceId: 'resource-1',
        totalPages: 3
      },
      initialLocation: null,
      preferences: DEFAULT_READER_PREFERENCES
    });
    assert.equal(combineCount, 1);
    assert.equal(cleanupCount, 1);
  } finally {
    adapter.dispose();
    if (anyDescriptor) Object.defineProperty(AbortSignal, 'any', anyDescriptor);
    else Reflect.deleteProperty(AbortSignal, 'any');
  }
});
