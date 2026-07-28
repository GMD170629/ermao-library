import assert from 'node:assert/strict';
import test from 'node:test';
import {
  DEFAULT_LIBRARY_SORT_PREFERENCE,
  librarySortPreferenceFromRoute,
  parseLibrarySortPreference,
  parseLibrarySortPreferenceValue,
  resolveLibrarySortPreference
} from './library-sort-preference';

test('new library sessions default to most recently added books first', () => {
  assert.deepEqual(
    resolveLibrarySortPreference({ route: null, account: null, device: null }),
    { sort: 'recent_import', direction: 'desc' }
  );
  assert.deepEqual(DEFAULT_LIBRARY_SORT_PREFERENCE, {
    sort: 'recent_import',
    direction: 'desc'
  });
});

test('a saved account sort is restored before the device fallback', () => {
  assert.deepEqual(
    resolveLibrarySortPreference({
      route: null,
      account: parseLibrarySortPreference('title', 'desc'),
      device: parseLibrarySortPreference('author', 'asc')
    }),
    { sort: 'title', direction: 'desc' }
  );
});

test('an explicit route sort takes precedence over remembered state', () => {
  assert.deepEqual(
    resolveLibrarySortPreference({
      route: librarySortPreferenceFromRoute('recent_read', null),
      account: parseLibrarySortPreference('title', 'asc'),
      device: null
    }),
    { sort: 'recent_read', direction: 'desc' }
  );
});

test('invalid remembered values are ignored instead of creating an unsupported query', () => {
  assert.equal(parseLibrarySortPreference('unknown', 'desc'), null);
  assert.equal(parseLibrarySortPreferenceValue({ sort: 'title', direction: 'sideways' })?.direction, 'asc');
  assert.equal(parseLibrarySortPreferenceValue('title'), null);
});
