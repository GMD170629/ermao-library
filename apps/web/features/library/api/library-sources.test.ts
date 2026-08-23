import assert from 'node:assert/strict';
import test from 'node:test';
import { libraryNavigationSourcesFromFilterSchema } from './library-sources';

function schemaWithLibraries(options: Array<{ value: string; label: string }>) {
  return {
    fields: [{
      key: 'library',
      label: '书库',
      group: '来源与归档',
      type: 'select' as const,
      operators: ['equals'],
      options
    }],
    maxConditions: 30
  };
}

test('library navigation sources parse the scoped API projection', () => {
  assert.deepEqual(libraryNavigationSourcesFromFilterSchema(schemaWithLibraries([
    { value: 'library-1', label: '主书库' },
    { value: 'library-2', label: '漫画库' }
  ])), [
    { id: 'library-1', name: '主书库' },
    { id: 'library-2', name: '漫画库' }
  ]);
});

test('library navigation sources reject malformed entries', () => {
  assert.throws(
    () => libraryNavigationSourcesFromFilterSchema(schemaWithLibraries([{ value: '', label: '主书库' }])),
    /LIBRARY_NAVIGATION_SOURCE_INVALID_id/
  );
});
