'use client';

import {
  createReaderSessionState,
  readerSessionReducer,
  type OperationToken,
  type ReaderAdapter,
  type ReaderAdapterEvent,
  type ReaderCommand,
  type ReaderLocation,
  type ReaderOperationKind,
  type ReaderPreferences,
  type ReaderSource
} from '@shuku/reader-core';
import { useCallback, useEffect, useMemo, useReducer, useRef } from 'react';
import { emitReaderDebug } from '../../../lib/reader';

type ReaderSessionOptions = {
  adapter: ReaderAdapter | null;
  source: ReaderSource;
  initialLocation: ReaderLocation | null;
  preferences: ReaderPreferences;
  onLocationChange: (location: ReaderLocation, percent: number) => void;
  onExternalLink?: (href: string) => void;
  onPasswordRequired?: (reason: 'need-password' | 'incorrect-password') => void;
};

function newSessionId() {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) return crypto.randomUUID();
  return `reader-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

function readerOpenError(reason: unknown) {
  if (reason instanceof Error) {
    const code = 'code' in reason && typeof reason.code === 'string'
      ? reason.code
      : 'READER_OPEN_FAILED';
    return { code, message: reason.message, recoverable: code !== 'NOVEL_DRM_PROTECTED' };
  }
  return { code: 'READER_OPEN_FAILED', message: '阅读器加载失败', recoverable: true };
}

/**
 * Serializes navigation intents without allocating their operation token early.
 * Reset invalidates work that has not started when an adapter session closes.
 */
export class ReaderNavigationIntentQueue {
  private generation = 0;
  private tail: Promise<void> = Promise.resolve();

  enqueue(run: () => Promise<boolean>) {
    const generation = this.generation;
    const result = this.tail
      .catch(() => undefined)
      .then(async () => {
        if (generation !== this.generation) return false;
        const accepted = await run();
        return generation === this.generation ? accepted : false;
      });
    this.tail = result.then(() => undefined, () => undefined);
    return result;
  }

  reset() {
    this.generation += 1;
    this.tail = Promise.resolve();
  }
}

/**
 * React owns one session; the adapter owns one rendering engine.
 *
 *   UI command -> operation token -> adapter -> tagged event -> reducer
 *                         |                         |
 *                         +-- AbortController -----+
 *
 * Side effects validate the same token before persisting progress, so stale
 * adapter callbacks cannot bypass the reducer's admission gate.
 */
export function useReaderSession({
  adapter,
  source,
  initialLocation,
  preferences,
  onLocationChange,
  onExternalLink,
  onPasswordRequired
}: ReaderSessionOptions) {
  const sessionIdRef = useRef(newSessionId());
  const initialPreferencesRef = useRef(preferences);
  const [state, dispatch] = useReducer(
    readerSessionReducer,
    undefined,
    () => createReaderSessionState(sessionIdRef.current, initialPreferencesRef.current, source.kind)
  );
  const operationSequencesRef = useRef<Record<ReaderOperationKind, number>>({
    bootstrap: 0,
    navigation: 0,
    render: 0,
    preferences: 0,
    pagination: 0
  });
  const controllersRef = useRef(new Map<ReaderOperationKind, AbortController>());
  const activeControllersRef = useRef(new Set<AbortController>());
  const navigationQueueRef = useRef(new ReaderNavigationIntentQueue());
  const openedAdapterRef = useRef<ReaderAdapter | null>(null);
  const appliedPreferencesRef = useRef<ReaderPreferences>(initialPreferencesRef.current);
  const callbacksRef = useRef({ onLocationChange, onExternalLink, onPasswordRequired });

  useEffect(() => {
    callbacksRef.current = { onLocationChange, onExternalLink, onPasswordRequired };
  }, [onExternalLink, onLocationChange, onPasswordRequired]);

  const beginOperation = useCallback((kind: ReaderOperationKind) => {
    // Navigation is an intent queue: rapid key/tap input must advance once per
    // intent. Other operation classes are latest-wins and cancel their prior work.
    if (kind !== 'navigation') controllersRef.current.get(kind)?.abort();
    const controller = new AbortController();
    controllersRef.current.set(kind, controller);
    activeControllersRef.current.add(controller);
    const operation: OperationToken = {
      sessionId: sessionIdRef.current,
      kind,
      sequence: operationSequencesRef.current[kind] + 1
    };
    operationSequencesRef.current[kind] = operation.sequence;
    dispatch({ type: 'operation/begin', operation });
    emitReaderDebug('info', '阅读器操作开始', operation);
    return { operation, signal: controller.signal, controller };
  }, []);

  const finishOperation = useCallback((kind: ReaderOperationKind, controller: AbortController) => {
    activeControllersRef.current.delete(controller);
    if (controllersRef.current.get(kind) === controller) controllersRef.current.delete(kind);
  }, []);

  const isAcceptedEvent = useCallback((event: ReaderAdapterEvent) => {
    return event.sessionId === sessionIdRef.current
      && event.operation.sequence === operationSequencesRef.current[event.operation.kind];
  }, []);

  useEffect(() => {
    if (!adapter || openedAdapterRef.current === adapter) return undefined;
    const navigationQueue = navigationQueueRef.current;
    const activeControllers = activeControllersRef.current;
    const controllers = controllersRef.current;
    openedAdapterRef.current = adapter;
    const { operation, signal, controller } = beginOperation('bootstrap');
    let adapterReady = false;
    const unsubscribe = adapter.subscribe((event) => {
      if (!isAcceptedEvent(event)) {
        emitReaderDebug('warning', '已丢弃过期阅读器事件', {
          type: event.type,
          operation: event.operation,
          activeSessionId: sessionIdRef.current
        });
        return;
      }
      dispatch({ type: 'adapter/event', event });
      if (event.type === 'ready') adapterReady = true;
      // Preference-driven reflow may report a visually different EPUB page.
      // Initial restore and preference reflow may update the in-memory session,
      // but neither is a user navigation and neither may become a mutation.
      if (
        event.type === 'location-changed'
        && event.operation.kind !== 'preferences'
        && (event.operation.kind !== 'bootstrap' || adapterReady)
      ) {
        callbacksRef.current.onLocationChange(event.location, event.percent);
      } else if (event.type === 'external-link') {
        callbacksRef.current.onExternalLink?.(event.href);
      } else if (event.type === 'password-required') {
        callbacksRef.current.onPasswordRequired?.(event.reason);
      }
    });

    void adapter.open({
      sessionId: sessionIdRef.current,
      operation,
      signal,
      source,
      initialLocation,
      preferences: initialPreferencesRef.current
    }).catch((reason) => {
      if (signal.aborted) return;
      dispatch({
        type: 'session/fail',
        operation,
        error: readerOpenError(reason)
      });
    }).finally(() => finishOperation('bootstrap', controller));

    return () => {
      unsubscribe();
      navigationQueue.reset();
      activeControllers.forEach((controller) => controller.abort());
      activeControllers.clear();
      controllers.clear();
      openedAdapterRef.current = null;
      void adapter.dispose();
      dispatch({ type: 'session/dispose' });
    };
  }, [adapter, beginOperation, finishOperation, initialLocation, isAcceptedEvent, source]);

  useEffect(() => {
    if (!adapter || openedAdapterRef.current !== adapter || appliedPreferencesRef.current === preferences) return;
    appliedPreferencesRef.current = preferences;
    const context = beginOperation('preferences');
    dispatch({ type: 'preferences/replace', operation: context.operation, preferences });
    void adapter.applyPreferences(preferences, context).catch((reason) => {
      if (context.signal.aborted) return;
      dispatch({
        type: 'session/fail',
        operation: context.operation,
        error: {
          code: 'PREFERENCES_APPLY_FAILED',
          message: reason instanceof Error ? reason.message : '阅读设置应用失败',
          recoverable: true
        }
      });
    }).finally(() => finishOperation('preferences', context.controller));
  }, [adapter, beginOperation, finishOperation, preferences]);

  const executeNow = useCallback(async (command: ReaderCommand, kind: 'navigation' | 'render') => {
    if (!adapter || openedAdapterRef.current !== adapter) return false;
    const context = beginOperation(kind);
    try {
      const acknowledgement = await adapter.execute(command, context);
      if (context.signal.aborted) return false;
      dispatch({ type: 'operation/complete', operation: context.operation });
      return acknowledgement.accepted;
    } catch (reason) {
      if (context.signal.aborted) return false;
      dispatch({
        type: 'session/fail',
        operation: context.operation,
        error: {
          code: 'READER_COMMAND_FAILED',
          message: reason instanceof Error ? reason.message : '阅读操作失败',
          recoverable: true
        }
      });
      return false;
    } finally {
      finishOperation(context.operation.kind, context.controller);
    }
  }, [adapter, beginOperation, finishOperation]);

  const execute = useCallback((command: ReaderCommand) => {
    if (command.type === 'retry') return executeNow(command, 'render');
    return navigationQueueRef.current.enqueue(() => executeNow(command, 'navigation'));
  }, [executeNow]);

  const controls = useMemo(() => ({
    next: () => execute({ type: 'next' }),
    prev: () => execute({ type: 'previous' }),
    first: () => execute({ type: 'first' }),
    last: () => execute({ type: 'last' }),
    jumpToProgress: (percent: number) => execute({ type: 'go-to-progress', progression: Math.max(0, Math.min(1, percent / 100)) }),
    jumpToHref: (href: string) => execute({ type: 'go-to-href', href }),
    jumpToIndex: (index: number) => execute({ type: 'go-to-index', index }),
    retry: () => execute({ type: 'retry' })
  }), [execute]);

  return { state, controls, execute };
}
