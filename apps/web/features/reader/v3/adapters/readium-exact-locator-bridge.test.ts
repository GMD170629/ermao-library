import assert from 'node:assert/strict';
import test from 'node:test';
import { resolveReadiumDocumentResourceHref } from './readium-resource-identity';

const resourceHrefs = [
  'text/part0008_split_011.html',
  'text/part0008_split_021.html',
  'text/part0011.html'
];

test('exact locator capture uses the visible Readium document resource instead of a stale locator href', () => {
  assert.equal(resolveReadiumDocumentResourceHref(
    [
      'blob:http://localhost:3000/3a0e0c45-7d0b-4318-b268-caf21083e5de',
      'http://localhost:3000/api/reader/publications/book/content/text/part0008_split_021.html'
    ],
    resourceHrefs,
    'text/part0011.html'
  ), 'text/part0008_split_021.html');
});

test('exact locator capture keeps the current href when the document identity is unavailable', () => {
  assert.equal(resolveReadiumDocumentResourceHref(
    ['about:blank'],
    resourceHrefs,
    'text/part0011.html'
  ), 'text/part0011.html');
});
