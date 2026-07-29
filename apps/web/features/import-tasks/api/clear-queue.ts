export type ImportQueueClearStatus = 'requested' | 'waiting' | 'running' | 'completed' | 'failed';

export type ImportQueueClearOperation = {
  id: string;
  queueName: 'import';
  action: 'clear';
  status: ImportQueueClearStatus;
  messageCode: string;
  requestedAt: string;
  startedAt: string | null;
  finishedAt: string | null;
  updatedAt: string;
};

type JsonObject = Record<string, unknown>;
const importQueueClearStatuses: readonly ImportQueueClearStatus[] = [
  'requested',
  'waiting',
  'running',
  'completed',
  'failed'
];

function isObject(value: unknown): value is JsonObject {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function requiredString(value: unknown, field: string): string {
  if (typeof value !== 'string') {
    throw new Error(`Invalid import queue operation field: ${field}`);
  }
  return value;
}

function isImportQueueClearStatus(value: string): value is ImportQueueClearStatus {
  return importQueueClearStatuses.some((status) => status === value);
}

export function parseImportQueueClearOperation(value: unknown): ImportQueueClearOperation {
  if (!isObject(value)) throw new Error('Invalid import queue operation');
  const queueName = requiredString(value.queueName, 'queueName');
  const action = requiredString(value.action, 'action');
  const status = requiredString(value.status, 'status');
  if (queueName !== 'import' || action !== 'clear') {
    throw new Error('Invalid import queue clear operation');
  }
  if (!isImportQueueClearStatus(status)) {
    throw new Error('Invalid import queue clear status');
  }
  return {
    id: requiredString(value.id, 'id'),
    queueName,
    action,
    status,
    messageCode: requiredString(value.messageCode, 'messageCode'),
    requestedAt: requiredString(value.requestedAt, 'requestedAt'),
    startedAt: value.startedAt === null ? null : requiredString(value.startedAt, 'startedAt'),
    finishedAt: value.finishedAt === null ? null : requiredString(value.finishedAt, 'finishedAt'),
    updatedAt: requiredString(value.updatedAt, 'updatedAt')
  };
}

function operationFromEnvelope(value: unknown): ImportQueueClearOperation {
  if (
    !isObject(value)
    || value.ok !== true
    || !isObject(value.data)
    || !('operation' in value.data)
  ) {
    const message = isObject(value)
      && isObject(value.error)
      && typeof value.error.message === 'string'
      ? value.error.message
      : '导入队列返回了无效响应';
    throw new Error(message);
  }
  return parseImportQueueClearOperation(value.data.operation);
}

export async function requestImportQueueClear(signal?: AbortSignal): Promise<ImportQueueClearOperation> {
  const response = await fetch('/api/import-tasks/clear', {
    method: 'POST',
    signal
  });
  const payload: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    const message = isObject(payload)
      && isObject(payload.error)
      && typeof payload.error.message === 'string'
      ? payload.error.message
      : '清理导入队列失败';
    throw new Error(message);
  }
  return operationFromEnvelope(payload);
}

export async function getImportQueueClearOperation(
  operationId: string,
  signal?: AbortSignal
): Promise<ImportQueueClearOperation> {
  const response = await fetch(
    `/api/system/queue-operations/${encodeURIComponent(operationId)}`,
    { cache: 'no-store', signal }
  );
  const payload: unknown = await response.json().catch(() => null);
  if (!response.ok) throw new Error('清理导入队列失败');
  return operationFromEnvelope(payload);
}

function waitForNextPoll(signal: AbortSignal | undefined, intervalMs: number): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) {
      reject(signal.reason);
      return;
    }
    const handleAbort = () => {
      window.clearTimeout(timer);
      reject(signal?.reason);
    };
    const timer = window.setTimeout(() => {
      signal?.removeEventListener('abort', handleAbort);
      resolve();
    }, intervalMs);
    signal?.addEventListener('abort', handleAbort, { once: true });
  });
}

export async function waitForImportQueueClear(
  operationId: string,
  options: {
    signal?: AbortSignal;
    intervalMs?: number;
    onUpdate?: (operation: ImportQueueClearOperation) => void;
  } = {}
): Promise<ImportQueueClearOperation> {
  while (true) {
    const operation = await getImportQueueClearOperation(operationId, options.signal);
    options.onUpdate?.(operation);
    if (operation.status === 'completed' || operation.status === 'failed') {
      return operation;
    }
    await waitForNextPoll(options.signal, options.intervalMs ?? 1_000);
  }
}
