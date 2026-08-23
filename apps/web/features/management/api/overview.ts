export type ManagementSystemEvent = {
  id: string;
  level: string;
  source: string;
  action: string;
  message: string;
  createdAt: string;
};

export type ManagementOverview = {
  cards: Record<string, number>;
  checks: Record<string, { status: string; message: string }>;
  recentEvents: ManagementSystemEvent[];
};

type JsonObject = Record<string, unknown>;

function isObject(value: unknown): value is JsonObject {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function requiredString(value: unknown, field: string): string {
  if (typeof value !== 'string') throw new Error(`Invalid management overview field: ${field}`);
  return value;
}

export function parseManagementOverview(value: unknown): ManagementOverview {
  if (!isObject(value) || !isObject(value.cards) || !isObject(value.checks) || !Array.isArray(value.recentEvents)) {
    throw new Error('Invalid management overview response');
  }
  const cards = Object.fromEntries(Object.entries(value.cards).map(([key, count]) => {
    if (typeof count !== 'number' || !Number.isFinite(count)) {
      throw new Error(`Invalid management overview field: cards.${key}`);
    }
    return [key, count];
  }));
  const checks = Object.fromEntries(Object.entries(value.checks).map(([key, check]) => {
    if (!isObject(check)) throw new Error(`Invalid management overview field: checks.${key}`);
    return [key, {
      status: requiredString(check.status, `checks.${key}.status`),
      message: requiredString(check.message, `checks.${key}.message`)
    }];
  }));
  return {
    cards,
    checks,
    recentEvents: value.recentEvents.map((event) => {
      if (!isObject(event)) throw new Error('Invalid management overview event');
      return {
        id: requiredString(event.id, 'event.id'),
        level: requiredString(event.level, 'event.level'),
        source: requiredString(event.source, 'event.source'),
        action: requiredString(event.action, 'event.action'),
        message: requiredString(event.message, 'event.message'),
        createdAt: requiredString(event.createdAt, 'event.createdAt')
      };
    })
  };
}

export async function fetchManagementOverview(signal?: AbortSignal): Promise<ManagementOverview> {
  const response = await fetch('/api/management/overview', {
    cache: 'no-store',
    credentials: 'same-origin',
    signal
  });
  const payload: unknown = await response.json().catch(() => null);
  if (!response.ok || !isObject(payload) || payload.ok !== true || !('data' in payload)) {
    const message = isObject(payload) && isObject(payload.error) && typeof payload.error.message === 'string'
      ? payload.error.message
      : '读取管理概览失败';
    throw new Error(message);
  }
  return parseManagementOverview(payload.data);
}
