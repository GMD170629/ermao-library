import assert from 'node:assert/strict';
import test from 'node:test';
import {
  fetchLibraryFilterOptions,
  parseLibraryFilterOptionPage,
  parseLibraryFilterSchema
} from './filtering';

test('parses filter schema option sources without unchecked casts', () => {
  const schema = parseLibraryFilterSchema({
    fields: [{
      key: 'author',
      label: '作者',
      group: '图书元数据',
      type: 'select',
      operators: ['equals'],
      optionSource: 'authors',
      allowCustom: true,
      options: []
    }],
    maxConditions: 30
  });

  assert.equal(schema.fields[0]?.optionSource, 'authors');
  assert.equal(schema.fields[0]?.allowCustom, true);
  assert.equal(schema.maxConditions, 30);
});

test('rejects malformed async filter option counts', () => {
  assert.throws(
    () => parseLibraryFilterOptionPage({
      source: 'authors',
      query: '林',
      options: [{ value: '林川', label: '林川', count: '1' }],
      hasMore: false,
      indexReady: true
    }),
    /Invalid library filter field/
  );
});

test('requests at most the default 20 async filter suggestions', async () => {
  const originalFetch = globalThis.fetch;
  let requestedUrl = '';
  globalThis.fetch = async (input: string | URL | Request) => {
    requestedUrl = String(input);
    return new Response(JSON.stringify({
      ok: true,
      data: {
        source: 'series',
        query: '星海',
        options: [{ value: '星海系列', label: '星海系列', count: 2 }],
        hasMore: false,
        indexReady: true
      }
    }), { status: 200, headers: { 'content-type': 'application/json' } });
  };
  try {
    const page = await fetchLibraryFilterOptions('series', '星海');
    assert.equal(page.options[0]?.count, 2);
    assert.match(requestedUrl, /source=series/);
    assert.match(requestedUrl, /limit=20/);
  } finally {
    globalThis.fetch = originalFetch;
  }
});
