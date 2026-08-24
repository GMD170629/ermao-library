import assert from 'node:assert/strict';
import test from 'node:test';
import { ComicSpreadTrackDriver, type ComicTrackView } from './comic-track';

class FakeElement {
  readonly dataset: Record<string, string> = {};
  readonly style: Record<string, string> = {};
  readonly attributes = new Map<string, string>();
  readonly children: FakeElement[] = [];
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
  complete = false;
  naturalWidth = 0;
  draggable = true;
  readonly listeners = new Map<string, Set<() => void>>();

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

  setAttribute(name: string, value: string) {
    this.attributes.set(name, value);
  }

  addEventListener(type: string, listener: () => void) {
    const listeners = this.listeners.get(type) ?? new Set<() => void>();
    listeners.add(listener);
    this.listeners.set(type, listeners);
  }

  removeEventListener(type: string, listener: () => void) {
    this.listeners.get(type)?.delete(listener);
  }

  dispatch(type: string) {
    this.listeners.get(type)?.forEach((listener) => listener());
  }
}

class FakeDocument {
  readonly documentElement = { lang: 'zh-CN' };

  createElement() {
    return new FakeElement(this);
  }
}

function page(pageIndex: number, url = `blob:${pageIndex}`) {
  return { pageIndex, url };
}

function view(overrides: Partial<ComicTrackView> = {}): ComicTrackView {
  return {
    previous: null,
    current: { anchor: 1, pages: [page(1)] },
    next: { anchor: 2, pages: [page(2)] },
    direction: 'ltr',
    mode: 'single',
    imageFit: 'contain',
    zoom: 1,
    pageWidth: 800,
    reducedMotion: true,
    ...overrides
  };
}

function createHarness(initial = view()) {
  const ownerDocument = new FakeDocument();
  const container = new FakeElement(ownerDocument);
  let currentView = initial;
  const retriedPages: number[] = [];
  const driver = new ComicSpreadTrackDriver(container as unknown as HTMLElement, {
    getView: () => currentView,
    prepare: async (step) => Boolean(step === -1 ? currentView.previous : currentView.next),
    promote: (step) => {
      if (step === 1) {
        currentView = {
          ...currentView,
          previous: { anchor: 1, pages: [page(1)] },
          current: { anchor: 2, pages: [page(2)] },
          next: { anchor: 3, pages: [page(3)] }
        };
      }
    },
    retry: (pageIndex) => retriedPages.push(pageIndex)
  });
  driver.render();
  driver.recenter();
  return { container, driver, retriedPages, getView: () => currentView, setView: (next: ComicTrackView) => { currentView = next; } };
}

test('comic track keeps the viewport and rotates persistent slots after promotion', async () => {
  const harness = createHarness();
  const viewport = harness.container.children[0];
  const previous = harness.driver.getSlotElement('previous');
  const current = harness.driver.getSlotElement('current');
  const next = harness.driver.getSlotElement('next');

  assert.equal(viewport.dataset.comicViewport, 'true');
  assert.equal(viewport.scrollLeft, 800);
  assert.equal(harness.driver.snapshot().hasPrevious, false);
  assert.equal(harness.driver.snapshot().hasNext, true);

  await harness.driver.promote(1, new AbortController().signal);

  assert.equal(harness.container.children[0], viewport);
  assert.equal(harness.driver.getSlotElement('previous'), current);
  assert.equal(harness.driver.getSlotElement('current'), next);
  assert.equal(harness.driver.getSlotElement('next'), previous);
  assert.equal(harness.driver.getSlotElement('current').dataset.comicSpreadAnchor, '2');
  assert.equal(viewport.scrollLeft, 800);
});

test('comic spread width follows the bounded page-width preference', () => {
  const harness = createHarness(view({ pageWidth: 720 }));
  const frame = harness.driver.getSlotElement('current').children[0] as HTMLElement;

  assert.equal(frame.style.maxWidth, '720px');

  harness.setView(view({ pageWidth: 640, zoom: 1.5 }));
  harness.driver.render();
  assert.equal((harness.driver.getSlotElement('current').children[0] as HTMLElement).style.maxWidth, '960px');
});

test('zoomed comic navigation starts the promoted spread at the top', async () => {
  const harness = createHarness(view({ zoom: 2 }));
  const next = harness.driver.getSlotElement('next') as unknown as FakeElement;
  next.scrollHeight = 1_200;
  next.clientHeight = 600;
  next.scrollWidth = 1_600;
  next.clientWidth = 800;
  next.scrollTop = 480;

  await harness.driver.promote(1, new AbortController().signal);

  const current = harness.driver.getSlotElement('current') as unknown as FakeElement;
  assert.equal(current.scrollTop, 0);
  assert.equal(current.scrollLeft, 400);
});

test('RTL reverses physical neighbor placement and preserves visual page order from the source', () => {
  const rtl = view({
    previous: { anchor: 1, pages: [page(2), page(1)] },
    current: { anchor: 3, pages: [page(4), page(3)] },
    next: { anchor: 5, pages: [page(6), page(5)] },
    direction: 'rtl',
    mode: 'double'
  });
  const harness = createHarness(rtl);
  const viewport = harness.container.children[0];
  const track = viewport.children[0];
  const current = harness.driver.getSlotElement('current');
  const frame = current.children[0];

  assert.equal(track.children[0].dataset.comicSpreadSlot, 'next');
  assert.equal(track.children[1].dataset.comicSpreadSlot, 'current');
  assert.equal(track.children[2].dataset.comicSpreadSlot, 'previous');
  assert.deepEqual(Array.from(frame.children).map((slot) => (slot as HTMLElement).dataset.comicPageIndex), ['4', '3']);

  harness.driver.setLogicalOffset(120);
  assert.equal(viewport.scrollLeft, 680);
});

test('an unmatched final double-page spread is centered as one logical page', () => {
  const harness = createHarness(view({
    previous: { anchor: 3, pages: [page(3), page(4)] },
    current: { anchor: 5, pages: [page(5)] },
    next: null,
    mode: 'double'
  }));
  const current = harness.driver.getSlotElement('current');
  const pageSlot = current.children[0].children[0] as HTMLElement;

  assert.equal(current.dataset.comicSpreadAnchor, '5');
  assert.equal(pageSlot.style.width, '100%');
  assert.equal(pageSlot.style.justifyContent, 'center');
  assert.equal(harness.driver.snapshot().hasNext, false);
});

test('native image events replace the loading placeholder and expose retry on failure', () => {
  const harness = createHarness();
  const root = harness.container.children[0];
  const next = harness.driver.getSlotElement('next');
  const pageSlot = next.children[0].children[0] as unknown as FakeElement;
  const image = pageSlot.children[0];
  const placeholder = pageSlot.children[1];

  assert.equal(harness.container.children[0], root);
  assert.equal(placeholder.textContent, '加载中');
  assert.equal(image.style.visibility, 'hidden');

  image.dispatch('error');
  const failure = placeholder.children[0];
  assert.equal(failure.children[0].textContent, '漫画页面加载失败');
  failure.children[1].dispatch('click');
  assert.deepEqual(harness.retriedPages, [2]);

  const currentPageSlot = harness.driver.getSlotElement('current').children[0].children[0] as unknown as FakeElement;
  const currentImage = currentPageSlot.children[0];
  currentImage.dispatch('load');
  assert.equal(currentImage.style.visibility, 'visible');
  assert.equal(currentPageSlot.children.length, 1);
});

test('a stalled animation frame still finishes at the exact comic snap point', async () => {
  const originalRequest = Object.getOwnPropertyDescriptor(globalThis, 'requestAnimationFrame');
  const originalCancel = Object.getOwnPropertyDescriptor(globalThis, 'cancelAnimationFrame');
  const cancelled: number[] = [];
  Object.defineProperty(globalThis, 'requestAnimationFrame', {
    configurable: true,
    value() {
      return 73;
    }
  });
  Object.defineProperty(globalThis, 'cancelAnimationFrame', {
    configurable: true,
    value(handle: number) {
      cancelled.push(handle);
    }
  });

  try {
    const harness = createHarness();
    const viewport = harness.container.children[0];
    await harness.driver.animateTo(1, 1, new AbortController().signal);

    assert.equal(viewport.scrollLeft, 1600);
    assert.deepEqual(cancelled, [73]);
  } finally {
    if (originalRequest) Object.defineProperty(globalThis, 'requestAnimationFrame', originalRequest);
    else Reflect.deleteProperty(globalThis, 'requestAnimationFrame');
    if (originalCancel) Object.defineProperty(globalThis, 'cancelAnimationFrame', originalCancel);
    else Reflect.deleteProperty(globalThis, 'cancelAnimationFrame');
  }
});
