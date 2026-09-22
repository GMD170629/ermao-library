'use client';

import { useEffect, useRef, useState } from 'react';
import type { CreateGrantRequest, UpdateGrantRequest } from '../../../generated/automation';
import { cancelOperation, createGrant, updateGrant, loadAutomation, loadOperations, revokeGrant, saveSettings } from '../api/client';
import type { ServiceSettings } from '../model/configuration';

type Data = Awaited<ReturnType<typeof loadAutomation>>;
export function useAutomation(userId: string | undefined) {
  const [data, setData] = useState<Data>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(false);
  const lifetime = useRef<AbortController | null>(null);
  const inFlight = useRef(false);
  useEffect(() => {
    const controller = new AbortController();
    lifetime.current = controller;
    setData(undefined); setError(false); setBusy(false); inFlight.current = false;
    if (userId) void loadAutomation(controller.signal).then((next) => {
      if (!controller.signal.aborted) setData(next);
    }).catch(() => { if (!controller.signal.aborted) setError(true); });
    return () => controller.abort();
  }, [userId]);

  async function mutate(operation: (signal: AbortSignal) => Promise<void>) {
    const controller = lifetime.current;
    if (inFlight.current || !controller || controller.signal.aborted) return;
    inFlight.current = true; setBusy(true); setError(false);
    try { await operation(controller.signal); return controller.signal.aborted ? undefined : true; }
    catch { if (controller.signal.aborted) return; setError(true); return false; }
    finally { if (!controller.signal.aborted) { inFlight.current = false; setBusy(false); } }
  }
  return { data, busy, error,
    retry: () => mutate(async (signal) => {
      const next = await loadAutomation(signal);
      if (!signal.aborted) setData(next);
    }),
    create: (input: CreateGrantRequest) => mutate(async (signal) => {
      const result = await createGrant(input, signal);
      if (signal.aborted) return;
      setData((previous) => previous ? { ...previous, grants: [result.grant, ...previous.grants] } : previous);
    }),
    update: (id: string, input: UpdateGrantRequest) => mutate(async (signal) => {
      const grant = await updateGrant(id, input, signal);
      if (!signal.aborted) setData((previous) => previous ? { ...previous,
        grants: previous.grants.map((item) => item.id === id ? grant : item) } : previous);
    }),
    revoke: (id: string) => mutate(async (signal) => {
      await revokeGrant(id, signal);
      const next = await loadAutomation(signal);
      if (!signal.aborted) setData(next);
    }),
    refreshOperations: () => mutate(async (signal) => {
      const operations = await loadOperations(signal);
      if (!signal.aborted) setData((previous) => previous ? { ...previous, operations } : previous);
    }),
    cancel: (id: string) => mutate(async (signal) => {
      const operation = await cancelOperation(id, signal);
      if (!signal.aborted) setData((previous) => previous ? { ...previous,
        operations: previous.operations.map((item) => item.operation_id === id ? operation : item) } : previous);
    }),
    save: (settings: ServiceSettings) => mutate(async (signal) => {
      const saved = await saveSettings(settings, signal);
      if (!signal.aborted) setData((previous) => previous ? { ...previous, settings: saved } : previous);
    })
  };
}
