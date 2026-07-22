export type EpubLayoutTaskContext = {
  epoch: number;
  isCurrent: () => boolean;
};

/**
 * epub.js mutates one rendition for both navigation and pagination. Keeping
 * those mutations on one queue prevents an older async resize/display from
 * landing after a newer navigation or layout request.
 */
export class EpubLayoutCoordinator {
  private tail: Promise<void> = Promise.resolve();
  private layoutEpoch = 0;

  enqueueNavigation<T>(task: () => Promise<T>) {
    return this.enqueue(task);
  }

  enqueueLayout(task: (context: EpubLayoutTaskContext) => Promise<void>) {
    const epoch = ++this.layoutEpoch;
    const promise = this.enqueue(async () => {
      if (epoch !== this.layoutEpoch) return false;
      await task({ epoch, isCurrent: () => epoch === this.layoutEpoch });
      return true;
    });
    return { epoch, promise };
  }

  invalidateLayouts() {
    this.layoutEpoch += 1;
  }

  private enqueue<T>(task: () => Promise<T>) {
    const result = this.tail.catch(() => undefined).then(task);
    this.tail = result.then(() => undefined, () => undefined);
    return result;
  }
}

function abortError() {
  return new DOMException('The operation was aborted', 'AbortError');
}

function throwIfSignalAborted(signal?: AbortSignal) {
  if (signal?.aborted) throw abortError();
}

function waitForAbortable<T>(promise: PromiseLike<T>, signal?: AbortSignal) {
  if (!signal) return Promise.resolve(promise);
  if (signal.aborted) return Promise.reject<T>(abortError());
  return new Promise<T>((resolve, reject) => {
    const abort = () => reject(abortError());
    signal.addEventListener('abort', abort, { once: true });
    Promise.resolve(promise).then(
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

function documentImages(document: Document) {
  return Array.from(document.querySelectorAll<HTMLImageElement>('img'));
}

function hasIntrinsicPlaceholder(image: HTMLImageElement) {
  const width = Number(image.getAttribute('width'));
  const height = Number(image.getAttribute('height'));
  return Number.isFinite(width) && width > 0 && Number.isFinite(height) && height > 0;
}

/** Backfill intrinsic dimensions so a later paint cannot invalidate columns. */
export function preserveEpubImageDimensions(image: HTMLImageElement) {
  const width = Math.round(image.naturalWidth);
  const height = Math.round(image.naturalHeight);
  if (width <= 0 || height <= 0) return;
  if (!image.hasAttribute('width')) image.setAttribute('width', String(width));
  if (!image.hasAttribute('height')) image.setAttribute('height', String(height));
  if (!image.style.aspectRatio) image.style.aspectRatio = `${width} / ${height}`;
}

function waitForImageDimensions(image: HTMLImageElement, signal?: AbortSignal) {
  if (hasIntrinsicPlaceholder(image)) {
    if (image.complete) preserveEpubImageDimensions(image);
    return Promise.resolve();
  }
  if (image.complete) {
    preserveEpubImageDimensions(image);
    return Promise.resolve();
  }

  // Lazy images without an authored aspect ratio can otherwise remain
  // dimensionless until the reader reaches a later column.
  image.loading = 'eager';
  return new Promise<void>((resolve, reject) => {
    const cleanup = () => {
      image.removeEventListener('load', settled);
      image.removeEventListener('error', settled);
      signal?.removeEventListener('abort', aborted);
    };
    const settled = () => {
      cleanup();
      preserveEpubImageDimensions(image);
      resolve();
    };
    const aborted = () => {
      cleanup();
      reject(abortError());
    };
    image.addEventListener('load', settled, { once: true });
    image.addEventListener('error', settled, { once: true });
    signal?.addEventListener('abort', aborted, { once: true });
    if (signal?.aborted) aborted();
    else if (image.complete) settled();
  });
}

export async function waitForEpubFonts(documents: Iterable<Document>, signal?: AbortSignal) {
  throwIfSignalAborted(signal);
  await Promise.all(Array.from(documents, async (document) => {
    const fontSet = document.fonts;
    if (!fontSet?.ready) return;
    await waitForAbortable(fontSet.ready, signal).catch((reason) => {
      // Detached iframe documents may reject while epub.js swaps a section.
      if (signal?.aborted) throw reason;
    });
  }));
}

export async function waitForEpubImages(documents: Iterable<Document>, signal?: AbortSignal) {
  throwIfSignalAborted(signal);
  const images = Array.from(documents).flatMap(documentImages);
  await Promise.all(images.map((image) => waitForImageDimensions(image, signal)));
}

function frameForDocument(document: Document | undefined) {
  const view = document?.defaultView;
  const requestFrame = view?.requestAnimationFrame;
  if (typeof requestFrame === 'function') return new Promise<void>((resolve) => {
    let settled = false;
    const timer = setTimeout(() => {
      if (settled) return;
      settled = true;
      resolve();
    }, 100);
    requestFrame.call(view, () => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      resolve();
    });
  });
  if (typeof globalThis.requestAnimationFrame === 'function') {
    return new Promise<void>((resolve) => globalThis.requestAnimationFrame(() => resolve()));
  }
  return new Promise<void>((resolve) => setTimeout(resolve, 0));
}

function documentLayoutSignature(documents: Document[]) {
  return documents.map((document) => {
    const root = document.documentElement;
    const body = document.body;
    return [
      root?.scrollWidth ?? 0,
      root?.scrollHeight ?? 0,
      body?.scrollWidth ?? 0,
      body?.scrollHeight ?? 0
    ].join(':');
  }).join('|');
}

/** Wait until column geometry is identical for two consecutive paint frames. */
export async function waitForStableEpubLayout(documents: Iterable<Document>, signal?: AbortSignal) {
  const snapshot = Array.from(documents);
  let previous = '';
  let stableFrames = 0;
  for (let frame = 0; frame < 12; frame += 1) {
    throwIfSignalAborted(signal);
    await frameForDocument(snapshot[0]);
    const signature = documentLayoutSignature(snapshot);
    if (signature === previous) stableFrames += 1;
    else stableFrames = 0;
    previous = signature;
    if (stableFrames >= 2) return;
  }
}

export async function waitForEpubLayoutBarrier(documents: Iterable<Document>, signal?: AbortSignal, timeoutMs = 4_000) {
  const snapshot = Array.from(documents);
  const readinessController = new AbortController();
  const abortReadiness = () => readinessController.abort();
  if (signal?.aborted) readinessController.abort();
  else signal?.addEventListener('abort', abortReadiness, { once: true });
  const timeout = setTimeout(abortReadiness, timeoutMs);
  try {
    await Promise.all([
      waitForEpubFonts(snapshot, readinessController.signal),
      waitForEpubImages(snapshot, readinessController.signal)
    ]);
  } catch (reason) {
    if (signal?.aborted) throw reason;
    // Broken remote assets must not keep an otherwise readable EPUB hidden.
  } finally {
    clearTimeout(timeout);
    signal?.removeEventListener('abort', abortReadiness);
  }
  await waitForStableEpubLayout(snapshot, signal);
}
