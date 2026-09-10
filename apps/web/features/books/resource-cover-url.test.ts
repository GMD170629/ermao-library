import assert from 'node:assert/strict';
import test from 'node:test';
import { smallResourceCoverUrl } from './resource-cover-url';

test('adds the small variant to a resource cover URL with existing query parameters', () => {
  assert.equal(
    smallResourceCoverUrl('/api/resources/resource-1/cover?resourceId=resource-1&v=7'),
    '/api/resources/resource-1/cover?resourceId=resource-1&v=7&size=small'
  );
});

test('replaces an existing resource cover size and preserves a fragment', () => {
  assert.equal(
    smallResourceCoverUrl('/api/resources/resource-1/cover?size=large#preview'),
    '/api/resources/resource-1/cover?size=small#preview'
  );
});

test('keeps a missing resource cover empty', () => {
  assert.equal(
    smallResourceCoverUrl(''),
    ''
  );
});
