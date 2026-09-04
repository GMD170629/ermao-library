import type { ReaderV5SyncDiagnostic } from './v5-storage';

export function emitReaderDebug(
  level: ReaderV5SyncDiagnostic['level'],
  message: string,
  data?: Record<string, unknown>
) {
  if (typeof window === 'undefined'
    || typeof window.dispatchEvent !== 'function'
    || typeof CustomEvent === 'undefined') return;
  window.dispatchEvent(new CustomEvent('shuku:reader-debug', { detail: { level, message, data } }));
}
