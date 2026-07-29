'use client';

import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';
import { fetchReleaseFeed } from '../api/client';
import type { ReleaseFeedState } from '../model/types';

type ReleaseFeedContextValue = {
  state: ReleaseFeedState;
  retry: () => void;
};

const ReleaseFeedContext = createContext<ReleaseFeedContextValue | null>(null);

export function ReleaseFeedProvider({ children }: { children: ReactNode }) {
  const [attempt, setAttempt] = useState(0);
  const [state, setState] = useState<ReleaseFeedState>({ status: 'loading' });

  useEffect(() => {
    const controller = new AbortController();
    setState({ status: 'loading' });
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
  const value = useMemo(() => ({ state, retry }), [retry, state]);
  return <ReleaseFeedContext.Provider value={value}>{children}</ReleaseFeedContext.Provider>;
}

export function useReleaseFeed() {
  const value = useContext(ReleaseFeedContext);
  if (!value) throw new Error('useReleaseFeed must be used inside ReleaseFeedProvider');
  return value;
}
