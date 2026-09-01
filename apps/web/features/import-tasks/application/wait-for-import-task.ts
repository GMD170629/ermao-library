import { fetchImportTask, type LibraryImportTask } from '../api/client';

const DEFAULT_POLL_INTERVAL_MS = 500;
const DEFAULT_TIMEOUT_MS = 120_000;

function wait(milliseconds: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) {
      reject(signal.reason);
      return;
    }
    const timeout = globalThis.setTimeout(resolve, milliseconds);
    signal?.addEventListener('abort', () => {
      globalThis.clearTimeout(timeout);
      reject(signal.reason);
    }, { once: true });
  });
}

export async function waitForImportTask(
  taskId: string,
  options: Readonly<{
    signal?: AbortSignal;
    pollIntervalMs?: number;
    timeoutMs?: number;
  }> = {}
): Promise<LibraryImportTask | null> {
  const pollIntervalMs = options.pollIntervalMs ?? DEFAULT_POLL_INTERVAL_MS;
  const timeoutAt = Date.now() + (options.timeoutMs ?? DEFAULT_TIMEOUT_MS);
  while (Date.now() < timeoutAt) {
    const task = await fetchImportTask(taskId, options.signal);
    if (task.state === 'SUCCEEDED' || task.state === 'FAILED') return task;
    await wait(pollIntervalMs, options.signal);
  }
  return null;
}
