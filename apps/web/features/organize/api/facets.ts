export type LibraryFacetKind = 'AUTHOR' | 'TAG' | 'SERIES';

export type LibraryFacet = {
  id: string;
  kind: LibraryFacetKind;
  name: string;
  normalizedName: string;
  aliases: string[];
  bookCount: number;
  updatedAt: string;
};

export type LibraryFacetPage = {
  facets: LibraryFacet[];
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
  if (typeof value !== 'string') throw new Error(`Invalid library facet field: ${field}`);
  return value;
}

function requiredNumber(value: unknown, field: string): number {
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    throw new Error(`Invalid library facet field: ${field}`);
  }
  return value;
}

function parseKind(value: unknown): LibraryFacetKind {
  if (value !== 'AUTHOR' && value !== 'TAG' && value !== 'SERIES') {
    throw new Error('Invalid library facet kind');
  }
  return value;
}

function parseFacet(value: unknown): LibraryFacet {
  if (!isObject(value) || !Array.isArray(value.aliases)) {
    throw new Error('Invalid library facet');
  }
  return {
    id: requiredString(value.id, 'id'),
    kind: parseKind(value.kind),
    name: requiredString(value.name, 'name'),
    normalizedName: requiredString(value.normalizedName, 'normalizedName'),
    aliases: value.aliases.map((alias) => requiredString(alias, 'alias')),
    bookCount: requiredNumber(value.bookCount, 'bookCount'),
    updatedAt: requiredString(value.updatedAt, 'updatedAt')
  };
}

export function parseLibraryFacetPage(value: unknown): LibraryFacetPage {
  if (!isObject(value) || !Array.isArray(value.facets)) {
    throw new Error('Invalid library facet response');
  }
  return {
    facets: value.facets.map(parseFacet),
    page: requiredNumber(value.page, 'page'),
    pageSize: requiredNumber(value.pageSize, 'pageSize'),
    total: requiredNumber(value.total, 'total'),
    totalPages: requiredNumber(value.totalPages, 'totalPages')
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

export async function fetchLibraryFacets(options: {
  kind: LibraryFacetKind;
  page: number;
  pageSize: number;
  search?: string;
  signal?: AbortSignal;
}): Promise<LibraryFacetPage> {
  const params = new URLSearchParams({
    kind: options.kind,
    page: String(options.page),
    pageSize: String(options.pageSize)
  });
  if (options.search?.trim()) params.set('search', options.search.trim());
  const response = await fetch(`/api/library/facets?${params}`, {
    cache: 'no-store',
    credentials: 'same-origin',
    signal: options.signal
  });
  return parseLibraryFacetPage(await readData(response, '读取分类失败'));
}

export async function renameLibraryFacet(facetId: string, name: string): Promise<void> {
  const response = await fetch(`/api/library/facets/${encodeURIComponent(facetId)}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'same-origin',
    body: JSON.stringify({ name })
  });
  await readData(response, '重命名失败');
}

export async function mergeLibraryFacets(input: {
  kind: LibraryFacetKind;
  targetId: string;
  sourceIds: string[];
}): Promise<void> {
  const response = await fetch('/api/library/facets/merge', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'same-origin',
    body: JSON.stringify(input)
  });
  await readData(response, '合并分类失败');
}

export async function deleteLibraryFacet(facetId: string): Promise<void> {
  const response = await fetch(`/api/library/facets/${encodeURIComponent(facetId)}`, {
    method: 'DELETE',
    credentials: 'same-origin'
  });
  await readData(response, '删除分类失败');
}
