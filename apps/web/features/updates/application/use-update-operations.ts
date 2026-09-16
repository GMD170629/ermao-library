'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import type { InstallRequest, PreparationState, UpdateCheck } from '@/generated/updates';
import { fetchUpdateCheck, fetchUpdateState, installUpdate, prepareUpdate, UpdateRequestError } from '../api/operations';
import { confirmedSuccess, installationPhases, observationTimeoutMs, pollIntervalMs, preparationPhases } from '../model/installation';
import { useReleaseFeed } from './release-feed-context';

export function useUpdateOperations(enabled: boolean) {
  const { runtime, refreshRuntime } = useReleaseFeed();
  const [check, setCheck] = useState<UpdateCheck | null>(null);
  const [state, setState] = useState<PreparationState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [observing, setObserving] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const expected = useRef<InstallRequest | null>(null);
  const sending = useRef(false);
  const deadline = useRef(0);
  const mounted = useRef(true);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);

  useEffect(() => {
    if (!enabled) return;
    const controller = new AbortController();
    fetchUpdateCheck(controller.signal).then(setCheck).catch(() => {
      if (!controller.signal.aborted) setError('暂时无法检查更新');
    });
    return () => controller.abort();
  }, [enabled, attempt]);

  useEffect(() => {
    if (!enabled) return;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const controller = new AbortController();
    if (!deadline.current) deadline.current = Date.now() + observationTimeoutMs;
    async function poll() {
      try {
        const next = await fetchUpdateState(controller.signal);
        const info = await refreshRuntime(controller.signal);
        if (controller.signal.aborted) return;
        setState(next);
        const pending = installationPhases.has(next.phase ?? '') || preparationPhases.has(next.phase ?? '') ||
          (next.phase === 'success' && !confirmedSuccess(next, info.current_version, expected.current)) ||
          (expected.current !== null && !confirmedSuccess(next, info.current_version, expected.current) && next.phase !== 'failed');
        setObserving(pending);
        if (!pending) return;
      } catch {
        if (controller.signal.aborted) return;
        setObserving(true);
      }
      if (Date.now() >= deadline.current) {
        setError('确认更新状态超时，请检查容器日志和 STORAGE_ROOT/update-tmp/installation.log。');
        setObserving(false);
        return;
      }
      timer = setTimeout(() => { void poll(); }, pollIntervalMs);
    }
    void poll();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [enabled, attempt, refreshRuntime]);

  const submit = useCallback(async (operation: 'prepare' | 'install', target: InstallRequest) => {
    if (sending.current) return;
    sending.current = true;
    setSubmitting(true);
    setError(null);
    if (operation === 'install') expected.current = target;
    deadline.current = Date.now() + observationTimeoutMs;
    try {
      const next = await (operation === 'prepare' ? prepareUpdate(target.version) : installUpdate(target));
      if (mounted.current) setState(next);
    } catch (reason) {
      if (!mounted.current) return;
      // A disconnected POST can have been accepted. Observe; never repeat the mutation.
      if (reason instanceof UpdateRequestError) {
        expected.current = null;
        setError(reason.code);
      } else {
        setError('正在确认更新状态，请勿重复提交。');
        setObserving(true);
      }
    } finally {
      sending.current = false;
      if (mounted.current) { setSubmitting(false); setAttempt(value => value + 1); }
    }
  }, []);
  return { check, state, error, observing, submitting, submit, runtime,
    installRequested: expected.current !== null,
    success: !!state && !!runtime && confirmedSuccess(state, runtime.current_version, expected.current),
    refresh: () => { deadline.current = 0; setError(null); setAttempt(value => value + 1); }
  };
}
