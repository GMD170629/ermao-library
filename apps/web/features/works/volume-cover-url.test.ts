import assert from 'node:assert/strict';
import test from 'node:test';
import { smallVolumeCoverUrl } from './volume-cover-url';

test('adds the small variant to a volume cover URL with existing query parameters', () => {
  assert.equal(
    smallVolumeCoverUrl('volume-1', '/api/volumes/volume-1/cover?volumeId=volume-1&v=7'),
    '/api/volumes/volume-1/cover?volumeId=volume-1&v=7&size=small'
  );
});

test('replaces an existing volume cover size and preserves a fragment', () => {
  assert.equal(
    smallVolumeCoverUrl('volume-1', '/api/volumes/volume-1/cover?size=large#preview'),
    '/api/volumes/volume-1/cover?size=small#preview'
  );
});

test('builds the volume cover endpoint when the response omits its URL', () => {
  assert.equal(
    smallVolumeCoverUrl('volume/1', ''),
    '/api/volumes/volume%2F1/cover?size=small'
  );
});
