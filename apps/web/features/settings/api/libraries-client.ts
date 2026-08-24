export type DirectoryNode = {
  name: string;
  path: string;
  readable: boolean;
  error?: string | null;
  children: Array<{ name: string; path: string; readable: boolean }>;
};

export class LibraryApiError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'LibraryApiError';
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function parseDirectoryNode(value: unknown): DirectoryNode | null {
  if (!isRecord(value) || typeof value.name !== 'string'
    || typeof value.path !== 'string' || typeof value.readable !== 'boolean'
    || !Array.isArray(value.children)) return null;
  const children = value.children.map((child) => {
    if (!isRecord(child) || typeof child.name !== 'string'
      || typeof child.path !== 'string' || typeof child.readable !== 'boolean') return null;
    return { name: child.name, path: child.path, readable: child.readable };
  });
  if (children.some((child) => child === null)) return null;
  return {
    name: value.name,
    path: value.path,
    readable: value.readable,
    error: typeof value.error === 'string' || value.error === null ? value.error : null,
    children: children.filter((child) => child !== null)
  };
}

export async function loadLibraryDirectory(
  path?: string,
  signal?: AbortSignal
): Promise<DirectoryNode> {
  const query = path ? `?path=${encodeURIComponent(path)}` : '';
  const response = await fetch(`/api/libraries/tree${query}`, {
    cache: 'no-store', credentials: 'same-origin', signal
  });
  const payload: unknown = await response.json();
  const data = isRecord(payload) && isRecord(payload.data) ? payload.data : null;
  const node = parseDirectoryNode(data?.node);
  if (!response.ok || !isRecord(payload) || payload.ok !== true || !node) {
    const message = isRecord(payload) && isRecord(payload.error)
      && typeof payload.error.message === 'string'
      ? payload.error.message : '读取目录树失败';
    throw new Error(message);
  }
  return node;
}

export async function deleteLibrary(libraryId: string): Promise<void> {
  const response = await fetch(`/api/libraries/${encodeURIComponent(libraryId)}`, {
    method: 'DELETE',
    credentials: 'same-origin'
  });
  const payload: unknown = await response.json().catch(() => null);
  const deleted = isRecord(payload) && isRecord(payload.data)
    ? payload.data.deleted : null;
  if (!response.ok || !isRecord(payload) || payload.ok !== true || deleted !== true) {
    const message = isRecord(payload) && isRecord(payload.error)
      && typeof payload.error.message === 'string'
      ? payload.error.message : '删除书库失败';
    throw new LibraryApiError(message);
  }
}
