import assert from 'node:assert/strict';
import test from 'node:test';
import { DEFAULT_READER_PREFERENCES } from '@shuku/reader-core';
import type { PDFDocumentLoadingTask, PDFDocumentProxy, PDFPageProxy, RenderTask, TextLayer } from 'pdfjs-dist';
import { PdfReaderAdapter } from './pdf-adapter';

type FakeListener = (event: Event) => void;

class FakeStyle {
  [key: string]: unknown;

  setProperty(name: string, value: string) {
    this[name] = value;
  }
}

class FakeElement {
  readonly dataset: Record<string, string> = {};
  readonly style = new FakeStyle();
  readonly children: FakeElement[] = [];
  readonly listeners = new Map<string, Set<FakeListener>>();
  ownerDocument: FakeDocument;
  parentElement: FakeElement | null = null;
  clientHeight = 600;
  clientWidth = 800;
  className = '';
  textContent = '';
  width = 0;
  height = 0;

  constructor(ownerDocument: FakeDocument) {
    this.ownerDocument = ownerDocument;
  }

  append(...nodes: FakeElement[]) {
    nodes.forEach((node) => {
      node.remove();
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

  setAttribute() {}
}

class FakeDocument {
  createElement() {
    return new FakeElement(this);
  }
}

class FakeResizeObserver {
  static latest: FakeResizeObserver | null = null;

  constructor(private readonly callback: ResizeObserverCallback) {
    FakeResizeObserver.latest = this;
  }

  observe() {}
  disconnect() {}

  trigger() {
    this.callback([], this as unknown as ResizeObserver);
  }
}

function deferred() {
  let resolve!: () => void;
  const promise = new Promise<void>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

async function waitFor(predicate: () => boolean, message: string) {
  const startedAt = Date.now();
  while (!predicate()) {
    if (Date.now() - startedAt > 1_000) throw new Error(message);
    await new Promise<void>((resolve) => setTimeout(resolve, 5));
  }
}

test('PDF resize and preference rerenders keep the committed page visible until replacement', async () => {
  const originalResizeObserver = globalThis.ResizeObserver;
  const originalRequestAnimationFrame = globalThis.requestAnimationFrame;
  const originalCancelAnimationFrame = globalThis.cancelAnimationFrame;
  const originalWindow = globalThis.window;
  const replacementRender = deferred();
  const preferenceRender = deferred();
  const ownerDocument = new FakeDocument();
  const container = new FakeElement(ownerDocument);
  let renderCalls = 0;

  const page = {
    getViewport: ({ scale }: { scale: number }) => ({ width: 600 * scale, height: 900 * scale }),
    render: () => {
      renderCalls += 1;
      return {
        promise: renderCalls === 1
          ? Promise.resolve()
          : renderCalls === 2
            ? replacementRender.promise
            : preferenceRender.promise,
        cancel() {}
      } as RenderTask;
    },
    streamTextContent: () => ({}),
    cleanup() {}
  } as unknown as PDFPageProxy;
  const document = {
    numPages: 1,
    getPage: async () => page
  } as unknown as PDFDocumentProxy;
  const loadingTask = {
    promise: Promise.resolve(document),
    destroy: async () => undefined,
    onPassword: undefined
  } as unknown as PDFDocumentLoadingTask;
  class FakeTextLayer {
    render() {
      return Promise.resolve();
    }

    cancel() {}
  }
  const pdfjs = {
    GlobalWorkerOptions: {},
    getDocument: () => loadingTask,
    TextLayer: FakeTextLayer as unknown as typeof TextLayer,
    AnnotationMode: { DISABLE: 0 },
    PasswordResponses: { INCORRECT_PASSWORD: 2 }
  } as unknown as typeof import('pdfjs-dist');

  Object.assign(globalThis, {
    ResizeObserver: FakeResizeObserver,
    requestAnimationFrame: (callback: FrameRequestCallback) => {
      setImmediate(() => callback(Date.now()));
      return 1;
    },
    cancelAnimationFrame: () => undefined,
    window: { devicePixelRatio: 1, innerWidth: 800, innerHeight: 600 }
  });

  const adapter = new PdfReaderAdapter({
    container: container as unknown as HTMLElement,
    fetch: async () => new Response('%PDF-1.7', { status: 200 }),
    loadPdfJs: async () => pdfjs
  });

  try {
    await adapter.open({
      sessionId: 'pdf-session',
      operation: { sessionId: 'pdf-session', kind: 'bootstrap', sequence: 1 },
      signal: new AbortController().signal,
      source: {
        editionId: 'edition-1',
        workId: 'work-1',
        kind: 'pdf',
        contentUrl: '/book.pdf',
        contentFingerprint: 'pdf-fingerprint',
        totalPages: 1
      },
      initialLocation: null,
      preferences: DEFAULT_READER_PREFERENCES
    });
    const committedPage = container.children[0];
    assert.ok(committedPage);

    container.clientWidth = 700;
    assert.ok(FakeResizeObserver.latest);
    FakeResizeObserver.latest.trigger();
    await waitFor(() => renderCalls === 2, 'resize render did not start');

    assert.equal(container.children[0], committedPage);
    replacementRender.resolve();
    await waitFor(() => container.children[0] !== committedPage, 'replacement page was not committed');
    assert.equal(container.children.length, 1);

    const resizedPage = container.children[0];
    FakeResizeObserver.latest.trigger();
    await new Promise<void>((resolve) => setImmediate(resolve));
    await new Promise<void>((resolve) => setImmediate(resolve));
    assert.equal(renderCalls, 2);

    const preferenceUpdate = adapter.applyPreferences({
      ...DEFAULT_READER_PREFERENCES,
      pdf: { ...DEFAULT_READER_PREFERENCES.pdf, zoom: 1.2 }
    }, {
      operation: { sessionId: 'pdf-session', kind: 'preferences', sequence: 1 },
      signal: new AbortController().signal
    });
    await waitFor(() => renderCalls === 3, 'preference render did not start');
    assert.equal(container.children[0], resizedPage);
    preferenceRender.resolve();
    await preferenceUpdate;
    assert.notEqual(container.children[0], resizedPage);
    assert.equal(container.children.length, 1);
  } finally {
    await adapter.dispose();
    Object.assign(globalThis, {
      ResizeObserver: originalResizeObserver,
      requestAnimationFrame: originalRequestAnimationFrame,
      cancelAnimationFrame: originalCancelAnimationFrame,
      window: originalWindow
    });
    FakeResizeObserver.latest = null;
  }
});
