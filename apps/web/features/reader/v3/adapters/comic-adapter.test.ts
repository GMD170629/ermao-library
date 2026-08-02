import assert from 'node:assert/strict';
import test from 'node:test';
import { DEFAULT_READER_PREFERENCES, type OperationToken, type ReaderCommand } from '@shuku/reader-core';
import { ComicReaderAdapter } from './comic-adapter';

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
  textContent = '';
  src = '';
  alt = '';
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
  defaultView: { ResizeObserver?: typeof ResizeObserver } | null = null;
  createElement() {
    return new FakeElement(this);
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


function deferred() {
  let resolve!: () => void;
  const promise = new Promise<void>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}
test('comic adapter commits programmatic and pointer navigation once while reusing the track slots', async () => {
  const ownerDocument = new FakeDocument();
  const container = new FakeElement(ownerDocument);
  let sequence = 1;
  let adapter!: ComicReaderAdapter;
  const events: Array<{ type: string; location?: { kind: string; pageIndex?: number } }> = [];
  adapter = new ComicReaderAdapter({
    container: container as unknown as HTMLElement,
    initialPages: [1, 2, 3].map((pageIndex) => ({ pageIndex, width: 600, height: 900 })),
    fetch: async () => new Response(new Blob(['page']), { status: 200 }),
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
      workId: 'work-1',
      kind: 'comic',
      contentUrl: '/comic',
      contentFingerprint: 'comic-fingerprint',
      volumeId: 'volume-1',
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
  assert.equal(adapter.getViewModel().currentPage, 2);
  assert.equal(container.children[0], viewport);
  assert.equal(track.children[1], nextSlot);
  assert.equal(track.children[0], currentSlot);
  assert.deepEqual(events.map((event) => event.location?.pageIndex), [2]);

  events.splice(0);
  viewport.dispatch('pointerdown', pointer(viewport, 7, 650, 100));
  const releaseEvent = pointer(viewport, 7, 80, 150);
  viewport.dispatch('pointerup', releaseEvent);
  await waitFor(() => adapter.getViewModel().currentPage === 3);
  const compatibilityClick = pointer(viewport, 7, 80, 151);
  viewport.dispatch('click', compatibilityClick);

  assert.equal(container.children[0], viewport);
  assert.deepEqual(events.map((event) => event.location?.pageIndex), [3]);
  assert.equal(releaseEvent.defaultPrevented, true);
  assert.equal(releaseEvent.propagationStopped, true);
  assert.equal(compatibilityClick.defaultPrevented, true);
  assert.equal(compatibilityClick.propagationStopped, true);
  assert.equal(adapter.getInteractionPolicy().horizontalPaging, 'adapter-interactive');

  adapter.dispose();
});

test('comic navigation waits for the candidate image to decode before promoting it', async () => {
  const ownerDocument = new FakeDocument();
  const container = new FakeElement(ownerDocument);
  const candidateDecode = deferred();
  let decodeCalls = 0;
  let sequence = 1;
  const adapter = new ComicReaderAdapter({
    container: container as unknown as HTMLElement,
    initialPages: [1, 2].map((pageIndex) => ({ pageIndex, width: 600, height: 900 })),
    fetch: async () => new Response(new Blob(['page']), { status: 200 }),
    decodeImage: async () => {
      decodeCalls += 1;
      if (decodeCalls > 1) await candidateDecode.promise;
    }
  });

  await adapter.open({
    sessionId: 'comic-session',
    operation: operation(sequence, 'bootstrap'),
    signal: new AbortController().signal,
    source: {
      workId: 'work-1',
      kind: 'comic',
      contentUrl: '/comic',
      contentFingerprint: 'comic-fingerprint',
      volumeId: 'volume-1',
      totalPages: 2
    },
    initialLocation: null,
    preferences: DEFAULT_READER_PREFERENCES
  });
  await waitFor(() => decodeCalls >= 2);

  const navigation = adapter.execute({ type: 'next' }, {
    operation: operation(++sequence),
    signal: new AbortController().signal
  });
  await new Promise<void>((resolve) => setImmediate(resolve));
  assert.equal(adapter.getViewModel().currentPage, 1);
  assert.equal(container.children[0].children[0].children[1].dataset.comicSpreadAnchor, '1');

  candidateDecode.resolve();
  const acknowledged = await navigation;
  assert.equal(acknowledged.accepted, true);
  assert.equal(adapter.getViewModel().currentPage, 2);
  adapter.dispose();
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
    initialPages: [1, 2].map((pageIndex) => ({ pageIndex, width: 600, height: 900 })),
    fetch: async () => new Response(new Blob(['page']), { status: 200 }),
    decodeImage: async () => undefined,
    onInputIntent: () => false
  });

  await adapter.open({
    sessionId: 'comic-session',
    operation: operation(1, 'bootstrap'),
    signal: new AbortController().signal,
    source: {
      workId: 'work-1',
      kind: 'comic',
      contentUrl: '/comic',
      contentFingerprint: 'comic-fingerprint',
      volumeId: 'volume-1',
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
  assert.equal(adapter.getViewModel().currentPage, 1);
  assert.equal(viewport.children[0].children[1].dataset.comicSpreadAnchor, '1');
  adapter.dispose();
  assert.equal(observer.disconnected, true);
});


test('comic signal fallback removes source listeners after abort and every completed page request', async () => {
  const anyDescriptor = Object.getOwnPropertyDescriptor(AbortSignal, 'any');
  Object.defineProperty(AbortSignal, 'any', { configurable: true, value: undefined });
  const ownerDocument = new FakeDocument();
  const container = new FakeElement(ownerDocument);
  const adapter = new ComicReaderAdapter({
    container: container as unknown as HTMLElement,
    initialPages: [1, 2, 3].map((pageIndex) => ({ pageIndex, width: 600, height: 900 })),
    fetch: async () => new Response(new Blob(['page']), { status: 200 }),
    decodeImage: async () => undefined
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
        workId: 'work-1',
        kind: 'comic',
        contentUrl: '/comic',
        contentFingerprint: 'comic-fingerprint',
        volumeId: 'volume-1',
        totalPages: 3
      },
      initialLocation: null,
      preferences: DEFAULT_READER_PREFERENCES
    });
    await waitFor(() => combineCount >= 3 && cleanupCount === combineCount);
    assert.equal(cleanupCount, combineCount);
  } finally {
    adapter.dispose();
    if (anyDescriptor) Object.defineProperty(AbortSignal, 'any', anyDescriptor);
    else Reflect.deleteProperty(AbortSignal, 'any');
  }
});
