import type {
  OperationToken,
  ReaderAdapterEvent,
  ReaderAdapterListener,
  ReaderAdapterOperationContext,
  ReaderCommandAck
} from '@shuku/reader-core';

type AdapterEventPayload = ReaderAdapterEvent extends infer Event
  ? Event extends ReaderAdapterEvent
    ? Omit<Event, 'sessionId' | 'operation' | 'occurredAt'>
    : never
  : never;

export class StaleReaderOperationError extends Error {
  constructor() {
    super('Reader operation is no longer active');
    this.name = 'StaleReaderOperationError';
  }
}

export function isAbortError(reason: unknown) {
  return reason instanceof DOMException && reason.name === 'AbortError';
}

export function errorMessage(reason: unknown, fallback: string) {
  return reason instanceof Error && reason.message ? reason.message : fallback;
}

export function throwIfAborted(signal: AbortSignal) {
  if (signal.aborted) throw new DOMException('The operation was aborted', 'AbortError');
}

/**
 * Adapter -> one stamped event stream -> ReaderSession
 *
 * Adapters never mutate session state directly. A generation change makes every
 * in-flight callback from the previous source inert, even when the underlying
 * third-party library cannot truly cancel its promise.
 */
export abstract class ReaderAdapterBase {
  private readonly listeners = new Set<ReaderAdapterListener>();
  private generation = 0;
  private sessionId = '';
  private operation: OperationToken | null = null;
  private disposed = false;

  subscribe(listener: ReaderAdapterListener) {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  protected beginSession(sessionId: string, operation: OperationToken) {
    this.generation += 1;
    this.sessionId = sessionId;
    this.operation = operation;
    this.disposed = false;
    return this.generation;
  }

  protected beginOperation(context: ReaderAdapterOperationContext) {
    this.assertSession(context.operation);
    throwIfAborted(context.signal);
    this.operation = context.operation;
    return this.generation;
  }

  protected currentGeneration() {
    return this.generation;
  }

  protected currentOperation() {
    if (!this.operation) throw new StaleReaderOperationError();
    return this.operation;
  }

  protected assertActive(generation: number, signal?: AbortSignal) {
    if (signal) throwIfAborted(signal);
    if (this.disposed || generation !== this.generation) {
      throw new StaleReaderOperationError();
    }
  }

  protected isActive(generation: number, signal?: AbortSignal) {
    return !this.disposed && generation === this.generation && !signal?.aborted;
  }

  protected emit(payload: AdapterEventPayload, operation = this.currentOperation()) {
    if (this.disposed || operation.sessionId !== this.sessionId) return;
    const event = {
      ...payload,
      sessionId: this.sessionId,
      operation,
      occurredAt: Date.now()
    } as ReaderAdapterEvent;
    this.listeners.forEach((listener) => listener(event));
  }

  protected ack(operation: OperationToken, accepted: boolean, options: Omit<ReaderCommandAck, 'operation' | 'accepted'> = {}): ReaderCommandAck {
    return { operation, accepted, ...options };
  }

  protected failOperation(context: ReaderAdapterOperationContext, reason: string) {
    return this.ack(context.operation, false, { reason });
  }

  protected markDisposed() {
    if (this.disposed) return false;
    this.disposed = true;
    this.generation += 1;
    this.operation = null;
    this.listeners.clear();
    return true;
  }

  private assertSession(operation: OperationToken) {
    if (this.disposed || !this.sessionId || operation.sessionId !== this.sessionId) {
      throw new StaleReaderOperationError();
    }
  }
}
