import type { LibraryNavigationSource } from '../model/library-source-navigation';
import type { LibraryFilterSchema } from '../model/filter-schema';
import { fetchLibraryFilterSchema } from './filtering';

function requiredString(value: unknown, field: string): string {
  if (typeof value !== 'string' || value.trim() === '') {
    throw new Error(`LIBRARY_NAVIGATION_SOURCE_INVALID_${field}`);
  }
  return value;
}

export function libraryNavigationSourcesFromFilterSchema(schema: LibraryFilterSchema): LibraryNavigationSource[] {
  const libraryField = schema.fields.find((field) => field.key === 'library');
  if (!libraryField) {
    throw new Error('LIBRARY_NAVIGATION_SOURCES_INVALID');
  }
  return (libraryField.options ?? []).map((option) => {
    return {
      id: requiredString(option.value, 'id'),
      name: requiredString(option.label, 'name')
    };
  });
}

export async function fetchLibraryNavigationSources(signal?: AbortSignal): Promise<LibraryNavigationSource[]> {
  return libraryNavigationSourcesFromFilterSchema(await fetchLibraryFilterSchema(signal));
}
