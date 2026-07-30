export type JsonTransportFailureReason =
  | 'aborted'
  | 'invalid-json'
  | 'network'
  | 'response-too-large'
  | 'timeout';

export type JsonTransportResult =
  | Readonly<{
      ok: true;
      status: number;
      body: unknown;
    }>
  | Readonly<{
      ok: false;
      reason: 'aborted' | 'network' | 'timeout';
    }>
  | Readonly<{
      ok: false;
      reason: 'invalid-json' | 'response-too-large';
      status: number;
    }>;

export type JsonGetRequest = Readonly<{
  maximumResponseBytes: number;
  signal?: AbortSignal;
  timeoutMs: number;
  url: string;
}>;

export interface JsonTransport {
  get(request: JsonGetRequest): Promise<JsonTransportResult>;
}

type FetchResponse = Readonly<{
  body: ReadableStream<Uint8Array> | null;
  status: number;
}>;

type FetchRequest = Readonly<{
  credentials: 'omit';
  headers: Readonly<Record<string, string>>;
  method: 'GET';
  redirect: 'manual';
  signal: AbortSignal;
}>;

export type FetchFunction = (
  url: string,
  request: FetchRequest,
) => Promise<FetchResponse>;

type BoundedBodyResult =
  | Readonly<{ ok: true; text: string }>
  | Readonly<{ ok: false }>;

async function readBoundedResponseBody(
  response: FetchResponse,
  maximumResponseBytes: number,
): Promise<BoundedBodyResult> {
  if (response.body === null) {
    return { ok: true, text: '' };
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  const chunks: string[] = [];
  let receivedBytes = 0;
  try {
    while (true) {
      const chunk = await reader.read();
      if (chunk.done) {
        chunks.push(decoder.decode());
        return { ok: true, text: chunks.join('') };
      }

      receivedBytes += chunk.value.byteLength;
      if (receivedBytes > maximumResponseBytes) {
        await reader.cancel('Response body exceeded its configured limit');
        return { ok: false };
      }
      chunks.push(decoder.decode(chunk.value, { stream: true }));
    }
  } finally {
    reader.releaseLock();
  }
}

export class FetchJsonTransport implements JsonTransport {
  constructor(private readonly fetchFunction: FetchFunction) {}

  async get(request: JsonGetRequest): Promise<JsonTransportResult> {
    if (
      !Number.isSafeInteger(request.maximumResponseBytes) ||
      request.maximumResponseBytes < 1 ||
      !Number.isSafeInteger(request.timeoutMs) ||
      request.timeoutMs < 1
    ) {
      throw new TypeError(
        'JSON transport limits must be positive safe integers',
      );
    }

    const controller = new AbortController();
    let timedOut = false;
    const timeout = setTimeout(() => {
      timedOut = true;
      controller.abort();
    }, request.timeoutMs);
    const abortFromCaller = (): void => {
      controller.abort(request.signal?.reason);
    };

    if (request.signal?.aborted) {
      clearTimeout(timeout);
      return { ok: false, reason: 'aborted' };
    }
    request.signal?.addEventListener('abort', abortFromCaller, { once: true });

    try {
      const response = await this.fetchFunction(request.url, {
        credentials: 'omit',
        headers: { Accept: 'application/json' },
        method: 'GET',
        redirect: 'manual',
        signal: controller.signal,
      });
      const body = await readBoundedResponseBody(
        response,
        request.maximumResponseBytes,
      );
      if (!body.ok) {
        return {
          ok: false,
          reason: 'response-too-large',
          status: response.status,
        };
      }
      try {
        const parsed: unknown = JSON.parse(body.text);
        return { ok: true, status: response.status, body: parsed };
      } catch (cause: unknown) {
        if (cause instanceof SyntaxError) {
          return {
            ok: false,
            reason: 'invalid-json',
            status: response.status,
          };
        }
        throw cause;
      }
    } catch {
      if (request.signal?.aborted) {
        return { ok: false, reason: 'aborted' };
      }
      if (timedOut) {
        return { ok: false, reason: 'timeout' };
      }
      return { ok: false, reason: 'network' };
    } finally {
      clearTimeout(timeout);
      request.signal?.removeEventListener('abort', abortFromCaller);
    }
  }
}