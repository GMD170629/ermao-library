import type {
  MobiOpenResult,
  MobiResourceDescriptor,
  MobiTocEntry,
  MobiWorkerRequest,
  MobiWorkerResponse
} from './mobi-worker-protocol';

function property(value: unknown, key: PropertyKey): unknown {
  if (value === null || (typeof value !== 'object' && typeof value !== 'function')) return undefined;
  return Reflect.get(value, key);
}

function safeUnsignedInteger(value: unknown): number | null {
  return typeof value === 'number' && Number.isSafeInteger(value) && value >= 0 ? value : null;
}

function nullableString(value: unknown): string | null | undefined {
  return value === null || typeof value === 'string' ? value : undefined;
}

function parseResource(value: unknown): MobiResourceDescriptor | null {
  const index = safeUnsignedInteger(property(value, 'index'));
  const category = safeUnsignedInteger(property(value, 'category'));
  const decodedLength = safeUnsignedInteger(property(value, 'decodedLength'));
  const sourceName = property(value, 'sourceName');
  const mediaType = property(value, 'mediaType');
  if (
    index === null
    || category === null
    || decodedLength === null
    || typeof sourceName !== 'string'
    || typeof mediaType !== 'string'
  ) return null;
  return { index, category, decodedLength, sourceName, mediaType };
}

function parseTocEntry(value: unknown): MobiTocEntry | null {
  const title = property(value, 'title');
  const resourceIndex = safeUnsignedInteger(property(value, 'resourceIndex'));
  const fragment = nullableString(property(value, 'fragment'));
  const parentIndexValue = property(value, 'parentIndex');
  const parentIndex = parentIndexValue === null ? null : safeUnsignedInteger(parentIndexValue);
  if (
    typeof title !== 'string'
    || resourceIndex === null
    || fragment === undefined
    || parentIndex === null && parentIndexValue !== null
  ) return null;
  return { title, resourceIndex, fragment, parentIndex };
}

function parseOpenResult(value: unknown): MobiOpenResult | null {
  const title = nullableString(property(value, 'title'));
  const language = nullableString(property(value, 'language'));
  const rawResources = property(value, 'resources');
  const rawReadingOrder = property(value, 'readingOrder');
  const rawToc = property(value, 'toc');
  if (
    title === undefined
    || language === undefined
    || !Array.isArray(rawResources)
    || !Array.isArray(rawReadingOrder)
    || !Array.isArray(rawToc)
  ) return null;
  const resources = rawResources.map(parseResource);
  const readingOrder = rawReadingOrder.map(safeUnsignedInteger);
  const toc = rawToc.map(parseTocEntry);
  if (
    resources.some((item) => item === null)
    || readingOrder.some((item) => item === null)
    || toc.some((item) => item === null)
  ) return null;
  return {
    title,
    language,
    resources: resources.filter((item): item is MobiResourceDescriptor => item !== null),
    readingOrder: readingOrder.filter((item): item is number => item !== null),
    toc: toc.filter((item): item is MobiTocEntry => item !== null)
  };
}

function response(value: unknown): MobiWorkerResponse | null {
  const requestId = safeUnsignedInteger(property(value, 'requestId'));
  const ok = property(value, 'ok');
  if (requestId === null || typeof ok !== 'boolean') return null;
  const code = property(value, 'code');
  if (ok === false && typeof code === 'string') {
    return { requestId, ok: false, code };
  }
  if (ok !== true) return null;
  const type = property(value, 'type');
  const bytes = property(value, 'bytes');
  if (type === 'read' && bytes instanceof ArrayBuffer) {
    return { requestId, ok: true, type: 'read', bytes };
  }
  if (type === 'close') return { requestId, ok: true, type: 'close' };
  if (type === 'open') {
    const result = parseOpenResult(property(value, 'result'));
    return result ? { requestId, ok: true, type: 'open', result } : null;
  }
  return null;
}

export class MobiWorkerClient {
  private readonly worker = new Worker(new URL('./mobi-core.worker.ts', import.meta.url), { type: 'module' });
  private sequence = 0;
  private readonly pending = new Map<number, Readonly<{
    resolve: (value: MobiWorkerResponse) => void;
    reject: (reason: unknown) => void;
  }>>();

  constructor(private readonly signal?: AbortSignal) {
    this.worker.addEventListener('message', (event: MessageEvent<unknown>) => {
      const incoming = response(event.data);
      if (!incoming) {
        this.failAll(new Error('MOBI_WORKER_PROTOCOL_INVALID'));
        return;
      }
      const waiter = this.pending.get(incoming.requestId);
      if (!waiter) return;
      this.pending.delete(incoming.requestId);
      waiter.resolve(incoming);
    });
    this.worker.addEventListener('error', () => this.failAll(new Error('MOBI_WORKER_FAILED')));
    signal?.addEventListener('abort', () => {
      this.failAll(new DOMException('Aborted', 'AbortError'));
      this.worker.terminate();
    }, { once: true });
  }

  async open(blob: Blob, filename: string): Promise<MobiOpenResult> {
    const result = await this.send({ requestId: this.nextId(), type: 'open', blob, filename });
    if (!result.ok) throw new Error(result.code);
    if (result.type !== 'open') throw new Error('MOBI_WORKER_PROTOCOL_INVALID');
    return result.result;
  }

  async read(resourceIndex: number): Promise<ArrayBuffer> {
    const result = await this.send({ requestId: this.nextId(), type: 'read', resourceIndex });
    if (!result.ok) throw new Error(result.code);
    if (result.type !== 'read') throw new Error('MOBI_WORKER_PROTOCOL_INVALID');
    return result.bytes;
  }

  async close(): Promise<void> {
    if (this.signal?.aborted) return;
    const result = await this.send({ requestId: this.nextId(), type: 'close' });
    if (!result.ok) throw new Error(result.code);
    this.worker.terminate();
  }

  terminate(): void {
    this.failAll(new Error('MOBI_WORKER_CLOSED'));
    this.worker.terminate();
  }

  private nextId(): number { return ++this.sequence; }

  private send(request: MobiWorkerRequest): Promise<MobiWorkerResponse> {
    if (this.signal?.aborted) return Promise.reject(new DOMException('Aborted', 'AbortError'));
    return new Promise((resolve, reject) => {
      this.pending.set(request.requestId, { resolve, reject });
      this.worker.postMessage(request);
    });
  }

  private failAll(reason: unknown): void {
    for (const waiter of this.pending.values()) waiter.reject(reason);
    this.pending.clear();
  }
}
