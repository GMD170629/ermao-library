'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { clearStorage, getStorageUsage, type StorageCategory, type UsagePayload } from '../api/storage-client';

export function useStorageManagement() {
  const [usage, setUsage] = useState<UsagePayload | null>(null);
  const [busy, setBusy] = useState<StorageCategory | 'refresh' | null>('refresh');
  const [error, setError] = useState<string | null>(null);
  const controller = useRef<AbortController | null>(null);

  const run = useCallback(async (category?: StorageCategory) => {
    controller.current?.abort();
    const current = new AbortController();
    controller.current = current;
    setBusy(category ?? 'refresh');
    setError(null);
    try {
      const result = await (category ? clearStorage(category, current.signal) : getStorageUsage(current.signal));
      if (current.signal.aborted) return;
      setUsage((previous) => category && previous ? { ...previous, categories: previous.categories.map((row) => result.categories.find((updated) => updated.id === row.id) ?? row) } : result);
    } catch {
      if (!current.signal.aborted) {
        setError(category ? '清理失败，请重试' : '读取空间用量失败');
        if (category) {
          try {
            const result = await getStorageUsage(current.signal, category);
            if (!current.signal.aborted) setUsage((previous) => previous ? { ...previous, categories: previous.categories.map((row) => result.categories.find((updated) => updated.id === row.id) ?? row) } : null);
          } catch {
            // Keep the failure visible if the follow-up usage request also fails.
          }
        }
      }
    } finally {
      if (!current.signal.aborted) setBusy(null);
    }
  }, []);

  useEffect(() => {
    let active = true;
    queueMicrotask(() => { if (active) void run(); });
    return () => {
      active = false;
      controller.current?.abort();
    };
  }, [run]);

  return { usage, busy, error, refresh: () => void run(), clear: (category: StorageCategory) => void run(category) };
}
