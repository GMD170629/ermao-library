import assert from 'node:assert/strict';
import test from 'node:test';
import { DEFAULT_READER_PREFERENCES } from '@shuku/reader-core';
import type {
  PDFDocumentLoadingTask,
  PDFDocumentProxy,
  PDFPageProxy,
  RenderTask,
  TextLayer
} from 'pdfjs-dist/legacy/build/pdf.mjs';
import { PdfReaderAdapter, resolvedPdfPageRotation } from './pdf-adapter';
import { MemoryReaderStorage } from '../../../../lib/reader/memory-storage';

type FakeListener = (event: Event) => void;

const PDF_FIXTURE_BYTES = new TextEncoder().encode('%PDF-1.7\nreader range fixture');
const PDF_FIXTURE_HASH = `sha256:${'1'.repeat(64)}`;
const PDF_FIXTURE_ETAG = `"${PDF_FIXTURE_HASH}"`;

class FakePdfDataRangeTransport {
  constructor(
    readonly length: number,
    readonly initialData: Uint8Array | null
  ) {}
  onDataRange() {}
  requestDataRange() {}
  abort() {}
}

function pdfRangeFixture() {
  return {
    rangeAccess: {
      url: '/book.pdf',
      length: PDF_FIXTURE_BYTES.byteLength,
      etag: PDF_FIXTURE_ETAG,
      identity: {
        serverIdentity: 'https://reader.test',
        userId: 'user-1',
        authorizationVersion: 1,
        resourceId: 'resource-1',
        assetId: 'asset-1',
      },
      cache: new MemoryReaderStorage()
    },
    fetch: async (_input: RequestInfo | URL, init?: RequestInit) => {
      const headers = new Headers({
        'Accept-Ranges': 'bytes',
        'Content-Length': String(PDF_FIXTURE_BYTES.byteLength),
        ETag: PDF_FIXTURE_ETAG
      });
      if (init?.method === 'HEAD') return new Response(null, { status: 200, headers });
      const range = new Headers(init?.headers).get('Range');
      const match = /^bytes=(\d+)-(\d+)$/u.exec(range ?? '');
      assert.ok(match);
      const begin = Number(match[1]);
      const end = Number(match[2]);
      headers.set('Content-Range', `bytes ${begin}-${end}/${PDF_FIXTURE_BYTES.byteLength}`);
      headers.set('Content-Length', String(end - begin + 1));
      return new Response(PDF_FIXTURE_BYTES.slice(begin, end + 1), { status: 206, headers });
    }
  };
}

test('PDF page rotation preserves each page intrinsic orientation and adds the reader preference', () => {
  assert.equal(resolvedPdfPageRotation(0, 0), 0);
  assert.equal(resolvedPdfPageRotation(180, 0), 180);
  assert.equal(resolvedPdfPageRotation(270, 90), 0);
  assert.equal(resolvedPdfPageRotation(-90, 180), 90);
  assert.equal(resolvedPdfPageRotation(Number.NaN, 270), 270);
});

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
  scrollLeft = 0;
  scrollTop = 0;

  get childElementCount() {
    return this.children.length;
  }

  get firstElementChild() {
    return this.children[0] ?? null;
  }

  get offsetHeight() {
    return Number.parseFloat(String(this.style.height ?? this.style.minHeight ?? 0)) || 0;
  }

  get offsetTop() {
    if (!this.parentElement) return 0;
    const index = this.parentElement.children.indexOf(this);
    return this.parentElement.children.slice(0, Math.max(0, index))
      .reduce((height, child) => height + child.offsetHeight, 0);
  }

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

test('PDF page navigation resets a zoomed document to the top', async () => {
  const originalResizeObserver = globalThis.ResizeObserver;
  const originalWindow = globalThis.window;
  const ownerDocument = new FakeDocument();
  const container = new FakeElement(ownerDocument);
  const page = {
    getViewport: ({ scale }: { scale: number }) => ({ width: 600 * scale, height: 900 * scale }),
    render: () => ({ promise: Promise.resolve(), cancel() {} }) as RenderTask,
    streamTextContent: () => ({}),
    cleanup() {}
  } as unknown as PDFPageProxy;
  const document = {
    setReadingWindow: async () => undefined,
    numPages: 2,
    getPage: async () => page
  } as unknown as PDFDocumentProxy;
  const loadingTask = {
    promise: Promise.resolve(document),
    destroy: async () => undefined,
    onPassword: undefined
  } as unknown as PDFDocumentLoadingTask;
  class FakeTextLayer {
    render() { return Promise.resolve(); }
    cancel() {}
  }
  const pdfjs = {
    GlobalWorkerOptions: {},
    getDocument: (parameters: unknown) => {
      assert.ok(parameters !== null && typeof parameters === 'object');
      assert.equal(Reflect.get(parameters, 'wasmUrl'), '/vendor/pdfjs/wasm/');
      assert.equal(Reflect.get(parameters, 'stopAtErrors'), true);
      return loadingTask;
    },
    TextLayer: FakeTextLayer as unknown as typeof TextLayer,
    AnnotationMode: { DISABLE: 0 },
    PasswordResponses: { INCORRECT_PASSWORD: 2 },
    PDFDataRangeTransport: FakePdfDataRangeTransport
  } as unknown as typeof import('pdfjs-dist/legacy/build/pdf.mjs');
  Object.assign(globalThis, {
    ResizeObserver: FakeResizeObserver,
    window: { devicePixelRatio: 1, innerWidth: 800, innerHeight: 600 }
  });
  const adapter = new PdfReaderAdapter({
    container: container as unknown as HTMLElement,
    ...pdfRangeFixture(),
    loadPdfJs: async () => pdfjs
  });

  try {
    await adapter.open({
      sessionId: 'pdf-session',
      operation: { sessionId: 'pdf-session', kind: 'bootstrap', sequence: 1 },
      signal: new AbortController().signal,
      source: {
        resourceId: 'resource-1',
        bookId: 'book-1',
        kind: 'pdf',
        contentUrl: '/book.pdf',
        totalPages: 2
      },
      initialLocation: null,
      preferences: {
        ...DEFAULT_READER_PREFERENCES,
        pdf: { ...DEFAULT_READER_PREFERENCES.pdf, fit: 'width', zoom: 2, pageWidth: 700 }
      }
    });
    assert.equal(container.children[0]?.style.width, '1400px');
    container.scrollTop = 420;

    const acknowledged = await adapter.execute({ type: 'next' }, {
      operation: { sessionId: 'pdf-session', kind: 'navigation', sequence: 2 },
      signal: new AbortController().signal
    });

    assert.equal(acknowledged.accepted, true);
    assert.equal(container.scrollTop, 0);
  } finally {
    await adapter.dispose();
    Object.assign(globalThis, {
      ResizeObserver: originalResizeObserver,
      window: originalWindow
    });
  }
});

test('PDF adapter forces legacy continuous preferences into paged rendering', async () => {
  const originalResizeObserver = globalThis.ResizeObserver;
  const originalWindow = globalThis.window;
  const ownerDocument = new FakeDocument();
  const container = new FakeElement(ownerDocument);
  const page = {
    getViewport: ({ scale }: { scale: number }) => ({ width: 600 * scale, height: 900 * scale }),
    render: () => ({ promise: Promise.resolve(), cancel() {} }) as RenderTask,
    streamTextContent: () => ({}),
    cleanup() {}
  } as unknown as PDFPageProxy;
  const document = {
    setReadingWindow: async () => undefined,
    numPages: 7,
    getPage: async () => page
  } as unknown as PDFDocumentProxy;
  const loadingTask = {
    promise: Promise.resolve(document),
    destroy: async () => undefined,
    onPassword: undefined
  } as unknown as PDFDocumentLoadingTask;
  class FakeTextLayer {
    render() { return Promise.resolve(); }
    cancel() {}
  }
  const pdfjs = {
    GlobalWorkerOptions: {},
    getDocument: () => loadingTask,
    TextLayer: FakeTextLayer as unknown as typeof TextLayer,
    AnnotationMode: { DISABLE: 0 },
    PasswordResponses: { INCORRECT_PASSWORD: 2 },
    PDFDataRangeTransport: FakePdfDataRangeTransport
  } as unknown as typeof import('pdfjs-dist/legacy/build/pdf.mjs');
  Object.assign(globalThis, {
    ResizeObserver: FakeResizeObserver,
    window: { devicePixelRatio: 1, innerWidth: 800, innerHeight: 600 }
  });
  const adapter = new PdfReaderAdapter({
    container: container as unknown as HTMLElement,
    ...pdfRangeFixture(),
    loadPdfJs: async () => pdfjs
  });

  try {
    await adapter.open({
      sessionId: 'pdf-continuous-session',
      operation: { sessionId: 'pdf-continuous-session', kind: 'bootstrap', sequence: 1 },
      signal: new AbortController().signal,
      source: {
        resourceId: 'resource-1',
        bookId: 'book-1',
        kind: 'pdf',
        contentUrl: '/book.pdf',
        totalPages: 7
      },
      initialLocation: null,
      preferences: {
        ...DEFAULT_READER_PREFERENCES,
        pdf: { ...DEFAULT_READER_PREFERENCES.pdf, flow: 'continuous' }
      }
    });
    assert.equal(adapter.getCapabilities().supportsScrolling, false);
    assert.equal(container.children.length, 1);
    assert.equal(container.children[0]?.className, 'shuku-pdf-page');

    const acknowledged = await adapter.execute({ type: 'go-to-index', index: 4 }, {
      operation: { sessionId: 'pdf-continuous-session', kind: 'navigation', sequence: 2 },
      signal: new AbortController().signal
    });

    assert.equal(acknowledged.accepted, true);
    assert.equal(container.children.length, 1);
    assert.equal(container.children[0]?.dataset.pageNumber, '4');

    const restored = await adapter.execute({
      type: 'go-to-location',
      location: { kind: 'pdf', pageIndex: 4, pageProgression: 0.5 }
    }, {
      operation: { sessionId: 'pdf-continuous-session', kind: 'navigation', sequence: 3 },
      signal: new AbortController().signal
    });

    assert.equal(restored.accepted, true);
    assert.deepEqual(restored.location, { kind: 'pdf', pageIndex: 4, pageProgression: 0 });
  } finally {
    await adapter.dispose();
    Object.assign(globalThis, {
      ResizeObserver: originalResizeObserver,
      window: originalWindow
    });
  }
});

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
    setReadingWindow: async () => undefined,
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
    PasswordResponses: { INCORRECT_PASSWORD: 2 },
    PDFDataRangeTransport: FakePdfDataRangeTransport
  } as unknown as typeof import('pdfjs-dist/legacy/build/pdf.mjs');

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
    ...pdfRangeFixture(),
    loadPdfJs: async () => pdfjs
  });

  try {
    await adapter.open({
      sessionId: 'pdf-session',
      operation: { sessionId: 'pdf-session', kind: 'bootstrap', sequence: 1 },
      signal: new AbortController().signal,
      source: {
        resourceId: 'resource-1',
        bookId: 'book-1',
        kind: 'pdf',
        contentUrl: '/book.pdf',
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
