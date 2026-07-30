import type { CancellationToken } from '../application/ports';

export class AbortSignalCancellationToken implements CancellationToken {
  constructor(private readonly signal: AbortSignal) {}

  isCancellationRequested(): boolean {
    return this.signal.aborted;
  }

  subscribe(listener: () => void): () => void {
    this.signal.addEventListener('abort', listener, { once: true });
    return () => {
      this.signal.removeEventListener('abort', listener);
    };
  }
}
