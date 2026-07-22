import type { Book } from 'epubjs';

const TEXT_NODE = 3;
const DEFAULT_YIELD_AFTER_MS = 12;
const DEFAULT_CONCURRENCY = 4;

type EpubLocationSection = {
  linear: boolean;
  load: (request: Book['load']) => Promise<Element>;
  unload: () => void;
  cfiFromRange: (range: Range) => string;
};

type EpubLocationBook = Pick<Book, 'load' | 'spine'>;

export type EpubLocationGenerationProgress = {
  completed: number;
  total: number;
  percent: number;
};

export type GenerateEpubLocationsOptions = {
  breakSize: number;
  signal?: AbortSignal;
  yieldAfterMs?: number;
  concurrency?: number;
  prepareDocument?: (document: Document) => void;
  onProgress?: (progress: EpubLocationGenerationProgress) => void;
};

function abortError() {
  if (typeof DOMException === 'function') return new DOMException('The operation was aborted', 'AbortError');
  const error = new Error('The operation was aborted');
  error.name = 'AbortError';
  return error;
}

function throwIfAborted(signal?: AbortSignal) {
  if (signal?.aborted) throw abortError();
}

function monotonicNow() {
  return typeof performance === 'undefined' ? Date.now() : performance.now();
}

function yieldToMainThread(signal?: AbortSignal) {
  throwIfAborted(signal);
  return new Promise<void>((resolve, reject) => {
    let settled = false;
    const finish = () => {
      if (settled) return;
      settled = true;
      signal?.removeEventListener('abort', cancel);
      resolve();
    };
    const cancel = () => {
      if (settled) return;
      settled = true;
      signal?.removeEventListener('abort', cancel);
      reject(abortError());
    };
    signal?.addEventListener('abort', cancel, { once: true });
    if (typeof MessageChannel === 'function') {
      const channel = new MessageChannel();
      channel.port1.onmessage = () => {
        channel.port1.close();
        channel.port2.close();
        finish();
      };
      channel.port2.postMessage(undefined);
      return;
    }
    setTimeout(finish, 0);
  });
}

function textNodes(root: Node) {
  const result: Text[] = [];
  const pending: Node[] = [root];
  while (pending.length > 0) {
    const node = pending.pop()!;
    if (node.nodeType === TEXT_NODE) {
      result.push(node as Text);
      continue;
    }
    const children = node.childNodes;
    for (let index = children.length - 1; index >= 0; index -= 1) pending.push(children[index]);
  }
  return result;
}

/**
 * Generates the same character-range CFI shape consumed by epub.js Locations,
 * while using only the public Section CFI API.
 */
export function generateEpubSectionLocations(
  contents: Element,
  section: Pick<EpubLocationSection, 'cfiFromRange'>,
  breakSize: number
) {
  const document = contents.ownerDocument;
  const body = document.querySelector('body');
  if (!body) return [];

  const locations: string[] = [];
  let range: Range | null = null;
  let counter = 0;
  let previous: Text | null = null;

  for (const node of textNodes(body)) {
    const length = node.length;
    let position = 0;
    if (node.textContent.trim().length === 0) continue;

    if (counter === 0) {
      range = document.createRange();
      range.setStart(node, 0);
    }

    let distance = breakSize - counter;
    if (distance > length) {
      counter += length;
      position = length;
    }

    while (position < length) {
      distance = breakSize - counter;
      if (counter === 0) {
        position += 1;
        range = document.createRange();
        range.setStart(node, position);
      }

      if (position + distance >= length) {
        counter += length - position;
        position = length;
      } else {
        position += distance;
        range!.setEnd(node, position);
        locations.push(section.cfiFromRange(range!));
        counter = 0;
      }
    }
    previous = node;
  }

  if (range?.startContainer && previous) {
    range.setEnd(previous, previous.length);
    locations.push(section.cfiFromRange(range));
  }
  return locations;
}

export async function generateEpubLocations(
  book: EpubLocationBook,
  options: GenerateEpubLocationsOptions
) {
  const sections: EpubLocationSection[] = [];
  book.spine.each((section: EpubLocationSection) => {
    if (section.linear) sections.push(section);
  });

  const total = sections.length;
  const locations: string[] = [];
  const yieldAfterMs = Math.max(1, options.yieldAfterMs ?? DEFAULT_YIELD_AFTER_MS);
  const concurrency = Math.max(1, Math.min(8, Math.round(options.concurrency ?? DEFAULT_CONCURRENCY)));
  const request = book.load.bind(book) as Book['load'];
  let sliceStartedAt = monotonicNow();
  let completed = 0;
  options.onProgress?.({ completed: 0, total, percent: total > 0 ? 0 : 100 });

  for (let index = 0; index < sections.length; index += concurrency) {
    throwIfAborted(options.signal);
    const batch = sections.slice(index, index + concurrency);
    const outcomes = await Promise.all(batch.map(async (section) => {
      try {
        const contents = await section.load(request);
        throwIfAborted(options.signal);
        options.prepareDocument?.(contents.ownerDocument);
        const sectionLocations = generateEpubSectionLocations(contents, section, options.breakSize);
        completed += 1;
        options.onProgress?.({ completed, total, percent: total > 0 ? (completed / total) * 100 : 100 });
        return { ok: true as const, locations: sectionLocations };
      } catch (reason) {
        return { ok: false as const, reason };
      } finally {
        section.unload();
      }
    }));
    const failure = outcomes.find((outcome) => !outcome.ok);
    if (failure && !failure.ok) throw failure.reason;
    outcomes.forEach((outcome) => {
      if (outcome.ok) locations.push(...outcome.locations);
    });
    if (monotonicNow() - sliceStartedAt >= yieldAfterMs && completed < total) {
      await yieldToMainThread(options.signal);
      sliceStartedAt = monotonicNow();
    }
  }

  return locations;
}
