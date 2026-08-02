import type { ReaderSyncDiagnostic } from './model';

export function emitReaderDebug(
  level: ReaderSyncDiagnostic['level'],
  message: string,
  data?: Record<string, unknown>
) {
  if (typeof window === 'undefined' || typeof CustomEvent === 'undefined') return;
  window.dispatchEvent(new CustomEvent('shuku:reader-debug', { detail: { level, message, data } }));
}

