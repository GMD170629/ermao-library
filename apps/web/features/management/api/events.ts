export type ManagementEvent = {
  id: string;
  level: string;
  source: string;
  actorType: string;
  action: string;
  targetType?: string | null;
  targetId?: string | null;
  message: string;
  metadata: Record<string, unknown>;
  createdAt: string;
};

export type EventStorage = {
  sizeBytes: number;
  maxBytes: number;
  lastPrunedAt?: string | null;
};

export type ManagementEventsPage = {
  events: ManagementEvent[];
  total: number;
  totalPages: number;
  storage: EventStorage;
};

type JsonObject = Record<string, unknown>;

function isObject(value: unknown): value is JsonObject {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function requiredString(value: unknown, field: string): string {
  if (typeof value !== 'string') throw new Error(`Invalid management events field: ${field}`);
  return value;
}

function nullableString(value: unknown, field: string): string | null | undefined {
  if (value === undefined) return undefined;
  if (value === null) return null;
  return requiredString(value, field);
}

function requiredNumber(value: unknown, field: string): number {
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    throw new Error(`Invalid management events field: ${field}`);
  }
  return value;
}

function parseStorage(value: unknown): EventStorage {
  if (!isObject(value)) throw new Error('Invalid management event storage');
  const lastPrunedAt = nullableString(value.lastPrunedAt, 'storage.lastPrunedAt');
  return {
    sizeBytes: requiredNumber(value.sizeBytes, 'storage.sizeBytes'),
    maxBytes: requiredNumber(value.maxBytes, 'storage.maxBytes'),
    ...(lastPrunedAt === undefined ? {} : { lastPrunedAt })
  };
}

function parseEvent(value: unknown): ManagementEvent {
  if (!isObject(value) || !isObject(value.metadata)) {
    throw new Error('Invalid management event');
  }
  return {
    id: requiredString(value.id, 'event.id'),
    level: requiredString(value.level, 'event.level'),
    source: requiredString(value.source, 'event.source'),
    actorType: requiredString(value.actorType, 'event.actorType'),
    action: requiredString(value.action, 'event.action'),
    targetType: nullableString(value.targetType, 'event.targetType'),
    targetId: nullableString(value.targetId, 'event.targetId'),
    message: requiredString(value.message, 'event.message'),
    metadata: value.metadata,
    createdAt: requiredString(value.createdAt, 'event.createdAt')
  };
}

async function readData(response: Response, fallback: string): Promise<unknown> {
  const payload: unknown = await response.json().catch(() => null);
  if (!response.ok || !isObject(payload) || payload.ok !== true || !('data' in payload)) {
    const message = isObject(payload) && isObject(payload.error) && typeof payload.error.message === 'string'
      ? payload.error.message
      : fallback;
    throw new Error(message);
  }
  return payload.data;
}

export async function fetchManagementEvents(params: URLSearchParams): Promise<ManagementEventsPage> {
  const data = await readData(
    await fetch(`/api/management/events?${params}`, {
      cache: 'no-store',
      credentials: 'same-origin'
    }),
    '读取日志失败'
  );
  if (!isObject(data) || !Array.isArray(data.events)) {
    throw new Error('Invalid management events response');
  }
  return {
    events: data.events.map(parseEvent),
    total: requiredNumber(data.total, 'total'),
    totalPages: requiredNumber(data.totalPages, 'totalPages'),
    storage: parseStorage(data.storage)
  };
}

export async function clearManagementEvents(): Promise<number> {
  const data = await readData(
    await fetch('/api/management/events', {
      method: 'DELETE',
      credentials: 'same-origin'
    }),
    '清理日志失败'
  );
  if (!isObject(data)) throw new Error('Invalid clear-events response');
  return requiredNumber(data.deleted, 'deleted');
}

export async function updateSystemLogLimit(maxBytes: number): Promise<EventStorage> {
  const data = await readData(
    await fetch('/api/system/log-settings', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'same-origin',
      body: JSON.stringify({ maxBytes })
    }),
    '保存日志容量失败'
  );
  if (!isObject(data)) throw new Error('Invalid log-settings response');
  return parseStorage(data.storage);
}
