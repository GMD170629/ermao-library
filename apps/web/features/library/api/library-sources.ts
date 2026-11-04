import type { LibraryNavigationSource } from '../model/library-source-navigation';
import { readLibraryQueryResponse } from './filtering';

function requiredString(value: unknown, field: string): string {
  if (typeof value !== 'string' || value.trim() === '') {
    throw new Error(`LIBRARY_NAVIGATION_SOURCE_INVALID_${field}`);
  }
  return value;
}

export function parseLibraryNavigationSources(payload: unknown): LibraryNavigationSource[] {
  if (!payload || typeof payload !== 'object' || !('sources' in payload) || !Array.isArray(payload.sources)) {
    throw new Error('LIBRARY_NAVIGATION_SOURCES_INVALID');
  }
  return payload.sources.map((source: unknown) => {
    if (!source || typeof source !== 'object' || !('id' in source) || !('name' in source)) {
      throw new Error('LIBRARY_NAVIGATION_SOURCES_INVALID');
    }
    return {
      id: requiredString(source.id, 'id'),
      name: requiredString(source.name, 'name')
    };
  });
}

export async function fetchLibraryNavigationSources(signal?: AbortSignal): Promise<LibraryNavigationSource[]> {
  const response = await fetch('/api/library/navigation-sources', {
    cache: 'no-store', credentials: 'same-origin', signal
  });
  return parseLibraryNavigationSources(await readLibraryQueryResponse(response, '读取筛选维度失败'));
}
