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
  const [state, setState] = useState<ReleaseFeedState>({ status: 'loading' });

  useEffect(() => {
    const controller = new AbortController();
    setState({ status: 'loading' });
    fetchRuntime(controller.signal).then(setRuntime).catch(() => undefined);
    fetchReleaseFeed(controller.signal)
      .then((feed) => setState({ status: 'ready', feed }))
      .catch((reason: unknown) => {
        if (controller.signal.aborted) return;
        setState({
          status: 'error',
          message: reason instanceof Error ? reason.message : '暂时无法检查更新'
        });
      });
    return () => controller.abort();
  }, [attempt]);

  const retry = useCallback(() => setAttempt((value) => value + 1), []);
  const value = useMemo(() => ({ state, retry, runtime, refreshRuntime }), [retry, state, runtime, refreshRuntime]);
  return <ReleaseFeedContext.Provider value={value}>{children}</ReleaseFeedContext.Provider>;
}

export function useReleaseFeed() {
  const value = useContext(ReleaseFeedContext);
  if (!value) throw new Error('useReleaseFeed must be used inside ReleaseFeedProvider');
  return value;
}
