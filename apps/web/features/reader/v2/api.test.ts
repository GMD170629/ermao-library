import assert from 'node:assert/strict';
import test from 'node:test';
import { wireLocationToDomain } from './api';

test('comic wire locations carry their own volume identity into the domain', () => {
  assert.deepEqual(
    wireLocationToDomain({ type: 'comic', volumeId: 'volume-2', pageIndex: 7 }),
    { kind: 'comic', volumeId: 'volume-2', pageIndex: 7 }
  );
});
