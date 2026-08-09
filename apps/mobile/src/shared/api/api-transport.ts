export type ApiTransportFailureReason =
  | 'aborted'
  | 'invalid-json'
  | 'network'
  | 'response-too-large'
  | 'timeout';

export type ApiResponseHeaders = Readonly<{
  contentType: string | null;
  etag: string | null;
  lastModified: string | null;
}>;

export type ApiTransportResult =
  | Readonly<{
      ok: true;
      responseType: 'json';
      status: number;
      headers: ApiResponseHeaders;
      body: unknown;
    }>
  | Readonly<{
      ok: true;
      responseType: 'bytes';
      status: number;
      headers: ApiResponseHeaders;
      body: Uint8Array;
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

export type ApiTransportFailure = Extract<
  ApiTransportResult,
  Readonly<{ ok: false }>
>;
export type ApiJsonTransportResult =
  | Extract<
      ApiTransportResult,
      Readonly<{ ok: true; responseType: 'json' }>
    >
  | ApiTransportFailure;
export type ApiBytesTransportResult =
  | Extract<
      ApiTransportResult,
      Readonly<{ ok: true; responseType: 'bytes' }>
    >
  | ApiTransportFailure;

export type ApiHttpMethod = 'DELETE' | 'GET' | 'PATCH' | 'POST' | 'PUT';
export type ApiRequestBody =
  | Readonly<{ kind: 'form-data'; value: FormData }>
  | Readonly<{ kind: 'json'; value: unknown }>;

export type ApiRequest = Readonly<{
  body?: ApiRequestBody;
  headers?: Readonly<Record<string, string>>;
  maximumResponseBytes: number;
  method: ApiHttpMethod;
  responseType: 'bytes' | 'json';
  signal?: AbortSignal;
  timeoutMs: number;
  url: string;
}>;

export interface ApiTransport {
  request(request: ApiRequest): Promise<ApiTransportResult>;
}

type FetchResponseHeaders = Readonly<{
  get(name: string): string | null;
}>;

export type ApiFetchResponse = Readonly<{
  body: ReadableStream<Uint8Array> | null;
  headers: FetchResponseHeaders;
  status: number;
}>;

export type ApiFetchRequest = Readonly<{
  body?: FormData | string;
  credentials: 'include';
  headers: Readonly<Record<string, string>>;
  method: ApiHttpMethod;
  redirect: 'manual';
  signal: AbortSignal;
}>;

export type ApiFetchFunction = (
  url: string,
  request: ApiFetchRequest,
) => Promise<ApiFetchResponse>;

type BoundedBodyResult =
  | Readonly<{ ok: true; bytes: Uint8Array }>
  | Readonly<{ ok: false }>;

function concatenateChunks(
  chunks: readonly Uint8Array[],
  byteLength: number,
): Uint8Array {
  const result = new Uint8Array(byteLength);
  let offset = 0;
  for (const chunk of chunks) {
    result.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return result;
}

async function readBoundedResponseBody(
  response: ApiFetchResponse,
  maximumResponseBytes: number,
): Promise<BoundedBodyResult> {
  if (response.body === null) {
    return { ok: true, bytes: new Uint8Array() };
  }

  const reader = response.body.getReader();
  const chunks: Uint8Array[] = [];
  let receivedBytes = 0;
  try {
    while (true) {
      const chunk = await reader.read();
      if (chunk.done) {
        return {
          ok: true,
          bytes: concatenateChunks(chunks, receivedBytes),
        };
      }

      receivedBytes += chunk.value.byteLength;
      if (receivedBytes > maximumResponseBytes) {
        await reader.cancel('Response body exceeded its configured limit');
        return { ok: false };
      }
      chunks.push(chunk.value);
    }
  } finally {
    reader.releaseLock();
  }
}

function serializedBody(body: unknown): string {
  const serialized = JSON.stringify(body);
  if (serialized === undefined) {
    throw new TypeError('JSON request body must be serializable');
  }
  return serialized;
}

function hasContentType(headers: Readonly<Record<string, string>>): boolean {
  return Object.keys(headers).some(
    (name) => name.toLowerCase() === 'content-type',
  );
}

function responseHeaders(response: ApiFetchResponse): ApiResponseHeaders {
  return {
    contentType: response.headers.get('content-type'),
    etag: response.headers.get('etag'),
    lastModified: response.headers.get('last-modified'),
  };
}

export class FetchApiTransport implements ApiTransport {
  constructor(private readonly fetchFunction: ApiFetchFunction) {}

  async request(request: ApiRequest): Promise<ApiTransportResult> {
    if (
      !Number.isSafeInteger(request.maximumResponseBytes) ||
      request.maximumResponseBytes < 1 ||
      !Number.isSafeInteger(request.timeoutMs) ||
      request.timeoutMs < 1
    ) {
      throw new TypeError(
        'API transport limits must be positive safe integers',
      );
    }
    if (
      (request.method === 'GET' || request.method === 'DELETE') &&
      request.body !== undefined
    ) {
      throw new TypeError(`${request.method} requests cannot include a body`);
    }
    if (
      request.body !== undefined &&
      hasContentType(request.headers ?? {})
    ) {
      throw new TypeError(
        request.body.kind === 'form-data'
          ? 'FormData Content-Type must be generated by the native fetch implementation'
          : 'JSON Content-Type is managed by the API transport',
      );
    }

    const body =
      request.body === undefined
        ? undefined
        : request.body.kind === 'json'
          ? serializedBody(request.body.value)
          : request.body.value;

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

    const headers: Record<string, string> = {
      Accept:
        request.responseType === 'json' ? 'application/json' : '*/*',
      ...request.headers,
      ...(request.body?.kind === 'json'
        ? { 'Content-Type': 'application/json' }
        : {}),
    };

    try {
      const response = await this.fetchFunction(request.url, {
        ...(body === undefined ? {} : { body }),
        credentials: 'include',
        headers,
        method: request.method,
        redirect: 'manual',
        signal: controller.signal,
      });
      const responseBody = await readBoundedResponseBody(
        response,
        request.maximumResponseBytes,
      );
      if (!responseBody.ok) {
        return {
          ok: false,
          reason: 'response-too-large',
          status: response.status,
        };
      }
      const headersResult = responseHeaders(response);
      if (request.responseType === 'bytes') {
        return {
          ok: true,
          responseType: 'bytes',
          status: response.status,
          headers: headersResult,
          body: responseBody.bytes,
        };
      }

      const text = new TextDecoder().decode(responseBody.bytes);
      if (text.trim().length === 0) {
        return {
          ok: true,
          responseType: 'json',
          status: response.status,
          headers: headersResult,
          body: null,
        };
      }
      try {
        const parsed: unknown = JSON.parse(text);
        return {
          ok: true,
          responseType: 'json',
          status: response.status,
          headers: headersResult,
          body: parsed,
        };
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
