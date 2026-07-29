export type LibraryGroupingKind = 'SERIES' | 'AUTHOR';

export type LibraryGrouping = {
  id: string;
  name: string;
  bookCount: number;
  updatedAt: string;
};

export type LibraryGroupingPage = {
  groups: LibraryGrouping[];
  page: number;
  pageSize: number;
  total: number;
  totalPages: number;
};

type JsonObject = Record<string, unknown>;

function isObject(value: unknown): value is JsonObject {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function requiredString(value: unknown, field: string): string {
  if (typeof value !== 'string') throw new Error(`Invalid library grouping field: ${field}`);
  return value;
}

function requiredNumber(value: unknown, field: string): number {
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    throw new Error(`Invalid library grouping field: ${field}`);
  }
  return value;
}

export function parseLibraryGroupingPage(value: unknown): LibraryGroupingPage {
  if (!isObject(value) || !Array.isArray(value.groups)) {
    throw new Error('Invalid library grouping response');
  }
  return {
    groups: value.groups.map((group) => {
      if (!isObject(group)) throw new Error('Invalid library grouping');
      return {
        id: requiredString(group.id, 'id'),
        name: requiredString(group.name, 'name'),
        bookCount: requiredNumber(group.bookCount, 'bookCount'),
        updatedAt: requiredString(group.updatedAt, 'updatedAt')
      };
    }),
    page: requiredNumber(value.page, 'page'),
    pageSize: requiredNumber(value.pageSize, 'pageSize'),
    total: requiredNumber(value.total, 'total'),
    totalPages: requiredNumber(value.totalPages, 'totalPages')
  };
}

export async function fetchLibraryGroupings(
  options: {
    kind: LibraryGroupingKind;
    page: number;
    pageSize: number;
    search?: string;
    signal?: AbortSignal;
  }
): Promise<LibraryGroupingPage> {
  const params = new URLSearchParams({
    kind: options.kind,
    page: String(options.page),
    pageSize: String(options.pageSize)
  });
  if (options.search?.trim()) params.set('search', options.search.trim());

  const response = await fetch(`/api/library/groupings?${params}`, {
    signal: options.signal
  });
  const payload: unknown = await response.json().catch(() => null);
  if (!isObject(payload) || payload.ok !== true || !('data' in payload)) {
    const message = isObject(payload) && isObject(payload.error) && typeof payload.error.message === 'string'
      ? payload.error.message
      : '读取书库分组失败';
    throw new Error(message);
  }
  if (!response.ok) throw new Error('读取书库分组失败');
  return parseLibraryGroupingPage(payload.data);
}
