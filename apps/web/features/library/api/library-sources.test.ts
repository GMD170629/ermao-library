import assert from 'node:assert/strict';
import test from 'node:test';
import { fetchLibraryNavigationSources, parseLibraryNavigationSources } from './library-sources';

function schemaWithLibraries(options: Array<{ value: string; label: string }>) {
  return { sources: options.map((option) => ({ id: option.value, name: option.label })) };
}

test('library navigation sources parse the scoped API projection', () => {
  assert.deepEqual(parseLibraryNavigationSources(schemaWithLibraries([
    { value: 'library-1', label: '主书库' },
    { value: 'library-2', label: '漫画库' }
  ])), [
    { id: 'library-1', name: '主书库' },
    { id: 'library-2', name: '漫画库' }
  ]);
});

test('library navigation sources reject malformed entries', () => {
  assert.throws(
    () => parseLibraryNavigationSources(schemaWithLibraries([{ value: '', label: '主书库' }])),
    /LIBRARY_NAVIGATION_SOURCE_INVALID_id/
  );
});

test('navigation fetch does not request catalog filter statistics', async () => {
  const original = globalThis.fetch;
  const requests: string[] = [];
  globalThis.fetch = async (url) => {
    requests.push(String(url));
    return Response.json({ ok: true, data: { sources: [{ id: 'library-1', name: '主书库' }] } });
  };
  try {
    assert.deepEqual(await fetchLibraryNavigationSources(), [{ id: 'library-1', name: '主书库' }]);
    assert.deepEqual(requests, ['/api/library/navigation-sources']);
  } finally { globalThis.fetch = original; }
});
