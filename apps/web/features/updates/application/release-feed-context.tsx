'use client';

import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';
import { fetchRuntime } from '../api/operations';
import type { RuntimeInfo } from '@/generated/updates';
import { fetchReleaseFeed } from '../api/client';
import type { ReleaseFeedState } from '../model/types';

type ReleaseFeedContextValue = {
  state: ReleaseFeedState;
  runtime: RuntimeInfo | null;
  refreshRuntime: (signal?: AbortSignal) => Promise<RuntimeInfo>;
  retry: () => void;
};

const ReleaseFeedContext = createContext<ReleaseFeedContextValue | null>(null);

export function ReleaseFeedProvider({ children }: { children: ReactNode }) {
  const [attempt, setAttempt] = useState(0);
  const [runtime, setRuntime] = useState<RuntimeInfo | null>(null);
  const refreshRuntime = useCallback(async (signal?: AbortSignal) => {
    const info = await fetchRuntime(signal);
    if (!signal?.aborted) setRuntime(info);
    return info;
  }, []);
  const [result, setResult] = useState<{ attempt: number; state: ReleaseFeedState }>();

  useEffect(() => {
    const controller = new AbortController();
    void refreshRuntime(controller.signal).catch(() => undefined);
    fetchReleaseFeed(controller.signal)
      .then((feed) => { if (!controller.signal.aborted) setResult({ attempt, state: { status: 'ready', feed } }); })
      .catch(() => {
        if (!controller.signal.aborted) setResult({ attempt, state: { status: 'error' } });
      });
    return () => controller.abort();
  }, [attempt, refreshRuntime]);

  const retry = useCallback(() => setAttempt((value) => value + 1), []);
  const value = useMemo<ReleaseFeedContextValue>(() => ({
    state: result?.attempt === attempt ? result.state : { status: 'loading' },
    retry, runtime, refreshRuntime
  }), [attempt, result, retry, runtime, refreshRuntime]);
  return <ReleaseFeedContext.Provider value={value}>{children}</ReleaseFeedContext.Provider>;
}

export function useReleaseFeed() {
  const value = useContext(ReleaseFeedContext);
  if (!value) throw new Error('useReleaseFeed must be used inside ReleaseFeedProvider');
  return value;
}
