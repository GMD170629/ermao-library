import type {
  TextPublicationChapter,
  TextPublicationFormat,
  TextPublicationResult,
  TextWorkerResponse
} from './text-worker-protocol';
import { isReaderSafetyRuleId, reviveReaderSafetyError } from '../security/reader-safety-policy';

function property(value: unknown, key: PropertyKey): unknown {
  if (value === null || (typeof value !== 'object' && typeof value !== 'function')) return undefined;
  return Reflect.get(value, key);
}

function unsignedInteger(value: unknown): number | null {
  return typeof value === 'number' && Number.isSafeInteger(value) && value >= 0 ? value : null;
}

function parseChapter(value: unknown): TextPublicationChapter | null {
  const href = property(value, 'href');
  const type = property(value, 'type');
  const title = property(value, 'title');
  const bytes = property(value, 'bytes');
  const positionLength = unsignedInteger(property(value, 'positionLength'));
  if (
    typeof href !== 'string'
    || type !== 'application/xhtml+xml'
    || typeof title !== 'string'
    || !(bytes instanceof ArrayBuffer)
    || positionLength === null
  ) return null;
  return { href, type, title, bytes, positionLength };
}

function parseResponse(value: unknown): TextWorkerResponse | null {
  const requestId = unsignedInteger(property(value, 'requestId'));
  const ok = property(value, 'ok');
  if (requestId === null || typeof ok !== 'boolean') return null;
  const code = property(value, 'code');
  if (!ok) {
    const ruleId = property(value, 'ruleId');
    return typeof code === 'string' && (ruleId === undefined || isReaderSafetyRuleId(ruleId))
      ? { requestId, ok: false, code, ...(ruleId ? { ruleId } : {}) }
      : null;
  }
  const result = property(value, 'result');
  const title = property(result, 'title');
  const language = property(result, 'language');
  const rawChapters = property(result, 'chapters');
  if (
    typeof title !== 'string'
    || (language !== null && typeof language !== 'string')
    || !Array.isArray(rawChapters)
  ) return null;
  const chapters = rawChapters.map(parseChapter);
  if (chapters.some((chapter) => chapter === null)) return null;
  return {
    requestId,
    ok: true,
    result: {
      title,
      language,
      chapters: chapters.filter((chapter): chapter is TextPublicationChapter => chapter !== null)
    }
  };
}

export function parseTextPublication(
  blob: Blob,
  format: TextPublicationFormat,
  fallbackTitle: string,
  signal?: AbortSignal
): Promise<TextPublicationResult> {
  return new Promise((resolve, reject) => {
    const worker = new Worker(new URL('./text-publication.worker.ts', import.meta.url), { type: 'module' });
    const stop = () => worker.terminate();
    const abort = () => {
      stop();
      reject(new DOMException('Aborted', 'AbortError'));
    };
    if (signal?.aborted) {
      abort();
      return;
    }
    signal?.addEventListener('abort', abort, { once: true });
    worker.addEventListener('error', () => {
      signal?.removeEventListener('abort', abort);
      stop();
      reject(new Error('PUBLICATION_PARSE_FAILED'));
    }, { once: true });
    worker.addEventListener('message', (event: MessageEvent<unknown>) => {
      signal?.removeEventListener('abort', abort);
      stop();
      const incoming = parseResponse(event.data);
      if (!incoming || incoming.requestId !== 1) {
        reject(new Error('PUBLICATION_WORKER_PROTOCOL_INVALID'));
      } else if (!incoming.ok) {
        reject(reviveReaderSafetyError(incoming.code, incoming.ruleId));
      } else {
        resolve(incoming.result);
      }
    }, { once: true });
    worker.postMessage({ requestId: 1, type: 'open', blob, format, fallbackTitle });
  });
}
